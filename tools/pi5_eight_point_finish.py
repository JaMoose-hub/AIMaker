"""Replay and conservative adoption decision for the isolated Pi eight-point trial."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import cv2
import numpy as np

from pi5_eight_point_check import load,PIN_IDS
from wiring_pose_data import ROOT,digest,write_json
from wiring_pose_evaluation import stats
from wiring_pose_followup_finalize import temporal_comparison
from wiring_pose_replay import replay_assembly,motion_residual


def replay(parent,out,name):
    manifest=load(parent/"manifest.json")
    base={c:spec["models"][spec["active"]] for c,spec in manifest["components"].items()}
    candidate={**base,"pi":load(out/"candidates.json")[name]}
    for kind,repeat in (("four",0),(name,0),(name,1),("four",1)):
        if (out/"replay"/f"{kind}-{repeat}.json").exists():raise FileExistsError("replay evidence already exists")
        print("REPLAY",kind,repeat,flush=True)
        replay_assembly(parent,kind,base if kind=="four" else candidate,repeat,artifact_root=out,
            variant={"pi_keypoints":4 if kind=="four" else 8,"calibration_forced":False,"production_changed":False})


def endpoint_residuals(parent,reports):
    """Same-image optical-flow proxy; never absolute jitter or GPIO ground truth."""
    sources={s["name"]:s for s in load(parent/"sequences.json")["sequences"]}
    results=[]
    for sequence in reports[0]["sequences"]:
        source=sources[sequence["sequence"]]
        if not source["precise_recovery_eligible"]:continue
        previous_frame=previous_points=None
        values=[]
        for row,sample in zip(sequence["components"]["pi"]["frames"],source["rows"]):
            frame=cv2.imread(str(parent/sample["image"]))
            pins=row["gpio_endpoints"]
            points=np.asarray([pins[k] for k in PIN_IDS]) if all(k in pins for k in PIN_IDS) and row["current_observation"] else None
            if previous_frame is not None:
                value=motion_residual(previous_frame,frame,previous_points,points)
                if value is not None:values.append(value)
            previous_frame,previous_points=frame,points
        results.append({"sequence":sequence["sequence"],"flow_compensated_gpio_residual_px":stats(values)})
    return {"repeat":0,"sequences":results,"scope":"unlabeled optical-flow proxy with correspondence failures excluded; not true GPIO jitter"}


def illustrations(out,name):
    base=load(out/"evaluations/four-current.json")
    candidate=load(out/"evaluations"/(name+".json"))
    reference={r["key"]:r for r in base["records"] if r["positive"]}
    rows=[r for r in candidate["records"] if r["positive"] and r.get("raw")
          and all(k in reference[r["key"]]["runtime_pins"] and k in r["runtime_pins"] for k in PIN_IDS)]
    rows=sorted(rows,key=lambda r:max(r["raw"]["row_angle_deg"]),reverse=True)[:4]
    paths=[]
    for index,row in enumerate(rows):
        panels=[]
        truth=np.asarray(row["truth_j8"])
        predictions=[reference[row["key"]]["runtime_pins"],row["raw_pins"],row["runtime_pins"]]
        all_points=[truth]+[np.asarray([p[k] for k in PIN_IDS]) for p in predictions if all(k in p for k in PIN_IDS)]
        limits=np.vstack(all_points)
        for title,pins in zip(("4pt final GPIO","8pt raw endpoints","8pt final GPIO"),predictions):
            frame=cv2.imread(row["image"])
            h,w=frame.shape[:2]
            lo=np.maximum(0,np.floor(limits.min(0)).astype(int)-25)
            hi=np.minimum([w,h],np.ceil(limits.max(0)).astype(int)+25)
            crop=frame[lo[1]:hi[1],lo[0]:hi[0]]
            scale=min(530/crop.shape[1],230/crop.shape[0])
            resized=cv2.resize(crop,None,fx=scale,fy=scale)
            canvas=np.full((280,550,3),20,np.uint8)
            canvas[40:40+resized.shape[0],:resized.shape[1]]=resized
            for points,color in ((truth,(70,240,70)),
                (np.asarray([pins[k] for k in PIN_IDS]) if all(k in pins for k in PIN_IDS) else None,(0,170,255))):
                if points is None:continue
                p=np.rint((points-lo)*scale+[0,40]).astype(np.int32)
                for a,b in ((0,3),(1,2)):
                    cv2.line(canvas,tuple(p[a]),tuple(p[b]),color,1)
                for point in p:cv2.circle(canvas,tuple(point),4,color,1)
            cv2.putText(canvas,title+" / green=human orange=prediction",(5,18),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1)
            cv2.putText(canvas,Path(row["image"]).name,(5,34),cv2.FONT_HERSHEY_SIMPLEX,.38,(255,255,255),1)
            panels.append(canvas)
        dest=out/"comparisons"/f"gpio-skew-{index+1}.jpg"
        dest.parent.mkdir(parents=True,exist_ok=True)
        cv2.imwrite(str(dest),np.hstack(panels))
        paths.append(str(dest.relative_to(out)))
    return paths


def qualification(base,candidate,temporal,speed,parity,paired=None):
    b,c=base["stages"]["runtime"],candidate["stages"]["runtime"]
    raw=candidate["stages"]["raw"]
    improve=lambda a,z: a is not None and z is not None and z>0 and a<=.85*z
    checks={"detector_misses_not_increased":candidate["misses"]<=base["misses"],
        "seen_negative_false_positives_not_increased":candidate["false_positive"]<=base["false_positive"],
        "runtime_endpoint_frames_not_lower":c["frames"]>=b["frames"],
        "runtime_p95_px_improves_15_percent":improve(c["px"]["p95"],b["px"]["p95"]),
        "runtime_p95_pitch_improves_15_percent":improve(c["pitch"]["p95"],b["pitch"]["p95"]),
        "runtime_angle_not_worse":c["row_angle_deg"]["p95"] is not None and c["row_angle_deg"]["p95"]<=b["row_angle_deg"]["p95"],
        "direct_eight_endpoints_beat_four_final":improve(raw["pitch"]["p95"],b["pitch"]["p95"]),
        "direct_eight_angle_not_worse":raw["row_angle_deg"]["p95"] is not None and raw["row_angle_deg"]["p95"]<=b["row_angle_deg"]["p95"],
        "no_crossed_or_reversed_rows":raw["crossed_or_reversed"]==0 and c["crossed_or_reversed"]==0,
        "all_component_clips_not_worse":bool(temporal) and all(t["per_clip_not_worse"] for t in temporal.values()),
        "latency_within_ten_percent":bool(speed),"pt_onnx_eight_point_parity":bool(parity)}
    if paired is not None:
        common=paired["runtime"]
        for field in ("px","pitch","row_angle_deg"):
            before,after=common["four_final"][field]["p95"],common["eight_runtime"][field]["p95"]
            checks["same_frames_runtime_"+field+"_not_worse"]=bool(common["paired_images"] and before is not None and after is not None and after<=before)
    return {"checks":checks,"offline_gate_passed":all(checks.values()),"production_promotion":False}


def paired_still_comparison(baseline,candidate):
    reference={r["key"]:r for r in baseline["records"] if r["positive"] and r.get("runtime")}
    results={}
    for stage in ("raw","runtime"):
        pairs=[(reference[r["key"]]["runtime"],r[stage]) for r in candidate["records"]
               if r["positive"] and r["key"] in reference and r.get(stage)]
        results[stage]={"paired_images":len(pairs)}
        for index,name in enumerate(("four_final","eight_"+stage)):
            results[stage][name]={field:stats([v for pair in pairs for v in pair[index][field]])
                                  for field in ("px","pitch","row_angle_deg")}
    return results


def report(parent,out,name):
    manifest=load(out/"manifest.json")
    evaluations={p.stem:load(p) for p in (out/"evaluations").glob("*.json")}
    baseline=evaluations["four-current"]["summary"]
    candidate=evaluations[name]["summary"]
    paired=paired_still_comparison(evaluations["four-current"],evaluations[name])
    replay={kind:[load(out/"replay"/f"{kind}-{i}.json") for i in (0,1)] for kind in ("four",name)}
    temporal=temporal_comparison(replay["four"],replay[name])
    latencies={k:stats([v for run in runs for v in run["latency_samples"]]) for k,runs in replay.items()}
    speed=latencies[name]["p95"]<=1.1*latencies["four"]["p95"]
    parity=load(out/"candidates"/name/"parity.json")["passed"]
    gate=qualification(baseline,candidate,temporal,speed,parity,paired)
    proxy={k:endpoint_residuals(parent,v) for k,v in replay.items()}
    images=illustrations(out,name)
    mismatches=[r["path"] for r in manifest["frozen"] if digest(out/r["path"])!=r["sha256"]]
    original=load(parent/"manifest.json")
    mismatches += [r["snapshot"] for r in original["frozen_files"] if digest(parent/r["snapshot"])!=r["sha256"]]
    config_unchanged=digest(ROOT/"backend/config.yaml")==manifest["source_config_sha256"]
    source_directory=out/"tool-versions/final"
    source_directory.mkdir(parents=True,exist_ok=True)
    snapshots=[]
    for pattern in ("pi5_eight_point_*.py","wiring_pose_*.py"):
        for path in Path(__file__).parent.glob(pattern):
            dest=source_directory/path.name
            shutil.copy2(path,dest)
            snapshots.append({"path":str(dest.relative_to(out)),"sha256":digest(dest)})
    payload={"gate":gate,"summaries":{k:v["summary"] for k,v in evaluations.items()},"temporal":temporal,"paired_stills":paired,
        "latency_ms":latencies,"gpio_flow_proxy":proxy,"comparisons":images,"snapshot_mismatches":mismatches,
        "source_config_unchanged":config_unchanged,"tool_snapshots":snapshots,"production_changed":False,
        "decision":"retain_four_point" if not gate["offline_gate_passed"] else "offline_pass_requires_seed1_and_user_trial",
        "scope":"all metrics are legacy regression or unlabeled replay; calibrated eight-point PnP not tested"}
    write_json(out/"report.json",payload)
    lines=["# Pi 5 四點／八點離線比較", "", "正式程式、相機、模型與設定沒有切換。本輪只測既有資料，沒有新拍攝、補標或偽標註。", "",
        "## 結論", "", "保留四點。八點未通過採用門檻。" if not gate["offline_gate_passed"] else "八點通過首輪離線門檻，仍需第二個 seed 與使用者實測。", "",
        "首輪未通過，因此不進行 seed 1 與正式替換。" if not gate["offline_gate_passed"] else "正式模型仍保留四點，候選不自動替換。", "",
        "## 資料與方法", "", "- 104 張既有人工八點訓練圖、35 張既有驗證圖、50 張已存在的非 Pi 負例。負例亦用於歷史／本輪訓練，只作已見壓力測試。",
        "- 驗證的來源圖及 J8 標註 SHA256 與前輪一致；不將模型看過的資料稱為獨立驗收。migration 的 session_id 是標註場次，並非可證實獨立的拍攝場次。",
        "- 先比較三版既有八點模型，再從 synth-negative-pilot 做 40 epochs 低學習率微調；AdamW 0.0001、warmup_bias_lr=0、batch 4、960、CUDA。",
        "- 只用已存在 P1/P2/P40/P39 人工端點作 GPIO 真值，另量測兩排端點方向的角度誤差。不把中間 36 點插值當成人工真值。",
        "- 所有 checkpoint 用相同驗證圖選模，分數存在選模偏差。位移小卻方向歪斜也不能通過。", "",
        "這是現有模型與有限微調的選型比較，不是控制變因證明四點架構天生優於八點；兩者歷史訓練資料與起始權重不同。", "",
        "## 同一組 35 張驗證圖", "", "|模型／流程|漏檢|J8 P95 px|J8 P95／腳距|排針角度 P95|有端點輸出的張數|", "|---|---:|---:|---:|---:|---:|"]
    for key in ("four-current","pilot","synth-pilot","synth-negative-pilot",name):
        s=evaluations[key]["summary"]
        for stage in (("runtime",) if key=="four-current" else ("raw","runtime")):
            t=s["stages"][stage]
            fmt=lambda v:"N/A" if v is None else f"{v:.2f}"
            lines.append(f"|{key} / {stage}|{s['misses']}|{fmt(t['px']['p95'])}|{fmt(t['pitch']['p95'])}|{fmt(t['row_angle_deg']['p95'])}°|{t['frames']} / 35|")
    lines.extend(["", "raw：八點直接預測 J8；runtime：沿用現有程式完整定位流程的 GPIO。漏檢按偵測框匹配 IoU ≥ 0.5；P95 包含有輸出的錯誤位置，不只選成功案例。", "",
        "現有相機沒有有效校正，所以 runtime 未開啟八點 3D PnP，仍使用既有四點幾何／影像修正回退。沒有拿其他相機的內參硬套，也沒有偽造 calibrated。這次不能推論『正確校正後的八點 PnP 一定差』。", "",
        f"共同有端點輸出的 {paired['runtime']['paired_images']} 張圖另外列於 `report.json / paired_stills`；不能把多輸出一張難圖造成的 P95 變化誤當成同幀退步或進步。",
        f"同幀四點／八點最終 GPIO P95：{paired['runtime']['four_final']['px']['p95']:.2f} / {paired['runtime']['eight_runtime']['px']['p95']:.2f} px；排針角度 P95：{paired['runtime']['four_final']['row_angle_deg']['p95']:.2f} / {paired['runtime']['eight_runtime']['row_angle_deg']['p95']:.2f}°。", "",
        "## 連續影格與延遲", "", "同一組 520 張既有影格，四點與候選各兩次，順序四→八→八→四；其他兩個元件權重與追蹤參數不變。", "",
        "|物件|新鮮鎖定幀數：四 → 八|失鎖次數：四 → 八|每段不退步|", "|---|---:|---:|---|"])
    for c,t in temporal.items():
        fresh=[sum(r[k]["locked_with_current_observation"] for r in t["checks"]) for k in ("baseline","candidate")]
        losses=[sum(r[k]["lock_loss_transitions"] for r in t["checks"]) for k in ("baseline","candidate")]
        lines.append(f"|{c}|{fresh[0]} → {fresh[1]}|{losses[0]} → {losses[1]}|{t['per_clip_not_worse']}|")
    lines.extend(["",f"三模型離線處理 P95：四點 {latencies['four']['p95']:.2f} ms → 八點 {latencies[name]['p95']:.2f} ms；速度門檻通過：{speed}。同機程式仍運行、GPU 非獨占，不能換算實際 webcam FPS。",
        "影片沒有 GPIO 人工真值；失鎖與光流補償殘差只是狀態／影像代理指標，不能冒充絕對靜止抖動或移動恢復精度。", "",
        "## 門檻", ""])
    lines += [f"- {k}: {v}" for k,v in gate["checks"].items()]
    lines.extend(["", "## 產物與限制", "", "- `comparisons/`：綠色人工端點與橘色預測的 GPIO 歪斜對照。",
        "- `training/eight-seed0/`：原始設定、40 個 checkpoint、學習率與逐 epoch 的端點選模結果。",
        "- `candidates/`：研究用 PT／ONNX 與全部八點匯出一致性檢查。",
        "- `evaluations/`、`replay/`、`report.json`：逐圖、逐影格與機器可讀結果。",
        f"- 凍結資料雜湊不一致 {len(mismatches)}；原始設定未改變：{config_unchanged}。",
        "- 沒有新增真實插滿接頭的獨立標註，因此不宣稱接線場景全面通過。"])
    (out/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(payload["decision"],gate,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("replay","report"))
    parser.add_argument("--parent",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--candidate",default="eight-seed0")
    args=parser.parse_args()
    globals()[args.action](args.parent.resolve(),args.out.resolve(),args.candidate)
