"""Video Processing Engine reports and stage orchestration."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import mimetypes
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.activity import ActivityProfile, activity_fit_score, activity_bucket, load_activity_profile, purpose_scores
from memory_curator_engine.common.media_sets import media_set_activity_map
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import parse_enabled


VIDEO_STAGES = [
    "scene-detection",
    "clip-segmentation",
    "clip-scoring",
    "frame-analysis",
    "audio-analysis",
    "transcript",
    "timeline-builder",
]

SCENE_COLUMNS = [
    "media_set",
    "video_path",
    "original_path",
    "moment_id",
    "scene_id",
    "scene_index",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "thumbnail_path",
    "scene_label",
    "confidence",
    "detection_method",
    "source_phase",
]

CLIP_COLUMNS = [
    "media_set",
    "video_path",
    "original_path",
    "moment_id",
    "scene_id",
    "clip_id",
    "clip_index",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "planned_clip_path",
    "clip_path",
    "clip_type",
    "segmentation_reason",
    "source_phase",
]

CLIP_SCORE_COLUMNS = [
    "media_set",
    "clip_id",
    "video_path",
    "clip_path",
    "moment_id",
    "scene_id",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "quality_score",
    "action_score",
    "people_score",
    "story_score",
    "audio_score",
    "activity_score",
    "activity_bucket",
    "reel_score",
    "documentary_score",
    "time_capsule_score",
    "overall_score",
    "recommended_uses",
    "scoring_reason",
    "source_phase",
]

FRAME_COLUMNS = [
    "media_set",
    "video_path",
    "moment_id",
    "scene_id",
    "clip_id",
    "frame_id",
    "timestamp_seconds",
    "frame_path",
    "width",
    "height",
    "brightness_score",
    "sharpness_score",
    "motion_context",
    "tags",
    "source_phase",
]

AFRAME_COLUMNS = FRAME_COLUMNS

AUDIO_COLUMNS = [
    "media_set",
    "video_path",
    "moment_id",
    "event_id",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "audio_event_type",
    "intensity_score",
    "confidence",
    "detection_method",
    "notes",
    "source_phase",
]

TRANSCRIPT_COLUMNS = [
    "media_set",
    "video_path",
    "moment_id",
    "segment_id",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "text",
    "language",
    "confidence",
    "speaker_label",
    "keywords",
    "source_phase",
]

TIMELINE_COLUMNS = [
    "media_set",
    "video_path",
    "moment_id",
    "timeline_event_id",
    "event_index",
    "start_seconds",
    "end_seconds",
    "duration_seconds",
    "event_type",
    "event_label",
    "scene_id",
    "clip_id",
    "audio_event_id",
    "transcript_segment_id",
    "frame_ids",
    "story_importance_score",
    "reel_value_score",
    "documentary_value_score",
    "time_capsule_value_score",
    "notes",
    "source_phase",
]

VIDEO_PROCESSING_MANIFEST_COLUMNS = [
    "media_set",
    "video_path",
    "moment_id",
    "scene_manifest_path",
    "clip_manifest_path",
    "clip_scores_path",
    "frame_manifest_path",
    "audio_events_path",
    "transcript_segments_path",
    "timeline_path",
    "processing_status",
    "source_phase",
]


@dataclass(frozen=True)
class StageConfig:
    enabled: bool
    output_dir: Path
    curated_dir: Path | None = None


@dataclass(frozen=True)
class VideoProcessingConfig:
    enabled: bool
    dry_run: bool
    input_quality_manifest: Path
    input_story_manifest: Path
    input_moment_assets: Path
    output_dir: Path
    curated_dir: Path
    overwrite_policy: str
    scene_detection: StageConfig
    clip_segmentation: StageConfig
    clip_scoring: StageConfig
    frame_analysis: StageConfig
    audio_analysis: StageConfig
    transcript: StageConfig
    timeline_builder: StageConfig
    target_scene_seconds: float
    thumbnail_on_execute: bool
    reel_clip_seconds: float
    documentary_clip_seconds: float
    extract_clips_on_execute: bool
    top_clip_count: int
    frame_sample_every_seconds: float
    extract_frames_on_execute: bool
    waveform_on_execute: bool
    audio_cache_enabled: bool
    audio_window_seconds: float
    transcript_enabled: bool
    transcript_required: bool
    transcript_backend: str
    transcript_model: str
    transcript_local_model: str
    timeline_ai_enabled: bool
    timeline_ai_required: bool
    timeline_ai_model: str
    timeline_ai_endpoint: str
    activity_profile: ActivityProfile
    media_set_profiles: dict[str, ActivityProfile]


@dataclass(frozen=True)
class VideoAsset:
    media_set: str
    video_path: str
    original_path: str
    file_type: str
    duration_seconds: float
    quality_score: float
    instagram_score: float
    movie_score: float
    activity_score: float
    reel_purpose_score: float
    documentary_purpose_score: float
    moment_id: str
    moment_type: str
    moment_title: str
    moment_score: float
    reel_moment_score: float
    documentary_moment_score: float
    time_capsule_moment_score: float
    role: str
    width: str
    height: str


@dataclass(frozen=True)
class FrameSample:
    timestamp: float
    brightness: float
    sharpness: float
    motion: float


@dataclass(frozen=True)
class VideoMetrics:
    method: str
    samples: list[FrameSample]
    boundaries: list[float]
    avg_brightness: float
    avg_sharpness: float
    avg_motion: float
    max_motion: float


@dataclass(frozen=True)
class VideoProcessingResult:
    video_count: int
    scene_count: int
    clip_count: int
    scored_clip_count: int
    frame_count: int
    audio_event_count: int
    transcript_segment_count: int
    timeline_event_count: int
    generated_media_count: int
    manifest_csv: Path
    dry_run: bool
    stages: list[str]


def load_video_processing_config(config: Config, project_root: Path) -> VideoProcessingConfig:
    output_dir = resolve_project_path(project_root, config_value(config, "video_processing.output_dir", "MemoryCurator/07 Video Processing"))
    curated_root = config_value(config, "project.curated_root", "input_data/curated")
    curated_dir = resolve_project_path(project_root, config_value(config, "video_processing.curated_dir", f"{curated_root}/07 Video Processing"))
    stages = config_value(config, "video_processing.stages", {}) or {}

    def stage(name: str, default_output: str, curated_key: str | None = None, default_curated: str | None = None) -> StageConfig:
        values = stages.get(name, {}) if isinstance(stages, dict) else {}
        curated_value = values.get(curated_key, default_curated) if curated_key else None
        return StageConfig(
            enabled=parse_enabled(values.get("enabled", True), f"video_processing.stages.{name}.enabled"),
            output_dir=resolve_project_path(project_root, values.get("output_dir", default_output)),
            curated_dir=resolve_project_path(project_root, curated_value) if curated_value else None,
        )

    scene_values = stages.get("scene_detection", {}) if isinstance(stages, dict) else {}
    clip_values = stages.get("clip_segmentation", {}) if isinstance(stages, dict) else {}
    clip_score_values = stages.get("clip_scoring", {}) if isinstance(stages, dict) else {}
    frame_values = stages.get("frame_analysis", {}) if isinstance(stages, dict) else {}
    audio_values = stages.get("audio_analysis", {}) if isinstance(stages, dict) else {}
    transcript_values = stages.get("transcript", {}) if isinstance(stages, dict) else {}
    timeline_values = stages.get("timeline_builder", {}) if isinstance(stages, dict) else {}
    timeline_ai_values = timeline_values.get("ai", {}) if isinstance(timeline_values, dict) else {}

    return VideoProcessingConfig(
        enabled=parse_enabled(config_value(config, "modules.video_processing.enabled", False), "video_processing"),
        dry_run=parse_enabled(config_value(config, "video_processing.dry_run", True), "video_processing.dry_run"),
        input_quality_manifest=resolve_project_path(
            project_root,
            config_value(config, "video_processing.input_quality_manifest", "MemoryCurator/03 Quality Scoring/quality_manifest.csv"),
        ),
        input_story_manifest=resolve_project_path(
            project_root,
            config_value(config, "video_processing.input_story_manifest", "MemoryCurator/05 Story Builder/story_manifest.csv"),
        ),
        input_moment_assets=resolve_project_path(
            project_root,
            config_value(config, "video_processing.input_moment_assets", "MemoryCurator/05 Story Builder/moment_assets.csv"),
        ),
        output_dir=output_dir,
        curated_dir=curated_dir,
        overwrite_policy=str(config_value(config, "video_processing.overwrite_policy", "fail")),
        scene_detection=stage(
            "scene_detection",
            "MemoryCurator/07 Video Processing/scene-detection",
            "thumbnails_dir",
            f"{curated_root}/07 Video Processing/scene-detection/scene_thumbnails",
        ),
        clip_segmentation=stage(
            "clip_segmentation",
            "MemoryCurator/07 Video Processing/clip-segmentation",
            "clips_dir",
            f"{curated_root}/07 Video Processing/clip-segmentation/clips",
        ),
        clip_scoring=stage("clip_scoring", "MemoryCurator/07 Video Processing/clip-scoring"),
        frame_analysis=stage(
            "frame_analysis",
            "MemoryCurator/07 Video Processing/frame-analysis",
            "frames_dir",
            f"{curated_root}/07 Video Processing/frame-analysis/frames",
        ),
        audio_analysis=stage(
            "audio_analysis",
            "MemoryCurator/07 Video Processing/audio-analysis",
            "waveforms_dir",
            f"{curated_root}/07 Video Processing/audio-analysis/waveforms",
        ),
        transcript=stage(
            "transcript",
            "MemoryCurator/07 Video Processing/transcript",
            "audio_dir",
            f"{curated_root}/07 Video Processing/transcript/audio",
        ),
        timeline_builder=stage("timeline_builder", "MemoryCurator/07 Video Processing/timeline-builder"),
        target_scene_seconds=float(scene_values.get("target_scene_seconds", 45)),
        thumbnail_on_execute=parse_enabled(scene_values.get("thumbnail_on_execute", False), "video_processing.scene_detection.thumbnail_on_execute"),
        reel_clip_seconds=float(clip_values.get("reel_clip_seconds", 12)),
        documentary_clip_seconds=float(clip_values.get("documentary_clip_seconds", 45)),
        extract_clips_on_execute=parse_enabled(clip_values.get("extract_on_execute", False), "video_processing.clip_segmentation.extract_on_execute"),
        top_clip_count=int(clip_score_values.get("top_clip_count", 24)),
        frame_sample_every_seconds=float(frame_values.get("sample_every_seconds", 5)),
        extract_frames_on_execute=parse_enabled(frame_values.get("extract_on_execute", False), "video_processing.frame_analysis.extract_on_execute"),
        waveform_on_execute=parse_enabled(audio_values.get("waveform_on_execute", False), "video_processing.audio_analysis.waveform_on_execute"),
        audio_cache_enabled=parse_enabled(audio_values.get("cache_enabled", True), "video_processing.audio_analysis.cache_enabled"),
        audio_window_seconds=float(audio_values.get("window_seconds", 5)),
        transcript_enabled=parse_enabled(transcript_values.get("enabled", False), "video_processing.transcript.enabled"),
        transcript_required=parse_enabled(transcript_values.get("required", False), "video_processing.transcript.required"),
        transcript_backend=str(transcript_values.get("backend", "none")),
        transcript_model=str(transcript_values.get("model", "gpt-4o-transcribe")),
        transcript_local_model=str(transcript_values.get("local_model", "base")),
        timeline_ai_enabled=parse_enabled(timeline_ai_values.get("enabled", False), "video_processing.timeline_builder.ai.enabled"),
        timeline_ai_required=parse_enabled(timeline_ai_values.get("required", False), "video_processing.timeline_builder.ai.required"),
        timeline_ai_model=str(timeline_ai_values.get("model", "gpt-5.2-mini")),
        timeline_ai_endpoint=str(timeline_ai_values.get("endpoint", "https://api.openai.com/v1/responses")),
        activity_profile=load_activity_profile(
            config,
            str(config_value(config, "video_processing.activity_profile", config_value(config, "reel_builder.activity_profile", "default"))),
        ),
        media_set_profiles={
            name: load_activity_profile(config, activity.activity_profile)
            for name, activity in media_set_activity_map(config).items()
        },
    )


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


def is_video_type(file_type: str, path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return file_type.startswith("video/") or suffix in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def path_text(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def slugify(value: str) -> str:
    cleaned: list[str] = []
    previous = False
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
            previous = False
        elif not previous:
            cleaned.append("_")
            previous = True
    return "".join(cleaned).strip("_") or "video"


def ffmpeg_available() -> bool:
    return ffmpeg_executable() is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def ffmpeg_executable() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    if optional_module_available("imageio_ffmpeg"):
        try:
            import imageio_ffmpeg  # type: ignore[import-not-found]

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 - optional binary discovery should fail soft.
            return None
    return None


def load_video_assets(config: VideoProcessingConfig, project_root: Path) -> list[VideoAsset]:
    story_rows = read_csv_required(config.input_story_manifest, project_root, "story-builder")
    asset_rows = read_csv_required(config.input_moment_assets, project_root, "story-builder")
    quality_rows = read_csv_required(config.input_quality_manifest, project_root, "quality-scoring")
    quality_by_path = {row.get("media_path", ""): row for row in quality_rows}
    story_by_moment = {row.get("moment_id", ""): row for row in story_rows}
    assets: list[VideoAsset] = []
    seen: set[str] = set()
    for row in asset_rows:
        video_path = row.get("media_path", "")
        file_type = row.get("file_type", "")
        if not video_path or video_path in seen or not is_video_type(file_type, video_path):
            continue
        source = resolve_project_path(project_root, video_path)
        if not source.exists():
            raise FileNotFoundError(f"Video source is missing: {source}")
        seen.add(video_path)
        quality = quality_by_path.get(video_path, {})
        story = story_by_moment.get(row.get("moment_id", ""), {})
        duration = safe_float(row.get("duration_seconds") or quality.get("duration_seconds"), 0)
        if duration <= 0:
            duration = ffprobe_duration(source) or 1.0
        assets.append(
            VideoAsset(
                media_set=row.get("media_set", "default"),
                video_path=video_path,
                original_path=quality.get("original_path", row.get("original_path", video_path)),
                file_type=file_type or quality.get("file_type", ""),
                duration_seconds=duration,
                quality_score=safe_float(row.get("quality_score") or quality.get("quality_score"), 50),
                instagram_score=safe_float(row.get("instagram_score") or quality.get("instagram_score"), 50),
                movie_score=safe_float(row.get("movie_score") or quality.get("movie_score"), 50),
                activity_score=safe_float(row.get("activity_score") or quality.get("activity_score"), 50),
                reel_purpose_score=safe_float(row.get("reel_purpose_score") or quality.get("reel_purpose_score") or row.get("instagram_score") or quality.get("instagram_score"), 50),
                documentary_purpose_score=safe_float(row.get("documentary_purpose_score") or quality.get("documentary_purpose_score") or row.get("movie_score") or quality.get("movie_score"), 50),
                moment_id=row.get("moment_id", ""),
                moment_type=story.get("moment_type", "other"),
                moment_title=story.get("title", row.get("moment_id", "")),
                moment_score=safe_float(story.get("moment_score"), 50),
                reel_moment_score=safe_float(story.get("reel_score"), 50),
                documentary_moment_score=safe_float(story.get("documentary_score"), 50),
                time_capsule_moment_score=safe_float(story.get("time_capsule_score"), 50),
                role=row.get("role", ""),
                width=quality.get("width", ""),
                height=quality.get("height", ""),
            )
        )
    return sorted(assets, key=lambda item: (item.media_set, item.moment_id, item.video_path))


def ffprobe_duration(path: Path) -> float | None:
    if not ffprobe_available():
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def optional_module_available(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def sample_video_metrics(path: Path, duration_seconds: float, sample_every_seconds: float = 2.0) -> VideoMetrics:
    if not optional_module_available("cv2") or not optional_module_available("numpy"):
        return VideoMetrics(
            method="coarse_time_window",
            samples=[],
            boundaries=[],
            avg_brightness=0,
            avg_sharpness=0,
            avg_motion=0,
            max_motion=0,
        )

    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return VideoMetrics("coarse_time_window", [], [], 0, 0, 0, 0)

    samples: list[FrameSample] = []
    previous_gray = None
    sample_step = max(sample_every_seconds, 0.5)
    timestamp = 0.0
    while timestamp <= max(duration_seconds, 0.1) and len(samples) < 600:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        success, frame = capture.read()
        if not success:
            timestamp += sample_step
            continue
        resized = cv2.resize(frame, (160, 90))
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        motion = 0.0
        if previous_gray is not None:
            motion = float(np.mean(cv2.absdiff(gray, previous_gray)))
        samples.append(FrameSample(round(timestamp, 3), brightness, sharpness, motion))
        previous_gray = gray
        timestamp += sample_step
    capture.release()

    if not samples:
        return VideoMetrics("coarse_time_window", [], [], 0, 0, 0, 0)

    motions = [sample.motion for sample in samples[1:]]
    avg_motion = mean(motions) if motions else 0.0
    max_motion = max(motions) if motions else 0.0
    motion_threshold = max(avg_motion * 1.9, 14.0)
    boundaries = [
        sample.timestamp
        for sample in samples[1:]
        if sample.motion >= motion_threshold and 2.0 <= sample.timestamp <= max(duration_seconds - 2.0, 2.0)
    ]
    filtered_boundaries: list[float] = []
    for boundary in boundaries:
        if not filtered_boundaries or boundary - filtered_boundaries[-1] >= 8:
            filtered_boundaries.append(boundary)
    return VideoMetrics(
        method="opencv_frame_difference",
        samples=samples,
        boundaries=filtered_boundaries,
        avg_brightness=mean(sample.brightness for sample in samples),
        avg_sharpness=mean(sample.sharpness for sample in samples),
        avg_motion=avg_motion,
        max_motion=max_motion,
    )


def boundaries_for_asset(config: VideoProcessingConfig, metrics: VideoMetrics, duration_seconds: float) -> list[float]:
    boundaries = [boundary for boundary in metrics.boundaries if 4 <= boundary <= duration_seconds - 4]
    max_gap = max(config.target_scene_seconds * 1.4, 30)
    all_boundaries: list[float] = []
    previous = 0.0
    for boundary in boundaries:
        while boundary - previous > max_gap:
            previous += max_gap
            all_boundaries.append(round(previous, 3))
        all_boundaries.append(round(boundary, 3))
        previous = boundary
    while duration_seconds - previous > max_gap:
        previous += max_gap
        all_boundaries.append(round(previous, 3))
    return sorted(set(value for value in all_boundaries if 0 < value < duration_seconds))


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_activity_csvs(base_dir: Path, filename: str, columns: list[str], rows: list[dict[str, object]]) -> None:
    grouped = group_by(rows, "media_set")
    for media_set, media_rows in grouped.items():
        write_csv(base_dir / media_set / filename, columns, media_rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def scene_label(asset: VideoAsset, scene_index: int, scene_count: int, metrics: VideoMetrics | None = None, start: float = 0.0, end: float = 0.0) -> str:
    base = asset.moment_title or asset.moment_type or asset.moment_id or "video"
    motion = segment_motion(metrics, start, end) if metrics else 0.0
    suffix = ""
    if asset.moment_type in {"rapids", "splash", "launch"} or motion >= 18:
        suffix = " action"
    elif asset.moment_type in {"safety_briefing", "gear_up", "walk_to_start"}:
        suffix = " setup"
    elif asset.moment_type in {"group_photo", "meal"}:
        suffix = " people"
    elif asset.moment_type in {"travel_to_activity", "arrival", "return_trip"}:
        suffix = " transition"
    if scene_count == 1:
        return f"{base}{suffix}"
    if scene_index == 1:
        return f"{base} opening{suffix}"
    if scene_index == scene_count:
        return f"{base} closing{suffix}"
    return f"{base} part {scene_index}{suffix}"


def segment_samples(metrics: VideoMetrics | None, start: float, end: float) -> list[FrameSample]:
    if not metrics:
        return []
    return [sample for sample in metrics.samples if start <= sample.timestamp <= end]


def segment_motion(metrics: VideoMetrics | None, start: float, end: float) -> float:
    samples = segment_samples(metrics, start, end)
    if not samples:
        return 0.0
    return mean(sample.motion for sample in samples)


def segment_brightness(metrics: VideoMetrics | None, start: float, end: float) -> float:
    samples = segment_samples(metrics, start, end)
    if not samples:
        return 0.0
    return mean(sample.brightness for sample in samples)


def segment_sharpness(metrics: VideoMetrics | None, start: float, end: float) -> float:
    samples = segment_samples(metrics, start, end)
    if not samples:
        return 0.0
    return mean(sample.sharpness for sample in samples)


def run_scene_detection(
    config: VideoProcessingConfig,
    project_root: Path,
    assets: list[VideoAsset],
    metrics_by_path: dict[str, VideoMetrics],
) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    generated = 0
    thumb_dir = config.scene_detection.curated_dir or (config.curated_dir / "scene-detection" / "scene_thumbnails")
    for asset in assets:
        source = resolve_project_path(project_root, asset.video_path)
        metrics = metrics_by_path.get(asset.video_path)
        if metrics is None:
            metrics = sample_video_metrics(source, asset.duration_seconds, sample_every_seconds=max(config.frame_sample_every_seconds, 2.0))
            metrics_by_path[asset.video_path] = metrics
        boundaries = boundaries_for_asset(config, metrics, asset.duration_seconds)
        points = [0.0, *boundaries, round(asset.duration_seconds, 3)]
        scene_count = len(points) - 1
        for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
            start = round(start, 3)
            end = round(end, 3)
            if end - start <= 0:
                continue
            scene_id = f"{slugify(Path(asset.video_path).stem)}_scene_{index:03d}"
            thumbnail_path = thumb_dir / asset.media_set / f"{scene_id}.jpg"
            if not config.dry_run and config.thumbnail_on_execute and ffmpeg_available():
                generated += extract_frame(resolve_project_path(project_root, asset.video_path), thumbnail_path, start)
            label = scene_label(asset, index, scene_count, metrics, start, end)
            rows.append(
                {
                    "media_set": asset.media_set,
                    "video_path": asset.video_path,
                    "original_path": asset.original_path,
                    "moment_id": asset.moment_id,
                    "scene_id": scene_id,
                    "scene_index": index,
                    "start_seconds": start,
                    "end_seconds": end,
                    "duration_seconds": round(end - start, 3),
                    "thumbnail_path": path_text(thumbnail_path, project_root),
                    "scene_label": label,
                    "confidence": 0.78 if metrics.method == "opencv_frame_difference" and boundaries else 0.58,
                    "detection_method": metrics.method,
                    "source_phase": "video_processing.scene_detection",
                }
            )
    output = config.scene_detection.output_dir / "scene_manifest.csv"
    write_csv(output, SCENE_COLUMNS, rows)
    write_activity_csvs(config.scene_detection.output_dir, "scene_manifest.csv", SCENE_COLUMNS, rows)
    write_text(config.scene_detection.output_dir / "scene_summary.md", f"# Scene Detection Summary\n\nScenes: {len(rows)}\nVideos: {len(assets)}\n")
    return rows, generated


def clip_type_for(asset: VideoAsset, scene: dict[str, object], clip_index: int) -> str:
    label = str(scene.get("scene_label", ""))
    if asset.role == "hero_video":
        return "hero_candidate"
    if asset.moment_type in {"rapids", "splash", "launch"} or any(token in label.lower() for token in ["rapid", "splash", "launch", "action"]):
        return "action"
    if "opening" in label.lower() or asset.moment_type in {"arrival", "travel_to_activity"}:
        return "establishing"
    if "closing" in label.lower() or asset.moment_type == "return_trip":
        return "closing"
    if asset.moment_type in {"safety_briefing", "gear_up", "walk_to_start"}:
        return "transition"
    if asset.moment_type in {"group_photo", "meal"}:
        return "reaction"
    return "b_roll"


def run_clip_segmentation(
    config: VideoProcessingConfig,
    project_root: Path,
    assets_by_path: dict[str, VideoAsset],
    scenes: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    generated = 0
    clips_dir = config.clip_segmentation.curated_dir or (config.curated_dir / "clip-segmentation" / "clips")
    for scene in scenes:
        asset = assets_by_path[str(scene["video_path"])]
        start = safe_float(str(scene["start_seconds"]))
        end = safe_float(str(scene["end_seconds"]))
        duration = max(end - start, 0.1)
        target = config.reel_clip_seconds if duration <= 30 else config.documentary_clip_seconds
        clip_count = max(1, math.ceil(duration / max(target, 1)))
        clip_length = duration / clip_count
        for index in range(1, clip_count + 1):
            clip_start = round(start + (index - 1) * clip_length, 3)
            clip_end = round(end if index == clip_count else start + index * clip_length, 3)
            clip_id = f"{scene['scene_id']}_clip_{index:03d}"
            clip_path = clips_dir / asset.media_set / f"{clip_id}{Path(asset.video_path).suffix.lower() or '.mp4'}"
            actual_clip_path = ""
            if not config.dry_run and config.extract_clips_on_execute and ffmpeg_available():
                generated += extract_clip(resolve_project_path(project_root, asset.video_path), clip_path, clip_start, clip_end - clip_start)
                actual_clip_path = path_text(clip_path, project_root)
            rows.append(
                {
                    "media_set": asset.media_set,
                    "video_path": asset.video_path,
                    "original_path": asset.original_path,
                    "moment_id": asset.moment_id,
                    "scene_id": scene["scene_id"],
                    "clip_id": clip_id,
                    "clip_index": index,
                    "start_seconds": clip_start,
                    "end_seconds": clip_end,
                    "duration_seconds": round(clip_end - clip_start, 3),
                    "planned_clip_path": path_text(clip_path, project_root),
                    "clip_path": actual_clip_path,
                    "clip_type": clip_type_for(asset, scene, index),
                    "segmentation_reason": "coarse segmentation from scene duration",
                    "source_phase": "video_processing.clip_segmentation",
                }
            )
    write_csv(config.clip_segmentation.output_dir / "clip_manifest.csv", CLIP_COLUMNS, rows)
    write_activity_csvs(config.clip_segmentation.output_dir, "clip_manifest.csv", CLIP_COLUMNS, rows)
    write_text(config.clip_segmentation.output_dir / "clip_summary.md", f"# Clip Segmentation Summary\n\nCandidate clips: {len(rows)}\nScenes: {len(scenes)}\n")
    return rows, generated


def run_clip_scoring(
    config: VideoProcessingConfig,
    project_root: Path,
    assets_by_path: dict[str, VideoAsset],
    clips: list[dict[str, object]],
    metrics_by_path: dict[str, VideoMetrics],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for clip in clips:
        asset = assets_by_path[str(clip["video_path"])]
        metrics = metrics_by_path.get(asset.video_path)
        if metrics is None:
            metrics = sample_video_metrics(resolve_project_path(project_root, asset.video_path), asset.duration_seconds, sample_every_seconds=2.0)
            metrics_by_path[asset.video_path] = metrics
        duration = safe_float(str(clip["duration_seconds"]))
        start = safe_float(str(clip["start_seconds"]))
        end = safe_float(str(clip["end_seconds"]))
        motion = segment_motion(metrics, start, end)
        brightness = segment_brightness(metrics, start, end)
        sharpness = segment_sharpness(metrics, start, end)
        motion_score = min(100.0, 45.0 + motion * 2.4)
        brightness_score = max(20.0, 100.0 - abs(brightness - 118.0) * 0.55) if brightness else 55.0
        sharpness_score = min(100.0, 35.0 + sharpness / 4.0) if sharpness else 55.0
        action = max(motion_score, 82.0 if clip["clip_type"] in {"hero_candidate", "action"} else 52.0)
        story = max(asset.moment_score, asset.reel_moment_score if clip["clip_type"] in {"hero_candidate", "action"} else asset.documentary_moment_score)
        audio = 62.0 if asset.moment_type in {"splash", "rapids", "group_photo"} else 55.0
        people = 50.0
        duration_reel = max(0.0, 100.0 - abs(duration - config.reel_clip_seconds) * 3)
        duration_doc = max(0.0, 100.0 - abs(duration - config.documentary_clip_seconds) * 0.8)
        technical = asset.quality_score * 0.45 + brightness_score * 0.20 + sharpness_score * 0.35
        text = f"{asset.video_path} {asset.moment_type} {asset.moment_title} {clip['clip_type']}"
        profile = config.media_set_profiles.get(asset.media_set, config.activity_profile)
        fit, fit_reason = activity_fit_score(
            profile,
            path=asset.video_path,
            moment_type=asset.moment_type,
            role=str(clip["clip_type"]),
            technical_score=technical,
            motion_score=motion_score,
            audio_score=audio,
            story_score=story,
            people_score=people,
            text=text,
        )
        purposes = purpose_scores(
            profile,
            path=asset.video_path,
            media_kind="video",
            technical_score=technical,
            quality_score=asset.quality_score,
            album_score=asset.quality_score,
            instagram_score=asset.reel_purpose_score or asset.instagram_score,
            movie_score=asset.documentary_purpose_score or asset.movie_score,
            motion_score=motion_score,
            stability_score=100.0 - max(0.0, motion_score - 85.0) * 0.5,
            duration_seconds=duration,
            moment_type=asset.moment_type,
            role=str(clip["clip_type"]),
            story_score=story,
            people_score=people,
            audio_score=audio,
            text=text,
        )
        activity_score = float(purposes["activity_score"])
        reel = max(
            float(purposes["reel_purpose_score"]),
            asset.reel_purpose_score * 0.22 + fit * 0.38 + action * 0.20 + duration_reel * 0.12 + technical * 0.08,
        )
        documentary = max(
            float(purposes["documentary_purpose_score"]),
            asset.documentary_purpose_score * 0.28 + story * 0.30 + fit * 0.18 + duration_doc * 0.14 + technical * 0.10,
        )
        time_capsule = asset.time_capsule_moment_score * 0.45 + audio * 0.30 + story * 0.25
        overall = technical * 0.16 + action * 0.18 + people * 0.06 + story * 0.20 + audio * 0.14 + activity_score * 0.26
        uses = []
        if reel >= 70:
            uses.append("reel")
        if documentary >= 62:
            uses.append("documentary")
        if time_capsule >= 62:
            uses.append("time_capsule")
        if not uses:
            uses.append("b_roll")
        rows.append(
            {
                "media_set": clip["media_set"],
                "clip_id": clip["clip_id"],
                "video_path": clip["video_path"],
                "clip_path": clip["clip_path"] or clip["planned_clip_path"],
                "moment_id": clip["moment_id"],
                "scene_id": clip["scene_id"],
                "start_seconds": clip["start_seconds"],
                "end_seconds": clip["end_seconds"],
                "duration_seconds": duration,
                "quality_score": round(technical, 2),
                "action_score": round(action, 2),
                "people_score": round(people, 2),
                "story_score": round(story, 2),
                "audio_score": round(audio, 2),
                "activity_score": round(activity_score, 2),
                "activity_bucket": activity_bucket(profile, asset.moment_type, str(clip["clip_type"])),
                "reel_score": round(reel, 2),
                "documentary_score": round(documentary, 2),
                "time_capsule_score": round(time_capsule, 2),
                "overall_score": round(overall, 2),
                "recommended_uses": ",".join(uses),
                "scoring_reason": (
                    f"quality/story/motion blend; motion={motion:.2f}, brightness={brightness:.1f}, "
                    f"sharpness={sharpness:.1f}, clip_type={clip['clip_type']}; {fit_reason}"
                ),
                "source_phase": "video_processing.clip_scoring",
            }
        )
    rows.sort(key=lambda row: (-safe_float(str(row["overall_score"])), str(row["video_path"]), safe_float(str(row["start_seconds"]))))
    write_csv(config.clip_scoring.output_dir / "clip_scores.csv", CLIP_SCORE_COLUMNS, rows)
    write_csv(config.clip_scoring.output_dir / "top_clips.csv", CLIP_SCORE_COLUMNS, rows[: config.top_clip_count])
    write_activity_csvs(config.clip_scoring.output_dir, "clip_scores.csv", CLIP_SCORE_COLUMNS, rows)
    for media_set, media_rows in group_by(rows, "media_set").items():
        write_csv(config.clip_scoring.output_dir / media_set / "top_clips.csv", CLIP_SCORE_COLUMNS, media_rows[: config.top_clip_count])
    write_text(config.clip_scoring.output_dir / "clip_scoring_summary.md", f"# Clip Scoring Summary\n\nScored clips: {len(rows)}\nTop clips: {min(len(rows), config.top_clip_count)}\n")
    return rows


def run_frame_analysis(
    config: VideoProcessingConfig,
    project_root: Path,
    assets_by_path: dict[str, VideoAsset],
    scenes: list[dict[str, object]],
    clips: list[dict[str, object]],
    metrics_by_path: dict[str, VideoMetrics],
) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    generated = 0
    frames_dir = config.frame_analysis.curated_dir or (config.curated_dir / "frame-analysis" / "frames")
    clips_by_scene = {str(clip["scene_id"]): clip for clip in clips}
    for scene in scenes:
        asset = assets_by_path[str(scene["video_path"])]
        metrics = metrics_by_path.get(asset.video_path)
        if metrics is None:
            metrics = sample_video_metrics(resolve_project_path(project_root, asset.video_path), asset.duration_seconds, sample_every_seconds=config.frame_sample_every_seconds)
            metrics_by_path[asset.video_path] = metrics
        start = safe_float(str(scene["start_seconds"]))
        end = safe_float(str(scene["end_seconds"]))
        step = max(config.frame_sample_every_seconds, 1)
        metric_timestamps = [sample.timestamp for sample in segment_samples(metrics, start, end)]
        timestamps = sorted(set([start, min(end, start + (end - start) / 2), max(start, end - 0.1), *metric_timestamps[:8]]))
        current = start
        while current < end and len(timestamps) < 8:
            timestamps.append(round(current, 3))
            current += step
        for index, timestamp in enumerate(sorted(set(round(value, 3) for value in timestamps if start <= value <= end)), start=1):
            frame_id = f"{scene['scene_id']}_frame_{index:03d}"
            frame_path = frames_dir / asset.media_set / f"{frame_id}.jpg"
            if not config.dry_run and config.extract_frames_on_execute and ffmpeg_available():
                generated += extract_frame(resolve_project_path(project_root, asset.video_path), frame_path, timestamp)
            nearest = nearest_sample(metrics, timestamp)
            brightness = nearest.brightness if nearest else segment_brightness(metrics, start, end)
            sharpness = nearest.sharpness if nearest else segment_sharpness(metrics, start, end)
            motion = nearest.motion if nearest else segment_motion(metrics, start, end)
            tags = frame_tags(asset, scene, brightness, sharpness, motion)
            rows.append(
                {
                    "media_set": asset.media_set,
                    "video_path": asset.video_path,
                    "moment_id": asset.moment_id,
                    "scene_id": scene["scene_id"],
                    "clip_id": clips_by_scene.get(str(scene["scene_id"]), {}).get("clip_id", ""),
                    "frame_id": frame_id,
                    "timestamp_seconds": timestamp,
                    "frame_path": path_text(frame_path, project_root),
                    "width": asset.width,
                    "height": asset.height,
                    "brightness_score": round(min(100.0, max(0.0, 100.0 - abs(brightness - 118.0) * 0.55)), 2) if brightness else "",
                    "sharpness_score": round(min(100.0, 35.0 + sharpness / 4.0), 2) if sharpness else "",
                    "motion_context": motion_context(motion),
                    "tags": ",".join(tags),
                    "source_phase": "video_processing.frame_analysis",
                }
            )
    write_csv(config.frame_analysis.output_dir / "frame_manifest.csv", FRAME_COLUMNS, rows)
    write_activity_csvs(config.frame_analysis.output_dir, "frame_manifest.csv", FRAME_COLUMNS, rows)
    tag_rows = [{"frame_id": row["frame_id"], "video_path": row["video_path"], "tags": row["tags"]} for row in rows]
    write_csv(config.frame_analysis.output_dir / "frame_tags.csv", ["frame_id", "video_path", "tags"], tag_rows)
    write_text(config.frame_analysis.output_dir / "frame_analysis_summary.md", f"# Frame Analysis Summary\n\nRepresentative frames: {len(rows)}\n")
    return rows, generated


def nearest_sample(metrics: VideoMetrics | None, timestamp: float) -> FrameSample | None:
    if not metrics or not metrics.samples:
        return None
    return min(metrics.samples, key=lambda sample: abs(sample.timestamp - timestamp))


def motion_context(motion: float) -> str:
    if motion >= 22:
        return "high_action_motion"
    if motion >= 10:
        return "moderate_motion"
    return "low_motion"


def frame_tags(asset: VideoAsset, scene: dict[str, object], brightness: float = 0.0, sharpness: float = 0.0, motion: float = 0.0) -> list[str]:
    tags = ["video", "outdoor"]
    label = str(scene.get("scene_label", ""))
    joined = f"{asset.video_path} {asset.moment_id} {asset.moment_type} {asset.moment_title} {label}".lower()
    for token, tag in [("river", "river"), ("rapid", "river"), ("splash", "water"), ("gopr", "action"), ("gx", "gopro"), ("img_", "iphone"), ("helmet", "gear"), ("lunch", "food")]:
        if token in joined and tag not in tags:
            tags.append(tag)
    if motion >= 22 and "action" not in tags:
        tags.append("action")
    elif motion <= 4:
        tags.append("calm")
    if brightness and brightness < 55:
        tags.append("low_light")
    elif brightness and brightness > 205:
        tags.append("bright")
    if sharpness and sharpness < 35:
        tags.append("soft_or_blurry")
    if asset.role == "hero_video":
        tags.append("hero_video")
    return tags


def run_audio_analysis(config: VideoProcessingConfig, project_root: Path, assets: list[VideoAsset]) -> tuple[list[dict[str, object]], int]:
    rows: list[dict[str, object]] = []
    generated = 0
    cache_hits = 0
    cache_writes = 0
    cache_dir = (config.audio_analysis.curated_dir or (config.curated_dir / "audio-analysis" / "waveforms")).parent / "cache"
    for asset in assets:
        source = resolve_project_path(project_root, asset.video_path)
        cached_rows = read_audio_cache(config, cache_dir, asset, source)
        if cached_rows is not None:
            audio_rows = cached_rows
            cache_hits += 1
        else:
            audio_rows = analyze_audio_events(config, asset, source)
            if config.audio_cache_enabled:
                write_audio_cache(config, cache_dir, asset, source, audio_rows)
                cache_writes += 1
        rows.extend(audio_rows)
    write_csv(config.audio_analysis.output_dir / "audio_events.csv", AUDIO_COLUMNS, rows)
    write_activity_csvs(config.audio_analysis.output_dir, "audio_events.csv", AUDIO_COLUMNS, rows)
    methods = sorted({str(row["detection_method"]) for row in rows})
    write_text(
        config.audio_analysis.output_dir / "audio_summary.md",
        (
            "# Audio Analysis Summary\n\n"
            f"Audio events: {len(rows)}\n"
            f"Detection methods: {', '.join(methods)}\n"
            f"Cache hits: {cache_hits}\n"
            f"Cache writes: {cache_writes}\n"
        ),
    )
    return rows, generated


def audio_cache_identity(config: VideoProcessingConfig, asset: VideoAsset, source: Path) -> dict[str, object]:
    stat = source.stat()
    return {
        "version": "audio-analysis-v2",
        "video_path": asset.video_path,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "duration_seconds": round(asset.duration_seconds, 3),
        "window_seconds": config.audio_window_seconds,
    }


def audio_cache_path(cache_dir: Path, identity: dict[str, object]) -> Path:
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return cache_dir / f"{digest}.json"


def read_audio_cache(config: VideoProcessingConfig, cache_dir: Path, asset: VideoAsset, source: Path) -> list[dict[str, object]] | None:
    if not config.audio_cache_enabled:
        return None
    identity = audio_cache_identity(config, asset, source)
    path = audio_cache_path(cache_dir, identity)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if loaded.get("identity") != identity:
        return None
    rows = loaded.get("rows")
    if not isinstance(rows, list):
        return None
    return [row for row in rows if isinstance(row, dict)]


def write_audio_cache(config: VideoProcessingConfig, cache_dir: Path, asset: VideoAsset, source: Path, rows: list[dict[str, object]]) -> None:
    identity = audio_cache_identity(config, asset, source)
    path = audio_cache_path(cache_dir, identity)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"identity": identity, "rows": rows}, indent=2), encoding="utf-8")


def analyze_audio_events(config: VideoProcessingConfig, asset: VideoAsset, source: Path) -> list[dict[str, object]]:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return metadata_audio_events(asset, "audio_decoder_unavailable")
    if not optional_module_available("librosa") or not optional_module_available("numpy"):
        return metadata_audio_events(asset, "audio_libraries_unavailable")

    import librosa  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    with tempfile.TemporaryDirectory(prefix="memory-curator-audio-") as temp_name:
        wav_path = Path(temp_name) / f"{source.stem}.wav"
        try:
            subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-y", str(wav_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return metadata_audio_events(asset, "audio_extract_failed")
        try:
            y, sample_rate = librosa.load(str(wav_path), sr=16000, mono=True)
        except Exception:  # noqa: BLE001
            return metadata_audio_events(asset, "audio_decode_failed")

    if len(y) == 0:
        return metadata_audio_events(asset, "empty_audio")

    window_seconds = max(config.audio_window_seconds, 1.0)
    hop = max(1, int(window_seconds * sample_rate))
    rms_values = []
    zcr_values = []
    centroid_values = []
    for start_sample in range(0, len(y), hop):
        segment = y[start_sample : start_sample + hop]
        if len(segment) < sample_rate:
            continue
        rms = float(np.sqrt(np.mean(segment**2)))
        zcr = float(librosa.feature.zero_crossing_rate(y=segment)[0].mean())
        centroid = float(librosa.feature.spectral_centroid(y=segment, sr=sample_rate)[0].mean())
        rms_values.append(rms)
        zcr_values.append(zcr)
        centroid_values.append(centroid)

    if not rms_values:
        return metadata_audio_events(asset, "audio_too_short_for_windows")

    rms_mean = float(np.mean(rms_values))
    rms_std = float(np.std(rms_values))
    rows: list[dict[str, object]] = []
    for index, rms in enumerate(rms_values, start=1):
        start = round((index - 1) * window_seconds, 3)
        end = round(min(index * window_seconds, asset.duration_seconds), 3)
        zcr = zcr_values[index - 1]
        centroid = centroid_values[index - 1]
        event_type, confidence = classify_audio_event(asset, rms, rms_mean, rms_std, zcr, centroid)
        rows.append(
            {
                "media_set": asset.media_set,
                "video_path": asset.video_path,
                "moment_id": asset.moment_id,
                "event_id": f"{slugify(Path(asset.video_path).stem)}_audio_{index:03d}",
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": round(end - start, 3),
                "audio_event_type": event_type,
                "intensity_score": round(min(100.0, rms * 900), 2),
                "confidence": confidence,
                "detection_method": "ffmpeg_librosa_signal",
                "notes": f"rms={rms:.4f}; zcr={zcr:.4f}; centroid={centroid:.1f}",
                "source_phase": "video_processing.audio_analysis",
            }
        )
    return rows


def metadata_audio_events(asset: VideoAsset, method: str) -> list[dict[str, object]]:
    segments = max(1, math.ceil(asset.duration_seconds / 60))
    length = asset.duration_seconds / segments
    rows: list[dict[str, object]] = []
    for index in range(1, segments + 1):
        start = round((index - 1) * length, 3)
        end = round(asset.duration_seconds if index == segments else index * length, 3)
        event_type = "river_noise_candidate" if any(token in asset.video_path.lower() for token in ["gopr", "gx"]) else "conversation_candidate"
        rows.append(
            {
                "media_set": asset.media_set,
                "video_path": asset.video_path,
                "moment_id": asset.moment_id,
                "event_id": f"{slugify(Path(asset.video_path).stem)}_audio_{index:03d}",
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": round(end - start, 3),
                "audio_event_type": event_type,
                "intensity_score": 55,
                "confidence": 0.25,
                "detection_method": method,
                "notes": "fallback audio event from metadata only",
                "source_phase": "video_processing.audio_analysis",
            }
        )
    return rows


def classify_audio_event(asset: VideoAsset, rms: float, rms_mean: float, rms_std: float, zcr: float, centroid: float) -> tuple[str, float]:
    if rms < max(0.003, rms_mean * 0.25):
        return "silence_or_quiet", 0.78
    if rms_std and rms > rms_mean + rms_std * 1.8:
        if zcr > 0.08 or centroid > 2600:
            return "cheering_or_laughing_candidate", 0.62
        return "loud_reaction_candidate", 0.58
    if asset.moment_type in {"rapids", "splash", "launch"} or "gopr" in asset.video_path.lower() or "gx" in asset.video_path.lower():
        if rms > rms_mean * 0.7 and centroid > 900:
            return "river_or_action_noise", 0.64
    if 0.015 <= rms <= max(rms_mean + rms_std, 0.12) and 0.03 <= zcr <= 0.13:
        return "conversation_candidate", 0.5
    if centroid > 2500:
        return "wind_or_high_frequency_noise", 0.45
    return "ambient_audio", 0.42


def run_transcript(config: VideoProcessingConfig, project_root: Path, assets: list[VideoAsset]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    backend = config.transcript_backend.strip().lower()
    summary = [f"# Transcript Summary\n", f"Backend: {backend}", ""]
    if not config.transcript_enabled or backend == "none":
        summary.append("Transcript extraction skipped by config.")
    elif backend == "local_whisper":
        rows, message = run_local_whisper_transcript(config, project_root, assets)
        summary.append(message)
    elif backend == "openai":
        rows, message = run_openai_transcript(config, project_root, assets)
        summary.append(message)
    else:
        message = f"Unsupported transcript backend: {backend}"
        if config.transcript_required:
            raise ValueError(message)
        summary.append(message)
    write_csv(config.transcript.output_dir / "transcript_segments.csv", TRANSCRIPT_COLUMNS, rows)
    write_activity_csvs(config.transcript.output_dir, "transcript_segments.csv", TRANSCRIPT_COLUMNS, rows)
    write_text(config.transcript.output_dir / "transcript_summary.md", "\n".join(summary) + "\n")
    full_text = "\n\n".join(f"## {row['video_path']}\n\n{row['text']}" for row in rows)
    write_text(config.transcript.output_dir / "transcript_full_text.md", full_text or "# Transcript Full Text\n\nNo transcript segments generated.\n")
    return rows


def run_local_whisper_transcript(config: VideoProcessingConfig, project_root: Path, assets: list[VideoAsset]) -> tuple[list[dict[str, object]], str]:
    if config.dry_run:
        return [], "Dry run: local Whisper was not invoked."
    if shutil.which("whisper") is None:
        message = "local_whisper backend selected, but `whisper` command is not installed."
        if config.transcript_required:
            raise FileNotFoundError(message)
        return [], message
    rows: list[dict[str, object]] = []
    json_dir = config.transcript.output_dir / "local_whisper_json"
    json_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        source = resolve_project_path(project_root, asset.video_path)
        try:
            subprocess.run(
                [
                    "whisper",
                    str(source),
                    "--model",
                    config.transcript_local_model,
                    "--output_format",
                    "json",
                    "--output_dir",
                    str(json_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            message = f"local_whisper transcription failed for {asset.video_path}: {exc.stderr.strip() or exc}"
            if config.transcript_required:
                raise ValueError(message) from exc
            return rows, message
        output_json = json_dir / f"{source.stem}.json"
        if not output_json.exists():
            continue
        loaded = json.loads(output_json.read_text(encoding="utf-8"))
        segments = loaded.get("segments", []) if isinstance(loaded, dict) else []
        if not isinstance(segments, list):
            continue
        for index, segment in enumerate(segments, start=1):
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            start = safe_float(str(segment.get("start", 0)))
            end = safe_float(str(segment.get("end", start)))
            rows.append(
                {
                    "media_set": asset.media_set,
                    "video_path": asset.video_path,
                    "moment_id": asset.moment_id,
                    "segment_id": f"{slugify(Path(asset.video_path).stem)}_transcript_{index:03d}",
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                    "duration_seconds": round(max(end - start, 0), 3),
                    "text": text,
                    "language": str(loaded.get("language", "")) if isinstance(loaded, dict) else "",
                    "confidence": "",
                    "speaker_label": "",
                    "keywords": keywords_from_text(text),
                    "source_phase": "video_processing.transcript.local_whisper",
                }
            )
    return rows, f"local_whisper generated {len(rows)} transcript segment rows."


def run_openai_transcript(config: VideoProcessingConfig, project_root: Path, assets: list[VideoAsset]) -> tuple[list[dict[str, object]], str]:
    if config.dry_run:
        return [], "Dry run: OpenAI transcription API was not called."
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        message = "openai transcript backend selected, but OPENAI_API_KEY is not set."
        if config.transcript_required:
            raise ValueError(message)
        return [], message
    if not assets:
        return [], "No videos available for OpenAI transcription."
    rows: list[dict[str, object]] = []
    for asset in assets:
        source = resolve_project_path(project_root, asset.video_path)
        try:
            response = openai_transcribe_file(source, config.transcript_model, api_key)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            message = f"OpenAI transcription failed for {asset.video_path}: {exc}"
            if config.transcript_required:
                raise ValueError(message) from exc
            return rows, message
        text = str(response.get("text", "")).strip()
        if not text:
            continue
        rows.append(
            {
                "media_set": asset.media_set,
                "video_path": asset.video_path,
                "moment_id": asset.moment_id,
                "segment_id": f"{slugify(Path(asset.video_path).stem)}_transcript_001",
                "start_seconds": 0,
                "end_seconds": round(asset.duration_seconds, 3),
                "duration_seconds": round(asset.duration_seconds, 3),
                "text": text,
                "language": str(response.get("language", "")),
                "confidence": "",
                "speaker_label": "",
                "keywords": keywords_from_text(text),
                "source_phase": "video_processing.transcript.openai",
            }
        )
    return rows, f"OpenAI transcription generated {len(rows)} transcript segment rows."


def openai_transcribe_file(source: Path, model: str, api_key: str) -> dict[str, object]:
    boundary = "----MemoryCuratorBoundary"
    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    body = multipart_body(
        boundary,
        fields={
            "model": model,
            "response_format": "json",
        },
        files={
            "file": (source.name, mime_type, source.read_bytes()),
        },
    )
    request = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read().decode("utf-8")
    loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        raise ValueError("OpenAI transcription response was not a JSON object")
    return loaded


def multipart_body(
    boundary: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, mime_type, data) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)


def keywords_from_text(text: str) -> str:
    words = []
    for token in text.lower().replace("\n", " ").split():
        cleaned = "".join(char for char in token if char.isalnum())
        if len(cleaned) >= 5 and cleaned not in words:
            words.append(cleaned)
        if len(words) >= 12:
            break
    return ",".join(words)


def run_timeline_builder(
    config: VideoProcessingConfig,
    project_root: Path,
    assets: list[VideoAsset],
    scenes: list[dict[str, object]],
    clips: list[dict[str, object]],
    clip_scores: list[dict[str, object]],
    frames: list[dict[str, object]],
    audio_events: list[dict[str, object]],
    transcripts: list[dict[str, object]],
) -> tuple[list[dict[str, object]], Path]:
    rows: list[dict[str, object]] = []
    scores_by_clip = {str(row["clip_id"]): row for row in clip_scores}
    audio_by_video = group_by(audio_events, "video_path")
    transcript_by_video = group_by(transcripts, "video_path")
    frames_by_scene = group_by(frames, "scene_id")
    clips_by_scene = group_by(clips, "scene_id")
    event_index_by_video: dict[str, int] = {}
    for scene in scenes:
        video_path = str(scene["video_path"])
        event_index_by_video[video_path] = event_index_by_video.get(video_path, 0) + 1
        scene_clips = clips_by_scene.get(str(scene["scene_id"]), [])
        best_clip = max(scene_clips, key=lambda item: safe_float(str(scores_by_clip.get(str(item["clip_id"]), {}).get("overall_score", 0))), default={})
        best_score = scores_by_clip.get(str(best_clip.get("clip_id", "")), {})
        audio_id = first_overlapping_id(audio_by_video.get(video_path, []), scene, "event_id")
        transcript_id = first_overlapping_id(transcript_by_video.get(video_path, []), scene, "segment_id")
        frame_ids = ",".join(str(frame["frame_id"]) for frame in frames_by_scene.get(str(scene["scene_id"]), [])[:5])
        rows.append(
            {
                "media_set": scene["media_set"],
                "video_path": video_path,
                "moment_id": scene["moment_id"],
                "timeline_event_id": f"{scene['scene_id']}_timeline",
                "event_index": event_index_by_video[video_path],
                "start_seconds": scene["start_seconds"],
                "end_seconds": scene["end_seconds"],
                "duration_seconds": scene["duration_seconds"],
                "event_type": "scene",
                "event_label": scene["scene_label"],
                "scene_id": scene["scene_id"],
                "clip_id": best_clip.get("clip_id", ""),
                "audio_event_id": audio_id,
                "transcript_segment_id": transcript_id,
                "frame_ids": frame_ids,
                "story_importance_score": best_score.get("story_score", 50),
                "reel_value_score": best_score.get("reel_score", 50),
                "documentary_value_score": best_score.get("documentary_score", 50),
                "time_capsule_value_score": best_score.get("time_capsule_score", 50),
                "notes": "semantic timeline event from scene, clip, frame, audio, and transcript stage outputs",
                "source_phase": "video_processing.timeline_builder",
            }
        )
    rows = refine_timeline_with_ai(config, rows)
    timeline_csv = config.timeline_builder.output_dir / "video_timeline.csv"
    write_csv(timeline_csv, TIMELINE_COLUMNS, rows)
    write_activity_csvs(config.timeline_builder.output_dir, "video_timeline.csv", TIMELINE_COLUMNS, rows)
    config.timeline_builder.output_dir.mkdir(parents=True, exist_ok=True)
    (config.timeline_builder.output_dir / "video_timeline.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    write_text(config.timeline_builder.output_dir / "timeline_summary.md", f"# Timeline Builder Summary\n\nTimeline events: {len(rows)}\n")
    return rows, timeline_csv


def group_by(rows: list[dict[str, object]], key: str) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key, "")), []).append(row)
    return grouped


def first_overlapping_id(rows: list[dict[str, object]], interval: dict[str, object], id_key: str) -> str:
    start = safe_float(str(interval.get("start_seconds", 0)))
    end = safe_float(str(interval.get("end_seconds", 0)))
    for row in rows:
        row_start = safe_float(str(row.get("start_seconds", 0)))
        row_end = safe_float(str(row.get("end_seconds", 0)))
        if row_start < end and row_end > start:
            return str(row.get(id_key, ""))
    return ""


def refine_timeline_with_ai(config: VideoProcessingConfig, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not config.timeline_ai_enabled:
        return rows
    if config.dry_run:
        return add_ai_status_to_timeline(rows, "AI labeling skipped in dry run")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        message = "Timeline AI labeling requested, but OPENAI_API_KEY is not set."
        if config.timeline_ai_required:
            raise ValueError(message)
        return add_ai_status_to_timeline(rows, message)
    refined: list[dict[str, object]] = []
    for batch_start in range(0, len(rows), 25):
        batch = rows[batch_start : batch_start + 25]
        try:
            refined.extend(refine_timeline_batch(config, api_key, batch))
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            message = f"Timeline AI labeling failed: {exc}"
            if config.timeline_ai_required:
                raise ValueError(message) from exc
            return add_ai_status_to_timeline(rows, message)
    return refined or rows


def add_ai_status_to_timeline(rows: list[dict[str, object]], message: str) -> list[dict[str, object]]:
    updated = []
    for row in rows:
        copy = dict(row)
        copy["notes"] = f"{copy.get('notes', '')}; {message}".strip("; ")
        updated.append(copy)
    return updated


def refine_timeline_batch(config: VideoProcessingConfig, api_key: str, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    compact_rows = [
        {
            "timeline_event_id": row["timeline_event_id"],
            "moment_id": row["moment_id"],
            "event_label": row["event_label"],
            "duration_seconds": row["duration_seconds"],
            "story_importance_score": row["story_importance_score"],
            "reel_value_score": row["reel_value_score"],
            "documentary_value_score": row["documentary_value_score"],
            "notes": row["notes"],
        }
        for row in rows
    ]
    payload = {
        "model": config.timeline_ai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You label travel video timeline events for media curation. "
                    "Return concise labels such as 'Rapids action', 'Group reaction', "
                    "'Walking transition', or 'Lunch conversation'. Do not invent people names."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"events": compact_rows}),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "timeline_labels",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "events": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "timeline_event_id": {"type": "string"},
                                    "event_label": {"type": "string"},
                                    "notes": {"type": "string"},
                                },
                                "required": ["timeline_event_id", "event_label", "notes"],
                            },
                        }
                    },
                    "required": ["events"],
                },
            }
        },
    }
    data = post_openai_json(config.timeline_ai_endpoint, api_key, payload)
    content = extract_response_text(data)
    parsed = json.loads(content)
    label_by_id = {item["timeline_event_id"]: item for item in parsed.get("events", []) if isinstance(item, dict)}
    refined = []
    for row in rows:
        copy = dict(row)
        item = label_by_id.get(str(row["timeline_event_id"]))
        if item:
            copy["event_label"] = str(item.get("event_label", copy["event_label"]))[:120]
            copy["notes"] = f"{copy.get('notes', '')}; AI label: {item.get('notes', '')}".strip("; ")
        refined.append(copy)
    return refined


def post_openai_json(endpoint: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        loaded = json.loads(response.read().decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("OpenAI response was not a JSON object")
    return loaded


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts: list[str] = []
    for output in data.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    texts.append(text)
    if not texts:
        raise ValueError("OpenAI response did not include output text")
    return "\n".join(texts)


def write_processing_manifest(
    config: VideoProcessingConfig,
    project_root: Path,
    assets: list[VideoAsset],
    timeline_csv: Path | None,
) -> Path:
    rows = []
    for asset in assets:
        rows.append(
            {
                "media_set": asset.media_set,
                "video_path": asset.video_path,
                "moment_id": asset.moment_id,
                "scene_manifest_path": path_text(config.scene_detection.output_dir / asset.media_set / "scene_manifest.csv", project_root),
                "clip_manifest_path": path_text(config.clip_segmentation.output_dir / asset.media_set / "clip_manifest.csv", project_root),
                "clip_scores_path": path_text(config.clip_scoring.output_dir / asset.media_set / "clip_scores.csv", project_root),
                "frame_manifest_path": path_text(config.frame_analysis.output_dir / asset.media_set / "frame_manifest.csv", project_root),
                "audio_events_path": path_text(config.audio_analysis.output_dir / asset.media_set / "audio_events.csv", project_root),
                "transcript_segments_path": path_text(config.transcript.output_dir / asset.media_set / "transcript_segments.csv", project_root),
                "timeline_path": path_text(config.timeline_builder.output_dir / asset.media_set / "video_timeline.csv", project_root) if timeline_csv else "",
                "processing_status": "complete",
                "source_phase": "video_processing",
            }
        )
    manifest = config.output_dir / "video_processing_manifest.csv"
    write_csv(manifest, VIDEO_PROCESSING_MANIFEST_COLUMNS, rows)
    return manifest


def extract_frame(source: Path, destination: Path, timestamp: float) -> int:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return 0
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(timestamp), "-i", str(source), "-frames:v", "1", str(destination)],
        check=True,
    )
    return 1


def extract_clip(source: Path, destination: Path, start: float, duration: float) -> int:
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return 0
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(start), "-i", str(source), "-t", str(duration), "-c", "copy", str(destination)],
        check=True,
    )
    return 1


def selected_stages(stage: str | None) -> list[str]:
    if stage is None or stage == "all":
        return VIDEO_STAGES
    normalized = stage.strip().lower().replace("_", "-")
    if normalized not in VIDEO_STAGES:
        raise ValueError(f"Unknown video-processing stage: {stage}. Expected one of: {', '.join(VIDEO_STAGES)}")
    return [normalized]


def run_video_processing(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
    stage: str | None = None,
) -> VideoProcessingResult:
    video_config = load_video_processing_config(config, project_root)
    if execute:
        video_config = replace(video_config, dry_run=False)
    if not video_config.enabled and not include_disabled:
        raise ValueError("Video Processing is disabled in config. Enable modules.video_processing.enabled or pass --include-disabled.")

    stages_to_run = selected_stages(stage)
    assets = load_video_assets(video_config, project_root)
    assets_by_path = {asset.video_path: asset for asset in assets}
    generated = 0
    scenes: list[dict[str, object]] = []
    clips: list[dict[str, object]] = []
    clip_scores: list[dict[str, object]] = []
    frames: list[dict[str, object]] = []
    audio_events: list[dict[str, object]] = []
    transcripts: list[dict[str, object]] = []
    timeline: list[dict[str, object]] = []
    timeline_csv: Path | None = None
    metrics_by_path: dict[str, VideoMetrics] = {}

    needs_scenes = bool({"scene-detection", "clip-segmentation", "clip-scoring", "frame-analysis", "timeline-builder"} & set(stages_to_run))
    needs_clips = bool({"clip-segmentation", "clip-scoring", "timeline-builder"} & set(stages_to_run))

    if needs_scenes and video_config.scene_detection.enabled:
        scenes, count = run_scene_detection(video_config, project_root, assets, metrics_by_path)
        generated += count
    if needs_clips and video_config.clip_segmentation.enabled:
        if not scenes:
            scenes, count = run_scene_detection(video_config, project_root, assets, metrics_by_path)
            generated += count
        clips, count = run_clip_segmentation(video_config, project_root, assets_by_path, scenes)
        generated += count
    if "clip-scoring" in stages_to_run or "timeline-builder" in stages_to_run:
        if not clips:
            if not scenes:
                scenes, count = run_scene_detection(video_config, project_root, assets, metrics_by_path)
                generated += count
            clips, count = run_clip_segmentation(video_config, project_root, assets_by_path, scenes)
            generated += count
        if video_config.clip_scoring.enabled:
            clip_scores = run_clip_scoring(video_config, project_root, assets_by_path, clips, metrics_by_path)
    if "frame-analysis" in stages_to_run or "timeline-builder" in stages_to_run:
        if not scenes:
            scenes, count = run_scene_detection(video_config, project_root, assets, metrics_by_path)
            generated += count
        if video_config.frame_analysis.enabled:
            frames, count = run_frame_analysis(video_config, project_root, assets_by_path, scenes, clips, metrics_by_path)
            generated += count
    if "audio-analysis" in stages_to_run or "timeline-builder" in stages_to_run:
        if video_config.audio_analysis.enabled:
            audio_events, count = run_audio_analysis(video_config, project_root, assets)
            generated += count
    if "transcript" in stages_to_run or "timeline-builder" in stages_to_run:
        if video_config.transcript.enabled:
            transcripts = run_transcript(video_config, project_root, assets)
    if "timeline-builder" in stages_to_run and video_config.timeline_builder.enabled:
        if not scenes:
            scenes, count = run_scene_detection(video_config, project_root, assets, metrics_by_path)
            generated += count
        if not clips:
            clips, count = run_clip_segmentation(video_config, project_root, assets_by_path, scenes)
            generated += count
        if not clip_scores:
            clip_scores = run_clip_scoring(video_config, project_root, assets_by_path, clips, metrics_by_path)
        timeline, timeline_csv = run_timeline_builder(
            video_config,
            project_root,
            assets,
            scenes,
            clips,
            clip_scores,
            frames,
            audio_events,
            transcripts,
        )

    manifest = write_processing_manifest(video_config, project_root, assets, timeline_csv)
    return VideoProcessingResult(
        video_count=len(assets),
        scene_count=len(scenes),
        clip_count=len(clips),
        scored_clip_count=len(clip_scores),
        frame_count=len(frames),
        audio_event_count=len(audio_events),
        transcript_segment_count=len(transcripts),
        timeline_event_count=len(timeline),
        generated_media_count=generated,
        manifest_csv=manifest,
        dry_run=video_config.dry_run,
        stages=stages_to_run,
    )
