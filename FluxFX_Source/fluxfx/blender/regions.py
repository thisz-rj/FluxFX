"""P1.3 topology preview. Python handles scene commands and wire geometry only."""
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from ..native import BrickPool
from .emitter import source_geometry,prepare_emission
from .domain import domain_object

pool=None
scene=None
handler=None
batches=[]
shader=None
history={}
message='Not started'
signature=None
steps=0


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type=='VIEW_3D':area.tag_redraw()


def shutdown():
    global pool,scene,handler,batches,shader,history,signature
    if bpy.app.timers.is_registered(tick):bpy.app.timers.unregister(tick)
    if handler is not None:bpy.types.SpaceView3D.draw_handler_remove(handler,'WINDOW')
    handler=None;batches=[];shader=None;history={};signature=None
    if pool is not None:pool.close()
    pool=scene=None
    redraw()


def draw():
    if pool is None or bpy.context.scene!=scene:return
    domain=domain_object(scene)
    if domain is None:return
    old_depth=gpu.state.depth_test_get();old_blend=gpu.state.blend_get()
    try:
        gpu.state.depth_test_set('LESS_EQUAL');gpu.state.blend_set('ALPHA')
        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(domain.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world)
            shader.bind()
            for batch,color in batches:
                shader.uniform_float('color',color);batch.draw(shader)
    finally:
        gpu.state.depth_test_set(old_depth);gpu.state.blend_set(old_blend)


def geometry(rows,grid):
    global batches,shader
    shader=shader or gpu.shader.from_builtin('UNIFORM_COLOR')
    edges=((0,1),(0,2),(0,4),(1,3),(1,5),(2,3),(2,6),(3,7),(4,5),(4,6),(5,7),(6,7))
    groups=[[],[]]
    for x,y,z,slot,age in rows:
        corners=[((x+(i&1))/grid-.5,(y+((i>>1)&1))/grid-.5,(z+((i>>2)&1))/grid-.5) for i in range(8)]
        vertices=groups[bool(age)]
        for a,b in edges:vertices.extend((corners[a],corners[b]))
    batches=[(batch_for_shader(shader,'LINES',{'pos':vertices}),color) for vertices,color in
             zip(groups,((.1,.8,1.,.8),(1.,.45,.08,.65))) if vertices]


def step(owner):
    global pool,scene,signature,history,message,steps
    props=owner.fluxfx
    if domain_object(owner) is None:raise ValueError('Create a FluxFX domain before showing active bricks')
    config=(props.native_budget_mb,props.sparse_capacity,props.sparse_grid)
    if pool is not None and signature!=config:
        raise ValueError('Settings changed; click Show Active Bricks to restart')
    if pool is None or scene!=owner:
        shutdown()
        pool=BrickPool(8,props.sparse_capacity,props.native_budget_mb*2**20)
        scene=owner;signature=config;steps=0
    sources=[];updated={}
    for key,source in [('primary',props)]+[(entry.name,entry) for entry in props.extra_emitters]:
        if not source.emission_enabled:continue
        center,radius=source_geometry(owner,source)
        motion,snapshot=prepare_emission(owner,history.get(key),source,interval=props.time_step)
        # User margin is a bound in domain lengths/sec, applied to all directions.
        # Expanding the source radius by speed*dt includes unknown flow direction.
        radius+=props.sparse_speed_margin*props.time_step
        sources.append((*center,radius,*motion.velocity));updated[key]=snapshot
    grid=props.sparse_grid//8
    pool.update_regions(sources,grid,props.time_step,props.sparse_linger,props.sparse_halo)
    history=updated;steps+=1
    rows=pool.snapshot();geometry(rows,grid)
    retained=sum(row[4]>0 for row in rows)
    message=f'{len(rows)} bricks · {retained} retained · step {steps}'
    redraw()


def tick():
    global message
    if pool is None:return None
    if bpy.context.scene!=scene:shutdown();return None
    try:step(scene)
    except Exception as exc:
        message=str(exc);shutdown();return None
    # step() can recreate the pool and remove the timer after setting changes.
    if not bpy.app.timers.is_registered(tick):return None
    return .1


def start(owner):
    global handler
    shutdown()
    step(owner)
    if handler is None:handler=bpy.types.SpaceView3D.draw_handler_add(draw,(),'WINDOW','POST_VIEW')
    if not bpy.app.timers.is_registered(tick):bpy.app.timers.register(tick,first_interval=.1)
    redraw()
