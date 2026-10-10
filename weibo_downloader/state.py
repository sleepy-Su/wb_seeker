from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import StateError

STATE_FILENAME = ".weibo_photo_state.json"
FAILED_FILENAME = ".weibo_photo_failed.jsonl"
STATE_VERSION = 1


@dataclass(slots=True)
class DownloadState:
    path: Path
    completed: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, output_dir: Path) -> "DownloadState":
        output_dir.mkdir(parents=True, exist_ok=True)
        state_path = output_dir / STATE_FILENAME
        if not state_path.exists():
            return cls(path=state_path)

        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"Unable to read download state {state_path}: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
            raise StateError(
                f"Unsupported download state format in {state_path}; expected version {STATE_VERSION}"
            )
        completed = payload.get("completed")
        if not isinstance(completed, dict):
            raise StateError(f"Invalid completed records in {state_path}")
        return cls(path=state_path, completed=completed)

    def get(self, key: str) -> dict[str, Any] | None:
        record = self.completed.get(key)
        return record if isinstance(record, dict) else None

    def mark_completed(self, key: str, record: dict[str, Any]) -> None:
        payload = dict(record)
        payload.setdefault("completed_at", datetime.now().astimezone().isoformat(timespec="seconds"))
        self.completed[key] = payload
        self.save()

    def remove(self, key: str) -> None:
        if key in self.completed:
            del self.completed[key]
            self.save()

    def save(self) -> None:
        payload = {"version": STATE_VERSION, "completed": self.completed}
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise StateError(f"Unable to save download state {self.path}: {exc}") from exc


def append_failure(output_dir: Path, record: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    failure_path = output_dir / FAILED_FILENAME
    payload = dict(record)
    payload.setdefault("failed_at", datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        with failure_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # A failure while writing the failure log must not hide the original download error.
        return
