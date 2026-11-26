import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import (
    FFPROBE_PATH,
    FFMPEG_PATH,
    MAX_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)


class MediaError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    width: int
    height: int


def parse_probe_data(payload: dict[str, Any]) -> MediaInfo:
    format_info = payload.get("format") or {}
    format_names = str(format_info.get("format_name", "")).split(",")
    if "mp4" not in format_names:
        raise MediaError("文件的真实格式不是 MP4，请转换为 MP4 后重新上传。")

    streams = payload.get("streams") or []
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    if not video_streams:
        raise MediaError("未检测到视频画面，请上传有效的 MP4 视频。")
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise MediaError("未检测到音轨，无法提取音频。请上传包含声音的视频。")

    duration_values = [format_info.get("duration")]
    duration_values.extend(stream.get("duration") for stream in streams)
    durations = []
    for value in duration_values:
        try:
            duration = float(value)
            if duration > 0:
                durations.append(duration)
        except (TypeError, ValueError):
            continue
    if not durations:
        raise MediaError("无法读取视频时长，请确认文件未损坏。")

    duration_seconds = max(durations)
    if duration_seconds > MAX_DURATION_SECONDS:
        raise MediaError("视频时长超过 3 分钟限制，请剪辑后重新上传。")

    video = video_streams[0]
    try:
        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
    except (TypeError, ValueError) as error:
        raise MediaError("无法读取视频分辨率，请确认文件未损坏。") from error
    if width <= 0 or height <= 0:
        raise MediaError("无法读取视频分辨率，请确认文件未损坏。")

    return MediaInfo(duration_seconds=duration_seconds, width=width, height=height)


async def run_process(command: list[str], timeout: int) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise MediaError("音视频处理超时，请重试。", 504) from None
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


async def probe_media(video_path: Path) -> MediaInfo:
    command = [
        FFPROBE_PATH,
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_type,width,height,duration",
        "-of",
        "json",
        str(video_path),
    ]
    logger.info("开始校验媒体文件：%s", video_path.name)
    try:
        returncode, stdout, stderr = await run_process(command, timeout=30)
    except FileNotFoundError:
        raise MediaError(
            "未检测到 FFprobe，请先安装 FFmpeg 并加入系统 PATH。", 503
        ) from None
    if returncode != 0:
        logger.warning("FFprobe 校验失败：%s", stderr)
        raise MediaError("无法读取视频，文件可能已损坏或不是有效的 MP4 视频。")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("FFprobe 返回了无法解析的数据：%s", stdout)
        raise MediaError("媒体校验服务返回了无效数据，请重试。", 500) from None
    media_info = parse_probe_data(payload)
    logger.info(
        "媒体校验通过：时长 %.2f 秒，分辨率 %sx%s",
        media_info.duration_seconds,
        media_info.width,
        media_info.height,
    )
    return media_info


async def extract_audio(video_path: Path, audio_path: Path) -> None:
    temporary_path = audio_path.with_name(f"{audio_path.stem}.partial.wav")
    command = [
        FFMPEG_PATH,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(temporary_path),
    ]
    logger.info("开始提取音频，任务输出：%s", audio_path.name)
    try:
        returncode, _, stderr = await run_process(command, timeout=300)
    except FileNotFoundError:
        raise MediaError("未检测到 FFmpeg，请先安装 FFmpeg 并加入系统 PATH。", 503) from None
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    if returncode != 0:
        temporary_path.unlink(missing_ok=True)
        logger.error("FFmpeg 提取音频失败：%s", stderr)
        raise MediaError("音频提取失败，请确认视频可正常播放后重试。", 500)
    temporary_path.replace(audio_path)
    logger.info("音频提取完成：%s", audio_path.name)
