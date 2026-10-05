void main() {
    ivec3 f=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(f,gridSize)))return;
    int a=int(componentAxis);float value=0.;
    if(f[a]>0 && f[a]<gridSize[a]-1) {
        ivec3 o=ivec3(0);o[a]=1;
        bool blocked=texelFetch(solidField,f,0).r>.5 || texelFetch(solidField,f-o,0).r>.5;
        bool previous=texelFetch(oldSolidField,f,0).r>.5 || texelFetch(oldSolidField,f-o,0).r>.5;
        value=blocked?texelFetch(boundaryField,f,0).r:(previous?0.:texelFetch(inputField,f,0).r);
    }
    imageStore(outputField,f,vec4(value,0,0,1));
}
