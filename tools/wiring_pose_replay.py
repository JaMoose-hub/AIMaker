"""Frozen existing-frame replay and conservative experiment acceptance report.

No capture or pseudo-labeling. No inference cache: each model runs on each frame.
The synchronous three-worker benchmark is not webcam FPS or electrical proof.
"""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import time

import cv2
import numpy as np

from wiring_pose_data import ROOT, IDS, digest, write_json
from wiring_pose_evaluation import RuntimeAdapter, configure_snapshot, stats


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def freeze_sequences(out):
    destination = out / "sequences.json"
    if destination.exists():
        return load(destination)
    requested = ["S01-four-parts-baseline-01", "S02-clutter-wire-occlusion-01",
                 "S02-white-empty-01", "S05-Pi-handheld-01",
                 "S05-TFT-handheld-01", "S05-HC-handheld-01"]
    sources = {p.parent.name: p for p in (ROOT / "runs/acceptance").rglob("samples.json")}
    sequences, missing = [], []
    for name in requested:
        if name not in sources:
            missing.append(name)
            continue
        path = sources[name]
        samples = [s for s in load(path) if s.get("image_path") and (path.parent/s["image_path"]).is_file()]
        # One contiguous window preserves source cadence, not an artificially dense resample.
        start = len(samples)//3 if "handheld" in name else 0
        rows = [{"source":path.parent/s["image_path"], "ts_ms":s["ts_ms"], "frame_id":s["frame_id"]}
                for s in samples[start:start+80]]
        sequences.append({"name":name, "kind":"dense_existing_clip", "ground_truth":False, "rows":rows})
    folder = ROOT/"datasets/live-captures/tft-lit-wired-motion/20260925-135051-tft-lit-wired-motion"
    if (folder/"manifest.jsonl").exists():
        samples = [json.loads(line) for line in (folder/"manifest.jsonl").read_text(encoding="utf-8").splitlines()]
        rows = [{"source":folder/s["image"], "ts_ms":datetime.fromisoformat(s["captured_at"]).timestamp()*1000,
                 "frame_id":s["index"]} for s in samples]
        sequences.append({"name":folder.name, "kind":"sparse_existing_clip", "ground_truth":False,
                          "training_exposure":"some frames used in historical and current training", "rows":rows})
    for sequence in sequences:
        for index, row in enumerate(sequence["rows"]):
            source = row.pop("source")
            relative = f"sequences/{sequence['name']}/{index:04d}.jpg"
            target = out/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            row.update(image=relative, sha256=digest(target), source=str(source))
        deltas = np.diff([r["ts_ms"] for r in sequence["rows"]])
        sequence["source_gap_ms"] = stats(deltas)
        sequence["precise_recovery_eligible"] = bool(len(deltas) and np.max(deltas) <= 100)
    record = {"sequences":sequences, "missing":missing,
              "scope":"unlabeled historical stress, not independent accuracy validation"}
    write_json(destination, record)
    return record


def motion_residual(previous_frame, frame, previous_points, points):
    """Image-motion compensated residual, not human-verified static GPIO error."""
    if previous_points is None or points is None:
        return None
    if np.asarray(points).shape != (4,2) or np.asarray(previous_points).shape != (4,2):
        return None
    before = cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY)
    after = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if before.shape != after.shape:
        return None
    tracked, valid, _ = cv2.calcOpticalFlowPyrLK(before, after, np.asarray(previous_points, np.float32).reshape(-1,1,2),
                                               None, winSize=(21,21), maxLevel=3)
    if tracked is None or not np.all(valid):
        return None
    returned, back_valid, _ = cv2.calcOpticalFlowPyrLK(after, before, tracked, None, winSize=(21,21), maxLevel=3)
    if returned is None or not np.all(back_valid) or np.max(np.linalg.norm(returned.reshape(4,2)-previous_points, axis=1)) > 1.5:
        return None
    return float(np.median(np.linalg.norm(np.asarray(points)-tracked.reshape(4,2), axis=1)))


def temporal_summary(rows, eligible):
    losses = 0
    loss_start = None
    recovery = []
    for previous, current in zip(rows, rows[1:]):
        if previous["tracking"] == "locked" and current["tracking"] != "locked":
            losses += 1
            loss_start = current["ts_ms"]
        if loss_start is not None and current["tracking"] == "locked":
            recovery.append(current["ts_ms"]-loss_start)
            loss_start = None
    return {"frames":len(rows), "statuses":dict(Counter(r["tracking"] for r in rows)),
            "current_observation_frames":sum(r["current_observation"] for r in rows),
            "locked_with_current_observation":sum(r["tracking"]=="locked" and r["current_observation"] for r in rows),
            "lock_loss_transitions":losses,
            "observed_relock_ms":stats(recovery) if eligible else None,
            "unrecovered_at_end":loss_start is not None,
            "flow_compensated_residual_px":stats([r.get("flow_residual_px") for r in rows]) if eligible else None,
            "static_ground_truth_jitter":None,
            "limitations":"Relock is an observed status transition, not independently verified pose recovery. No static ground truth."}


def replay_assembly(out, name, models, repeat,*,artifact_root=None,variant=None):
    config = configure_snapshot(out)
    if models["pi"].get("count",4)==8:
        config.yolo_pose.board_8pt_model_paths={"raspberry-pi-5":out/models["pi"]["onnx"]}
    from app.component_worker import ComponentPoseState
    sequence_manifest = freeze_sequences(out)
    state = ComponentPoseState()
    try:
        hardware=subprocess.run(["nvidia-smi","--query-gpu=name,driver_version,utilization.gpu,memory.used,temperature.gpu,power.draw","--format=csv,noheader"],
                                capture_output=True,text=True,timeout=5).stdout.strip()
    except (OSError,subprocess.TimeoutExpired):
        hardware="unavailable"
    adapters = {}
    reports, timings = [], []
    try:
        # TFT first ensures HC peer-identity checks see the same-frame TFT result.
        for component in ("pi", "tft", "hc"):
            adapters[component] = RuntimeAdapter(out, component, out/models[component]["onnx"], config, state)
        for sequence in sequence_manifest["sequences"]:
            state.clear()
            for adapter in adapters.values():
                adapter.reset()
            rows = {c:[] for c in adapters}
            previous_frame, previous_points = None, {}
            for index, sample in enumerate(sequence["rows"]):
                path = out/sample["image"]
                if digest(path) != sample["sha256"]:
                    raise ValueError(f"replay frame changed: {path}")
                frame = cv2.imread(str(path))
                started = time.perf_counter()
                results = {c:a.process(frame, sample["frame_id"], sample["ts_ms"]) for c,a in adapters.items()}
                elapsed = (time.perf_counter()-started)*1000
                # Avoid including per-sequence model warmup/acquisition in steady-state latency.
                if index >= 5:
                    timings.append(elapsed)
                for component, result in results.items():
                    adapter = adapters[component]
                    corners = adapter.post_corners
                    eligible = sequence["precise_recovery_eligible"]
                    stability=str(getattr(result,"pose_stability_state",None) or getattr(result,"stability",None) or "")
                    current=corners is not None and result.tracking!="stale" and "hold" not in stability and "stale" not in stability
                    residual = motion_residual(previous_frame,frame,previous_points.get(component),corners) if previous_frame is not None and eligible else None
                    rows[component].append({"frame_id":sample["frame_id"],"ts_ms":sample["ts_ms"],
                        "tracking":result.tracking, "current_observation":current,"stability":stability,
                        "pins":len(result.pins), "flow_residual_px":residual,
                        "reason":getattr(result,"tracking_reason",None),
                        "gpio_endpoints":{p.pin_id:[float(p.x),float(p.y)] for p in result.pins
                            if component=="pi" and getattr(p,"pin_id",None) in ("3V3_P1","5V_P2","GPIO21","GND_P39")},
                        "pose_mode":getattr(result,"pose_mode",None),
                        "corners":None if corners is None else np.asarray(corners).tolist()})
                    previous_points[component] = None if corners is None else np.asarray(corners).copy()
                previous_frame = frame
            reports.append({"sequence":sequence["name"], "kind":sequence["kind"],
                "components":{c:{"summary":temporal_summary(r,sequence["precise_recovery_eligible"]),"frames":r} for c,r in rows.items()}})
    finally:
        for adapter in adapters.values():
            adapter.close()
    result = {"name":name,"repeat":repeat,"models":models,"sequence_manifest_sha256":digest(out/"sequences.json"),
        "gpu_at_start":hardware,
        "latency_ms":stats(timings),"latency_samples":timings,"sequences":reports,
        "runtime_config_sha256":digest(out/"snapshot/backend/config.yaml"),
        "inference_cache":"disabled; actual model inference on every frame",
        "scope":"synchronous CUDA three-worker offline processing; no JPEG decode, browser or webcam FPS"}
    result["variant"]=variant
    write_json((artifact_root or out)/"replay"/f"{name}-{repeat}.json",result)
    return result


def replay(out):
    configure_snapshot(out)
    manifest = load(out/"manifest.json")
    baseline = {c:v["models"][v["active"]] for c,v in manifest["components"].items()}
    candidate = {c:(baseline[c] if (out/"blocked"/(c+".json")).exists() else load(out/"selection"/(c+".json"))["candidate"]) for c in baseline}
    # Reversed second-pass order reduces thermal/order bias. No training may run concurrently.
    for name, repeat, models in [("baseline",0,baseline),("candidate",0,candidate),
                                 ("candidate",1,candidate),("baseline",1,baseline)]:
        if not (out/"replay"/f"{name}-{repeat}.json").exists():
            print(f"replaying {name} repeat {repeat}",flush=True)
            replay_assembly(out,name,models,repeat)


def negative_stress(out):
    from wiring_pose_evaluation import evaluate
    config=configure_snapshot(out)
    manifest=load(out/"manifest.json")
    for component,spec in manifest["components"].items():
        models={spec["active"]:spec["models"][spec["active"]]}
        for path in (out/"candidates").glob(f"{component}-*/candidate.json"):
            candidate=load(path)
            models[candidate["name"]]=candidate
        for name,model in models.items():
            destination=out/"negative-stress"/component/(name+".json")
            if not destination.exists():
                evaluate(out,component,out/model["onnx"],name,config,splits=("train","val","test"),negative_only=True)


def metric(report, field):
    return report["summary"][field]["p95"]


def replay_comparison_images(out):
    before_file,after_file=out/"replay/baseline-0.json",out/"replay/candidate-0.json"
    if not before_file.exists() or not after_file.exists():return []
    before,after=load(before_file),load(after_file)
    sources={s["name"]:s for s in load(out/"sequences.json")["sequences"]}
    colors={"pi":(70,230,70),"tft":(255,180,0),"hc":(30,120,255)}
    paths=[]
    for b,a in zip(before["sequences"],after["sequences"]):
        source=sources[b["sequence"]]
        count=len(source["rows"])
        differences=[sum(b["components"][c]["frames"][i]["tracking"]!=a["components"][c]["frames"][i]["tracking"] for c in colors) for i in range(count)]
        indices=sorted({int(np.argmax(differences)),count//2})
        for index in indices:
            sample=source["rows"][index]
            panels=[]
            for title,sequence in (("BASELINE",b),("CANDIDATE",a)):
                frame=cv2.imread(str(out/sample["image"]))
                statuses=[]
                for c,color in colors.items():
                    result=sequence["components"][c]["frames"][index]
                    statuses.append(c+":"+result["tracking"])
                    if result["corners"] is not None:
                        cv2.polylines(frame,[np.rint(result["corners"]).astype(np.int32)],True,color,3)
                frame=cv2.resize(frame,(640,360))
                cv2.rectangle(frame,(0,0),(640,43),(20,20,20),-1)
                cv2.putText(frame,title+"  "+" ".join(statuses),(6,17),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1)
                cv2.putText(frame,"Existing replay / estimated corners / NO ground truth",(6,36),cv2.FONT_HERSHEY_SIMPLEX,.4,(230,230,230),1)
                panels.append(frame)
            target=out/"comparisons/replay"/f"{b['sequence']}-{index:03d}.jpg"
            target.parent.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(target),np.hstack(panels))
            paths.append(str(target.relative_to(out)))
    return paths


def fmt(value, digits=2):
    return "N/A" if value is None else f"{value:.{digits}f}"


def report(out):
    manifest = load(out/"manifest.json")
    components, lines = {}, ["# 接線場景辨識實驗報告", "", "候選模型未上線；正式 API、UI、模型與啟動設定不變。", "",
        "## 資料與限制", "", "使用既有原圖與標註，不新增拍攝、不做偽標註。歷史驗證曾參與模型選擇，以下是回歸證據，不是獨立真實接線泛化成績。",
        "Pi J8 僅比較人工標註的 P1/P2/P40/P39。TFT 亮屏接線資料主要在訓練集；缺少獨立插滿杜邦接頭的真值，仍待驗證。", "",
        "|類別|合格原始訓練圖|既有驗證圖|J8 驗證圖|", "|---|---:|---:|---:|"]
    for c,spec in manifest["components"].items():
        counts=spec["counts"]
        if (out/"blocked"/(c+".json")).exists():
            lines.append(f"|{c}|隔離（格式合格原圖 {counts['train_original_eligible']}）|隔離（既有 {counts['val']}）|—|")
        else:
            lines.append(f"|{c}|{counts['train_original_eligible']}|{counts['val']}|{counts['j8_validation']}|")
    lines.extend(["", "## 同條件模型比較", "", "像素／正規化 P95 僅統計有輸出的角點，因此同時列出漏檢與包含漏檢的定位成功率。",
                  "正例必須與人工框的 IoU 至少 0.5 才算偵測成功；有框但未匹配也計入漏檢，不代表一定辨識成其他物件。",
                  "Pi 正規化單位為 J8 腳距；TFT/HC 為角點四邊形對角線比例。",
                  "定位成功率的分母包含全部正例：Pi 要求四個 J8 端點誤差中位數不超過 0.25 腳距且 P95 不超過 0.5 腳距；元件要求已標角點最大誤差不超過對角線的 2%。", "",
                  "|類別／模型|漏檢／正例|誤檢／負例|原始 P95 px|原始 P95 正規化|後處理 P95 px|定位成功率|",
                  "|---|---:|---:|---:|---:|---:|---:|"])
    for c,spec in manifest["components"].items():
        if (out/"blocked"/(c+".json")).exists():
            components[c]={"blocked":load(out/"blocked"/(c+".json")),"production_promotion":False,
                           "repeatable_regression_pass":False,"final_decision":"retain_current_production_model"}
            for path in (out/"evaluations"/c).glob("*.json"):
                diagnostic=load(path)
                diagnostic["localization_acceptance_valid"]=False
                diagnostic["invalidation_reason"]=components[c]["blocked"]["reason"]
                write_json(path,diagnostic)
            lines.append(f"|{c}|標註語意衝突，舊定位分數不作驗收|—|—|—|—|—|")
            continue
        for path in sorted((out/"evaluations"/c).glob("*.json")):
            r=load(path); s=r["summary"]
            raw="raw_j8_px" if c=="pi" else "raw_corner_px"
            norm="raw_j8_pitch" if c=="pi" else "raw_corner_diagonal"
            post="runtime_j8_px" if c=="pi" else "post_corner_px"
            lines.append(f"|{c}/{r['name']}|{s['missed']}/{s['positive']}|{s['false_positive']}/{s['negative']}|{fmt(metric(r,raw))}|{fmt(metric(r,norm),4)}|{fmt(metric(r,post))}|{fmt(100*s['raw_localization_success'])}%|")
        selection=load(out/"selection"/(c+".json"))
        chosen=selection["candidate"]
        seed1=out/"candidates"/f"{c}-{chosen['arm']}-seed1"
        first=load(out/"candidates"/chosen["name"]/"gate.json")
        second=load(seed1/"gate.json")
        components[c]={"chosen":chosen,"seed0":first,"seed1":second,
                       "repeatable_regression_pass":first["regression_gate_passed"] and second["regression_gate_passed"],
                       "production_promotion":False}
        curves=[]
        for seed in (0,1):
            path=out/"training"/f"{c}-{chosen['arm']}-seed{seed}"/"results.csv"
            with path.open(encoding="utf-8") as stream:
                curves.append([{k:v for k,v in row.items() if k not in ("time","epoch")} for row in csv.DictReader(stream)])
        budget=min(map(len,curves))
        different=curves[0][:budget]!=curves[1][:budget]
        components[c]["different_seed_effect_verified"]=different
        components[c]["repeatable_regression_pass"] &= different
        neg_base=out/"negative-stress"/c/(spec["active"]+".json")
        neg_first=out/"negative-stress"/c/(chosen["name"]+".json")
        neg_second=out/"negative-stress"/c/(f"{c}-{chosen['arm']}-seed1.json")
        if all(p.exists() for p in (neg_base,neg_first,neg_second)):
            nb,n0,n1=[load(p)["summary"] for p in (neg_base,neg_first,neg_second)]
            components[c]["seen_negative_stress"]={"count":nb["negative"],"baseline_fp":nb["false_positive"],
                "seed0_fp":n0["false_positive"],"seed1_fp":n1["false_positive"],
                "not_worse":max(n0["false_positive"],n1["false_positive"])<=nb["false_positive"],
                "scope":"includes training negatives; not independent validation"}
            components[c]["repeatable_regression_pass"] &= components[c]["seen_negative_stress"]["not_worse"]
    replay_files=list((out/"replay").glob("*.json"))
    assemblies={name:[load(p) for p in replay_files if p.stem.startswith(name+"-")] for name in ("baseline","candidate")}
    latency={name:stats([t for r in runs for t in r["latency_samples"]]) for name,runs in assemblies.items()}
    bp,cp=latency["baseline"]["p95"],latency["candidate"]["p95"]
    speed_pass=bp is not None and cp is not None and len(assemblies["baseline"])==2 and len(assemblies["candidate"])==2 and cp<=bp*1.10
    stability={}
    if assemblies["baseline"] and assemblies["candidate"]:
        before=assemblies["baseline"][0]["sequences"]
        after=assemblies["candidate"][0]["sequences"]
        for c in components:
            pairs=[(b["components"][c]["summary"],a["components"][c]["summary"]) for b,a in zip(before,after)]
            checks=[{"sequence":before[i]["sequence"],
                     "lock_losses_not_increased":a["lock_loss_transitions"]<=b["lock_loss_transitions"],
                     "fresh_locked_not_lower":a["locked_with_current_observation"]>=b["locked_with_current_observation"],
                     "baseline":b,"candidate":a} for i,(b,a) in enumerate(pairs)]
            stability[c]={"checks":checks,"coarse_gate":all(x["lock_losses_not_increased"] and x["fresh_locked_not_lower"] for x in checks),
                          "static_jitter_acceptance":"unavailable_without_verified_static_ground_truth"}
    lines.extend(["", "## 驗收", "", f"三模型同步 CUDA 回放 P95：基準 {fmt(bp)} ms；候選 {fmt(cp)} ms；+10% 門檻：{'通過' if speed_pass else '未通過或資料不足'}。不是 webcam FPS。", "",
                  "正值代表 P95 下降；負值代表變差。原始推論與正式後處理都需下降至少 15%，不能只看原始模型。", "",
                  "|類別|seed 0 原始改善|seed 1 原始改善|seed 0 正式流程改善|seed 1 正式流程改善|兩種 seed 回歸門檻|決策|", "|---|---:|---:|---:|---:|---|---|"])
    for c,result in components.items():
        if "blocked" in result:
            lines.append(f"|{c}|N/A|N/A|N/A|N/A|資料隔離，未訓練|保留正式模型|")
            continue
        a,b=result["seed0"]["p95_improvement"],result["seed1"]["p95_improvement"]
        pa,pb=result["seed0"].get("production_p95_improvement"),result["seed1"].get("production_p95_improvement")
        result["joint_speed_gate"]=speed_pass
        result["temporal"]=stability.get(c)
        # Independent wired evidence and verified static/recovery accuracy are still absent.
        result["final_decision"]="retain_current_production_model"
        lines.append(f"|{c}|{fmt(None if a is None else a*100)}%|{fmt(None if b is None else b*100)}%|{fmt(None if pa is None else pa*100)}%|{fmt(None if pb is None else pb*100)}%|{'通過' if result['repeatable_regression_pass'] else '未通過'}|保留正式模型，候選僅供研究|")
    lines.extend(["", "已見負例壓力檢查（包含訓練負例，不是獨立驗證）：", ""])
    for c,result in components.items():
        negative=result.get("seen_negative_stress")
        if negative:
            lines.append(f"- {c}：{negative['count']} 張，基準誤檢 {negative['baseline_fp']}，seed 0 {negative['seed0_fp']}，seed 1 {negative['seed1_fp']}。")
    lines.extend(["", "## 回放穩定度摘要", "",
        "以下彙總第一輪同影格回放的狀態（基準 → 候選）；新鮮鎖定不包含舊位置保留。失鎖是狀態轉換次數，不是人工真值錯誤數。",
        "逐片段門檻要求每段失鎖不增加且新鮮鎖定不減少；總數改善不能掩蓋個別片段退步。TFT 權重保持不變，但共用元件狀態仍可能受其他候選影響。", "",
        "|類別|有當幀觀測的鎖定幀數|失鎖次數|逐片段粗略門檻|", "|---|---:|---:|---|"])
    for c,temporal in stability.items():
        checks=temporal["checks"]
        fresh=[sum(x[side]["locked_with_current_observation"] for x in checks) for side in ("baseline","candidate")]
        losses=[sum(x[side]["lock_loss_transitions"] for x in checks) for side in ("baseline","candidate")]
        lines.append(f"|{c}|{fresh[0]} → {fresh[1]}|{losses[0]} → {losses[1]}|{'通過' if temporal['coarse_gate'] else '未通過'}|")
    lines.extend(["", "## 時序與定位解讀", "",
        "回放使用連續原影格、原時間戳及同一份正式追蹤設定，不延長位置保留。原圖推論不使用快取，避免模型之間共享推論結果。",
        "dense clip 記錄失鎖、重新鎖定狀態的時間與影像運動補償後的角點殘差；這不是人工確認的恢復時間或絕對靜止抖動。低頻 TFT clip 不計精細恢復時間。",
        "回放只同步執行三個辨識工作器，不包含正式排程、網路傳輸、畫面更新或額外 MotionOverlayWorker，因此不能當成完整產品 FPS 驗收。",
        "原本程式未被關閉，可能與實驗共用 GPU；採兩輪反向順序回放減少順序偏差，仍不是完全隔離的效能實驗。",
        "缺少負例的類別不宣稱已驗證誤檢改善。後處理可能改善或破壞模型定位，詳見各圖 raw/post 座標與 runtime 是否實際輸出 pins。", "",
        "## 可重現與產物", "", "- `manifest.json`：來源／模型／設定／程式快照、SHA256 與排除原因。",
        "- `datasets/*/{A,B}/lineage.json`：成對資料、拍攝組與增強來源。",
        "- `training/*/complete.json`：固定環境、AdamW、loss、seed、資料量與實際步數依據。",
        "- `candidates/*/`：PT、ONNX、匯出比對、回歸門檻。",
        "- `evaluations/*/`：逐圖原始／正式流程輸出；`comparisons/*/`：標註與前後對照圖。",
        "- `sequences.json`、`replay/*`：既有影格 SHA256、原時間戳、同條件回放。", ""])
    for c,result in components.items():
        if "blocked" in result:
            lines.extend([f"## {c} 資料隔離", "", result["blocked"]["reason"], "",
                "舊資料與衍生版本保留，不改寫或自動修標。已生成但未使用的 A/B 副本不進訓練。模型原始輸出仍保留作診斷，但不將外框標註冒充孔心真值。",
                "三模型回放中該類維持基準模型。需找到既有且語意一致的標註／驗證資料，或另行取得修標授權，才能繼續該類微調。", ""])
    invalid=[p.name for p in (out/"training").glob("*-invalid-*")]
    if invalid:
        lines.extend(["實驗過程排除的部分訓練（保留原始紀錄，未納入模型比較）："+", ".join(invalid)+"。原因是原 DataLoader 固定洗牌 seed，非零 seed 未產生獨立順序；工具修正後重跑。", ""])
    changed=[]; snapshot_bad=[]
    for row in manifest["frozen_files"]:
        original=Path(row["source"])
        if not original.is_file() or digest(original)!=row["sha256"]:
            changed.append(row["source"])
        if digest(out/row["snapshot"])!=row["sha256"]:
            snapshot_bad.append(row["snapshot"])
    integrity={"source_changed_since_snapshot":changed,"snapshot_mismatches":snapshot_bad,
               "note":"Source drift can come from other work; frozen experiment input remains authoritative."}
    write_json(out/"integrity.json",integrity)
    if changed:
        lines.extend(["注意：工作區有來源在快照後變更；這次仍使用凍結版本，詳見 integrity.json。", ""])
    payload={"components":components,"latency_ms":latency,"speed_gate":speed_pass,"integrity":integrity,
             "independent_wired_acceptance":False,"production_promotion":False}
    payload["replay_comparisons"]=replay_comparison_images(out)
    rules=Path(__file__).with_name("wiring_pose_semantic_exclusions.json")
    shutil.copy2(rules,out/"semantic-rules.json")
    payload["semantic_rules_sha256"]=digest(rules)
    blocked=[c for c,r in components.items() if "blocked" in r]
    payload["planned_training_complete"]=not blocked
    payload["blocked_components"]=blocked
    write_json(out/"training-complete.json",{"complete":not blocked,"completed_components":[c for c in components if c not in blocked],
        "blocked_components":blocked,"production_promotion":False})
    write_json(out/"report.json",payload)
    (out/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    return payload
