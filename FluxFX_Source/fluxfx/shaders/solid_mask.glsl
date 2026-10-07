void main() {
    ivec3 cell=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(cell,gridSize)))return;
    vec4 p=vec4((vec3(cell)+0.5)*domainExtent/vec3(gridSize),1.0);
    vec3 q=vec3(dot(row0,p),dot(row1,p),dot(row2,p));
    bool inside=shapeKind<0.5 ? dot(q,q)<=1.0 : all(lessThanEqual(abs(q),vec3(1.0)));
    float value=max(texelFetch(inputField,cell,0).r,inside?1.0:0.0);
    imageStore(outputField,cell,vec4(value,0,0,1));
}
