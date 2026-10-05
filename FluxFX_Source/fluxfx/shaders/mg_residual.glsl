void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if (any(greaterThanEqual(c,gridSize))) return;
    float center=texelFetch(inputField,c,0).r;
    float lap=0.0;
    for (int axis=0;axis<3;++axis) {
        ivec3 offset=ivec3(0);offset[axis]=1;
        float w=invCell[axis]*invCell[axis];
        if(c[axis]>0) lap+=w*(texelFetch(inputField,c-offset,0).r-center);
        if(c[axis]+1<gridSize[axis]) lap+=w*(texelFetch(inputField,c+offset,0).r-center);
    }
    imageStore(outputField,c,vec4(texelFetch(divergenceField,c,0).r/dt-lap,0.0,0.0,1.0));
}
