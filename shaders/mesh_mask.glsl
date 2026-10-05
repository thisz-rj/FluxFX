void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(cell,gridSize)))return;
    float solid=max(texelFetch(inputField,cell,0).r,texelFetch(sdfField,cell,0).r<=0.0 ? 1.0 : 0.0);
    imageStore(outputField,cell,vec4(solid,0,0,1));
}
