"""Small CPU 3D Gaussian splat still-image renderer for EzRender experiments.
Supports common 3DGS PLY vertex properties, SH DC colors, anisotropic covariance.
Requires numpy and Pillow only. Not a real-time renderer.
"""
import argparse
import math
import struct
from pathlib import Path
import numpy as np
from PIL import Image

TYPES = {'char':'b','uchar':'B','short':'h','ushort':'H','int':'i','uint':'I','float':'f','double':'d',
         'int8':'b','uint8':'B','int16':'h','uint16':'H','int32':'i','uint32':'I','float32':'f','float64':'d'}

def read_ply(path):
    with open(path, 'rb') as f:
        if f.readline().strip() != b'ply': raise ValueError('Not a PLY file')
        fmt = None; props=[]; count=None; element=None
        while True:
            line=f.readline()
            if not line: raise ValueError('Truncated PLY header')
            s=line.decode('ascii').strip().split()
            if not s: continue
            if s[0]=='format': fmt=s[1]
            elif s[0]=='element':
                element=s[1]
                if element=='vertex': count=int(s[2])
            elif s[0]=='property' and element=='vertex':
                if s[1]=='list': raise ValueError('List properties in vertex are unsupported')
                props.append((s[2],s[1]))
            elif s[0]=='end_header': break
        if count is None: raise ValueError('No vertex element')
        if fmt in ('binary_little_endian','binary_big_endian'):
            endian='<' if fmt=='binary_little_endian' else '>'
            dt=np.dtype([(name,endian+TYPES[t]) for name,t in props])
            data=np.fromfile(f,dtype=dt,count=count)
            if len(data)!=count: raise ValueError('Truncated vertex data')
            return {name:np.asarray(data[name],dtype=np.float64) for name,_ in props}
        if fmt=='ascii':
            vals=np.empty((count,len(props)),dtype=np.float64)
            for i in range(count):
                vals[i]=[float(x) for x in f.readline().split()[:len(props)]]
            return {name:vals[:,i] for i,(name,_) in enumerate(props)}
        raise ValueError(f'Unsupported PLY format: {fmt}')

def sigmoid(x): return 1/(1+np.exp(-np.clip(x,-30,30)))

def quaternion_matrices(q):
    q=q/np.maximum(np.linalg.norm(q,axis=1,keepdims=True),1e-12)
    w,x,y,z=q.T
    return np.stack([1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),
                     2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),
                     2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)],axis=-1).reshape(-1,3,3)

