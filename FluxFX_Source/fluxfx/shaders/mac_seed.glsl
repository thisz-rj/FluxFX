void main()
{
    ivec3 cell = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(cell, gridSize))) { return; }
    vec3 p = (vec3(cell) + faceOffset) * domainExtent / cellCount;
    vec2 q = p.xy - 0.5 * domainExtent.xy;
    vec3 velocity = baseVelocity + vec3(-angularSpeed * q.y, angularSpeed * q.x, 0.0);
    imageStore(outputField, cell, vec4(dot(velocity, axisMask), 0.0, 0.0, 1.0));
}
