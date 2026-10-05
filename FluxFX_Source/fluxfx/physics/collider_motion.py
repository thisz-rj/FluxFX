"""Rigid collider paths in simulation metres, independent of Blender and GPU."""
from dataclasses import dataclass
from math import acos, sin, cos, sqrt
from .collision import Collider

MAX_SURFACE_SPEED = 2.0


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def length(v):return sqrt(dot(v,v))
def mul(a,b):
    w,x,y,z=a;v,i,j,k=b
    return (w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v)
def conjugate(q):return (q[0],-q[1],-q[2],-q[3])


def quaternion(m):
    trace=sum(m[i][i] for i in range(3))
    if trace>0:
        s=2*sqrt(trace+1)
        q=(s/4,(m[2][1]-m[1][2])/s,(m[0][2]-m[2][0])/s,(m[1][0]-m[0][1])/s)
    else:
        i=max(range(3),key=lambda a:m[a][a]);j=(i+1)%3;k=(i+2)%3
        s=2*sqrt(max(0,1+m[i][i]-m[j][j]-m[k][k]))
        v=[0.,0.,0.];v[i]=s/4;v[j]=(m[j][i]+m[i][j])/s;v[k]=(m[k][i]+m[i][k])/s
        q=((m[k][j]-m[j][k])/s,*v)
    n=length(q)
    return tuple(v/n for v in q)


def rotation(q):
    w,x,y,z=q
    return ((1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)),
            (2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)),
            (2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)))


def slerp(a,b,f):
    d=dot(a,b)
    if d<0:b=tuple(-v for v in b);d=-d
    d=min(1.,max(-1.,d))
    if d>.9995:
        q=tuple(x+(y-x)*f for x,y in zip(a,b));n=length(q)
        return tuple(v/n for v in q)
    t=acos(d)
    return tuple((sin((1-f)*t)*x+sin(f*t)*y)/sin(t) for x,y in zip(a,b))


@dataclass(frozen=True)
class Pose:
    shape: str
    center: tuple
    size: tuple
    orientation: tuple

    @classmethod
    def from_collider(cls,collider):
        rows=collider.inverse_rows
        sizes=tuple(1/length(row[:3]) for row in rows)
        axes=tuple(tuple(v*s for v in row[:3]) for row,s in zip(rows,sizes))
        if any(abs(dot(axes[i],axes[j]))>1e-5 for i in range(3) for j in range(i)):
            raise ValueError('Moving colliders do not support shear; use an unscaled or uniformly scaled domain')
        m=tuple(tuple(axes[j][i] for j in range(3)) for i in range(3))
        det=dot(axes[0],(axes[1][1]*axes[2][2]-axes[1][2]*axes[2][1],axes[1][2]*axes[2][0]-axes[1][0]*axes[2][2],axes[1][0]*axes[2][1]-axes[1][1]*axes[2][0]))
        if det<0:raise ValueError('Moving colliders require positive scale')
        center=tuple(-sum(axes[j][i]*sizes[j]*rows[j][3] for j in range(3)) for i in range(3))
        return cls(collider.shape,center,sizes,quaternion(m))

    def collider(self):
        m=rotation(self.orientation)
        rows=tuple(tuple(m[j][i]/self.size[i] for j in range(3)) for i in range(3))
        return Collider(self.shape,tuple(row+(-dot(row,self.center),) for row in rows))

    def interpolate(self,target,f):
        return Pose(self.shape,tuple(a+(b-a)*f for a,b in zip(self.center,target.center)),self.size,slerp(self.orientation,target.orientation,f))

    def distance_bound(self,target):
        angle=2*acos(min(1.,abs(dot(self.orientation,target.orientation))))
        return length(tuple(b-a for a,b in zip(self.center,target.center)))+angle*length(self.size)


def validate_motion(previous,current):
    if len(previous)!=len(current):raise ValueError('Collider entries changed; press Reset')
    poses=[]
    for old,new in zip(previous,current):
        a,b=Pose.from_collider(old),Pose.from_collider(new)
        if a.shape!=b.shape or any(abs(x-y)>max(x,y)*1e-5 for x,y in zip(a.size,b.size)):
            raise ValueError('Collider shape or size changed; press Reset')
        poses.append((a,b))
    return tuple(poses)


class MotionPath:
    def __init__(self,previous,current,duration):
        self.poses=validate_motion(previous,current)
        self.distance=max((a.distance_bound(b) for a,b in self.poses),default=0.)
        self.duration=max(duration,self.distance/MAX_SURFACE_SPEED,1e-6)
        self.speed=self.distance/self.duration

    def at(self,elapsed):
        f=min(1.,max(0.,elapsed/self.duration))
        return tuple(a.interpolate(b,f).collider() for a,b in self.poses)

    def limit_dt(self,dt,cell_size):
        return min(dt,.5*min(cell_size)/self.speed) if self.speed>1e-8 else dt


def velocity_rows(old,new,dt):
    """v(p)=translation velocity + omega cross (p-new_center)."""
    a,b=Pose.from_collider(old),Pose.from_collider(new)
    q=mul(b.orientation,conjugate(a.orientation))
    if q[0]<0:q=tuple(-v for v in q)
    s=length(q[1:]);angle=2*acos(min(1.,max(-1.,q[0])))
    omega=tuple(v*angle/(s*dt) for v in q[1:]) if s>1e-8 else (0.,)*3
    x,y,z=omega
    rows=((0.,-z,y),(z,0.,-x),(-y,x,0.))
    linear=tuple((v-u)/dt for u,v in zip(a.center,b.center))
    return tuple(row+(linear[i]-dot(row,b.center),) for i,row in enumerate(rows))
