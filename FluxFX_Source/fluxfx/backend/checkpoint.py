"""Versioned local checkpoints for fixed-input, collider-free research runs.

Full scene/timeline caching is deliberately outside this initial format.
"""
from dataclasses import asdict
from math import isfinite, prod
from pathlib import Path
import json
from ..physics.config import GridSpec, validate_dt
from ..physics.pressure import PressureSettings
from .projected import DenseProjectedSmoke


def save_checkpoint(solver, path):
    import numpy as np
    if solver.faulted or solver.solids is not None:
        raise ValueError('Checkpoint v1 requires a healthy solver without colliders')
    meta={'format':'fluxfx-checkpoint-1','settings':asdict(solver.settings),'grid':asdict(solver.grid),
          'time':solver.time,'steps':solver.steps,'last_dt':solver.projector.last_dt}
    fields={'density':solver.read_density(),'temperature':solver.read_temperature(),
            'pressure':solver.device.read(solver.projector.pressure,solver.grid.shape)}
    fields.update({f'velocity{i}':solver.device.read(t,s) for i,(t,s) in enumerate(zip(solver._velocity,solver.grid.face_shapes))})
    if solver.combustion:
        fields.update(fuel=solver.device.read(solver.combustion.fuel,solver.grid.shape),
                      flame=solver.device.read(solver.combustion.flame,solver.grid.shape))
    arrays={k:np.asarray(v,dtype=np.float32) for k,v in fields.items()}
    if any(not np.isfinite(a).all() for a in arrays.values()):raise ValueError('Nonfinite checkpoint state')
    # A failed write leaves the previous checkpoint intact.
    path=Path(path);temporary=path.with_name(path.name+'.tmp')
    try:
        with temporary.open('wb') as stream:np.savez_compressed(stream,metadata=json.dumps(meta),**arrays)
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


def load_checkpoint(path):
    import numpy as np
    with np.load(path,allow_pickle=False) as archive:
        meta=json.loads(str(archive['metadata']))
        if meta['format']!='fluxfx-checkpoint-1':raise ValueError('Unsupported checkpoint format')
        grid=GridSpec(tuple(meta['grid']['shape']),tuple(meta['grid']['extent']))
        options=meta['settings']
        for name in ('velocity','source_center'):options[name]=tuple(options[name])
        settings=PressureSettings(**options)
        if not isfinite(meta['time']) or meta['time']<0 or type(meta['steps']) is not int or meta['steps']<0:
            raise ValueError('Invalid checkpoint clock')
        if meta['last_dt'] is not None:validate_dt(meta['last_dt'])
        shapes={k:grid.shape for k in ('density','temperature','pressure')}
        shapes.update({f'velocity{i}':s for i,s in enumerate(grid.face_shapes)})
        if settings.combustion_enabled:shapes.update(fuel=grid.shape,flame=grid.shape)
        arrays={k:archive[k].copy() for k in shapes}
        for k,a in arrays.items():
            if a.shape!=(prod(shapes[k]),) or not np.isfinite(a).all():raise ValueError('Invalid field: '+k)
            if k in {'density','fuel','flame'} and (a<0).any():raise ValueError('Negative field: '+k)
    solver=DenseProjectedSmoke(grid,settings)
    try:
        solver.upload(arrays['density'].tolist());solver.upload_temperature(arrays['temperature'].tolist())
        solver.upload_velocity([arrays[f'velocity{i}'].tolist() for i in range(3)])
        solver.projector.pressure=solver.device.texture(grid.shape,arrays['pressure'].tolist(),nonnegative=False)
        solver.projector.last_dt=meta['last_dt']
        solver.projector.ready=False # divergence diagnostics recomputed on next step
        if solver.combustion:
            solver.combustion.fuel=solver.device.texture(grid.shape,arrays['fuel'].tolist())
            solver.combustion.flame=solver.device.texture(grid.shape,arrays['flame'].tolist())
        solver.time,solver.steps=meta['time'],meta['steps']
        return solver
    except Exception:
        solver.close();raise


def advance_fixed(solver, steps, dt, sources=None):
    """Offline reproducible input schedule; no wall-clock debt or dropped steps."""
    validate_dt(dt)
    if type(steps) is not int or steps<0:raise ValueError('Steps must be a nonnegative integer')
    if solver.solids is not None:raise ValueError('Fixed checkpoint runner v1 excludes colliders')
    for _ in range(steps):solver.step(dt,sources=sources)
