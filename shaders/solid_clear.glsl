void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(cell,gridSize)))return;
    float value=solidCell(cell)?0.0:texelFetch(inputField,cell,0).r;
    imageStore(outputField,cell,vec4(value,0,0,1));
}
