void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    float value=texelFetch(edgeField,c,0).a>0.0 ?
        texelFetch(inputField,c,0).r+texelFetch(coarseField,c/2,0).r : 0.0;
    imageStore(outputField,c,vec4(value,0,0,1));
}
