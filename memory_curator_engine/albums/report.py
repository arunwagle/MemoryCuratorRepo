"""Album Builder reports and dry-run/export planning."""

from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.media import PHOTO_EXTENSIONS
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import parse_enabled


ALBUM_CANDIDATE_COLUMNS = [
    "media_set",
    "activity",
    "album_size",
    "moment_id",
    "moment_title",
    "moment_type",
    "media_path",
    "original_path",
    "file_type",
    "width",
    "height",
    "quality_score",
    "memory_score",
    "story_score",
    "people_score",
    "face_count",
    "face_cutoff_count",
    "visual_hash",
    "diversity_score",
    "final_album_score",
    "candidate_role",
    "selection_status",
    "selection_reason",
    "exclusion_reason",
]

ALBUM_SELECTION_COLUMNS = [
    "media_set",
    "activity",
    "album_size",
    "album_sequence",
    "moment_id",
    "moment_title",
    "moment_type",
    "media_path",
    "export_path",
    "original_path",
    "candidate_role",
    "final_album_score",
    "selection_reason",
]

ALBUM_MANIFEST_COLUMNS = [
    "media_set",
    "activity",
    "album_size",
    "album_sequence",
    "moment_id",
    "moment_title",
    "media_path",
    "export_path",
    "original_path",
    "file_type",
    "width",
    "height",
    "final_album_score",
    "candidate_role",
    "source_phase",
]


@dataclass(frozen=True)
class AlbumSizeConfig:
    name: str
    enabled: bool
    strategy: str
    min_photos: int
    target_photos: int
    max_photos: int
    min_per_important_moment: int
    max_per_moment: int
    include_all_good: bool
    exclude_from: tuple[str, ...]
    overlap_limit_fraction: float


@dataclass(frozen=True)
class AlbumConfig:
    enabled: bool
    dry_run: bool
    trip_slug: str
    album_scope: str
    input_story_manifest: Path
    input_moments: Path
    input_moment_assets: Path
    input_quality_manifest: Path
    output_dir: Path
    exports_dir: Path
    copy_on_execute: bool
    pdf_export_enabled: bool
    pdf_title: str
    pdf_subtitle: str
    pdf_cover_photo: str
    pdf_closing_photo: str
    require_faces: bool
    min_faces: int
    face_detection_backend: str
    face_detection_model: Path
    face_score_threshold: float
    exclude_cutoff_faces: bool
    face_edge_margin_ratio: float
    similarity_filter_enabled: bool
    similarity_hash_size: int
    similarity_duplicate_distance: int
    similarity_burst_distance: int
    similarity_burst_window_seconds: int
    similarity_imagehash_enabled: bool
    similarity_imagehash_distance: int
    orientation_correction_enabled: bool
    orientation_score_margin: float
    overwrite_policy: str
    sizes: list[AlbumSizeConfig]
    activity_names: dict[str, str]
    activity_order: dict[str, int]
    important_moment_types: set[str]
    max_same_minute_per_album: int
    max_same_moment_fraction: float
    quality_weight: float
    memory_weight: float
    story_weight: float
    people_weight: float
    diversity_weight: float


@dataclass(frozen=True)
class MomentInfo:
    moment_id: str
    media_set: str
    moment_type: str
    title: str
    start_time: str
    album_score: float
    photo_count: int
    hero_photo: str


@dataclass(frozen=True)
class PhotoCandidate:
    media_set: str
    activity: str
    moment_id: str
    moment_title: str
    moment_type: str
    media_path: str
    original_path: str
    file_type: str
    captured_at: str
    width: str
    height: str
    quality_score: float
    memory_score: float
    story_score: float
    people_score: float
    face_count: int
    face_cutoff_count: int
    visual_hash: str
    perceptual_hashes: tuple[str, str, str, str]
    diversity_score: float
    final_album_score: float
    candidate_role: str
    selection_reason: str = ""
    exclusion_reason: str = ""


@dataclass(frozen=True)
class SelectedPhoto:
    candidate: PhotoCandidate
    album_size: str
    sequence: int
    export_path: Path
    selection_reason: str


@dataclass(frozen=True)
class AlbumResult:
    candidate_count: int
    variant_counts: dict[str, int]
    small_count: int
    standard_count: int
    extended_count: int
    enhanced_count: int
    copied_count: int
    generated_pdf_count: int
    album_candidates_csv: Path
    album_selection_csv: Path
    album_manifest_csv: Path
    album_report_md: Path
    dry_run: bool


@dataclass(frozen=True)
class FaceAnalysis:
    count: int
    cutoff_count: int


@dataclass(frozen=True)
class FaceOrientationScore:
    face_count: int
    cutoff_count: int
    score: float


_ORIENTED_IMAGE_ROTATION_CACHE: dict[str, int] = {}


def load_album_config(config: Config, project_root: Path) -> AlbumConfig:
    output_dir = resolve_project_path(project_root, config_value(config, "album_builder.output_dir", "MemoryCurator/06 Album Builder"))
    curated_root = config_value(config, "project.curated_root", "input_data/curated")
    scoring = config_value(config, "album_builder.scoring", {}) or {}
    activity_names, activity_order = load_album_activity_maps(config)
    return AlbumConfig(
        enabled=parse_enabled(config_value(config, "modules.album_builder.enabled", False), "album_builder"),
        dry_run=parse_enabled(config_value(config, "album_builder.dry_run", True), "album_builder.dry_run"),
        trip_slug=str(config_value(config, "project.trip_slug", "trip")),
        album_scope=str(config_value(config, "album_builder.album_scope", "trip")),
        input_story_manifest=resolve_project_path(
            project_root,
            config_value(config, "album_builder.input_story_manifest", "MemoryCurator/05 Story Builder/story_manifest.csv"),
        ),
        input_moments=resolve_project_path(project_root, config_value(config, "album_builder.input_moments", "MemoryCurator/05 Story Builder/moments.csv")),
        input_moment_assets=resolve_project_path(
            project_root,
            config_value(config, "album_builder.input_moment_assets", "MemoryCurator/05 Story Builder/moment_assets.csv"),
        ),
        input_quality_manifest=resolve_project_path(
            project_root,
            config_value(config, "album_builder.input_quality_manifest", "MemoryCurator/03 Quality Scoring/quality_manifest.csv"),
        ),
        output_dir=output_dir,
        exports_dir=resolve_project_path(project_root, config_value(config, "album_builder.exports_dir", f"{curated_root}/06 Album Builder/exports")),
        copy_on_execute=parse_enabled(config_value(config, "album_builder.copy_on_execute", False), "album_builder.copy_on_execute"),
        pdf_export_enabled=parse_enabled(config_value(config, "album_builder.pdf_export.enabled", True), "album_builder.pdf_export.enabled"),
        pdf_title=str(config_value(config, "album_builder.pdf_export.title", "Some friendships never needed a restart.")),
        pdf_subtitle=str(config_value(config, "album_builder.pdf_export.subtitle", "from this trip")),
        pdf_cover_photo=str(config_value(config, "album_builder.pdf_export.cover_photo", "auto")),
        pdf_closing_photo=str(config_value(config, "album_builder.pdf_export.closing_photo", "auto")),
        require_faces=parse_enabled(config_value(config, "album_builder.face_filter.require_faces", True), "album_builder.face_filter.require_faces"),
        min_faces=int(config_value(config, "album_builder.face_filter.min_faces", 1)),
        face_detection_backend=str(config_value(config, "album_builder.face_filter.backend", "opencv_yunet")),
        face_detection_model=resolve_project_path(
            project_root,
            config_value(config, "album_builder.face_filter.model_path", "models/face_detection_yunet_2023mar.onnx"),
        ),
        face_score_threshold=float(config_value(config, "album_builder.face_filter.score_threshold", 0.45)),
        exclude_cutoff_faces=parse_enabled(config_value(config, "album_builder.face_filter.exclude_cutoff_faces", True), "album_builder.face_filter.exclude_cutoff_faces"),
        face_edge_margin_ratio=float(config_value(config, "album_builder.face_filter.edge_margin_ratio", 0.025)),
        similarity_filter_enabled=parse_enabled(config_value(config, "album_builder.similarity_filter.enabled", True), "album_builder.similarity_filter.enabled"),
        similarity_hash_size=int(config_value(config, "album_builder.similarity_filter.hash_size", 16)),
        similarity_duplicate_distance=int(config_value(config, "album_builder.similarity_filter.duplicate_distance", 24)),
        similarity_burst_distance=int(config_value(config, "album_builder.similarity_filter.burst_distance", 54)),
        similarity_burst_window_seconds=int(config_value(config, "album_builder.similarity_filter.burst_window_seconds", 900)),
        similarity_imagehash_enabled=parse_enabled(
            config_value(config, "album_builder.similarity_filter.imagehash_enabled", True),
            "album_builder.similarity_filter.imagehash_enabled",
        ),
        similarity_imagehash_distance=int(config_value(config, "album_builder.similarity_filter.imagehash_distance", 26)),
        orientation_correction_enabled=parse_enabled(
            config_value(config, "album_builder.orientation_correction.enabled", True),
            "album_builder.orientation_correction.enabled",
        ),
        orientation_score_margin=float(config_value(config, "album_builder.orientation_correction.score_margin", 40.0)),
        overwrite_policy=str(config_value(config, "album_builder.overwrite_policy", "fail")),
        sizes=load_size_configs(config),
        activity_names=activity_names,
        activity_order=activity_order,
        important_moment_types=set(config_value(config, "album_builder.important_moment_types", default_important_moments())),
        max_same_minute_per_album=int(config_value(config, "album_builder.max_same_minute_per_album", 3)),
        max_same_moment_fraction=float(config_value(config, "album_builder.max_same_moment_fraction", 0.20)),
        quality_weight=float(scoring.get("quality_weight", 0.30)),
        memory_weight=float(scoring.get("memory_weight", 0.30)),
        story_weight=float(scoring.get("story_weight", 0.20)),
        people_weight=float(scoring.get("people_weight", 0.10)),
        diversity_weight=float(scoring.get("diversity_weight", 0.10)),
    )


def load_album_activity_maps(config: Config) -> tuple[dict[str, str], dict[str, int]]:
    media_sets = config_value(config, "inventory.media_sets", {}) or {}
    if not isinstance(media_sets, dict):
        return {}, {}
    names: dict[str, str] = {}
    order: dict[str, int] = {}
    for index, (name, values) in enumerate(media_sets.items()):
        section = values if isinstance(values, dict) else {}
        media_set = str(name)
        names[media_set] = str(section.get("activity_name") or media_set.replace("_", " ").title())
        order[media_set] = index
    return names, order


def activity_name_for(config: AlbumConfig, media_set: str) -> str:
    return config.activity_names.get(media_set, media_set.replace("_", " ").title())


def default_important_moments() -> list[str]:
    return ["arrival", "safety_briefing", "gear_up", "launch", "rapids", "splash", "group_photo", "meal", "return_trip"]


def load_size_configs(config: Config) -> list[AlbumSizeConfig]:
    size_defaults = {
        "small": (20, 25, 30, 1, 2, False, "story"),
        "standard": (40, 50, 60, 1, 3, False, "story"),
        "extended": (80, 100, 120, 2, 6, False, "story"),
        "enhanced": (70, 160, 10000, 0, 10000, True, "visual_story"),
    }
    configured = config_value(config, "album_builder.variants", None)
    if configured is None:
        configured = config_value(config, "album_builder.sizes", {}) or {}
    sizes: list[AlbumSizeConfig] = []
    configured_names = list(configured.keys()) if isinstance(configured, dict) and configured else ["enhanced"]
    for name in configured_names:
        section = configured.get(name, {}) if isinstance(configured, dict) else {}
        defaults = size_defaults.get(name, (0, 0, 10000, 0, 10000, True, "story"))
        min_photos, target_photos, max_photos, min_per_moment, max_per_moment, include_all_good, strategy = defaults
        enabled = parse_enabled(section.get("enabled", True), f"album_builder.sizes.{name}.enabled")
        if not enabled:
            continue
        exclude_from = section.get("exclude_from", section.get("exclude_media_paths_from", []))
        if isinstance(exclude_from, str):
            exclude_from = [exclude_from]
        sizes.append(
            AlbumSizeConfig(
                name=name,
                enabled=enabled,
                strategy=str(section.get("strategy", strategy)),
                min_photos=int(section.get("min_photos", min_photos)),
                target_photos=int(section.get("target_photos", target_photos)),
                max_photos=int(section.get("max_photos", max_photos)),
                min_per_important_moment=int(section.get("min_per_important_moment", min_per_moment)),
                max_per_moment=int(section.get("max_per_moment", max_per_moment)),
                include_all_good=parse_enabled(section.get("include_all_good", include_all_good), f"album_builder.sizes.{name}.include_all_good"),
                exclude_from=tuple(str(value) for value in exclude_from),
                overlap_limit_fraction=float(section.get("overlap_limit_fraction", 0.0)),
            )
        )
    return sizes


def read_csv_required(path: Path, project_root: Path, phase_hint: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing upstream manifest: {path.relative_to(project_root).as_posix()}. Run {phase_hint} first.")
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"Upstream manifest is empty: {path.relative_to(project_root).as_posix()}. Run {phase_hint} first.")
    return rows


def safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except ValueError:
        return default


def safe_int_text(value: str | None) -> str:
    try:
        number = int(float(value or ""))
    except ValueError:
        return ""
    return str(number) if number else ""


def is_photo_path(path: str, file_type: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in PHOTO_EXTENSIONS or file_type.startswith("photo/")


def role_from_asset(role: str, moment_type: str, media_path: str) -> str:
    if role == "hero_photo":
        return "hero"
    if moment_type in {"group_photo", "meal"}:
        return "group"
    if moment_type in {"rapids", "splash", "launch"}:
        return "action"
    if moment_type in {"arrival", "travel_to_activity", "return_trip"}:
        return "establishing"
    if moment_type in {"gear_up", "safety_briefing", "walk_to_start"}:
        return "detail"
    lowered = Path(media_path).stem.lower()
    if any(token in lowered for token in ["laugh", "fun", "smile"]):
        return "candid"
    return "supporting"


def slugify(value: str) -> str:
    cleaned = []
    previous_underscore = False
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
            previous_underscore = False
        elif not previous_underscore:
            cleaned.append("_")
            previous_underscore = True
    return "".join(cleaned).strip("_") or "album"


def minute_key(captured_at: str) -> str:
    return captured_at[:16] if len(captured_at) >= 16 else captured_at


def path_text(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def load_moments(config: AlbumConfig, project_root: Path) -> dict[str, MomentInfo]:
    rows = read_csv_required(config.input_moments, project_root, "story-builder")
    moments: dict[str, MomentInfo] = {}
    for row in rows:
        moment_id = row.get("moment_id", "")
        if not moment_id:
            continue
        moments[moment_id] = MomentInfo(
            moment_id=moment_id,
            media_set=row.get("media_set", "default"),
            moment_type=row.get("moment_type", "other"),
            title=row.get("title", moment_id),
            start_time=row.get("start_time", ""),
            album_score=safe_float(row.get("album_score"), 50),
            photo_count=int(safe_float(row.get("photo_count"), 0)),
            hero_photo=row.get("hero_photo", ""),
        )
    return moments


def load_quality_by_path(config: AlbumConfig, project_root: Path) -> dict[str, dict[str, str]]:
    rows = read_csv_required(config.input_quality_manifest, project_root, "quality-scoring")
    return {row.get("media_path", ""): row for row in rows if row.get("media_path")}


def load_previous_candidate_analysis(config: AlbumConfig) -> dict[str, dict[str, str]]:
    previous_path = config.output_dir / "album_candidates.csv"
    if not previous_path.exists():
        return {}
    try:
        with previous_path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
    except Exception:  # noqa: BLE001 - cache reuse is opportunistic.
        return {}
    analysis: dict[str, dict[str, str]] = {}
    for row in rows:
        media_path = row.get("media_path", "")
        if media_path and media_path not in analysis:
            analysis[media_path] = row
    return analysis


def analyze_faces(source_path: Path, config: AlbumConfig) -> FaceAnalysis:
    if config.face_detection_backend == "opencv_yunet":
        return analyze_faces_yunet(source_path, config.face_detection_model, config.face_score_threshold, config.face_edge_margin_ratio)
    if config.face_detection_backend != "opencv_haar":
        raise ValueError(f"Unsupported album face detection backend: {config.face_detection_backend}")
    return analyze_faces_haar(source_path, config.face_edge_margin_ratio)


def analyze_faces_yunet(source_path: Path, model_path: Path, score_threshold: float, edge_margin_ratio: float) -> FaceAnalysis:
    if not model_path.exists():
        raise FileNotFoundError(f"Album face detection model is missing: {model_path}")
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Album Builder face filtering requires opencv-python and numpy. Install requirements and rerun album-builder.") from exc
    if hasattr(cv2, "setLogLevel"):
        cv2.setLogLevel(0)

    image = decode_album_image(source_path)
    if image is None:
        return FaceAnalysis(0, 0)
    image.thumbnail((1600, 1600))
    rgb = np.array(image)
    height, width = rgb.shape[:2]
    if width <= 0 or height <= 0:
        return FaceAnalysis(0, 0)
    detector = cv2.FaceDetectorYN_create(str(model_path), "", (width, height), score_threshold, 0.30, 5000)
    _, faces = detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if faces is None:
        return FaceAnalysis(0, 0)
    boxes = [(int(face[0]), int(face[1]), int(face[2]), int(face[3])) for face in faces]
    return FaceAnalysis(len(boxes), count_cutoff_faces(boxes, width, height, edge_margin_ratio))


def analyze_faces_haar(source_path: Path, edge_margin_ratio: float) -> FaceAnalysis:
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Album Builder face filtering requires opencv-python and numpy. Install requirements and rerun album-builder.") from exc
    if hasattr(cv2, "setLogLevel"):
        cv2.setLogLevel(0)
    if not hasattr(cv2, "CascadeClassifier"):
        raise RuntimeError("The installed OpenCV build does not provide CascadeClassifier. Use the opencv_yunet backend.")

    image = decode_album_image(source_path)
    if image is None:
        return FaceAnalysis(0, 0)
    image_width, image_height = image.size
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    cascade_dir = Path(cv2.data.haarcascades)
    cascades = [
        cascade_dir / "haarcascade_frontalface_default.xml",
        cascade_dir / "haarcascade_frontalface_alt2.xml",
        cascade_dir / "haarcascade_profileface.xml",
    ]
    face_boxes: list[tuple[int, int, int, int]] = []
    for cascade_path in cascades:
        detector = cv2.CascadeClassifier(str(cascade_path))
        if detector.empty():
            continue
        detected = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=4, minSize=(24, 24))
        for x, y, width, height in detected:
            face_boxes.append((int(x), int(y), int(width), int(height)))
    unique = dedupe_face_boxes(face_boxes)
    return FaceAnalysis(len(unique), count_cutoff_faces(unique, image_width, image_height, edge_margin_ratio))


def count_cutoff_faces(boxes: list[tuple[int, int, int, int]], image_width: int, image_height: int, edge_margin_ratio: float) -> int:
    margin_x = max(2, int(image_width * edge_margin_ratio))
    margin_y = max(2, int(image_height * edge_margin_ratio))
    cutoff = 0
    for x, y, width, height in boxes:
        if x <= margin_x or y <= margin_y or x + width >= image_width - margin_x or y + height >= image_height - margin_y:
            cutoff += 1
    return cutoff


def dedupe_face_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    unique: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda item: item[2] * item[3], reverse=True):
        if all(face_overlap_ratio(box, existing) < 0.35 for existing in unique):
            unique.append(box)
    return unique


def face_overlap_ratio(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    left_x, left_y, left_w, left_h = left
    right_x, right_y, right_w, right_h = right
    x1 = max(left_x, right_x)
    y1 = max(left_y, right_y)
    x2 = min(left_x + left_w, right_x + right_w)
    y2 = min(left_y + left_h, right_y + right_h)
    overlap = max(0, x2 - x1) * max(0, y2 - y1)
    if not overlap:
        return 0.0
    smaller_area = min(left_w * left_h, right_w * right_h)
    return overlap / smaller_area if smaller_area else 0.0


def people_score_from_faces(face_count: int) -> float:
    if face_count <= 0:
        return 0.0
    if face_count == 1:
        return 72.0
    if face_count == 2:
        return 84.0
    return min(100.0, 88.0 + face_count * 3.0)


def image_dhash(source_path: Path, hash_size: int) -> str:
    image = decode_album_image(source_path)
    if image is None:
        return ""
    try:
        from PIL import Image

        resampling = Image.Resampling.LANCZOS
    except Exception:  # noqa: BLE001 - Pillow compatibility fallback.
        resampling = 1
    grayscale = image.convert("L").resize((hash_size + 1, hash_size), resampling)
    pixels = list(grayscale.getdata())
    bits: list[str] = []
    for row in range(hash_size):
        offset = row * (hash_size + 1)
        for col in range(hash_size):
            bits.append("1" if pixels[offset + col] > pixels[offset + col + 1] else "0")
    return f"{int(''.join(bits), 2):0{hash_size * hash_size // 4}x}"


def imagehash_fingerprints(source_path: Path) -> tuple[str, str, str, str]:
    image = decode_album_image(source_path)
    if image is None:
        return ("", "", "", "")
    try:
        import imagehash  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional stronger similarity backend.
        return ("", "", "", "")
    try:
        return (
            str(imagehash.phash(image)),
            str(imagehash.whash(image)),
            str(imagehash.average_hash(image)),
            str(imagehash.colorhash(image)),
        )
    except Exception:  # noqa: BLE001 - failed hashes fall back to dHash.
        return ("", "", "", "")


def hamming_distance_hex(left: str, right: str) -> int:
    if not left or not right:
        return 10**9
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 10**9


def perceptual_hash_distances(left: tuple[str, str, str, str], right: tuple[str, str, str, str]) -> tuple[int, int, int, int]:
    if not all(left) or not all(right):
        return (10**9, 10**9, 10**9, 10**9)
    distances = tuple(hamming_distance_hex(left[index], right[index]) for index in range(4))
    return distances  # type: ignore[return-value]


def captured_timestamp(value: str) -> float | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def is_visually_similar_to_selected(config: AlbumConfig, candidate: PhotoCandidate, selected: list[PhotoCandidate]) -> bool:
    if not config.similarity_filter_enabled or not candidate.visual_hash:
        return False
    candidate_time = captured_timestamp(candidate.captured_at)
    for existing in selected:
        if existing.media_set != candidate.media_set or not existing.visual_hash:
            continue
        distance = hamming_distance_hex(candidate.visual_hash, existing.visual_hash)
        if distance <= config.similarity_duplicate_distance:
            return True
        existing_time = captured_timestamp(existing.captured_at)
        close_in_time = candidate_time is not None and existing_time is not None and abs(candidate_time - existing_time) <= config.similarity_burst_window_seconds
        same_moment = candidate.moment_id and candidate.moment_id == existing.moment_id
        if distance <= config.similarity_burst_distance and close_in_time:
            return True
        if config.similarity_imagehash_enabled and close_in_time:
            phash, whash, average_hash, color_hash = perceptual_hash_distances(candidate.perceptual_hashes, existing.perceptual_hashes)
            if whash <= config.similarity_imagehash_distance and average_hash <= config.similarity_imagehash_distance:
                return True
            if phash <= config.similarity_imagehash_distance and color_hash <= 2:
                return True
    return False


def build_candidates(config: AlbumConfig, project_root: Path) -> list[PhotoCandidate]:
    read_csv_required(config.input_story_manifest, project_root, "story-builder")
    asset_rows = read_csv_required(config.input_moment_assets, project_root, "story-builder")
    moments = load_moments(config, project_root)
    quality_by_path = load_quality_by_path(config, project_root)
    previous_analysis = load_previous_candidate_analysis(config)

    candidates: list[PhotoCandidate] = []
    seen: set[str] = set()
    for row in asset_rows:
        media_path = row.get("media_path", "")
        file_type = row.get("file_type", "")
        if not media_path or media_path in seen or not is_photo_path(media_path, file_type):
            continue
        seen.add(media_path)
        source_path = resolve_project_path(project_root, media_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Album candidate media file is missing: {source_path}")

        moment_id = row.get("moment_id", "")
        moment = moments.get(moment_id, MomentInfo(moment_id, row.get("media_set", "default"), "other", moment_id, "", 50, 0, ""))
        quality_row = quality_by_path.get(media_path, {})
        base_quality = safe_float(row.get("quality_score") or quality_row.get("quality_score"), 50)
        album_score = safe_float(row.get("album_score") or quality_row.get("album_score"), base_quality)
        technical_quality = album_score * 0.70 + base_quality * 0.30
        memory_score = score_memory(row=row, moment=moment, media_path=media_path)
        story_score = score_story(moment=moment, config=config)
        cached_analysis = previous_analysis.get(media_path, {})
        if config.require_faces and cached_analysis.get("face_count") not in {None, ""}:
            face_analysis = FaceAnalysis(int(safe_float(cached_analysis.get("face_count"), 0)), int(safe_float(cached_analysis.get("face_cutoff_count"), 0)))
        else:
            face_analysis = analyze_faces(source_path, config) if config.require_faces else FaceAnalysis(0, 0)
        people_score = people_score_from_faces(face_analysis.count) if config.require_faces else 50.0
        diversity_score = score_diversity_seed(row=row, moment=moment)
        visual_hash = cached_analysis.get("visual_hash", "") if config.similarity_filter_enabled else ""
        if config.similarity_filter_enabled and not visual_hash:
            visual_hash = image_dhash(source_path, config.similarity_hash_size)
        perceptual_hashes = imagehash_fingerprints(source_path) if config.similarity_filter_enabled and config.similarity_imagehash_enabled else ("", "", "", "")
        final_score = (
            technical_quality * config.quality_weight
            + memory_score * config.memory_weight
            + story_score * config.story_weight
            + people_score * config.people_weight
            + diversity_score * config.diversity_weight
        )
        role = role_from_asset(row.get("role", ""), moment.moment_type, media_path)
        exclusion_reason = ""
        if config.require_faces and face_analysis.count < config.min_faces:
            exclusion_reason = f"no face detected; requires at least {config.min_faces}"
        elif config.exclude_cutoff_faces and face_analysis.cutoff_count > 0:
            exclusion_reason = f"detected {face_analysis.cutoff_count} face(s) too close to image edge"
        media_set = row.get("media_set", moment.media_set)
        candidates.append(
            PhotoCandidate(
                media_set=media_set,
                activity=activity_name_for(config, media_set),
                moment_id=moment_id,
                moment_title=activity_name_for(config, media_set),
                moment_type=moment.moment_type,
                media_path=media_path,
                original_path=quality_row.get("original_path", row.get("original_path", media_path)),
                file_type=file_type or quality_row.get("file_type", ""),
                captured_at=row.get("captured_at", moment.start_time),
                width=safe_int_text(quality_row.get("width")),
                height=safe_int_text(quality_row.get("height")),
                quality_score=round(technical_quality, 2),
                memory_score=round(memory_score, 2),
                story_score=round(story_score, 2),
                people_score=round(people_score, 2),
                face_count=face_analysis.count,
                face_cutoff_count=face_analysis.cutoff_count,
                visual_hash=visual_hash,
                perceptual_hashes=perceptual_hashes,
                diversity_score=round(diversity_score, 2),
                final_album_score=round(final_score, 2),
                candidate_role=role,
                exclusion_reason=exclusion_reason,
            )
        )
    return sorted(candidates, key=lambda candidate: (config.activity_order.get(candidate.media_set, 9999), candidate.captured_at, candidate.media_path))


def score_memory(row: dict[str, str], moment: MomentInfo, media_path: str) -> float:
    score = 50.0
    if row.get("role") == "hero_photo" or media_path == moment.hero_photo:
        score += 25
    if moment.moment_type in {"splash", "group_photo", "rapids", "launch", "meal"}:
        score += 12
    if moment.moment_type in {"safety_briefing", "gear_up", "arrival"}:
        score += 6
    return min(score, 100.0)


def score_story(moment: MomentInfo, config: AlbumConfig) -> float:
    score = 50.0 + min(max(moment.album_score - 50, 0), 25)
    if moment.moment_type in config.important_moment_types:
        score += 18
    if moment.photo_count:
        score += min(moment.photo_count, 5)
    return min(score, 100.0)


def score_diversity_seed(row: dict[str, str], moment: MomentInfo) -> float:
    score = 70.0
    if row.get("role") == "hero_photo":
        score += 5
    if moment.photo_count <= 2:
        score += 10
    elif moment.photo_count > 6:
        score -= min((moment.photo_count - 6) * 3, 18)
    return max(35.0, min(score, 100.0))


def export_path_for(config: AlbumConfig, project_root: Path, candidate: PhotoCandidate, album_size: str, sequence: int) -> Path:
    return pdf_album_path(config, album_size)


def pdf_album_path(config: AlbumConfig, album_size: str) -> Path:
    album_name = config.trip_slug if config.album_scope == "trip" else "album"
    return config.exports_dir / f"{album_name}_{album_size}_album.pdf"


def variant_score(candidate: PhotoCandidate, strategy: str) -> float:
    if strategy == "people_memory":
        role_bonus = 10.0 if candidate.candidate_role in {"group", "hero", "candid"} else 0.0
        return candidate.people_score * 0.36 + candidate.memory_score * 0.34 + candidate.story_score * 0.12 + candidate.quality_score * 0.10 + candidate.diversity_score * 0.08 + role_bonus
    if strategy == "visual_story":
        return candidate.story_score * 0.32 + candidate.memory_score * 0.26 + candidate.quality_score * 0.22 + candidate.diversity_score * 0.12 + candidate.people_score * 0.08
    return candidate.final_album_score


def ordered_candidates_for_variant(config: AlbumConfig, candidates: list[PhotoCandidate], size: AlbumSizeConfig) -> list[PhotoCandidate]:
    if size.strategy == "people_memory":
        return sorted(
            candidates,
            key=lambda item: (
                -variant_score(item, size.strategy),
                config.activity_order.get(item.media_set, 9999),
                item.captured_at,
                item.media_path,
            ),
        )
    if size.strategy == "visual_story":
        return sorted(
            candidates,
            key=lambda item: (
                config.activity_order.get(item.media_set, 9999),
                item.captured_at,
                -variant_score(item, size.strategy),
                item.media_path,
            ),
        )
    return sorted(
        candidates,
        key=lambda item: (
            config.activity_order.get(item.media_set, 9999),
            item.captured_at,
            item.media_path,
        ),
    )


def select_album_size(
    config: AlbumConfig,
    project_root: Path,
    candidates: list[PhotoCandidate],
    size: AlbumSizeConfig,
    excluded_paths: set[str] | None = None,
) -> list[SelectedPhoto]:
    eligible_candidates = [candidate for candidate in candidates if not candidate.exclusion_reason]
    if not eligible_candidates:
        return []
    excluded_paths = excluded_paths or set()
    allowed_overlap = int(size.max_photos * size.overlap_limit_fraction) if size.max_photos < 10000 else int(len(eligible_candidates) * size.overlap_limit_fraction)
    if size.include_all_good:
        ordered_all = ordered_candidates_for_variant(config, eligible_candidates, size)
        selected: list[PhotoCandidate] = []
        selected_paths: set[str] = set()
        overlap_count = 0
        for candidate in ordered_all:
            if len(selected) >= size.max_photos:
                break
            if candidate.media_path in selected_paths:
                continue
            if candidate.media_path in excluded_paths and overlap_count >= allowed_overlap:
                continue
            if is_visually_similar_to_selected(config, candidate, selected):
                continue
            selected.append(candidate)
            selected_paths.add(candidate.media_path)
            if candidate.media_path in excluded_paths:
                overlap_count += 1
        if len(selected) < size.min_photos and excluded_paths:
            for candidate in ordered_all:
                if len(selected) >= min(size.min_photos, len(eligible_candidates), size.max_photos):
                    break
                if candidate.media_path in selected_paths:
                    continue
                if candidate.media_path in excluded_paths and overlap_count >= allowed_overlap:
                    continue
                if is_visually_similar_to_selected(config, candidate, selected):
                    continue
                selected.append(candidate)
                selected_paths.add(candidate.media_path)
                if candidate.media_path in excluded_paths:
                    overlap_count += 1
        return [
            SelectedPhoto(
                candidate=candidate,
                album_size=size.name,
                sequence=index,
                export_path=export_path_for(config, project_root, candidate, size.name, index),
                selection_reason=selection_reason(candidate),
            )
            for index, candidate in enumerate(order_selected_for_output(config, selected, size), start=1)
        ]

    selected: list[PhotoCandidate] = []
    selected_paths: set[str] = set()
    moment_counts: dict[str, int] = {}
    minute_counts: dict[str, int] = {}
    max_fraction_count = max(1, int(size.max_photos * config.max_same_moment_fraction))
    max_per_moment = max(1, min(size.max_per_moment, max_fraction_count))

    important_ids = sorted({candidate.moment_id for candidate in eligible_candidates if candidate.moment_type in config.important_moment_types})
    for moment_id in important_ids:
        moment_candidates = [candidate for candidate in eligible_candidates if candidate.moment_id == moment_id]
        for candidate in sorted(moment_candidates, key=lambda item: (-item.final_album_score, item.media_path))[: size.min_per_important_moment]:
            add_candidate(candidate, selected, selected_paths, moment_counts, minute_counts, max_per_moment, config)

    for candidate in sorted(eligible_candidates, key=lambda item: (-variant_score(item, size.strategy), item.captured_at, item.media_path)):
        if len(selected) >= size.target_photos:
            break
        if candidate.media_path in excluded_paths:
            continue
        add_candidate(candidate, selected, selected_paths, moment_counts, minute_counts, max_per_moment, config)

    if len(selected) < size.min_photos:
        for candidate in sorted(eligible_candidates, key=lambda item: (-item.final_album_score, item.captured_at, item.media_path)):
            if len(selected) >= min(size.min_photos, len(eligible_candidates)):
                break
            if candidate.media_path in selected_paths:
                continue
            if candidate.media_path in excluded_paths and len(selected) >= size.min_photos:
                continue
            if is_visually_similar_to_selected(config, candidate, selected):
                continue
            selected.append(candidate)
            selected_paths.add(candidate.media_path)

    ordered = order_selected_for_output(config, selected, size)[: size.max_photos]
    return [
        SelectedPhoto(
            candidate=candidate,
            album_size=size.name,
            sequence=index,
            export_path=export_path_for(config, project_root, candidate, size.name, index),
            selection_reason=selection_reason(candidate),
        )
        for index, candidate in enumerate(ordered, start=1)
    ]


def order_selected_for_output(config: AlbumConfig, selected: list[PhotoCandidate], size: AlbumSizeConfig) -> list[PhotoCandidate]:
    return sorted(
        selected,
        key=lambda item: (
            config.activity_order.get(item.media_set, 9999),
            item.captured_at,
            item.moment_id,
            -variant_score(item, size.strategy),
            item.media_path,
        ),
    )


def add_candidate(
    candidate: PhotoCandidate,
    selected: list[PhotoCandidate],
    selected_paths: set[str],
    moment_counts: dict[str, int],
    minute_counts: dict[str, int],
    max_per_moment: int,
    config: AlbumConfig,
) -> bool:
    if candidate.media_path in selected_paths:
        return False
    if is_visually_similar_to_selected(config, candidate, selected):
        return False
    if moment_counts.get(candidate.moment_id, 0) >= max_per_moment:
        return False
    minute = minute_key(candidate.captured_at)
    if minute and minute_counts.get(minute, 0) >= config.max_same_minute_per_album:
        return False
    selected.append(candidate)
    selected_paths.add(candidate.media_path)
    moment_counts[candidate.moment_id] = moment_counts.get(candidate.moment_id, 0) + 1
    if minute:
        minute_counts[minute] = minute_counts.get(minute, 0) + 1
    return True


def selection_reason(candidate: PhotoCandidate) -> str:
    reasons = [f"final score {candidate.final_album_score}"]
    if candidate.candidate_role in {"hero", "action", "group"}:
        reasons.append(f"{candidate.candidate_role} candidate")
    if candidate.memory_score >= 75:
        reasons.append("strong memory/story value")
    if candidate.quality_score >= 75:
        reasons.append("strong technical album score")
    return "; ".join(reasons)


def candidate_row(candidate: PhotoCandidate, album_size: str, selected_paths: set[str]) -> dict[str, object]:
    selected = candidate.media_path in selected_paths
    return {
        "media_set": candidate.media_set,
        "activity": candidate.activity,
        "album_size": album_size,
        "moment_id": candidate.moment_id,
        "moment_title": candidate.moment_title,
        "moment_type": candidate.moment_type,
        "media_path": candidate.media_path,
        "original_path": candidate.original_path,
        "file_type": candidate.file_type,
        "width": candidate.width,
        "height": candidate.height,
        "quality_score": candidate.quality_score,
        "memory_score": candidate.memory_score,
        "story_score": candidate.story_score,
        "people_score": candidate.people_score,
        "face_count": candidate.face_count,
        "face_cutoff_count": candidate.face_cutoff_count,
        "visual_hash": candidate.visual_hash,
        "diversity_score": candidate.diversity_score,
        "final_album_score": candidate.final_album_score,
        "candidate_role": candidate.candidate_role,
        "selection_status": "selected" if selected else "not_selected",
        "selection_reason": selection_reason(candidate) if selected else "",
        "exclusion_reason": "" if selected else candidate.exclusion_reason or "lower ranked or constrained by moment/minute/visual diversity",
    }


def selection_row(selected: SelectedPhoto, project_root: Path) -> dict[str, object]:
    candidate = selected.candidate
    return {
        "media_set": candidate.media_set,
        "activity": candidate.activity,
        "album_size": selected.album_size,
        "album_sequence": selected.sequence,
        "moment_id": candidate.moment_id,
        "moment_title": candidate.moment_title,
        "moment_type": candidate.moment_type,
        "media_path": candidate.media_path,
        "export_path": path_text(selected.export_path, project_root),
        "original_path": candidate.original_path,
        "candidate_role": candidate.candidate_role,
        "final_album_score": candidate.final_album_score,
        "selection_reason": selected.selection_reason,
    }


def manifest_row(selected: SelectedPhoto, project_root: Path) -> dict[str, object]:
    candidate = selected.candidate
    return {
        "media_set": candidate.media_set,
        "activity": candidate.activity,
        "album_size": selected.album_size,
        "album_sequence": selected.sequence,
        "moment_id": candidate.moment_id,
        "moment_title": candidate.moment_title,
        "media_path": candidate.media_path,
        "export_path": path_text(selected.export_path, project_root),
        "original_path": candidate.original_path,
        "file_type": candidate.file_type,
        "width": candidate.width,
        "height": candidate.height,
        "final_album_score": candidate.final_album_score,
        "candidate_role": candidate.candidate_role,
        "source_phase": "album_builder",
    }


def files_are_identical(left: Path, right: Path) -> bool:
    if not left.exists() or not right.exists() or left.stat().st_size != right.stat().st_size:
        return False
    return sha256_file(left) == sha256_file(right)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_selected(config: AlbumConfig, project_root: Path, selected: list[SelectedPhoto]) -> int:
    copied = 0
    for item in selected:
        source = resolve_project_path(project_root, item.candidate.media_path)
        if not source.exists():
            raise FileNotFoundError(f"Album export source is missing: {source}")
        destination = item.export_path
        if destination.exists():
            if files_are_identical(source, destination):
                continue
            if config.overwrite_policy == "fail":
                raise FileExistsError(f"Album export already exists and differs: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


def decode_album_image(path: Path):
    try:
        from PIL import Image, ImageOps

        try:
            from pillow_heif import register_heif_opener  # type: ignore[import-not-found]

            register_heif_opener()
        except Exception:  # noqa: BLE001 - HEIC support is optional.
            pass

        with Image.open(path) as image:
            return ImageOps.exif_transpose(image).convert("RGB")
    except Exception:  # noqa: BLE001 - failed images are skipped by the PDF renderer.
        return None


def face_orientation_score(image, config: AlbumConfig) -> FaceOrientationScore:
    if config.face_detection_backend != "opencv_yunet" or not config.face_detection_model.exists():
        return FaceOrientationScore(0, 0, 0.0)
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - orientation correction is optional.
        return FaceOrientationScore(0, 0, 0.0)
    if hasattr(cv2, "setLogLevel"):
        cv2.setLogLevel(0)
    working = image.copy()
    working.thumbnail((1200, 1200))
    rgb = np.array(working)
    height, width = rgb.shape[:2]
    if width <= 0 or height <= 0:
        return FaceOrientationScore(0, 0, 0.0)
    detector = cv2.FaceDetectorYN_create(str(config.face_detection_model), "", (width, height), config.face_score_threshold, 0.30, 5000)
    _, faces = detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if faces is None:
        return FaceOrientationScore(0, 0, 0.0)
    boxes = [(int(face[0]), int(face[1]), int(face[2]), int(face[3])) for face in faces]
    confidences = [float(face[-1]) for face in faces]
    cutoff_count = count_cutoff_faces(boxes, width, height, config.face_edge_margin_ratio)
    face_area_score = sum((box_width * box_height) / max(1, width * height) for _, _, box_width, box_height in boxes) * 100.0
    max_confidence = max(confidences) if confidences else 0.0
    score = max_confidence * 1000.0 + sum(confidences) * 10.0 + face_area_score - cutoff_count * 35.0
    return FaceOrientationScore(len(boxes), cutoff_count, score)


def prepare_album_render_image(config: AlbumConfig, source_path: Path, *, allow_face_rotation: bool = True):
    image = decode_album_image(source_path)
    if image is None or not config.orientation_correction_enabled or not allow_face_rotation:
        return image
    if image.width <= image.height:
        return image
    cache_key = source_path.as_posix()
    cached_rotation = _ORIENTED_IMAGE_ROTATION_CACHE.get(cache_key)
    if cached_rotation is not None:
        return image.rotate(cached_rotation, expand=True) if cached_rotation else image

    rotations = [0, 90, 270, 180]
    scored: list[tuple[int, FaceOrientationScore]] = []
    for rotation in rotations:
        rotated = image.rotate(rotation, expand=True) if rotation else image
        scored.append((rotation, face_orientation_score(rotated, config)))
    original_score = scored[0][1].score
    best_rotation, best_score = max(scored, key=lambda item: (item[1].score, item[1].face_count, -item[1].cutoff_count))
    if best_rotation and best_score.score >= original_score + config.orientation_score_margin:
        _ORIENTED_IMAGE_ROTATION_CACHE[cache_key] = best_rotation
        return image.rotate(best_rotation, expand=True)
    _ORIENTED_IMAGE_ROTATION_CACHE[cache_key] = 0
    return image


def draw_image(canvas, image, box: tuple[float, float, float, float], mode: str = "cover") -> None:
    from reportlab.lib.utils import ImageReader

    x, y, width, height = box
    image_width, image_height = image.size
    if image_width <= 0 or image_height <= 0:
        return
    scale = max(width / image_width, height / image_height) if mode == "cover" else min(width / image_width, height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    draw_x = x + (width - draw_width) / 2
    draw_y = y + (height - draw_height) / 2
    render_image = image.copy()
    try:
        from PIL import Image

        resampling = Image.Resampling.LANCZOS
    except Exception:  # noqa: BLE001 - Pillow compatibility fallback.
        resampling = 1
    target_width = max(1, int(draw_width * 2))
    target_height = max(1, int(draw_height * 2))
    render_image.thumbnail((target_width, target_height), resampling)
    image_buffer = BytesIO()
    render_image.save(image_buffer, format="JPEG", quality=88, optimize=True)
    image_buffer.seek(0)
    canvas.saveState()
    path = canvas.beginPath()
    path.rect(x, y, width, height)
    canvas.clipPath(path, stroke=0, fill=0)
    canvas.drawImage(ImageReader(image_buffer), draw_x, draw_y, draw_width, draw_height)
    canvas.restoreState()


def selected_cover_photo(config: AlbumConfig, project_root: Path, selections: list[SelectedPhoto]) -> Path | None:
    if config.pdf_cover_photo and config.pdf_cover_photo != "auto":
        configured = resolve_project_path(project_root, config.pdf_cover_photo)
        if configured.exists():
            return configured
    if not selections:
        return None
    ranked = sorted(
        selections,
        key=lambda item: (
            item.candidate.candidate_role not in {"group", "hero"},
            -item.candidate.memory_score,
            -item.candidate.final_album_score,
            item.sequence,
        ),
    )
    return resolve_project_path(project_root, ranked[0].candidate.media_path)


def selected_closing_photo(config: AlbumConfig, project_root: Path, selections: list[SelectedPhoto]) -> Path | None:
    if config.pdf_closing_photo and config.pdf_closing_photo != "auto":
        configured = resolve_project_path(project_root, config.pdf_closing_photo)
        if configured.exists():
            return configured
    if not selections:
        return None
    ranked = sorted(
        selections,
        key=lambda item: (
            item.candidate.candidate_role not in {"group", "hero"},
            item.candidate.captured_at,
            -item.candidate.memory_score,
            -item.candidate.final_album_score,
        ),
        reverse=True,
    )
    return resolve_project_path(project_root, ranked[0].candidate.media_path)


def write_pdf_cover(canvas, config: AlbumConfig, project_root: Path, selections: list[SelectedPhoto], page_width: float, page_height: float) -> None:
    from reportlab.lib.colors import Color, HexColor

    canvas.setFillColor(HexColor("#efe5d2"))
    canvas.rect(0, 0, page_width, page_height, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#d8c29a"))
    canvas.rect(0, page_height * 0.72, page_width * 0.58, page_height * 0.28, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#c9eef0"))
    canvas.rect(page_width * 0.68, 0, page_width * 0.32, page_height * 0.23, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#f0c9aa"))
    canvas.rect(page_width * 0.45, page_height * 0.18, page_width * 0.48, page_height * 0.62, stroke=0, fill=1)
    canvas.setFillColor(Color(1, 1, 1, alpha=0.58))
    canvas.roundRect(page_width * 0.07, page_height * 0.13, page_width * 0.42, page_height * 0.66, 26, stroke=0, fill=1)

    cover = selected_cover_photo(config, project_root, selections)
    if cover:
        image = prepare_album_render_image(config, cover)
        if image:
            draw_image(canvas, image, (page_width * 0.09, page_height * 0.15, page_width * 0.38, page_height * 0.58), mode="cover")

    canvas.setFillColor(HexColor("#33281f"))
    title_lines = wrap_cover_title(config.pdf_title, max_chars=18, max_lines=4)
    font_size = 33 if any(len(line) > 14 for line in title_lines) else 38
    line_gap = font_size + 13
    y = page_height * 0.66
    for line in title_lines:
        canvas.setFont("Courier-Bold", font_size)
        canvas.drawCentredString(page_width * 0.66, y, line)
        y -= line_gap
    canvas.setFont("Helvetica-Oblique", 30)
    canvas.drawCentredString(page_width * 0.66, page_height * 0.26, config.pdf_subtitle)
    canvas.showPage()


def write_pdf_closing(canvas, config: AlbumConfig, project_root: Path, selections: list[SelectedPhoto], page_width: float, page_height: float, page_number: int) -> None:
    from reportlab.lib.colors import Color, HexColor

    canvas.setFillColor(HexColor("#fbf7ef"))
    canvas.rect(0, 0, page_width, page_height, stroke=0, fill=1)
    canvas.setFillColor(HexColor("#efe5d2"))
    canvas.rect(0, 0, page_width, page_height * 0.24, stroke=0, fill=1)
    closing = selected_closing_photo(config, project_root, selections)
    if closing:
        image = prepare_album_render_image(config, closing, allow_face_rotation=False)
        if image:
            box = (page_width * 0.10, page_height * 0.27, page_width * 0.80, page_height * 0.56)
            x, y, width, height = box
            canvas.setFillColor(Color(1, 1, 1, alpha=0.92))
            canvas.rect(x - 8, y - 8, width + 16, height + 16, stroke=0, fill=1)
            draw_image(canvas, image, box, mode="contain")

    canvas.setFillColor(HexColor("#33281f"))
    canvas.setFont("Helvetica-Bold", 28)
    canvas.drawCentredString(page_width / 2, page_height * 0.145, "until the next adventure")
    canvas.setFont("Helvetica-Oblique", 18)
    canvas.drawCentredString(page_width / 2, page_height * 0.095, config.pdf_subtitle)
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(HexColor("#777067"))
    canvas.drawRightString(page_width - 36, 24, str(page_number))
    canvas.showPage()


def wrap_cover_title(title: str, max_chars: int, max_lines: int) -> list[str]:
    words = [word.strip() for word in title.split() if word.strip()]
    if not words:
        return ["Adventure", "Begins", "Here"]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars and len(lines) < max_lines - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:max_lines]


def layout_boxes(page_width: float, page_height: float, count: int) -> list[tuple[float, float, float, float]]:
    margin = 36
    gutter = 16
    title_space = 42
    area_y = margin
    area_h = page_height - margin * 2 - title_space
    area_w = page_width - margin * 2
    if count <= 1:
        return [(margin, area_y, area_w, area_h)]
    if count == 2:
        box_w = (area_w - gutter) / 2
        return [(margin, area_y, box_w, area_h), (margin + box_w + gutter, area_y, box_w, area_h)]
    if count == 3:
        left_w = area_w * 0.58
        right_w = area_w - left_w - gutter
        right_h = (area_h - gutter) / 2
        return [
            (margin, area_y, left_w, area_h),
            (margin + left_w + gutter, area_y + right_h + gutter, right_w, right_h),
            (margin + left_w + gutter, area_y, right_w, right_h),
        ]
    box_w = (area_w - gutter) / 2
    box_h = (area_h - gutter) / 2
    return [
        (margin, area_y + box_h + gutter, box_w, box_h),
        (margin + box_w + gutter, area_y + box_h + gutter, box_w, box_h),
        (margin, area_y, box_w, box_h),
        (margin + box_w + gutter, area_y, box_w, box_h),
    ]


def image_draw_mode_for_box(image, box: tuple[float, float, float, float]) -> str:
    _, _, width, height = box
    image_width, image_height = image.size
    if image_height > image_width and width > height:
        return "contain"
    return "cover"


def grouped_album_pages(selections: list[SelectedPhoto]) -> list[list[SelectedPhoto]]:
    pages: list[list[SelectedPhoto]] = []
    current_activity = ""
    current_page: list[SelectedPhoto] = []
    for selection in selections:
        activity = selection.candidate.activity
        if current_page and (activity != current_activity or len(current_page) >= 4):
            pages.append(current_page)
            current_page = []
        current_activity = activity
        current_page.append(selection)
    if current_page:
        pages.append(current_page)
    return pages


def write_photo_page(canvas, config: AlbumConfig, project_root: Path, photos: list[SelectedPhoto], page_width: float, page_height: float, page_number: int) -> None:
    from reportlab.lib.colors import HexColor

    canvas.setFillColor(HexColor("#fbf7ef"))
    canvas.rect(0, 0, page_width, page_height, stroke=0, fill=1)
    title = photos[0].candidate.activity if photos else config.pdf_title
    canvas.setFillColor(HexColor("#2f2a24"))
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(36, page_height - 42, title)
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(HexColor("#777067"))
    canvas.drawRightString(page_width - 36, 24, str(page_number))
    for photo, box in zip(photos, layout_boxes(page_width, page_height, len(photos))):
        source = resolve_project_path(project_root, photo.candidate.media_path)
        image = prepare_album_render_image(config, source)
        if image is None:
            continue
        x, y, width, height = box
        canvas.setFillColor(HexColor("#ffffff"))
        canvas.rect(x - 4, y - 4, width + 8, height + 8, stroke=0, fill=1)
        draw_image(canvas, image, box, mode=image_draw_mode_for_box(image, box))
    canvas.showPage()


def write_album_pdf(config: AlbumConfig, project_root: Path, album_size: str, selections: list[SelectedPhoto]) -> Path | None:
    if not selections:
        return None
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("ReportLab is required for PDF album export. Install reportlab and rerun album-builder.") from exc

    output_path = pdf_album_path(config, album_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(str(output_path), pagesize=(page_width, page_height))
    write_pdf_cover(pdf, config, project_root, selections, page_width, page_height)
    page_number = 2
    for page_photos in grouped_album_pages(selections):
        write_photo_page(pdf, config, project_root, page_photos, page_width, page_height, page_number)
        page_number += 1
    write_pdf_closing(pdf, config, project_root, selections, page_width, page_height, page_number)
    pdf.save()
    return output_path


def write_album_pdfs(config: AlbumConfig, project_root: Path, selections_by_size: dict[str, list[SelectedPhoto]]) -> int:
    if not config.pdf_export_enabled:
        return 0
    generated = 0
    for size in config.sizes:
        if write_album_pdf(config, project_root, size.name, selections_by_size.get(size.name, [])):
            generated += 1
    return generated


def write_markdown_report(config: AlbumConfig, selections_by_size: dict[str, list[SelectedPhoto]], candidates: list[PhotoCandidate]) -> Path:
    report_path = config.output_dir / "album_report.md"
    lines = [
        "# Album Builder Report",
        "",
        f"Photo candidates: {len(candidates)}",
        "",
        "Selected photos remain at their original `input_data` paths. Album export paths point to final PDF artifacts.",
        "",
    ]
    for size in config.sizes:
        selections = selections_by_size.get(size.name, [])
        lines.extend(
            [
                f"## {size.name.title()} Album",
                "",
                f"- Selected photos: {len(selections)}",
                f"- Target range: {size.min_photos}-{size.max_photos} photos, target {size.target_photos}",
                f"- PDF output: {pdf_album_path(config, size.name).as_posix() if selections else ''}",
            ]
        )
        if len(selections) < size.min_photos:
            lines.append(f"- Shortage: selected {len(selections)}, below minimum {size.min_photos}")
        role_counts: dict[str, int] = {}
        activity_counts: dict[str, int] = {}
        for item in selections:
            role_counts[item.candidate.candidate_role] = role_counts.get(item.candidate.candidate_role, 0) + 1
            activity_counts[item.candidate.activity] = activity_counts.get(item.candidate.activity, 0) + 1
        lines.append(f"- Role mix: {', '.join(f'{role}: {count}' for role, count in sorted(role_counts.items())) or 'none'}")
        lines.extend(["", "### Activity Coverage", "", "| Activity | Photos |", "| --- | ---: |"])
        for activity, count in sorted(activity_counts.items()):
            lines.append(f"| {activity} | {count} |")
        lines.extend(["", "### Top Photos", ""])
        for item in sorted(selections, key=lambda value: value.candidate.final_album_score, reverse=True)[:10]:
            lines.append(f"- {item.sequence:03d}: {item.candidate.media_path} ({item.candidate.final_album_score})")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def write_reports(
    config: AlbumConfig,
    project_root: Path,
    candidates: list[PhotoCandidate],
    selections_by_size: dict[str, list[SelectedPhoto]],
) -> tuple[Path, Path, Path, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    candidates_csv = config.output_dir / "album_candidates.csv"
    selection_csv = config.output_dir / "album_selection.csv"
    manifest_csv = config.output_dir / "album_manifest.csv"

    with candidates_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ALBUM_CANDIDATE_COLUMNS)
        writer.writeheader()
        for size_name, selections in selections_by_size.items():
            selected_paths = {item.candidate.media_path for item in selections}
            for candidate in candidates:
                writer.writerow(candidate_row(candidate, size_name, selected_paths))

    with selection_csv.open("w", newline="", encoding="utf-8") as selection_file, manifest_csv.open("w", newline="", encoding="utf-8") as manifest_file:
        selection_writer = csv.DictWriter(selection_file, fieldnames=ALBUM_SELECTION_COLUMNS)
        manifest_writer = csv.DictWriter(manifest_file, fieldnames=ALBUM_MANIFEST_COLUMNS)
        selection_writer.writeheader()
        manifest_writer.writeheader()
        for size in config.sizes:
            for selected in selections_by_size.get(size.name, []):
                selection_writer.writerow(selection_row(selected, project_root))
                manifest_writer.writerow(manifest_row(selected, project_root))

    report_md = write_markdown_report(config, selections_by_size, candidates)
    return candidates_csv, selection_csv, manifest_csv, report_md


def run_album_builder(config: Config, project_root: Path, include_disabled: bool = False, execute: bool = False) -> AlbumResult:
    album_config = load_album_config(config, project_root)
    if execute:
        album_config = replace(album_config, dry_run=False)
    if not album_config.enabled and not include_disabled:
        raise ValueError("Album Builder is disabled in config. Enable modules.album_builder.enabled or pass --include-disabled.")

    candidates = build_candidates(album_config, project_root)
    selections_by_size: dict[str, list[SelectedPhoto]] = {}
    for size in album_config.sizes:
        excluded_paths: set[str] = set()
        for source_variant in size.exclude_from:
            excluded_paths.update(item.candidate.media_path for item in selections_by_size.get(source_variant, []))
        selections_by_size[size.name] = select_album_size(album_config, project_root, candidates, size, excluded_paths)
    all_selected = [item for selections in selections_by_size.values() for item in selections]
    copied_count = 0
    generated_pdf_count = 0
    if not album_config.dry_run:
        generated_pdf_count = write_album_pdfs(album_config, project_root, selections_by_size)

    candidates_csv, selection_csv, manifest_csv, report_md = write_reports(album_config, project_root, candidates, selections_by_size)
    return AlbumResult(
        candidate_count=len(candidates),
        variant_counts={name: len(selections) for name, selections in selections_by_size.items()},
        small_count=len(selections_by_size.get("small", [])),
        standard_count=len(selections_by_size.get("standard", [])),
        extended_count=len(selections_by_size.get("extended", [])),
        enhanced_count=len(selections_by_size.get("enhanced", [])),
        copied_count=copied_count,
        generated_pdf_count=generated_pdf_count,
        album_candidates_csv=candidates_csv,
        album_selection_csv=selection_csv,
        album_manifest_csv=manifest_csv,
        album_report_md=report_md,
        dry_run=album_config.dry_run,
    )
