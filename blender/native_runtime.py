"""Blender ownership/lifecycle for the P1.1 native resource diagnostic."""
import bpy
from ..native import Context

context=None
scene=None
last_report=None


def shutdown():
    global context,scene
    if bpy.app.timers.is_registered(watch_scene):bpy.app.timers.unregister(watch_scene)
    if context is not None:context.close()
    context=scene=None


def watch_scene():
    if context is None:return None
    if bpy.context.scene!=scene:
        shutdown();return None
    return .25


def test(owner):
    global context,scene,last_report
    budget=owner.fluxfx.native_budget_mb*2**20
    if context is None or scene!=owner or context.stats()['budget_bytes']!=budget:
        shutdown()
        context=Context(budget);scene=owner
        bpy.app.timers.register(watch_scene,first_interval=.25)
    allocation=context.allocate(min(2**20,budget))
    try:last_report=context.dispatch(allocation,min(2**20,budget)//4,repeats=4)
    finally:context.release(allocation)
    last_report['resources']=context.stats()
    return last_report
