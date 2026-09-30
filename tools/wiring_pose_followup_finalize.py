"""Export and verify the controlled follow-up without touching production weights."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import shutil

import numpy as np

from wiring_pose_data import digest, write_json
from wiring_pose_experiment import export_candidate, audit_finetune_learning_rates


def load(path):return json.loads(path.read_text(encoding="utf-8"))


def choose_localization_checkpoint(epochs, baseline):
    """Meet the actual P95 goal subject to no more misses; then prefer coverage."""
    admissible=[r for r in epochs if r["misses"]<=baseline["missed"] and r["false_positives"]<=baseline["false_positive"]
                and r["normalized"]["p95"] is not None]
    if not admissible:raise ValueError("no checkpoint respects baseline detection constraints")
    qualified=[r for r in admissible if r["normalized"]["p95"]<=.85*baseline["raw_corner_diagonal"]["p95"]]
    if qualified:return min(qualified,key=lambda r:(r["misses"],r["normalized"]["p95"]))
    return min(admissible,key=lambda r:(r["normalized"]["p95"],r["misses"]))


def export(parent,out):
    baseline=load(parent/"evaluations/hc/v3.json")["summary"]
    selected={}
    for seed in (0,1):
        name=f"hc-A-seed{seed}"
        scan=load(out/"warmup-scan/checkpoint-scan"/(name+".json"))
        candidate=choose_localization_checkpoint(scan["epochs"],baseline)
        if digest(Path(candidate["checkpoint"]))!=candidate["sha256"]:raise ValueError("checkpoint changed since scan")
        selected[name]={k:v for k,v in candidate.items() if k!="records"}
        rows=list(csv.DictReader((out/"training"/name/"results.csv").open(encoding="utf-8")))
        selected[name]["learning_rates"]=audit_finetune_learning_rates(rows,.0001)
        export_candidate(parent,"hc","A",seed,14,artifact_root=out,checkpoint_override=candidate["checkpoint"])
    write_json(out/"selection.json",{"selected":selected,"scope":"legacy validation selection, not independent acceptance",
        "rule":"first achieve >=15% normalized P95 reduction with no additional baseline misses; among qualified, prefer fewer misses"})


def evaluate(parent,out):
    import onnxruntime as ort
    from wiring_pose_evaluation import (configure_snapshot, evaluate as evaluate_model, gate,
        RuntimeAdapter,compare_tensors,compare_decoded_outputs,comparison_images)
    config=configure_snapshot(parent)
    baseline=load(parent/"evaluations/hc/v3.json")
    results={}
    for seed in (0,1):
        name=f"hc-A-seed{seed}"
        directory=out/"candidates"/name
        metadata=load(directory/"candidate.json")
        model=out/metadata["onnx"]
        report=evaluate_model(parent,"hc",model,name+"-matching-v4",config,artifact_root=out)
        negative=evaluate_model(parent,"hc",model,name,config,splits=("train","val","test"),negative_only=True,artifact_root=out)
        adapter=RuntimeAdapter(parent,"hc",model,config)
        try:
            session=ort.InferenceSession(str(model),providers=[("CUDAExecutionProvider",{"use_tf32":0}),"CPUExecutionProvider"])
            if session.get_providers()[0]!="CUDAExecutionProvider":raise RuntimeError("parity fell back to CPU")
            arrays=np.load(directory/"pt-parity.npz")
            checks=[]
            for i in range(2):
                expected=arrays[f"output_{i}"]
                strict=session.run(None,{session.get_inputs()[0].name:arrays[f"input_{i}"]})[0]
                actual=adapter.locator._session.run(None,{adapter.locator._input_name:arrays[f"input_{i}"]})[0]
                checks.append({"tensor":compare_tensors(expected,strict),
                    "production_decoded":compare_decoded_outputs(expected,actual,adapter.locator._decode_options)})
            parity={"passed":all(c["tensor"]["allclose"] and c["production_decoded"]["passed"] for c in checks),
                "checks":checks,"model_sha256":digest(model)}
            write_json(directory/"parity.json",parity)
            del session
        finally:adapter.close()
        qualification=gate(baseline,report)
        qualification["parity_passed"]=parity["passed"]
        qualification["seen_negative_stress"]=negative["summary"]
        qualification["regression_gate_passed"] &= parity["passed"] and negative["summary"]["false_positive"]==0
        qualification["live_acceptance"]=False
        qualification["metric_schema"]=4
        qualification["comparison_images"]=comparison_images(parent,"hc",baseline,report,artifact_root=out)
        results[name]=qualification
        write_json(directory/"gate-matching-v4.json",qualification)
        print(name,json.dumps(qualification),flush=True)
    write_json(out/"hc-gates.json",results)


def replay(parent,out):
    from wiring_pose_evaluation import configure_snapshot
    from wiring_pose_replay import replay_assembly
    from wiring_pose_candidates import orientation_consensus
    configure_snapshot(parent)
    import app.vision.tft_ring_geometry as geometry
    original=geometry.orient_tft_from_panel_inset
    manifest=load(parent/"manifest.json")
    baseline={c:spec["models"][spec["active"]] for c,spec in manifest["components"].items()}
    candidate=dict(baseline)
    hc=load(out/"candidates/hc-A-seed1/candidate.json")
    candidate["hc"]={**hc,"onnx":str(out/hc["onnx"])}
    variant={"tft_guard_sha256":digest(Path(__file__).with_name("wiring_pose_candidates.py")),
        "hc_seed":1,"pi_unchanged":True,"production_changed":False}
    try:
        for name,repeat in (("baseline",0),("candidate",0),("candidate",1),("baseline",1)):
            if (out/"replay"/f"{name}-{repeat}.json").exists():raise FileExistsError("replay output already exists; do not silently reuse")
            geometry.orient_tft_from_panel_inset=orientation_consensus(original) if name=="candidate" else original
            print("REPLAY",name,repeat,flush=True)
            replay_assembly(parent,name,candidate if name=="candidate" else baseline,repeat,artifact_root=out,
                variant=variant if name=="candidate" else None)
    finally:geometry.orient_tft_from_panel_inset=original


def tft_replay(parent,out):
    from wiring_pose_evaluation import configure_snapshot
    from wiring_pose_replay import replay_assembly
    from wiring_pose_candidates import orientation_consensus
    configure_snapshot(parent)
    import app.vision.tft_ring_geometry as geometry
    original=geometry.orient_tft_from_panel_inset
    geometry.orient_tft_from_panel_inset=orientation_consensus(original)
    manifest=load(parent/"manifest.json")
    models={c:spec["models"][spec["active"]] for c,spec in manifest["components"].items()}
    variant={"tft_guard_sha256":digest(Path(__file__).with_name("wiring_pose_candidates.py")),
        "all_model_weights_unchanged":True,"production_changed":False}
    try:
        for repeat in (0,1):
            if (out/"replay"/f"tft-only-{repeat}.json").exists():raise FileExistsError("isolated replay output already exists")
            print("REPLAY tft-only",repeat,flush=True)
            replay_assembly(parent,"tft-only",models,repeat,artifact_root=out,variant=variant)
    finally:geometry.orient_tft_from_panel_inset=original


def temporal_comparison(baselines,candidates):
    if not baselines or len(baselines)!=len(candidates):
        raise ValueError("replay repeat count mismatch or empty comparison")
    for b,a in zip(baselines,candidates):
        if b["repeat"]!=a["repeat"] or [s["sequence"] for s in b["sequences"]]!=[s["sequence"] for s in a["sequences"]]:
            raise ValueError("replay repeat or sequence identity mismatch")
    result={}
    for component in ("pi","tft","hc"):
        checks=[]
        for b,a in zip(baselines,candidates):
            for bs,cs in zip(b["sequences"],a["sequences"]):
                bsum,csum=bs["components"][component]["summary"],cs["components"][component]["summary"]
                checks.append({"repeat":b["repeat"],"sequence":bs["sequence"],"baseline":bsum,"candidate":csum,
                    "not_worse":csum["lock_loss_transitions"]<=bsum["lock_loss_transitions"] and
                                csum["locked_with_current_observation"]>=bsum["locked_with_current_observation"]})
        result[component]={"per_clip_not_worse":bool(checks) and all(c["not_worse"] for c in checks),"checks":checks}
    return result


def report(parent,out):
    from wiring_pose_evaluation import summarize,stats,comparison_images
    old=load(parent/"evaluations/hc/v3.json")
    baseline=summarize(old["records"])
    candidates={str(seed):load(out/"evaluations/hc"/f"hc-A-seed{seed}-matching-v4.json") for seed in (0,1)}
    gates=load(out/"hc-gates.json")
    before=load(out/"evaluations/tft/v3-last-lit-regression.json")
    after=load(out/"evaluations/tft/v3-last-orientation-consensus-v2.json")
    case_before={**before,"records":[r for r in before["records"] if r["key"].endswith("/frame_000020.jpg")]}
    case_after={**after,"records":[r for r in after["records"] if r["key"].endswith("/frame_000020.jpg")]}
    illustrations=comparison_images(parent,"tft",case_before,case_after,artifact_root=out)
    assemblies={name:[load(out/"replay"/f"{name}-{i}.json") for i in (0,1) if (out/"replay"/f"{name}-{i}.json").exists()]
                for name in ("baseline","candidate","tft-only")}
    latency={name:stats([v for r in rows for v in r["latency_samples"]]) for name,rows in assemblies.items()}
    complete=all(len(assemblies[name])==2 for name in ("baseline","candidate"))
    speed=complete and latency["candidate"]["p95"]<=1.1*latency["baseline"]["p95"]
    temporal=temporal_comparison(assemblies["baseline"],assemblies["candidate"]) if complete else {}
    isolated_complete=len(assemblies["baseline"])==2 and len(assemblies["tft-only"])==2
    isolated=temporal_comparison(assemblies["baseline"],assemblies["tft-only"]) if isolated_complete else {}
    isolated_speed=isolated_complete and latency["tft-only"]["p95"]<=1.1*latency["baseline"]["p95"]
    tft_offline_pass=bool(isolated_speed and isolated and all(t["per_clip_not_worse"] for t in isolated.values()))
    decisions={"hc":"retain_original; static improvement does not pass continuous replay",
               "tft":"offline_guard_ready_for_user_trial" if tft_offline_pass else "retain_original; offline guard requires further investigation",
               "pi":"retain_original; eight_point_comparison_awaits_user_choice"}
    changes=[]
    manifest=load(parent/"manifest.json")
    for row in manifest["frozen_files"]:
        path=parent/row["snapshot"]
        if not path.is_file() or digest(path)!=row["sha256"]:changes.append(row["snapshot"])
    source_snapshot=out/"tool-versions/final"
    source_snapshot.mkdir(parents=True,exist_ok=True)
    sources=[]
    for source in Path(__file__).parent.glob("wiring_pose_*.*"):
        if source.suffix not in (".py",".json"):continue
        target=source_snapshot/source.name
        shutil.copy2(source,target)
        sources.append({"path":str(target.relative_to(out)),"sha256":digest(target)})
    payload={"hc_baseline":baseline,"hc_candidates":{s:r["summary"] for s,r in candidates.items()},"hc_gates":gates,
        "tft_baseline":before["summary"],"tft_candidate":after["summary"],"tft_failure_images":illustrations,
        "replay_complete":complete,"latency_ms":latency,"speed_gate":speed,"temporal":temporal,
        "tft_isolated":{"complete":isolated_complete,"speed_gate":isolated_speed,"temporal":isolated},
        "snapshot_mismatches":changes,"tool_snapshot":sources,"production_promotion":False,"independent_wired_acceptance":False,
        "decisions":decisions,
        "pi_eight_point_experiment":"awaiting_user_choice; not performed","tft_training":"not performed; existing labels unchanged"}
    fmt=lambda v:"N/A" if v is None else f"{v:.2f}"
    lines=["# 接線辨識第二輪實驗", "", "正式模型、API、UI、相機與啟動設定均未由本次實驗更改。沒有新拍攝、人工修標或偽標註。", "",
        "## 這輪找到並處理的問題", "",
        "1. 第一輪 AdamW 微調沿用了 `warmup_bias_lr=0.1`，第一個 epoch 記錄約 0.0669，遠高於主學習率 0.0001。已將所有參數組暖身起點設為 0，保留資料、輸入尺寸、loss 與原 LR 排程；HC 兩個 seed 各重跑 14 epochs。",
        "2. 選 checkpoint 改為：先滿足相對原模型漏檢不增加及 P95 至少下降 15%，再在合格者中選漏檢較少者。不再以 pose mAP 代替角點定位目標。這是驗證集選模，不是獨立測試。",
        "3. TFT 原後處理會把一張圖的玻璃邊框當作 LCD 方向證據，將已正確的孔心順序翻轉 180°。離線候選增加既有面板幾何範圍與局部擾動一致性檢查，不增加保留舊位置的時間。", "",
        "## HC：同一組 46 張既有驗證圖", "",
        "|模型|漏檢|原始 P95 px|原始 P95／對角線|正式流程 P95／對角線|匹配正確零件的後處理幀數|", "|---|---:|---:|---:|---:|---:|"]
    for name,s in [("原模型",baseline)]+[("warmup seed "+seed,r["summary"]) for seed,r in candidates.items()]:
        lines.append(f"|{name}|{s['missed']} / 46|{fmt(s['raw_corner_px']['p95'])}|{s['raw_corner_diagonal']['p95']:.4f}|{s['post_corner_diagonal']['p95']:.4f}|{s['post_localized_positive']}|")
    static_pass=all(g["regression_gate_passed"] for g in gates.values())
    lines.extend(["", f"HC 兩個 seed 的靜態回歸門檻皆通過：{static_pass}。門檻包括正規化 P95、已見負例、覆蓋及 PT／ONNX 比對。像素誤差也列於表中，不將正規化改善百分比冒充像素改善百分比。",
        "模型選擇仍使用歷史 validation，因此只代表既有資料上的可重現回歸改善。", "",
        "### 評估工具修正", "",
        "第一輪 `post_localized_positive` 只計有沒有輸出，會把錯誤對象當作有效定位。本輪 schema 4 對兩邊一致加上後處理四邊形與人工物件四邊形 IoU ≥ 0.5，另保留所有輸出數；P95 仍列出所有有輸出點的誤差，沒有刪除困難圖片。",
        "HC 原模型有輸出 46 幀、匹配 45 幀；seed 0 有輸出 45 幀、匹配 45 幀；seed 1 有輸出 46 幀、匹配 45 幀。第一輪原始報告不改寫。", "",
        "## TFT：只用既有 29 張孔心標註作回歸", "",
        "這 29 張都已在歷史訓練中出現，不是獨立 holdout；舊 PCB 外角標註仍隔離，沒有自動改成孔心。",
        f"原模型原始漏檢仍為 {before['summary']['missed']}/29，沒有靠降低門檻宣稱改善。方向保護把後處理 P95 從 {fmt(before['summary']['post_corner_px']['p95'])} px 降至 {fmt(after['summary']['post_corner_px']['p95'])} px；主要是修正一張 180° 錯判，不代表整體模型辨識能力提升同樣比例。",
        "仍有亮屏角度與錯誤物件問題，TFT 網路權重未更新。", "",
        "## Pi：分離模型與幾何問題", "",
        "人工板卡四角的診斷投影仍有約 24 px 的 J8 P95 誤差，說明只把板卡框訓練得更準，無法完整處理針腳高度／傾斜與局部端點位置。人工角點僅用來分析，沒有作為正式候選輸入。",
        "也測過現有高度投影加近似內參：未提供穩定改善，因此不解除原本的相機校正限制。下一步八點 Pi（四板角＋四個 J8 端點）需要使用者確認是否放寬四點架構限制；本輪未啟用或訓練。", "",
        "## 同條件連續影格回放", "",
        f"四輪完成：{complete}；基準 P95 {fmt(latency['baseline']['p95'])} ms，候選 {fmt(latency['candidate']['p95'])} ms；+10% 速度門檻：{speed}。不是 webcam FPS，也不包含完整伺服器排程。",
        "兩輪反向順序，使用同一組 520 張既有影格；Pi 原模型不變、HC 使用 seed 1 候選、TFT 原權重加離線方向保護。程式仍在同機運行，GPU 非完全獨占。", "",
        "|類別|新鮮鎖定幀數（基準 → 候選）|失鎖次數（基準 → 候選）|每段皆不退步|", "|---|---:|---:|---|"])
    for c,t in temporal.items():
        fresh=[sum(x[s]["locked_with_current_observation"] for x in t["checks"]) for s in ("baseline","candidate")]
        losses=[sum(x[s]["lock_loss_transitions"] for x in t["checks"]) for s in ("baseline","candidate")]
        lines.append(f"|{c}|{fresh[0]} → {fresh[1]}|{losses[0]} → {losses[1]}|{t['per_clip_not_worse']}|")
    lines.extend(["", "### 僅 TFT 修正，保留全部原模型權重", "",
        f"另外兩輪回放完成：{isolated_complete}；P95 {fmt(latency['tft-only']['p95'])} ms；+10% 門檻：{isolated_speed}。使用同組基準，未與每輪候選交錯，效能結果仍需視為共用 GPU 下的離線量測。", "",
        "|類別|新鮮鎖定幀數（基準 → TFT-only）|失鎖次數（基準 → TFT-only）|每段皆不退步|", "|---|---:|---:|---|"])
    for c,t in isolated.items():
        fresh=[sum(x[s]["locked_with_current_observation"] for x in t["checks"]) for s in ("baseline","candidate")]
        losses=[sum(x[s]["lock_loss_transitions"] for x in t["checks"]) for s in ("baseline","candidate")]
        lines.append(f"|{c}|{fresh[0]} → {fresh[1]}|{losses[0]} → {losses[1]}|{t['per_clip_not_worse']}|")
    lines.extend(["", "此表是狀態指標，沒有人工真值的影片不宣稱絕對靜止抖動或精準恢復時間。低頻片段不作細粒度恢復評分。", "",
        "## 本輪決定", "",
        "- HC：保留原模型。兩個 seed 的靜態定位雖改善，但 seed 1 連續回放的手持片段退步，不能只憑靜態分數替換。",
        f"- TFT：只加方向保護的離線回放檢查通過：{tft_offline_pass}。這是後處理修正，不是重新訓練的權重提升；尚未接入正式程式。",
        "- Pi：維持原模型；若允許放寬四點限制，下一步用既有人工 J8 端點作八點離線比較，不要求新拍攝或新人工標註。",
        "- 既有低頻亮屏接線片段仍沒有鎖定成功；不能把多物件片段的改善宣稱成已解決所有亮屏接線漏檢。", "",
        "## 產物與限制", "", "- `candidates/`：兩個 HC PT、ONNX、匯出比對與驗收明細。",
        "- `diagnosis.json`、`height-ablation.json`、`j8-patches/`：Pi 分段誤差及失敗影像。",
        "- `tft-label-audit/`、`tft-clean-regression.json`、`comparisons/`：TFT 既有孔心標註稽核與方向錯判對照。",
        "- `warmup-experiment.json`、`training/`、`warmup-scan/`、`selection.json`：固定設定、學習率與 checkpoint 比較。",
        "- `replay/`、`report.json`、`tool-versions/final/`：回放、機器可讀報告與這輪工具快照。",
        f"凍結輸入雜湊不一致：{len(changes)}。所有候選未上線；仍欠獨立真實插滿接頭資料的驗證。"])
    write_json(out/"report.json",payload)
    (out/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("export","evaluate","replay","tft-replay","report"))
    parser.add_argument("--parent",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    globals()[args.action.replace("-","_")](args.parent.resolve(),args.out.resolve())
