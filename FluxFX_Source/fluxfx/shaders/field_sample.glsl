float fieldAt(vec3 p) {
    ivec3 size = textureSize(densityField, 0);
    vec3 q = clamp(p, vec3(0.0), vec3(1.0)) * vec3(size) - 0.5;
    ivec3 b = ivec3(floor(q));
    vec3 f = fract(q);
    float result = 0.0;
    for (int z=0; z<2; ++z) for (int y=0; y<2; ++y) for (int x=0; x<2; ++x) {
        ivec3 o = ivec3(x,y,z);
        vec3 w = mix(vec3(1.0)-f, f, vec3(o));
        result += texelFetch(densityField, clamp(b+o, ivec3(0), size-1), 0).r * w.x*w.y*w.z;
    }
    return result;
}
