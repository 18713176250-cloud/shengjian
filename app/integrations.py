from pathlib import Path
from typing import Any, Protocol


class ObsStorage(Protocol):
    async def upload(self, local_path: Path, object_name: str) -> str: ...


class SisService(Protocol):
    async def transcribe(self, audio_path: Path, language: str) -> dict[str, Any]: ...


class SoundEventDetector(Protocol):
    async def detect(self, audio_path: Path) -> list[dict[str, Any]]: ...
