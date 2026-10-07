"""Direct-keyframe definitions used to invalidate animated playback caches."""
from ..physics.cache import fingerprint


def animation_signature(scene):
    # Names, parenting and action-slot assignment are persistent across save/load.
    ids = [scene]
    p = scene.fluxfx
    objects = [p.domain_object, p.emitter_object]
    objects += [e.emitter_object for e in p.extra_emitters]
    objects += [e.collider_object for e in p.colliders]
    seen = set()
    for obj in objects:
        while obj is not None and obj.as_pointer() not in seen:
            seen.add(obj.as_pointer()); ids.append(obj)
            if getattr(obj, 'data', None) is not None: ids.append(obj.data)
            obj = obj.parent
    definitions = []
    for owner in ids:
        if any(not c.mute for c in getattr(owner, 'constraints', ())):
            raise ValueError('Animated bake supports direct keyframes; bake object constraints to keys first')
        animation = owner.animation_data
        entry = dict(type=owner.bl_rna.identifier, name=owner.name,
                     parent=getattr(getattr(owner, 'parent', None), 'name', None), curves=[])
        definitions.append(entry)
        if animation is None: continue
        if animation.drivers or animation.nla_tracks or animation.use_tweak_mode:
            raise ValueError('Animated bake does not support drivers, NLA or tweak mode')
        action = animation.action
        if action is None: continue
        entry['slot'] = animation.action_slot_handle
        entry['blend'] = (animation.action_blend_type, animation.action_extrapolation, animation.action_influence)
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    if bag.slot_handle != animation.action_slot_handle: continue
                    for curve in bag.fcurves:
                        if curve.modifiers or curve.sampled_points:
                            raise ValueError('Animated bake requires keyframe curves without F-curve modifiers')
                        keys = [dict(co=list(k.co), left=list(k.handle_left), right=list(k.handle_right),
                                     left_type=k.handle_left_type, right_type=k.handle_right_type,
                                     interpolation=k.interpolation, easing=k.easing, back=k.back,
                                     amplitude=k.amplitude, period=k.period) for k in curve.keyframe_points]
                        entry['curves'].append(dict(path=curve.data_path, index=curve.array_index,
                            mute=curve.mute, extrapolation=curve.extrapolation, smoothing=curve.auto_smoothing, keys=keys))
    return fingerprint(definitions)
