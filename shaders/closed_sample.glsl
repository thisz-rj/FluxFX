float fetchClosed(ivec3 p)
{
    p = clamp(p, ivec3(0), gridSize - ivec3(1));
    return texelFetch(inputField, p, 0).r;
}

float sampleClosed(vec3 q)
{
#ifdef FLUXFX_COLLISIONS
    ivec3 base=ivec3(floor(q)); vec3 f=fract(q);
    float value=0.0, total=0.0;
    for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++) {
        ivec3 offset=ivec3(x,y,z);
        ivec3 cell=clamp(base+offset,ivec3(0),gridSize-1);
        if(solidCell(cell))continue;
        vec3 w=mix(vec3(1)-f,f,vec3(offset));float weight=w.x*w.y*w.z;
        value+=weight*texelFetch(inputField,cell,0).r;total+=weight;
    }
    return total>1e-8 ? value/total : 0.0;
#else
    ivec3 b = ivec3(floor(q));
    vec3 f = fract(q);
    float z0 = mix(mix(fetchClosed(b), fetchClosed(b + ivec3(1, 0, 0)), f.x),
                   mix(fetchClosed(b + ivec3(0, 1, 0)), fetchClosed(b + ivec3(1, 1, 0)), f.x), f.y);
    float z1 = mix(mix(fetchClosed(b + ivec3(0, 0, 1)), fetchClosed(b + ivec3(1, 0, 1)), f.x),
                   mix(fetchClosed(b + ivec3(0, 1, 1)), fetchClosed(b + ivec3(1, 1, 1)), f.x), f.y);
    return mix(z0, z1, f.z);
#endif
}

