#!/usr/bin/env python3
'''
はじめに
(1) https://github.com/pengHTYX/Era3D のConda環境は自分で構築してください．
(2) 本スクリプトでは背景除去に
 https://github.com/liuyuan-pal/SyncDreamer の foreground_segment.py  
 を利用していますが，そのファイルが無い場合はEra3Dの環境構築時に導入される rembg を使います．
(3) 3Dモデルの生成が完了すると，Era3Dのトップディレクトリ下に，latest-output というリンクができます．
'''

import subprocess
import os
import sys
import glob
import argparse
import shutil
import time

# ==============================
# ユーザ環境設定（必要に応じて変更）
# ==============================
HOME_DIR = os.path.expanduser("~")
CONDA_ENV_DIR = os.path.join(HOME_DIR, "miniconda3/envs/era3d")
ERA3D_DIR = os.path.join(HOME_DIR, "Era3D")
# ==============================

# CUDA/Conda環境のパス設定
os.environ["PATH"] = os.path.join(CONDA_ENV_DIR, "bin") + ":" + os.environ.get("PATH", "")
os.environ["LD_LIBRARY_PATH"] = os.path.join(CONDA_ENV_DIR, "lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")

print("🔧 環境変数を設定しました:")
print("   PATH =", os.environ["PATH"].split(":")[0], "...")
print("   LD_LIBRARY_PATH =", os.environ["LD_LIBRARY_PATH"].split(":")[0], "...")

# 引数解析
parser = argparse.ArgumentParser(description="Era3D パイプライン全自動スクリプト")
parser.add_argument("--input", "-i", required=True, help="入力画像（PNGなど）へのパス")
parser.add_argument("--output-name", "-o", required=True, help="出力メッシュ等のベース名")
args = parser.parse_args()

# パスと変数設定
CONDA_PYTHON = os.path.join(CONDA_ENV_DIR, "bin/python")
EXAMPLES_DIR = os.path.join(ERA3D_DIR, "examples")
INPUT_IMAGE_PATH = args.input
OUTPUT_NAME = args.output_name
MV_RES_DIR = os.path.join(ERA3D_DIR, "mv_res")
NSR_DIR = os.path.join(ERA3D_DIR, "instant-nsr-pl")
RECON_DIR = os.path.join(NSR_DIR, "recon")
CONFIG_UNCLIP = "configs/test_unclip-512-6view.yaml"
CONFIG_NSR = "configs/neuralangelo-ortho-wmask.yaml"

def run(cmd, cwd=None, label=None):
    if label:
        print(f"\n🟢 [{label}] 開始")
    print(f"[RUN] {cmd}")
    start = time.perf_counter()
    subprocess.run(cmd, shell=True, check=True, cwd=cwd)
    end = time.perf_counter()
    if label:
        print(f"✅ [{label}] 完了（{end - start:.2f} 秒）")

# examplesディレクトリの初期化
if os.path.exists(EXAMPLES_DIR):
    print(f"\n🧹 既存の {EXAMPLES_DIR} を削除します")
    shutil.rmtree(EXAMPLES_DIR)
os.makedirs(EXAMPLES_DIR, exist_ok=True)
print(f"📁 {EXAMPLES_DIR} を再作成しました")

# 背景除去
foreground_script = os.path.join(ERA3D_DIR, "foreground_segment.py")
output_foreground_path = os.path.join(EXAMPLES_DIR, f"{OUTPUT_NAME}.png")

if os.path.exists(foreground_script):
    run(
        f"{CONDA_PYTHON} {foreground_script} --input {INPUT_IMAGE_PATH} --output {output_foreground_path}",
        cwd=ERA3D_DIR,
        label="背景除去 (foreground_segment.py)"
    )
else:
    print("\n⚠️ foreground_segment.py が見つかりません。rembg による背景除去を試みます。")
    try:
        run(f"rembg i {INPUT_IMAGE_PATH} {output_foreground_path}", label="背景除去 (rembg)")
    except subprocess.CalledProcessError:
        print("❌ rembg の実行に失敗しました。背景除去を中断します。")
        sys.exit(1)

# 多視点画像生成
run(
    f"{CONDA_PYTHON} test_mvdiffusion_unclip.py "
    f"--config {CONFIG_UNCLIP} "
    f"pretrained_model_name_or_path='pengHTYX/MacLab-Era3D-512-6view' "
    f"validation_dataset.crop_size=420 "
    f"validation_dataset.root_dir={EXAMPLES_DIR} "
    f"seed=600 save_dir='mv_res' save_mode='rgb'",
    cwd=ERA3D_DIR,
    label="多視点画像生成"
)

# timg プレビュー
color_pattern = os.path.join(MV_RES_DIR, OUTPUT_NAME, "color_*.png")
print(f"\n🖼️ timg によるプレビュー表示: {color_pattern}")
try:
    run(f"timg --grid 6x1 {color_pattern}", label="多視点画像プレビュー")
except subprocess.CalledProcessError:
    print("⚠️ timg 実行中にエラーが発生しました（GUI環境がない可能性あり）")

# Instant-NSR 実行
run(
    f"{CONDA_PYTHON} launch.py "
    f"--config {CONFIG_NSR} "
    f"--gpu 0 "
    f"--train dataset.root_dir=../mv_res dataset.scene={OUTPUT_NAME} "
    f"--exp_dir recon",
    cwd=NSR_DIR,
    label="Instant-NSR 実行"
)

# 最新の @ ディレクトリを取得
output_base = os.path.join(RECON_DIR, OUTPUT_NAME)
candidates = sorted(glob.glob(f"{output_base}/@*/"), reverse=True)
if not candidates:
    print("❌ NSR出力ディレクトリが見つかりません")
    sys.exit(1)

latest_dir = os.path.join(candidates[0], "save")
print(f"\n✅ 最新出力ディレクトリ: {latest_dir}")

# e3d_objfix.py の存在チェックとダウンロード
objfix_script = os.path.join(ERA3D_DIR, "e3d_objfix.py")
if not os.path.exists(objfix_script):
    print(f"\n🌐 e3d_objfix.py が見つかりません。GitHubからダウンロードを試みます...")
    try:
        run(
            f"wget -O {objfix_script} https://raw.githubusercontent.com/takago/EzRender/refs/heads/main/utils/e3d_objfix.py",
            label="e3d_objfix.py ダウンロード"
        )
    except subprocess.CalledProcessError:
        print("❌ e3d_objfix.py のダウンロードに失敗しました。修復処理をスキップします。")
        sys.exit(1)

# 修復処理
fixed_output_path = os.path.join(latest_dir, f"refine_{OUTPUT_NAME}_fixed.obj")
run(
    f"{CONDA_PYTHON} {objfix_script} {os.path.join(latest_dir, f'refine_{OUTPUT_NAME}.obj')} "
    f"-o {fixed_output_path}",
    cwd=ERA3D_DIR,
    label="修復処理"
)
print(f"🛠️ 修復済みモデルを保存: {fixed_output_path}")

# シンボリックリンク更新
link_path = os.path.join(ERA3D_DIR, "latest_output")
if os.path.islink(link_path) or os.path.exists(link_path):
    os.unlink(link_path)
os.symlink(latest_dir, link_path)
print(f"🔗 最新出力へのリンクを作成: {link_path} -> {latest_dir}")
