void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    int row=c.x+gridSize.x*(c.y+gridSize.y*c.z);
    int count=gridSize.x*gridSize.y*gridSize.z;
    float value=0.0;
    for(int j=0;j<count;j++) {
        ivec3 p=ivec3(j%gridSize.x,(j/gridSize.x)%gridSize.y,j/(gridSize.x*gridSize.y));
        value+=texelFetch(inverseField,ivec3(j,row,0),0).r*texelFetch(inputField,p,0).r;
    }
    imageStore(outputField,c,vec4(value,0,0,1));
}
