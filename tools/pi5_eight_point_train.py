"""Bounded eight-point trial on existing human labels, never runtime weights."""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import os
from pathlib import Path
import shutil
import sys
import time

import cv2
import numpy as np
import yaml

os.environ["YOLO_AUTOINSTALL"]="false"
os.environ["YOLO_OFFLINE"]="true"

from pi5_eight_point_check import load,summary,header_shape
from wiring_pose_data import digest,write_json,read_label
from wiring_pose_experiment import audit_finetune_learning_rates
from wiring_pose_evaluation import box_iou,j8_errors,stats


def dataset(out):
    manifest=load(out/"manifest.json")
    target=out/"training-data"
    if target.exists():raise FileExistsError(target)
    lineage=[]
    for row in manifest["records"]:
        split="val" if row["split"]=="val" else "train"
        if digest(out/row["image"])!=row["sha256"]:raise ValueError("input image hash changed")
        if row.get("label_sha256") and digest(out/row["label"])!=row["label_sha256"]:raise ValueError("label hash changed")
        for kind,key in (("images","image"),("labels","label")):
            source=out/row[key]
            dest=target/kind/split/source.name
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():raise ValueError("training basename collision")
            shutil.copy2(source,dest)
        lineage.append({"source":row["image"],"split":split,"sha256":row["sha256"],"positive":row["positive"]})
    data={"path":str(target),"train":"images/train","val":"images/val","kpt_shape":[8,3],
        "names":{0:"raspberry-pi-5"},"kpt_names":{0:manifest["keypoint_order"]}}
    (target/"data.yaml").write_text(yaml.safe_dump(data,sort_keys=False),encoding="utf-8")
    write_json(target/"lineage.json",lineage)


def train(out,seed,epochs):
    import torch
    import ultralytics
    from ultralytics import YOLO
    if not torch.cuda.is_available():raise RuntimeError("CUDA required")
    manifest=load(out/"manifest.json")
    checkpoint=Path(manifest["models"]["synth-negative-pilot"]["checkpoint"])
    dest=out/"training"/f"eight-seed{seed}"
    if dest.exists():raise FileExistsError(dest)
    model=YOLO(str(checkpoint))
    if model.model.yaml["kpt_shape"]!=[8,3]:raise ValueError("not an eight-point checkpoint")
    args={"data":str(out/"training-data/data.yaml"),"epochs":epochs,"imgsz":960,"batch":4,
        "device":"0","workers":2,"optimizer":"AdamW","lr0":.0001,"lrf":.01,
        "warmup_epochs":3.,"warmup_bias_lr":0.,"weight_decay":.0005,"patience":0,
        "seed":seed,"deterministic":True,"project":str(out/"training"),"name":f"eight-seed{seed}",
        "exist_ok":False,"resume":False,"save_period":1,"amp":True,"cache":False,"plots":False,
        "degrees":10.,"translate":.025,"scale":.12,"shear":0.,"perspective":0.,
        "fliplr":0.,"flipud":0.,"mosaic":0.,"mixup":0.,"copy_paste":0.,"cutmix":0.,
        "erasing":0.,"hsv_h":.005,"hsv_s":.2,"hsv_v":.15}
    for key in ("box","cls","dfl","pose","kobj"):
        args[key]=model.ckpt["train_args"][key]
    def seed_loader(trainer):
        value=6148914691236517204+seed
        if seed:
            loader=trainer.train_loader
            loader.generator.manual_seed(value)
            if hasattr(loader.sampler,"generator"):loader.sampler.generator=loader.generator
            loader.reset()
        write_json(Path(trainer.save_dir)/"sampler.json",{"seed":seed,"loader_seed":value})
    model.add_callback("on_train_start",seed_loader)
    started=time.time()
    model.train(**args)
    if Path(model.trainer.save_dir).resolve()!=dest.resolve() or model.trainer.batch_size!=4:
        raise RuntimeError("training silently changed destination or batch")
    metrics=list(csv.DictReader((dest/"results.csv").open(encoding="utf-8")))
    evidence=audit_finetune_learning_rates(metrics,args["lr0"])
    write_json(dest/"complete.json",{"args":args,"epochs_completed":len(metrics),"seconds":time.time()-started,
        "initial_sha256":digest(checkpoint),"data_lineage_sha256":digest(out/"training-data/lineage.json"),
        "script_sha256":digest(Path(__file__)),"observed_learning_rate_maxima":evidence,
        "environment":{"torch":torch.__version__,"ultralytics":ultralytics.__version__,"gpu":torch.cuda.get_device_name(0)},
        "production_changed":False})


def scan(parent,out,seed):
    import torch
    from ultralytics import YOLO
    sys.path.insert(0,str(parent/"snapshot/backend"))
    from app.vision.yolo_pose import _letterbox,decode_yolo_pose_output
    cfg=yaml.safe_load((parent/"snapshot/backend/config.yaml").read_text(encoding="utf-8"))["yolo_pose"]
    confidence=cfg.get("board_confidence_thresholds",{}).get("raspberry-pi-5",cfg["confidence_threshold"])
    manifest=load(out/"manifest.json")
    rows=[r for r in manifest["records"] if r["split"]!="train"]
    inputs=[]; metadata=[]
    for row in rows:
        frame=cv2.imread(str(out/row["image"]))
        h,w=frame.shape[:2]
        padded,scale,px,py=_letterbox(frame,960)
        inputs.append(np.ascontiguousarray(padded[:,:,::-1].transpose(2,0,1),dtype=np.float32)/255.)
        metadata.append((w,h,scale,px,py,read_label(out/row["label"],count=8)))
    # Keep host-side inputs; loading every 960p tensor on an 8-GB GPU crowds the active app.
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    epochs=[]
    directory=out/"training"/f"eight-seed{seed}"
    budget=load(directory/"complete.json")["epochs_completed"]
    for index in range(budget):
        checkpoint=directory/"weights"/f"epoch{index}.pt"
        net=YOLO(str(checkpoint)).model.cuda().float().eval()
        net.fuse(verbose=False)
        predicted=[]
        with torch.inference_mode():
            for offset in range(0,len(rows),4):
                tensor=torch.from_numpy(np.stack(inputs[offset:offset+4])).cuda()
                output=net(tensor)
                output=output[0] if isinstance(output,(tuple,list)) else output
                predicted.extend(output.cpu().numpy())
        records=[]
        for row,(w,h,scale,px,py,label),output in zip(rows,metadata,predicted):
            obs=decode_yolo_pose_output(output,frame_size=(w,h),input_size=960,scale=scale,pad_x=px,pad_y=py,
                keypoint_count=8,confidence_threshold=confidence,keypoint_threshold=cfg["keypoint_threshold"],
                nms_iou_threshold=cfg["nms_iou_threshold"])
            r={"image":row["image"],"positive":label is not None,"detected":obs is not None,"matched":False}
            if label is not None and obs is not None:
                cx,cy,bw,bh=label[1:5]*[w,h,w,h]
                r["matched"]=box_iou(obs.box_xyxy,[cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2])>=.5
                if np.all(obs.keypoint_confidences[4:]>=cfg["keypoint_threshold"]):
                    truth=label[5:].reshape(8,3)[4:]
                    pins=dict(zip(("3V3_P1","5V_P2","GPIO21","GND_P39"),obs.landmarks_px[4:]))
                    r["raw"]={**j8_errors(pins,truth,w,h),**header_shape(obs.landmarks_px[4:],truth[:,:2]*[w,h])}
            records.append(r)
        s=summary(records)
        epochs.append({"epoch":index+1,"checkpoint":str(checkpoint),"sha256":digest(checkpoint),"summary":s,"records":records})
        print("CHECKPOINT",index+1,"miss",s["misses"],"fp",s["false_positive"],"J8 P95",s["stages"]["raw"]["pitch"]["p95"],flush=True)
        del net,tensor,output
    base=load(out/"evaluations/four-current.json")["summary"]
    eligible=[e for e in epochs if e["summary"]["misses"]<=base["misses"]
        and e["summary"]["false_positive"]<=base["false_positive"] and e["summary"]["stages"]["raw"]["frames"]==35]
    # Qualification requires no detection regressions. If none qualifies, the least-bad
    # checkpoint is only an investigation candidate, never automatic promotion.
    pool=eligible or epochs
    winner=min(pool,key=lambda e:(e["summary"]["misses"],e["summary"]["stages"]["raw"]["pitch"]["p95"] or float("inf")))
    write_json(directory/"checkpoint-scan.json",{"epochs":epochs,"winner":{k:v for k,v in winner.items() if k!="records"},
        "selection_scope":"same legacy validation selected all checkpoints; not independent testing"})


def export(out,seed):
    from ultralytics import YOLO
    import torch
    selected=load(out/"training"/f"eight-seed{seed}"/"checkpoint-scan.json")["winner"]
    source=Path(selected["checkpoint"])
    if digest(source)!=selected["sha256"]:raise ValueError("checkpoint changed")
    destination=out/"candidates"/f"eight-seed{seed}"
    destination.mkdir(parents=True,exist_ok=False)
    path=destination/"model.pt"
    shutil.copy2(source,path)
    model=YOLO(str(path))
    model.export(format="onnx",imgsz=960,dynamic=False,simplify=True,nms=False,opset=12,device="0")
    net=YOLO(str(path)).model.cuda().float().eval()
    net.fuse(verbose=False)
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    from ultralytics.data.augment import LetterBox
    manifest=load(out/"manifest.json")
    selected_rows=[next(r for r in manifest["records"] if r["split"]=="val"),
                   next(r for r in manifest["records"] if not r["positive"])]
    arrays={}
    with torch.inference_mode():
        for i,row in enumerate(selected_rows):
            frame=cv2.imread(str(out/row["image"]))
            padded=LetterBox((960,960),auto=False,stride=32)(image=frame)
            blob=np.ascontiguousarray(padded[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255.
            result=net(torch.from_numpy(blob).cuda())
            result=result[0] if isinstance(result,(tuple,list)) else result
            arrays[f"input_{i}"]=blob;arrays[f"output_{i}"]=result.cpu().numpy()
    np.savez_compressed(destination/"pt-parity.npz",**arrays)
    entry={"onnx":str(destination/"model.onnx"),"checkpoint":str(path),"count":8,
        "onnx_sha256":digest(destination/"model.onnx"),"checkpoint_sha256":digest(path),"selected_epoch":selected["epoch"]}
    write_json(destination/"candidate.json",entry)
    # Candidate registry is separate from the immutable source manifest.
    registry=out/"candidates.json"
    entries=load(registry) if registry.exists() else {}
    entries[f"eight-seed{seed}"]=entry
    write_json(registry,entries)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("dataset","train","scan","export"))
    parser.add_argument("--parent",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--seed",type=int,default=0,choices=(0,1))
    parser.add_argument("--epochs",type=int,default=40,choices=range(1,41))
    parser.add_argument("--accept-ultralytics-license",action="store_true")
    args=parser.parse_args()
    parent,out=args.parent.resolve(),args.out.resolve()
    if args.action=="dataset":dataset(out)
    elif args.action=="train":
        if not args.accept_ultralytics_license:parser.error("project license confirmation required")
        train(out,args.seed,args.epochs)
    elif args.action=="scan":scan(parent,out,args.seed)
    else:export(out,args.seed)
