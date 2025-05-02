#!/home/< USER >/miniconda3/envs/< CONDA_ENV >/bin/python
 
# Era3Dのinstant-nsl-plが出力した objを修正してアーティファクトがでないよう補正する (出力は obj または glb)
 
 
import argparse
import numpy as np
import trimesh
import os
 
def srgb_to_linear(c):
    return np.where(c <= 0.04045,
                    c / 12.92,
                    ((c + 0.055) / 1.055) ** 2.4)
 
def linear_to_srgb(c):
    return np.where(c <= 0.0031308,
                    c * 12.92,
                    1.055 * (c ** (1 / 2.4)) - 0.055)
 
def load_obj_with_vertex_colors(obj_path):
    vertices = []
    vertex_colors = []
    faces = []
 
    with open(obj_path, 'r') as file:
        for line in file:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == 'v':
                x, y, z = map(float, parts[1:4])
                if len(parts) >= 7:
                    r, g, b = map(float, parts[4:7])
                else:
                    r, g, b = 1.0, 1.0, 1.0
                vertices.append([x, y, z])
                vertex_colors.append([r, g, b])
            elif parts[0] == 'f':
                face = [int(idx.split('/')[0]) - 1 for idx in parts[1:]]
                faces.append(face)
 
    vertices = np.array(vertices)
    vertex_colors = np.array(vertex_colors, dtype=np.float32)
    vertex_colors_linear = srgb_to_linear(np.clip(vertex_colors, 0.0, 1.0))
    faces = np.array(faces)
 
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    return mesh, vertex_colors_linear
 
def flip_mesh(mesh):
    mesh.vertices[:, 0] *= -1
    mesh.faces = mesh.faces[:, ::-1]
 
def save_obj_with_vertex_colors(mesh, rgb_linear, output_path):
    rgb_srgb = linear_to_srgb(np.clip(rgb_linear, 0.0, 1.0))  # ← sRGBに戻す
    with open(output_path, 'w') as f:
        for v, c in zip(mesh.vertices, rgb_srgb):
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f} {c[0]:.6f} {c[1]:.6f} {c[2]:.6f}\n")
        for face in mesh.faces:
            idxs = face + 1
            f.write(f"f {idxs[0]} {idxs[1]} {idxs[2]}\n")
 
def main():
    parser = argparse.ArgumentParser(description="Fix and convert OBJ mesh (GLB or sRGB-colored OBJ).")
    parser.add_argument("input", type=str, help="Input OBJ file path.")
    parser.add_argument("-o", "--output", type=str, default="output.glb", help="Output file path (.glb or .obj).")
    parser.add_argument("--no-flip", action="store_true", help="Disable flipping the model horizontally.")
    args = parser.parse_args()
 
    if not os.path.isfile(args.input):
        print(f"Error: Input file not found: {args.input}")
        return
 
    print(f"Reading OBJ file: {args.input}")
    try:
        mesh, vertex_colors_linear = load_obj_with_vertex_colors(args.input)
    except Exception as e:
        print(f"Error loading OBJ file: {e}")
        return
 
    if not args.no_flip:
        print("Flipping the model horizontally.")
        flip_mesh(mesh)
 
    output_path = args.output
    ext = os.path.splitext(output_path)[1].lower()
 
    if ext == ".glb":
        print(f"Exporting GLB file: {output_path}")
        mesh.visual.vertex_colors = np.hstack((vertex_colors_linear, np.ones((len(vertex_colors_linear), 1))))
        mesh.export(output_path)
    elif ext == ".obj":
        print(f"Exporting OBJ file: {output_path}")
        save_obj_with_vertex_colors(mesh, vertex_colors_linear, output_path)
    else:
        print("Error: Output file must end with .glb or .obj.")
        return
 
    print("Conversion completed successfully!")
 
if __name__ == "__main__":
    main()
