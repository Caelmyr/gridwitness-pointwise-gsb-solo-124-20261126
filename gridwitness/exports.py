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
    writer.writerow(("row","column","nominal_x","nominal_y","source_center_x","source_center_y","dark_pixels","dx","dy"))
    for cell in result["profile"]:
        center=cell["center"]
        actual=(f'{center["x"]:.3f}',f'{center["y"]:.3f}',center["support"],f'{cell["dx"]:.3f}',f'{cell["dy"]:.3f}') if center else ("","",0,"","")
        writer.writerow((cell["row"],cell["column"],cell["nominal_x"],cell["nominal_y"],*actual))
    return target.getvalue().encode()


def proof(image, card, result):
    height,width=image.shape[:2]
    output=Image.new("RGB",(max(430,width),height+64),"#203747")
    output.paste(Image.fromarray(image),(0,0))
    draw=ImageDraw.Draw(output)
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
    reading=result["reading"]
    detail=(f'Row {reading["row"]} | RMS displacement {reading["rms"]:.2f} px | support {reading["valid"]}/{reading["columns"]}'
            if reading else f'Row {result["focus"]} | no supported dot center')
    cfg=card["settings"]
    draw.text((14,height+13),detail,fill="#e8eef3")
    draw.text((14,height+35),f'Nominal origin ({cfg["origin_x"]}, {cfg["origin_y"]})',fill="#b3dde0")
    return png(output)


def package(card, original, image, result):
    memory=BytesIO()
    with ZipFile(memory,"w",ZIP_DEFLATED) as stream:
        stream.writestr("target.png",original)
        stream.writestr("reading.json",json.dumps({"card":card,"grid":result["grid"]},ensure_ascii=False,indent=2))
        stream.writestr("grid-profile.csv",trace_table(result))
        stream.writestr("grid-proof.png",proof(image,card,result))
    return memory.getvalue()
