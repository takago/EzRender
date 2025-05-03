#!/usr/bin/env python3
# ===============================================
# vc2tex.py - 頂点カラー付きOBJ → テクスチャ付きOBJ変換ツール
#
# 📦 導入方法:
#     pip install pymeshlab tabulate
#
# 🛠️ 使用例:
#     python vc2tex.py -i input.obj -o output.obj
#     python vc2tex.py -i input.obj -o output.zip --save-temp
#
# ===============================================

import pymeshlab
import argparse
import os
import sys
import zipfile
import shutil
from tabulate import tabulate

def format_size(bytesize):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytesize < 1024.0:
            return f"{bytesize:.1f} {unit}"
        bytesize /= 1024.0
    return f"{bytesize:.1f} TB"

def safe_getsize(path):
    return os.path.getsize(path) if os.path.exists(path) else 0

def main():
    parser = argparse.ArgumentParser(
        description="頂点カラー付きOBJをUV展開・テクスチャ化して出力（OBJ/ZIP対応）",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument('--input', '-i', required=True, help='入力ファイル（.obj）')
    parser.add_argument('--output', '-o', required=True, help='出力ファイル（.obj または .zip）')
    parser.add_argument('--texture-size', '-t', type=int, default=2048, help='テクスチャ解像度（既定: 2048）')
    parser.add_argument('--decimate', '-d', type=float, default=0.5, help='ポリゴン削減率（既定: 0.5）')
    parser.add_argument('--save-temp', action='store_true', help='ZIP出力時に中間ファイルを残す')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"エラー: 入力ファイル {args.input} が見つかりません。", file=sys.stderr)
        sys.exit(1)

    base_name = os.path.splitext(os.path.basename(args.output))[0]
    output_dir = os.path.dirname(os.path.abspath(args.output)) or "."

    temp_obj = os.path.join(output_dir, base_name + ".obj")
    temp_png = os.path.join(output_dir, base_name + ".png")
    temp_mtl = os.path.join(output_dir, base_name + ".mtl")
    png_name_only = base_name + ".png"

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(args.input)

    print("▶️ 変換前:")
    m = ms.current_mesh()
    print(f"  頂点数: {m.vertex_number()}")
    print(f"  面数  : {m.face_number()}")

    ms.meshing_decimation_clustering(threshold=pymeshlab.PercentageValue(args.decimate))

    print("✅ 簡略化後:")
    print(f"  頂点数: {m.vertex_number()}")
    print(f"  面数  : {m.face_number()}")

    ms.compute_texcoord_parametrization_triangle_trivial_per_wedge(
        textdim=args.texture_size, method=1
    )

    ms.transfer_attributes_to_texture_per_vertex(
        textw=args.texture_size, texth=args.texture_size, textname=png_name_only
    )

    if not os.path.samefile(os.getcwd(), output_dir):
        shutil.move(png_name_only, temp_png)

    ms.save_current_mesh(temp_obj)

    # MTL異常名対応
    mtl_found = False
    for candidate in [temp_mtl, temp_obj + ".mtl"]:
        if os.path.exists(candidate):
            if candidate.endswith(".obj.mtl"):
                os.rename(candidate, temp_mtl)
                print(f"📄 MTLファイルをリネーム: {candidate} → {temp_mtl}")
                with open(temp_obj, 'r') as f:
                    lines = f.readlines()
                with open(temp_obj, 'w') as f:
                    for line in lines:
                        if line.strip().startswith("mtllib ") and ".obj.mtl" in line:
                            line = line.replace(".obj.mtl", ".mtl")
                        f.write(line)
            mtl_found = True
            break
    if not mtl_found:
        print("⚠️ MTLファイルが見つかりませんでした。")

    # ZIP or 単体出力
    if args.output.endswith('.zip'):
        zip_path = args.output
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_obj, os.path.basename(temp_obj))
            zipf.write(temp_png, os.path.basename(temp_png))
            if os.path.exists(temp_mtl):
                zipf.write(temp_mtl, os.path.basename(temp_mtl))
        print(f"\n📦 ZIPアーカイブ保存: {zip_path}")

        if not args.save_temp:
            for f in [temp_obj, temp_png, temp_mtl]:
                if os.path.exists(f):
                    os.remove(f)
            print("🧹 一時ファイルを削除しました（--save-temp 未指定）")
    else:
        print(f"\n💾 OBJ保存: {temp_obj}")
        print(f"🖼️ テクスチャ画像保存: {temp_png}")
        print(f"📄 MTL保存: {temp_mtl if os.path.exists(temp_mtl) else 'なし'}")

    # サイズ取得
    input_size = os.path.getsize(args.input)
    obj_size = safe_getsize(temp_obj)
    png_size = safe_getsize(temp_png)
    mtl_size = safe_getsize(temp_mtl)
    zip_size = safe_getsize(args.output) if args.output.endswith('.zip') else 0

    # 表構築（INPUT/OUTPUT区切り＋ZIP前にも区切り線）
    table = []
    table.append(["INPUT", "OBJ", format_size(input_size)])
    table.append(["--------", "--------", "----------"])
    table.append(["OUTPUT", "OBJ", format_size(obj_size)])
    table.append(["OUTPUT", "PNG", format_size(png_size)])
    if mtl_size:
        table.append(["OUTPUT", "MTL", format_size(mtl_size)])
    table.append(["--------", "--------", "----------"])
    if zip_size:
        table.append(["OUTPUT", "ZIP", format_size(zip_size)])

    print("\n📊 ファイルサイズ:")
    print(tabulate(table, headers=["区分", "種類", "サイズ"], tablefmt="github", colalign=("left", "left", "right")))

    print("🔧 処理完了。")

if __name__ == '__main__':
    main()

