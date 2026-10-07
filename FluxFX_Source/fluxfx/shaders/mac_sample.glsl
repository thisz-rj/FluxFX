// Face velocities use constant extrapolation (clamp), not solid walls.
float sampleFace(sampler3D field, vec3 q)
{
    ivec3 size = textureSize(field, 0);
    q = clamp(q, vec3(0.0), vec3(size - ivec3(1)));
    ivec3 b = ivec3(floor(q));
    vec3 f = fract(q);
    float value = 0.0;
    for (int z = 0; z < 2; ++z) {
        for (int y = 0; y < 2; ++y) {
            for (int x = 0; x < 2; ++x) {
                ivec3 o = ivec3(x, y, z);
                vec3 w = mix(vec3(1.0) - f, f, vec3(o));
                value += w.x * w.y * w.z * texelFetch(field, min(b + o, size - ivec3(1)), 0).r;
            }
        }
    }
    return value;
}
vec3 velocityAt(vec3 p)
{
    vec3 q = p * cellCount / domainExtent;
    return vec3(sampleFace(velocityU, q - vec3(0.0, 0.5, 0.5)),
                sampleFace(velocityV, q - vec3(0.5, 0.0, 0.5)),
                sampleFace(velocityW, q - vec3(0.5, 0.5, 0.0)));
}
