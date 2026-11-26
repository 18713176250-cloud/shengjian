import os
import tempfile
import unittest
import uuid
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

TEST_DIRECTORY = tempfile.TemporaryDirectory()
TEST_ROOT = Path(TEST_DIRECTORY.name)
os.environ["APP_DATA_DIR"] = str(TEST_ROOT / "storage")
os.environ["APP_DATABASE_PATH"] = str(TEST_ROOT / "storage" / "test.db")

from fastapi.testclient import TestClient

from app import database, main
from app.config import AUDIO_DIR, VIDEO_DIR
from app.media import MediaError, MediaInfo, parse_probe_data


def valid_probe_data():
    return {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.5"},
        "streams": [
            {"codec_type": "video", "width": 1280, "height": 720},
            {"codec_type": "audio"},
        ],
    }


class MediaParsingTests(unittest.TestCase):
    def test_valid_mp4(self):
        info = parse_probe_data(valid_probe_data())
        self.assertEqual(info, MediaInfo(12.5, 1280, 720))

    def test_rejects_non_mp4(self):
        payload = valid_probe_data()
        payload["format"]["format_name"] = "matroska,webm"
        with self.assertRaisesRegex(MediaError, "真实格式不是 MP4"):
            parse_probe_data(payload)

    def test_rejects_missing_audio(self):
        payload = valid_probe_data()
        payload["streams"] = [payload["streams"][0]]
        with self.assertRaisesRegex(MediaError, "未检测到音轨"):
            parse_probe_data(payload)

    def test_rejects_over_duration(self):
        payload = valid_probe_data()
        payload["format"]["duration"] = "180.01"
        with self.assertRaisesRegex(MediaError, "超过 3 分钟"):
            parse_probe_data(payload)


class ApiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        TEST_DIRECTORY.cleanup()

    def setUp(self):
        with database.connect() as connection:
            connection.execute("DELETE FROM tasks")
            connection.execute("DELETE FROM projects")
        for directory in (VIDEO_DIR, AUDIO_DIR):
            for path in directory.iterdir():
                if path.is_file():
                    path.unlink()

    @patch("app.main.probe_media", new_callable=AsyncMock)
    def test_upload_extract_play_download_and_persist(self, probe_mock):
        probe_mock.return_value = MediaInfo(12.5, 1280, 720)
        response = self.client.post(
            "/api/projects",
            files={"file": ("我的示例.mp4", b"fake-mp4-content", "video/mp4")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        project = response.json()
        self.assertEqual(project["original_filename"], "我的示例.mp4")
        self.assertNotIn("我的示例", project["video_filename"])
        self.assertEqual(project["status"], "ready")
        self.assertTrue((VIDEO_DIR / project["video_filename"]).is_file())

        async def write_test_audio(_, audio_path):
            with wave.open(str(audio_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b"\x00\x00" * 160)

        with patch("app.main.extract_audio", new_callable=AsyncMock) as extract_mock:
            extract_mock.side_effect = write_test_audio
            extraction = self.client.post(f"/api/projects/{project['id']}/extract-audio")
            self.assertEqual(extraction.status_code, 202, extraction.text)

        detail = self.client.get(f"/api/projects/{project['id']}").json()
        self.assertEqual(detail["status"], "audio_ready")
        self.assertEqual(detail["latest_audio_task"]["status"], "succeeded")
        self.assertTrue(detail["has_audio"])
        audio_path = AUDIO_DIR / detail["audio_filename"]
        with wave.open(str(audio_path), "rb") as audio_file:
            self.assertEqual(audio_file.getnchannels(), 1)
            self.assertEqual(audio_file.getsampwidth(), 2)
            self.assertEqual(audio_file.getframerate(), 16000)

        audio_response = self.client.get(detail["audio_url"])
        self.assertEqual(audio_response.status_code, 200)
        self.assertEqual(audio_response.headers["content-type"], "audio/wav")
        download_response = self.client.get(detail["audio_download_url"])
        self.assertEqual(download_response.status_code, 200)
        self.assertIn("attachment", download_response.headers["content-disposition"])

        with TestClient(main.app) as restarted_client:
            history = restarted_client.get("/api/projects")
            self.assertEqual(history.status_code, 200)
            self.assertEqual(len(history.json()["items"]), 1)
            self.assertEqual(history.json()["items"][0]["id"], project["id"])

    def test_rejects_wrong_extension(self):
        response = self.client.post(
            "/api/projects",
            files={"file": ("example.avi", b"not-a-video", "video/avi")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("仅支持 MP4", response.json()["detail"])
        self.assertEqual(list(VIDEO_DIR.iterdir()), [])

    @patch("app.main.probe_media", new_callable=AsyncMock)
    def test_failed_upload_does_not_leave_file(self, probe_mock):
        probe_mock.side_effect = MediaError("未检测到音轨，无法提取音频。请上传包含声音的视频。")
        response = self.client.post(
            "/api/projects",
            files={"file": ("silent.mp4", b"fake-mp4-content", "video/mp4")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("未检测到音轨", response.json()["detail"])
        self.assertEqual(list(VIDEO_DIR.iterdir()), [])
        self.assertEqual(database.list_projects(), [])

    @patch("app.main.probe_media", new_callable=AsyncMock)
    def test_rejects_over_size_and_cleans_file(self, probe_mock):
        with patch("app.main.MAX_FILE_BYTES", 4):
            response = self.client.post(
                "/api/projects",
                files={"file": ("large.mp4", b"too-large", "video/mp4")},
            )
        self.assertEqual(response.status_code, 413)
        self.assertIn("超过 100 MB", response.json()["detail"])
        probe_mock.assert_not_awaited()
        self.assertEqual(list(VIDEO_DIR.iterdir()), [])

    @patch("app.main.probe_media", new_callable=AsyncMock)
    def test_extraction_failure_is_visible_and_retryable(self, probe_mock):
        probe_mock.return_value = MediaInfo(12.5, 1280, 720)
        project = self.client.post(
            "/api/projects",
            files={"file": ("demo.mp4", b"fake-mp4-content", "video/mp4")},
        ).json()
        with patch("app.main.extract_audio", new_callable=AsyncMock) as extract_mock:
            extract_mock.side_effect = MediaError("未检测到 FFmpeg，请先安装 FFmpeg 并加入系统 PATH。", 503)
            response = self.client.post(f"/api/projects/{project['id']}/extract-audio")
            self.assertEqual(response.status_code, 202)
        detail = self.client.get(f"/api/projects/{project['id']}").json()
        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["latest_audio_task"]["status"], "failed")
        self.assertIn("未检测到 FFmpeg", detail["error_message"])

    def test_restart_marks_unfinished_task_as_failed(self):
        project = database.create_project("demo.mp4", f"{uuid.uuid4()}.mp4", 10, 640, 360, 100)
        task = database.create_task(project["id"], "extract_audio")
        database.set_project_processing(project["id"])
        database.set_task_running(task["id"])
        with TestClient(main.app):
            detail = self.client.get(f"/api/projects/{project['id']}").json()
            self.assertEqual(detail["status"], "failed")
            self.assertEqual(detail["latest_audio_task"]["status"], "failed")
            self.assertIn("服务重启", detail["error_message"])

    def test_unknown_project_has_chinese_404(self):
        response = self.client.get(f"/api/projects/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertIn("未找到该项目", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
