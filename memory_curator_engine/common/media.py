"""Shared media models and helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PHOTO_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v"}
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

INVENTORY_CSV_COLUMNS = [
    "filename",
    "relative_path",
    "file_type",
    "size_bytes",
    "capture_date",
    "capture_date_source",
    "created_date",
    "modified_date",
    "width",
    "height",
    "duration_seconds",
    "metadata_notes",
]


@dataclass
class MediaMetadata:
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    capture_date: str = ""
    capture_date_source: str = ""
    notes: str = ""


@dataclass
class MediaRecord:
    path: Path
    project_root: Path
    file_type: str
    size_bytes: int
    capture_date: str
    capture_date_source: str
    created_date: str
    modified_date: str
    metadata: MediaMetadata

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.project_root).as_posix()


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PHOTO_EXTENSIONS:
        return f"photo/{ext.lstrip('.')}"
    if ext in VIDEO_EXTENSIONS:
        return f"video/{ext.lstrip('.')}"
    return f"other/{ext.lstrip('.') or 'no_extension'}"


def format_timestamp(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")


def file_created_time(stat_result: os.stat_result) -> float | None:
    return getattr(stat_result, "st_birthtime", None)
