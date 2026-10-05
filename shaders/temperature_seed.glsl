void main()
{
    ivec3 cell = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell, gridSize))) { return; }
    vec3 p = (vec3(cell) + vec3(0.5)) * domainExtent / vec3(gridSize);
    vec3 offset = p - sourceCenter;
    float w = max(1.0 - dot(offset, offset) / (sourceRadius * sourceRadius), 0.0);
    imageStore(outputField, cell, vec4(seedTemperature * w * w, 0.0, 0.0, 1.0));
}
