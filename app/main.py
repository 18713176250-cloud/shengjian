import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import database
from app.config import (
    APP_HOST,
    APP_PORT,
    AUDIO_DIR,
    FFMPEG_PATH,
    FFPROBE_PATH,
    MAX_FILE_BYTES,
    STATIC_DIR,
    VIDEO_DIR,
)
from app.media import MediaError, extract_audio, probe_media

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
extraction_lock = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global extraction_lock
    import asyncio

    extraction_lock = asyncio.Lock()
    database.init_db()
    interrupted = database.recover_interrupted_tasks()
    if interrupted:
        logger.warning("已将 %s 个中断任务标记为失败", interrupted)
    logger.info("声见服务已启动，数据库初始化完成")
    yield


app = FastAPI(title="声见", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def find_executable(configured_path: str) -> bool:
    return Path(configured_path).is_file() or shutil.which(configured_path) is not None


def get_project_or_404(project_id: str) -> dict:
    project = database.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="未找到该项目，它可能已被移除。")
    return project


def serialize_project(project: dict) -> dict:
    result = dict(project)
    audio_filename = result.get("audio_filename")
    has_audio = bool(audio_filename) and (AUDIO_DIR / audio_filename).is_file()
    result["has_audio"] = has_audio
    result["video_url"] = f"/api/projects/{result['id']}/video"
    result["audio_url"] = (
        f"/api/projects/{result['id']}/audio" if has_audio else None
    )
    result["audio_download_url"] = (
        f"/api/projects/{result['id']}/audio/download" if has_audio else None
    )
    result["latest_audio_task"] = database.get_latest_task(
        result["id"], "extract_audio"
    )
    return result


async def save_upload_limited(upload: UploadFile, destination: Path) -> int:
    size = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise MediaError("视频大小超过 100 MB 限制，请压缩后重新上传。", 413)
            output.write(chunk)
    if size == 0:
        raise MediaError("上传的文件为空，请选择有效的 MP4 视频。")
    return size


async def run_audio_extraction(task_id: str, project_id: str) -> None:
    project = database.get_project(project_id)
    if project is None:
        logger.error("后台任务找不到项目：%s", project_id)
        return
    audio_filename = f"{uuid.uuid4()}.wav"
    database.set_task_running(task_id)
    logger.info("音频任务开始运行：%s", task_id)
    try:
        await extract_audio(
            VIDEO_DIR / project["video_filename"], AUDIO_DIR / audio_filename
        )
        database.complete_audio_task(task_id, project_id, audio_filename)
        logger.info("音频任务成功：%s", task_id)
    except MediaError as error:
        logger.error("音频任务失败：%s，%s", task_id, error.message)
        database.fail_task(task_id, project_id, error.message)
    except Exception:
        logger.exception("音频任务出现未预期错误：%s", task_id)
        database.fail_task(task_id, project_id, "音频提取失败，请稍后重试。")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "ffmpeg_available": find_executable(FFMPEG_PATH),
        "ffprobe_available": find_executable(FFPROBE_PATH),
    }


@app.get("/api/projects")
def project_list() -> dict:
    return {"items": [serialize_project(project) for project in database.list_projects()]}


@app.post("/api/projects", status_code=201)
async def create_project(file: UploadFile = File(...)) -> dict:
    original_filename = (file.filename or "未命名.mp4").replace("\\", "/").split("/")[-1]
    original_filename = original_filename[:255] or "未命名.mp4"
    if Path(original_filename).suffix.lower() != ".mp4":
        raise HTTPException(status_code=400, detail="第一版仅支持 MP4 视频（.mp4）。")

    video_filename = f"{uuid.uuid4()}.mp4"
    video_path = VIDEO_DIR / video_filename
    persisted = False
    logger.info("接收上传：%s，保存为 %s", original_filename, video_filename)
    try:
        file_size = await save_upload_limited(file, video_path)
        media_info = await probe_media(video_path)
        project = database.create_project(
            original_filename=original_filename,
            video_filename=video_filename,
            duration_seconds=media_info.duration_seconds,
            width=media_info.width,
            height=media_info.height,
            file_size=file_size,
        )
        persisted = True
        logger.info("项目创建成功：%s", project["id"])
        return serialize_project(project)
    except MediaError as error:
        logger.warning("上传校验未通过：%s", error.message)
        raise HTTPException(status_code=error.status_code, detail=error.message) from None
    except Exception:
        logger.exception("创建项目失败")
        raise HTTPException(status_code=500, detail="项目创建失败，请稍后重试。") from None
    finally:
        await file.close()
        if not persisted:
            video_path.unlink(missing_ok=True)


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict:
    return serialize_project(get_project_or_404(project_id))


@app.post("/api/projects/{project_id}/extract-audio", status_code=202)
async def request_audio_extraction(project_id: str, background_tasks: BackgroundTasks) -> dict:
    project = get_project_or_404(project_id)
    if project.get("audio_filename") and (AUDIO_DIR / project["audio_filename"]).is_file():
        raise HTTPException(status_code=409, detail="音频已提取，可直接播放或下载。")
    async with extraction_lock:
        latest_task = database.get_latest_task(project_id, "extract_audio")
        if latest_task and latest_task["status"] in {"queued", "running"}:
            raise HTTPException(status_code=409, detail="音频提取任务正在进行，请稍候。")
        task = database.create_task(project_id, "extract_audio")
        database.set_project_processing(project_id)
    background_tasks.add_task(run_audio_extraction, task["id"], project_id)
    logger.info("音频任务已排队：%s", task["id"])
    return serialize_project(get_project_or_404(project_id))


@app.get("/api/projects/{project_id}/video")
def project_video(project_id: str) -> FileResponse:
    project = get_project_or_404(project_id)
    video_path = VIDEO_DIR / project["video_filename"]
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在，请重新上传。")
    return FileResponse(video_path, media_type="video/mp4")


@app.get("/api/projects/{project_id}/audio")
def project_audio(project_id: str) -> FileResponse:
    project = get_project_or_404(project_id)
    if not project.get("audio_filename"):
        raise HTTPException(status_code=404, detail="音频尚未提取，请先点击“提取音频”。")
    audio_path = AUDIO_DIR / project["audio_filename"]
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在，请重新提取。")
    return FileResponse(audio_path, media_type="audio/wav")


@app.get("/api/projects/{project_id}/audio/download")
def download_project_audio(project_id: str) -> FileResponse:
    project = get_project_or_404(project_id)
    if not project.get("audio_filename"):
        raise HTTPException(status_code=404, detail="音频尚未提取，请先点击“提取音频”。")
    audio_path = AUDIO_DIR / project["audio_filename"]
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="音频文件不存在，请重新提取。")
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"shengjian-{project_id[:8]}.wav",
    )


@app.get("/", include_in_schema=False)
def index_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/projects/{project_id}", include_in_schema=False)
def project_page(project_id: str) -> FileResponse:
    get_project_or_404(project_id)
    return FileResponse(STATIC_DIR / "project.html")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=False)
