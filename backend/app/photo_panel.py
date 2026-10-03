"""Current-photo LCD edge corroboration for slightly oblique raised panels.

Mounting holes are on the PCB, not the raised glass plane. Rectifying the
holes does not make the LCD rails exactly axis aligned. Measure four actual
sloped edges instead; no cached pose, inferred hole or brightness-only panel.
"""
from dataclasses import replace
from itertools import product

import cv2
import numpy as np


def photo_lcd_orientation(frame, observation, evidence):
    evidence.update(verified=False,source="current_lcd_sloped_edges",reason="four_lcd_edges_required")
    corners=np.asarray(observation.corners_px,np.float32)
    if (corners.shape!=(4,2) or not np.isfinite(corners).all() or not cv2.isContourConvex(corners)
            or cv2.contourArea(corners,oriented=True)<=0 or np.any(corners<0)
            or np.any(corners>=[frame.shape[1],frame.shape[0]])):
        evidence['reason']='invalid_or_clipped_mounts'
        return None
    target=np.float32([[32,32],[271,32],[271,431],[32,431]])
    patch=cv2.warpPerspective(frame,cv2.getPerspectiveTransform(corners,target),(304,464))
    gray=cv2.createCLAHE(clipLimit=3.,tileGridSize=(4,4)).apply(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY))
    edges=cv2.Canny(gray,35,100)
    lines=cv2.HoughLines(edges,1,np.pi/720,threshold=80)
    groups=[[],[],[],[]]  # left, right, header end, opposite end
    for rho,theta in ([] if lines is None else lines.reshape(-1,2)):
        sine,cosine=float(np.sin(theta)),float(np.cos(theta))
        group=None
        if abs(sine)<=.10*abs(cosine):
            line=(-sine/cosine,float(rho)/cosine)  # x = a*y+b
            x=line[0]*232+line[1]
            group=0 if 12<=x<=52 else 1 if 251<=x<=291 else None
        elif abs(cosine)<=.10*abs(sine):
            line=(-cosine/sine,float(rho)/sine)  # y = a*x+b
            y=line[0]*152+line[1]
            group=2 if 42<=y<=128 else 3 if 335<=y<=421 else None
        if group is not None:
            groups[group].append(line)
    for i,group in enumerate(groups):
        selected=[]
        for line in group:  # Hough candidates are already ordered by support.
            mid=232 if i<2 else 152
            if all(abs((line[0]-old[0])*mid+line[1]-old[1])>3 for old in selected):
                selected.append(line)
            if len(selected)==4:
                break
        groups[i]=selected
    evidence["edge_candidates"]=[len(group) for group in groups]
    if not all(groups):
        return None
    # Two canonical pixels cover rectification/edge antialiasing, not gaps
    # along a rail. Length and corner support are still independently gated.
    supported=cv2.dilate(edges,np.ones((5,5),np.uint8))>0

    def intersection(vertical,horizontal):
        a,b=vertical; c,d=horizontal
        y=(c*b+d)/(1-c*a)
        return [a*y+b,y]

    candidates=[]
    strongest=None
    for left,right,top,bottom in product(*groups):
        quad=np.float32([intersection(left,top),intersection(right,top),
                         intersection(right,bottom),intersection(left,bottom)])
        q=(quad-[32,32])/[239,399]
        if (not cv2.isContourConvex(quad) or cv2.contourArea(quad,oriented=True)<=0
                or not np.all((q[[0,3],0]>=-.08)&(q[[0,3],0]<=.08))
                or not np.all((q[[1,2],0]>=.92)&(q[[1,2],0]<=1.08))
                or not np.all((q[:2,1]>=.025)&(q[:2,1]<=.24))
                or not np.all((q[2:,1]>=.76)&(q[2:,1]<=.975))):
            continue
        top_inset=float(q[:2,1].mean()); bottom_inset=float(1-q[2:,1].mean())
        if not .65<=1-top_inset-bottom_inset<=.88 or not .04<=abs(top_inset-bottom_inset)<=.16:
            continue
        fractions=[]; joins=[]
        for start,end in zip(quad,np.roll(quad,-1,axis=0)):
            samples=np.rint(np.linspace(start,end,max(32,int(np.linalg.norm(end-start))))).astype(int)
            values=supported[samples[:,1],samples[:,0]]
            count=max(3,round(.15*len(values)))
            fractions.append(float(values.mean()))
            joins.extend([float(values[:count].mean()),float(values[-count:].mean())])
        if strongest is None or min(fractions)>strongest[0]:
            strongest=(min(fractions),min(joins))
        if min(fractions)>=.70 and min(joins)>=.50:
            candidates.append((top_inset,bottom_inset,min(fractions)))
    if strongest is not None:
        evidence['best_edge_support'],evidence['best_corner_support']=strongest
    if not candidates or len({top>bottom for top,bottom,_ in candidates})!=1:
        evidence["reason"]="lcd_inset_ambiguous"
        return None
    top,bottom,support=np.median(candidates,axis=0)
    flip=bool(top>bottom)
    evidence.update(verified=True,corrected=flip,reason="four_sloped_edges_and_asymmetric_inset",
        top_inset=round(float(top),4),bottom_inset=round(float(bottom),4),
        minimum_edge_support=round(float(support),3))
    return replace(observation,corners_px=np.roll(corners,2,axis=0).astype(float) if flip else corners.astype(float))
