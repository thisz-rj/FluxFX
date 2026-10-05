// Symmetric graph Laplacian; zero edges encode solid walls on every level.
void graphTerms(ivec3 c, out float diagonal, out float neighbors) {
    diagonal=0.0; neighbors=0.0;
    for(int a=0;a<3;a++) {
        ivec3 o=ivec3(0);o[a]=1;
        if(c[a]>0) {
            float w=texelFetch(edgeField,c-o,0)[a];
            diagonal+=w;neighbors+=w*texelFetch(inputField,c-o,0).r;
        }
        if(c[a]+1<gridSize[a]) {
            float w=texelFetch(edgeField,c,0)[a];
            diagonal+=w;neighbors+=w*texelFetch(inputField,c+o,0).r;
        }
    }
}
