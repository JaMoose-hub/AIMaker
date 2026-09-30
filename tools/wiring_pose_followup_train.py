"""Controlled warmup-only continuation of an immutable earlier experiment."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from wiring_pose_data import digest, write_json
from wiring_pose_experiment import run_process, train_one


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--component",choices=("hc","pi"),default="hc")
    parser.add_argument("--budget",type=int,required=True)
    parser.add_argument("--seed",type=int,choices=(0,1))
    parser.add_argument("--accept-ultralytics-license",action="store_true")
    args=parser.parse_args()
    if not args.accept_ultralytics_license:parser.error("project license confirmation required")
    parent,out=args.parent.resolve(),args.out.resolve()
    if parent==out:parser.error("follow-up must not modify its parent experiment")
    if args.seed is not None:
        train_one(parent,args.component,"A",args.seed,artifact_root=out,common_budget=args.budget)
    else:
        write_json(out/"warmup-experiment.json",{"parent":str(parent),"parent_manifest_sha256":digest(parent/"manifest.json"),
            "component":args.component,"common_epoch_budget":args.budget,"lr0":.0001,"warmup_bias_lr":0.,
            "changed_factor":"bias warmup; source data, architecture, input size, loss weights unchanged",
            "selection_scope":"legacy validation, not independent test","production_promotion":False})
        for seed in (0,1):
            run_process(out,[sys.executable,str(Path(__file__).resolve()),"--parent",str(parent),"--out",str(out),
                "--component",args.component,"--budget",str(args.budget),"--seed",str(seed),"--accept-ultralytics-license"],f"warmup-{args.component}-seed{seed}")
