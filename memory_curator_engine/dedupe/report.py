"""Dry-run duplicate detection reports."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.media import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, MediaRecord
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import build_media_record, inventory_jobs_from_config, iter_media_files, parse_enabled


DUPLICATE_GROUP_COLUMNS = [
    "media_set",
    "group_id",
    "action",
    "original_path",
    "duplicate_path",
    "file_type",
    "size_bytes",
    "width",
    "height",
    "duration_seconds",
    "duplicate_type",
    "similarity_score",
    "hash_distance",
    "reason",
]

DUPLICATES_TO_REVIEW_COLUMNS = [
    "media_set",
    "group_id",
    "original_path",
    "duplicate_path",
    "keep_path",
    "duplicate_type",
    "reason",
]

KEEPER_MANIFEST_COLUMNS = [
    "media_set",
    "keeper_path",
    "file_type",
    "size_bytes",
    "capture_date",
    "capture_date_source",
    "created_date",
    "modified_date",
    "width",
    "height",
    "duration_seconds",
    "source_phase",
]


@dataclass(frozen=True)
class DuplicateConfig:
    enabled: bool
    dry_run: bool
    exact_hash: bool
    photo_near_duplicates: bool
    video_near_duplicates: bool
    preserve_video_near_duplicates: bool
    photo_hash_threshold: int
    video_hash_threshold: int
    video_sample_positions: list[float]
    output_dir: Path


@dataclass(frozen=True)
class HashedRecord:
    media_set: str
    record: MediaRecord
    sha256: str
    visual_hash: int | None = None
    visual_hash_error: str = ""


@dataclass
class DuplicateGroup:
    items: list[HashedRecord]
    duplicate_type: str
    hash_distance: int
    reason: str


@dataclass(frozen=True)
class DuplicateResult:
    scanned_count: int
    duplicate_group_count: int
    duplicate_file_count: int
    duplicate_groups_csv: Path
    duplicates_to_review_csv: Path
    keeper_manifest_csv: Path
    dry_run: bool


@dataclass(frozen=True)
class KeeperManifestResult:
    scanned_count: int
    keeper_manifest_csv: Path


def load_duplicate_config(config: Config, project_root: Path) -> DuplicateConfig:
    output_dir = resolve_project_path(
        project_root,
        config_value(config, "duplicate_detection.output_dir", "MemoryCurator/02 Duplicate Detection"),
    )
    return DuplicateConfig(
        enabled=parse_enabled(config_value(config, "modules.duplicate_detection.enabled", False), "duplicate_detection"),
        dry_run=parse_enabled(config_value(config, "duplicate_detection.dry_run", True), "duplicate_detection.dry_run"),
        exact_hash=parse_enabled(config_value(config, "duplicate_detection.exact_hash", True), "duplicate_detection.exact_hash"),
        photo_near_duplicates=parse_enabled(
            config_value(config, "duplicate_detection.photo_near_duplicates", False),
            "duplicate_detection.photo_near_duplicates",
        ),
        video_near_duplicates=parse_enabled(
            config_value(config, "duplicate_detection.video_near_duplicates", False),
            "duplicate_detection.video_near_duplicates",
        ),
        preserve_video_near_duplicates=parse_enabled(
            config_value(config, "duplicate_detection.preserve_video_near_duplicates", True),
            "duplicate_detection.preserve_video_near_duplicates",
        ),
        photo_hash_threshold=int(config_value(config, "duplicate_detection.photo_hash_threshold", 8)),
        video_hash_threshold=int(config_value(config, "duplicate_detection.video_hash_threshold", 10)),
        video_sample_positions=parse_float_list(config_value(config, "duplicate_detection.video_sample_positions", [0.1, 0.5, 0.9])),
        output_dir=output_dir,
    )


def parse_float_list(value: object) -> list[float]:
    if not isinstance(value, list):
        return [0.1, 0.5, 0.9]
    positions = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 1:
            positions.append(number)
    return positions or [0.1, 0.5, 0.9]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def optional_module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def pillow_image_hash(path: Path) -> tuple[int | None, str]:
    if not optional_module_available("PIL"):
        return None, "Pillow not installed"

    try:
        from PIL import Image

        if optional_module_available("pillow_heif"):
            from pillow_heif import register_heif_opener

            register_heif_opener()

        with Image.open(path) as image:
            image = image.convert("RGB")
            return difference_hash_from_pillow(image), ""
    except Exception as exc:  # noqa: BLE001 - optional decoder failures should become reportable notes.
        return None, f"Pillow image hashing failed: {exc}"


def pillow_hash_from_array(frame: object) -> tuple[int | None, str]:
    if not optional_module_available("PIL"):
        return None, "Pillow not installed"

    try:
        from PIL import Image

        image = Image.fromarray(frame).convert("RGB")
        return difference_hash_from_pillow(image), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"Pillow image hashing failed for frame: {exc}"


def difference_hash_from_pillow(image: object) -> int:
    resized = image.resize((9, 8)).convert("L")
    pixels = list(resized.getdata())
    if len(set(pixels)) < 4:
        raise ValueError("thumbnail has too little visual variation")

    value = 0
    for row in range(8):
        row_start = row * 9
        for column in range(8):
            left = pixels[row_start + column]
            right = pixels[row_start + column + 1]
            value = (value << 1) | int(left > right)
    return value


def parse_bmp_grayscale_pixels(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("BMP signature not found")

    pixel_offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    height = int.from_bytes(data[22:26], "little", signed=True)
    bits_per_pixel = int.from_bytes(data[28:30], "little")
    if width <= 0 or height == 0 or bits_per_pixel not in {24, 32}:
        raise ValueError(f"Unsupported BMP format: {width}x{height}, {bits_per_pixel} bpp")

    absolute_height = abs(height)
    bytes_per_pixel = bits_per_pixel // 8
    row_stride = ((width * bytes_per_pixel + 3) // 4) * 4
    top_down = height < 0
    pixels: list[int] = []

    for row_index in range(absolute_height):
        source_row = row_index if top_down else absolute_height - row_index - 1
        row_start = pixel_offset + source_row * row_stride
        for column in range(width):
            pixel_start = row_start + column * bytes_per_pixel
            blue, green, red = data[pixel_start : pixel_start + 3]
            pixels.append(round((red * 0.299) + (green * 0.587) + (blue * 0.114)))

    return pixels


def difference_hash_from_bmp(path: Path) -> int:
    pixels = parse_bmp_grayscale_pixels(path)
    if len(set(pixels)) < 4:
        raise ValueError("thumbnail has too little visual variation")
    width = 9
    height = 8
    if len(pixels) != width * height:
        raise ValueError(f"Expected {width}x{height} thumbnail, found {len(pixels)} pixels")
    value = 0
    for row in range(height):
        row_start = row * width
        for column in range(width - 1):
            left = pixels[row_start + column]
            right = pixels[row_start + column + 1]
            value = (value << 1) | int(left > right)
    return value


def image_difference_hash(path: Path, temp_dir: Path) -> tuple[int | None, str]:
    if shutil.which("sips") is None:
        return None, "sips not available for image decoding"

    bmp_path = temp_dir / f"{path.stem}.bmp"
    command = ["sips", "-z", "8", "9", "-s", "format", "bmp", "--out", str(bmp_path), str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "sips conversion failed"
        return None, message
    try:
        return difference_hash_from_bmp(bmp_path), ""
    except (OSError, ValueError) as exc:
        return None, str(exc)


def quicklook_thumbnail(path: Path, temp_dir: Path) -> tuple[Path | None, str]:
    if shutil.which("qlmanage") is None:
        return None, "qlmanage not available for thumbnail extraction"

    thumbnail_dir = temp_dir / f"ql-{hashlib.sha1(str(path).encode('utf-8')).hexdigest()}"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    command = ["qlmanage", "-t", "-s", "128", "-o", str(thumbnail_dir), str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "qlmanage thumbnail extraction failed"
        return None, message

    thumbnails = sorted(thumbnail_dir.glob(f"{path.name}*.png"))
    if not thumbnails:
        thumbnails = sorted(thumbnail_dir.glob("*.png"))
    if not thumbnails:
        return None, "qlmanage did not produce a thumbnail"
    return thumbnails[0], ""


def quicklook_difference_hash(path: Path, temp_dir: Path) -> tuple[int | None, str]:
    thumbnail, error = quicklook_thumbnail(path, temp_dir)
    if thumbnail is None:
        return None, error
    return image_difference_hash(thumbnail, temp_dir)


def visual_hash_for_record(record: MediaRecord, temp_dir: Path) -> tuple[int | None, str]:
    suffix = record.path.suffix.lower()
    if suffix in PHOTO_EXTENSIONS:
        pillow_hash, pillow_error = pillow_image_hash(record.path)
        if pillow_hash is not None:
            return pillow_hash, ""
        if suffix not in {".heic", ".heif"}:
            fallback_hash, fallback_error = image_difference_hash(record.path, temp_dir)
            return fallback_hash, fallback_error or pillow_error
        fallback_hash, fallback_error = quicklook_difference_hash(record.path, temp_dir)
        return fallback_hash, fallback_error or pillow_error
    return None, "unsupported media type for visual hashing"


def visual_hash_for_video(record: MediaRecord, temp_dir: Path, sample_positions: list[float]) -> tuple[int | None, str]:
    opencv_hash, opencv_error = opencv_video_hash(record.path, sample_positions)
    if opencv_hash is not None:
        return opencv_hash, ""
    fallback_hash, fallback_error = quicklook_difference_hash(record.path, temp_dir)
    return fallback_hash, fallback_error or opencv_error


def opencv_video_hash(path: Path, sample_positions: list[float]) -> tuple[int | None, str]:
    if not optional_module_available("cv2"):
        return None, "opencv-python not installed"
    if not optional_module_available("PIL"):
        return None, "Pillow not installed for video frame hashing"

    try:
        import cv2

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return None, "OpenCV could not open video"

        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            capture.release()
            return None, "OpenCV could not determine frame count"

        hashes: list[int] = []
        for position in sample_positions:
            frame_index = min(frame_count - 1, max(0, int(frame_count * position)))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_hash, _ = pillow_hash_from_array(frame)
            if frame_hash is not None:
                hashes.append(frame_hash)
        capture.release()

        if not hashes:
            return None, "OpenCV did not produce hashable frames"
        return combine_hashes(hashes), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"OpenCV video hashing failed: {exc}"


def combine_hashes(hashes: list[int]) -> int:
    combined = 0
    for bit_index in range(63, -1, -1):
        ones = sum((value >> bit_index) & 1 for value in hashes)
        combined = (combined << 1) | int(ones >= (len(hashes) / 2))
    return combined


def legacy_visual_hash_for_record(record: MediaRecord, temp_dir: Path) -> tuple[int | None, str]:
    suffix = record.path.suffix.lower()
    if suffix in {".heic", ".heif"}:
        return quicklook_difference_hash(record.path, temp_dir)
    if suffix in PHOTO_EXTENSIONS:
        return image_difference_hash(record.path, temp_dir)
    if suffix in VIDEO_EXTENSIONS:
        return quicklook_difference_hash(record.path, temp_dir)
    return None, "unsupported media type for visual hashing"


def record_quality_key(item: HashedRecord) -> tuple[int, float, int, int, str]:
    metadata = item.record.metadata
    pixels = (metadata.width or 0) * (metadata.height or 0)
    duration = metadata.duration_seconds or 0.0
    metadata_fields = sum(
        value not in {None, ""}
        for value in [metadata.width, metadata.height, metadata.duration_seconds, item.record.created_date, item.record.modified_date]
    )
    return (pixels, duration, item.record.size_bytes, metadata_fields, item.record.relative_path)


def choose_best(items: list[HashedRecord]) -> HashedRecord:
    return max(items, key=record_quality_key)


def duplicate_items_for_manifest(config: DuplicateConfig, duplicate_groups: list[DuplicateGroup]) -> list[HashedRecord]:
    duplicate_items: list[HashedRecord] = []
    for group in duplicate_groups:
        if config.preserve_video_near_duplicates and group.duplicate_type.startswith("video_"):
            continue
        keep = choose_best(group.items)
        duplicate_items.extend(item for item in group.items if item != keep)
    return duplicate_items


def keeper_manifest_row(item: HashedRecord) -> dict[str, object]:
    metadata = item.record.metadata
    return {
        "media_set": item.media_set,
        "keeper_path": item.record.relative_path,
        "file_type": item.record.file_type,
        "size_bytes": item.record.size_bytes,
        "capture_date": item.record.capture_date,
        "capture_date_source": item.record.capture_date_source,
        "created_date": item.record.created_date,
        "modified_date": item.record.modified_date,
        "width": metadata.width or "",
        "height": metadata.height or "",
        "duration_seconds": metadata.duration_seconds if metadata.duration_seconds is not None else "",
        "source_phase": "duplicate_detection",
    }


def write_keeper_manifest(config: DuplicateConfig, records: list[HashedRecord], duplicate_groups: list[DuplicateGroup]) -> Path:
    duplicate_paths = {item.record.path for item in duplicate_items_for_manifest(config, duplicate_groups)}
    keeper_manifest_csv = config.output_dir / "keeper_manifest.csv"

    with keeper_manifest_csv.open("w", newline="", encoding="utf-8") as manifest_file:
        writer = csv.DictWriter(manifest_file, fieldnames=KEEPER_MANIFEST_COLUMNS)
        writer.writeheader()
        for item in sorted(records, key=lambda hashed: (hashed.media_set, hashed.record.relative_path)):
            if item.record.path in duplicate_paths:
                continue
            writer.writerow(keeper_manifest_row(item))

    return keeper_manifest_csv


def write_keeper_manifest_for_records(config: DuplicateConfig, records: list[HashedRecord]) -> Path:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    return write_keeper_manifest(config=config, records=records, duplicate_groups=[])


def row_for_item(
    item: HashedRecord,
    group_id: str,
    action: str,
    duplicate_path: Path | None,
    duplicate_type: str,
    hash_distance: int,
    reason: str,
    project_root: Path,
) -> dict[str, object]:
    metadata = item.record.metadata
    return {
        "media_set": item.media_set,
        "group_id": group_id,
        "action": action,
        "original_path": item.record.relative_path,
        "duplicate_path": duplicate_path.relative_to(project_root).as_posix() if duplicate_path else "",
        "file_type": item.record.file_type,
        "size_bytes": item.record.size_bytes,
        "width": metadata.width or "",
        "height": metadata.height or "",
        "duration_seconds": metadata.duration_seconds if metadata.duration_seconds is not None else "",
        "duplicate_type": duplicate_type,
        "similarity_score": round(1 - (hash_distance / 64), 4) if duplicate_type != "exact_hash" else "1.0",
        "hash_distance": hash_distance,
        "reason": reason,
    }


def write_reports(
    config: DuplicateConfig,
    project_root: Path,
    records: list[HashedRecord],
    duplicate_groups: list[DuplicateGroup],
    scanned_count: int,
) -> DuplicateResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    duplicate_groups_csv = config.output_dir / "duplicate_groups.csv"
    duplicates_to_review_csv = config.output_dir / "duplicates_to_review.csv"
    keeper_manifest_csv = config.output_dir / "keeper_manifest.csv"

    duplicate_file_count = 0
    with duplicate_groups_csv.open("w", newline="", encoding="utf-8") as groups_file, duplicates_to_review_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as review_file:
        groups_writer = csv.DictWriter(groups_file, fieldnames=DUPLICATE_GROUP_COLUMNS)
        review_writer = csv.DictWriter(review_file, fieldnames=DUPLICATES_TO_REVIEW_COLUMNS)
        groups_writer.writeheader()
        review_writer.writeheader()

        for index, group in enumerate(duplicate_groups, start=1):
            group_id = f"{group.duplicate_type}-{index:04d}"
            keep = choose_best(group.items)

            for item in sorted(group.items, key=lambda hashed: hashed.record.relative_path):
                if item == keep:
                    groups_writer.writerow(
                        row_for_item(
                            item=item,
                            group_id=group_id,
                            action="keep",
                            duplicate_path=None,
                            duplicate_type=group.duplicate_type,
                            hash_distance=group.hash_distance,
                            reason=group.reason,
                            project_root=project_root,
                        )
                    )
                    continue

                duplicate_file_count += 1
                groups_writer.writerow(
                    row_for_item(
                        item=item,
                        group_id=group_id,
                        action="duplicate",
                        duplicate_path=item.record.path,
                        duplicate_type=group.duplicate_type,
                        hash_distance=group.hash_distance,
                        reason=group.reason,
                        project_root=project_root,
                    )
                )
                review_writer.writerow(
                    {
                        "media_set": item.media_set,
                        "group_id": group_id,
                        "original_path": item.record.relative_path,
                        "duplicate_path": item.record.relative_path,
                        "keep_path": keep.record.relative_path,
                        "duplicate_type": group.duplicate_type,
                        "reason": group.reason,
                    }
                )

    keeper_manifest_csv = write_keeper_manifest(config=config, records=records, duplicate_groups=duplicate_groups)
    write_activity_csv_copies(
        output_dir=config.output_dir,
        csv_paths=[duplicate_groups_csv, duplicates_to_review_csv, keeper_manifest_csv],
    )

    return DuplicateResult(
        scanned_count=scanned_count,
        duplicate_group_count=len(duplicate_groups),
        duplicate_file_count=duplicate_file_count,
        duplicate_groups_csv=duplicate_groups_csv,
        duplicates_to_review_csv=duplicates_to_review_csv,
        keeper_manifest_csv=keeper_manifest_csv,
        dry_run=config.dry_run,
    )


def write_activity_csv_copies(output_dir: Path, csv_paths: list[Path]) -> None:
    for csv_path in csv_paths:
        if not csv_path.exists():
            continue
        with csv_path.open(newline="", encoding="utf-8") as source_file:
            reader = csv.DictReader(source_file)
            fieldnames = reader.fieldnames or []
            if "media_set" not in fieldnames:
                continue
            rows_by_set: dict[str, list[dict[str, str]]] = {}
            for row in reader:
                media_set = row.get("media_set") or "default"
                rows_by_set.setdefault(media_set, []).append(row)
        for media_set, rows in rows_by_set.items():
            activity_dir = output_dir / media_set
            activity_dir.mkdir(parents=True, exist_ok=True)
            with (activity_dir / csv_path.name).open("w", newline="", encoding="utf-8") as target_file:
                writer = csv.DictWriter(target_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def media_kind(record: MediaRecord) -> str:
    if record.path.suffix.lower() in PHOTO_EXTENSIONS:
        return "photo"
    if record.path.suffix.lower() in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def build_duplicate_groups(records: list[HashedRecord], config: DuplicateConfig) -> list[DuplicateGroup]:
    union_find = UnionFind(len(records))
    reasons: dict[tuple[int, int], tuple[str, int, str]] = {}

    if config.exact_hash:
        by_sha: dict[str, list[int]] = {}
        for index, item in enumerate(records):
            by_sha.setdefault(item.sha256, []).append(index)

        for indexes in by_sha.values():
            if len(indexes) < 2:
                continue
            first = indexes[0]
            for index in indexes[1:]:
                union_find.union(first, index)
                reasons[tuple(sorted((first, index)))] = (
                    "exact_hash",
                    0,
                    "same SHA-256 file content hash; highest quality candidate kept",
                )

    for left_index, left in enumerate(records):
        if left.visual_hash is None:
            continue
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            if right.visual_hash is None:
                continue
            left_kind = media_kind(left.record)
            right_kind = media_kind(right.record)
            if left_kind != right_kind:
                continue

            distance = hamming_distance(left.visual_hash, right.visual_hash)
            if left_kind == "photo" and config.photo_near_duplicates and distance <= config.photo_hash_threshold:
                union_find.union(left_index, right_index)
                reasons[tuple(sorted((left_index, right_index)))] = (
                    "photo_visual_similarity",
                    distance,
                    f"photo difference-hash distance {distance} <= threshold {config.photo_hash_threshold}; highest quality candidate kept",
                )
            elif left_kind == "video" and config.video_near_duplicates and distance <= config.video_hash_threshold:
                if not videos_are_comparable(left.record, right.record):
                    continue
                union_find.union(left_index, right_index)
                reasons[tuple(sorted((left_index, right_index)))] = (
                    "video_visual_similarity",
                    distance,
                    f"video thumbnail difference-hash distance {distance} <= threshold {config.video_hash_threshold}; highest quality candidate kept",
                )

    groups_by_root: dict[int, list[int]] = {}
    for index in range(len(records)):
        groups_by_root.setdefault(union_find.find(index), []).append(index)

    duplicate_groups: list[DuplicateGroup] = []
    for indexes in groups_by_root.values():
        if len(indexes) < 2:
            continue
        duplicate_type, distance, reason = best_group_reason(indexes, reasons)
        duplicate_groups.append(
            DuplicateGroup(
                items=[records[index] for index in indexes],
                duplicate_type=duplicate_type,
                hash_distance=distance,
                reason=reason,
            )
        )

    duplicate_groups.sort(key=lambda group: sorted(item.record.relative_path for item in group.items)[0])
    return duplicate_groups


def best_group_reason(indexes: list[int], reasons: dict[tuple[int, int], tuple[str, int, str]]) -> tuple[str, int, str]:
    priority = {"exact_hash": 0, "photo_visual_similarity": 1, "video_visual_similarity": 1}
    candidates = [
        reasons[pair]
        for left_offset, left in enumerate(indexes)
        for right in indexes[left_offset + 1 :]
        for pair in [tuple(sorted((left, right)))]
        if pair in reasons
    ]
    if not candidates:
        return ("unknown", 64, "grouped by duplicate detection; highest quality candidate kept")
    return min(candidates, key=lambda candidate: (priority.get(candidate[0], 9), candidate[1]))


def videos_are_comparable(left: MediaRecord, right: MediaRecord) -> bool:
    left_meta = left.metadata
    right_meta = right.metadata
    if left_meta.width and right_meta.width and left_meta.height and right_meta.height:
        if (left_meta.width, left_meta.height) != (right_meta.width, right_meta.height):
            return False
    if left_meta.duration_seconds is not None and right_meta.duration_seconds is not None:
        return abs(left_meta.duration_seconds - right_meta.duration_seconds) <= 2.0
    return True


def run_duplicate_detection(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
) -> DuplicateResult:
    duplicate_config = load_duplicate_config(config=config, project_root=project_root)
    if execute:
        duplicate_config = replace(duplicate_config, dry_run=False)
    if not duplicate_config.enabled and not include_disabled:
        return write_reports(config=duplicate_config, project_root=project_root, records=[], duplicate_groups=[], scanned_count=0)

    jobs = inventory_jobs_from_config(config=config, project_root=project_root)
    records: list[HashedRecord] = []
    scanned_count = 0

    with tempfile.TemporaryDirectory(prefix="memory-curator-dedupe-") as temp_name:
        temp_dir = Path(temp_name)
        for job in jobs:
            if not job.enabled:
                continue
            if not job.input_dir.exists() or not job.input_dir.is_dir():
                raise FileNotFoundError(f"Input folder not found for inventory set '{job.name}': {job.input_dir}")

            for path in iter_media_files(job.input_dir):
                record = build_media_record(path=path, project_root=project_root)
                visual_hash = None
                visual_hash_error = ""
                if (media_kind(record) == "photo" and duplicate_config.photo_near_duplicates) or (
                    media_kind(record) == "video" and duplicate_config.video_near_duplicates
                ):
                    if media_kind(record) == "video":
                        visual_hash, visual_hash_error = visual_hash_for_video(
                            record,
                            temp_dir,
                            duplicate_config.video_sample_positions,
                        )
                    else:
                        visual_hash, visual_hash_error = visual_hash_for_record(record, temp_dir)
                records.append(
                    HashedRecord(
                        media_set=job.name,
                        record=record,
                        sha256=sha256_file(path) if duplicate_config.exact_hash else "",
                        visual_hash=visual_hash,
                        visual_hash_error=visual_hash_error,
                    )
                )
                scanned_count += 1

    duplicate_groups = build_duplicate_groups(records, duplicate_config)
    return write_reports(
        config=duplicate_config,
        project_root=project_root,
        records=records,
        duplicate_groups=duplicate_groups,
        scanned_count=scanned_count,
    )


def run_keeper_manifest(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
) -> KeeperManifestResult:
    duplicate_config = load_duplicate_config(config=config, project_root=project_root)
    if not duplicate_config.enabled and not include_disabled:
        manifest_csv = write_keeper_manifest_for_records(config=duplicate_config, records=[])
        return KeeperManifestResult(scanned_count=0, keeper_manifest_csv=manifest_csv)

    jobs = inventory_jobs_from_config(config=config, project_root=project_root)
    records: list[HashedRecord] = []

    for job in jobs:
        if not job.enabled:
            continue
        if not job.input_dir.exists() or not job.input_dir.is_dir():
            raise FileNotFoundError(f"Input folder not found for inventory set '{job.name}': {job.input_dir}")

        for path in iter_media_files(job.input_dir):
            records.append(
                HashedRecord(
                    media_set=job.name,
                    record=build_media_record(path=path, project_root=project_root),
                    sha256="",
                )
            )

    manifest_csv = write_keeper_manifest_for_records(config=duplicate_config, records=records)
    return KeeperManifestResult(scanned_count=len(records), keeper_manifest_csv=manifest_csv)
