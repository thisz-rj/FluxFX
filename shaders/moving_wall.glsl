void main() {
    ivec3 f=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(f,gridSize)))return;
    int a=int(componentAxis);float value=0.0;
    if(f[a]>0 && f[a]<gridSize[a]-1) {
        ivec3 o=ivec3(0);o[a]=1;
        int hi=int(texelFetch(solidField,f,0).r);
        int lo=int(texelFetch(solidField,f-o,0).r);
        int owner=lo>0 ? lo : hi;
        if(owner>0) {
            vec3 offset=vec3(.5);offset[a]=0.;
            vec4 p=vec4((vec3(f)+offset)*domainExtent/vec3(textureSize(solidField,0)),1);
            vec4 row=vec4(0);
            for(int i=0;i<4;i++)row[i]=texelFetch(wallTable,ivec3(i,(owner-1)*3+a,0),0).r;
            value=dot(row,p);
        }
    }
    imageStore(outputField,f,vec4(value,0,0,1));
}
