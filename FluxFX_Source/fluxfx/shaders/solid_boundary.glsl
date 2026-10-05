#define FLUXFX_COLLISIONS
bool solidCell(ivec3 cell) {
    ivec3 size=textureSize(solidField,0);
    if(any(lessThan(cell,ivec3(0))) || any(greaterThanEqual(cell,size)))return true;
    return texelFetch(solidField,cell,0).r>0.5;
}
bool solidFace(ivec3 face,int axis) {
    ivec3 offset=ivec3(0);offset[axis]=1;
    return solidCell(face) || solidCell(face-offset);
}
// Grid traversal clips a characteristic at the first blocked cell, including
// steps larger than one voxel. 3*128 crossings bound any clamped domain segment.
vec3 clipSolidTrace(vec3 origin,vec3 target,vec3 extent) {
    vec3 count=vec3(textureSize(solidField,0));
    vec3 a=clamp(origin/extent*count,vec3(0.0001),count-0.0001);
    vec3 b=clamp(target/extent*count,vec3(0.0001),count-0.0001);
    vec3 delta=b-a;
    ivec3 cell=ivec3(floor(a));
    if(solidCell(cell))return origin;
    ivec3 direction=ivec3(sign(delta));
    vec3 crossing=vec3(1e20), stride=vec3(1e20);
    for(int axis=0;axis<3;axis++)if(abs(delta[axis])>1e-10) {
        float edge=float(cell[axis]+(direction[axis]>0?1:0));
        crossing[axis]=(edge-a[axis])/delta[axis];
        stride[axis]=1.0/abs(delta[axis]);
    }
    for(int i=0;i<384;i++) {
        int axis=crossing.x<=crossing.y && crossing.x<=crossing.z ? 0 : (crossing.y<=crossing.z ? 1 : 2);
        float t=crossing[axis];
        if(t>=1.0)return b/count*extent;
        cell[axis]+=direction[axis];
        if(solidCell(cell))return (a+delta*max(0.0,t-0.0001/max(length(delta),1.0)))/count*extent;
        crossing[axis]+=stride[axis];
    }
    return origin; // Conservative if a future larger grid exceeds the traversal limit.
}

// One-cell halo excludes correction wherever any interpolation stencil touches a wall.
bool solidHalo(vec3 p, vec3 extent) {
    ivec3 c=ivec3(floor(p/extent*vec3(textureSize(solidField,0))));
    for(int z=-1;z<=1;z++)for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++)
        if(solidCell(c+ivec3(x,y,z)))return true;
    return false;
}
bool safeSolidCorrection(vec3 p,vec3 departure,vec3 midpoint,vec3 arrival,vec3 extent) {
    return !solidHalo(p,extent) && !solidHalo(departure,extent) && !solidHalo(arrival,extent) &&
        distance(clipSolidTrace(p,departure,extent),departure)<1e-7 &&
        distance(clipSolidTrace(p,midpoint,extent),midpoint)<1e-7 &&
        distance(clipSolidTrace(p,arrival,extent),arrival)<1e-7;
}
