// Exact time-average of the compact spherical profile along a linear sweep.
float sourceWeight(vec3 p, vec3 sourceCenter, vec3 sourceStart, float sourceRadius, float sourceProfile)
{
    vec3 segment = sourceCenter - sourceStart;
    float lengthSquared = dot(segment, segment);
    float r2 = sourceRadius * sourceRadius;
    if (lengthSquared < 1e-12) {
        vec3 d = p-sourceCenter;
        float w = max(1.0-dot(d,d)/r2, 0.0);
        return sourceProfile>0.5 ? (dot(d,d)<r2 ? 1.0 : 0.0) : w*w;
    }
    float lengthPath = sqrt(lengthSquared);
    vec3 axis = segment/lengthPath;
    vec3 offset = p-sourceStart;
    float along = dot(offset,axis);
    vec3 perpendicular = offset-along*axis;
    float a = 1.0-dot(perpendicular,perpendicular)/r2;
    if (a <= 0.0) return 0.0;
    float halfWidth = sourceRadius*sqrt(a);
    float lo = max(-along,-halfWidth);
    float hi = min(lengthPath-along,halfWidth);
    if (hi <= lo) return 0.0;
    if (sourceProfile>0.5) return (hi-lo)/lengthPath;
    // Normalize before polynomial evaluation for numerical stability.
    float u = lo/halfWidth;
    float v = hi/halfWidth;
    float integral = (v-u)-2.0/3.0*(v*v*v-u*u*u)+0.2*(v*v*v*v*v-u*u*u*u*u);
    return clamp(a*a*halfWidth/lengthPath*integral,0.0,1.0);
}

float sourceValue(int source, int column, int row)
{
    return texelFetch(sourceTable,ivec3(column,row,source),0).r;
}
vec3 sourceVector(int source, int row)
{
    return vec3(sourceValue(source,0,row),sourceValue(source,1,row),sourceValue(source,2,row));
}
float tableWeight(int source,vec3 p)
{
    return sourceWeight(p,sourceVector(source,0),sourceVector(source,1),sourceValue(source,3,0),sourceValue(source,2,3));
}
