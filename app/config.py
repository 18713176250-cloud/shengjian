import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def get_path(env_name: str, default: str) -> Path:
    value = Path(os.getenv(env_name, default))
    return value if value.is_absolute() else BASE_DIR / value


DATA_DIR = get_path("APP_DATA_DIR", "storage")
VIDEO_DIR = DATA_DIR / "videos"
AUDIO_DIR = DATA_DIR / "audio"
DATABASE_PATH = get_path("APP_DATABASE_PATH", "storage/shengjian.db")
STATIC_DIR = BASE_DIR / "static"

MAX_FILE_BYTES = int(os.getenv("APP_MAX_FILE_BYTES", str(100 * 1024 * 1024)))
MAX_DURATION_SECONDS = float(os.getenv("APP_MAX_DURATION_SECONDS", "180"))
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE_PATH = os.getenv("FFPROBE_PATH", "ffprobe")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

for directory in (DATA_DIR, VIDEO_DIR, AUDIO_DIR, DATABASE_PATH.parent):
    directory.mkdir(parents=True, exist_ok=True)
