import time
import requests
import os
import subprocess
from PIL import Image
from flask import send_from_directory

# Flask アプリのルート側でこれを import して使う
TMP_DIR = "/tmp/cat_videos"
os.makedirs(TMP_DIR, exist_ok=True)

BASE_URL = "https://line-bot-1-rsyx.onrender.com"

def get_cat_video_url(max_seconds=15):
    timestamp = int(time.time())
    gif_path = os.path.join(TMP_DIR, f"cat_{timestamp}.gif")
    mp4_path = os.path.join(TMP_DIR, f"cat_{timestamp}.mp4")
    preview_path = os.path.join(TMP_DIR, f"preview_{timestamp}.png")

    # --- 1. GIF ダウンロード ---
    gif_url = f"https://cataas.com/cat/gif?{timestamp}"
    r = requests.get(gif_url, timeout=10)
    r.raise_for_status()
    with open(gif_path, "wb") as f:
        f.write(r.content)

    # --- 2. プレビュー画像生成 ---
    im = Image.open(gif_path)
    im.seek(0)
    im.save(preview_path)

    # --- 3. GIF → MP4 変換 ---
    subprocess.run([
        "ffmpeg", "-y",
        "-stream_loop", "2",
        "-i", gif_path,
        "-vf", "scale='min(480,iw)':-2,pad=480:480:(480-iw)/2:(480-ih)/2",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        mp4_path
    ], check=True)

    # --- 4. Flask 経由で配信できるURLを返す ---
    mp4_filename = os.path.basename(mp4_path)
    preview_filename = os.path.basename(preview_path)

    mp4_url = f"{BASE_URL}/tmp/{mp4_filename}"
    preview_url = f"{BASE_URL}/tmp/{preview_filename}"
    return mp4_url, preview_url
