void main()
{
    ivec3 face = ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(face, gridSize))) { return; }
    int axis = int(componentAxis);
    float value = 0.0;
    bool openFace = face[axis] > 0 && face[axis] < gridSize[axis] - 1;
#ifdef FLUXFX_COLLISIONS
    openFace = openFace && !solidFace(face,axis);
#endif
#ifdef FLUXFX_MOVING_COLLIDERS
    if(!openFace)value=texelFetch(boundaryField,face,0).r;
#endif
    if (openFace) {
        ivec3 offset = ivec3(0);
        offset[axis] = 1;
        float gradient = (texelFetch(pressureField, face, 0).r - texelFetch(pressureField, face - offset, 0).r) * invCell[axis];
        value = texelFetch(inputField, face, 0).r - dt * gradient;
    }
    imageStore(outputField, face, vec4(value, 0.0, 0.0, 1.0));
}
