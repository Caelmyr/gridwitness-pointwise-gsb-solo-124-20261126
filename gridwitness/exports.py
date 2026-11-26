"""Export the nominal grid and its source-coordinate measured dot centres."""
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json

from PIL import Image,ImageDraw

from .photo import png


def trace_table(result):
    target=StringIO()
    writer=csv.writer(target)
    writer.writerow(("row","column","nominal_x","nominal_y","source_center_x","source_center_y",
                     "dark_pixels","dx","dy","line_offset"))
    for cell in result["profile"]:
        center=cell["center"]
        actual=(f'{center["x"]:.3f}',f'{center["y"]:.3f}',center["support"],
                f'{cell["dx"]:.3f}',f'{cell["dy"]:.3f}') if center else ("","",0,"","")
        line_offset=f'{cell["line_offset"]:.3f}' if cell.get("line_offset") is not None else ""
        writer.writerow((cell["row"],cell["column"],cell["nominal_x"],cell["nominal_y"],
                         *actual,line_offset))
    return target.getvalue().encode()


def proof(image, card, result):
    height,width=image.shape[:2]
    output=Image.new("RGB",(max(430,width),height+88),"#203747")
    output.paste(Image.fromarray(image),(0,0))
    draw=ImageDraw.Draw(output)
    reference=result.get("reference",{})
    adopted=reference.get("adopted")
    span=range(adopted["left_column"],adopted["right_column"]+1) if adopted else ()
    for cells in result["grid"]:
        for cell in cells:
            x,y=cell["nominal_x"],cell["nominal_y"]
            draw.line((x-3,y,x+3,y),fill="#4b93a8",width=1)
            draw.line((x,y-3,x,y+3),fill="#4b93a8",width=1)
            center=cell["center"]
            if center:
                ax,ay=center["x"],center["y"]
                color="#f3a259" if cell["row"]==result["focus"] else "#5f6b9f"
                draw.line((x,y,ax,ay),fill=color,width=1)
                draw.ellipse((ax-3,ay-3,ax+3,ay+3),outline=color,width=2)
    if adopted:
        lx,ly,rx,ry=adopted["left_x"],adopted["left_y"],adopted["right_x"],adopted["right_y"]
        draw.line((lx,ly,rx,ry),fill="#f2e46a",width=2)
        for cell in result["profile"]:
            if cell["column"] not in span or not cell["center"]:
                continue
            ax,ay=cell["center"]["x"],cell["center"]["y"]
            endpoint=cell["column"] in (adopted["left_column"],adopted["right_column"])
            radius=6 if endpoint else 4
            draw.ellipse((ax-radius,ay-radius,ax+radius,ay+radius),
                         outline="#f2e46a",width=2 if endpoint else 1)
        draw.text((lx,max(2,ly-15)),f'L{adopted["left_column"]}',fill="#f2e46a")
        draw.text((rx,max(2,ry-15)),f'R{adopted["right_column"]}',fill="#f2e46a")
    reading=result["reading"]
    detail=(f'Row {reading["row"]} | RMS displacement {reading["rms"]:.2f} px | support {reading["valid"]}/{reading["columns"]}'
            if reading else f'Row {result["focus"]} | no supported dot center')
    cfg=card["settings"]
    draw.text((14,height+10),detail,fill="#e8eef3")
    draw.text((14,height+31),f'Nominal origin ({cfg["origin_x"]}, {cfg["origin_y"]})',fill="#b3dde0")
    if adopted:
        line_detail=(f'Reference line L{adopted["left_column"]}->R{adopted["right_column"]} | '
                     f'angle {adopted["angle"]:.3f} deg | witnesses {adopted["witness_count"]} '
                     f'(inside {adopted["inside_valid"]}) | signed offset RMS {adopted["rms_offset"]:.3f} px '
                     f'| below +, above -')
    else:
        line_detail="Reference line: not adopted | " + reference.get("reason_en","no candidate line")
    draw.text((14,height+52),line_detail[:150],fill="#f2e46a" if adopted else "#e0a07a")
    return png(output)


def package(card, original, image, result):
    memory=BytesIO()
    with ZipFile(memory,"w",ZIP_DEFLATED) as stream:
        stream.writestr("target.png",original)
        stream.writestr("reading.json",json.dumps({"card":card,"grid":result["grid"],
                                                   "reference":result.get("reference")},
                                                  ensure_ascii=False,indent=2))
        stream.writestr("grid-profile.csv",trace_table(result))
        stream.writestr("grid-proof.png",proof(image,card,result))
    return memory.getvalue()
