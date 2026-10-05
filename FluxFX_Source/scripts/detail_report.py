"""Render reproducible density comparisons using NumPy/Pillow, outside Blender."""
from pathlib import Path
import json,gzip,math
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'test-results/detail-comparison'
OLD=ROOT/'test-results/comparison'
OUT=ROOT/'docs/validation/detail-016'
def font(n):return ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',n)
def read(folder,tag,n):
    report=json.loads((folder/(tag+'.json')).read_text())
    assert report['status']=='PASS'
    field=np.frombuffer(gzip.decompress((folder/(tag+'.f32.gz')).read_bytes()),dtype='<f4').reshape(n,n,n)
    assert np.isfinite(field).all()
    report['density_metrics']={'peak':float(field.max()),'integrated_density':float(field.sum(dtype=np.float64)/n**3)}
    report['frame_median_ms']=float(np.median(report['frame_ms']))
    report['frame_p95_ms']=float(np.percentile(report['frame_ms'],95))
    (OUT/(tag+'.json')).write_text(json.dumps(report,indent=2))
    return report,field

def tile(image,draw,field,left,top,label,report):
    n=len(field);opacity=1-np.exp(-3*field.sum(axis=1)/n)
    picture=Image.fromarray(np.uint8(np.clip(opacity[::-1],0,1)*255)).convert('RGB').resize((300,300),Image.Resampling.NEAREST)
    image.paste(picture,(left,top))
    draw.text((left,top-28),label,font=font(18),fill='#0f172a')
    draw.text((left,top+310),f"Integral {report['density_metrics']['integrated_density']:.4f} · peak {field.max():.2f}",font=font(16),fill='#475569')

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    summary={'scope':'Single trials, 2 simulated seconds each; native reference reused from 0.15. Different solver/source models, not equal-quality speedups.','variants':[],'cases':[]}
    image=Image.new('RGB',(1740,470),'#f8fafc');d=ImageDraw.Draw(image)
    d.text((30,16),'Stationary 64³: separate transport, curl, and emission changes',font=font(27),fill='#0f172a')
    variants=[('Fast','fluxfx',DATA),('Detailed','detailed',DATA),('Detailed + curl','curl',DATA),('Target / solid + curl','calibrated',DATA),('Native reference','mantaflow',OLD)]
    for i,(label,tag,folder) in enumerate(variants):
        report,field=read(folder,f'{tag}-stationary-64',64)
        tile(image,d,field,30+i*342,100,label,report)
        summary['variants'].append({'variant':tag,'seconds':report['simulation_evaluation_seconds'],'frame_median_ms':report['frame_median_ms'],'density':report['density_metrics']})
    image.save(OUT/'quality-variants.png')
    image=Image.new('RGB',(1400,1290),'#f8fafc');d=ImageDraw.Draw(image)
    d.text((30,18),'Smoke detail and source calibration after 2 simulated seconds',font=font(29),fill='#0f172a')
    d.text((30,60),'Same opacity scale and 1 m domain. Native reference reused; no claim of equivalent flow or quality.',font=font(19),fill='#475569')
    for row,case in enumerate(('stationary','moving','multiple')):
        for j,n in enumerate((64,128)):
            reports={}
            for k,(tag,folder,label) in enumerate((('mantaflow',OLD,'Native'),('calibrated',DATA,'FluxFX 0.16'))):
                report,field=read(folder,f'{tag}-{case}-{n}',n);reports[tag]=report
                tile(image,d,field,30+(j*2+k)*342,132+row*374,f'{case.title()} · {label} {n}³',report)
            f=reports['calibrated'];native=reports['mantaflow']
            summary['cases'].append({'case':case,'grid':n,'fluxfx_seconds':f['simulation_evaluation_seconds'],'native_reference_seconds':native['simulation_evaluation_seconds'],'frame_median_ms':f['frame_median_ms'],'frame_p95_ms':f['frame_p95_ms'],'steps':f['steps'],'field_mib':f['field_bytes']/2**20,'density':f['density_metrics'],'native_density':native['density_metrics'],'integral_ratio_native_over_fluxfx':native['density_metrics']['integrated_density']/f['density_metrics']['integrated_density']})
    image.save(OUT/'density-comparison.png')
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__':run()
