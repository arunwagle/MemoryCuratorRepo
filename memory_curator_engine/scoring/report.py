"""Quality scoring reports for selected downstream media."""

from __future__ import annotations

import csv
import importlib.util
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.activity import ActivityProfile, load_activity_profile, purpose_scores
from memory_curator_engine.common.execution import ordered_map
from memory_curator_engine.common.media import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, MediaRecord
from memory_curator_engine.common.media_sets import media_set_activity_map
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import build_media_record, parse_enabled


QUALITY_SCORE_COLUMNS = [
    "media_set",
    "original_path",
    "selected_path",
    "file_type",
    "size_bytes",
    "width",
    "height",
    "duration_seconds",
    "quality_score",
    "album_score",
    "instagram_score",
    "movie_score",
    "activity_score",
    "album_purpose_score",
    "reel_purpose_score",
    "documentary_purpose_score",
    "time_capsule_purpose_score",
    "activity_profile",
    "technical_score",
    "sharpness_score",
    "exposure_score",
    "resolution_score",
    "stability_score",
    "video_motion_score",
    "selection_status",
    "selection_reason",
    "scoring_notes",
]

QUALITY_SELECTION_COLUMNS = [
    "media_set",
    "original_path",
    "selected_path",
    "file_type",
    "quality_score",
    "album_score",
    "instagram_score",
    "movie_score",
    "activity_score",
    "album_purpose_score",
    "reel_purpose_score",
    "documentary_purpose_score",
    "activity_profile",
    "selection_reason",
]

QUALITY_MANIFEST_COLUMNS = [
    "media_set",
    "media_path",
    "original_path",
    "file_type",
    "size_bytes",
    "width",
    "height",
    "duration_seconds",
    "quality_score",
    "album_score",
    "instagram_score",
    "movie_score",
    "activity_score",
    "album_purpose_score",
    "reel_purpose_score",
    "documentary_purpose_score",
    "time_capsule_purpose_score",
    "activity_profile",
    "recommended_uses",
    "source_phase",
]


@dataclass(frozen=True)
class QualityConfig:
    enabled: bool
    dry_run: bool
    input_manifest: Path
    output_dir: Path
    photo_min_score: float
    video_min_score: float
    album_min_score: float
    instagram_min_score: float
    movie_min_score: float
    top_percent_per_media_set: float
    min_selected_per_media_set: int
    max_selected_per_media_set: int
    min_video_duration_seconds: float
    movie_target_minutes_min: float
    movie_target_minutes_max: float
    video_sample_positions: list[float]
    preserve_all_videos: bool
    activity_profile: ActivityProfile
    media_set_profiles: dict[str, ActivityProfile]


@dataclass(frozen=True)
class ManifestItem:
    media_set: str
    path: Path


@dataclass(frozen=True)
class QualityScore:
    item: ManifestItem
    record: MediaRecord
    selected_path: Path
    quality_score: float
    album_score: float
    instagram_score: float
    movie_score: float
    activity_score: float
    album_purpose_score: float
    reel_purpose_score: float
    documentary_purpose_score: float
    time_capsule_purpose_score: float
    activity_profile_name: str
    activity_reason: str
    technical_score: float
    sharpness_score: float
    exposure_score: float
    resolution_score: float
    stability_score: float
    video_motion_score: float
    selected: bool = False
    selection_reason: str = ""
    scoring_notes: str = ""


@dataclass(frozen=True)
class QualityResult:
    scanned_count: int
    selected_count: int
    quality_scores_csv: Path
    quality_selection_csv: Path
    quality_manifest_csv: Path
    dry_run: bool


def optional_module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def load_quality_config(config: Config, project_root: Path) -> QualityConfig:
    output_dir = resolve_project_path(
        project_root,
        config_value(config, "quality_scoring.output_dir", "MemoryCurator/03 Quality Scoring"),
    )
    return QualityConfig(
        enabled=parse_enabled(config_value(config, "modules.quality_scoring.enabled", False), "quality_scoring"),
        dry_run=parse_enabled(config_value(config, "quality_scoring.dry_run", True), "quality_scoring.dry_run"),
        input_manifest=resolve_project_path(
            project_root,
            config_value(config, "quality_scoring.input_manifest", "MemoryCurator/02 Duplicate Detection/keeper_manifest.csv"),
        ),
        output_dir=output_dir,
        photo_min_score=float(config_value(config, "quality_scoring.photo_min_score", 65)),
        video_min_score=float(config_value(config, "quality_scoring.video_min_score", 60)),
        album_min_score=float(config_value(config, "quality_scoring.album_min_score", 70)),
        instagram_min_score=float(config_value(config, "quality_scoring.instagram_min_score", 68)),
        movie_min_score=float(config_value(config, "quality_scoring.movie_min_score", 62)),
        top_percent_per_media_set=float(config_value(config, "quality_scoring.top_percent_per_media_set", 40)),
        min_selected_per_media_set=int(config_value(config, "quality_scoring.min_selected_per_media_set", 20)),
        max_selected_per_media_set=int(config_value(config, "quality_scoring.max_selected_per_media_set", 250)),
        min_video_duration_seconds=float(config_value(config, "quality_scoring.min_video_duration_seconds", 2)),
        movie_target_minutes_min=float(config_value(config, "quality_scoring.movie_target_minutes_min", 30)),
        movie_target_minutes_max=float(config_value(config, "quality_scoring.movie_target_minutes_max", 60)),
        video_sample_positions=parse_float_list(config_value(config, "quality_scoring.video_sample_positions", [0.1, 0.5, 0.9])),
        preserve_all_videos=parse_enabled(
            config_value(config, "quality_scoring.preserve_all_videos", False),
            "quality_scoring.preserve_all_videos",
        ),
        activity_profile=load_activity_profile(
            config,
            str(config_value(config, "quality_scoring.activity_profile", config_value(config, "reel_builder.activity_profile", "default"))),
        ),
        media_set_profiles={
            name: load_activity_profile(config, activity.activity_profile)
            for name, activity in media_set_activity_map(config).items()
        },
    )


def parse_float_list(value: object) -> list[float]:
    if not isinstance(value, list):
        return [0.1, 0.5, 0.9]
    positions: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 1:
            positions.append(number)
    return positions or [0.1, 0.5, 0.9]


def media_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PHOTO_EXTENSIONS:
        return "photo"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, value))


def read_manifest(config: QualityConfig, project_root: Path) -> list[ManifestItem]:
    if not config.input_manifest.exists():
        raise FileNotFoundError(
            f"Missing upstream manifest: {config.input_manifest.relative_to(project_root).as_posix()}. "
            "Run inventory and duplicate-detection first."
        )

    with config.input_manifest.open(newline="", encoding="utf-8") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
    if not rows:
        raise ValueError(
            f"Upstream manifest is empty: {config.input_manifest.relative_to(project_root).as_posix()}. "
            "Run inventory and duplicate-detection first."
        )

    items: list[ManifestItem] = []
    for row in rows:
        media_path = row.get("keeper_path") or row.get("media_path")
        media_set = row.get("media_set") or "default"
        if not media_path:
            raise ValueError(f"Manifest row is missing keeper_path/media_path: {config.input_manifest}")
        path = resolve_project_path(project_root, media_path)
        if not path.exists():
            raise FileNotFoundError(f"Manifest media file is missing: {path}")
        items.append(ManifestItem(media_set=media_set, path=path))
    return items


def selected_path_for(item: ManifestItem) -> Path:
    return item.path


def resolution_score(record: MediaRecord) -> float:
    width = record.metadata.width or 0
    height = record.metadata.height or 0
    pixels = width * height
    if media_kind(record.path) == "video":
        return clamp((pixels / (1920 * 1080)) * 85 + 15)
    return clamp((pixels / (4000 * 3000)) * 85 + 15)


def orientation_tags(record: MediaRecord) -> set[str]:
    width = record.metadata.width or 0
    height = record.metadata.height or 0
    if width <= 0 or height <= 0:
        return set()
    ratio = width / height
    tags = set()
    if ratio < 0.8:
        tags.add("vertical")
    elif ratio > 1.4:
        tags.add("wide")
    else:
        tags.add("square_friendly")
    return tags


def decode_photo(path: Path):
    if not optional_module_available("PIL"):
        return None, "Pillow not installed"
    try:
        from PIL import Image

        if optional_module_available("pillow_heif"):
            from pillow_heif import register_heif_opener

            register_heif_opener()

        with Image.open(path) as image:
            return image.convert("RGB"), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"photo decode failed: {exc}"


def frame_scores_from_image(image: object) -> tuple[float, float, float, str]:
    if not optional_module_available("numpy"):
        return 50, 50, 50, "numpy not installed"
    try:
        import numpy as np

        gray = np.array(image.convert("L"))
        brightness = float(gray.mean())
        contrast = float(gray.std())
        dark_clip = float((gray <= 5).mean())
        bright_clip = float((gray >= 250).mean())
        exposure = clamp(100 - abs(brightness - 128) * 0.6 - (dark_clip + bright_clip) * 160)
        contrast_score = clamp(contrast * 2.2)
        sharpness = 50.0
        notes = ""
        if optional_module_available("cv2"):
            import cv2

            laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            sharpness = clamp((laplacian_variance / 650) * 100)
        else:
            notes = "opencv-python not installed; sharpness estimated from contrast"
            sharpness = contrast_score
        return sharpness, exposure, contrast_score, notes
    except Exception as exc:  # noqa: BLE001
        return 40, 40, 40, f"image scoring failed: {exc}"


def score_photo(record: MediaRecord) -> tuple[float, float, float, float, float, float, float, float, str]:
    image, decode_note = decode_photo(record.path)
    resolution = resolution_score(record)
    if image is None:
        technical = resolution * 0.45
        return technical, technical, technical, 0, 0, 35, resolution, 0, 0, decode_note

    sharpness, exposure, contrast, scoring_note = frame_scores_from_image(image)
    technical = clamp(resolution * 0.35 + sharpness * 0.35 + exposure * 0.2 + contrast * 0.1)
    tags = orientation_tags(record)
    album = clamp(technical + (8 if record.metadata.width and record.metadata.width >= 3000 else 0))
    instagram = clamp(technical + (8 if tags & {"vertical", "square_friendly"} else 0))
    movie = clamp(technical * 0.75 + (10 if "wide" in tags else 0))
    quality = clamp(technical * 0.7 + max(album, instagram, movie) * 0.3)
    notes = "; ".join(note for note in [decode_note, scoring_note] if note)
    return quality, album, instagram, movie, sharpness, exposure, resolution, 0, 0, notes


def sampled_video_frames(path: Path, sample_positions: list[float]):
    if not optional_module_available("cv2"):
        return [], "opencv-python not installed"
    try:
        import cv2
        from PIL import Image

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            return [], "OpenCV could not open video"

        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count <= 0:
            capture.release()
            return [], "OpenCV could not determine frame count"

        frames = []
        for position in sample_positions:
            frame_index = min(frame_count - 1, max(0, int(frame_count * position)))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(frame).convert("RGB"))
        capture.release()
        return frames, "" if frames else "OpenCV did not produce sample frames"
    except Exception as exc:  # noqa: BLE001
        return [], f"video frame sampling failed: {exc}"


def video_motion_score(frames: list[object]) -> tuple[float, float, str]:
    if len(frames) < 2 or not optional_module_available("numpy"):
        return 50, 50, "not enough sampled frames for motion/stability"
    try:
        import numpy as np

        diffs = []
        for left, right in zip(frames, frames[1:]):
            left_gray = np.array(left.convert("L").resize((96, 54)), dtype="float32")
            right_gray = np.array(right.convert("L").resize((96, 54)), dtype="float32")
            diffs.append(float(np.abs(left_gray - right_gray).mean()))
        avg_diff = mean(diffs)
        motion = clamp(avg_diff * 5)
        stability = clamp(100 - max(0, avg_diff - 10) * 4)
        return motion, stability, ""
    except Exception as exc:  # noqa: BLE001
        return 50, 50, f"motion scoring failed: {exc}"


def score_video(record: MediaRecord, config: QualityConfig) -> tuple[float, float, float, float, float, float, float, float, str]:
    resolution = resolution_score(record)
    frames, frame_note = sampled_video_frames(record.path, config.video_sample_positions)
    frame_metrics = [frame_scores_from_image(frame) for frame in frames]
    if frame_metrics:
        sharpness = mean(metric[0] for metric in frame_metrics)
        exposure = mean(metric[1] for metric in frame_metrics)
        contrast = mean(metric[2] for metric in frame_metrics)
        notes = [metric[3] for metric in frame_metrics if metric[3]]
    else:
        sharpness, exposure, contrast = 35, 40, 40
        notes = []

    motion, stability, motion_note = video_motion_score(frames)
    duration = record.metadata.duration_seconds or 0
    duration_score = clamp((duration / 20) * 100)
    if 0 < duration < config.min_video_duration_seconds:
        duration_score *= 0.5

    technical = clamp(resolution * 0.25 + sharpness * 0.25 + exposure * 0.2 + stability * 0.2 + contrast * 0.1)
    tags = orientation_tags(record)
    album = clamp(technical * 0.45 + resolution * 0.25)
    instagram = clamp(technical * 0.55 + motion * 0.25 + duration_score * 0.2 + (8 if "vertical" in tags else 0))
    movie = clamp(technical * 0.55 + stability * 0.2 + duration_score * 0.15 + motion * 0.1)
    quality = clamp(technical * 0.55 + max(instagram, movie) * 0.3 + duration_score * 0.15)
    scoring_notes = "; ".join(note for note in [frame_note, motion_note, *notes] if note)
    return quality, album, instagram, movie, sharpness, exposure, resolution, stability, motion, scoring_notes


def score_item(config: QualityConfig, project_root: Path, item: ManifestItem) -> QualityScore:
    record = build_media_record(path=item.path, project_root=project_root)
    selected_path = selected_path_for(item)
    kind = media_kind(record.path)
    activity_profile = config.media_set_profiles.get(item.media_set, config.activity_profile)
    if kind == "photo":
        quality, album, instagram, movie, sharpness, exposure, resolution, stability, motion, notes = score_photo(record)
    elif kind == "video":
        quality, album, instagram, movie, sharpness, exposure, resolution, stability, motion, notes = score_video(record, config)
    else:
        quality, album, instagram, movie, sharpness, exposure, resolution, stability, motion = (0, 0, 0, 0, 0, 0, 0, 0, 0)
        notes = "unsupported media type"
    technical = clamp(resolution * 0.35 + sharpness * 0.3 + exposure * 0.25 + stability * 0.1)
    purposes = purpose_scores(
        activity_profile,
        path=record.path,
        media_kind=kind,
        technical_score=technical,
        quality_score=quality,
        album_score=album,
        instagram_score=instagram,
        movie_score=movie,
        motion_score=motion,
        stability_score=stability,
        duration_seconds=record.metadata.duration_seconds or 0,
        text=f"{record.path.name} {record.file_type}",
    )
    activity_reason = str(purposes["activity_reason"])
    notes = "; ".join(note for note in [notes, activity_reason] if note)
    return QualityScore(
        item=item,
        record=record,
        selected_path=selected_path,
        quality_score=round(quality, 2),
        album_score=round(album, 2),
        instagram_score=round(instagram, 2),
        movie_score=round(movie, 2),
        activity_score=float(purposes["activity_score"]),
        album_purpose_score=float(purposes["album_purpose_score"]),
        reel_purpose_score=float(purposes["reel_purpose_score"]),
        documentary_purpose_score=float(purposes["documentary_purpose_score"]),
        time_capsule_purpose_score=float(purposes["time_capsule_purpose_score"]),
        activity_profile_name=activity_profile.name,
        activity_reason=activity_reason,
        technical_score=round(technical, 2),
        sharpness_score=round(sharpness, 2),
        exposure_score=round(exposure, 2),
        resolution_score=round(resolution, 2),
        stability_score=round(stability, 2),
        video_motion_score=round(motion, 2),
        scoring_notes=notes,
    )


def threshold_for(score: QualityScore, config: QualityConfig) -> float:
    if media_kind(score.record.path) == "video":
        return config.video_min_score
    return config.photo_min_score


def recommended_uses(score: QualityScore, config: QualityConfig) -> list[str]:
    uses = []
    if score.album_purpose_score >= config.album_min_score:
        uses.append("album")
    if score.reel_purpose_score >= config.instagram_min_score:
        uses.append("instagram")
    if score.documentary_purpose_score >= config.movie_min_score:
        uses.append("movie")
    if media_kind(score.record.path) == "video" and score.activity_score >= 60 and score.reel_purpose_score >= config.instagram_min_score * 0.95:
        uses.append("activity_reel")
    if score.time_capsule_purpose_score >= max(config.video_min_score, config.photo_min_score):
        uses.append("time_capsule")
    return uses


def select_scores(scores: list[QualityScore], config: QualityConfig) -> list[QualityScore]:
    selected_reasons: dict[str, str] = {}
    scores_by_set: dict[str, list[QualityScore]] = {}
    for score in scores:
        scores_by_set.setdefault(score.item.media_set, []).append(score)

    for media_scores in scores_by_set.values():
        ranked = sorted(
            media_scores,
            key=lambda item: (
                -max(item.quality_score, item.reel_purpose_score, item.documentary_purpose_score, item.time_capsule_purpose_score),
                item.record.relative_path,
            ),
        )
        top_count = round(len(ranked) * (config.top_percent_per_media_set / 100))
        target_count = min(config.max_selected_per_media_set, max(config.min_selected_per_media_set, top_count))
        threshold_selected = [
            score
            for score in ranked
            if score.quality_score >= threshold_for(score, config) or recommended_uses(score, config)
        ]
        for score in threshold_selected[: config.max_selected_per_media_set]:
            uses = recommended_uses(score, config)
            reason = "selected for " + ",".join(uses) if uses else "selected by quality threshold"
            selected_reasons[score.record.relative_path] = reason
        if config.preserve_all_videos:
            for score in media_scores:
                if media_kind(score.record.path) != "video":
                    continue
                selected_reasons.setdefault(score.record.relative_path, "selected to preserve source video for downstream timeline intelligence")
        for score in ranked[: max(0, target_count - len(threshold_selected))]:
            selected_reasons.setdefault(score.record.relative_path, "selected by media-set quota")

        movie_target_seconds = config.movie_target_minutes_min * 60
        selected_video_seconds = sum(
            score.record.metadata.duration_seconds or 0
            for score in media_scores
            if score.record.relative_path in selected_reasons and media_kind(score.record.path) == "video"
        )
        movie_ranked_videos = sorted(
            [score for score in media_scores if media_kind(score.record.path) == "video"],
            key=lambda item: (-item.documentary_purpose_score, -item.reel_purpose_score, -item.activity_score, item.record.relative_path),
        )
        for score in movie_ranked_videos:
            if selected_video_seconds >= movie_target_seconds or len(selected_reasons) >= config.max_selected_per_media_set:
                break
            if score.record.relative_path in selected_reasons:
                continue
            if score.documentary_purpose_score < config.movie_min_score * 0.70 and score.reel_purpose_score < config.instagram_min_score * 0.70:
                continue
            selected_reasons[score.record.relative_path] = "selected to preserve activity video runtime"
            selected_video_seconds += score.record.metadata.duration_seconds or 0

    selected: list[QualityScore] = []
    for score in scores:
        uses = recommended_uses(score, config)
        is_selected = score.record.relative_path in selected_reasons
        reason = selected_reasons.get(score.record.relative_path, "")
        if not is_selected:
            reason = "below configured quality and purpose thresholds"
        selected.append(replace(score, selected=is_selected, selection_reason=reason))
    return selected


def path_text(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def score_row(score: QualityScore, project_root: Path) -> dict[str, object]:
    metadata = score.record.metadata
    return {
        "media_set": score.item.media_set,
        "original_path": score.record.relative_path,
        "selected_path": path_text(score.selected_path, project_root),
        "file_type": score.record.file_type,
        "size_bytes": score.record.size_bytes,
        "width": metadata.width or "",
        "height": metadata.height or "",
        "duration_seconds": metadata.duration_seconds if metadata.duration_seconds is not None else "",
        "quality_score": score.quality_score,
        "album_score": score.album_score,
        "instagram_score": score.instagram_score,
        "movie_score": score.movie_score,
        "activity_score": score.activity_score,
        "album_purpose_score": score.album_purpose_score,
        "reel_purpose_score": score.reel_purpose_score,
        "documentary_purpose_score": score.documentary_purpose_score,
        "time_capsule_purpose_score": score.time_capsule_purpose_score,
        "activity_profile": score.activity_profile_name,
        "technical_score": score.technical_score,
        "sharpness_score": score.sharpness_score,
        "exposure_score": score.exposure_score,
        "resolution_score": score.resolution_score,
        "stability_score": score.stability_score,
        "video_motion_score": score.video_motion_score,
        "selection_status": "selected" if score.selected else "not_selected",
        "selection_reason": score.selection_reason,
        "scoring_notes": score.scoring_notes,
    }


def selection_row(score: QualityScore, selected_path: Path, project_root: Path) -> dict[str, object]:
    return {
        "media_set": score.item.media_set,
        "original_path": score.record.relative_path,
        "selected_path": path_text(selected_path, project_root),
        "file_type": score.record.file_type,
        "quality_score": score.quality_score,
        "album_score": score.album_score,
        "instagram_score": score.instagram_score,
        "movie_score": score.movie_score,
        "activity_score": score.activity_score,
        "album_purpose_score": score.album_purpose_score,
        "reel_purpose_score": score.reel_purpose_score,
        "documentary_purpose_score": score.documentary_purpose_score,
        "activity_profile": score.activity_profile_name,
        "selection_reason": score.selection_reason,
    }


def manifest_row(score: QualityScore, media_path: Path, project_root: Path, config: QualityConfig) -> dict[str, object]:
    metadata = score.record.metadata
    return {
        "media_set": score.item.media_set,
        "media_path": path_text(media_path, project_root),
        "original_path": score.record.relative_path,
        "file_type": score.record.file_type,
        "size_bytes": score.record.size_bytes,
        "width": metadata.width or "",
        "height": metadata.height or "",
        "duration_seconds": metadata.duration_seconds if metadata.duration_seconds is not None else "",
        "quality_score": score.quality_score,
        "album_score": score.album_score,
        "instagram_score": score.instagram_score,
        "movie_score": score.movie_score,
        "activity_score": score.activity_score,
        "album_purpose_score": score.album_purpose_score,
        "reel_purpose_score": score.reel_purpose_score,
        "documentary_purpose_score": score.documentary_purpose_score,
        "time_capsule_purpose_score": score.time_capsule_purpose_score,
        "activity_profile": score.activity_profile_name,
        "recommended_uses": ",".join(recommended_uses(score, config)),
        "source_phase": "quality_scoring",
    }


def write_reports(config: QualityConfig, project_root: Path, scores: list[QualityScore]) -> QualityResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    quality_scores_csv = config.output_dir / "quality_scores.csv"
    quality_selection_csv = config.output_dir / "quality_selection.csv"
    quality_manifest_csv = config.output_dir / "quality_manifest.csv"

    selected_scores = [score for score in scores if score.selected]
    selected_paths = {score.record.relative_path: score.record.path for score in selected_scores}
    write_quality_csv_set(config, project_root, scores, selected_scores, selected_paths, quality_scores_csv, quality_selection_csv, quality_manifest_csv)
    write_quality_activity_reports(config, project_root, scores, selected_paths)

    return QualityResult(
        scanned_count=len(scores),
        selected_count=len(selected_scores),
        quality_scores_csv=quality_scores_csv,
        quality_selection_csv=quality_selection_csv,
        quality_manifest_csv=quality_manifest_csv,
        dry_run=config.dry_run,
    )


def write_quality_csv_set(
    config: QualityConfig,
    project_root: Path,
    scores: list[QualityScore],
    selected_scores: list[QualityScore],
    selected_paths: dict[str, Path],
    quality_scores_csv: Path,
    quality_selection_csv: Path,
    quality_manifest_csv: Path,
) -> None:
    quality_scores_csv.parent.mkdir(parents=True, exist_ok=True)
    with quality_scores_csv.open("w", newline="", encoding="utf-8") as scores_file:
        writer = csv.DictWriter(scores_file, fieldnames=QUALITY_SCORE_COLUMNS)
        writer.writeheader()
        for score in scores:
            writer.writerow(score_row(score, project_root))

    with quality_selection_csv.open("w", newline="", encoding="utf-8") as selection_file, quality_manifest_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as manifest_file:
        selection_writer = csv.DictWriter(selection_file, fieldnames=QUALITY_SELECTION_COLUMNS)
        manifest_writer = csv.DictWriter(manifest_file, fieldnames=QUALITY_MANIFEST_COLUMNS)
        selection_writer.writeheader()
        manifest_writer.writeheader()
        for score in selected_scores:
            media_path = selected_paths[score.record.relative_path]
            selection_writer.writerow(selection_row(score, media_path, project_root))
            manifest_writer.writerow(manifest_row(score, media_path, project_root, config))


def write_quality_activity_reports(
    config: QualityConfig,
    project_root: Path,
    scores: list[QualityScore],
    selected_paths: dict[str, Path],
) -> None:
    by_set: dict[str, list[QualityScore]] = {}
    for score in scores:
        by_set.setdefault(score.item.media_set, []).append(score)
    for media_set, media_scores in by_set.items():
        selected_scores = [score for score in media_scores if score.selected]
        activity_dir = config.output_dir / media_set
        write_quality_csv_set(
            config,
            project_root,
            media_scores,
            selected_scores,
            selected_paths,
            activity_dir / "quality_scores.csv",
            activity_dir / "quality_selection.csv",
            activity_dir / "quality_manifest.csv",
        )


def run_quality_scoring(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
) -> QualityResult:
    quality_config = load_quality_config(config, project_root)
    if execute:
        quality_config = replace(quality_config, dry_run=False)
    if not quality_config.enabled and not include_disabled:
        raise ValueError("Quality Scoring is disabled in config. Enable modules.quality_scoring.enabled or pass --include-disabled.")

    items = read_manifest(quality_config, project_root)
    scores = ordered_map(config, "quality_scoring", lambda item: score_item(quality_config, project_root, item), items)
    selected = select_scores(scores, quality_config)
    return write_reports(quality_config, project_root, selected)
