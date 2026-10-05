void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(cell,gridSize)))return;
    float value=texelFetch(inputField,cell,0).r+dt*yieldValue*texelFetch(burnField,cell,0).r;
    if(yieldValue<0.0)value=max(value,0.0);
    imageStore(outputField,cell,vec4(value,0,0,1));
}
