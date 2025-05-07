#!/home/<USER>/miniconda3/envs/<CONDA_ENV>/bin/python

# Era3Dのinstant-nsl-plが出力したOBJファイルを補正し、
# sRGBカラーを維持したまま左右反転してOBJとして再出力するスクリプトです。
# （Blenderで正しく読み出せるようにもなります）
#
# - 入力: 頂点カラー付きOBJファイル（v行にRGBが含まれている）
# - 出力: sRGBカラーのOBJファイル
# - 処理内容:
#     - sRGB → リニア変換（内部処理用）
#     - 左右反転（オプションで無効化可）
#     - リニア → sRGBへ戻し、OBJファイルへ保存

import argparse
import numpy as np
import trimesh
import os

# sRGBからリニア色空間への変換（γ補正を外す）
def srgb_to_linear(c):
    return np.where(c <= 0.04045,
                    c / 12.92,
                    ((c + 0.055) / 1.055) ** 2.4)

# リニア色空間からsRGBへの変換（γ補正をかける）
def linear_to_srgb(c):
    return np.where(c <= 0.0031308,
                    c * 12.92,
                    1.055 * (c ** (1 / 2.4)) - 0.055)

# OBJファイルを読み込み、頂点位置・頂点カラー（sRGB）・面情報を抽出
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
                # 頂点座標 + 頂点カラー（r,g,b）
                x, y, z = map(float, parts[1:4])
                if len(parts) >= 7:
                    r, g, b = map(float, parts[4:7])
                else:
                    r, g, b = 1.0, 1.0, 1.0  # デフォルトは白
                vertices.append([x, y, z])
                vertex_colors.append([r, g, b])
            elif parts[0] == 'f':
                # 面情報（1-based → 0-basedへ変換）
                face = [int(idx.split('/')[0]) - 1 for idx in parts[1:]]
                faces.append(face)

    # numpy配列に変換
    vertices = np.array(vertices)
    vertex_colors = np.array(vertex_colors, dtype=np.float32)
    vertex_colors_linear = srgb_to_linear(np.clip(vertex_colors, 0.0, 1.0))
    faces = np.array(faces)

    # trimeshオブジェクトを作成
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    return mesh, vertex_colors_linear

# メッシュをX軸方向で左右反転し、面の向きも補正（反時計回り→時計回りなど）
def flip_mesh(mesh):
    mesh.vertices[:, 0] *= -1
    mesh.faces = mesh.faces[:, ::-1]

# OBJ形式でメッシュとsRGB頂点カラーを書き出す
def save_obj_with_vertex_colors(mesh, rgb_linear, output_path):
    rgb_srgb = linear_to_srgb(np.clip(rgb_linear, 0.0, 1.0))  # sRGBに戻す
    with open(output_path, 'w') as f:
        for v, c in zip(mesh.vertices, rgb_srgb):
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f} {c[0]:.6f} {c[1]:.6f} {c[2]:.6f}\n")
        for face in mesh.faces:
            idxs = face + 1  # OBJは1始まり
            f.write(f"f {idxs[0]} {idxs[1]} {idxs[2]}\n")

# メイン処理：引数解析 → 読み込み → 反転（必要に応じて） → OBJ出力
def main():
    parser = argparse.ArgumentParser(description="Era3D出力OBJの補正：sRGB補正＋左右反転＋再出力")
    parser.add_argument("input", type=str, help="入力OBJファイルパス")
    parser.add_argument("-o", "--output", type=str, default="output.obj", help="出力OBJファイル名（.obj）")
    parser.add_argument("--no-flip", action="store_true", help="左右反転を行わない")
    args = parser.parse_args()

    # 入力ファイル存在確認
    if not os.path.isfile(args.input):
        print(f"エラー: 入力ファイルが見つかりません: {args.input}")
        return

    # 拡張子チェック（.objのみ許可）
    ext = os.path.splitext(args.output)[1].lower()
    if ext != ".obj":
        print("エラー: 出力ファイルの拡張子は .obj にしてください。")
        return

    print(f"OBJファイル読み込み中: {args.input}")
    try:
        mesh, vertex_colors_linear = load_obj_with_vertex_colors(args.input)
    except Exception as e:
        print(f"エラー: OBJ読み込みに失敗しました: {e}")
        return

    if not args.no_flip:
        print("左右反転処理を実行中...")
        flip_mesh(mesh)

    print(f"OBJファイルを書き出します: {args.output}")
    save_obj_with_vertex_colors(mesh, vertex_colors_linear, args.output)

    print("処理完了！")

if __name__ == "__main__":
    main()
