void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    vec4 p=vec4((vec3(c)+.5)*domainExtent/vec3(gridSize),1);
    vec3 q=vec3(dot(row0,p),dot(row1,p),dot(row2,p));
    bool inside=shapeKind<.5 ? dot(q,q)<=1.0 : all(lessThanEqual(abs(q),vec3(1)));
    float value=texelFetch(inputField,c,0).r;
    // First enabled collider owns overlapping solid cells deterministically.
    if(value<.5 && inside)value=owner;
    imageStore(outputField,c,vec4(value,0,0,1));
}
