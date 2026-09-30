"""Offline-only geometry candidates. Nothing here changes the running application."""
from dataclasses import replace

import numpy as np


def orientation_consensus(original):
    """Require a proposed 180-degree semantic reversal to survive localization noise.

    This cannot establish header identity by itself. It only rejects brittle LCD
    inset votes; the original model identity and visibility gates remain required.
    No previous pose, label, or training-image identity is consulted.
    """
    def orient(frame,observation,evidence):
        result=original(frame,observation,evidence)
        if not (evidence.get("verified") and evidence.get("corrected")):
            return result
        # The existing panel model has a ~13.5% far-end flex strip. Two
        # small glass-border insets cannot authorize reversing all pin IDs.
        if max(evidence.get("top_inset",0.),evidence.get("bottom_inset",0.))<.11:
            evidence.update(verified=False,corrected=False,reason="outer_glass_not_active_panel")
            return observation
        corners=np.asarray(observation.corners_px,float)
        short=float(np.min(np.linalg.norm(corners-np.roll(corners,-1,axis=0),axis=1)))
        noise=float(np.clip(short*.004,.75,2.5))
        votes=[]
        for offset in ((noise,0),(-noise,0),(0,noise),(0,-noise)):
            probe={}
            original(frame,replace(observation,corners_px=corners+offset),probe)
            votes.append(probe)
        support=sum(p.get("verified") and p.get("corrected") for p in votes)
        contradictory=any(p.get("verified") and not p.get("corrected") for p in votes)
        evidence["orientation_consensus"]={"perturbation_px":noise,"support":support,"probes":len(votes),"contradictory":contradictory}
        if support<3 or contradictory:
            evidence.update(verified=False,corrected=False,reason="unstable_lcd_orientation")
            return observation
        return result
    return orient
