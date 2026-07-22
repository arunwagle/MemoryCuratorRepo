"""Read basic dimensions and duration from common photo/video containers."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO, Iterable

from memory_curator_engine.common.media import MediaMetadata, VIDEO_EXTENSIONS


@dataclass
class Box:
    box_type: str
    start: int
    header_size: int
    size: int

    @property
    def payload_start(self) -> int:
        return self.start + self.header_size

    @property
    def end(self) -> int:
        return self.start + self.size


def parse_jpeg_dimensions(path: Path) -> MediaMetadata:
    metadata = MediaMetadata()
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return MediaMetadata(notes="JPEG signature not found")

        while True:
            marker_prefix = handle.read(1)
            if not marker_prefix:
                return MediaMetadata(notes="JPEG dimensions not found")
            if marker_prefix != b"\xff":
                continue

            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)

            if not marker or marker in {b"\xd9", b"\xda"}:
                return MediaMetadata(notes="JPEG dimensions not found")

            segment_length_bytes = handle.read(2)
            if len(segment_length_bytes) != 2:
                return MediaMetadata(notes="Incomplete JPEG segment")
            segment_length = struct.unpack(">H", segment_length_bytes)[0]
            if segment_length < 2:
                return MediaMetadata(notes="Invalid JPEG segment length")

            marker_value = marker[0]
            segment_data = handle.read(segment_length - 2)
            if marker_value == 0xE1 and not metadata.capture_date:
                capture_date = parse_exif_capture_date(segment_data)
                if capture_date:
                    metadata.capture_date = capture_date
                    metadata.capture_date_source = "exif"
            if marker_value in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                data = segment_data[:5]
                if len(data) != 5:
                    return MediaMetadata(notes="Incomplete JPEG size segment")
                height, width = struct.unpack(">HH", data[1:5])
                metadata.width = width
                metadata.height = height
                return metadata


def parse_exif_capture_date(segment_data: bytes) -> str:
    if not segment_data.startswith(b"Exif\x00\x00"):
        return ""
    tiff = segment_data[6:]
    if len(tiff) < 8:
        return ""
    endian_marker = tiff[:2]
    if endian_marker == b"II":
        endian = "<"
    elif endian_marker == b"MM":
        endian = ">"
    else:
        return ""
    try:
        if struct.unpack(f"{endian}H", tiff[2:4])[0] != 42:
            return ""
        first_ifd_offset = struct.unpack(f"{endian}I", tiff[4:8])[0]
        exif_ifd_offset = read_ifd_tag_value(tiff, first_ifd_offset, 0x8769, endian)
        candidates = []
        if exif_ifd_offset:
            candidates.extend(
                [
                    read_ascii_tag(tiff, int(exif_ifd_offset), 0x9003, endian),  # DateTimeOriginal
                    read_ascii_tag(tiff, int(exif_ifd_offset), 0x9004, endian),  # DateTimeDigitized
                ]
            )
        candidates.append(read_ascii_tag(tiff, first_ifd_offset, 0x0132, endian))  # DateTime
        for value in candidates:
            parsed = normalize_exif_datetime(value)
            if parsed:
                return parsed
    except (struct.error, ValueError, IndexError):
        return ""
    return ""


def read_ifd_tag_value(tiff: bytes, ifd_offset: int, tag_id: int, endian: str) -> int | None:
    if ifd_offset <= 0 or ifd_offset + 2 > len(tiff):
        return None
    entry_count = struct.unpack(f"{endian}H", tiff[ifd_offset : ifd_offset + 2])[0]
    cursor = ifd_offset + 2
    for _ in range(entry_count):
        entry = tiff[cursor : cursor + 12]
        if len(entry) != 12:
            return None
        tag, field_type, count, value_or_offset = struct.unpack(f"{endian}HHII", entry)
        if tag == tag_id:
            return value_or_offset
        cursor += 12
    return None


def read_ascii_tag(tiff: bytes, ifd_offset: int, tag_id: int, endian: str) -> str:
    if ifd_offset <= 0 or ifd_offset + 2 > len(tiff):
        return ""
    entry_count = struct.unpack(f"{endian}H", tiff[ifd_offset : ifd_offset + 2])[0]
    cursor = ifd_offset + 2
    for _ in range(entry_count):
        entry = tiff[cursor : cursor + 12]
        if len(entry) != 12:
            return ""
        tag, field_type, count, value_or_offset = struct.unpack(f"{endian}HHII", entry)
        if tag == tag_id and field_type == 2 and count > 0:
            if count <= 4:
                raw = entry[8 : 8 + count]
            else:
                raw = tiff[value_or_offset : value_or_offset + count]
            return raw.split(b"\x00", 1)[0].decode("latin-1", errors="ignore").strip()
        cursor += 12
    return ""


def normalize_exif_datetime(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned[:19], fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


def parse_png_dimensions(path: Path) -> MediaMetadata:
    with path.open("rb") as handle:
        signature = handle.read(24)
    if len(signature) < 24 or not signature.startswith(b"\x89PNG\r\n\x1a\n"):
        return MediaMetadata(notes="PNG signature not found")
    if signature[12:16] != b"IHDR":
        return MediaMetadata(notes="PNG IHDR chunk not found")
    width, height = struct.unpack(">II", signature[16:24])
    return MediaMetadata(width=width, height=height)


def read_box(handle: BinaryIO, start: int, parent_end: int) -> Box | None:
    if start + 8 > parent_end:
        return None

    handle.seek(start)
    header = handle.read(8)
    if len(header) != 8:
        return None

    size_32, raw_type = struct.unpack(">I4s", header)
    box_type = raw_type.decode("latin-1")
    header_size = 8

    if size_32 == 1:
        large_size = handle.read(8)
        if len(large_size) != 8:
            return None
        size = struct.unpack(">Q", large_size)[0]
        header_size = 16
    elif size_32 == 0:
        size = parent_end - start
    else:
        size = size_32

    if size < header_size or start + size > parent_end:
        return None
    return Box(box_type=box_type, start=start, header_size=header_size, size=size)


def iter_boxes(handle: BinaryIO, start: int, end: int) -> Iterable[Box]:
    offset = start
    while offset + 8 <= end:
        box = read_box(handle, offset, end)
        if box is None:
            break
        yield box
        offset = box.end


def parse_mvhd(handle: BinaryIO, box: Box) -> float | None:
    handle.seek(box.payload_start)
    payload = handle.read(min(box.size - box.header_size, 32))
    if len(payload) < 20:
        return None

    version = payload[0]
    if version == 1:
        if len(payload) < 32:
            return None
        timescale = struct.unpack(">I", payload[20:24])[0]
        duration = struct.unpack(">Q", payload[24:32])[0]
    else:
        timescale = struct.unpack(">I", payload[12:16])[0]
        duration = struct.unpack(">I", payload[16:20])[0]

    if timescale == 0:
        return None
    return round(duration / timescale, 3)


def parse_mvhd_creation_date(handle: BinaryIO, box: Box) -> str:
    handle.seek(box.payload_start)
    payload = handle.read(min(box.size - box.header_size, 24))
    if len(payload) < 12:
        return ""
    version = payload[0]
    try:
        if version == 1:
            if len(payload) < 16:
                return ""
            raw_seconds = struct.unpack(">Q", payload[4:12])[0]
        else:
            raw_seconds = struct.unpack(">I", payload[4:8])[0]
        return quicktime_seconds_to_iso(raw_seconds)
    except (OverflowError, ValueError, struct.error):
        return ""


def quicktime_seconds_to_iso(raw_seconds: int) -> str:
    if raw_seconds <= 0:
        return ""
    quicktime_epoch = datetime(1904, 1, 1, tzinfo=timezone.utc)
    value = quicktime_epoch + timedelta(seconds=raw_seconds)
    if not (datetime(1990, 1, 1, tzinfo=timezone.utc) <= value <= datetime(2100, 1, 1, tzinfo=timezone.utc)):
        return ""
    return value.astimezone().isoformat(timespec="seconds")


def parse_tkhd_dimensions(handle: BinaryIO, box: Box) -> tuple[int, int] | None:
    handle.seek(box.payload_start)
    payload = handle.read(min(box.size - box.header_size, 128))
    if len(payload) < 84:
        return None

    version = payload[0]
    width_offset = 88 if version == 1 else 76
    height_offset = width_offset + 4
    if len(payload) < height_offset + 4:
        return None

    width_fixed = struct.unpack(">I", payload[width_offset : width_offset + 4])[0]
    height_fixed = struct.unpack(">I", payload[height_offset : height_offset + 4])[0]
    width = width_fixed >> 16
    height = height_fixed >> 16
    if width <= 0 or height <= 0:
        return None
    return width, height


def dimensions_are_larger(current_width: int | None, current_height: int | None, width: int, height: int) -> bool:
    if current_width is None or current_height is None:
        return True
    return width * height > current_width * current_height


def parse_ispe_dimensions(handle: BinaryIO, box: Box) -> tuple[int, int] | None:
    handle.seek(box.payload_start)
    payload = handle.read(min(box.size - box.header_size, 12))
    if len(payload) < 12:
        return None
    width, height = struct.unpack(">II", payload[4:12])
    if width <= 0 or height <= 0:
        return None
    return width, height


def parse_iso_media_metadata(path: Path) -> MediaMetadata:
    metadata = MediaMetadata()
    file_size = path.stat().st_size
    container_boxes = {"moov", "trak", "mdia", "minf", "stbl", "edts", "dinf", "udta", "iprp", "ipco"}

    with path.open("rb") as handle:
        stack: list[tuple[int, int]] = [(0, file_size)]
        while stack:
            start, end = stack.pop()
            for box in iter_boxes(handle, start, end):
                if box.box_type == "mvhd" and metadata.duration_seconds is None:
                    metadata.duration_seconds = parse_mvhd(handle, box)
                if box.box_type == "mvhd" and not metadata.capture_date:
                    capture_date = parse_mvhd_creation_date(handle, box)
                    if capture_date:
                        metadata.capture_date = capture_date
                        metadata.capture_date_source = "quicktime_mvhd"
                elif box.box_type == "tkhd":
                    dimensions = parse_tkhd_dimensions(handle, box)
                    if dimensions and dimensions_are_larger(metadata.width, metadata.height, *dimensions):
                        metadata.width, metadata.height = dimensions
                elif box.box_type == "ispe":
                    dimensions = parse_ispe_dimensions(handle, box)
                    if dimensions and dimensions_are_larger(metadata.width, metadata.height, *dimensions):
                        metadata.width, metadata.height = dimensions

                if box.box_type == "meta":
                    stack.append((box.payload_start + 4, box.end))
                elif box.box_type in container_boxes:
                    stack.append((box.payload_start, box.end))

    missing = []
    if metadata.width is None or metadata.height is None:
        missing.append("dimensions not found")
    if path.suffix.lower() in VIDEO_EXTENSIONS and metadata.duration_seconds is None:
        missing.append("duration not found")
    metadata.notes = "; ".join(missing)
    return metadata


def optional_module_available(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def pillow_capture_date(path: Path) -> tuple[str, str]:
    if not optional_module_available("PIL"):
        return "", ""
    try:
        from PIL import Image, ExifTags  # type: ignore[import-not-found]

        if path.suffix.lower() in {".heic", ".heif"} and optional_module_available("pillow_heif"):
            from pillow_heif import register_heif_opener  # type: ignore[import-not-found]

            register_heif_opener()

        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return "", ""
            tag_names = {value: key for key, value in ExifTags.TAGS.items()}
            for tag_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                tag_id = tag_names.get(tag_name)
                if tag_id is None:
                    continue
                parsed = normalize_exif_datetime(str(exif.get(tag_id) or ""))
                if parsed:
                    return parsed, f"pillow_{tag_name}"
    except Exception:  # noqa: BLE001 - optional decoder should fail soft.
        return "", ""
    return "", ""


def mdls_capture_date(path: Path) -> tuple[str, str]:
    if shutil.which("mdls") is None:
        return "", ""
    attributes = [
        "kMDItemContentCreationDate",
        "kMDItemFSCreationDate",
    ]
    for attribute in attributes:
        try:
            result = subprocess.run(
                ["mdls", "-raw", "-name", attribute, str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
        value = result.stdout.strip()
        if not value or value == "(null)":
            continue
        parsed = normalize_mdls_datetime(value)
        if parsed:
            return parsed, f"mdls_{attribute}"
    return "", ""


def normalize_mdls_datetime(value: str) -> str:
    cleaned = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(cleaned, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    parsed = normalize_exif_datetime(cleaned.replace("Z", "+00:00"))
    if parsed:
        return parsed
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).isoformat(timespec="seconds")
    except ValueError:
        return ""


def enrich_capture_date(path: Path, metadata: MediaMetadata) -> MediaMetadata:
    if metadata.capture_date:
        return metadata
    capture_date, source = pillow_capture_date(path)
    if capture_date:
        metadata.capture_date = capture_date
        metadata.capture_date_source = source
        return metadata
    capture_date, source = mdls_capture_date(path)
    if capture_date:
        metadata.capture_date = capture_date
        metadata.capture_date_source = source
    return metadata


def get_metadata(path: Path) -> MediaMetadata:
    ext = path.suffix.lower()
    try:
        if ext in {".jpg", ".jpeg"}:
            return enrich_capture_date(path, parse_jpeg_dimensions(path))
        if ext == ".png":
            return enrich_capture_date(path, parse_png_dimensions(path))
        if ext in {".heic", ".heif", ".mov", ".mp4", ".m4v"}:
            return enrich_capture_date(path, parse_iso_media_metadata(path))
    except OSError as exc:
        return MediaMetadata(notes=f"metadata read error: {exc}")
    except struct.error as exc:
        return MediaMetadata(notes=f"metadata parse error: {exc}")
    return MediaMetadata(notes="unsupported media extension")
