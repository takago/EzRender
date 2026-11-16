"""Static 3D Gaussian Splatting PLY renderer for EzRender.

Requires: numpy, Pillow, moderngl (EGL/OpenGL 3.3+), and optionally timg.
No PyTorch, CUDA, or gsplat dependency.
"""
import argparse
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from gs_renderer import read_ply, sigmoid, quaternion_matrices

VS = '''#version 330
in vec2 in_corner;
in vec2 in_center;
in vec2 in_axis0;
in vec2 in_axis1;
in vec4 in_rgba;
uniform vec2 u_size;
out vec2 v_corner;
out vec4 v_rgba;
void main() {
    vec2 pixel = in_center + in_axis0 * in_corner.x + in_axis1 * in_corner.y;
    gl_Position = vec4(pixel / u_size * 2.0 - 1.0, 0.0, 1.0);
    v_corner = in_corner;
    v_rgba = in_rgba;
}
'''
FS = '''#version 330
in vec2 v_corner;
in vec4 v_rgba;
out vec4 f_color;
void main() {
    float r2 = dot(v_corner, v_corner);
    if (r2 > 9.0) discard;
    float a = clamp(v_rgba.a * exp(-0.5 * r2), 0.0, 0.999);
    if (a < 0.001) discard;
    f_color = vec4(v_rgba.rgb, a);
}
'''


def _context():
    import moderngl
    try:
        return moderngl.create_standalone_context(backend='egl', require=330)
    except Exception as exc:
        raise RuntimeError('EGL OpenGL 3.3+ context unavailable. Check GPU drivers and EGL support') from exc


def _attributes(p, indices, radius):
    def cols(names):
        return np.column_stack([p[k][indices] for k in names]).astype(np.float32)
    n = len(indices)
    if all(f'f_dc_{i}' in p for i in range(3)):
        rgb = cols([f'f_dc_{i}' for i in range(3)]) * 0.28209479177387814 + 0.5
    elif all(k in p for k in ('red', 'green', 'blue')):
        rgb = cols(['red', 'green', 'blue']) / 255.0
    else:
        rgb = np.full((n, 3), 0.8, dtype=np.float32)
    opacity = sigmoid(p['opacity'][indices]).astype(np.float32) if 'opacity' in p else np.full(n, 0.8, dtype=np.float32)
    if all(f'scale_{i}' in p for i in range(3)):
        scale = np.exp(np.clip(cols([f'scale_{i}' for i in range(3)]), -15, 8))
    else:
        scale = np.full((n, 3), radius * 0.005, dtype=np.float32)
    if all(f'rot_{i}' in p for i in range(4)):
        rot = quaternion_matrices(cols([f'rot_{i}' for i in range(4)])).astype(np.float32)
    else:
        rot = np.broadcast_to(np.eye(3, dtype=np.float32), (n, 3, 3))
    return np.clip(rgb, 0, 1), opacity, scale, rot


def render(path, yaw=0, pitch=0, distance=None, width=512, height=512,
           max_gaussians=None, fov=30.0, background=(0.5, 0.5, 0.5), roll=0.0):
    """Render a single 3DGS view; return a PIL RGB image.

    Orbit convention: yaw 0 is +Z, yaw 90 is +X; Y-up.
    Uses depth-sorted, back-to-front alpha blending (approximate GS rasterization).
    """
    import moderngl
    if width < 1 or height < 1 or not 1 < fov < 179:
        raise ValueError('Invalid image dimensions or FOV')
    p = read_ply(path)
    if not all(k in p for k in ('x', 'y', 'z')):
        raise ValueError('PLY requires x/y/z vertex properties')
    xyz_all = np.column_stack([p[k] for k in ('x', 'y', 'z')]).astype(np.float32)
    n = len(xyz_all)
    if n == 0:
        raise ValueError('Empty PLY')
    if not np.isfinite(xyz_all).all():
        raise ValueError('PLY has non-finite coordinates')
    indices = np.arange(n, dtype=np.int64)
    if max_gaussians is not None:
        if max_gaussians <= 0:
            raise ValueError('max_gaussians must be positive')
        if max_gaussians < n:
            indices = np.linspace(0, n - 1, max_gaussians, dtype=np.int64)
    center = np.median(xyz_all, axis=0)
    radius = max(float(np.percentile(np.linalg.norm(xyz_all - center, axis=1), 95)), 1e-3)
    if distance is None:
        distance = radius * 3.5
    if distance <= 0:
        raise ValueError('distance must be positive')
    from orbit_camera import orbit_basis
    eye, right, up, back = orbit_basis(center, distance, yaw, pitch, roll)
    forward = -back
    basis = np.stack([right, up, forward]).astype(np.float32)
    xyz = xyz_all[indices]
    cam = (xyz - eye) @ basis.T
    depth = cam[:, 2]
    visible = np.isfinite(depth) & (depth > 1e-3)
    indices = indices[visible]
    cam = cam[visible]
    depth = depth[visible]
    if len(indices) == 0:
        return Image.new('RGB', (width, height), tuple(int(c*255) for c in background))
    # Far to near for SRC_ALPHA / ONE_MINUS_SRC_ALPHA compositing.
    order = np.argsort(depth)[::-1]
    indices, cam, depth = indices[order], cam[order], depth[order]
    rgb, opacity, scales, rot = _attributes(p, indices, radius)
    # World covariance -> camera covariance -> screen covariance.
    cov = np.einsum('nij,nj,nkj->nik', rot, scales*scales, rot, optimize=True)
    covcam = np.einsum('ij,njk,lk->nil', basis, cov, basis, optimize=True)
    focal = height / (2 * math.tan(math.radians(fov) / 2))
    z = depth
    center_px = np.column_stack([focal*cam[:,0]/z + width/2,
                                 focal*cam[:,1]/z + height/2]).astype(np.float32)
    jac = np.zeros((len(z), 2, 3), dtype=np.float32)
    jac[:,0,0] = focal/z
    jac[:,0,2] = -focal*cam[:,0]/(z*z)
    jac[:,1,1] = focal/z
    jac[:,1,2] = -focal*cam[:,1]/(z*z)
    cov2 = np.einsum('nij,njk,nlk->nil', jac, covcam, jac, optimize=True)
    cov2[:,0,0] += 0.3
    cov2[:,1,1] += 0.3
    # Covariance eigenvectors are the screen-space ellipse principal axes.
    eigenval, eigenvec = np.linalg.eigh(cov2)
    eigenval = np.maximum(eigenval, 1e-5)
    axes = eigenvec * np.sqrt(eigenval)[:, None, :]
    # Clamp very large splats to avoid pathological screen-space geometry.
    axes = np.clip(axes, -max(width,height)*2, max(width,height)*2)
    valid = (opacity >= 0.005) & np.isfinite(axes).all(axis=(1,2)) & np.isfinite(center_px).all(axis=1)
    # Conservative screen-space rejection.
    bound = 3.0 * np.linalg.norm(axes, axis=1).sum(axis=1)
    valid &= (center_px[:,0] + bound >= 0) & (center_px[:,0] - bound < width)
    valid &= (center_px[:,1] + bound >= 0) & (center_px[:,1] - bound < height)
    # center xy, axis0 xy, axis1 xy, RGBA = 10 floats/instance.
    data = np.column_stack([center_px, axes[:,:,0], axes[:,:,1], rgb, opacity]).astype('f4')[valid]
    print(f'3DGS: {n:,} total, {len(data):,} visible splats', flush=True)
    ctx = _context()
    try:
        tex = ctx.texture((width, height), 4, dtype='f1')
        framebuffer = ctx.framebuffer(color_attachments=[tex])
        framebuffer.use()
        ctx.viewport = (0, 0, width, height)
        framebuffer.clear(*background, 1.0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        program = ctx.program(vertex_shader=VS, fragment_shader=FS)
        program['u_size'].value = (float(width), float(height))
        # Two triangles spanning the [-3,3] standard-deviation square.
        corners = np.array([[-3,-3], [3,-3], [-3,3], [-3,3], [3,-3], [3,3]], dtype='f4')
        quad = ctx.buffer(corners.tobytes())
        instances = ctx.buffer(data.tobytes() if len(data) else bytes(40))
        vao = ctx.vertex_array(program, [(quad, '2f', 'in_corner'),
                                         (instances, '2f 2f 2f 4f /i', 'in_center', 'in_axis0', 'in_axis1', 'in_rgba')])
        if len(data):
            vao.render(mode=moderngl.TRIANGLES, vertices=6, instances=len(data))
        raw = framebuffer.read(components=3, alignment=1)
        image = Image.frombytes('RGB', (width, height), raw)
        vao.release(); instances.release(); quad.release(); program.release()
        framebuffer.release(); tex.release()
        return image
    finally:
        ctx.release()


def main():
    ap = argparse.ArgumentParser(description='EzRender experimental OpenGL/EGL 3DGS still renderer')
    ap.add_argument('model_file')
    ap.add_argument('--yaw', type=float, default=0)
    ap.add_argument('--roll', type=float, default=0)
    ap.add_argument('--pitch', type=float, default=0)
    ap.add_argument('--distance', type=float)
    ap.add_argument('--size', default='512x512')
    ap.add_argument('--output')
    ap.add_argument('--no-view', action='store_true')
    ap.add_argument('--max-gaussians', type=int)
    ap.add_argument('--fov', type=float, default=30)
    ap.add_argument('--info', action='store_true')
    args = ap.parse_args()
    w, h = map(int, args.size.lower().split('x'))
    if args.info:
        p = read_ply(args.model_file)
        print(f'Gaussians: {len(p["x"]):,}; fields: {", ".join(p)}')
    start = time.monotonic()
    img = render(args.model_file, args.yaw, args.pitch, args.distance, w, h,
                 args.max_gaussians, args.fov, roll=args.roll)
    print(f'Render time: {time.monotonic()-start:.2f}s')
    if args.output:
        out = args.output if args.output.lower().endswith('.webp') else args.output + '.webp'
        img.save(out)
        print('Saved:', out)
    if not args.no_view:
        with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as temp:
            name = temp.name
        try:
            img.save(name)
            subprocess.run(['timg', name], check=True)
        finally:
            os.unlink(name)

if __name__ == '__main__':
    main()
