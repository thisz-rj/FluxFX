// Neumann walls: omit exterior neighbors from both sum and diagonal.
void main()
{
    ivec3 c = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(c, gridSize))) { return; }
#ifdef FLUXFX_COLLISIONS
    if(solidCell(c)) { imageStore(outputField,c,vec4(0)); return; }
#endif
    float neighborSum = 0.0;
    float diagonal = 0.0;
    for (int axis = 0; axis < 3; ++axis) {
        ivec3 offset = ivec3(0);
        offset[axis] = 1;
        float weight = invCell[axis] * invCell[axis];
        bool lower = c[axis] > 0;
        bool upper = c[axis] + 1 < gridSize[axis];
#ifdef FLUXFX_COLLISIONS
        lower = lower && !solidCell(c-offset);
        upper = upper && !solidCell(c+offset);
#endif
        if (lower) {
            neighborSum += weight * texelFetch(inputField, c - offset, 0).r;
            diagonal += weight;
        }
        if (upper) {
            neighborSum += weight * texelFetch(inputField, c + offset, 0).r;
            diagonal += weight;
        }
    }
    if(diagonal==0.0) { imageStore(outputField,c,vec4(0)); return; }
    float candidate = (neighborSum - texelFetch(divergenceField, c, 0).r / dt) / diagonal;
    float oldPressure = texelFetch(inputField, c, 0).r;
    imageStore(outputField, c, vec4(mix(oldPressure, candidate, relaxation), 0.0, 0.0, 1.0));
}
