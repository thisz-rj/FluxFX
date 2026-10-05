void main()
{
    ivec3 c = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(c, gridSize))) { return; }
#ifdef FLUXFX_COLLISIONS
    if(solidCell(c)) { imageStore(outputField,c,vec4(0));return; }
#endif
    float d = (texelFetch(velocityU, c + ivec3(1,0,0), 0).r - texelFetch(velocityU, c, 0).r) * invCell.x
            + (texelFetch(velocityV, c + ivec3(0,1,0), 0).r - texelFetch(velocityV, c, 0).r) * invCell.y
            + (texelFetch(velocityW, c + ivec3(0,0,1), 0).r - texelFetch(velocityW, c, 0).r) * invCell.z;
    imageStore(outputField, c, vec4(d, 0.0, 0.0, 1.0));
}
