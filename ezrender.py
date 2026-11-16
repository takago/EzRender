#!/home/< USER >/miniconda3/envs/< CONDA_ENV >/bin/python

import os
os.environ["PYOPENGL_PLATFORM"] = "egl"

import sys
import argparse
import numpy as np
import tempfile
import subprocess
import trimesh
import pyrender
from PIL import Image

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
    with open(input_path, 'r') as fin, open(temp_path, 'w') as fout:
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
                    except:
                        fout.write(line)
                else:
                    fout.write(line)
            else:
                fout.write(line)
    return temp_path

def look_at_view_matrix(eye, target, up=[0, 1, 0]):
    forward = np.array(target) - np.array(eye)
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    view = np.eye(4)
    view[0, :3] = right
    view[1, :3] = true_up
    view[2, :3] = -forward
    view[:3, 3] = -view[:3, :3] @ eye
    return view

def load_model(path):
    loaded = trimesh.load(path)
    return loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)


def parse_xyz(text):
    try:
        parts = [float(x.strip()) for x in text.split(",")]
        if len(parts) != 3:
            raise ValueError
        return np.array(parts)
    except:
        raise argparse.ArgumentTypeError("形式は x,y,z の3値（例: 1.0,2.0,3.0）")

def parse_size(text):
    try:
        width, height = text.lower().split("x")
        return int(width), int(height)
    except:
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
    camera = pyrender.PerspectiveCamera(yfov=np.pi / 6.0)
    camera_node = scene.add(camera, pose=pose)
    light = pyrender.PointLight(color=np.ones(3), intensity=intensity)
    light_node = scene.add(light, pose=pose)
    renderer = pyrender.OffscreenRenderer(width, height)
    color, _ = renderer.render(scene, flags=pyrender.RenderFlags.RGBA)
    renderer.delete()
    scene.remove_node(camera_node)
    scene.remove_node(light_node)
    return Image.fromarray(color, mode="RGBA")

from orbit_camera import orbit_view

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
        angles = [args.yaw] if (args.yaw is not None or args.distance is not None or args.pitch is not None or args.roll != 0) else [0, 90, 180, 270]
        if angles == [None]:
            angles = [0]
        start = time.monotonic()
        frames = [render_gaussians(args.model_file, yaw=a, pitch=args.pitch if args.pitch is not None else 0, roll=args.roll,
                                  distance=args.distance, width=width, height=height,
                                  max_gaussians=args.max_gaussians, fov=args.fov)
                  for a in angles]
        if len(frames) == 1:
            img = frames[0]
        else:
            img = Image.new("RGB", (width * len(frames), height))
            for i, frame in enumerate(frames):
                img.paste(frame, (i * width, 0))
        print(f"Render time: {time.monotonic()-start:.2f}s")
        if args.output:
            out = args.output if args.output.lower().endswith(".webp") else args.output + ".webp"
            img.save(out)
            print("Image saved:", out)
        if show_view:
            with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as tmp:
                preview_path = tmp.name
            try:
                img.save(preview_path)
                subprocess.run(["timg", preview_path], check=True)
            finally:
                os.unlink(preview_path)
        elif not args.output:
            print("No output or view specified. Use --output or omit --no-view.")
        return

    temp_file = None
    model_file = args.model_file
    if model_file.lower().endswith(".obj"):
        try:
            temp_file = convert_obj_srgb_to_linear(model_file)
            print(f"🎨 Converted OBJ sRGB → Linear: {temp_file}")
            model_file = temp_file
        except Exception as e:
            print("❌ OBJ変換に失敗しました:", e)
            sys.exit(1)

    tri_scene = load_model(model_file)
    center = tri_scene.centroid
    scale = np.linalg.norm(tri_scene.extents)
    width, height = args.size

    intensity = args.light_intensity if args.light_intensity is not None else scale * 10.0
    if args.light_intensity is None:
        print(f"💡 Auto-set light intensity to {intensity:.1f} based on model scale")

    scene = pyrender.Scene.from_trimesh_scene(tri_scene, bg_color=[0.5, 0.5, 0.5, 1.0])

    if args.cam_xyz is not None or args.distance is not None or args.yaw is not None or args.pitch is not None or args.roll != 0:
        if args.yaw is not None and args.distance is None:
            args.distance = scale * 2.0
            print(f"📏 Auto-set distance: {args.distance:.2f}")
        if args.cam_xyz is None:
            if args.yaw is None:
                args.yaw = 0.0
            if args.distance is None:
                args.distance = scale * 2.0
        eye = args.cam_xyz
        view = look_at_view_matrix(eye, center) if args.cam_xyz is not None else orbit_view(center, args.distance, args.yaw, args.pitch or 0, args.roll)
        camera_pose = np.linalg.inv(view)
        img = render_image(scene, camera_pose, width, height, intensity)
    else:
        angles = [0, 90, 180, 270]
        images = []
        for ang in angles:
            view = orbit_view(center, scale * 2.0, ang, args.pitch or 0, args.roll)
            pose = np.linalg.inv(view)
            img_piece = render_image(scene, pose, width, height, intensity)
            images.append(img_piece)
        img = Image.new("RGBA", (width * 4, height))
        for i, piece in enumerate(images):
            img.paste(piece, (i * width, 0))

    if args.output:
        out = args.output if args.output.lower().endswith(".webp") else args.output + ".webp"
        img.save(out)
        print("Image saved:", out)

    if show_view:
        tmpfile = "_tmp_render.webp"
        img.save(tmpfile)
        os.system(f"timg {tmpfile}")
        os.remove(tmpfile)
    elif not args.output:
        print("⚠️ No output or view specified. Use --output or omit --no-view to preview.")

    if temp_file and os.path.exists(temp_file):
        os.remove(temp_file)

if __name__ == "__main__":
    main()
