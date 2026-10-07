"""Render archived numerical XZ slices. Development dependency: Pillow."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/validation/colliders020'
FONT='/System/Library/Fonts/Helvetica.ttc'
def font(n):return ImageFont.truetype(FONT,n)
canvas=Image.new('RGB',(1560,1280),(17,22,30));draw=ImageDraw.Draw(canvas)
draw.text((36,25),'FluxFX 0.20 | Static collider comparison',font=font(32),fill='white')
draw.text((36,72),'64 cubed | 6 simulated seconds | XZ slice at y = 0.5 | density 0 to 0.5 (clipped)',font=font(20),fill=(177,193,211))
for row,name in enumerate(('sphere','box')):
 for col,(label,title) in enumerate((('baseline','Jacobi + Fast'),('fast','Masked multigrid + Fast'),('detailed','Masked multigrid + Detailed'))):
  raw=json.loads((DATA/f'collision-slice-{label}-{name}.json').read_text())
  case=next(c for c in json.loads((DATA/f'collision-benchmark-{label}.json').read_text())['cases'] if c['name']==name)
  n=raw['n'];im=Image.new('RGB',(n,n));pixels=[]
  for z in reversed(range(n)):
   for x in range(n):
    i=x+n*z;v=min(1,max(0,raw['density'][i]/.5))
    pixels.append((77,104,132) if raw['solid'][i] else tuple(round(a+(b-a)*v) for a,b in zip((9,14,22),(243,248,255))))
  im.putdata(pixels);im=im.resize((468,468),Image.Resampling.NEAREST)
  x=36+col*508;y=122+row*562
  draw.text((x,y),name.title()+' | '+title,font=font(21),fill='white')
  canvas.paste(im,(x,y+37))
  draw.rectangle((x,y+37,x+467,y+504),outline=(65,77,92))
  draw.text((x,y+515),f"{case['simulation_speed']:.3f}x sim/wall  |  RMS {case['projection']['rms_after']:.5f}",font=font(19),fill=(184,202,220))
draw.text((36,1240),'Solid cells: blue-gray. Same inputs; methods produce different flows and adaptive workloads.',font=font(19),fill=(177,193,211))
canvas.save(DATA/'collision-comparison.png')
