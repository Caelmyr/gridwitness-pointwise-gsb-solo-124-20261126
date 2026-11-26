"""Measure actual dark-dot centroids near a nominal calibration grid."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from image_lab.validation import Invalid, integer, number

from .photo import decode, pixels, png, MAX_IMAGE_BYTES


LUMA = np.array([0.2126,0.7152,0.0722])
MAX_CANDIDATE_COLUMNS = 12
MIN_INSIDE_WITNESSES = 4


def column_list(value, label, columns):
    if not isinstance(value, list):
        raise Invalid(label + "必须是列号列表")
    if len(value) > MAX_CANDIDATE_COLUMNS:
        raise Invalid(label + "最多指定" + str(MAX_CANDIDATE_COLUMNS) + "个候选列")
    result = []
    for item in value:
        column = integer(item, label, 1, columns)
        if column not in result:
            result.append(column)
    return sorted(result)


def settings(value, size):
    width,height=size
    rows=integer(value.get("rows"),"行数",1,24)
    config={
        "origin_x":integer(value.get("origin_x"),"首点 X",0,width-1),
        "origin_y":integer(value.get("origin_y"),"首点 Y",0,height-1),
        "rows":rows,"columns":integer(value.get("columns"),"列数",1,24),
        "step_x":integer(value.get("step_x"),"列间距",2,width),
        "step_y":integer(value.get("step_y"),"行间距",2,height),
        "focus":integer(value.get("focus"),"当前行",1,rows),
        "radius":integer(value.get("radius"),"寻点半宽",1,40),
        "cutoff":integer(value.get("cutoff"),"暗点亮度上限",1,254),
        "line_angle":number(value.get("line_angle",5.0),"参考线角度限值",0,45),
    }
    config["line_left"]=column_list(value.get("line_left",[]),"左端候选列",config["columns"])
    config["line_right"]=column_list(value.get("line_right",[]),"右端候选列",config["columns"])
    return config


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


def reference_line(profile, config):
    """Pick one measured-centroid line between left and right candidate columns."""
    def fail(reason, reason_en, candidates=()):
        return {"adopted": None, "reason": reason, "reason_en": reason_en,
                "candidates": list(candidates)}

    left_columns = config["line_left"]
    right_columns = config["line_right"]
    if not left_columns or not right_columns:
        return fail("未指定左右候选列：请在当前行左右各填至少一个候选格列。",
                    "no candidate columns specified")
    by_column = {cell["column"]: cell for cell in profile}

    def measured(column):
        cell = by_column.get(column)
        return cell if cell and cell["center"] is not None else None

    raw_pairs = [(lc, rc) for lc in left_columns for rc in right_columns if lc < rc]
    if not raw_pairs:
        return fail("候选列没有满足左列在右列左侧的组合。",
                    "no left/right candidate pair with left column before right column")
    candidates = []
    rejected_angles = 0
    for lc, rc in raw_pairs:
        left, right = measured(lc), measured(rc)
        if left is None or right is None:
            continue
        lc_x, lc_y = left["center"]["x"], left["center"]["y"]
        rc_x, rc_y = right["center"]["x"], right["center"]["y"]
        dx, dy = rc_x - lc_x, rc_y - lc_y
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        if angle > config["line_angle"] + 1e-9:
            rejected_angles += 1
            continue
        inside = [cell for cell in profile
                  if lc < cell["column"] < rc and cell["center"] is not None]
        span_cells = [cell for cell in profile
                      if lc <= cell["column"] <= rc and cell["center"] is not None]
        candidates.append({
            "left_column": lc, "right_column": rc,
            "angle": angle, "inside_valid": len(inside),
            "witness_count": len(span_cells), "span": rc - lc, "length": length,
            "dx": dx, "dy": dy,
            "normal_x": -dy / length, "normal_y": dx / length,
        })
    if not candidates:
        if rejected_angles:
            return fail("候选端点连线的横向倾角都超过限值 " + str(config["line_angle"]) + "°。",
                        "every candidate line exceeds the angle limit of "
                        + str(config["line_angle"]) + " deg")
        return fail("候选格缺少实测质心：端点必须选到真有暗点证据的格。",
                    "candidate endpoint cells lack measured centroids")
    enough = [candidate for candidate in candidates
              if candidate["inside_valid"] >= MIN_INSIDE_WITNESSES]
    summary = [{key: candidate[key] for key in
                ("left_column", "right_column", "angle", "inside_valid", "witness_count", "span")}
               for candidate in candidates[:64]]
    if not enough:
        best = max(candidates, key=lambda c: c["inside_valid"])
        return fail(("端点之间只有 " + str(best["inside_valid"]) + " 个实测格可核，"
                     "至少需要 " + str(MIN_INSIDE_WITNESSES) + " 个；缺证格不补。"),
                    ("only " + str(best["inside_valid"]) + " measured cells between endpoints, "
                     + str(MIN_INSIDE_WITNESSES) + " required; unsupported cells are not filled"),
                    summary)
    ordered = sorted(enumerate(enough), key=lambda item: item[0])
    by_angle = sorted(ordered, key=lambda item: (item[1]["angle"], item[0]))
    by_coverage = sorted(ordered, key=lambda item: (-item[1]["witness_count"], item[0]))
    rank = {item[0]: {} for item in ordered}
    for position, (index, _) in enumerate(by_angle):
        rank[index]["angle"] = position
    for position, (index, _) in enumerate(by_coverage):
        rank[index]["coverage"] = position
    chosen_index, chosen = min(ordered, key=lambda item: (
        rank[item[0]]["angle"] + rank[item[0]]["coverage"],
        item[1]["angle"], -item[1]["witness_count"], -item[1]["span"], item[0]))
    left_cell, right_cell = measured(chosen["left_column"]), measured(chosen["right_column"])

    def signed_offset(cell):
        center = cell["center"]
        return ((center["x"] - left_cell["center"]["x"]) * chosen["normal_x"]
                + (center["y"] - left_cell["center"]["y"]) * chosen["normal_y"])

    offsets = {cell["column"]: signed_offset(cell) for cell in profile
               if chosen["left_column"] <= cell["column"] <= chosen["right_column"]
               and cell["center"] is not None}
    values = list(offsets.values())
    rms = math.sqrt(sum(value * value for value in values) / len(values))
    adopted = {
        "left_column": chosen["left_column"], "right_column": chosen["right_column"],
        "left_x": left_cell["center"]["x"], "left_y": left_cell["center"]["y"],
        "right_x": right_cell["center"]["x"], "right_y": right_cell["center"]["y"],
        "angle": chosen["angle"], "length": chosen["length"],
        "normal_x": chosen["normal_x"], "normal_y": chosen["normal_y"],
        "witness_count": chosen["witness_count"], "inside_valid": chosen["inside_valid"],
        "rms_offset": rms, "max_abs_offset": max(abs(value) for value in values),
        "offsets": [{"column": column, "offset": offsets[column]}
                    for column in sorted(offsets)],
    }
    return {"adopted": adopted,
            "reason": "", "reason_en": "",
            "candidates": [{key: candidate[key] for key in
                            ("left_column", "right_column", "angle", "inside_valid",
                             "witness_count", "span")}
                           for candidate in enough[:64]]}


def report(image, config):
    mask=(image @ LUMA)<=config["cutoff"]
    grid=[row_measurements(mask,config,row) for row in range(1,config["rows"]+1)]
    selected=grid[config["focus"]-1]
    reference=reference_line(selected,config)
    offsets={item["column"]:item["offset"] for item in reference["adopted"]["offsets"]} \
        if reference["adopted"] else {}
    for cell in selected:
        cell["line_offset"]=offsets.get(cell["column"])
    current=[cell for cell in selected if cell["center"] is not None]
    reading=None
    if current:
        rms=math.sqrt(sum(cell["dx"]**2+cell["dy"]**2 for cell in current)/len(current))
        reading={"row":config["focus"],"rms":rms,"valid":len(current),"columns":len(selected)}
    return {"reading":reading,"profile":selected,"grid":grid,"focus":config["focus"],
            "reference":reference,
            "row_counts":[{"row":i+1,"valid":sum(cell["center"] is not None for cell in row)}
                          for i,row in enumerate(grid)]}


def practice():
    width,height=782,474
    cfg=settings({"origin_x":154,"origin_y":131,"rows":6,"columns":9,"step_x":58,
                  "step_y":43,"focus":1,"radius":16,"cutoff":115,
                  "line_left":[1,2,3],"line_right":[7,8,9],"line_angle":3.0},(width,height))
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
