#!/home/< USER >/miniconda3/envs/< CONDA_ENV >/bin/python
# Era3Dのinstant-nsr-plで出力した objファイルを修正するプログラム

import argparse
import trimesh
import numpy as np
 
def srgb_to_linear(color):
    """sRGBカラーをLinearカラーに変換（安全な処理）"""
    color = np.clip(color, 0.0, 1.0)  # 必ず0.0～1.0の範囲に収める
    return np.where(color <= 0.04045,
                    color / 12.92,
                    ((color + 0.055) / 1.055) ** 2.4)
 
def load_obj_with_vertex_colors(obj_path):
    """OBJファイルを読み込み、頂点カラーを処理"""
    vertices = []
    vertex_colors = []
    faces = []
 
    with open(obj_path, 'r') as file:
        for line in file:
            parts = line.strip().split()
            if not parts:
                continue
 
            # 頂点情報の解析
            if parts[0] == 'v':  # 頂点情報
                x, y, z = map(float, parts[1:4])
                r, g, b = map(float, parts[4:7])  # カラー情報
                vertices.append([x, y, z])
                vertex_colors.append([r, g, b])  # RGB形式で格納
 
            # 面情報の解析
            elif parts[0] == 'f':  # 面情報
                face = [int(idx.split('/')[0]) - 1 for idx in parts[1:]]
                faces.append(face)
 
    # numpy配列に変換
    vertices = np.array(vertices)
    vertex_colors = np.array(vertex_colors, dtype=np.float32)
 
    # 頂点カラーを事前にクリップ
    vertex_colors_clipped = np.clip(vertex_colors, 0.0, 1.0)
 
    # カラー情報をsRGB -> Linearに変換
    vertex_colors_linear = srgb_to_linear(vertex_colors_clipped)
 
    # 面情報をnumpy配列に変換
    faces = np.array(faces)
 
    # trimeshメッシュ作成
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual.vertex_colors = vertex_colors_linear
    return mesh
 
def flip_mesh(mesh):
    """左右反転後に法線方向を修正"""
    # x軸を反転
    mesh.vertices[:, 0] *= -1
 
    # 面の頂点インデックスを反転
    mesh.faces = mesh.faces[:, ::-1]  # 反転して法線方向を維持
 
def main():
    """コマンドライン引数を解析してGLBを生成"""
    parser = argparse.ArgumentParser(description="Convert an OBJ file to GLB format with vertex colors.")
    parser.add_argument("input", type=str, help="Input OBJ file path.")
    parser.add_argument("-o", "--output", type=str, default="output.glb", help="Output GLB file path.")
    parser.add_argument("--no-flip", action="store_true", help="Disable flipping the model horizontally.")
 
    args = parser.parse_args()
 
    # OBJファイルを読み込み
    print(f"Reading OBJ file: {args.input}")
    mesh = load_obj_with_vertex_colors(args.input)
 
    # 左右反転処理
    if not args.no_flip:
        print("Flipping the model horizontally (default behavior).")
        flip_mesh(mesh)
 
    # 出力ファイルをGLB形式でエクスポート
    output_path = args.output
    if not output_path.endswith(".glb"):
        print("Error: Output file must have a .glb extension.")
        return
 
    print(f"Exporting GLB file: {output_path}")
    mesh.export(output_path)
    print("Conversion completed successfully!")
 
if __name__ == "__main__":
    main()
