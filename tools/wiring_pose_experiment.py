"""Run the bounded three-component wiring-pose experiment without deployment.

Use backend/.venv for audit/evaluation and .venv-training for train/export.
Every subprocess and artifact is local. No camera, server, UI or model registry
is changed. Rerunning `run` resumes completed stages in its experiment directory.
"""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import yaml

# Export helpers must fail on a missing dependency, never upgrade this environment.
os.environ["YOLO_AUTOINSTALL"] = "false"
os.environ["YOLO_OFFLINE"] = "true"

from wiring_pose_data import ROOT, SPECS, prepare, complete_support_snapshot, build_paired_datasets, digest, write_json


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit_finetune_learning_rates(rows, maximum):
    """Fail if a scratch-training warmup silently exceeds the fine-tune LR."""
    groups=sorted({key for row in rows for key in row if key.startswith("lr/pg")})
    if not groups or not rows:raise ValueError("missing optimizer learning-rate evidence")
    maxima={key:max(float(row[key]) for row in rows) for key in groups}
    if any(not math.isfinite(float(row[key])) or not 0.<=float(row[key])<=maximum*1.001
           for row in rows for key in groups):
        raise ValueError("optimizer learning rate exceeded fine-tune budget")
    return maxima


def baseline(out):
    from wiring_pose_evaluation import configure_snapshot, evaluate_if_needed, score
    complete_support_snapshot(out)
    config=configure_snapshot(out)
    manifest=load(out/"manifest.json")
    selected={}
    for component,spec in manifest["components"].items():
        if (out/"blocked"/(component+".json")).exists():
            selected[component]={"name":spec["active"],**spec["models"][spec["active"]],"selection_scope":"quarantined; production retained without accuracy ranking"}
            continue
        reports=[]
        for name,model in spec["models"].items():
            dest=out/"evaluations"/component/(name+".json")
            report=evaluate_if_needed(out,component,out/model["onnx"],name,config)
            reports.append(report)
            print(component,name,report["summary"],flush=True)
        winner=min(reports,key=score)
        selected[component]={"name":winner["name"],**spec["models"][winner["name"]],"selection_key":list(score(winner))}
    write_json(out/"baseline-selection.json",selected)


def train_one(out,component,arm,seed,epochs=None,*,artifact_root=None,common_budget=None):
    # Authorization was supplied by the user for this project; CLI keeps an explicit flag.
    if (out/"blocked"/(component+".json")).exists():
        raise RuntimeError(f"{component} quarantined by semantic audit; training is forbidden")
    script_sha256=digest(Path(__file__))
    import torch
    import ultralytics
    from ultralytics import YOLO
    if not torch.cuda.is_available():
        raise RuntimeError("training requires CUDA; refusing silent CPU training")
    manifest=load(out/"manifest.json")
    spec=manifest["components"][component]
    selection=load(out/"baseline-selection.json")[component]
    checkpoint=out/selection["checkpoint"]
    if digest(checkpoint)!=selection["checkpoint_sha256"]:
        raise ValueError("initial checkpoint changed")
    paired=load(out/"datasets"/component/"paired.json")
    saved=yaml.safe_load((out/f"snapshot/args/{component}.yaml").read_text(encoding="utf-8"))
    name=f"{component}-{arm}-seed{seed}"
    artifact_root=out if artifact_root is None else artifact_root
    destination=artifact_root/"training"/name
    if destination.exists():
        raise ValueError(f"refusing to replace an existing training run: {destination}")
    # Reproduction uses the same LR-schedule horizon, stopping at the common budget.
    kwargs={"data":paired[arm]["data"],"epochs":spec["epochs"] if seed or common_budget else (epochs or spec["epochs"]),"imgsz":spec["input_size"],
        "batch":4,"device":"0","workers":2,"optimizer":"AdamW","lr0":.0001,
        "lrf":.01,"warmup_epochs":3.,"warmup_bias_lr":0.,"weight_decay":.0005,
        "patience":8 if seed==0 and not common_budget else 0,"seed":seed,"deterministic":True,
        "project":str(artifact_root/"training"),"name":name,"exist_ok":False,"resume":False,
        "save_period":1,"amp":True,"cache":False,"plots":True,
        # Paired datasets already contain exactly the same mild affine transforms.
        "degrees":0.,"translate":0.,"scale":0.,"shear":0.,"perspective":0.,
        "fliplr":0.,"flipud":0.,"mosaic":0.,"mixup":0.,"copy_paste":0.,
        "erasing":0.,"hsv_h":0.,"hsv_s":0.,"hsv_v":0.}
    started=time.time()
    model=YOLO(str(checkpoint))
    saved = {**saved, **(model.ckpt.get("train_args", {}) if model.ckpt else {})}
    for key in ("box","cls","dfl","pose","kobj"):
        if key in saved:kwargs[key]=saved[key]
    loader_seed=6148914691236517204+seed
    def seed_training_loader(trainer):
        # Ultralytics 8.4.115 hardcodes its DataLoader generator independently of args.seed.
        # Offline A/B augmentation is deterministic, so changing args.seed alone was a no-op.
        if seed:
            loader=trainer.train_loader
            loader.generator.manual_seed(loader_seed)
            if hasattr(loader.sampler,"generator"):loader.sampler.generator=loader.generator
            loader.reset()
        write_json(Path(trainer.save_dir)/"sampler.json",{"requested_seed":seed,"effective_loader_seed":loader_seed,
            "reset_for_nonzero_seed":bool(seed),"installed_package_modified":False})
    model.add_callback("on_train_start",seed_training_loader)
    stop_budget=common_budget or (epochs if seed else None)
    if stop_budget:
        def stop_at_budget(trainer):
            if trainer.epoch+1>=stop_budget:trainer.stop=True
        model.add_callback("on_fit_epoch_end",stop_at_budget)
    model.train(**kwargs)
    actual=Path(model.trainer.save_dir).resolve()
    if actual!=destination.resolve():
        raise RuntimeError(f"unexpected training output: {actual}")
    if model.trainer.batch_size!=4:
        raise RuntimeError("training changed batch size; reject unequal-budget experiment")
    metrics=list(csv.DictReader((actual/"results.csv").open(encoding="utf-8")))
    lr_evidence=audit_finetune_learning_rates(metrics,kwargs["lr0"])
    write_json(actual/"complete.json",{"component":component,"arm":arm,"seed":seed,"args":kwargs,
        "initial_checkpoint":str(checkpoint),"initial_sha256":digest(checkpoint),"epochs_completed":len(metrics),
        "elapsed_s":time.time()-started,"environment":{"torch":torch.__version__,"ultralytics":ultralytics.__version__,
            "gpu":torch.cuda.get_device_name(0)},"dataset_counts":paired[arm],
        "installed_packages":{p.metadata["Name"]:p.version for p in importlib.metadata.distributions() if p.metadata["Name"]},
        "training_script_sha256":script_sha256,"epoch_budget":stop_budget or epochs or spec["epochs"],"loader_seed":loader_seed,
        "parent_manifest_sha256":digest(out/"manifest.json"),"parent_experiment":str(out),
        "fine_tune_warmup":"all parameter groups warm up from zero; never use the 0.1 scratch-training bias default",
        "observed_learning_rate_maxima":lr_evidence})


def choose_checkpoint(training:Path, budget:int):
    rows=list(csv.DictReader((training/"results.csv").open(encoding="utf-8")))[:budget]
    if not rows:raise ValueError("empty training metrics")
    # Same checkpoint-selection budget in A and B even if early stopping differs.
    index=max(range(len(rows)),key=lambda i:(float(rows[i]["metrics/mAP50-95(P)"]),-float(rows[i]["val/pose_loss"])))
    checkpoint=training/"weights"/f"epoch{index}.pt"
    if not checkpoint.exists():raise FileNotFoundError(checkpoint)
    return checkpoint,index+1


def export_candidate(out,component,arm,seed,budget,*,artifact_root=None,checkpoint_override=None):
    import cv2
    import numpy as np
    import torch
    from ultralytics import YOLO
    from ultralytics.data.augment import LetterBox
    name=f"{component}-{arm}-seed{seed}"
    artifact_root=out if artifact_root is None else artifact_root
    training=artifact_root/"training"/name
    if checkpoint_override is None:
        checkpoint,epoch=choose_checkpoint(training,budget)
    else:
        checkpoint=Path(checkpoint_override).resolve()
        if checkpoint.parent!=(training/"weights").resolve():raise ValueError("checkpoint is outside the requested training run")
        epoch=int(checkpoint.stem.removeprefix("epoch"))+1
        if not 1<=epoch<=budget:raise ValueError("checkpoint exceeds the common budget")
    destination=artifact_root/"candidates"/name
    destination.mkdir(parents=True,exist_ok=False)
    stable=destination/"model.pt"
    shutil.copy2(checkpoint,stable)
    size=SPECS[component]["size"]
    model=YOLO(str(stable))
    exported=Path(model.export(format="onnx",imgsz=size,dynamic=False,simplify=True,nms=False,opset=12,device="0"))
    if exported != destination/"model.onnx":
        shutil.copy2(exported,destination/"model.onnx")
    manifest=load(out/"manifest.json")
    rows=[r for r in manifest["components"][component]["records"] if r["split"]=="val" and not r.get("exclusion")]
    parity_rows=[next(r for r in rows if r["positive"])]
    parity_rows.append(next((r for r in rows if not r["positive"]),rows[-1]))
    network=YOLO(str(stable)).model.to("cuda").float().eval()
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    network.fuse(verbose=False)
    arrays={}
    with torch.inference_mode():
        for i,row in enumerate(parity_rows):
            image=cv2.imread(str(out/row["image"]))
            padded=LetterBox((size,size),auto=False,stride=32)(image=image)
            blob=np.ascontiguousarray(padded[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255.
            output=network(torch.from_numpy(blob).cuda())
            output=output[0] if isinstance(output,(tuple,list)) else output
            arrays[f"input_{i}"]=blob
            arrays[f"output_{i}"]=output.detach().cpu().numpy()
    np.savez_compressed(destination/"pt-parity.npz",**arrays)
    record={"component":component,"arm":arm,"seed":seed,"selected_epoch":epoch,"common_budget":budget,
            "name":name,"onnx":str((destination/"model.onnx").relative_to(artifact_root)),
            "checkpoint":str(stable.relative_to(artifact_root)),"onnx_sha256":digest(destination/"model.onnx"),
            "checkpoint_sha256":digest(stable),"parity_images":[r["key"] for r in parity_rows],
            "reference_format":"fused-fp32-tf32-disabled","parent_experiment":str(out),
            "selection_metric":"explicit_localization_objective" if checkpoint_override is not None else "pose_map_then_loss"}
    write_json(destination/"candidate.json",record)


def refresh_parity_reference(out,component,arm,seed):
    import numpy as np
    import torch
    from ultralytics import YOLO
    directory=out/"candidates"/f"{component}-{arm}-seed{seed}"
    candidate=load(directory/"candidate.json")
    if candidate.get("reference_format")=="fused-fp32-tf32-disabled":return
    previous=np.load(directory/"pt-parity.npz")
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    network=YOLO(str(directory/"model.pt")).model.to("cuda").float().eval()
    network.fuse(verbose=False)
    arrays={}
    with torch.inference_mode():
        for i in range(2):
            blob=previous[f"input_{i}"]
            result=network(torch.from_numpy(blob).cuda())
            result=result[0] if isinstance(result,(tuple,list)) else result
            arrays[f"input_{i}"]=blob
            arrays[f"output_{i}"]=result.cpu().numpy()
    np.savez_compressed(directory/"pt-reference-fp32.npz",**arrays)
    candidate["reference_format"]="fused-fp32-tf32-disabled"
    candidate["parity_file"]="pt-reference-fp32.npz"
    write_json(directory/"candidate.json",candidate)


def evaluate_candidates(out,component,seed):
    if (out/"blocked"/(component+".json")).exists():
        raise RuntimeError(f"{component}: quarantined labels cannot certify candidate localization")
    import numpy as np
    from wiring_pose_evaluation import configure_snapshot,evaluate_if_needed,RuntimeAdapter,gate,score,comparison_images,compare_tensors,compare_decoded_outputs
    config=configure_snapshot(out)
    manifest=load(out/"manifest.json")
    active=manifest["components"][component]["active"]
    production=evaluate_if_needed(out,component,out/manifest["components"][component]["models"][active]["onnx"],active,config)
    results=[]
    for metadata in sorted((out/"candidates").glob(f"{component}-*-seed{seed}/candidate.json")):
        candidate=load(metadata)
        name=candidate["name"]
        model=out/candidate["onnx"]
        dest=out/"evaluations"/component/(name+".json")
        report=evaluate_if_needed(out,component,model,name,config)
        parity_file=metadata.parent/"parity.json"
        parity_data=metadata.parent/candidate.get("parity_file","pt-parity.npz")
        parity_identity={"onnx":digest(model),"pt":digest(out/candidate["checkpoint"]),"inputs":digest(parity_data),"version":2}
        if not parity_file.exists() or load(parity_file).get("identity")!=parity_identity:
            adapter=RuntimeAdapter(out,component,model,config)
            try:
                import onnxruntime as ort
                strict=ort.InferenceSession(str(model),providers=[("CUDAExecutionProvider",{"use_tf32":0}),"CPUExecutionProvider"])
                if strict.get_providers()[0]!="CUDAExecutionProvider":raise RuntimeError("parity session fell back from CUDA")
                inputs=np.load(parity_data)
                checks=[]
                for i in range(2):
                    expected=inputs[f"output_{i}"]
                    actual=adapter.locator._session.run(None,{adapter.locator._input_name:inputs[f"input_{i}"]})[0]
                    exact=strict.run(None,{strict.get_inputs()[0].name:inputs[f"input_{i}"]})[0]
                    checks.append({"image":candidate["parity_images"][i],"strict_fp32":compare_tensors(expected,exact),
                        "production_tensor":compare_tensors(expected,actual),
                        "production_decoded":compare_decoded_outputs(expected,actual,adapter.locator._decode_options)})
                write_json(parity_file,{"passed":all(c["strict_fp32"]["allclose"] and c["production_decoded"]["passed"] for c in checks),
                    "rtol":.001,"atol":.01,"decoded_corner_atol_px":.5,"decoded_confidence_atol":.002,
                    "checks":checks,"identity":parity_identity,"reference_format":candidate.get("reference_format"),
                    "note":"Strict export check disables TF32 only in its private session; production CUDA is unchanged and checked at decoded coordinates."})
                del strict
            finally:adapter.close()
        qualification=gate(production,report)
        qualification["pt_onnx_parity"]=load(parity_file)["passed"]
        qualification["regression_gate_passed"] &= qualification["pt_onnx_parity"]
        qualification["comparison_images"]=comparison_images(out,component,production,report)
        write_json(metadata.parent/"gate.json",qualification)
        results.append((report,candidate,qualification))
        print(component,name,qualification,flush=True)
    if seed==0:
        # Prefer a qualified arm; if none qualifies still reproduce the least-bad arm.
        winner=min(results,key=lambda r:(not r[2]["regression_gate_passed"],*score(r[0])))
        write_json(out/"selection"/(component+".json"),{"candidate":winner[1],"gate":winner[2],
            "selection_scope":"validation_research_candidate_not_production_approval"})


def run_process(out,command,name):
    log=out/"logs"/(name+".log")
    log.parent.mkdir(parents=True,exist_ok=True)
    snapshot=out/"tool-versions"/name
    snapshot.mkdir(parents=True,exist_ok=True)
    for source in Path(__file__).parent.glob("wiring_pose_*.*"):
        if source.suffix not in (".py",".json"):continue
        target=snapshot/(source.stem+"-"+digest(source)[:12]+source.suffix)
        if not target.exists():shutil.copy2(source,target)
    with log.open("a",encoding="utf-8") as stream:
        stream.write("\nCOMMAND "+json.dumps(command,ensure_ascii=False)+"\n")
        stream.flush()
        result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,"PYTHONUNBUFFERED":"1","PYTHONUTF8":"1"})
    if result.returncode:
        raise RuntimeError(f"stage failed ({result.returncode}): {name}; see {log}")


def run(out):
    backend=str(ROOT/"backend/.venv/Scripts/python.exe")
    training=str(ROOT/".venv-training/Scripts/python.exe")
    script=str(Path(__file__).resolve())
    def stage(interpreter,action,*extra):
        run_process(out,[interpreter,script,action,"--out",str(out),*extra],action+"-"+"-".join(extra).replace("--",""))
    if not (out/"manifest.json").exists():prepare(out)
    if not (out/"baseline-selection.json").exists():stage(backend,"baseline")
    for component in ("pi","tft","hc"):
        if (out/"blocked"/(component+".json")).exists():
            print(f"{component}: semantic audit blocks fine-tuning; keep production model",flush=True)
            continue
        if not (out/"datasets"/component/"paired.json").exists():
            build_paired_datasets(out,component,load(out/"manifest.json"))
        for arm in ("A","B"):
            if not (out/"training"/f"{component}-{arm}-seed0/complete.json").exists():
                stage(training,"train","--component",component,"--arm",arm,"--seed","0","--accept-ultralytics-license")
        budget=min(load(out/"training"/f"{component}-{arm}-seed0/complete.json")["epochs_completed"] for arm in ("A","B"))
        for arm in ("A","B"):
            if not (out/"candidates"/f"{component}-{arm}-seed0/candidate.json").exists():
                stage(training,"export","--component",component,"--arm",arm,"--seed","0","--epochs",str(budget))
        if not (out/"selection"/(component+".json")).exists():stage(backend,"evaluate","--component",component,"--seed","0")
        arm=load(out/"selection"/(component+".json"))["candidate"]["arm"]
        if not (out/"training"/f"{component}-{arm}-seed1/complete.json").exists():
            stage(training,"train","--component",component,"--arm",arm,"--seed","1","--epochs",str(budget),"--accept-ultralytics-license")
        if not (out/"candidates"/f"{component}-{arm}-seed1/candidate.json").exists():
            stage(training,"export","--component",component,"--arm",arm,"--seed","1","--epochs",str(budget))
        stage(backend,"evaluate","--component",component,"--seed","1")
    blocked=[c for c in SPECS if (out/"blocked"/(c+".json")).exists()]
    write_json(out/"training-complete.json",{"complete":not blocked,"completed_components":[c for c in SPECS if c not in blocked],
        "blocked_components":blocked,"production_promotion":False})
    stage(backend,"negative-stress")
    stage(backend,"replay")
    stage(backend,"report")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","baseline","datasets","train","export","refresh-parity","evaluate","replay","report","freeze-replay","negative-stress","run"))
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--component",choices=tuple(SPECS))
    parser.add_argument("--arm",choices=("A","B"))
    parser.add_argument("--seed",type=int,default=0)
    parser.add_argument("--epochs",type=int)
    parser.add_argument("--accept-ultralytics-license",action="store_true")
    args=parser.parse_args()
    out=args.out.resolve()
    if args.action in ("train","run") and not args.accept_ultralytics_license:
        parser.error("training requires the existing project license confirmation flag")
    if args.action=="prepare":prepare(out)
    elif args.action=="baseline":baseline(out)
    elif args.action=="datasets":build_paired_datasets(out,args.component,load(out/"manifest.json"))
    elif args.action=="train":train_one(out,args.component,args.arm,args.seed,args.epochs)
    elif args.action=="export":export_candidate(out,args.component,args.arm,args.seed,args.epochs)
    elif args.action=="refresh-parity":refresh_parity_reference(out,args.component,args.arm,args.seed)
    elif args.action=="evaluate":evaluate_candidates(out,args.component,args.seed)
    elif args.action=="run":run(out)
    elif args.action in ("replay","report","freeze-replay","negative-stress"):
        from wiring_pose_replay import replay, report, freeze_sequences, negative_stress
        {"replay":replay,"report":report,"freeze-replay":freeze_sequences,"negative-stress":negative_stress}[args.action](out)


if __name__=="__main__":
    main()
