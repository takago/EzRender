#!/usr/bin/env python3
import argparse
import os
import numpy as np
import trimesh
import xatlas
import pymeshlab

def simplify_mesh(input_obj, target_faces):
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_obj)
    ms.apply_coord_laplacian_smoothing()
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target_faces)
    temp_obj = "temp_simplified.obj"
    ms.save_current_mesh(temp_obj)
    return temp_obj

def uv_unwrap_and_add_colors(obj_file):
    mesh = trimesh.load_mesh(obj_file)
    vmapping, indices, uvs = xatlas.parametrize(mesh.vertices, mesh.faces)
    vertices = mesh.vertices[vmapping]
    faces = indices

    # 頂点カラーがあるか確認
    if hasattr(mesh.visual, "vertex_colors") and mesh.visual.vertex_colors is not None:
        colors = mesh.visual.vertex_colors[vmapping][:, :3]  # RGB（RGBA → RGB）
        obj_lines = []
        for v, c in zip(vertices, colors):
            obj_lines.append("v {:.6f} {:.6f} {:.6f} {} {} {}".format(*v, *c))
    else:
        raise ValueError("頂点カラー情報が見つかりません（mesh.visual.vertex_colors が存在しない）")

    for uv in uvs:
        obj_lines.append("vt {:.6f} {:.6f}".format(*uv))
    for f in faces:
        f1, f2, f3 = f + 1  # 1-based index
        obj_lines.append(f"f {f1}/{f1} {f2}/{f2} {f3}/{f3}")

    temp_obj = "temp_uvcolor.obj"
    with open(temp_obj, "w") as f:
        f.write("\n".join(obj_lines))
    return temp_obj

def bake_texture(obj_file, texture_file, size):
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(obj_file)
    ms.compute_texmap_from_color(textname=texture_file, textw=size, texth=size, pullpush=False)
    baked_obj = "temp_baked.obj"
    ms.save_current_mesh(baked_obj)
    return baked_obj

def convert_to_glb(obj_file, output_glb):
    mesh = trimesh.load(obj_file)
    mesh.export(output_glb)

def main():
    parser = argparse.ArgumentParser(
        description="""
頂点カラー付きのOBJファイルを、以下の手順でGLB形式に変換します：

1. メッシュを指定されたフェイス数以下に簡略化（pymeshlab使用）
2. xatlasでUV展開（スマートUVアンラップ）
3. 頂点カラー情報を頂点ごとにOBJへ追加
4. pymeshlabでテクスチャ画像へとベイク
5. 最終的にGLB形式でエクスポート（trimesh使用）

テクスチャ画像（PNG）はGLBに埋め込まれます。
""",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "input_obj",
        help="入力OBJファイル（頂点カラー付きが必須。例: color_model.obj）"
    )

    parser.add_argument(
        "output_glb",
        help="出力GLBファイル名（例: output.glb）"
    )

    parser.add_argument(
        "--face-limit", type=int, default=200000,
        help="簡略化後の最大フェイス数（デフォルト: 200000）"
    )

    parser.add_argument(
        "--keep-temp", action="store_true",
        help="一時ファイル（中間OBJ/PNGファイル）を削除せず保存する"
    )

    parser.add_argument(
        "--texture", default="baked_texture.png",
        help="生成されるテクスチャ画像ファイル名（デフォルト: baked_texture.png）"
    )

    parser.add_argument(
        "--tex-size", type=int, default=2048,
        help="生成されるテクスチャ画像の幅・高さ（ピクセル単位、デフォルト: 2048）"
    )

    args = parser.parse_args()

    print("[1] メッシュ簡略化中...")
    simplified_obj = simplify_mesh(args.input_obj, args.face_limit)

    print("[2] UV展開 + 頂点カラー転送中...")
    uvcolor_obj = uv_unwrap_and_add_colors(simplified_obj)

    print("[3] テクスチャベイク中...")
    baked_obj = bake_texture(uvcolor_obj, args.texture, args.tex_size)

    print("[4] GLBに変換中...")
    convert_to_glb(baked_obj, args.output_glb)

    if not args.keep_temp:
        for f in [simplified_obj, uvcolor_obj, baked_obj]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(args.texture):
            os.remove(args.texture)

    print("✅ 完了:", args.output_glb)

if __name__ == "__main__":
    main()

