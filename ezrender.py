#!/usr/bin/env python3

import os
os.environ["PYOPENGL_PLATFORM"] = "egl"

import sys
from contextlib import contextmanager
from pathlib import Path
import argparse
import numpy as np
import tempfile
import subprocess
import trimesh
from PIL import Image
from orbit_camera import orbit_view

def srgb_to_linear(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(
        c <= 0.04045,
        c / 12.92,
        ((c + 0.055) / 1.055) ** 2.4
    )

def convert_obj_srgb_to_linear(input_path):
    temp_fd, temp_path = tempfile.mkstemp(suffix=".obj")
    os.close(temp_fd)
    try:
        with open(input_path, "r") as fin, open(temp_path, "w") as fout:
            _convert_obj_lines(fin, fout)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise
    return temp_path

def _convert_obj_lines(fin, fout):
    for line in fin:
        if line.startswith('v '):
            parts = line.strip().split()
            if len(parts) == 7:
                try:
                    r, g, b = map(float, parts[4:7])
                    rgb = np.array([r, g, b])
                    linear = srgb_to_linear(rgb)
                    newline = f"v {parts[1]} {parts[2]} {parts[3]} {linear[0]:.6f} {linear[1]:.6f} {linear[2]:.6f}\n"
                    fout.write(newline)
                except ValueError:
                    fout.write(line)
            else:
                fout.write(line)
        else:
            fout.write(line)

def look_at_view_matrix(eye, target, up=(0, 1, 0)):
    forward = np.asarray(target, dtype=float) - np.asarray(eye, dtype=float)
    length = np.linalg.norm(forward)
    if length == 0 or not np.isfinite(length):
        raise ValueError("Camera position must differ from the target")
    forward /= length
    right = np.cross(forward, up)
    norm = np.linalg.norm(right)
    if norm < 1e-10:
        right = np.cross(forward, (0, 0, 1))
        norm = np.linalg.norm(right)
    right /= norm
    true_up = np.cross(right, forward)
    view = np.eye(4)
    view[:3, :3] = np.stack((right, true_up, -forward))
    view[:3, 3] = -view[:3, :3] @ eye
    return view

@contextmanager
def prepared_model(path):
    """Convert colored OBJ temporarily and clean it up even on errors."""
    if not path.lower().endswith(".obj"):
        yield path
        return
    temporary = convert_obj_srgb_to_linear(path)
    try:
        print(f"🎨 Converted OBJ sRGB → Linear: {temporary}")
        yield temporary
    finally:
        Path(temporary).unlink(missing_ok=True)

def load_model(path):
    loaded = trimesh.load(path)
    return loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)


def parse_xyz(text):
    try:
        parts = [float(x.strip()) for x in text.split(",")]
        if len(parts) != 3:
            raise ValueError
        return np.array(parts)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("形式は x,y,z の3値（例: 1.0,2.0,3.0）")

def parse_size(text):
    try:
        width, height = text.lower().split("x")
        return int(width), int(height)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("--size は WIDTHxHEIGHT（例: 800x600）形式")

def describe_color_attribution(mesh):
    kind = mesh.visual.kind
    if kind == "vertex":
        vc = mesh.visual.vertex_colors
        channels = vc.shape[1] if vc is not None else 0
        return f"Vertex Color ({'RGBA' if channels == 4 else 'RGB'})"
    elif kind == "texture":
        return "Texture Mapping (UV + Image)"
    elif kind == "face":
        return "Face Color"
    else:
        return "None"

def print_scene_info(scene):
    from tabulate import tabulate
    meshes = list(scene.geometry.values())
    print(f"🔍 Model Information (Total Meshes: {len(meshes)})\n")
    table = []
    headers = ["Mesh", "Vertices", "Faces", "Color Attribution", "UV Mapping"]
    for i, mesh in enumerate(meshes):
        row = [
            f"{i}",
            str(len(mesh.vertices)),
            str(len(mesh.faces)),
            describe_color_attribution(mesh),
            "Yes" if hasattr(mesh.visual, 'uv') and mesh.visual.uv is not None else "No"
        ]
        table.append(row)
    print(tabulate(table, headers=headers, tablefmt="grid"))

def print_3dgs_info(path):
    """Inspect a 3DGS PLY header without reading Gaussian data or initializing GL."""
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("Not a PLY file")
        fmt = None
        element = None
        count = None
        fields = []
        while True:
            line = f.readline()
            if not line:
                raise ValueError("Truncated PLY header")
            tokens = line.decode("ascii").split()
            if not tokens:
                continue
            if tokens[0] == "format" and len(tokens) >= 2:
                fmt = tokens[1]
            elif tokens[0] == "element" and len(tokens) >= 3:
                element = tokens[1]
                if element == "vertex":
                    count = int(tokens[2])
            elif tokens[0] == "property" and element == "vertex":
                if len(tokens) < 3 or tokens[1] == "list":
                    raise ValueError("Unsupported PLY vertex property")
                fields.append(tokens[2])
            elif tokens[0] == "end_header":
                break
    if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise ValueError(f"Unsupported PLY format: {fmt}")
    if count is None:
        raise ValueError("No vertex element in PLY")
    print("3D Gaussian Splatting Information")
    print(f"Gaussians: {count:,}")
    print(f"PLY format: {fmt}")
    print(f"Fields ({len(fields)}): {', '.join(fields)}")


def render_image(scene, pose, width, height, intensity):
    import pyrender
    camera_node = scene.add(pyrender.PerspectiveCamera(yfov=np.pi / 6.0), pose=pose)
    light_node = None
    renderer = None
    try:
        light_node = scene.add(pyrender.PointLight(color=np.ones(3), intensity=intensity), pose=pose)
        renderer = pyrender.OffscreenRenderer(width, height)
        color, _ = renderer.render(scene, flags=pyrender.RenderFlags.RGBA)
        return Image.fromarray(color, mode="RGBA")
    finally:
        if renderer is not None:
            renderer.delete()
        if light_node is not None:
            scene.remove_node(light_node)
        scene.remove_node(camera_node)


def join_views(frames):
    if len(frames) == 1:
        return frames[0]
    width, height = frames[0].size
    image = Image.new(frames[0].mode, (width * len(frames), height))
    for i, frame in enumerate(frames):
        image.paste(frame, (i * width, 0))
    return image


def save_and_preview(image, output, show_view):
    if output:
        out = output if output.lower().endswith(".webp") else output + ".webp"
        image.save(out)
        print("Image saved:", out)
    if show_view:
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as tmp:
            preview_path = tmp.name
        try:
            image.save(preview_path)
            subprocess.run(["timg", preview_path], check=True)
        finally:
            Path(preview_path).unlink(missing_ok=True)
    elif not output:
        print("No output or view specified. Use --output or omit --no-view.")


def requested_angles(args):
    single = (args.cam_xyz is not None or args.yaw is not None or
              args.distance is not None or args.pitch is not None or args.roll != 0)
    return [args.yaw if args.yaw is not None else 0] if single else [0, 90, 180, 270]

def main():
    parser = argparse.ArgumentParser(description="Render a 3D model to a still image")
    parser.add_argument("model_file", help="3D model file (.obj, .glb, or 3DGS .ply)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--distance", type=float, help="Distance from model center (spherical)")
    group.add_argument("--cam-xyz", type=parse_xyz, help="Camera position x,y,z")
    parser.add_argument("--yaw", type=float, help="Orbit yaw in degrees (0: +Z, 90: +X)")
    parser.add_argument("--angle", type=float, help=argparse.SUPPRESS)  # Legacy alias
    parser.add_argument("--roll", type=float, default=0.0, help="Camera roll in degrees (positive: clockwise tilt)")
    parser.add_argument("--output", type=str, help="Output file (.webp)")
    parser.add_argument("--no-view", action="store_true", help="Disable timg preview (default is ON)")
    parser.add_argument("--info", action="store_true", help="Display model information")
    parser.add_argument("--size", type=parse_size, default=(512, 512), help="Output size WIDTHxHEIGHT (default: 512x512)")
    parser.add_argument("--light-intensity", type=float, help="Light intensity (auto if omitted; mesh only)")
    parser.add_argument("--pitch", type=float, default=None, help="Camera elevation in degrees (positive: from above)")
    parser.add_argument("--3dgs", dest="three_dgs", action="store_true", help="Interpret a PLY file as 3D Gaussian Splatting")
    parser.add_argument("--fov", type=float, default=30, help="3DGS vertical field of view (degrees)")
    parser.add_argument("--max-gaussians", type=int, help="Limit 3DGS Gaussian count for previews")

    args = parser.parse_args()
    if args.angle is not None:
        if args.yaw is not None:
            parser.error("--yaw and legacy --angle cannot be combined")
        args.yaw = args.angle
    if args.pitch is not None and not -90 <= args.pitch <= 90:
        parser.error("--pitch must be within [-90, 90]")
    show_view = not args.no_view

    if not os.path.exists(args.model_file):
        print("File not found:", args.model_file)
        sys.exit(1)

    # --info is inspection-only: no rendering, preview, or image output.
    if args.info:
        if args.three_dgs:
            if not args.model_file.lower().endswith(".ply"):
                parser.error("--3dgs requires a .ply file")
            try:
                print_3dgs_info(args.model_file)
            except (OSError, ValueError, UnicodeDecodeError) as exc:
                parser.exit(1, f"Failed to read 3DGS information: {exc}\n")
        else:
            try:
                print_scene_info(load_model(args.model_file))
            except (OSError, ValueError) as exc:
                parser.exit(1, f"Failed to read model information: {exc}\n")
        return

    # Gaussian PLY uses its own renderer; do not send splats to trimesh/pyrender.
    if args.three_dgs:
        if not args.model_file.lower().endswith(".ply"):
            parser.error("--3dgs requires a .ply file")
        from gs_gl import render as render_gaussians
        import time
        width, height = args.size
        if args.cam_xyz is not None:
            parser.error("--cam-xyz is not yet supported for 3DGS; use --yaw/--pitch/--distance")
        if args.light_intensity is not None:
            parser.error("--light-intensity applies to meshes only (3DGS has baked colors)")
        angles = requested_angles(args)
        start = time.monotonic()
        frames = [render_gaussians(args.model_file, yaw=a, pitch=args.pitch or 0, roll=args.roll,
                                  distance=args.distance, width=width, height=height,
                                  max_gaussians=args.max_gaussians, fov=args.fov)
                  for a in angles]
        img = join_views(frames)
        print(f"Render time: {time.monotonic()-start:.2f}s")
        save_and_preview(img, args.output, show_view)
        return

    import pyrender
    with prepared_model(args.model_file) as model_file:
        tri_scene = load_model(model_file)
        center = tri_scene.centroid
        scale = np.linalg.norm(tri_scene.extents)
        width, height = args.size
        intensity = args.light_intensity if args.light_intensity is not None else scale * 10.0
        if args.light_intensity is None:
            print(f"💡 Auto-set light intensity to {intensity:.1f} based on model scale")
        scene = pyrender.Scene.from_trimesh_scene(tri_scene, bg_color=[0.5, 0.5, 0.5, 1.0])
        frames = []
        for yaw in requested_angles(args):
            if args.cam_xyz is not None:
                view = look_at_view_matrix(args.cam_xyz, center)
            else:
                view = orbit_view(center, args.distance if args.distance is not None else scale * 2.0,
                                  yaw, args.pitch or 0, args.roll)
            frames.append(render_image(scene, np.linalg.inv(view), width, height, intensity))
        save_and_preview(join_views(frames), args.output, show_view)

if __name__ == "__main__":
    main()
