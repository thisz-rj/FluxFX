void main()
{
    ivec3 p = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(p, gridSize))) { return; }
    float value = float(p.x + 10 * p.y + 100 * p.z);
    imageStore(outputField, p, vec4(value, 0.0, 0.0, 1.0));
}
