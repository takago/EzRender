#!/usr/bin/env python3
"""
srgb2linobj.py

OBJファイル中の頂点カラー（sRGB）をLinear RGBに変換するツール。
主に `v x y z r g b` 形式の頂点行を処理します。

（EzRenderではこの処理を内蔵しています）
"""

import argparse
import numpy as np
import os
import sys

def srgb_to_linear(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(
        c <= 0.04045,
        c / 12.92,
        ((c + 0.055) / 1.055) ** 2.4
    )

def process_obj(input_path, output_path):
    converted_count = 0
    with open(input_path, 'r') as fin, open(output_path, 'w') as fout:
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
                        converted_count += 1
                    except:
                        fout.write(line)
                else:
                    fout.write(line)
            else:
                fout.write(line)
    return converted_count

def main():
    parser = argparse.ArgumentParser(
        description="OBJファイルの頂点カラー（sRGB）をLinear RGBに変換します。",
        epilog="使用例: python objconv_srgb2linear.py 入力.obj 出力.obj"
    )
    parser.add_argument("input", help="入力ファイル（sRGB頂点カラーを含む.obj）")
    parser.add_argument("output", help="出力ファイル（Linear RGBに変換された.obj）")

    args = parser.parse_args()

    if not args.input.lower().endswith('.obj') or not args.output.lower().endswith('.obj'):
        print("❌ エラー: 入力・出力ファイルはともに .obj である必要があります。")
        sys.exit(1)

    if not os.path.exists(args.input):
        print("❌ エラー: 入力ファイルが見つかりません:", args.input)
        sys.exit(1)

    print(f"📂 変換中: {args.input} → {args.output}")
    count = process_obj(args.input, args.output)
    print(f"✅ 変換完了: {count} 行の頂点カラーを sRGB → Linear RGB に変換しました。")

if __name__ == "__main__":
    main()

