import subprocess
import os
import sys
import glob
import argparse
import shutil

# === CUDA・Conda 環境の明示的設定 ===
CONDA_ENV_DIR = "/home/takago.ai /miniconda3/envs/era3d"
os.environ["PATH"] = os.path.join(CONDA_ENV_DIR, "bin") + ":" + os.environ.get("PATH", "")
os.environ["LD_LIBRARY_PATH"] = os.path.join(CONDA_ENV_DIR, "lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")

print("🔧 環境変数を設定しました:")
print("   PATH =", os.environ["PATH"].split(":")[0], "...")
print("   LD_LIBRARY_PATH =", os.environ["LD_LIBRARY_PATH"].split(":")[0], "...")

# === 引数解析 ===
parser = argparse.ArgumentParser(description="Era3D パイプライン全自動スクリプト")
parser.add_argument("--input", "-i", required=True, help="入力画像（PNGなど）へのパス")
parser.add_argument("--output-name", "-o", required=True, help="出力メッシュ等のベース名")
args = parser.parse_args()

# === パスと変数設定 ===
CONDA_PYTHON = os.path.join(CONDA_ENV_DIR, "bin/python")
ERA3D_DIR = os.path.expanduser("~/Era3D")
EXAMPLES_DIR = os.path.join(ERA3D_DIR, "examples")
INPUT_IMAGE_PATH = args.input
OUTPUT_NAME = args.output_name
MV_RES_DIR = os.path.join(ERA3D_DIR, "mv_res")
NSR_DIR = os.path.join(ERA3D_DIR, "instant-nsr-pl")
RECON_DIR = os.path.join(NSR_DIR, "recon")
CONFIG_UNCLIP = "configs/test_unclip-512-6view.yaml"
CONFIG_NSR = "configs/neuralangelo-ortho-wmask.yaml"

def run(cmd, cwd=None):
    print(f"[RUN] {cmd}")
    subprocess.run(cmd, shell=True, check=True, cwd=cwd)

# === examplesディレクトリを空にする ===
if os.path.exists(EXAMPLES_DIR):
    print(f"🧹 既存の {EXAMPLES_DIR} を削除します")
    shutil.rmtree(EXAMPLES_DIR)

os.makedirs(EXAMPLES_DIR, exist_ok=True)
print(f"📁 {EXAMPLES_DIR} を再作成しました（空フォルダ）")

# === 背景除去 ===
run(
    f"{CONDA_PYTHON} foreground_segment.py "
    f"--input {INPUT_IMAGE_PATH} "
    f"--output {os.path.join(EXAMPLES_DIR, OUTPUT_NAME)}.png",
    cwd=ERA3D_DIR
)

# === 多視点画像生成 ===
run(
    f"{CONDA_PYTHON} test_mvdiffusion_unclip.py "
    f"--config {CONFIG_UNCLIP} "
    f"pretrained_model_name_or_path='pengHTYX/MacLab-Era3D-512-6view' "
    f"validation_dataset.crop_size=420 "
    f"validation_dataset.root_dir={EXAMPLES_DIR} "
    f"seed=600 "
    f"save_dir='mv_res' "
    f"save_mode='rgb'",
    cwd=ERA3D_DIR
)

# === timg による画像プレビュー ===
color_pattern = os.path.join(MV_RES_DIR, OUTPUT_NAME, "color_*.png")
print(f"🖼️ timg によるプレビュー表示: {color_pattern}")
try:
    subprocess.run(f"timg --grid 6x1 {color_pattern}", shell=True, check=True)
except subprocess.CalledProcessError:
    print("⚠️ timg 実行中にエラーが発生しました（GUI環境がない可能性あり）")

# === Instant-NSR 実行 ===
run(
    f"{CONDA_PYTHON} launch.py "
    f"--config {CONFIG_NSR} "
    f"--gpu 0 "
    f"--train dataset.root_dir=../mv_res dataset.scene={OUTPUT_NAME} "
    f"--exp_dir recon",
    cwd=NSR_DIR
)

# === 最新の@xxxxディレクトリを取得 ===
output_base = os.path.join(RECON_DIR, OUTPUT_NAME)
candidates = sorted(glob.glob(f"{output_base}/@*/"), reverse=True)
if not candidates:
    print("❌ NSR出力ディレクトリが見つかりません")
    sys.exit(1)

latest_dir = os.path.join(candidates[0], "save")
print(f"✅ 最新出力ディレクトリ: {latest_dir}")

# === 修復処理（fixed.obj を latest_dir に出力）===
fixed_output_path = os.path.join(latest_dir, f"refine_{OUTPUT_NAME}_fixed.obj")
run(
    f"{CONDA_PYTHON} e3d_objfix.py {os.path.join(latest_dir, f'refine_{OUTPUT_NAME}.obj')} "
    f"-o {fixed_output_path}",
    cwd=ERA3D_DIR
)
print(f"🛠️ 修復済みモデルを保存: {fixed_output_path}")

# === シンボリックリンク更新 ===
link_path = os.path.join(ERA3D_DIR, "latest_output")
if os.path.islink(link_path) or os.path.exists(link_path):
    os.unlink(link_path)
os.symlink(latest_dir, link_path)
print(f"🔗 最新出力へのリンクを作成: {link_path} -> {latest_dir}")

