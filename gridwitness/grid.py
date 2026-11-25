"""Measure actual dark-dot centroids near a nominal calibration grid."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import integer

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126,0.7152,0.0722])


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
    height,width=mask.shape
    x0,x1=max(0,x-radius),min(width-1,x+radius)
    y0,y1=max(0,y-radius),min(height-1,y+radius)
    if x0>x1 or y0>y1:
        return None
    ys,xs=np.nonzero(mask[y0:y1+1,x0:x1+1])
    if len(xs) < 3:
        return None
    return {"x":x0+float(xs.mean()),"y":y0+float(ys.mean()),"support":int(len(xs))}


def row_measurements(mask, config, row):
    y=config["origin_y"]+(row-1)*config["step_y"]
    cells=[]
    for column in range(1,config["columns"]+1):
        x=config["origin_x"]+(column-1)*config["step_x"]
        center=dark_center(mask,x,y,config["radius"])
        cell={"row":row,"column":column,"nominal_x":x,"nominal_y":y,"center":center}
        if center:
            cell.update(dx=center["x"]-x,dy=center["y"]-y)
        cells.append(cell)
    return cells


def report(image, config):
    mask=(image @ LUMA)<=config["cutoff"]
    grid=[row_measurements(mask,config,row) for row in range(1,config["rows"]+1)]
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
