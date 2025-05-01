#!/home/< USER >/miniconda3/envs/< CONDA_ENV >/bin/python

import os
os.environ["PYOPENGL_PLATFORM"] = "egl"

import sys
import argparse
import numpy as np
import trimesh
import pyrender
from PIL import Image

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

def spherical_camera_position(center, distance, angle_deg):
    theta = np.radians(angle_deg)
    x = distance * np.cos(theta)
    z = distance * np.sin(theta)
    y = distance * 0.1
    return center + np.array([x, y, z])

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

def main():
    parser = argparse.ArgumentParser(description="Render a 3D model to a still image")
    parser.add_argument("model_file", help="3D model file (.obj or .glb)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--distance", type=float, help="Distance from model center (spherical)")
    group.add_argument("--cam-xyz", type=parse_xyz, help="Camera position x,y,z")
    parser.add_argument("--angle", type=float, help="Azimuth angle (degrees)")
    parser.add_argument("--output", type=str, help="Output file (.webp)")
    parser.add_argument("--no-view", action="store_true", help="Disable timg preview (default is ON)")
    parser.add_argument("--info", action="store_true", help="Display model information")
    parser.add_argument("--size", type=parse_size, default=(512, 512), help="Output size WIDTHxHEIGHT (default: 512x512)")
    parser.add_argument("--light-intensity", type=float, help="Light intensity (auto if omitted)")

    args = parser.parse_args()
    show_view = not args.no_view

    if not os.path.exists(args.model_file):
        print("File not found:", args.model_file)
        sys.exit(1)

    tri_scene = load_model(args.model_file)
    center = tri_scene.centroid
    scale = np.linalg.norm(tri_scene.extents)
    width, height = args.size

    if args.info:
        try:
            import tabulate
        except ImportError:
            print("The 'tabulate' module is required for --info output. Install it with: pip install tabulate")
            sys.exit(1)
        print_scene_info(tri_scene)

    intensity = args.light_intensity if args.light_intensity is not None else scale * 10.0
    if args.light_intensity is None:
        print(f"💡 Auto-set light intensity to {intensity:.1f} based on model scale")

    scene = pyrender.Scene.from_trimesh_scene(tri_scene, bg_color=[0.5, 0.5, 0.5, 1.0])

    if args.cam_xyz is not None or args.distance is not None or args.angle is not None:
        if args.distance is not None and args.angle is None:
            args.angle = np.random.uniform(0, 360)
            print(f"🎯 Random angle assigned: {args.angle:.1f}°")
        if args.angle is not None and args.distance is None:
            args.distance = scale * 2.0
            print(f"📏 Auto-set distance: {args.distance:.2f}")
        eye = args.cam_xyz if args.cam_xyz is not None else spherical_camera_position(center, args.distance, args.angle)
        view = look_at_view_matrix(eye, center)
        camera_pose = np.linalg.inv(view)
        img = render_image(scene, camera_pose, width, height, intensity)
    else:
        angles = [0, 90, 180, 270]
        images = []
        for ang in angles:
            eye = spherical_camera_position(center, scale * 2.0, ang)
            view = look_at_view_matrix(eye, center)
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

if __name__ == "__main__":
    main()
