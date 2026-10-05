void main()
{
    ivec3 face = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(face, gridSize))) { return; }
    int axis = int(componentAxis);
    bool wall = face[axis] == 0 || face[axis] == gridSize[axis] - 1;
#ifdef FLUXFX_COLLISIONS
    wall = wall || solidFace(face,axis);
#endif
    float value = wall ? 0.0 : texelFetch(inputField, face, 0).r;
#ifdef FLUXFX_MOVING_COLLIDERS
    if(wall)value=texelFetch(boundaryField,face,0).r;
#endif
    imageStore(outputField, face, vec4(value, 0.0, 0.0, 1.0));
}
