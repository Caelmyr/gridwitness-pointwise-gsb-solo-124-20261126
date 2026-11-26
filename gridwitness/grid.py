"""Measure actual dark-dot centroids near a nominal calibration grid."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from image_lab.validation import integer

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126,0.7152,0.0722])
# Up/down/left/right connectivity; diagonal pixels do not join a dark group.
CROSS = np.array([[0,1,0],[1,1,1],[0,1,0]], dtype=bool)


def settings(value, size):
    width,height=size
    rows=integer(value.get("rows"),"行数",1,24)
    return {
        "origin_x":integer(value.get("origin_x"),"首点 X",0,width-1),
        "origin_y":integer(value.get("origin_y"),"首点 Y",0,height-1),
        "rows":rows,"columns":integer(value.get("columns"),"列数",1,24),
        "step_x":integer(value.get("step_x"),"列间距",2,width),
        "step_y":integer(value.get("step_y"),"行间距",2,height),
        "focus":integer(value.get("focus"),"当前行",1,rows),
        "radius":integer(value.get("radius"),"寻点半宽",1,40),
        "cutoff":integer(value.get("cutoff"),"暗点亮度上限",1,254),
    }


def defaults(size):
    width,height=size
    return settings({"origin_x":width//5,"origin_y":height//4,"rows":5,"columns":7,
                     "step_x":max(2,width//10),"step_y":max(2,height//10),"focus":1,
                     "radius":15,"cutoff":115},size)


def point(image, x, y, config):
    rgb=image[y,x]
    luma=float(rgb @ LUMA)
    return {"x":x,"y":y,"rgb":rgb.tolist(),"brightness":luma,"dark":luma<=config["cutoff"]}


def dark_center(mask, x, y, radius):
    """Legacy window-local centroid; retained for direct callers."""
    height,width=mask.shape
    x0,x1=max(0,x-radius),min(width-1,x+radius)
    y0,y1=max(0,y-radius),min(height-1,y+radius)
    if x0>x1 or y0>y1:
        return None
    ys,xs=np.nonzero(mask[y0:y1+1,x0:x1+1])
    if len(xs) < 3:
        return None
    return {"x":x0+float(xs.mean()),"y":y0+float(ys.mean()),"support":int(len(xs))}


def dark_mask(image, cutoff):
    """Eligible dot/bridge pixels.

    The existing luma threshold decides "dark"; additionally a pixel with any
    RGB channel clipped at 0 or 255 may neither form a dot nor bridge a group.
    """
    rgb=np.asarray(image)
    if rgb.ndim == 2:
        rgb=np.repeat(rgb[...,None],3,axis=2)
    rgb=rgb[...,:3]
    luma=rgb @ LUMA
    clipped=(rgb == 0).any(axis=-1) | (rgb == 255).any(axis=-1)
    return (luma <= cutoff) & ~clipped


def dark_groups(source, cutoff=None):
    """Four-connected eligible-dark groups with full-group centroids.

    ``source`` is an RGB original photo (thresholded with ``cutoff``) or a
    ready-made 2D eligibility mask.  Centroids and support always describe the
    complete group, never just the slice falling inside a search window.
    """
    array=np.asarray(source)
    if array.ndim == 3:
        mask=dark_mask(array,cutoff)
    else:
        mask=array.astype(bool,copy=False)
    labels,count=ndimage.label(mask,structure=CROSS)
    flat=labels.ravel()
    support=np.bincount(flat)
    height,width=mask.shape
    columns=np.broadcast_to(np.arange(width)[None,:],mask.shape)
    rows=np.broadcast_to(np.arange(height)[:,None],mask.shape)
    minlength=count+1
    sum_x=np.bincount(flat,weights=columns.ravel(),minlength=minlength)
    sum_y=np.bincount(flat,weights=rows.ravel(),minlength=minlength)
    groups=[]
    for label in range(1,minlength):
        size=int(support[label])
        if size == 0:
            continue
        groups.append({"id":label,"x":float(sum_x[label]/size),
                       "y":float(sum_y[label]/size),"support":size})
    return groups


# Natural-language aliases for the same complete-group extraction.
eligible_mask=dark_mask
solid_mask=dark_mask
connected_groups=dark_groups
connected_dark_groups=dark_groups


def assign_row_groups(nominal_xs, nominal_y, radius, groups):
    """Match one complete dark group to at most one cell of a nominal row.

    A group is a legal candidate only when its full-group centroid lies inside
    or on the edge of the cell's original square search window.  Adopted cells
    run left to right with strictly increasing centroid X.  Among legal
    matchings we maximise claimed cells first, then minimise total squared
    centroid-to-nominal distance; residual ties favour earlier columns.
    Returns one group (or ``None``) per nominal X.
    """
    columns=list(nominal_xs)
    count_columns=len(columns)
    half=float(radius)
    near_y=[group for group in groups
            if group.get("support",3) >= 3 and abs(group["y"]-nominal_y) <= half]
    near_y.sort(key=lambda group:(group["x"],group["y"],group.get("id",0)))
    count_groups=len(near_y)
    group_x=[group["x"] for group in near_y]

    # table[j][k] = best score using the first j columns and first k groups.
    zero=(0,0.0,0)
    table=[[zero]*(count_groups+1) for _ in range(count_columns+1)]
    for j in range(1,count_columns+1):
        nominal_x=columns[j-1]
        row=table[j]
        previous=table[j-1]
        for k in range(1,count_groups+1):
            best=max(previous[k],row[k-1])  # skip column / skip group
            group=near_y[k-1]
            if abs(group["x"]-nominal_x) <= half:
                # Only groups whose X is strictly smaller may precede this one.
                smaller=int(np.searchsorted(group_x,group["x"],side="left"))
                more,neg_cost,tie=previous[smaller]
                dx=group["x"]-nominal_x
                dy=group["y"]-nominal_y
                cost=dx*dx+dy*dy
                candidate=(more+1,neg_cost-cost,tie+(count_columns-j+1))
                if candidate > best:
                    best=candidate
            row[k]=best

    assigned=[None]*count_columns
    j,k=count_columns,count_groups
    while j > 0 and k > 0:
        current=table[j][k]
        if current == table[j][k-1]:
            k-=1
            continue
        if current == table[j-1][k]:
            j-=1
            continue
        group=near_y[k-1]
        assigned[j-1]=group
        k=int(np.searchsorted(group_x,group["x"],side="left"))
        j-=1
    return assigned


def row_measurements(source, config, row, groups=None):
    y=config["origin_y"]+(row-1)*config["step_y"]
    nominal_xs=[config["origin_x"]+column*config["step_x"]
                for column in range(config["columns"])]
    if groups is None:
        if isinstance(source,list):  # already-extracted group dictionaries
            groups=source
        else:
            groups=dark_groups(source,config["cutoff"])
    assigned=assign_row_groups(nominal_xs,y,config["radius"],groups)
    cells=[]
    for column,(x,group) in enumerate(zip(nominal_xs,assigned),start=1):
        cell={"row":row,"column":column,"nominal_x":x,"nominal_y":y,"center":None}
        if group is not None:
            center={"x":group["x"],"y":group["y"],"support":int(group["support"])}
            cell["center"]=center
            cell.update(dx=center["x"]-x,dy=center["y"]-y)
        cells.append(cell)
    return cells


# Descriptive alias for direct callers/tests.
measure_row=row_measurements


def report(image, config):
    # One extraction feeds every row, the focus reading, CSV and PNG exports.
    groups=dark_groups(image,config["cutoff"])
    grid=[row_measurements(None,config,row,groups)
          for row in range(1,config["rows"]+1)]
    selected=grid[config["focus"]-1]
    current=[cell for cell in selected if cell["center"] is not None]
    reading=None
    if current:
        rms=math.sqrt(sum(cell["dx"]**2+cell["dy"]**2 for cell in current)/len(current))
        reading={"row":config["focus"],"rms":rms,"valid":len(current),"columns":len(selected)}
    return {"reading":reading,"profile":selected,"grid":grid,"focus":config["focus"],
            "row_counts":[{"row":i+1,"valid":sum(cell["center"] is not None for cell in row)}
                          for i,row in enumerate(grid)]}


def practice():
    width,height=782,474
    cfg=settings({"origin_x":154,"origin_y":131,"rows":6,"columns":9,"step_x":58,
                  "step_y":43,"focus":1,"radius":16,"cutoff":115},(width,height))
    y,x=np.indices((height,width))
    field=(97 <= x)&(x <= 687)&(73 <= y)&(y <= 402)
    texture=4*np.sin(x*.08+y*.1)+3*np.sin(x*.41-y*.53)
    tone=np.where(field,215,53)+texture
    image=Image.fromarray((tone[...,None]+np.array([-6,4,11])).clip(0,255).astype("uint8"),"RGB")
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((97,73,687,402),radius=8,outline="#acbcc2",width=2)
    for row in range(cfg["rows"]):
        for column in range(cfg["columns"]):
            if (row,column)==(4,6):
                continue
            cx=cfg["origin_x"]+column*cfg["step_x"]+row-2+round(.11*(column-4)**2*(row-1))
            cy=cfg["origin_y"]+row*cfg["step_y"]+row-2+round(2*math.sin(column*.55+row*.4))
            dot=4+int((row+column)%4==2)
            draw.ellipse((cx-dot,cy-dot,cx+dot,cy+dot),fill=(49+row,58+column,67))
    draw.text((103,38),"CAMERA GRID / DOT CENTRES",fill="#d4e5e6",font=ImageFont.load_default(size=14))
    draw.text((104,431),"SIMULATED CALIBRATION PHOTO",fill="#c7d9da",font=ImageFont.load_default(size=12))
    return image.size,png(image),cfg
