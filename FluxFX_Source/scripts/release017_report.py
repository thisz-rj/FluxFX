"""0.16 versus 0.17 figures and repeated-trial summaries; requires NumPy/Pillow."""
from pathlib import Path
from statistics import median
import json,gzip,shutil
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'test-results/release017'
OLD=ROOT/'test-results/detail-comparison'
OUT=ROOT/'docs/validation/motion-017'
def font(n):return ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',n)
def read(folder,tag,n):
    d=json.loads((folder/(tag+'.json')).read_text());assert d['status']=='PASS'
    a=np.frombuffer(gzip.decompress((folder/(tag+'.f32.gz')).read_bytes()),dtype='<f4').reshape((n,)*3)
    assert np.isfinite(a).all()
    d['density_metrics']={'peak':float(a.max()),'integrated_density':float(a.sum(dtype=np.float64)/n**3)}
    return d,a

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    summary={'scope':'64³: three trials each with 0.16 configuration rerun; 128³: one 0.17 trial against archived 0.16. Two simulated seconds per run; matched source settings, changed transport/pressure/time integration. Simulation plus GPU synchronization, excluding normal UI rendering.','cases':[]}
    figure=Image.new('RGB',(1400,1290),'#f8fafc');draw=ImageDraw.Draw(figure)
    draw.text((30,18),'FluxFX smoke motion: 0.16 versus 0.17',font=font(31),fill='#0f172a')
    draw.text((30,60),'Two simulated seconds · same emission and opacity · 0.17 uses limited velocity correction',font=font(20),fill='#475569')
    for row,case in enumerate(('stationary','moving','multiple')):
        for j,n in enumerate((64,128)):
            rowdata={'case':case,'grid':n}
            for k,variant in enumerate(('legacy','release')):
                trials=[];frames=[]
                count=3 if n==64 else 1
                for trial in range(1,count+1):
                    folder=OLD if n==128 and variant=='legacy' else DATA
                    tag=f'calibrated-{case}-{n}' if folder==OLD else f'{variant}-t{trial}-{case}-{n}'
                    report,field=read(folder,tag,n)
                    if variant=='release':assert max(q['ratio'] for q in report['projection_samples'])<.1
                    trials.append(report);frames+=report['frame_ms']
                    (OUT/(tag+'.json')).write_text(json.dumps(report,indent=2))
                    if trial==1:
                        left=30+(j*2+k)*342;top=132+row*374
                        opacity=1-np.exp(-3*field.sum(axis=1)/n)
                        tile=Image.fromarray(np.uint8(np.clip(opacity[::-1],0,1)*255)).convert('RGB').resize((300,300),Image.Resampling.NEAREST)
                        figure.paste(tile,(left,top))
                        draw.text((left,top-28),f'{case.title()} · {"0.16" if k==0 else "0.17"} {n}³',font=font(20),fill='#0f172a')
                        draw.text((left,top+310),f"Integral {report['density_metrics']['integrated_density']:.4f} · peak {field.max():.2f}",font=font(16),fill='#475569')
                seconds=[r['simulation_evaluation_seconds'] for r in trials]
                rowdata[variant]={'trials':count,'median_seconds':median(seconds),'min_seconds':min(seconds),'max_seconds':max(seconds),'frame_median_ms':median(frames),'frame_p95_ms':float(np.percentile(frames,95)),'worst_frame_ms':max(frames),'field_mib':trials[0]['field_bytes']/2**20,'steps':[r['steps'] for r in trials],'density':trials[0]['density_metrics'],'max_sampled_divergence_ratio':max(q['ratio'] for r in trials for q in r.get('projection_samples',[r['projection']]))}
            rowdata['wall_time_change_percent']=100*(rowdata['release']['median_seconds']/rowdata['legacy']['median_seconds']-1)
            summary['cases'].append(rowdata)
    figure.save(OUT/'density-comparison.png')
    chart=Image.new('RGB',(1200,560),'#f8fafc');d=ImageDraw.Draw(chart)
    d.text((30,20),'64³ simulation cost per output frame',font=font(30),fill='#0f172a')
    d.text((30,64),'Median of 180 frames/configuration; three runs. Bars exclude ordinary Blender UI/render work.',font=font(18),fill='#475569')
    for i,c in enumerate(q for q in summary['cases'] if q['grid']==64):
        y=140+i*120
        d.text((30,y+20),c['case'].title(),font=font(22),fill='#0f172a')
        for offset,key,color in ((0,'legacy','#64748b'),(42,'release','#0d9488')):
            value=c[key]['frame_median_ms'];end=220+value*14
            d.rectangle((220,y+offset,end,y+offset+30),fill=color)
            d.text((end+10,y+offset+4),f'{"0.16" if key=="legacy" else "0.17"}: {value:.1f} ms',font=font(18),fill='#0f172a')
    x=220+(1000/30)*14;d.line((x,116,x,480),fill='#ea580c',width=2)
    d.text((x-60,498),'33.3 ms target',font=font(18),fill='#c2410c')
    chart.save(OUT/'timing-comparison.png')
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))
if __name__=='__main__':run()
