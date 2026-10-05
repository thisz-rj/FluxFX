void main()
{
    ivec3 cell = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell, gridSize))) { return; }
    vec3 p = (vec3(cell) + faceOffset) * domainExtent / cellCount;
    vec3 midpoint = p - 0.5 * dt * velocityAt(p);
    vec3 departure = p - dt * velocityAt(midpoint);
    float value = dot(velocityAt(departure), axisMask);
    imageStore(outputField, cell, vec4(value, 0.0, 0.0, 1.0));
}
