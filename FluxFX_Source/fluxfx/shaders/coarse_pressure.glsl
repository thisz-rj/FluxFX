void main()
{
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    int row=(c.z*4+c.y)*4+c.x;
    float value=0.0;
    for(int j=0;j<64;j++) {
        ivec3 p=ivec3(j%4,(j/4)%4,j/16);
        value+=texelFetch(inverseField,ivec3(j,row,0),0).r*texelFetch(inputField,p,0).r;
    }
    imageStore(outputField,c,vec4(value/dt,0,0,1));
}
