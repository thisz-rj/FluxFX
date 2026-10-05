void main() {
    ivec3 c=ivec3(gl_GlobalInvocationID.xyz);
    if(any(greaterThanEqual(c,gridSize)))return;
    // Exposed cells start empty; never resurrect trapped density or temperature.
    bool blocked=texelFetch(solidField,c,0).r>.5 || texelFetch(oldSolidField,c,0).r>.5;
    imageStore(outputField,c,vec4(blocked?0.:texelFetch(inputField,c,0).r,0,0,1));
}
