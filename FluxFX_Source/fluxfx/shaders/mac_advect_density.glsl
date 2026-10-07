float fetchZero(ivec3 p)
{
    if (any(lessThan(p, ivec3(0))) || any(greaterThanEqual(p, gridSize))) { return 0.0; }
    return texelFetch(inputField, p, 0).r;
}

float sampleZero(vec3 q)
{
    ivec3 b = ivec3(floor(q));
    vec3 f = fract(q);
    float z0 = mix(mix(fetchZero(b), fetchZero(b + ivec3(1, 0, 0)), f.x),
                   mix(fetchZero(b + ivec3(0, 1, 0)), fetchZero(b + ivec3(1, 1, 0)), f.x), f.y);
    float z1 = mix(mix(fetchZero(b + ivec3(0, 0, 1)), fetchZero(b + ivec3(1, 0, 1)), f.x),
                   mix(fetchZero(b + ivec3(0, 1, 1)), fetchZero(b + ivec3(1, 1, 1)), f.x), f.y);
    return mix(z0, z1, f.z);
}

void main()
{
    ivec3 cell = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell, gridSize))) { return; }
    vec3 h = domainExtent / vec3(gridSize);
    vec3 p = (vec3(cell) + vec3(0.5)) * h;
    vec3 midpoint = p - 0.5 * dt * velocityAt(p);
    vec3 departure = p - dt * velocityAt(midpoint);
    float density = sampleZero(departure / h - vec3(0.5)) * exp(-dissipation * dt);
    vec3 offset = p - sourceCenter;
    float w = max(1.0 - dot(offset, offset) / (sourceRadius * sourceRadius), 0.0);
    density += dt * sourceRate * w * w;
    imageStore(outputField, cell, vec4(density, 0.0, 0.0, 1.0));
}
