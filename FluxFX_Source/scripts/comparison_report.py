"""Build static figures and machine-readable summary from completed comparison runs.
Requires NumPy/Pillow only for reporting, never for the add-on.
"""
from pathlib import Path
import json,gzip,math
import numpy as np
from PIL import Image,ImageDraw,ImageFont

def font(size):return ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',size)
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'test-results/comparison'
OUT=ROOT/'docs/validation/comparison-015'

def stats(a):
    ordered=sorted(a)
    return dict(median_ms=float(np.median(a)),p95_ms=ordered[math.ceil(.95*len(a))-1],max_ms=max(a))

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    summary={'scope':'Single trial per case, 60 frames at 30 FPS = 2 simulated seconds. Workflow timings, not matched-quality solver speedups.', 'cases':[]}
    image=Image.new('RGB',(1460,1330),'#f8fafc');draw=ImageDraw.Draw(image)
    draw.text((40,24),'Smoke after 2 simulated seconds',font=font(32),fill='#0f172a')
    draw.text((40,68),'Identical opacity scale and 1 m domain. Different source models; not an equal-quality proof.',font=font(20),fill='#475569')
    for row,case in enumerate(('stationary','moving','multiple')):
        for n in (64,128):
            reports={}
            for engine in ('mantaflow','fluxfx'):
                tag=f'{engine}-{case}-{n}'
                report=json.loads((DATA/(tag+'.json')).read_text())
                assert report['status']=='PASS' and len(report['frame_ms'])==60
                assert report['duration_seconds']==2
                if engine=='mantaflow':assert report['velocity_max_abs']>0
                raw=gzip.decompress((DATA/(tag+'.f32.gz')).read_bytes())
                field=np.frombuffer(raw,dtype='<f4').reshape(n,n,n)
                assert np.isfinite(field).all() and field.max()>0
                mass=float(field.sum(dtype=np.float64))/n**3
                zprofile=field.sum(axis=(1,2),dtype=np.float64)
                report['density_metrics']={'peak':float(field.max()),'integrated_density':mass,
                    'centroid_z_m':float(np.dot(zprofile,(np.arange(n)+.5)/n)/zprofile.sum()),
                    'occupied_fraction_density_above_0_01':float((field>.01).mean())}
                report['output_frame_timing']=stats(report['frame_ms'])
                # Fixed opacity scale, same domain and view for both engines.
                opacity=1-np.exp(-3*field.sum(axis=1)/n)
                col=(0 if n==64 else 2)+(1 if engine=='fluxfx' else 0)
                left=40+col*350;top=150+row*375
                tile=Image.fromarray(np.uint8(np.clip(opacity[::-1],0,1)*255)).convert('RGB').resize((310,310),Image.Resampling.NEAREST)
                image.paste(tile,(left,top))
                draw.text((left,top-30),f"{case.title()} / {'FluxFX' if engine=='fluxfx' else 'Mantaflow'} {n}³",font=font(18),fill='#0f172a')
                draw.text((left,top+320),f"Density peak {field.max():.2f} · integral {mass:.4f}",font=font(16),fill='#475569')
                (OUT/(tag+'.json')).write_text(json.dumps(report,indent=2))
                reports[engine]=report
            summary['cases'].append({'case':case,'grid':n,
                'fluxfx_seconds':reports['fluxfx']['simulation_evaluation_seconds'],
                'mantaflow_seconds':reports['mantaflow']['simulation_evaluation_seconds'],
                'workflow_time_ratio_native_over_fluxfx':reports['mantaflow']['simulation_evaluation_seconds']/reports['fluxfx']['simulation_evaluation_seconds'],
                'fluxfx_frame':reports['fluxfx']['output_frame_timing'],
                'mantaflow_frame':reports['mantaflow']['output_frame_timing'],
                'fluxfx_steps':reports['fluxfx']['steps'],
                'fluxfx_field_mib':reports['fluxfx']['field_bytes']/2**20,
                'native_peak_process_rss_mib':reports['mantaflow']['peak_process_rss_bytes']/2**20,
                'native_cache_mib':reports['mantaflow']['cache_bytes']/2**20,
                'fluxfx_common_preview_ms':reports['fluxfx']['common_preview']['median_ms'],
                'native_common_preview_ms':reports['fluxfx']['native_common_preview']['median_ms'],
                'fluxfx_density':reports['fluxfx']['density_metrics'],'native_density':reports['mantaflow']['density_metrics']})
    draw.text((40,1290),'View: X horizontal, Z vertical; density integrated along Y. White = greater opacity.',font=font(18),fill='#475569')
    image.save(OUT/'density-comparison.png')
    chart=Image.new('RGB',(1440,800),'#f8fafc');d=ImageDraw.Draw(chart)
    d.text((40,25),'Wall time to advance 2 simulated seconds',font=font(32),fill='#0f172a')
    d.text((40,74),'One run per case. Native evaluation includes Replay cache; source models differ.',font=font(20),fill='#475569')
    d.rectangle((40,116,60,136),fill='#64748b');d.text((70,115),'Mantaflow: evaluation + cache',font=font(18),fill='#334155')
    d.rectangle((550,116,570,136),fill='#0d9488');d.text((580,115),'FluxFX: adaptive simulation + GPU sync',font=font(18),fill='#334155')
    largest=max(c['mantaflow_seconds'] for c in summary['cases'])
    largest=max(largest,max(c['fluxfx_seconds'] for c in summary['cases']))
    limit=math.ceil(largest/20)*20
    for tick in np.linspace(0,limit,6):
        x=260+tick/limit*1020
        d.line((x,180,x,715),fill='#e2e8f0',width=1)
        d.text((x-15,735),f'{tick:.0f} s',font=font(17),fill='#64748b')
    for i,c in enumerate(summary['cases']):
        y=192+i*85
        d.text((40,y+9),f"{c['case'].title()} {c['grid']}³",font=font(20),fill='#0f172a')
        for offset,key,color in ((0,'mantaflow_seconds','#64748b'),(30,'fluxfx_seconds','#0d9488')):
            end=260+c[key]/limit*1020
            d.rectangle((260,y+offset,end,y+offset+22),fill=color)
            d.text((end+8,y+offset),f'{c[key]:.2f} s',font=font(17),fill='#334155')
    chart.save(OUT/'timing-comparison.png')
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':run()
