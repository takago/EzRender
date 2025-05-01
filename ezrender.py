import os
os.environ["PYOPENGL_PLATFORM"] = "egl"  # ヘッドレスレンダリング用

import sys
import argparse
import numpy as np
import trimesh
import pyrender
from PIL import Image

# === カメラ姿勢計算 ===
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

# === モデル読み込み ===
def load_model(path):
    loaded = trimesh.load(path)
    if isinstance(loaded, trimesh.Scene):
        return loaded
    else:
        return trimesh.Scene(loaded)

# === 極座標によるカメラ位置計算 ===
def spherical_camera_position(center, distance, angle_deg):
    theta = np.radians(angle_deg)
    x = distance * np.cos(theta)
    z = distance * np.sin(theta)
    y = distance * 0.1  # 少し上から
    return center + np.array([x, y, z])

# === --cam-xyz パース関数 ===
def parse_xyz(text):
    try:
        parts = [float(x.strip()) for x in text.split(",")]
        if len(parts) != 3:
            raise ValueError("3つの値が必要です")
        return np.array(parts)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"--cam-xyz の形式エラー: {e}")

# === --size パース関数 ===
def parse_size(text):
    try:
        width, height = text.lower().split("x")
        return int(width), int(height)
    except:
        raise argparse.ArgumentTypeError("--size の形式は WIDTHxHEIGHT（例: 800x600）で指定してください")

# === メイン処理 ===
def main():
    parser = argparse.ArgumentParser(
        description="3Dモデルを任意視点からレンダリングし、WebP画像として保存または表示します。",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
【使用例】

# 1. モデル中心から距離3.0、方位角45度の位置にカメラを置き、画像を表示（保存しない）
  python render_model.py model.glb --distance 3.0 --angle 45 --view

# 2. カメラ位置をx=1, y=2, z=3で指定し、画像を保存（表示しない）
  python render_model.py model.obj --cam-xyz 1.0,2.0,3.0 --output output.webp

# 3. 上記のカメラ位置で画像を保存し、さらに表示もする
  python render_model.py model.obj --cam-xyz 1.0,2.0,3.0 --output output.webp --view

# 4. 出力サイズを1024x768に指定して保存
  python render_model.py model.obj --cam-xyz 0,1,2 --output big.webp --size 1024x768

【補足】

- --distance と --angle はセットで使用してください。
- --cam-xyz はカンマ区切りで3値 (x,y,z) を与えてください。
- --view は timg コマンドで画像を表示します（Linuxターミナル専用）。
- --output を省略するとファイル保存されません（--view だけでも可）。
- --size は出力画像サイズを指定（デフォルト: 512x512）
"""
    )

    parser.add_argument("model_file", help="3Dモデルファイル（.obj または .glb）")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--distance", type=float, help="極座標モード: モデル中心からカメラまでの距離")
    group.add_argument("--cam-xyz", type=parse_xyz, help="直指定モード: カメラ位置 x,y,z をカンマ区切りで指定")

    parser.add_argument("--angle", type=float, help="極座標モード: 方位角（度）Y軸中心に水平回転")
    parser.add_argument("--output", type=str, help="出力画像ファイル名（.webp 拡張子が自動追加されます）")
    parser.add_argument("--view", action="store_true", help="timg コマンドで画像を表示（保存は --output 指定時のみ）")
    parser.add_argument("--size", type=parse_size, default=(512, 512), help="出力画像サイズ（幅x高さ）。例: --size 1024x768（デフォルト: 512x512）")

    args = parser.parse_args()

    # === モデル読み込み ===
    if not os.path.exists(args.model_file):
        print(f"ファイルが存在しません: {args.model_file}")
        sys.exit(1)

    tri_scene = load_model(args.model_file)
    scene = pyrender.Scene.from_trimesh_scene(tri_scene, bg_color=[0.5, 0.5, 0.5, 1.0]) # 背景は灰色に
    # scene = pyrender.Scene.from_trimesh_scene(tri_scene)
    center = tri_scene.centroid

    # === カメラ位置決定 ===
    if args.distance is not None:
        if args.angle is None:
            print("--distance を使う場合は --angle も必要です")
            sys.exit(1)
        eye = spherical_camera_position(center, args.distance, args.angle)
    else:
        eye = args.cam_xyz

    # === カメラ姿勢行列 ===
    view = look_at_view_matrix(eye, center)
    camera_pose = np.linalg.inv(view)

    # === カメラとライトの追加 ===
    camera = pyrender.PerspectiveCamera(yfov=np.pi / 6.0)
    scene.add(camera, pose=camera_pose)
    light = pyrender.DirectionalLight(color=np.ones(3), intensity=2.0)
    scene.add(light, pose=camera_pose)

    # === レンダリング処理 ===
    width, height = args.size
    renderer = pyrender.OffscreenRenderer(width, height)
    color, _ = renderer.render(scene)
    renderer.delete()

    # === 画像の保存または一時保存 ===
    if args.output:
        output_path = args.output
        if not output_path.lower().endswith(".webp"):
            output_path += ".webp"
        Image.fromarray(color).save(output_path)
        print(f"画像を保存しました: {output_path}")
    else:
        output_path = "_tmp_render.webp"
        Image.fromarray(color).save(output_path)

    # === 表示処理（必要な場合） ===
    if args.view:
        os.system(f"timg {output_path}")

    # === 一時ファイルの削除（--viewのみ使用時） ===
    if args.view and not args.output:
        os.remove(output_path)

if __name__ == "__main__":
    main()

