import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.config import DATABASE_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                video_filename TEXT NOT NULL UNIQUE,
                audio_filename TEXT UNIQUE,
                duration_seconds REAL NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                file_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_project_created
            ON tasks(project_id, created_at DESC);
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_project(
    original_filename: str,
    video_filename: str,
    duration_seconds: float,
    width: int,
    height: int,
    file_size: int,
) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (
                id, original_filename, video_filename, duration_seconds,
                width, height, file_size, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (
                project_id,
                original_filename,
                video_filename,
                duration_seconds,
                width,
                height,
                file_size,
                timestamp,
                timestamp,
            ),
        )
    return get_project(project_id)


def get_project(project_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return row_to_dict(row)


def list_projects() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def create_task(project_id: str, task_type: str) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO tasks (id, project_id, task_type, status, created_at)
            VALUES (?, ?, ?, 'queued', ?)
            """,
            (task_id, project_id, task_type, utc_now()),
        )
    return get_task(task_id)


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_dict(row)


def get_latest_task(project_id: str, task_type: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM tasks
            WHERE project_id = ? AND task_type = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id, task_type),
        ).fetchone()
    return row_to_dict(row)


def set_project_processing(project_id: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE projects
            SET status = 'extracting', error_message = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), project_id),
        )


def set_task_running(task_id: str) -> None:
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'running', started_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (timestamp, task_id),
        )


def complete_audio_task(task_id: str, project_id: str, audio_filename: str) -> None:
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'succeeded', finished_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (timestamp, task_id),
        )
        connection.execute(
            """
            UPDATE projects
            SET status = 'audio_ready', audio_filename = ?, error_message = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (audio_filename, timestamp, project_id),
        )


def fail_task(task_id: str, project_id: str, message: str) -> None:
    timestamp = utc_now()
    with connect() as connection:
        connection.execute(
            """
            UPDATE tasks
            SET status = 'failed', error_message = ?, finished_at = ?
            WHERE id = ?
            """,
            (message, timestamp, task_id),
        )
        connection.execute(
            """
            UPDATE projects
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (message, timestamp, project_id),
        )


def recover_interrupted_tasks() -> int:
    timestamp = utc_now()
    message = "服务重启导致提取任务中断，请重新提取音频。"
    with connect() as connection:
        interrupted = connection.execute(
            "SELECT id, project_id FROM tasks WHERE status IN ('queued', 'running')"
        ).fetchall()
        for task in interrupted:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'failed', error_message = ?, finished_at = ?
                WHERE id = ?
                """,
                (message, timestamp, task["id"]),
            )
            connection.execute(
                """
                UPDATE projects
                SET status = 'failed', error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (message, timestamp, task["project_id"]),
            )
    return len(interrupted)
