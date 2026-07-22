"""Reel Builder planning and rendering."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.activity import ActivityProfile, load_activity_profile
from memory_curator_engine.common.execution import ordered_map
from memory_curator_engine.common.media_sets import configured_media_sets, media_set_activity_map
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import inventory_jobs_from_config, parse_enabled
from memory_curator_engine.video.report import ffmpeg_executable


REEL_CANDIDATE_COLUMNS = [
    "reel_id",
    "reel_style",
    "target_duration_seconds",
    "media_set",
    "activity",
    "moment_id",
    "moment_type",
    "story_order",
    "moment_title",
    "timeline_event_id",
    "timeline_label",
    "source_media_path",
    "source_file_type",
    "source_video_duration_seconds",
    "segment_start_seconds",
    "segment_end_seconds",
    "segment_duration_seconds",
    "clip_id",
    "clip_overall_score",
    "quality_score",
    "action_score",
    "story_score",
    "people_score",
    "audio_energy_score",
    "diversity_score",
    "adventure_score",
    "cinematic_score",
    "memory_score",
    "emotion_score",
    "activity_score",
    "activity_bucket",
    "activity_reason",
    "visual_tags",
    "activity_confidence",
    "activity_mismatch",
    "speed_factor",
    "audio_decision",
    "audit_reason",
    "final_reel_score",
    "candidate_role",
    "selection_status",
    "selection_reason",
    "exclusion_reason",
]

REEL_HIGHLIGHT_TIMELINE_COLUMNS = [
    "highlight_sequence",
    "media_set",
    "activity",
    "source_media_path",
    "source_start_seconds",
    "source_end_seconds",
    "source_duration_seconds",
    "timeline_event_id",
    "timeline_label",
    "moment_id",
    "moment_title",
    "visual_tags",
    "activity_confidence",
    "highlight_score",
    "recommended_speed",
    "selection_role",
    "selection_reason",
]

REEL_SELECTION_COLUMNS = [
    "reel_id",
    "reel_style",
    "reel_sequence",
    "media_set",
    "activity",
    "moment_id",
    "moment_title",
    "timeline_event_id",
    "source_media_path",
    "source_start_seconds",
    "source_end_seconds",
    "output_start_seconds",
    "output_end_seconds",
    "output_duration_seconds",
    "crop_mode",
    "crop_anchor",
    "audio_mode",
    "caption_text",
    "selected_role",
    "activity_bucket",
    "activity_score",
    "adventure_score",
    "emotion_score",
    "visual_tags",
    "activity_confidence",
    "activity_mismatch",
    "speed_factor",
    "final_reel_score",
    "selection_reason",
]

REEL_EDIT_DECISION_COLUMNS = [
    "reel_id",
    "edit_sequence",
    "source_media_path",
    "source_start_seconds",
    "source_end_seconds",
    "output_start_seconds",
    "output_end_seconds",
    "output_width",
    "output_height",
    "aspect_ratio",
    "transform",
    "crop_anchor_x",
    "crop_anchor_y",
    "source_audio_enabled",
    "music_enabled",
    "playback_speed",
    "caption_enabled",
    "caption_text",
    "transition_type",
    "transition_duration_seconds",
]

REEL_MANIFEST_COLUMNS = [
    "reel_id",
    "trip_slug",
    "reel_style",
    "media_sets",
    "target_duration_seconds",
    "actual_duration_seconds",
    "aspect_ratio",
    "output_width",
    "output_height",
    "rendered_file_path",
    "edit_decision_path",
    "selection_path",
    "report_path",
    "dry_run",
    "created_at",
    "render_status",
    "render_reason",
]


@dataclass(frozen=True)
class ReelRenderConfig:
    enabled: bool
    width: int
    height: int
    fps: int
    crop_mode: str
    audio_mode: str
    music_enabled: bool
    music_path: str
    music_volume: float
    source_audio_volume: float
    natural_audio_enabled_sets: tuple[str, ...]
    mute_phrases: tuple[str, ...]
    mute_phrase_padding_seconds: float
    mute_action_camera_boundary_seconds: float
    video_codec: str
    overwrite_policy: str


@dataclass(frozen=True)
class ReelConfig:
    enabled: bool
    dry_run: bool
    trip_slug: str
    input_story_manifest: Path
    input_moments: Path
    input_moment_assets: Path
    input_clip_scores: Path
    input_clip_manifest: Path
    input_video_timeline: Path
    input_audio_events: Path
    input_transcript_segments: Path
    output_dir: Path
    curated_dir: Path
    exports_dir: Path
    reel_id: str
    style: str
    media_sets: set[str]
    target_duration_seconds: float
    min_segment_seconds: float
    max_segment_seconds: float
    max_segments_per_moment: int
    max_segments_per_source_video: int
    min_clips: int
    max_clips: int
    chronological: str
    variant: str
    include_moment_types: set[str]
    required_moment_types: list[str]
    moment_story_order: list[str]
    group_perspective_patterns: list[str]
    exclude_source_patterns: list[str]
    group_perspective_min_segments: int
    promote_high_action_arrival: bool
    promoted_action_min_audio_score: float
    promoted_action_min_start_seconds: float
    suppress_low_motion_water_clips: bool
    activity_profile: ActivityProfile
    render: ReelRenderConfig
    reels_per_activity: int
    intelligence_enabled: bool
    intelligence_backend: str
    intelligence_sample_frames: int
    reject_activity_mismatch: bool
    min_activity_confidence: float
    speed_ramps_enabled: bool
    speed_ramp_fraction: float
    max_speed_factor: float
    refine_segment_windows: bool
    max_window_candidates: int
    windows_per_clip: int
    highlight_timeline_enabled: bool
    highlight_max_per_source_video: int


@dataclass(frozen=True)
class ReelCandidate:
    reel_id: str
    reel_style: str
    target_duration_seconds: float
    media_set: str
    activity: str
    moment_id: str
    moment_type: str
    story_order: float
    moment_title: str
    timeline_event_id: str
    timeline_label: str
    source_media_path: str
    source_file_type: str
    source_video_duration_seconds: float
    segment_start_seconds: float
    segment_end_seconds: float
    segment_duration_seconds: float
    clip_id: str
    clip_overall_score: float
    quality_score: float
    action_score: float
    story_score: float
    people_score: float
    audio_energy_score: float
    diversity_score: float
    adventure_score: float
    cinematic_score: float
    memory_score: float
    emotion_score: float
    activity_score: float
    activity_bucket: str
    activity_reason: str
    visual_tags: str
    activity_confidence: float
    activity_mismatch: str
    speed_factor: float
    audio_decision: str
    audit_reason: str
    final_reel_score: float
    candidate_role: str


@dataclass(frozen=True)
class ReelSelection:
    candidate: ReelCandidate
    sequence: int
    output_start_seconds: float
    output_end_seconds: float
    selection_reason: str


@dataclass(frozen=True)
class ReelResult:
    candidate_count: int
    selected_count: int
    actual_duration_seconds: float
    rendered_count: int
    render_status: str
    rendered_file_path: Path
    reel_candidates_csv: Path
    reel_selection_csv: Path
    reel_edit_decisions_csv: Path
    reel_manifest_csv: Path
    reel_report_md: Path
    dry_run: bool


@dataclass(frozen=True)
class MasterHighlightResult:
    selected_count: int
    actual_duration_seconds: float
    render_status: str
    rendered_file_path: Path
    selection_csv: Path
    edit_decisions_csv: Path
    dry_run: bool


@dataclass(frozen=True)
class SegmentAudit:
    visual_tags: tuple[str, ...]
    activity_confidence: float
    activity_mismatch: bool
    speed_factor: float
    audio_decision: str
    reason: str


REEL_VARIANTS = [
    "instagram_reel",
    "full_highlight",
    "story_continuity",
    "action_audio",
    "water_focus",
    "people_reactions",
    "cinematic_story",
    "selected_timeline_fun",
]
SEGMENT_AUDIT_CACHE_VERSION = "v21"
SEGMENT_AUDIT_CACHE: dict[tuple[str, float, float, str], SegmentAudit] = {}
VIDEO_CAPTURE_CACHE: dict[str, Any] = {}
SOURCE_CHRONOLOGY_BY_PATH: dict[str, float] = {}
SOURCE_CHRONOLOGY_BY_NAME: dict[str, float] = {}
SOURCE_DURATION_BY_PATH: dict[str, float] = {}
SOURCE_DURATION_BY_NAME: dict[str, float] = {}
MUTED_TRANSCRIPT_WINDOWS_CACHE: dict[tuple[str, tuple[str, ...], float], dict[str, list[tuple[float, float]]]] = {}


def load_source_chronology_index(config: Config, project_root: Path, media_sets: set[str] | None = None) -> int:
    """Load source capture/created timestamps from Inventory reports for chronological edits."""
    SOURCE_CHRONOLOGY_BY_PATH.clear()
    SOURCE_CHRONOLOGY_BY_NAME.clear()
    SOURCE_DURATION_BY_PATH.clear()
    SOURCE_DURATION_BY_NAME.clear()
    name_candidates: dict[str, set[float]] = {}
    duration_name_candidates: dict[str, set[float]] = {}
    try:
        jobs = inventory_jobs_from_config(config=config, project_root=project_root, only_names=media_sets)
    except ValueError:
        jobs = inventory_jobs_from_config(config=config, project_root=project_root)
    loaded = 0
    for job in jobs:
        if media_sets is not None and job.name not in media_sets:
            continue
        if not job.output_csv.exists():
            continue
        with job.output_csv.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                timestamp = (
                    parse_inventory_timestamp(row.get("capture_date"))
                    or parse_inventory_timestamp(row.get("created_date"))
                    or parse_inventory_timestamp(row.get("modified_date"))
                )
                relative_path = (row.get("relative_path") or "").strip()
                filename = (row.get("filename") or Path(relative_path).name).strip()
                if timestamp is None or not relative_path:
                    continue
                normalized_path = normalize_source_path(relative_path)
                SOURCE_CHRONOLOGY_BY_PATH[normalized_path] = timestamp
                duration = safe_float(row.get("duration_seconds"), 0.0)
                if duration > 0:
                    SOURCE_DURATION_BY_PATH[normalized_path] = duration
                if filename:
                    name_candidates.setdefault(filename.lower(), set()).add(timestamp)
                    if duration > 0:
                        duration_name_candidates.setdefault(filename.lower(), set()).add(round(duration, 3))
                loaded += 1
    for filename, timestamps in name_candidates.items():
        if len(timestamps) == 1:
            SOURCE_CHRONOLOGY_BY_NAME[filename] = next(iter(timestamps))
    for filename, durations in duration_name_candidates.items():
        if len(durations) == 1:
            SOURCE_DURATION_BY_NAME[filename] = next(iter(durations))
    return loaded


def parse_inventory_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        return datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return None


def normalize_source_path(path: str) -> str:
    return Path(path).as_posix().lower()


def load_segment_audit_cache(path: Path) -> int:
    SEGMENT_AUDIT_CACHE.clear()
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    loaded = 0
    for key_text, payload in raw.items():
        try:
            video_path, start, end, profile = key_text.split("|", 3)
            key = (video_path, float(start), float(end), profile)
            SEGMENT_AUDIT_CACHE[key] = SegmentAudit(
                visual_tags=tuple(payload.get("visual_tags", [])),
                activity_confidence=float(payload.get("activity_confidence", 0)),
                activity_mismatch=bool(payload.get("activity_mismatch", False)),
                speed_factor=float(payload.get("speed_factor", 1.0)),
                audio_decision=str(payload.get("audio_decision", "")),
                reason=str(payload.get("reason", "disk_cache")),
            )
            loaded += 1
        except (AttributeError, TypeError, ValueError):
            continue
    return loaded


def save_segment_audit_cache(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        segment_audit_cache_key(key): {
            "visual_tags": list(audit.visual_tags),
            "activity_confidence": audit.activity_confidence,
            "activity_mismatch": audit.activity_mismatch,
            "speed_factor": audit.speed_factor,
            "audio_decision": audit.audio_decision,
            "reason": audit.reason,
        }
        for key, audit in sorted(SEGMENT_AUDIT_CACHE.items(), key=lambda item: item[0])
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return len(payload)


def segment_audit_cache_key(key: tuple[str, float, float, str]) -> str:
    video_path, start, end, profile = key
    return f"{video_path}|{start:.2f}|{end:.2f}|{profile}"


def load_reel_config(config: Config, project_root: Path) -> ReelConfig:
    curated_root = config_value(config, "project.curated_root", "input_data/curated")
    reel_id = str(config_value(config, "reel_builder.reel_id", "sample_activity_highlight"))
    style = str(config_value(config, "reel_builder.style", "highlight"))
    media_sets = parse_media_sets(config_value(config, "reel_builder.media_sets", ["rafting"]))
    profile_name = str(config_value(config, "reel_builder.activity_profile", next(iter(sorted(media_sets)), "default")))
    render_section = config_value(config, "reel_builder.render", {}) or {}
    music_section = render_section.get("music", {}) or {}
    natural_audio_section = render_section.get("natural_audio", {}) or {}
    intelligence_section = config_value(config, "reel_builder.intelligence", {}) or {}
    profile = load_activity_profile(config, profile_name)
    min_segment_seconds = float(config_value(config, "reel_builder.selection.min_segment_seconds", 1.5))
    if profile.optimization_goal in {"memory", "social", "cinematic"} or profile_values_people_terms(profile):
        min_segment_seconds = min(min_segment_seconds, 2.0)
    return ReelConfig(
        enabled=parse_enabled(config_value(config, "modules.reel_builder.enabled", False), "reel_builder"),
        dry_run=parse_enabled(config_value(config, "reel_builder.dry_run", True), "reel_builder.dry_run"),
        trip_slug=str(config_value(config, "project.trip_slug", "trip")),
        input_story_manifest=resolve_project_path(project_root, config_value(config, "reel_builder.input_story_manifest", "MemoryCurator/05 Story Builder/story_manifest.csv")),
        input_moments=resolve_project_path(project_root, config_value(config, "reel_builder.input_moments", "MemoryCurator/05 Story Builder/moments.csv")),
        input_moment_assets=resolve_project_path(project_root, config_value(config, "reel_builder.input_moment_assets", "MemoryCurator/05 Story Builder/moment_assets.csv")),
        input_clip_scores=resolve_project_path(project_root, config_value(config, "reel_builder.input_clip_scores", "MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv")),
        input_clip_manifest=resolve_project_path(project_root, config_value(config, "reel_builder.input_clip_manifest", "MemoryCurator/07 Video Processing/clip-segmentation/clip_manifest.csv")),
        input_video_timeline=resolve_project_path(project_root, config_value(config, "reel_builder.input_video_timeline", "MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv")),
        input_audio_events=resolve_project_path(project_root, config_value(config, "reel_builder.input_audio_events", "MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv")),
        input_transcript_segments=resolve_project_path(project_root, config_value(config, "reel_builder.input_transcript_segments", "MemoryCurator/07 Video Processing/transcript/transcript_segments.csv")),
        output_dir=resolve_project_path(project_root, config_value(config, "reel_builder.output_dir", "MemoryCurator/09 Reel Builder")),
        curated_dir=resolve_project_path(project_root, config_value(config, "reel_builder.curated_dir", f"{curated_root}/09 Reel Builder")),
        exports_dir=resolve_project_path(project_root, config_value(config, "reel_builder.exports_dir", f"{curated_root}/09 Reel Builder/exports")),
        reel_id=reel_id,
        style=style,
        media_sets=media_sets,
        target_duration_seconds=float(config_value(config, "reel_builder.target_duration_seconds", 60)),
        min_segment_seconds=min_segment_seconds,
        max_segment_seconds=float(config_value(config, "reel_builder.selection.max_segment_seconds", 5)),
        max_segments_per_moment=int(config_value(config, "reel_builder.selection.max_segments_per_moment", 3)),
        max_segments_per_source_video=int(config_value(config, "reel_builder.selection.max_segments_per_source_video", 5)),
        min_clips=int(config_value(config, "reel_builder.selection.min_clips", 8)),
        max_clips=int(config_value(config, "reel_builder.selection.max_clips", 18)),
        chronological=str(config_value(config, "reel_builder.selection.chronological", "mostly")),
        variant=str(config_value(config, "reel_builder.variant", "story_continuity")),
        include_moment_types=parse_list(config_value(config, "reel_builder.selection.include_moment_types", default_reel_moment_types())),
        required_moment_types=list(parse_ordered_list(config_value(config, "reel_builder.selection.required_moment_types", default_required_moment_types()))),
        moment_story_order=list(parse_ordered_list(config_value(config, "reel_builder.selection.moment_story_order", default_reel_moment_types()))),
        group_perspective_patterns=list(parse_ordered_list(config_value(config, "reel_builder.selection.group_perspective_patterns", []))),
        exclude_source_patterns=list(parse_ordered_list(config_value(config, "reel_builder.selection.exclude_source_patterns", []))),
        group_perspective_min_segments=int(config_value(config, "reel_builder.selection.group_perspective_min_segments", 0)),
        promote_high_action_arrival=parse_enabled(config_value(config, "reel_builder.selection.promote_high_action_arrival", False), "reel_builder.selection.promote_high_action_arrival"),
        promoted_action_min_audio_score=float(config_value(config, "reel_builder.selection.promoted_action_min_audio_score", 80)),
        promoted_action_min_start_seconds=float(config_value(config, "reel_builder.selection.promoted_action_min_start_seconds", 30)),
        suppress_low_motion_water_clips=parse_enabled(
            config_value(config, "reel_builder.selection.suppress_low_motion_water_clips", True),
            "reel_builder.selection.suppress_low_motion_water_clips",
        ),
        activity_profile=profile,
        render=ReelRenderConfig(
            enabled=parse_enabled(render_section.get("enabled", False), "reel_builder.render.enabled"),
            width=int(render_section.get("width", 1080)),
            height=int(render_section.get("height", 1920)),
            fps=int(render_section.get("fps", 30)),
            crop_mode=str(render_section.get("crop_mode", "center_crop")),
            audio_mode=str(render_section.get("audio_mode", "keep_source")),
            music_enabled=parse_enabled(music_section.get("enabled", False), "reel_builder.render.music.enabled"),
            music_path=str(music_section.get("path") or ""),
            music_volume=float(music_section.get("volume", 0.85)),
            source_audio_volume=float(music_section.get("source_audio_volume", 1.0))
            if not parse_ordered_list(natural_audio_section.get("enabled_media_sets", []))
            else float(natural_audio_section.get("source_audio_volume", 1.0)),
            natural_audio_enabled_sets=tuple(parse_ordered_list(natural_audio_section.get("enabled_media_sets", []))),
            mute_phrases=tuple(parse_ordered_list(natural_audio_section.get("mute_phrases", []))),
            mute_phrase_padding_seconds=float(natural_audio_section.get("mute_phrase_padding_seconds", 0.35)),
            mute_action_camera_boundary_seconds=float(natural_audio_section.get("mute_action_camera_boundary_seconds", 0.0)),
            video_codec=str(render_section.get("video_codec", "h264")),
            overwrite_policy=str(render_section.get("overwrite_policy", config_value(config, "reel_builder.overwrite_policy", "replace"))),
        ),
        reels_per_activity=int(config_value(config, "reel_builder.reels_per_activity", 2)),
        intelligence_enabled=parse_enabled(intelligence_section.get("enabled", True), "reel_builder.intelligence.enabled"),
        intelligence_backend=str(intelligence_section.get("backend", "opencv")),
        intelligence_sample_frames=int(intelligence_section.get("sample_frames_per_segment", 5)),
        reject_activity_mismatch=parse_enabled(
            intelligence_section.get("reject_activity_mismatch", True),
            "reel_builder.intelligence.reject_activity_mismatch",
        ),
        min_activity_confidence=float(intelligence_section.get("min_activity_confidence", 42)),
        speed_ramps_enabled=parse_enabled(intelligence_section.get("speed_ramps", True), "reel_builder.intelligence.speed_ramps"),
        speed_ramp_fraction=float(intelligence_section.get("speed_ramp_fraction", 0.55)),
        max_speed_factor=float(intelligence_section.get("max_speed_factor", 3.0)),
        refine_segment_windows=parse_enabled(
            intelligence_section.get("refine_segment_windows", True),
            "reel_builder.intelligence.refine_segment_windows",
        ),
        max_window_candidates=int(intelligence_section.get("max_window_candidates", 8)),
        windows_per_clip=int(intelligence_section.get("windows_per_clip", 1)),
        highlight_timeline_enabled=parse_enabled(
            intelligence_section.get("highlight_timeline_enabled", True),
            "reel_builder.intelligence.highlight_timeline_enabled",
        ),
        highlight_max_per_source_video=int(intelligence_section.get("highlight_max_per_source_video", 4)),
    )


def activity_scoped_input_path(path: Path, media_set: str) -> Path:
    """Prefer per-activity outputs when a previous phase wrote them."""
    scoped = path.parent / media_set / path.name
    return scoped if scoped.exists() else path


def activity_scoped_reel_config(config: ReelConfig, media_set: str) -> ReelConfig:
    return replace(
        config,
        input_clip_scores=activity_scoped_input_path(config.input_clip_scores, media_set),
        input_clip_manifest=activity_scoped_input_path(config.input_clip_manifest, media_set),
        input_video_timeline=activity_scoped_input_path(config.input_video_timeline, media_set),
        input_audio_events=activity_scoped_input_path(config.input_audio_events, media_set),
        input_transcript_segments=activity_scoped_input_path(config.input_transcript_segments, media_set),
    )


def parse_media_sets(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    return set()


def parse_ordered_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def parse_list(value: object) -> set[str]:
    return set(parse_ordered_list(value))


def default_reel_moment_types() -> list[str]:
    return ["arrival", "safety_briefing", "gear_up", "walk_to_start", "launch", "rapids", "splash", "group_photo", "meal", "return_trip"]


def default_required_moment_types() -> list[str]:
    return ["arrival", "gear_up", "walk_to_start", "launch", "rapids", "splash", "group_photo"]


def read_csv_required(path: Path, project_root: Path, phase_hint: str) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing upstream manifest: {path.relative_to(project_root).as_posix()}. Run {phase_hint} first.")
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"Upstream manifest is empty: {path.relative_to(project_root).as_posix()}. Run {phase_hint} first.")
    return rows


def read_csv_optional(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except ValueError:
        return default


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
    return "".join(cleaned).strip("_") or "reel"


def build_candidates(config: ReelConfig, project_root: Path) -> list[ReelCandidate]:
    story_rows = read_csv_required(config.input_story_manifest, project_root, "story-builder")
    clip_rows = read_csv_required(config.input_clip_scores, project_root, "video-processing")
    timeline_rows = read_csv_required(config.input_video_timeline, project_root, "video-processing")
    audio_rows = read_csv_optional(config.input_audio_events)
    read_csv_required(config.input_moment_assets, project_root, "story-builder")
    read_csv_required(config.input_clip_manifest, project_root, "video-processing")

    moments = {row.get("moment_id", ""): row for row in story_rows}
    timeline_by_clip = {row.get("clip_id", ""): row for row in timeline_rows if row.get("clip_id")}
    audio_by_video = group_audio_events(audio_rows)
    source_counts: dict[str, int] = {}

    candidates: list[ReelCandidate] = []
    for row in clip_rows:
        media_set = row.get("media_set", "")
        if config.media_sets and media_set not in config.media_sets:
            continue
        video_path = row.get("video_path", "")
        if not video_path:
            continue
        if path_matches_patterns(video_path, config.exclude_source_patterns):
            continue
        source_path = resolve_project_path(project_root, video_path)
        if not source_path.exists():
            continue

        clip_id = row.get("clip_id", "")
        timeline = timeline_by_clip.get(clip_id) or best_timeline_for_clip(row, timeline_rows)
        moment_id = row.get("moment_id", "") or timeline.get("moment_id", "")
        moment = moments.get(moment_id, {})
        moment_type = moment.get("moment_type", "")
        is_group_perspective = path_matches_patterns(video_path, config.group_perspective_patterns)
        clip_start = safe_float(row.get("start_seconds"))
        clip_end = safe_float(row.get("end_seconds"), clip_start + safe_float(row.get("duration_seconds"), config.max_segment_seconds))
        source_duration = max(clip_end, safe_float(row.get("duration_seconds"), clip_end))
        segment_start, segment_end = choose_segment_window(config, row, timeline, clip_start, clip_end)
        if segment_end - segment_start < config.min_segment_seconds:
            continue
        role = "group_action" if is_group_perspective else role_for_candidate(row, timeline, moment)
        audio_score = audio_energy_score(audio_by_video.get(video_path, []), segment_start, segment_end)
        motion_score = motion_from_scoring_reason(row.get("scoring_reason", ""))
        if should_promote_arrival_action(config, moment_type, role, clip_start, audio_score, motion_score):
            moment_type = "water_action"
            role = "action"
            moment_id = f"{moment_id}_water_action"
        if config.include_moment_types and moment_type not in config.include_moment_types and not is_group_perspective:
            continue
        refined_windows = refine_segment_windows_for_reel(
            config,
            project_root,
            video_path,
            clip_start,
            clip_end,
            segment_start,
            segment_end,
            motion_score,
            audio_score,
            timeline,
            row,
            moment,
            role,
        )
        clip_overall = safe_float(row.get("overall_score"), safe_float(row.get("reel_score"), 50))
        quality = safe_float(row.get("quality_score"), 50)
        action = safe_float(row.get("action_score"), 50)
        for window_index, (segment_start, segment_end, audit) in enumerate(refined_windows, start=1):
            audio_score = audio_energy_score(audio_by_video.get(video_path, []), segment_start, segment_end)
            diversity_seed = diversity_seed_score(source_counts.get(video_path, 0), role)
            source_counts[video_path] = source_counts.get(video_path, 0) + 1

            story = max(safe_float(row.get("story_score"), 50), safe_float(timeline.get("story_importance_score"), 50), safe_float(moment.get("reel_score"), 50))
            people = safe_float(row.get("people_score"), 50)
            timeline_score = safe_float(timeline.get("reel_value_score"), safe_float(row.get("reel_score"), 50))
            adventure_score = adventure_score_for(config, video_path, moment_type, role, action, audio_score, motion_score, timeline, row)
            cinematic_score = cinematic_score_for(clip_overall, quality, timeline_score, motion_score, row, timeline)
            visual_score = activity_visual_score_for(config, row, quality, motion_score, action)
            memory_score = memory_score_for(moment_type, role, people, story, timeline, row)
            emotion_score = emotion_score_for(role, audio_score, people, story, timeline, row)
            context_score, context_reason, essence_chapter = activity_context_score_for(config, media_set, moment_type, role, timeline, row, moment)
            activity_score, activity_reason = activity_score_for(
                config,
                video_path,
                moment_type,
                role,
                adventure_score,
                cinematic_score,
                memory_score,
                emotion_score,
                timeline,
                row,
            )
            activity_score = clamp_score(activity_score * 0.72 + context_score * 0.28)
            activity_reason = f"{activity_reason}; context={context_reason}; essence={essence_chapter}"
            activity_bucket = activity_bucket_for(config, moment_type, role)
            if is_group_ending(moment, timeline):
                activity_bucket = "ending"
            final_score = final_reel_score_for(
                config,
                activity_score=activity_score,
                adventure_score=adventure_score,
                emotion_score=emotion_score,
                story_score=story,
                technical_score=max(clip_overall * 0.45 + visual_score * 0.55, clip_overall if visual_score >= 70 else visual_score),
                diversity_score=diversity_seed,
            )
            if role == "hook":
                final_score += 6
            elif role == "action":
                final_score += 4
            elif role == "group_action":
                final_score += 10
            elif role == "reaction":
                final_score += 3
            elif role == "closing":
                final_score += 2
            if moment_type in {"rapids", "splash", "water_action"}:
                final_score += min(audio_score * 0.08, 8)
                final_score += min(motion_score * 0.08, 8)
                if config.suppress_low_motion_water_clips and motion_score <= 1 and (segment_end - segment_start) < 3:
                    final_score -= 10
            if config.reject_activity_mismatch and audit.activity_mismatch:
                continue
            if audit.activity_confidence < config.min_activity_confidence:
                continue
            face_score = metric_from_scoring_reason(audit.reason, "face", 0.0)
            max_faces = metric_from_scoring_reason(audit.reason, "max_faces", 0.0)
            if profile_values_people(config):
                people = max(people, min(100.0, 55.0 + face_score * 38.0 + min(max_faces * 6.0, 18.0)))
            speed_factor = audit.speed_factor
            output_duration = (segment_end - segment_start) / max(speed_factor, 0.1)
            audit_tags = merge_visual_tags(audit.visual_tags, camera_perspective_tags(video_path))
            final_score += (audit.activity_confidence - 50.0) * 0.18
            if "hero_action" in audit_tags:
                final_score += 4
            if any(tag in audit_tags for tag in ("water_crossing", "mud_action", "tunnel_or_shade")):
                final_score += 5
            if any(tag in audit_tags for tag in ("face_visible", "people_visible", "group_reaction")):
                final_score += 9 if profile_values_people(config) else 4
            if config.activity_profile.name.lower() == "rafting":
                if "weak_close_pov" in audit_tags:
                    final_score -= 34
                if "action_camera_pov" in audit_tags and not set(audit_tags).intersection({"water_crossing", "river_scene", "river_people", "group_reaction", "face_visible"}):
                    final_score -= 12
                if set(audit_tags).intersection({"phone_perspective", "group_camera_perspective"}) and set(audit_tags).intersection({"river_scene", "river_people", "water_crossing", "water"}):
                    final_score += 16
            final_score += segment_distinctiveness_bonus(config, segment_start, clip_start, clip_end, audit, role)

            candidates.append(
                ReelCandidate(
                    reel_id=config.reel_id,
                    reel_style=config.style,
                    target_duration_seconds=config.target_duration_seconds,
                    media_set=media_set,
                    activity=moment.get("activity", media_set.title()),
                    moment_id=moment_id,
                    moment_type=moment_type,
                    story_order=story_order_for(config, moment_type, is_group_perspective),
                    moment_title=moment.get("title", moment_id),
                    timeline_event_id=timeline.get("timeline_event_id", ""),
                    timeline_label=timeline.get("event_label", ""),
                    source_media_path=video_path,
                    source_file_type="video",
                    source_video_duration_seconds=round(source_duration, 3),
                    segment_start_seconds=round(segment_start, 3),
                    segment_end_seconds=round(segment_end, 3),
                    segment_duration_seconds=round(output_duration, 3),
                    clip_id=f"{clip_id}_w{window_index:02d}" if len(refined_windows) > 1 else clip_id,
                    clip_overall_score=round(clip_overall, 2),
                    quality_score=round(quality, 2),
                    action_score=round(action, 2),
                    story_score=round(story, 2),
                    people_score=round(people, 2),
                    audio_energy_score=round(audio_score, 2),
                    diversity_score=round(diversity_seed, 2),
                    adventure_score=round(adventure_score, 2),
                    cinematic_score=round(cinematic_score, 2),
                    memory_score=round(memory_score, 2),
                    emotion_score=round(emotion_score, 2),
                    activity_score=round(activity_score, 2),
                    activity_bucket=activity_bucket,
                    activity_reason=activity_reason,
                    visual_tags=",".join(audit_tags),
                    activity_confidence=round(audit.activity_confidence, 2),
                    activity_mismatch="yes" if audit.activity_mismatch else "no",
                    speed_factor=round(speed_factor, 3),
                    audio_decision=audit.audio_decision,
                    audit_reason=audit.reason,
                    final_reel_score=round(final_score, 2),
                    candidate_role=role,
                )
            )
    return sorted(candidates, key=lambda item: (item.story_order, -item.final_reel_score, item.media_set, item.segment_start_seconds, item.source_media_path))


def refine_segment_windows_for_reel(
    config: ReelConfig,
    project_root: Path,
    video_path: str,
    clip_start: float,
    clip_end: float,
    preferred_start: float,
    preferred_end: float,
    motion_score: float,
    audio_score: float,
    timeline: dict[str, str],
    clip: dict[str, str],
    moment: dict[str, str],
    role: str,
) -> list[tuple[float, float, SegmentAudit]]:
    preferred_audit = inspect_segment_for_reel(
        config,
        project_root,
        video_path,
        preferred_start,
        preferred_end,
        motion_score,
        audio_score,
        timeline,
        clip,
        moment,
        role,
    )
    if not config.refine_segment_windows or config.intelligence_backend.lower() != "opencv":
        return [(preferred_start, preferred_end, preferred_audit)]

    windows = candidate_subwindows(config, clip_start, clip_end, preferred_start, preferred_end)
    scored: list[tuple[float, float, SegmentAudit, float]] = [
        (preferred_start, preferred_end, preferred_audit, segment_window_score(config, preferred_audit, preferred_start, clip_start, clip_end, role))
    ]
    for start, end in windows:
        audit = inspect_segment_for_reel(
            config,
            project_root,
            video_path,
            start,
            end,
            motion_score,
            audio_score,
            timeline,
            clip,
            moment,
            role,
        )
        if config.reject_activity_mismatch and audit.activity_mismatch:
            continue
        score = segment_window_score(config, audit, start, clip_start, clip_end, role)
        scored.append((start, end, audit, score))
    selected: list[tuple[float, float, SegmentAudit]] = []
    for start, end, audit, _score in sorted(scored, key=lambda item: -item[3]):
        if any(ranges_overlap(start - 0.1, end + 0.1, kept_start, kept_end) for kept_start, kept_end, _ in selected):
            continue
        selected.append((start, end, audit))
        if len(selected) >= max(1, config.windows_per_clip):
            break
    return sorted(selected, key=lambda item: item[0])


def candidate_subwindows(config: ReelConfig, clip_start: float, clip_end: float, preferred_start: float, preferred_end: float) -> list[tuple[float, float]]:
    clip_duration = max(0.0, clip_end - clip_start)
    preferred_duration = max(config.min_segment_seconds, preferred_end - preferred_start)
    window_duration = min(config.max_segment_seconds, max(config.min_segment_seconds, preferred_duration), clip_duration)
    if clip_duration <= window_duration + 0.25:
        return [(round(clip_start, 3), round(clip_end, 3))]
    step = max(2.0, window_duration * 0.55)
    starts = [preferred_start, clip_start, max(clip_start, clip_end - window_duration)]
    cursor = clip_start
    while cursor <= clip_end - window_duration + 0.05 and len(starts) < config.max_window_candidates + 3:
        starts.append(cursor)
        cursor += step
    unique: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for start in starts:
        bounded_start = min(max(clip_start, start), clip_end - window_duration)
        bounded_end = min(clip_end, bounded_start + window_duration)
        key = (round(bounded_start, 3), round(bounded_end, 3))
        if key not in seen:
            unique.append(key)
            seen.add(key)
        if len(unique) >= config.max_window_candidates:
            break
    return unique


def segment_window_score(config: ReelConfig, audit: SegmentAudit, start: float, clip_start: float, clip_end: float, role: str) -> float:
    tags = set(audit.visual_tags)
    score = audit.activity_confidence
    if "hero_action" in tags:
        score += 8
    if "ground_only" in tags:
        score -= 32
    if "weak_close_pov" in tags:
        score -= 36
    if "unstable_roll" in tags:
        score -= 48
    if "bad_orientation" in tags:
        score -= 48
    if config.activity_profile.name.lower() == "rafting":
        if tags.intersection({"river_scene", "river_people"}):
            score += 10
        if tags.intersection({"phone_perspective", "group_camera_perspective"}) and tags.intersection({"river_scene", "water_crossing", "water"}):
            score += 8
    if config.activity_profile.name.lower() == "atv":
        for tag in (
            "atv_pov",
            "mud_action",
            "water_crossing",
            "mud_water_run",
            "water_speed_run",
            "tunnel_or_shade",
            "lit_tunnel",
            "jungle_trail",
            "speed_action",
            "rough_motion",
        ):
            if tag in tags:
                score += 4
        if {"water_speed_run", "speed_action"} <= tags:
            score += 8
        if {"lit_tunnel", "atv_pov"} <= tags:
            score += 7
    if role in {"action", "group_action"}:
        progress = (start - clip_start) / max(0.1, clip_end - clip_start)
        score += min(progress * 8.0, 8.0)
    return score


def segment_distinctiveness_bonus(
    config: ReelConfig,
    segment_start: float,
    clip_start: float,
    clip_end: float,
    audit: SegmentAudit,
    role: str,
) -> float:
    if role not in {"action", "group_action", "supporting"}:
        return 0.0
    tags = set(audit.visual_tags)
    bonus = 0.0
    for tag, value in {
        "water_crossing": 8.0,
        "water_speed_run": 10.0,
        "mud_water_run": 7.0,
        "tunnel_or_shade": 5.0,
        "lit_tunnel": 9.0,
        "speed_action": 4.0,
        "rough_motion": 3.0,
        "jungle_trail": 3.0,
    }.items():
        if tag in tags:
            bonus += value
    progress = (segment_start - clip_start) / max(0.1, clip_end - clip_start)
    if config.chronological in {"strict", "timeline", "source"}:
        bonus += min(max(progress, 0.0) * 6.0, 6.0)
    if "ground_only" in tags:
        bonus -= 14.0
    if "weak_close_pov" in tags:
        bonus -= 18.0
    if "unstable_roll" in tags:
        bonus -= 24.0
    if "bad_orientation" in tags:
        bonus -= 24.0
    return bonus


def inspect_segment_for_reel(
    config: ReelConfig,
    project_root: Path,
    video_path: str,
    start_seconds: float,
    end_seconds: float,
    motion_score: float,
    audio_score: float,
    timeline: dict[str, str],
    clip: dict[str, str],
    moment: dict[str, str],
    role: str,
) -> SegmentAudit:
    key = (video_path, round(start_seconds, 2), round(end_seconds, 2), f"{config.activity_profile.name}:{SEGMENT_AUDIT_CACHE_VERSION}")
    if key in SEGMENT_AUDIT_CACHE:
        return SEGMENT_AUDIT_CACHE[key]
    if not config.intelligence_enabled or config.intelligence_backend.lower() in {"none", "off"}:
        audit = baseline_segment_audit(config, motion_score, audio_score, timeline, clip, moment, role)
        SEGMENT_AUDIT_CACHE[key] = audit
        return audit
    if config.intelligence_backend.lower() != "opencv":
        audit = baseline_segment_audit(config, motion_score, audio_score, timeline, clip, moment, role)
        SEGMENT_AUDIT_CACHE[key] = audit
        return audit
    try:
        audit = opencv_segment_audit(
            config,
            resolve_project_path(project_root, video_path),
            start_seconds,
            end_seconds,
            motion_score,
            audio_score,
            timeline,
            clip,
            moment,
            role,
        )
    except Exception as error:  # pragma: no cover - defensive fallback for codec/platform oddities.
        audit = baseline_segment_audit(config, motion_score, audio_score, timeline, clip, moment, role, f"opencv_fallback={type(error).__name__}")
    SEGMENT_AUDIT_CACHE[key] = audit
    return audit


def baseline_segment_audit(
    config: ReelConfig,
    motion_score: float,
    audio_score: float,
    timeline: dict[str, str],
    clip: dict[str, str],
    moment: dict[str, str],
    role: str,
    fallback_note: str = "text_only",
) -> SegmentAudit:
    text = candidate_context_text("", moment.get("moment_type", ""), role, timeline, clip, moment)
    required_hits = [term for term in config.activity_profile.required_context if profile_term_matches(term, text)]
    reject_hits = [term for term in config.activity_profile.reject_context if profile_term_matches(term, text)]
    confidence = 58.0 + min(len(required_hits) * 8.0, 28.0) - min(len(reject_hits) * 20.0, 60.0)
    if motion_score >= 60:
        confidence += 6
    speed = speed_factor_for(config, motion_score, audio_score, role, tuple(required_hits), "text_only")
    mismatch = bool(reject_hits) or confidence < config.min_activity_confidence
    tags = tuple(dict.fromkeys(required_hits + (["hero_action"] if motion_score >= 70 else []))) or ("text_candidate",)
    return SegmentAudit(tags, clamp_score(confidence), mismatch, speed, audio_decision_for(config), f"{fallback_note}; text_tags={','.join(tags)}")


def opencv_segment_audit(
    config: ReelConfig,
    source: Path,
    start_seconds: float,
    end_seconds: float,
    motion_score: float,
    audio_score: float,
    timeline: dict[str, str],
    clip: dict[str, str],
    moment: dict[str, str],
    role: str,
) -> SegmentAudit:
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    if hasattr(cv2, "setLogLevel"):
        try:
            cv2.setLogLevel(0)
        except Exception:
            pass
    frames = sample_video_frames(cv2, source, start_seconds, end_seconds, max(3, config.intelligence_sample_frames))
    if not frames:
        return baseline_segment_audit(config, motion_score, audio_score, timeline, clip, moment, role, "no_frames")

    metrics = [frame_metrics(cv2, np, frame) for frame in frames]
    avg = average_metrics(metrics)
    face_model_path = Path(str(config_value(config, "selected_timeline.face_filter.model_path", config_value(config, "album_builder.face_filter.model_path", "models/face_detection_yunet_2023mar.onnx"))))
    if not face_model_path.is_absolute():
        face_model_path = Path.cwd() / face_model_path
    face_threshold = float(config_value(config, "selected_timeline.face_filter.face_score_threshold", config_value(config, "album_builder.face_filter.score_threshold", 0.45)))
    face = face_presence_metrics(cv2, frames, face_model_path, face_threshold)
    text = candidate_context_text("", moment.get("moment_type", ""), role, timeline, clip, moment)
    tags: list[str] = []
    is_atv_profile = config.activity_profile.name.lower() == "atv"
    is_rafting_profile = config.activity_profile.name.lower() == "rafting"
    is_stay_profile = config.activity_profile.name.lower() == "stay"
    people_profile = profile_values_people(config)
    tags.extend(camera_perspective_tags(source.as_posix()))
    if face["face_score"] >= 0.28:
        tags.append("face_visible")
    if face["max_faces"] >= 2 or face["avg_faces"] >= 1.35:
        tags.append("group_reaction")
    elif people_profile and face["face_score"] >= 0.16:
        tags.append("people_visible")
    if is_atv_profile and avg["vehicle_score"] >= 0.16:
        tags.append("atv_pov")
    if is_atv_profile and avg["mud_ratio"] >= 0.10:
        tags.append("mud_action")
    if avg["green_ratio"] >= 0.22:
        tags.append("jungle_trail")
    muddy_water_run = is_atv_profile and avg["mud_ratio"] >= 0.24 and avg["vehicle_score"] >= 0.18 and avg["edge_density"] >= 0.14
    if muddy_water_run:
        tags.append("mud_water_run")
    if is_atv_profile and avg["water_ratio"] >= 0.16 and avg["vehicle_score"] >= 0.12:
        tags.append("water_crossing")
    elif muddy_water_run:
        tags.append("water_crossing")
    elif is_rafting_profile and avg["water_ratio"] >= 0.16:
        tags.append("water_crossing")
    elif avg["water_ratio"] >= 0.22:
        tags.append("water")
    if is_stay_profile and avg["water_ratio"] >= 0.18:
        tags.append("pool")
        if motion_score >= 42 or audio_score >= 60:
            tags.append("pool_action")
        if motion_score >= 58:
            tags.append("swimming")
        if motion_score >= 70 and avg["edge_density"] >= 0.09:
            tags.append("pool_jump")
    if avg["dark_ratio"] >= 0.32 and (avg["vehicle_score"] >= 0.12 if is_atv_profile else avg["edge_density"] >= 0.08):
        tags.append("tunnel_or_shade")
    if avg["dark_ratio"] >= 0.45 and avg["orange_ratio"] >= 0.035 and (avg["vehicle_score"] >= 0.12 if is_atv_profile else avg["edge_density"] >= 0.08):
        tags.append("lit_tunnel")
    if motion_score >= 58:
        tags.append("speed_action")
    if muddy_water_run and (motion_score >= 45 or audio_score >= 70):
        tags.append("water_speed_run")
    if avg["edge_density"] >= 0.13 and motion_score >= 45:
        tags.append("rough_motion")
    pavement_floor = (
        is_atv_profile
        and avg["gray_floor_ratio"] >= 0.40
        and avg["green_ratio"] < 0.08
        and avg["water_ratio"] < 0.08
        and avg["orange_ratio"] < 0.012
    )
    setup_surface = (
        is_atv_profile
        and start_seconds <= 15.0
        and avg["gray_floor_ratio"] >= 0.20
        and avg["green_ratio"] <= 0.18
        and "lit_tunnel" not in tags
    )
    ground_only = (
        (
            avg["mud_ratio"] >= 0.42
            and avg["green_ratio"] < 0.16
            and avg["water_ratio"] < 0.10
            and avg["edge_density"] < 0.16
        )
        or pavement_floor
    ) and not muddy_water_run
    if setup_surface:
        tags.append("setup_surface")
    if ground_only:
        tags.append("ground_only")
    rafting_like = (
        is_atv_profile
        and avg["orange_ratio"] >= 0.008
        and avg["water_ratio"] >= 0.15
        and avg["vehicle_score"] < 0.13
    )
    if rafting_like or any(profile_term_matches(term, text) for term in ("rafting", "rapids", "paddle")):
        tags.append("rafting_like")
    weak_close_pov = (
        is_rafting_profile
        and "action_camera_pov" in tags
        and avg["water_ratio"] < 0.10
        and face["face_score"] < 0.16
        and (avg["orange_ratio"] >= 0.16 or avg["gray_floor_ratio"] >= 0.50)
        and (avg["edge_density"] < 0.18 or avg["orange_ratio"] >= 0.28 or avg["gray_floor_ratio"] >= 0.62)
    )
    if weak_close_pov:
        tags.append("weak_close_pov")
    unstable_roll = (
        "action_camera_pov" in tags
        and face["face_score"] >= 0.48
        and face["max_faces"] <= 3
        and (avg["gray_floor_ratio"] >= 0.44 or (avg["mud_ratio"] >= 0.28 and avg["green_ratio"] < 0.04))
        and avg["green_ratio"] < 0.14
        and avg["water_ratio"] < 0.13
        and avg["edge_density"] < 0.09
        and avg["dark_ratio"] < 0.28
        and not is_atv_profile
    )
    if unstable_roll:
        tags.append("unstable_roll")
    bad_orientation = (
        not is_atv_profile
        and "action_camera_pov" in tags
        and (
            (
                face["face_score"] >= 0.28
                and face["max_faces"] <= 3
                and avg["green_ratio"] < 0.18
                and avg["edge_density"] < 0.12
                and avg["dark_ratio"] < 0.32
                and (
                    avg["gray_floor_ratio"] >= 0.32
                    or (avg["mud_ratio"] >= 0.22 and avg["green_ratio"] < 0.08)
                    or (avg["mud_ratio"] >= 0.16 and avg["green_ratio"] < 0.04 and avg["water_ratio"] < 0.12 and avg["edge_density"] < 0.07)
                    or (avg["water_ratio"] < 0.08 and avg["orange_ratio"] >= 0.06)
                )
            )
            or (
                avg["gray_floor_ratio"] >= 0.32
                and avg["edge_density"] < 0.11
                and avg["green_ratio"] < 0.24
                and avg["water_ratio"] < 0.22
                and face["max_faces"] <= 2
            )
            or (
                face["face_score"] < 0.16
                and avg["gray_floor_ratio"] >= 0.50
                and avg["edge_density"] < 0.11
                and avg["green_ratio"] < 0.22
                and avg["water_ratio"] < 0.32
            )
            or (
                face["face_score"] < 0.28
                and face["max_faces"] <= 2
                and avg["gray_floor_ratio"] >= 0.25
                and avg["edge_density"] < 0.11
                and avg["green_ratio"] < 0.30
                and avg["water_ratio"] < 0.20
            )
            or (
                face["max_faces"] <= 2
                and avg["gray_floor_ratio"] >= 0.27
                and avg["edge_density"] < 0.08
                and avg["green_ratio"] < 0.18
                and avg["water_ratio"] < 0.18
            )
            or (
                face["face_score"] >= 0.22
                and face["max_faces"] <= 2
                and avg["edge_density"] < 0.075
                and avg["green_ratio"] < 0.04
                and avg["water_ratio"] < 0.17
                and avg["dark_ratio"] < 0.26
                and avg["orange_ratio"] < 0.04
            )
        )
    )
    if bad_orientation:
        tags.append("bad_orientation")
    if is_rafting_profile and avg["water_ratio"] >= 0.08 and not weak_close_pov:
        tags.append("river_scene")
    if is_rafting_profile and avg["water_ratio"] >= 0.08 and (
        "group_reaction" in tags
        or "face_visible" in tags
        or "people_visible" in tags
        or set(tags).intersection({"phone_perspective", "group_camera_perspective"})
    ):
        tags.append("river_people")
    required_hits = [term for term in config.activity_profile.required_context if profile_term_matches(term, " ".join(tags) + " " + text)]
    reject_hits = [term for term in config.activity_profile.reject_context if profile_term_matches(term, " ".join(tags) + " " + text)]
    confidence = 50.0 + min(len(required_hits) * 5.0, 25.0)
    if config.activity_profile.name.lower() == "atv":
        confidence += avg["vehicle_score"] * 95.0
        confidence += min(avg["mud_ratio"] * 70.0, 10.0)
        confidence += min(avg["green_ratio"] * 35.0, 9.0)
        if "water_crossing" in tags:
            confidence += 8.0
        if "mud_water_run" in tags:
            confidence += 8.0
        if "water_speed_run" in tags:
            confidence += 10.0
        if "tunnel_or_shade" in tags:
            confidence += 6.0
        if "lit_tunnel" in tags:
            confidence += 9.0
        if "speed_action" in tags:
            confidence += 5.0
        if ground_only:
            confidence -= 28.0
        if setup_surface:
            confidence -= 34.0
        if rafting_like:
            confidence -= 48.0
    else:
        confidence += min(avg["edge_density"] * 55.0, 10.0)
        confidence += 6.0 if motion_score >= 60 else 0.0
        if is_stay_profile:
            if "pool" in tags:
                confidence += 9.0
            if "pool_action" in tags:
                confidence += 10.0
            if "swimming" in tags:
                confidence += 8.0
            if "pool_jump" in tags:
                confidence += 12.0
        if people_profile:
            confidence += min(face["face_score"] * 34.0, 18.0)
            confidence += min(face["avg_faces"] * 5.0, 12.0)
            if "group_reaction" in tags:
                confidence += 7.0
        elif "group_reaction" in tags:
            confidence += 5.0
        if is_rafting_profile:
            if "river_scene" in tags:
                confidence += 8.0
            if "river_people" in tags:
                confidence += 10.0
            if set(tags).intersection({"phone_perspective", "group_camera_perspective"}) and "river_scene" in tags:
                confidence += 8.0
            if weak_close_pov:
                confidence -= 38.0
    confidence -= min(len(reject_hits) * 16.0, 48.0)
    tags = list(dict.fromkeys(tags or ["visual_candidate"]))
    if confidence >= 72 and role in {"action", "group_action"}:
        tags.append("hero_action")
    speed = speed_factor_for(config, motion_score, audio_score, role, tuple(tags), f"{source.name}:{start_seconds:.2f}:{end_seconds:.2f}")
    mismatch = bool(reject_hits) or ("rafting_like" in tags and config.activity_profile.name.lower() == "atv") or confidence < config.min_activity_confidence
    reason = (
        f"opencv; vehicle={avg['vehicle_score']:.3f}; water={avg['water_ratio']:.3f}; mud={avg['mud_ratio']:.3f}; "
        f"green={avg['green_ratio']:.3f}; orange={avg['orange_ratio']:.3f}; dark={avg['dark_ratio']:.3f}; edge={avg['edge_density']:.3f}; gray_floor={avg['gray_floor_ratio']:.3f}; "
        f"face={face['face_score']:.3f}; faces={face['avg_faces']:.2f}; max_faces={face['max_faces']:.0f}; "
        f"required={','.join(required_hits[:4]) or 'none'}; reject={','.join(reject_hits[:4]) or 'none'}"
    )
    return SegmentAudit(tuple(tags), clamp_score(confidence), mismatch, speed, audio_decision_for(config), reason)


def profile_values_people(config: ReelConfig) -> bool:
    values = activity_profile_terms(config.activity_profile)
    people_terms = {"friends", "friend", "people", "person", "group", "group_reactions", "emotion", "celebration", "dancing"}
    return bool(values.intersection(people_terms)) or config.activity_profile.optimization_goal in {"memory", "social", "cinematic"}


def profile_values_people_terms(profile: ActivityProfile) -> bool:
    people_terms = {"friends", "friend", "people", "person", "group", "group_reactions", "emotion", "celebration", "dancing"}
    return bool(activity_profile_terms(profile).intersection(people_terms))


def activity_profile_terms(profile: ActivityProfile) -> set[str]:
    return {
        str(item).lower()
        for item in (
            list(profile.maximize)
            + list(profile.required_context)
            + list(profile.essence_chapters.keys())
        )
    }


def face_presence_metrics(cv2: Any, frames: list[Any], yunet_model_path: Path | None = None, score_threshold: float = 0.45) -> dict[str, float]:
    if yunet_model_path and yunet_model_path.exists() and hasattr(cv2, "FaceDetectorYN_create"):
        try:
            return face_presence_metrics_yunet(cv2, frames, yunet_model_path, score_threshold)
        except Exception:
            pass
    cv2_data = getattr(cv2, "data", None)
    haarcascades = getattr(cv2_data, "haarcascades", "") if cv2_data is not None else ""
    if not haarcascades or not hasattr(cv2, "CascadeClassifier"):
        return {"face_score": 0.0, "avg_faces": 0.0, "max_faces": 0.0}
    face_cascade = cv2.CascadeClassifier(str(Path(haarcascades) / "haarcascade_frontalface_default.xml"))
    profile_cascade = cv2.CascadeClassifier(str(Path(haarcascades) / "haarcascade_profileface.xml"))
    if face_cascade.empty() and profile_cascade.empty():
        return {"face_score": 0.0, "avg_faces": 0.0, "max_faces": 0.0}
    counts: list[int] = []
    area_scores: list[float] = []
    for frame in frames:
        height, width = frame.shape[:2]
        target_width = 480
        if width > target_width:
            scale = target_width / float(width)
            frame = cv2.resize(frame, (target_width, max(1, int(height * scale))))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = []
        if not face_cascade.empty():
            faces.extend(face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(28, 28)))
        if not profile_cascade.empty():
            faces.extend(profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(28, 28)))
        deduped: list[tuple[int, int, int, int]] = []
        for x, y, w, h in faces:
            if any(rects_overlap((x, y, w, h), existing) for existing in deduped):
                continue
            deduped.append((int(x), int(y), int(w), int(h)))
        frame_area = max(1, gray.shape[0] * gray.shape[1])
        counts.append(len(deduped))
        area_scores.append(sum((w * h) / frame_area for _, _, w, h in deduped))
    avg_faces = mean(counts) if counts else 0.0
    max_faces = max(counts) if counts else 0.0
    face_score = min(1.0, (mean(area_scores) if area_scores else 0.0) * 18.0 + min(avg_faces * 0.18, 0.7))
    return {"face_score": float(face_score), "avg_faces": float(avg_faces), "max_faces": float(max_faces)}


def face_presence_metrics_yunet(cv2: Any, frames: list[Any], model_path: Path, score_threshold: float) -> dict[str, float]:
    counts: list[int] = []
    area_scores: list[float] = []
    for frame in frames:
        height, width = frame.shape[:2]
        target_width = 720
        if width > target_width:
            scale = target_width / float(width)
            frame = cv2.resize(frame, (target_width, max(1, int(height * scale))))
            height, width = frame.shape[:2]
        detector = cv2.FaceDetectorYN_create(str(model_path), "", (width, height), score_threshold, 0.30, 5000)
        _ok, faces = detector.detect(frame)
        frame_area = max(1, height * width)
        detected: list[tuple[int, int, int, int]] = []
        if faces is not None:
            for face in faces:
                x, y, w, h = [int(round(value)) for value in face[:4]]
                score = float(face[-1])
                if score < score_threshold or w <= 0 or h <= 0:
                    continue
                rect = (max(0, x), max(0, y), min(width, w), min(height, h))
                if any(rects_overlap(rect, existing) for existing in detected):
                    continue
                detected.append(rect)
        counts.append(len(detected))
        area_scores.append(sum((w * h) / frame_area for _, _, w, h in detected))
    avg_faces = mean(counts) if counts else 0.0
    max_faces = max(counts) if counts else 0.0
    face_score = min(1.0, (mean(area_scores) if area_scores else 0.0) * 24.0 + min(avg_faces * 0.20, 0.8))
    return {"face_score": float(face_score), "avg_faces": float(avg_faces), "max_faces": float(max_faces)}


def rects_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return max(lx, rx) < min(lx + lw, rx + rw) and max(ly, ry) < min(ly + lh, ry + rh)


def sample_video_frames(cv2: Any, source: Path, start_seconds: float, end_seconds: float, count: int) -> list[Any]:
    source_key = str(source)
    cap = VIDEO_CAPTURE_CACHE.get(source_key)
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(source_key)
        VIDEO_CAPTURE_CACHE[source_key] = cap
    if not cap.isOpened():
        return []
    duration = max(0.2, end_seconds - start_seconds)
    if count <= 1:
        offsets = [0.5]
    else:
        offsets = [(index + 0.5) / count for index in range(count)]
    frames: list[Any] = []
    for offset in offsets:
        timestamp_ms = (start_seconds + duration * offset) * 1000.0
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(frame)
    return frames


def frame_metrics(cv2: Any, np: Any, frame: Any) -> dict[str, float]:
    height, width = frame.shape[:2]
    target_width = 360
    if width > target_width:
        scale = target_width / float(width)
        frame = cv2.resize(frame, (target_width, max(1, int(height * scale))))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    total = max(1, h.size)
    bottom = hsv[int(hsv.shape[0] * 0.58) :, int(hsv.shape[1] * 0.20) : int(hsv.shape[1] * 0.80), :]
    bottom_gray = gray[int(gray.shape[0] * 0.58) :, int(gray.shape[1] * 0.20) : int(gray.shape[1] * 0.80)]
    bottom_total = max(1, bottom.shape[0] * bottom.shape[1])
    orange = ((h >= 4) & (h <= 24) & (s >= 80) & (v >= 80)).sum() / total
    mud = ((h >= 5) & (h <= 28) & (s >= 35) & (v >= 35) & (v <= 230)).sum() / total
    green = ((h >= 35) & (h <= 88) & (s >= 38) & (v >= 35)).sum() / total
    blue = ((h >= 88) & (h <= 112) & (s >= 28) & (v >= 45)).sum() / total
    waterish = blue + min(green * 0.35, 0.16)
    dark = (v <= 70).sum() / total
    bottom_h = bottom[:, :, 0]
    bottom_s = bottom[:, :, 1]
    bottom_v = bottom[:, :, 2]
    bottom_dark = (bottom_v <= 80).sum() / bottom_total
    bottom_grayish = ((bottom_s <= 55) & (bottom_v >= 35) & (bottom_v <= 180)).sum() / bottom_total
    gray_floor = ((s <= 45) & (v >= 45) & (v <= 230)).sum() / total
    bottom_red_or_orange = (((bottom_h <= 12) | ((bottom_h >= 170) & (bottom_h <= 179))) & (bottom_s >= 70) & (bottom_v >= 60)).sum() / bottom_total
    edges = cv2.Canny(bottom_gray, 80, 160)
    edge_density = float((edges > 0).sum() / bottom_total)
    vehicle_score = min(1.0, bottom_dark * 0.45 + bottom_grayish * 0.28 + bottom_red_or_orange * 0.55 + edge_density * 0.85)
    return {
        "orange_ratio": float(orange),
        "mud_ratio": float(mud),
        "green_ratio": float(green),
        "water_ratio": float(waterish),
        "dark_ratio": float(dark),
        "edge_density": float(edge_density),
        "vehicle_score": float(vehicle_score),
        "gray_floor_ratio": float(gray_floor),
    }


def average_metrics(metrics: list[dict[str, float]]) -> dict[str, float]:
    keys = metrics[0].keys()
    return {key: mean(row[key] for row in metrics) for key in keys}


def speed_factor_for(config: ReelConfig, motion_score: float, audio_score: float, role: str, tags: tuple[str, ...], identity: str) -> float:
    if not config.speed_ramps_enabled:
        return 1.0
    if role not in {"action", "group_action", "supporting"}:
        return 1.0
    if any(tag in tags for tag in ("lit_tunnel", "tunnel_or_shade", "mud_action", "mud_water_run", "water_crossing", "water_speed_run", "speed_action", "rough_motion")):
        if deterministic_percent(identity) >= clamp_fraction(config.speed_ramp_fraction) * 100.0:
            return 1.0
        if config.variant == "action_audio" and any(tag in tags for tag in ("water_speed_run", "mud_water_run", "water_crossing", "lit_tunnel", "tunnel_or_shade", "speed_action", "rough_motion")):
            if max(motion_score, audio_score) >= 70:
                return min(config.max_speed_factor, 3.0)
        if max(motion_score, audio_score) >= 82:
            return 1.45
        if max(motion_score, audio_score) >= 58:
            return 1.25
    return 1.0


def deterministic_percent(value: str) -> float:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10000 / 100.0


def clamp_fraction(value: float) -> float:
    return max(0.0, min(value, 1.0))


def audio_decision_for(config: ReelConfig) -> str:
    if config.render.audio_mode == "mute":
        return "mute_source"
    if config.render.music_enabled and config.render.music_path:
        return "music_overlay"
    return "keep_source"


def motion_from_scoring_reason(reason: str) -> float:
    return metric_from_scoring_reason(reason, "motion", 0.0)


def metric_from_scoring_reason(reason: str, metric: str, default: float = 0.0) -> float:
    marker = f"{metric}="
    if marker not in reason:
        return default
    tail = reason.split(marker, 1)[1]
    value = re.split(r"[,;]", tail, maxsplit=1)[0].strip()
    try:
        return float(value)
    except ValueError:
        return default


def visual_clarity_score(quality: float, clip: dict[str, str]) -> float:
    reason = clip.get("scoring_reason", "")
    sharpness = metric_from_scoring_reason(reason, "sharpness", 0.0)
    brightness = metric_from_scoring_reason(reason, "brightness", 120.0)
    sharpness_score = clamp_score((sharpness / 4500.0) * 100.0)
    brightness_score = clamp_score(100.0 - abs(brightness - 126.0) * 1.25)
    clip_type_bonus = 7.0 if "clip_type=action" in reason else 3.0 if "clip_type=scenic" in reason else 0.0
    return clamp_score(quality * 0.55 + sharpness_score * 0.30 + brightness_score * 0.15 + clip_type_bonus)


def should_promote_arrival_action(config: ReelConfig, moment_type: str, role: str, clip_start: float, audio_score: float, motion_score: float) -> bool:
    return (
        config.promote_high_action_arrival
        and moment_type in {"arrival", "transition", "travel_to_activity", "other", ""}
        and role == "action"
        and (clip_start >= config.promoted_action_min_start_seconds or source_like_gopro_action(role, audio_score, motion_score))
        and audio_score >= config.promoted_action_min_audio_score
        and motion_score > 10
    )


def source_like_gopro_action(role: str, audio_score: float, motion_score: float) -> bool:
    return role == "action" and audio_score >= 65 and motion_score >= 45


def clamp_score(value: float) -> float:
    return max(0.0, min(value, 100.0))


def source_camera_score(path: str) -> float:
    name = Path(path).name.lower()
    if name.startswith("gx") or "gopro" in name:
        return 100.0
    if name.startswith("img_") and name.endswith(".mov"):
        return 72.0
    if "meta" in name:
        return 70.0
    return 55.0


def text_blob(*rows: dict[str, str]) -> str:
    values: list[str] = []
    for row in rows:
        values.extend(str(value) for value in row.values())
    return " ".join(values).lower()


def adventure_score_for(
    config: ReelConfig,
    video_path: str,
    moment_type: str,
    role: str,
    action_score: float,
    audio_score: float,
    motion_score: float,
    timeline: dict[str, str],
    clip: dict[str, str],
) -> float:
    profile = config.activity_profile
    moment_weight = profile.moment_weights.get(moment_type, 0.45) * 100
    camera = source_camera_score(video_path)
    role_bonus = 100 if role in {"action", "group_action"} else 78 if role == "reaction" else 55 if role == "scenic" else 35
    text = text_blob(timeline, clip)
    keyword_bonus = 0.0
    if any(token in text for token in ["rapid", "splash", "river", "water", "rafting", "action", "launch"]):
        keyword_bonus += 12
    if any(token in text for token in ["gopro", "pov", "helmet", "wide"]):
        keyword_bonus += 8
    if any(token in text for token in ["waiting", "walking", "briefing", "parking", "meal", "lunch"]):
        keyword_bonus -= 12
    motion_component = clamp_score(motion_score)
    score = (
        moment_weight * 0.30
        + action_score * 0.22
        + audio_score * 0.18
        + motion_component * 0.14
        + role_bonus * 0.10
        + camera * 0.06
        + keyword_bonus
    )
    return clamp_score(score)


def cinematic_score_for(clip_overall: float, quality: float, timeline_score: float, motion_score: float, clip: dict[str, str], timeline: dict[str, str]) -> float:
    text = text_blob(clip, timeline)
    scenic_bonus = 8 if any(token in text for token in ["scenic", "landscape", "river", "waterfall", "calm", "view"]) else 0
    harsh_motion_penalty = 5 if motion_score > 95 else 0
    return clamp_score(quality * 0.38 + clip_overall * 0.30 + timeline_score * 0.20 + min(motion_score, 80) * 0.12 + scenic_bonus - harsh_motion_penalty)


def memory_score_for(moment_type: str, role: str, people: float, story: float, timeline: dict[str, str], clip: dict[str, str]) -> float:
    text = text_blob(timeline, clip)
    bonus = 0.0
    if role in {"reaction", "group_action", "closing"}:
        bonus += 12
    if moment_type in {"group_photo", "gear_up", "walk_to_start", "meal"}:
        bonus += 8
    if any(token in text for token in ["laugh", "cheer", "smile", "group", "friends", "people"]):
        bonus += 10
    return clamp_score(people * 0.45 + story * 0.35 + 50 * 0.20 + bonus)


def emotion_score_for(role: str, audio_score: float, people: float, story: float, timeline: dict[str, str], clip: dict[str, str]) -> float:
    text = text_blob(timeline, clip)
    bonus = 0.0
    if role in {"reaction", "group_action"}:
        bonus += 10
    if any(token in text for token in ["laugh", "cheer", "scream", "excite", "reaction", "splash"]):
        bonus += 14
    return clamp_score(audio_score * 0.42 + people * 0.24 + story * 0.24 + 50 * 0.10 + bonus)


def activity_score_for(
    config: ReelConfig,
    video_path: str,
    moment_type: str,
    role: str,
    adventure_score: float,
    cinematic_score: float,
    memory_score: float,
    emotion_score: float,
    timeline: dict[str, str],
    clip: dict[str, str],
) -> tuple[float, str]:
    profile = config.activity_profile
    text = text_blob(timeline, clip) + " " + Path(video_path).name.lower() + " " + moment_type + " " + role
    maximize_hits = [token for token in profile.maximize if profile_term_matches(token, text)]
    minimize_hits = [token for token in profile.minimize if profile_term_matches(token, text)]
    base = adventure_score * 0.42 + emotion_score * 0.22 + cinematic_score * 0.14 + memory_score * 0.12 + source_camera_score(video_path) * 0.10
    base += min(len(maximize_hits) * 6, 24)
    base -= min(len(minimize_hits) * 8, 28)
    if config.activity_profile.optimization_goal == "adventure" and moment_type in {"rapids", "water_action", "splash", "launch"}:
        base += 10
    reason = f"profile={profile.name}; bucket={activity_bucket_for(config, moment_type, role)}"
    if maximize_hits:
        reason += f"; maximize={','.join(maximize_hits[:4])}"
    if minimize_hits:
        reason += f"; minimize={','.join(minimize_hits[:4])}"
    return clamp_score(base), reason


def activity_context_score_for(
    config: ReelConfig,
    media_set: str,
    moment_type: str,
    role: str,
    timeline: dict[str, str],
    clip: dict[str, str],
    moment: dict[str, str],
) -> tuple[float, str, str]:
    profile = config.activity_profile
    text = candidate_context_text(media_set, moment_type, role, timeline, clip, moment)
    required_hits = [term for term in profile.required_context if profile_term_matches(term, text)]
    reject_hits = [term for term in profile.reject_context if profile_term_matches(term, text)]
    maximize_hits = [term for term in profile.maximize if profile_term_matches(term, text)]
    score = 70.0
    if profile.required_context:
        score = 92.0 if required_hits else 38.0
    score += min(len(maximize_hits) * 4.0, 18.0)
    score -= min(len(reject_hits) * 18.0, 54.0)
    if media_set and media_set.lower() == profile.name.lower():
        score += 4.0
    essence = essence_chapter_for(profile, text, moment_type)
    reason = "match"
    if required_hits:
        reason += f":required={','.join(required_hits[:3])}"
    elif profile.required_context:
        reason += ":missing_required_context"
    if reject_hits:
        reason += f":reject={','.join(reject_hits[:3])}"
    return clamp_score(score), reason, essence


def candidate_context_text(
    media_set: str,
    moment_type: str,
    role: str,
    timeline: dict[str, str],
    clip: dict[str, str],
    moment: dict[str, str],
) -> str:
    values = [
        media_set,
        moment_type,
        role,
        timeline.get("event_label", ""),
        timeline.get("event_type", ""),
        timeline.get("notes", ""),
        clip.get("clip_type", ""),
        clip.get("recommended_uses", ""),
        clip.get("scoring_reason", ""),
        moment.get("title", ""),
        moment.get("moment_type", ""),
        moment.get("mood", ""),
    ]
    return " ".join(values).lower()


def essence_chapter_for(profile: ActivityProfile, text: str, moment_type: str) -> str:
    if not profile.essence_chapters:
        return moment_type or "general"
    best_name = "general"
    best_hits = 0
    for chapter, terms in profile.essence_chapters.items():
        hits = sum(1 for term in terms if profile_term_matches(term, text))
        if hits > best_hits:
            best_name = chapter
            best_hits = hits
    return best_name if best_hits else (moment_type or "general")


def profile_term_matches(term: str, text: str) -> bool:
    aliases = {
        "group_reactions": ["group", "reaction", "cheer", "laugh", "scream", "people"],
        "gopro": ["gopro", "gx", "pov"],
        "helmet_cam": ["helmet", "helmet cam", "pov", "gopro", "gx"],
        "rapids": ["rapid", "rapids"],
        "excitement": ["excite", "cheer", "laugh", "scream", "reaction"],
        "static": ["static", "still", "photo", "low_motion"],
        "walking": ["walk", "walking"],
        "talking": ["talk", "conversation", "briefing"],
        "mud": ["mud", "muddy"],
        "trail": ["trail", "jungle", "path", "ride"],
        "water_crossing": ["water crossing", "water", "splash", "puddle"],
        "slope": ["slope", "hill", "climb", "descent", "downhill", "uphill"],
        "tunnel": ["tunnel", "underpass", "narrow"],
        "turns": ["turn", "turns", "curve", "fast turns"],
        "speed": ["speed", "fast", "motion", "action"],
        "quad": ["quad", "atv", "ride"],
    }
    needles = aliases.get(term, [term.replace("_", " ")])
    return any(needle in text for needle in needles)


def activity_bucket_for(config: ReelConfig, moment_type: str, role: str) -> str:
    if moment_type in {"arrival", "safety_briefing", "gear_up", "walk_to_start"} or role in {"hook", "setup"}:
        return "opening"
    if moment_type in {"group_photo", "meal", "return_trip"} or role == "closing":
        return "ending"
    return "middle"


def is_group_ending(moment: dict[str, str], timeline: dict[str, str]) -> bool:
    text = f"{moment.get('title', '')} {moment.get('moment_type', '')} {timeline.get('event_label', '')}".lower()
    return "group" in text or "photo" in text or "final" in text


def final_reel_score_for(
    config: ReelConfig,
    *,
    activity_score: float,
    adventure_score: float,
    emotion_score: float,
    story_score: float,
    technical_score: float,
    diversity_score: float,
) -> float:
    weights = config.activity_profile.reel_weights
    score = (
        activity_score * weights.get("activity", 0.35)
        + adventure_score * weights.get("adventure", 0.20)
        + emotion_score * weights.get("emotion", 0.15)
        + story_score * weights.get("story", 0.15)
        + technical_score * weights.get("technical", 0.10)
        + diversity_score * weights.get("diversity", 0.05)
    )
    return clamp_score(score)


def activity_visual_score_for(config: ReelConfig, clip: dict[str, str], quality: float, motion_score: float, action_score: float) -> float:
    clarity = visual_clarity_score(quality, clip)
    if config.activity_profile.optimization_goal == "adventure":
        return clamp_score(clarity * 0.40 + action_score * 0.32 + clamp_score(motion_score) * 0.28)
    return clamp_score(clarity * 0.58 + action_score * 0.18 + clamp_score(motion_score) * 0.24)


def path_matches_patterns(path: str, patterns: list[str]) -> bool:
    lowered = path.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def camera_perspective_tags(path: str) -> tuple[str, ...]:
    name = Path(path).name.lower()
    if name.startswith(("gx", "gopr", "gop")):
        return ("action_camera_pov",)
    if name.startswith(("img_", "pxl_", "dsc", "mvimg")):
        return ("phone_perspective",)
    if any(token in name for token in ("meta", "rayban", "dana")):
        return ("group_camera_perspective",)
    if name.startswith(("dji", "air", "mavic")):
        return ("aerial_perspective",)
    return ("camera_perspective",)


def merge_visual_tags(*tag_groups: Iterable[str]) -> tuple[str, ...]:
    merged: list[str] = []
    for tags in tag_groups:
        for tag in tags:
            cleaned = str(tag).strip()
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
    return tuple(merged)


def source_perspective(candidate: ReelCandidate) -> str:
    tags = set(candidate.visual_tags.split(","))
    if "action_camera_pov" in tags:
        return "action_camera"
    if "phone_perspective" in tags:
        return "phone"
    if "group_camera_perspective" in tags:
        return "group_camera"
    if "aerial_perspective" in tags:
        return "aerial"
    return "camera"


def story_order_for(config: ReelConfig, moment_type: str, is_group_perspective: bool = False) -> float:
    if is_group_perspective:
        if "rapids" in config.moment_story_order:
            return config.moment_story_order.index("rapids") + 0.6
        if "splash" in config.moment_story_order:
            return config.moment_story_order.index("splash") + 0.2
    try:
        return float(config.moment_story_order.index(moment_type))
    except ValueError:
        return float(len(config.moment_story_order) + 1)


def group_audio_events(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("video_path", ""), []).append(row)
    return grouped


def best_timeline_for_clip(clip: dict[str, str], timeline_rows: list[dict[str, str]]) -> dict[str, str]:
    video_path = clip.get("video_path", "")
    moment_id = clip.get("moment_id", "")
    clip_start = safe_float(clip.get("start_seconds"))
    clip_end = safe_float(clip.get("end_seconds"), clip_start + safe_float(clip.get("duration_seconds")))
    matches = [
        row
        for row in timeline_rows
        if row.get("video_path") == video_path
        and (not moment_id or row.get("moment_id") == moment_id)
        and ranges_overlap(clip_start, clip_end, safe_float(row.get("start_seconds")), safe_float(row.get("end_seconds")))
    ]
    if not matches:
        return {}
    return max(matches, key=lambda row: safe_float(row.get("reel_value_score"), 0))


def ranges_overlap(left_start: float, left_end: float, right_start: float, right_end: float) -> bool:
    return max(left_start, right_start) < min(left_end, right_end)


def choose_segment_window(config: ReelConfig, clip: dict[str, str], timeline: dict[str, str], clip_start: float, clip_end: float) -> tuple[float, float]:
    duration = max(0.0, clip_end - clip_start)
    role = role_for_candidate(clip, timeline, {})
    motion_score = motion_from_scoring_reason(clip.get("scoring_reason", ""))
    action_score = safe_float(clip.get("action_score"), 50)
    audio_score = safe_float(clip.get("audio_score"), 50)
    immersive = config.target_duration_seconds >= 120
    target = config.max_segment_seconds
    if role == "hook":
        target = min(target, 4.0 if immersive else 2.8)
    elif role == "reaction":
        target = min(target, 6.0 if immersive else 4.0)
    elif role == "closing":
        target = min(target, 6.0 if immersive else 4.0)
    elif role == "action":
        if config.activity_profile.optimization_goal == "adventure":
            if immersive:
                target = min(target, 10.0 if max(action_score, motion_score, audio_score) >= 75 else 7.0)
            else:
                target = min(target, 4.6 if max(action_score, motion_score, audio_score) >= 75 else 3.8)
        else:
            target = min(target, 8.0 if immersive else 4.2)
    elif role == "scenic":
        target = min(target, 8.0 if immersive else 3.6)
    target = max(config.min_segment_seconds, min(target, duration if duration else target))
    if duration <= target:
        return clip_start, clip_end
    if role in {"hook", "setup"}:
        start = clip_start
    elif role == "closing":
        start = clip_end - target
    elif role == "action":
        # Long action clips often build to a better moment after the first second or two.
        energy_ratio = 0.48 if max(motion_score, audio_score) >= 70 else 0.38
        start = clip_start + max(0.0, (duration - target) * energy_ratio)
    elif role == "reaction":
        start = clip_start + max(0.0, (duration - target) * 0.25)
    else:
        start = clip_start + max(0.0, (duration - target) * 0.35)
    return round(start, 3), round(min(clip_end, start + target), 3)


def role_for_candidate(clip: dict[str, str], timeline: dict[str, str], moment: dict[str, str]) -> str:
    moment_type = moment.get("moment_type", "")
    moment_title = moment.get("title", "").lower()
    text = " ".join(
        [
            clip.get("clip_type", ""),
            clip.get("recommended_uses", ""),
            clip.get("scoring_reason", ""),
            timeline.get("event_label", ""),
            timeline.get("event_type", ""),
            moment.get("moment_type", ""),
            moment.get("title", ""),
            moment.get("mood", ""),
        ]
    ).lower()
    if moment_type in {"return_trip", "meal"} or any(token in moment_title for token in ["drive home", "return"]):
        return "closing"
    if any(token in text for token in ["laugh", "cheer", "reaction", "group", "people"]):
        return "reaction"
    if any(token in text for token in ["safety", "helmet", "gear", "setup", "briefing"]):
        return "setup"
    if any(token in text for token in ["splash", "rapids", "action", "launch", "adventure"]):
        return "action"
    if any(token in text for token in ["opening", "leaving", "arrival", "arriving"]) and safe_float(clip.get("start_seconds")) <= 5:
        return "hook"
    if any(token in text for token in ["river", "scenic", "calm"]):
        return "scenic"
    return "supporting"


def audio_energy_score(audio_rows: list[dict[str, str]], start: float, end: float) -> float:
    overlapping = [
        row
        for row in audio_rows
        if ranges_overlap(start, end, safe_float(row.get("start_seconds")), safe_float(row.get("end_seconds")))
    ]
    if not overlapping:
        return 50.0
    scores = []
    for row in overlapping:
        score = safe_float(row.get("intensity_score"), 50)
        event_type = row.get("audio_event_type", "")
        if event_type in {"cheering_or_laughing_candidate", "loud_reaction_candidate"}:
            score += 18
        elif event_type == "river_or_action_noise":
            score += 8
        elif event_type == "silence_or_quiet":
            score -= 18
        scores.append(max(0.0, min(score, 100.0)))
    return mean(scores)


def diversity_seed_score(source_seen_count: int, role: str) -> float:
    score = 78.0 - min(source_seen_count * 5, 30)
    if role in {"hook", "action", "reaction", "closing"}:
        score += 6
    return max(35.0, min(score, 100.0))


def select_reel(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelSelection]:
    if not candidates:
        return []

    selected: list[ReelCandidate] = []
    selected_keys: set[tuple[str, float, float]] = set()
    moment_counts: dict[str, int] = {}
    video_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    bucket_durations: dict[str, float] = {"opening": 0.0, "middle": 0.0, "ending": 0.0}
    duration = 0.0
    opening_budget = max(0.0, config.activity_profile.opening_duration_seconds)
    ending_budget = max(0.0, config.activity_profile.ending_duration_seconds)
    middle_target = config.target_duration_seconds * config.activity_profile.middle_min_fraction

    def try_add(candidate: ReelCandidate, relaxed: bool = False, enforce_bucket_budget: bool = True) -> bool:
        nonlocal duration
        key = (candidate.source_media_path, candidate.segment_start_seconds, candidate.segment_end_seconds)
        if key in selected_keys:
            return False
        if overlaps_selected_source_window(candidate, selected):
            return False
        if len(selected) >= config.max_clips:
            return False
        if enforce_bucket_budget and candidate.activity_bucket == "opening" and bucket_durations["opening"] + candidate.segment_duration_seconds > opening_budget + 0.75:
            return False
        if enforce_bucket_budget and candidate.activity_bucket == "ending" and bucket_durations["ending"] + candidate.segment_duration_seconds > ending_budget + 0.75:
            return False
        if not relaxed and moment_counts.get(candidate.moment_id, 0) >= config.max_segments_per_moment:
            return False
        if video_counts.get(candidate.source_media_path, 0) >= config.max_segments_per_source_video:
            return False
        if role_counts.get(candidate.candidate_role, 0) >= role_limit(candidate.candidate_role, config):
            return False
        if duration + candidate.segment_duration_seconds > config.target_duration_seconds + 1 and len(selected) >= config.min_clips:
            return False
        selected.append(candidate)
        selected_keys.add(key)
        moment_counts[candidate.moment_id] = moment_counts.get(candidate.moment_id, 0) + 1
        video_counts[candidate.source_media_path] = video_counts.get(candidate.source_media_path, 0) + 1
        role_counts[candidate.candidate_role] = role_counts.get(candidate.candidate_role, 0) + 1
        bucket_durations[candidate.activity_bucket] = bucket_durations.get(candidate.activity_bucket, 0.0) + candidate.segment_duration_seconds
        duration += candidate.segment_duration_seconds
        return True

    opening_candidates = sorted(
        [candidate for candidate in candidates if candidate.activity_bucket == "opening"],
        key=lambda item: (opening_priority(item), -item.activity_score, -item.final_reel_score, item.story_order, item.segment_start_seconds),
    )
    for candidate in opening_candidates:
        if bucket_durations["opening"] >= opening_budget or len(selected) >= max(1, config.max_clips // 5):
            break
        if bucket_durations["opening"] > 0 and opening_priority(candidate) >= 3:
            continue
        try_add(candidate)

    group_perspective_count = 0
    for candidate in sorted([item for item in candidates if item.candidate_role == "group_action"], key=lambda item: -item.final_reel_score):
        if group_perspective_count >= config.group_perspective_min_segments:
            break
        if try_add(candidate, relaxed=True):
            group_perspective_count += 1

    required_middle_types = [moment_type for moment_type in config.required_moment_types if moment_type not in {"arrival", "safety_briefing", "gear_up", "walk_to_start", "group_photo", "meal", "return_trip"}]
    for moment_type in required_middle_types:
        moment_candidates = [candidate for candidate in candidates if candidate.moment_type == moment_type and candidate.activity_bucket == "middle"]
        if moment_candidates:
            try_add(max(moment_candidates, key=lambda item: (item.activity_score, item.final_reel_score)), enforce_bucket_budget=False)

    for tag in required_visual_tags_for_variant(config):
        tag_candidates = [candidate for candidate in candidates if candidate.activity_bucket == "middle" and tag in candidate.visual_tags.split(",")]
        if tag_candidates:
            try_add(max(tag_candidates, key=lambda item: (item.final_reel_score, item.activity_confidence)), relaxed=True, enforce_bucket_budget=False)

    group_photo_candidates = sorted(
        [candidate for candidate in candidates if candidate.activity_bucket == "ending"],
        key=lambda item: (-item.memory_score, -item.activity_score, -item.final_reel_score, item.segment_start_seconds),
    )
    for candidate in group_photo_candidates[:2]:
        if len(selected) >= config.max_clips:
            break
        try_add(candidate, relaxed=True)

    middle_candidates = sorted(
        [candidate for candidate in candidates if candidate.activity_bucket == "middle"],
        key=lambda item: (-item.activity_score, -item.final_reel_score, item.story_order, item.segment_start_seconds, item.source_media_path),
    )
    for candidate in middle_candidates:
        if bucket_durations["middle"] >= middle_target or duration >= config.target_duration_seconds or len(selected) >= config.max_clips:
            break
        try_add(candidate, enforce_bucket_budget=False)

    ending_candidates = sorted(
        [candidate for candidate in candidates if candidate.activity_bucket == "ending"],
        key=lambda item: (-item.activity_score, -item.final_reel_score, item.story_order, item.segment_start_seconds),
    )
    for candidate in ending_candidates:
        if bucket_durations["ending"] >= ending_budget or duration >= config.target_duration_seconds or len(selected) >= config.max_clips:
            break
        try_add(candidate)

    for candidate in sorted(candidates, key=lambda item: (-item.activity_score, item.story_order, -item.final_reel_score, item.segment_start_seconds, item.source_media_path)):
        if duration >= config.target_duration_seconds or len(selected) >= config.max_clips:
            break
        try_add(candidate)

    if duration < config.target_duration_seconds * 0.85 or len(selected) < config.min_clips:
        for candidate in sorted(candidates, key=lambda item: (-item.final_reel_score, -item.activity_score)):
            if duration >= config.target_duration_seconds or len(selected) >= config.max_clips:
                break
            try_add(candidate, relaxed=True, enforce_bucket_budget=False)

    ordered = ensure_reel_speed_mix(config, trim_weak_opening_candidates(config, order_selected(config, selected)))
    selections: list[ReelSelection] = []
    output_cursor = 0.0
    for index, candidate in enumerate(ordered, start=1):
        start = output_cursor
        end = start + candidate.segment_duration_seconds
        selections.append(
            ReelSelection(
                candidate=candidate,
                sequence=index,
                output_start_seconds=round(start, 3),
                output_end_seconds=round(end, 3),
                selection_reason=selection_reason(candidate),
            )
        )
        output_cursor = end
    return selections


def ensure_reel_speed_mix(config: ReelConfig, ordered: list[ReelCandidate]) -> list[ReelCandidate]:
    if config.variant == "selected_timeline" or not config.speed_ramps_enabled or not ordered:
        return ordered
    fast_count = sum(1 for candidate in ordered if candidate.speed_factor > 1.01)
    action_indexes = [
        index
        for index, candidate in enumerate(ordered)
        if reel_speed_candidate(config, candidate)
    ]
    if fast_count or not action_indexes:
        return ordered
    target_fast = max(1, min(len(action_indexes) // 3 + 1, max(1, len(ordered) // 4)))
    updated = list(ordered)
    for index in action_indexes[1::3] or action_indexes[:target_fast]:
        if target_fast <= 0:
            break
        candidate = updated[index]
        source_duration = max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds)
        speed = min(config.max_speed_factor, 3.0 if candidate.audio_energy_score >= 72 or candidate.action_score >= 80 else 1.5)
        updated[index] = replace(
            candidate,
            speed_factor=round(speed, 3),
            segment_duration_seconds=round(source_duration / speed, 3),
        )
        target_fast -= 1
    return updated


def reel_speed_candidate(config: ReelConfig, candidate: ReelCandidate) -> bool:
    if candidate.activity_bucket in {"opening", "ending"}:
        return False
    if candidate.candidate_role not in {"action", "group_action", "supporting", "scenic"}:
        return False
    tags = set(candidate.visual_tags.split(","))
    dynamic_tags = {
        "action",
        "trail",
        "ride",
        "turns",
        "mud",
        "water",
        "ocean",
        "beach",
        "water_crossing",
        "water_speed_run",
        "mud_water_run",
        "mud_action",
        "lit_tunnel",
        "tunnel_or_shade",
        "speed_action",
        "rough_motion",
        "jungle_trail",
    }
    if tags.intersection(dynamic_tags):
        return True
    if config.activity_profile.optimization_goal == "adventure" and max(candidate.action_score, candidate.audio_energy_score, candidate.adventure_score) >= 70:
        return True
    if config.activity_profile.optimization_goal == "cinematic" and max(candidate.cinematic_score, candidate.activity_score) >= 75:
        return True
    return False


def opening_priority(candidate: ReelCandidate) -> int:
    text = f"{candidate.moment_type} {candidate.moment_title} {candidate.timeline_label}".lower()
    if any(token in text for token in ["walk", "stairs", "start"]):
        return 0
    if any(token in text for token in ["gear", "helmet"]):
        return 1
    if "arrival" in text:
        return 2
    return 3


def trim_weak_opening_candidates(config: ReelConfig, ordered: list[ReelCandidate]) -> list[ReelCandidate]:
    if config.activity_profile.name.lower() != "atv" or not ordered:
        return ordered
    trimmed = list(ordered)
    while len(trimmed) > config.min_clips and trimmed and not strong_opening_action(trimmed[0]):
        if any(strong_opening_action(candidate) for candidate in trimmed[1:]):
            trimmed.pop(0)
        else:
            break
    return trimmed


def strong_opening_action(candidate: ReelCandidate) -> bool:
    tags = set(candidate.visual_tags.split(","))
    return bool(tags.intersection({"water_crossing", "tunnel_or_shade", "speed_action", "rough_motion", "jungle_trail"}))


def role_limit(role: str, config: ReelConfig) -> int:
    limits = {
        "hook": 2,
        "setup": 2,
        "reaction": 3,
        "closing": 1,
        "group_action": 3,
        "scenic": 3,
        "supporting": 3,
    }
    if role == "action":
        return max(5, config.max_clips)
    return limits.get(role, config.max_clips)


def required_visual_tags_for_variant(config: ReelConfig) -> list[str]:
    if config.activity_profile.name.lower() != "atv":
        return []
    if config.variant == "action_audio":
        return ["lit_tunnel", "tunnel_or_shade", "water_speed_run", "mud_water_run", "water_crossing", "speed_action", "rough_motion", "jungle_trail"]
    return ["lit_tunnel", "tunnel_or_shade", "water_speed_run", "mud_water_run", "water_crossing", "speed_action"]


def order_selected(config: ReelConfig, selected: list[ReelCandidate]) -> list[ReelCandidate]:
    if not selected:
        return []
    if config.chronological in {"strict", "timeline", "source"}:
        return sorted(
            selected,
            key=lambda item: (
                source_chronology_key(item.source_media_path),
                item.segment_start_seconds,
                item.story_order,
                -item.final_reel_score,
            ),
        )
    if config.chronological in {"yes", "mostly", "true"}:
        return sorted(
            selected,
            key=lambda item: (
                bucket_order(item),
                opening_priority(item),
                item.story_order,
                source_chronology_key(item.source_media_path),
                item.segment_start_seconds,
                -item.final_reel_score,
            ),
        )
    return sorted(selected, key=lambda item: -item.final_reel_score)


def overlaps_selected_source_window(candidate: ReelCandidate, selected: list[ReelCandidate]) -> bool:
    for item in selected:
        if item.source_media_path != candidate.source_media_path:
            continue
        if ranges_overlap(
            candidate.segment_start_seconds - 0.25,
            candidate.segment_end_seconds + 0.25,
            item.segment_start_seconds,
            item.segment_end_seconds,
        ):
            return True
    return False


def source_chronology_key(path: str) -> tuple[object, ...]:
    source = Path(path)
    parent = source.parent.as_posix().lower()
    timestamp = source_capture_timestamp(path)
    if timestamp is not None:
        return 0, timestamp, parent, opaque_source_penalty(source.name), natural_key(source.stem.lower())
    return 1, parent, opaque_source_penalty(source.name), natural_key(source.stem.lower())


def source_capture_timestamp(path: str) -> float | None:
    normalized = normalize_source_path(path)
    if normalized in SOURCE_CHRONOLOGY_BY_PATH:
        return SOURCE_CHRONOLOGY_BY_PATH[normalized]
    return SOURCE_CHRONOLOGY_BY_NAME.get(Path(path).name.lower())


def opaque_source_penalty(name: str) -> int:
    lowered = name.lower()
    if lowered.startswith(("gx", "gopr", "gop", "img_", "dji")):
        return 0
    return 1


def natural_key(value: str) -> tuple[tuple[int, object], ...]:
    parts: list[tuple[int, object]] = []
    for token in re.split(r"(\d+)", value):
        if not token:
            continue
        parts.append((0, int(token)) if token.isdigit() else (1, token))
    return tuple(parts)


def bucket_order(candidate: ReelCandidate) -> int:
    if candidate.activity_bucket == "opening":
        return 0
    if candidate.activity_bucket == "ending":
        return 2
    return 1


def selection_reason(candidate: ReelCandidate) -> str:
    reasons = [
        f"final reel score {candidate.final_reel_score}",
        f"activity score {candidate.activity_score}",
        f"{candidate.activity_bucket} bucket",
        f"{candidate.candidate_role} role",
    ]
    if candidate.adventure_score >= 80:
        reasons.append("strong activity/adventure fit")
    if candidate.action_score >= 85:
        reasons.append("strong action")
    if candidate.candidate_role == "group_action":
        reasons.append("group/action perspective")
    if candidate.audio_energy_score >= 70:
        reasons.append("strong natural audio")
    if candidate.story_score >= 75:
        reasons.append("strong story value")
    if candidate.activity_confidence >= 70:
        reasons.append(f"visual fit {candidate.activity_confidence}")
    if candidate.speed_factor > 1:
        reasons.append(f"{candidate.speed_factor}x action pace")
    return "; ".join(reasons)


def select_master_highlight(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelSelection]:
    """Create the canonical activity timeline used by reels and documentaries."""
    if not candidates:
        return []

    selected: list[ReelCandidate] = []
    duration = 0.0
    source_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    source_layout_counts: dict[tuple[str, str], int] = {}

    def try_add(candidate: ReelCandidate, relaxed: bool = False) -> bool:
        nonlocal duration
        if duration >= config.target_duration_seconds:
            return False
        if overlaps_selected_source_window(candidate, selected):
            return False
        if source_counts.get(candidate.source_media_path, 0) >= config.highlight_max_per_source_video and not relaxed:
            return False
        layout_key = selected_timeline_layout_key(candidate)
        if layout_key and source_layout_counts.get((candidate.source_media_path, layout_key), 0) >= selected_timeline_layout_limit(config, layout_key):
            return False
        if len(selected) >= config.max_clips:
            return False
        selected.append(candidate)
        source_counts[candidate.source_media_path] = source_counts.get(candidate.source_media_path, 0) + 1
        role_counts[candidate.candidate_role] = role_counts.get(candidate.candidate_role, 0) + 1
        if layout_key:
            source_layout_counts[(candidate.source_media_path, layout_key)] = source_layout_counts.get((candidate.source_media_path, layout_key), 0) + 1
        for tag in candidate.visual_tags.split(","):
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        duration += candidate.segment_duration_seconds
        return True

    strong_candidates = [
        candidate
        for candidate in candidates
        if candidate.activity_mismatch != "yes"
        and candidate.activity_confidence >= max(35.0, config.min_activity_confidence)
        and "ground_only" not in candidate.visual_tags.split(",")
        and selected_timeline_candidate_allowed(config, candidate)
    ]
    if not strong_candidates:
        strong_candidates = candidates

    required_tags = required_visual_tags_for_variant(config)
    for tag in required_tags:
        tag_candidates = [
            candidate
            for candidate in strong_candidates
            if tag in candidate.visual_tags.split(",") and candidate.activity_bucket == "middle"
        ]
        if tag_candidates:
            try_add(max(tag_candidates, key=master_highlight_rank), relaxed=True)

    if config.activity_profile.name.lower() == "rafting":
        river_perspective_candidates = [
            candidate
            for candidate in strong_candidates
            if source_perspective(candidate) in {"phone", "group_camera"}
            and set(candidate.visual_tags.split(",")).intersection({"river_scene", "river_people", "water", "water_crossing", "group_reaction", "face_visible"})
        ]
        perspective_sources: set[str] = set()
        for candidate in sorted(river_perspective_candidates, key=master_highlight_rank, reverse=True):
            if candidate.source_media_path in perspective_sources:
                continue
            if try_add(candidate, relaxed=True):
                perspective_sources.add(candidate.source_media_path)
            if len(perspective_sources) >= 8:
                break

    if config.variant == "selected_timeline" and (
        config.activity_profile.optimization_goal in {"memory", "social", "cinematic"} or profile_values_people(config)
    ):
        memory_tags = {
            "face_visible",
            "people_visible",
            "group_reaction",
            "pool_action",
            "pool",
            "pool_jump",
            "swimming",
            "water",
            "celebration",
            "dancing",
            "food",
        }
        memory_sources: set[str] = set()
        memory_candidates = [
            candidate
            for candidate in strong_candidates
            if (
                candidate.final_reel_score >= 88
                or (
                    candidate.final_reel_score >= 82
                    and candidate.activity_confidence >= 80
                    and set(candidate.visual_tags.split(",")).intersection({"pool", "water", "scenic", "landscape"})
                )
            )
            and set(candidate.visual_tags.split(",")).intersection(memory_tags)
        ]
        for candidate in sorted(memory_candidates, key=master_highlight_rank, reverse=True):
            if candidate.source_media_path in memory_sources:
                continue
            if try_add(candidate, relaxed=True):
                memory_sources.add(candidate.source_media_path)
            if len(memory_sources) >= max(8, min(config.max_clips, round(config.max_clips * 0.75))):
                break

    for source_path in sorted({candidate.source_media_path for candidate in strong_candidates}, key=source_chronology_key):
        source_candidates = [candidate for candidate in strong_candidates if candidate.source_media_path == source_path]
        if not source_candidates:
            continue
        for tag in source_event_coverage_tags(config):
            tag_candidates = [candidate for candidate in source_candidates if tag in candidate.visual_tags.split(",")]
            if tag_candidates:
                for candidate in separated_top_candidates(tag_candidates, limit=source_event_coverage_limit(tag), min_gap_seconds=45.0):
                    try_add(candidate, relaxed=True)
        top_windows = sorted(source_candidates, key=master_highlight_rank, reverse=True)[: max(1, config.highlight_max_per_source_video)]
        for candidate in sorted(top_windows, key=lambda item: item.segment_start_seconds):
            if candidate.final_reel_score < 42 and not required_tags:
                continue
            try_add(candidate)

    for candidate in selected_timeline_late_payoff_candidates(config, strong_candidates):
        try_add(candidate, relaxed=True)

    if duration < config.target_duration_seconds * 0.65:
        for candidate in sorted(strong_candidates, key=master_highlight_rank, reverse=True):
            if duration >= config.target_duration_seconds or len(selected) >= config.max_clips:
                break
            try_add(candidate, relaxed=True)

    ordered = order_selected(replace(config, chronological="strict"), selected)
    ordered = remove_selected_timeline_story_regressions(config, ordered)
    selections: list[ReelSelection] = []
    output_cursor = 0.0
    for index, candidate in enumerate(ordered, start=1):
        start = output_cursor
        end = start + candidate.segment_duration_seconds
        selections.append(
            ReelSelection(
                candidate=candidate,
                sequence=index,
                output_start_seconds=round(start, 3),
                output_end_seconds=round(end, 3),
                selection_reason=selection_reason(candidate),
            )
        )
        output_cursor = end
    return selections


def remove_selected_timeline_story_regressions(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelCandidate]:
    """Keep chronological order while removing visual stage backtracking."""
    profile_name = config.activity_profile.name.lower()
    if profile_name not in {"waterfall", "beach", "ricefield", "temple"} or len(candidates) < 4:
        return candidates
    if profile_name == "waterfall":
        return remove_waterfall_story_regressions(config, candidates)
    return candidates


def remove_waterfall_story_regressions(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelCandidate]:
    kept: list[ReelCandidate] = []
    main_water_started = False
    setup_count = 0
    min_keep = max(10, int(len(candidates) * 0.48))
    for candidate in candidates:
        stage = waterfall_story_stage(candidate)
        if not main_water_started and stage <= 1:
            setup_count += 1
            if setup_count > 4 and not waterfall_high_memory_transition(candidate):
                if len(candidates) - len(kept) > min_keep:
                    continue
        if main_water_started and stage <= 1 and not waterfall_valid_closing(candidate):
            if len(candidates) - len(kept) > min_keep:
                continue
        kept.append(candidate)
        if stage >= 3:
            main_water_started = True
    return kept or candidates


def waterfall_story_stage(candidate: ReelCandidate) -> int:
    tags = set(candidate.visual_tags.split(","))
    water = audit_metric(candidate.audit_reason, "water")
    green = audit_metric(candidate.audit_reason, "green")
    gray_floor = audit_metric(candidate.audit_reason, "gray_floor")
    face = audit_metric(candidate.audit_reason, "face")
    people_tags = tags.intersection({"face_visible", "people_visible", "group_reaction"})
    if tags.intersection({"bad_orientation", "ground_only", "setup_surface", "weak_close_pov"}):
        return 0
    if "waterfall" in tags or "scenic" in tags or "landscape" in tags:
        return 4
    if water >= 0.34 and gray_floor >= 0.45:
        return 4
    if water >= 0.24 and (people_tags or "hero_action" in tags):
        return 3
    if water >= 0.30:
        return 3
    if "jungle_trail" in tags and water < 0.25 and green >= 0.28 and face < 0.25:
        return 1
    if "tunnel_or_shade" in tags and water < 0.24 and not people_tags:
        return 1
    return 2


def waterfall_high_memory_transition(candidate: ReelCandidate) -> bool:
    tags = set(candidate.visual_tags.split(","))
    return bool(tags.intersection({"face_visible", "group_reaction"})) and candidate.final_reel_score >= 88


def waterfall_valid_closing(candidate: ReelCandidate) -> bool:
    tags = set(candidate.visual_tags.split(","))
    water = audit_metric(candidate.audit_reason, "water")
    return bool(tags.intersection({"face_visible", "group_reaction"})) and water >= 0.22 and candidate.final_reel_score >= 82


def selected_timeline_late_payoff_candidates(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelCandidate]:
    payoff_tags = late_payoff_tags_for_profile(config.activity_profile.name)
    if not payoff_tags:
        return []
    payoff_candidates: list[ReelCandidate] = []
    for source_path in sorted({candidate.source_media_path for candidate in candidates}, key=source_chronology_key):
        source_candidates = [candidate for candidate in candidates if candidate.source_media_path == source_path]
        if not source_candidates:
            continue
        source_duration = source_duration_for_path(source_path) or max(candidate.segment_end_seconds for candidate in source_candidates)
        tail_start = source_duration * 0.55
        tagged_tail = [
            candidate
            for candidate in source_candidates
            if candidate.segment_start_seconds >= tail_start
            and set(candidate.visual_tags.split(",")).intersection(payoff_tags)
            and not set(candidate.visual_tags.split(",")).intersection({"ground_only", "setup_surface", "weak_close_pov"})
        ]
        if tagged_tail:
            payoff_candidates.append(max(tagged_tail, key=late_payoff_rank))
    return sorted(payoff_candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))


def late_payoff_tags_for_profile(profile_name: str) -> set[str]:
    normalized = profile_name.lower()
    if normalized == "atv":
        return {"water_speed_run", "mud_water_run", "speed_action", "lit_tunnel"}
    if normalized == "rafting":
        return {"splash", "rapids", "river_people", "river_scene", "water_crossing", "group_reaction"}
    if normalized in {"waterfall", "beach"}:
        return {"water", "scenic", "landscape", "group_reaction"}
    if normalized == "stay":
        return {"group_reaction", "face_visible", "people_visible", "celebration", "pool", "pool_action", "swimming", "pool_jump"}
    if normalized in {"savaya", "clubbing", "restaurants"}:
        return {"group_reaction", "face_visible", "people_visible", "celebration"}
    return set()


def late_payoff_rank(candidate: ReelCandidate) -> tuple[float, float, float]:
    tags = set(candidate.visual_tags.split(","))
    payoff_bonus = 0.0
    if "water_speed_run" in tags:
        payoff_bonus += 28.0
    if "lit_tunnel" in tags:
        payoff_bonus += 18.0
    if "speed_action" in tags:
        payoff_bonus += 12.0
    if "mud_water_run" in tags or "water_crossing" in tags:
        payoff_bonus += 10.0
    return (
        candidate.final_reel_score + payoff_bonus,
        candidate.segment_start_seconds,
        candidate.segment_duration_seconds,
    )


def source_event_coverage_tags(config: ReelConfig) -> list[str]:
    if config.activity_profile.name.lower() == "atv":
        return ["lit_tunnel", "water_speed_run", "mud_water_run", "water_crossing", "speed_action"]
    if config.activity_profile.name.lower() == "rafting":
        return [
            "river_people",
            "river_scene",
            "water_crossing",
            "water",
            "speed_action",
            "rough_motion",
            "group_reaction",
            "face_visible",
            "phone_perspective",
            "group_camera_perspective",
        ]
    if config.activity_profile.name.lower() == "stay":
        return ["pool_jump", "pool_action", "swimming", "pool", "group_reaction", "face_visible", "people_visible"]
    tags: list[str] = []
    if profile_values_people(config):
        tags.extend(["group_reaction", "face_visible", "people_visible"])
    if config.activity_profile.optimization_goal in {"cinematic", "memory", "social"}:
        tags.extend(["water_crossing", "water", "scenic", "landscape"])
    return list(dict.fromkeys(tags))


def selected_timeline_candidate_allowed(config: ReelConfig, candidate: ReelCandidate) -> bool:
    if config.variant != "selected_timeline":
        return True
    tags = set(candidate.visual_tags.split(","))
    if tags.intersection({"ground_only", "setup_surface", "weak_close_pov", "unstable_roll", "bad_orientation"}):
        return False
    if config.activity_profile.name.lower() == "rafting" and "action_camera_pov" in tags:
        has_scene_value = tags.intersection({"water_crossing", "river_scene", "river_people", "group_reaction", "face_visible", "people_visible"})
        if not has_scene_value:
            return False
    if tags.intersection(meaningful_event_tags_for_profile(config.activity_profile.name)):
        return True
    if profile_values_people(config) and tags.intersection({"face_visible", "people_visible", "group_reaction"}):
        return True
    text = selected_timeline_candidate_text(candidate)
    required_hits = [term for term in config.activity_profile.required_context if profile_term_matches(term, text)]
    maximize_hits = [term for term in config.activity_profile.maximize if profile_term_matches(term, text)]
    reject_hits = [term for term in config.activity_profile.reject_context if profile_term_matches(term, text)]
    if reject_hits and not required_hits:
        return False
    if config.activity_profile.name.lower() == "atv":
        # Plain ATV POV or mud-colored ground is not a timeline-worthy event by itself.
        return False
    if len(required_hits) >= 2:
        return True
    if required_hits and candidate.final_reel_score >= 65 and candidate.activity_score >= 72:
        return True
    if len(maximize_hits) >= 2 and candidate.final_reel_score >= 62:
        return True
    if not config.activity_profile.required_context and not config.activity_profile.maximize:
        return candidate.final_reel_score >= 68 and max(candidate.story_score, candidate.cinematic_score, candidate.emotion_score) >= 70
    return False


def meaningful_event_tags_for_profile(profile_name: str) -> set[str]:
    common = {
        "water_speed_run",
        "mud_water_run",
        "water_crossing",
        "tunnel_or_shade",
        "lit_tunnel",
        "speed_action",
        "rough_motion",
        "jungle_trail",
        "face_visible",
        "people_visible",
        "group_reaction",
    }
    by_profile = {
        "atv": common,
        "rafting": common | {"water", "river_scene", "river_people", "river_action", "splash", "rapids", "group_reaction"},
        "waterfall": common | {"water", "waterfall", "scenic", "landscape"},
        "beach": {"water", "scenic", "landscape", "group_reaction", "face_visible", "people_visible"},
        "temple": {"scenic", "landscape", "architecture", "group_reaction"},
        "ricefield": {"scenic", "landscape", "jungle_trail", "group_reaction"},
        "savaya": {"group_reaction", "nightlife", "dancing", "scenic"},
        "clubbing": {"group_reaction", "nightlife", "dancing", "scenic"},
        "restaurants": {"group_reaction", "food", "celebration"},
        "stay": {"group_reaction", "pool", "pool_action", "swimming", "pool_jump", "water", "celebration"},
    }
    return by_profile.get(profile_name.lower(), common | {"scenic", "landscape", "group_reaction"})


def selected_timeline_layout_key(candidate: ReelCandidate) -> str:
    tags = set(candidate.visual_tags.split(","))
    if tags.intersection({"phone_perspective", "group_camera_perspective"}) and tags.intersection({"river_scene", "river_people", "water", "water_crossing"}):
        return "river_people_perspective"
    if "action_camera_pov" in tags and tags.intersection({"water_crossing", "speed_action", "rough_motion"}):
        return "action_camera_water"
    if tags.intersection({"group_reaction", "face_visible", "people_visible"}):
        return "people_group"
    if tags.intersection({"water_speed_run", "mud_water_run", "water_crossing", "water"}):
        return "water_action"
    if tags.intersection({"pool_action", "swimming", "pool_jump", "pool"}):
        return "pool_action"
    if tags.intersection({"lit_tunnel", "tunnel_or_shade"}):
        return "tunnel"
    if tags.intersection({"jungle_trail", "scenic", "landscape"}):
        return "scenic"
    if tags.intersection({"speed_action", "rough_motion"}):
        return "motion"
    return ""


def selected_timeline_layout_limit(config: ReelConfig, layout_key: str) -> int:
    if config.activity_profile.name.lower() == "atv" and layout_key in {"action_camera_water", "water_action", "tunnel", "motion"}:
        return 5
    if config.activity_profile.name.lower() == "rafting":
        if layout_key == "action_camera_water":
            return 2
        if layout_key == "river_people_perspective":
            return 4
    if config.activity_profile.name.lower() == "stay" and layout_key == "pool_action":
        return 5
    if layout_key == "people_group":
        return 2
    return 2


def selected_timeline_candidate_text(candidate: ReelCandidate) -> str:
    return " ".join(
        [
            candidate.source_media_path,
            candidate.moment_type,
            candidate.moment_title,
            candidate.timeline_label,
            candidate.candidate_role,
            candidate.activity_reason,
            candidate.audit_reason,
            candidate.visual_tags,
        ]
    ).lower()


def source_event_coverage_limit(tag: str) -> int:
    if tag == "water_speed_run":
        return 4
    if tag == "mud_water_run":
        return 2
    return 1


def separated_top_candidates(candidates: list[ReelCandidate], limit: int, min_gap_seconds: float) -> list[ReelCandidate]:
    selected: list[ReelCandidate] = []
    for candidate in sorted(candidates, key=master_highlight_rank, reverse=True):
        if any(abs(candidate.segment_start_seconds - item.segment_start_seconds) < min_gap_seconds for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda item: item.segment_start_seconds)


def master_highlight_rank(candidate: ReelCandidate) -> tuple[float, float, float, float, float]:
    tag_bonus = 0.0
    tags = set(candidate.visual_tags.split(","))
    for tag, bonus in {
        "hero_action": 10.0,
        "water_crossing": 8.0,
        "water_speed_run": 12.0,
        "mud_water_run": 8.0,
        "tunnel_or_shade": 8.0,
        "lit_tunnel": 12.0,
        "mud_action": 6.0,
        "speed_action": 6.0,
        "rough_motion": 5.0,
        "jungle_trail": 4.0,
        "river_scene": 8.0,
        "river_people": 14.0,
        "pool": 8.0,
        "pool_action": 14.0,
        "swimming": 12.0,
        "pool_jump": 18.0,
        "group_reaction": 10.0,
        "face_visible": 8.0,
        "people_visible": 6.0,
    }.items():
        if tag in tags:
            tag_bonus += bonus
    if "ground_only" in tags:
        tag_bonus -= 30.0
    if "weak_close_pov" in tags:
        tag_bonus -= 46.0
    if source_perspective(candidate) in {"phone", "group_camera"} and tags.intersection({"river_scene", "river_people", "water", "water_crossing"}):
        tag_bonus += 18.0
    if source_perspective(candidate) == "action_camera" and not tags.intersection({"river_scene", "river_people", "water_crossing", "group_reaction", "face_visible"}):
        tag_bonus -= 12.0
    if "lit_tunnel" in tags:
        tag_bonus += metric_from_scoring_reason(candidate.audit_reason, "dark", 0.0) * 14.0
        tag_bonus += metric_from_scoring_reason(candidate.audit_reason, "orange", 0.0) * 22.0
        tag_bonus -= metric_from_scoring_reason(candidate.audit_reason, "edge", 0.0) * 8.0
    if "water_speed_run" in tags:
        tag_bonus += metric_from_scoring_reason(candidate.audit_reason, "mud", 0.0) * 5.0
        tag_bonus += metric_from_scoring_reason(candidate.audit_reason, "water", 0.0) * 8.0
    if tags.intersection({"group_reaction", "face_visible", "people_visible"}):
        tag_bonus += metric_from_scoring_reason(candidate.audit_reason, "face", 0.0) * 16.0
        tag_bonus += min(metric_from_scoring_reason(candidate.audit_reason, "max_faces", 0.0) * 3.0, 12.0)
    return (
        candidate.activity_score + candidate.adventure_score * 0.55 + candidate.final_reel_score * 0.45 + tag_bonus,
        candidate.activity_confidence,
        candidate.action_score,
        candidate.audio_energy_score,
        -candidate.segment_start_seconds,
    )


def highlight_timeline_row(selection: ReelSelection) -> dict[str, object]:
    candidate = selection.candidate
    return {
        "highlight_sequence": selection.sequence,
        "media_set": candidate.media_set,
        "activity": candidate.activity,
        "source_media_path": candidate.source_media_path,
        "source_start_seconds": candidate.segment_start_seconds,
        "source_end_seconds": candidate.segment_end_seconds,
        "source_duration_seconds": round(candidate.segment_end_seconds - candidate.segment_start_seconds, 3),
        "timeline_event_id": candidate.timeline_event_id,
        "timeline_label": candidate.timeline_label,
        "moment_id": candidate.moment_id,
        "moment_title": candidate.moment_title,
        "visual_tags": candidate.visual_tags,
        "activity_confidence": candidate.activity_confidence,
        "highlight_score": round(master_highlight_rank(candidate)[0], 2),
        "recommended_speed": candidate.speed_factor,
        "selection_role": candidate.candidate_role,
        "selection_reason": selection.selection_reason,
    }


def aspect_ratio_for(config: ReelConfig) -> str:
    width = max(1, config.render.width)
    height = max(1, config.render.height)
    if height > width:
        return "9:16"
    if width > height:
        return "16:9"
    return "1:1"


def output_file_for(config: ReelConfig) -> Path:
    safe_id = slugify(config.reel_id)
    safe_style = slugify(config.variant or config.style)
    duration = int(round(config.target_duration_seconds))
    orientation = "vertical" if config.render.height > config.render.width else "landscape"
    return config.exports_dir / f"{safe_id}_{safe_style}_{duration}s_{orientation}.mp4"


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def candidate_row(candidate: ReelCandidate, selected_keys: set[tuple[str, float, float]]) -> dict[str, object]:
    key = (candidate.source_media_path, candidate.segment_start_seconds, candidate.segment_end_seconds)
    selected = key in selected_keys
    return {
        **candidate.__dict__,
        "selection_status": "selected" if selected else "not_selected",
        "selection_reason": selection_reason(candidate) if selected else "",
        "exclusion_reason": "" if selected else "lower score or constrained by moment/source diversity",
    }


def selection_row(selection: ReelSelection, config: ReelConfig) -> dict[str, object]:
    candidate = selection.candidate
    transform = transform_for_candidate(candidate, config)
    audio_mode = effective_segment_audio_mode(config, candidate)
    if audio_mode != "mute" and muted_audio_windows_for_selection(config, candidate, candidate.speed_factor):
        audio_mode = "keep_source_filtered"
    return {
        "reel_id": candidate.reel_id,
        "reel_style": candidate.reel_style,
        "reel_sequence": selection.sequence,
        "media_set": candidate.media_set,
        "activity": candidate.activity,
        "moment_id": candidate.moment_id,
        "moment_title": candidate.moment_title,
        "timeline_event_id": candidate.timeline_event_id,
        "source_media_path": candidate.source_media_path,
        "source_start_seconds": candidate.segment_start_seconds,
        "source_end_seconds": candidate.segment_end_seconds,
        "output_start_seconds": selection.output_start_seconds,
        "output_end_seconds": selection.output_end_seconds,
        "output_duration_seconds": round(selection.output_end_seconds - selection.output_start_seconds, 3),
        "crop_mode": transform,
        "crop_anchor": "center",
        "audio_mode": audio_mode,
        "caption_text": caption_text(candidate),
        "selected_role": candidate.candidate_role,
        "activity_bucket": candidate.activity_bucket,
        "activity_score": candidate.activity_score,
        "adventure_score": candidate.adventure_score,
        "emotion_score": candidate.emotion_score,
        "visual_tags": candidate.visual_tags,
        "activity_confidence": candidate.activity_confidence,
        "activity_mismatch": candidate.activity_mismatch,
        "speed_factor": candidate.speed_factor,
        "final_reel_score": candidate.final_reel_score,
        "selection_reason": selection.selection_reason,
    }


def edit_decision_row(selection: ReelSelection, config: ReelConfig) -> dict[str, object]:
    candidate = selection.candidate
    transform = transform_for_candidate(candidate, config)
    audio_mode = effective_segment_audio_mode(config, candidate)
    return {
        "reel_id": candidate.reel_id,
        "edit_sequence": selection.sequence,
        "source_media_path": candidate.source_media_path,
        "source_start_seconds": candidate.segment_start_seconds,
        "source_end_seconds": candidate.segment_end_seconds,
        "output_start_seconds": selection.output_start_seconds,
        "output_end_seconds": selection.output_end_seconds,
        "output_width": config.render.width,
        "output_height": config.render.height,
        "aspect_ratio": aspect_ratio_for(config),
        "transform": transform,
        "crop_anchor_x": 0.5,
        "crop_anchor_y": 0.5,
        "source_audio_enabled": "yes" if audio_mode != "mute" else "no",
        "music_enabled": "yes" if config.render.music_enabled and config.render.music_path else "no",
        "playback_speed": candidate.speed_factor,
        "caption_enabled": "no",
        "caption_text": caption_text(candidate),
        "transition_type": transition_type_for(selection),
        "transition_duration_seconds": transition_duration_for(selection),
    }


def caption_text(candidate: ReelCandidate) -> str:
    if candidate.candidate_role in {"hook", "closing"}:
        return candidate.moment_title
    return ""


def transform_for_candidate(candidate: ReelCandidate, config: ReelConfig) -> str:
    return config.render.crop_mode


def write_reports(
    config: ReelConfig,
    project_root: Path,
    candidates: list[ReelCandidate],
    selections: list[ReelSelection],
    rendered_file: Path,
    render_status: str,
    render_reason: str,
) -> tuple[Path, Path, Path, Path, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    candidates_csv = config.output_dir / "reel_candidates.csv"
    selection_csv = config.output_dir / "reel_selection.csv"
    edit_decisions_csv = config.output_dir / "reel_edit_decisions.csv"
    manifest_csv = config.output_dir / "reel_manifest.csv"
    report_md = config.output_dir / "reel_report.md"

    selected_keys = {
        (selection.candidate.source_media_path, selection.candidate.segment_start_seconds, selection.candidate.segment_end_seconds)
        for selection in selections
    }
    write_csv(candidates_csv, REEL_CANDIDATE_COLUMNS, [candidate_row(candidate, selected_keys) for candidate in candidates])
    write_csv(selection_csv, REEL_SELECTION_COLUMNS, [selection_row(selection, config) for selection in selections])
    write_csv(edit_decisions_csv, REEL_EDIT_DECISION_COLUMNS, [edit_decision_row(selection, config) for selection in selections])

    actual_duration = round(sum(selection.candidate.segment_duration_seconds for selection in selections), 3)
    write_csv(
        manifest_csv,
        REEL_MANIFEST_COLUMNS,
        [
            {
                "reel_id": config.reel_id,
                "trip_slug": config.trip_slug,
                "reel_style": config.style,
                "media_sets": ",".join(sorted(config.media_sets)),
                "target_duration_seconds": config.target_duration_seconds,
                "actual_duration_seconds": actual_duration,
                "aspect_ratio": aspect_ratio_for(config),
                "output_width": config.render.width,
                "output_height": config.render.height,
                "rendered_file_path": path_text(rendered_file, project_root) if rendered_file else "",
                "edit_decision_path": path_text(edit_decisions_csv, project_root),
                "selection_path": path_text(selection_csv, project_root),
                "report_path": path_text(report_md, project_root),
                "dry_run": "yes" if config.dry_run else "no",
                "created_at": "",
                "render_status": render_status,
                "render_reason": render_reason,
            }
        ],
    )
    write_markdown_report(config, candidates, selections, rendered_file, render_status, render_reason, report_md, project_root)
    return candidates_csv, selection_csv, edit_decisions_csv, manifest_csv, report_md


def write_markdown_report(
    config: ReelConfig,
    candidates: list[ReelCandidate],
    selections: list[ReelSelection],
    rendered_file: Path,
    render_status: str,
    render_reason: str,
    report_md: Path,
    project_root: Path,
) -> None:
    role_counts: dict[str, int] = {}
    bucket_durations: dict[str, float] = {}
    moment_counts: dict[str, int] = {}
    for selection in selections:
        role_counts[selection.candidate.candidate_role] = role_counts.get(selection.candidate.candidate_role, 0) + 1
        bucket_durations[selection.candidate.activity_bucket] = bucket_durations.get(selection.candidate.activity_bucket, 0.0) + selection.candidate.segment_duration_seconds
        key = f"{selection.candidate.moment_id} - {selection.candidate.moment_title}"
        moment_counts[key] = moment_counts.get(key, 0) + 1
    lines = [
        "# Reel Builder Report",
        "",
        f"- Reel ID: {config.reel_id}",
        f"- Style: {config.style}",
        f"- Activity profile: {config.activity_profile.name} ({config.activity_profile.optimization_goal})",
        f"- Run mode: {'dry run' if config.dry_run else 'execute'}",
        f"- Media sets: {', '.join(sorted(config.media_sets)) or 'all'}",
        f"- Target duration: {config.target_duration_seconds:.0f}s",
        f"- Actual planned duration: {sum(selection.candidate.segment_duration_seconds for selection in selections):.1f}s",
        f"- Candidates: {len(candidates)}",
        f"- Selected clips: {len(selections)}",
        f"- Render status: {render_status}",
        f"- Render reason: {render_reason}",
        f"- Output: {path_text(rendered_file, project_root) if rendered_file else ''}",
        "",
        "## Activity Shape",
        "",
    ]
    lines.extend(f"- {bucket}: {seconds:.1f}s" for bucket, seconds in sorted(bucket_durations.items()))
    lines.extend([
        "",
        "## Role Balance",
        "",
    ])
    lines.extend(f"- {role}: {count}" for role, count in sorted(role_counts.items()))
    lines.extend(["", "## Moment Coverage", "", "| Moment | Clips |", "| --- | ---: |"])
    for moment, count in sorted(moment_counts.items()):
        lines.append(f"| {moment} | {count} |")
    lines.extend(["", "## Selected Edit", ""])
    for selection in selections:
        candidate = selection.candidate
        lines.append(
            f"- {selection.sequence:02d}. {candidate.candidate_role}: {candidate.source_media_path} "
            f"{candidate.segment_start_seconds:.1f}-{candidate.segment_end_seconds:.1f}s "
            f"({candidate.final_reel_score})"
        )
    lines.extend(["", "## Top Excluded Candidates", ""])
    selected_keys = {
        (selection.candidate.source_media_path, selection.candidate.segment_start_seconds, selection.candidate.segment_end_seconds)
        for selection in selections
    }
    excluded = [
        candidate
        for candidate in sorted(candidates, key=lambda item: -item.final_reel_score)
        if (candidate.source_media_path, candidate.segment_start_seconds, candidate.segment_end_seconds) not in selected_keys
    ][:10]
    for candidate in excluded:
        lines.append(f"- {candidate.candidate_role}: {candidate.source_media_path} ({candidate.final_reel_score})")
    report_md.write_text("\n".join(lines), encoding="utf-8")


def render_reel(config: ReelConfig, project_root: Path, selections: list[ReelSelection], output_file: Path) -> tuple[str, str, int]:
    if config.dry_run:
        return "planned", "dry run: rendering skipped", 0
    if not config.render.enabled:
        return "skipped", "render.enabled is false", 0
    if not selections:
        return "failed", "no selected clips to render", 0
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return "failed", "ffmpeg is unavailable", 0
    if output_file.exists() and config.render.overwrite_policy == "fail":
        return "failed", f"output already exists: {output_file}", 0

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="memory_curator_reel_") as tmp:
        tmp_dir = Path(tmp)
        clip_paths: list[Path] = []
        for selection in selections:
            clip_file = tmp_dir / f"{selection.sequence:03d}.mp4"
            render_segment(ffmpeg, config, project_root, selection, clip_file)
            clip_paths.append(clip_file)
        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in clip_paths), encoding="utf-8")
        temp_output = tmp_dir / "rendered_reel.mp4"
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(temp_output)],
            check=True,
        )
        if config.render.music_enabled and config.render.music_path:
            music_output = tmp_dir / "rendered_reel_with_music.mp4"
            add_music_track(ffmpeg, config, project_root, temp_output, music_output)
            temp_output = music_output
        if output_file.exists():
            output_file.unlink()
        temp_output.replace(output_file)
    return "rendered", "rendered with ffmpeg", 1


def render_segment(ffmpeg: str, config: ReelConfig, project_root: Path, selection: ReelSelection, destination: Path) -> None:
    candidate = selection.candidate
    source = resolve_project_path(project_root, candidate.source_media_path)
    source_duration = max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds)
    output_duration = max(0.1, candidate.segment_duration_seconds)
    speed_factor = max(0.1, candidate.speed_factor)
    vf = video_filter_for(transform_for_candidate(candidate, config), config, output_duration, speed_factor)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{candidate.segment_start_seconds:.3f}",
        "-i",
        str(source),
        "-t",
        f"{source_duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-dn",
        "-ignore_unknown",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
    ]
    effective_audio_mode = effective_segment_audio_mode(config, candidate)
    if effective_audio_mode == "mute":
        render_silent_audio_segment(ffmpeg, config, source, candidate, destination, vf, source_duration, output_duration)
        return
    else:
        mute_windows = muted_audio_windows_for_selection(config, candidate, speed_factor)
        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-af",
                audio_filter_for(output_duration, speed_factor, config.render.source_audio_volume, mute_windows),
            ]
        )
    command.extend(["-t", f"{output_duration:.3f}", "-movflags", "+faststart", str(destination)])
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        if destination.exists():
            destination.unlink()
        render_silent_audio_segment(ffmpeg, config, source, candidate, destination, vf, source_duration, output_duration)


def render_silent_audio_segment(
    ffmpeg: str,
    config: ReelConfig,
    source: Path,
    candidate: ReelCandidate,
    destination: Path,
    video_filter: str,
    source_duration: float,
    output_duration: float,
) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{candidate.segment_start_seconds:.3f}",
        "-i",
        str(source),
        "-f",
        "lavfi",
        "-t",
        f"{output_duration:.3f}",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-dn",
        "-ignore_unknown",
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-t",
        f"{output_duration:.3f}",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def command_without_audio(command: list[str]) -> list[str]:
    stripped: list[str] = []
    skip_next = False
    skip_options = {"-c:a", "-b:a", "-af"}
    index = 0
    while index < len(command):
        item = command[index]
        if skip_next:
            skip_next = False
            index += 1
            continue
        if item in skip_options:
            skip_next = True
            index += 1
            continue
        if item == "-map" and index + 1 < len(command) and command[index + 1].startswith("0:a"):
            index += 2
            continue
        stripped.append(item)
        index += 1
    output = stripped[-1]
    return stripped[:-1] + ["-an", output]


def effective_segment_audio_mode(config: ReelConfig, candidate: ReelCandidate) -> str:
    if candidate.media_set in set(config.render.natural_audio_enabled_sets):
        return "keep_source"
    return config.render.audio_mode


def muted_audio_windows_for_selection(config: ReelConfig, candidate: ReelCandidate, speed_factor: float) -> list[tuple[float, float]]:
    source_windows = muted_source_windows_for_candidate(config, candidate)
    output_windows: list[tuple[float, float]] = []
    for start, end in source_windows:
        intersection_start = max(start, candidate.segment_start_seconds)
        intersection_end = min(end, candidate.segment_end_seconds)
        if intersection_end <= intersection_start:
            continue
        output_start = (intersection_start - candidate.segment_start_seconds) / max(speed_factor, 0.1)
        output_end = (intersection_end - candidate.segment_start_seconds) / max(speed_factor, 0.1)
        if output_end - output_start >= 0.05:
            output_windows.append((round(max(0.0, output_start), 3), round(max(0.0, output_end), 3)))
    return merge_mute_windows(output_windows)


def muted_source_windows_for_candidate(config: ReelConfig, candidate: ReelCandidate) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    windows.extend(transcript_muted_source_windows(config, candidate.source_media_path))
    boundary_seconds = max(0.0, config.render.mute_action_camera_boundary_seconds)
    if boundary_seconds > 0 and "action_camera_pov" in candidate.visual_tags.split(","):
        duration = source_duration_for_path(candidate.source_media_path)
        windows.append((0.0, boundary_seconds))
        if duration:
            windows.append((max(0.0, duration - boundary_seconds), duration))
        segment_edge = min(boundary_seconds, max(0.0, candidate.segment_duration_seconds / 3.0))
        if segment_edge > 0:
            windows.append((candidate.segment_start_seconds, candidate.segment_start_seconds + segment_edge))
            windows.append((candidate.segment_end_seconds - segment_edge, candidate.segment_end_seconds))
    return windows


def transcript_muted_source_windows(config: ReelConfig, source_media_path: str) -> list[tuple[float, float]]:
    phrases = tuple(phrase.strip().lower() for phrase in config.render.mute_phrases if phrase.strip())
    if not phrases or not config.input_transcript_segments.exists():
        return []
    cache_key = (config.input_transcript_segments.as_posix(), phrases, round(config.render.mute_phrase_padding_seconds, 3))
    if cache_key not in MUTED_TRANSCRIPT_WINDOWS_CACHE:
        MUTED_TRANSCRIPT_WINDOWS_CACHE[cache_key] = load_transcript_mute_windows(
            config.input_transcript_segments,
            phrases,
            max(0.0, config.render.mute_phrase_padding_seconds),
        )
    return MUTED_TRANSCRIPT_WINDOWS_CACHE[cache_key].get(normalize_source_path(source_media_path), [])


def load_transcript_mute_windows(path: Path, phrases: tuple[str, ...], padding_seconds: float) -> dict[str, list[tuple[float, float]]]:
    windows_by_path: dict[str, list[tuple[float, float]]] = {}
    try:
        with path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
    except OSError:
        return windows_by_path
    for row in rows:
        text = (row.get("text") or "").lower()
        if not text or not any(phrase in text for phrase in phrases):
            continue
        video_path = (row.get("video_path") or "").strip()
        if not video_path:
            continue
        start = max(0.0, safe_float(row.get("start_seconds"), 0.0) - padding_seconds)
        end = max(start, safe_float(row.get("end_seconds"), start) + padding_seconds)
        windows_by_path.setdefault(normalize_source_path(video_path), []).append((start, end))
    return {path_key: merge_mute_windows(windows) for path_key, windows in windows_by_path.items()}


def merge_mute_windows(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not windows:
        return []
    merged: list[tuple[float, float]] = []
    for start, end in sorted(windows):
        if end <= start:
            continue
        if not merged or start > merged[-1][1] + 0.05:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def source_duration_for_path(path: str) -> float | None:
    normalized = normalize_source_path(path)
    if normalized in SOURCE_DURATION_BY_PATH:
        return SOURCE_DURATION_BY_PATH[normalized]
    return SOURCE_DURATION_BY_NAME.get(Path(path).name.lower())


def add_music_track(ffmpeg: str, config: ReelConfig, project_root: Path, video_file: Path, destination: Path) -> None:
    music_path = resolve_project_path(project_root, config.render.music_path)
    if not music_path.exists():
        video_file.replace(destination)
        return
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-stream_loop",
        "-1",
        "-i",
        str(music_path),
        "-i",
        str(video_file),
        "-map",
        "1:v:0",
        "-map",
        "0:a:0",
        "-shortest",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-af",
        f"volume={config.render.music_volume:.3f}",
        str(destination),
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def video_filter_for(transform: str, config: ReelConfig, duration: float | None = None, speed_factor: float = 1.0) -> str:
    width = config.render.width
    height = config.render.height
    fps = config.render.fps
    speed = max(0.1, speed_factor)
    speed_filter = "" if abs(speed - 1.0) < 0.01 else f",setpts=PTS/{speed:.3f}"
    if transform == "fit_blur_background":
        return (
            "split[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},gblur=sigma=24[bg];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps}{speed_filter},format=yuv420p"
        )
    return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps}{speed_filter},format=yuv420p"


def audio_filter_for(duration: float, speed_factor: float = 1.0, volume: float = 1.0, mute_windows: list[tuple[float, float]] | None = None) -> str:
    filters = ["aresample=48000:async=1:first_pts=0", "aformat=sample_rates=48000:channel_layouts=stereo"]
    if abs(speed_factor - 1.0) >= 0.01:
        filters.extend(atempo_filters(speed_factor))
    if abs(volume - 1.0) >= 0.01:
        filters.append(f"volume={max(0.0, volume):.3f}")
    for start, end in mute_windows or []:
        if end <= start:
            continue
        filters.append(f"volume=enable='between(t,{start:.3f},{end:.3f})':volume=0")
    return ",".join(filters)


def atempo_filters(speed_factor: float) -> list[str]:
    value = max(0.5, min(speed_factor, 4.0))
    filters: list[str] = []
    while value > 2.0:
        filters.append("atempo=2.0")
        value /= 2.0
    filters.append(f"atempo={value:.3f}")
    return filters


def transition_type_for(selection: ReelSelection) -> str:
    if selection.sequence == 1:
        return "opening"
    if selection.candidate.candidate_role in {"action", "group_action"}:
        return "smooth_action_cut"
    return "soft_cut"


def transition_duration_for(selection: ReelSelection) -> float:
    if selection.sequence == 1:
        return 0.0
    if selection.candidate.candidate_role in {"action", "group_action"}:
        return 0.12
    return 0.18


def run_reel_builder(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
    reel_id: str | None = None,
    style: str | None = None,
    variant: str | None = None,
) -> ReelResult:
    reel_config = load_reel_config(config, project_root)
    if execute:
        reel_config = replace(reel_config, dry_run=False)
    if reel_id:
        reel_config = replace(reel_config, reel_id=reel_id)
    if style:
        reel_config = replace(reel_config, style=style)
    if variant:
        reel_config = apply_variant(reel_config, variant)
    if len(reel_config.media_sets) == 1:
        reel_config = activity_scoped_reel_config(reel_config, next(iter(reel_config.media_sets)))
    if not reel_config.enabled and not include_disabled:
        raise ValueError("Reel Builder is disabled in config. Enable modules.reel_builder.enabled or pass --include-disabled.")

    load_source_chronology_index(config, project_root, reel_config.media_sets)
    candidates = build_candidates(reel_config, project_root)
    selections = select_reel(reel_config, candidates)
    rendered_file = output_file_for(reel_config)
    render_status, render_reason, rendered_count = render_reel(reel_config, project_root, selections, rendered_file)
    candidates_csv, selection_csv, edit_decisions_csv, manifest_csv, report_md = write_reports(
        reel_config,
        project_root,
        candidates,
        selections,
        rendered_file,
        render_status,
        render_reason,
    )
    return ReelResult(
        candidate_count=len(candidates),
        selected_count=len(selections),
        actual_duration_seconds=round(sum(selection.candidate.segment_duration_seconds for selection in selections), 3),
        rendered_count=rendered_count,
        render_status=render_status,
        rendered_file_path=rendered_file,
        reel_candidates_csv=candidates_csv,
        reel_selection_csv=selection_csv,
        reel_edit_decisions_csv=edit_decisions_csv,
        reel_manifest_csv=manifest_csv,
        reel_report_md=report_md,
        dry_run=reel_config.dry_run,
    )


def run_selected_timeline_fun_reel(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
    reel_id: str | None = None,
) -> ReelResult:
    reel_config = load_reel_config(config, project_root)
    if execute:
        reel_config = replace(reel_config, dry_run=False)
    if not reel_config.enabled and not include_disabled:
        raise ValueError("Reel Builder is disabled in config. Enable modules.reel_builder.enabled or pass --include-disabled.")
    media_sets = sorted(reel_config.media_sets)
    if len(media_sets) != 1:
        raise ValueError("selected_timeline_fun requires exactly one --set/activity, for example: --set atv.")
    media_set = media_sets[0]
    load_source_chronology_index(config, project_root, {media_set})
    timeline_path = resolve_project_path(project_root, config_value(config, "reel_builder.input_selected_timeline", "MemoryCurator/08 Selected Timeline")) / media_set / "selected_timeline.csv"
    timeline_rows = read_csv_required(timeline_path, project_root, "selected-timeline")
    profile = load_activity_profile(config, media_set_activity_map(config).get(media_set).activity_profile if media_set_activity_map(config).get(media_set) else media_set)
    fun_config = replace(
        reel_config,
        reel_id=reel_id or f"{reel_config.trip_slug}_{media_set}_reel_rank_01_selected_timeline_fun",
        style="selected_timeline_fun",
        variant="selected_timeline_fun",
        media_sets={media_set},
        activity_profile=profile,
        output_dir=reel_config.output_dir / media_set / "rank_01_selected_timeline_fun",
        exports_dir=reel_config.exports_dir / media_set,
        target_duration_seconds=150.0,
        min_clips=14,
        max_clips=26,
        render=replace(reel_config.render, audio_mode="mute"),
    )
    candidates = selected_timeline_reel_candidates(fun_config, timeline_rows)
    selections = select_selected_timeline_fun_reel(fun_config, candidates)
    rendered_file = output_file_for(fun_config)
    render_status, render_reason, rendered_count = render_reel(fun_config, project_root, selections, rendered_file)
    candidates_csv, selection_csv, edit_decisions_csv, manifest_csv, report_md = write_reports(
        fun_config,
        project_root,
        candidates,
        selections,
        rendered_file,
        render_status,
        render_reason,
    )
    return ReelResult(
        candidate_count=len(candidates),
        selected_count=len(selections),
        actual_duration_seconds=round(sum(selection.candidate.segment_duration_seconds for selection in selections), 3),
        rendered_count=rendered_count,
        render_status=render_status,
        rendered_file_path=rendered_file,
        reel_candidates_csv=candidates_csv,
        reel_selection_csv=selection_csv,
        reel_edit_decisions_csv=edit_decisions_csv,
        reel_manifest_csv=manifest_csv,
        reel_report_md=report_md,
        dry_run=fun_config.dry_run,
    )


def selected_timeline_reel_candidates(config: ReelConfig, rows: list[dict[str, str]]) -> list[ReelCandidate]:
    candidates: list[ReelCandidate] = []
    for row in rows:
        source_start = safe_float(row.get("source_start_seconds"))
        source_end = safe_float(row.get("source_end_seconds"), source_start + safe_float(row.get("source_duration_seconds"), 8))
        source_duration = max(0.1, source_end - source_start)
        tags = row.get("visual_tags", "")
        speed = selected_timeline_reel_speed(row)
        output_duration = source_duration / max(speed, 0.1)
        highlight_score = safe_float(row.get("highlight_score"), 80)
        role = row.get("selection_role", "action") or "action"
        source_video_duration = source_duration_for_path(row.get("source_media_path", "")) or source_end
        candidates.append(
            ReelCandidate(
                reel_id=config.reel_id,
                reel_style=config.style,
                target_duration_seconds=config.target_duration_seconds,
                media_set=row.get("media_set", ""),
                activity=row.get("activity", ""),
                moment_id=row.get("moment_id", ""),
                moment_type="action",
                story_order=float(len(candidates)),
                moment_title=row.get("moment_title", ""),
                timeline_event_id=row.get("timeline_event_id", ""),
                timeline_label=row.get("timeline_label", ""),
                source_media_path=row.get("source_media_path", ""),
                source_file_type="video",
                source_video_duration_seconds=source_video_duration,
                segment_start_seconds=round(source_start, 3),
                segment_end_seconds=round(source_end, 3),
                segment_duration_seconds=round(output_duration, 3),
                clip_id=f"selected_timeline_{len(candidates) + 1:03d}",
                clip_overall_score=min(100.0, highlight_score / 2.5),
                quality_score=85.0,
                action_score=100.0 if any(tag in tags for tag in ("water_speed_run", "speed_action", "lit_tunnel")) else 88.0,
                story_score=85.0,
                people_score=50.0,
                audio_energy_score=85.0,
                diversity_score=80.0,
                adventure_score=100.0,
                cinematic_score=82.0,
                memory_score=70.0,
                emotion_score=82.0,
                activity_score=100.0,
                activity_bucket="middle",
                activity_reason="selected_timeline_fun",
                visual_tags=tags,
                activity_confidence=safe_float(row.get("activity_confidence"), 100),
                activity_mismatch="no",
                speed_factor=round(speed, 3),
                audio_decision="mute_source",
                audit_reason=row.get("selection_reason", ""),
                final_reel_score=min(100.0, highlight_score / 2.0),
                candidate_role=role,
            )
        )
    return candidates


def selected_timeline_reel_speed(row: dict[str, str]) -> float:
    tags = set((row.get("visual_tags") or "").split(","))
    sequence = int(safe_float(row.get("highlight_sequence"), 0))
    if "lit_tunnel" in tags:
        return 1.0
    if sequence >= 70 and "water_speed_run" in tags:
        return 1.0 if sequence % 2 == 0 else 1.5
    if sequence <= 2:
        return 1.0
    if tags.intersection({"water_speed_run", "speed_action", "rough_motion"}):
        return 3.0 if sequence % 3 != 0 else 1.0
    return 1.5 if "mud_water_run" in tags and sequence % 4 == 0 else 1.0


def compress_selected_timeline_candidates(config: ReelConfig, candidates: list[ReelCandidate], variant: str) -> list[ReelCandidate]:
    """Keep every selected-timeline row and compress playback to the target duration."""
    ordered = sorted(candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))
    if not ordered:
        return []
    source_durations = [max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds) for candidate in ordered]
    target = max(1.0, config.target_duration_seconds)
    anchor_indexes = selected_timeline_anchor_indexes(ordered, variant, target)
    story_variant = variant in {"story_continuity", "instagram_reel"}
    full_highlight_variant = variant == "full_highlight"
    if variant == "instagram_reel":
        max_speed = max(1.0, config.max_speed_factor)
        anchor_indexes = {0, len(ordered) - 1}
        compressed: list[ReelCandidate] = []
        for index, (candidate, source_duration) in enumerate(zip(ordered, source_durations, strict=False)):
            speed = instagram_candidate_speed(candidate, max_speed, anchor=index in anchor_indexes)
            compressed.append(
                replace(
                    candidate,
                    speed_factor=round(speed, 3),
                    segment_duration_seconds=round(source_duration / max(speed, 0.1), 3),
                )
            )
        return compressed
    if variant == "full_highlight":
        max_speed = max(1.0, config.max_speed_factor)
        anchor_indexes = {0, len(ordered) - 1}
        compressed: list[ReelCandidate] = []
        for index, (candidate, source_duration) in enumerate(zip(ordered, source_durations, strict=False)):
            speed = full_highlight_candidate_speed(candidate, max_speed, anchor=index in anchor_indexes)
            compressed.append(
                replace(
                    candidate,
                    speed_factor=round(speed, 3),
                    segment_duration_seconds=round(source_duration / max(speed, 0.1), 3),
                )
            )
        return compressed

    base_speeds: list[float] = []
    for index, candidate in enumerate(ordered):
        tags = set(candidate.visual_tags.split(","))
        if full_highlight_variant:
            if index in anchor_indexes:
                base = 1.0
            elif tags.intersection({"lit_tunnel", "group_reaction", "face_visible", "people_visible"}):
                base = 1.25
            elif tags.intersection({"water_speed_run", "mud_water_run", "speed_action", "rough_motion", "water_crossing"}):
                base = 2.5
            else:
                base = 2.0
        elif index in anchor_indexes:
            base = 1.0 if story_variant else 1.25
        elif tags.intersection({"lit_tunnel", "group_reaction", "face_visible", "people_visible"}):
            base = 1.75 if story_variant else 2.25
        elif tags.intersection({"water_speed_run", "mud_water_run", "speed_action", "rough_motion", "water_crossing"}):
            base = 4.0 if story_variant else 5.0
        else:
            base = 3.0 if story_variant else 4.0
        base_speeds.append(base)

    anchor_duration = sum(duration / base_speeds[index] for index, duration in enumerate(source_durations) if index in anchor_indexes)
    non_anchor_indexes = [index for index in range(len(ordered)) if index not in anchor_indexes]
    non_anchor_duration = sum(source_durations[index] / base_speeds[index] for index in non_anchor_indexes)
    remaining = max(target - anchor_duration, target * 0.35)
    multiplier = max(1.0, non_anchor_duration / remaining) if non_anchor_indexes else 1.0
    speeds = list(base_speeds)
    for index in non_anchor_indexes:
        speeds[index] *= multiplier

    total_output = sum(duration / speed for duration, speed in zip(source_durations, speeds, strict=False))
    if total_output > target:
        final_multiplier = total_output / target
        speeds = [speed * final_multiplier for speed in speeds]

    compressed: list[ReelCandidate] = []
    for candidate, source_duration, speed in zip(ordered, source_durations, speeds, strict=False):
        compressed.append(
            replace(
                candidate,
                speed_factor=round(speed, 3),
                segment_duration_seconds=round(source_duration / max(speed, 0.1), 3),
            )
        )
    return compressed


def dynamic_selected_timeline_reel_duration(
    base_duration_seconds: float,
    candidates: list[ReelCandidate],
    min_duration_seconds: float = 90.0,
    max_duration_seconds: float = 120.0,
    comfortable_average_speed: float = 3.8,
) -> float:
    """Choose a reel duration from selected timeline density without exceeding the max."""
    source_duration = sum(max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds) for candidate in candidates)
    base = max(min_duration_seconds, base_duration_seconds)
    if source_duration <= 0:
        return base
    needed = source_duration / max(comfortable_average_speed, 0.1)
    return round(min(max_duration_seconds, max(base, needed)), 3)


def selected_timeline_source_duration(candidates: list[ReelCandidate]) -> float:
    return sum(max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds) for candidate in candidates)


def instagram_reel_duration(config: Config, base_duration_seconds: float, candidates: list[ReelCandidate]) -> float:
    source_duration = selected_timeline_source_duration(candidates)
    duration_seconds = float(config_value(config, "reel_builder.instagram.duration_seconds", base_duration_seconds))
    if source_duration <= duration_seconds:
        return round(source_duration, 3)
    return round(duration_seconds, 3)


def instagram_max_playback_speed(config: Config) -> float:
    return max(1.0, float(config_value(config, "reel_builder.instagram.max_playback_speed", 2.35)))


def full_highlight_max_playback_speed(config: Config) -> float:
    return max(1.0, float(config_value(config, "reel_builder.full_highlight.max_playback_speed", 2.75)))


def instagram_candidate_speed(candidate: ReelCandidate, max_speed: float, anchor: bool = False) -> float:
    tags = set(candidate.visual_tags.split(","))
    if anchor or tags.intersection({"lit_tunnel", "group_reaction", "face_visible", "people_visible"}):
        return 1.0
    if tags.intersection({"water_speed_run", "splash", "rapids", "mud_water_run", "water_crossing"}):
        return min(max_speed, 1.75)
    if tags.intersection({"speed_action", "rough_motion", "mud_action", "jungle_trail", "water"}):
        return min(max_speed, 2.0)
    return max_speed


def full_highlight_candidate_speed(candidate: ReelCandidate, max_speed: float, anchor: bool = False) -> float:
    tags = set(candidate.visual_tags.split(","))
    if anchor or tags.intersection({"lit_tunnel", "group_reaction", "face_visible", "people_visible"}):
        return 1.0
    if tags.intersection({"water_speed_run", "splash", "rapids", "mud_water_run", "water_crossing"}):
        return min(max_speed, 2.0)
    if tags.intersection({"speed_action", "rough_motion", "mud_action", "jungle_trail", "water"}):
        return min(max_speed, 2.35)
    return max_speed


def instagram_estimated_output_seconds(candidate: ReelCandidate, max_speed: float, anchor: bool = False) -> float:
    source_duration = max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds)
    return source_duration / instagram_candidate_speed(candidate, max_speed, anchor=anchor)


def full_highlight_estimated_output_seconds(candidate: ReelCandidate, max_speed: float, anchor: bool = False) -> float:
    source_duration = max(0.1, candidate.segment_end_seconds - candidate.segment_start_seconds)
    return source_duration / full_highlight_candidate_speed(candidate, max_speed, anchor=anchor)


def full_highlight_duration(config: Config, base_duration_seconds: float, candidates: list[ReelCandidate]) -> float:
    source_duration = selected_timeline_source_duration(candidates)
    duration_seconds = float(config_value(config, "reel_builder.full_highlight.duration_seconds", 180))
    return round(min(duration_seconds, source_duration), 3)


def should_create_full_highlight(config: Config, candidates: list[ReelCandidate]) -> bool:
    source_duration = selected_timeline_source_duration(candidates)
    min_source_seconds = float(config_value(config, "reel_builder.full_highlight.skip_if_source_under_seconds", 130))
    min_clip_count = int(config_value(config, "reel_builder.full_highlight.skip_if_clip_count_under", 16))
    return source_duration >= min_source_seconds and len(candidates) >= min_clip_count


def select_budgeted_timeline_candidates(
    *,
    candidates: list[ReelCandidate],
    target_seconds: float,
    max_speed: float,
    budget_tolerance: float,
    max_clips: int,
    max_segments_per_source: int,
    estimated_output_seconds: Callable[[ReelCandidate, float, bool], float],
    required_tags: list[str],
    per_required_tag: int,
) -> list[ReelCandidate]:
    ordered = sorted(candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))
    if not ordered:
        return []
    budget_seconds = target_seconds * budget_tolerance
    selected: list[ReelCandidate] = []
    keys: set[tuple[str, float, float]] = set()
    source_counts: dict[str, int] = {}
    estimated_duration = 0.0

    def add(candidate: ReelCandidate, anchor: bool = False, force: bool = False) -> bool:
        nonlocal estimated_duration
        key = (candidate.source_media_path, candidate.segment_start_seconds, candidate.segment_end_seconds)
        if key in keys or len(selected) >= max_clips:
            return False
        if source_counts.get(candidate.source_media_path, 0) >= max_segments_per_source and not force:
            return False
        addition = estimated_output_seconds(candidate, max_speed, anchor)
        if selected and estimated_duration + addition > budget_seconds and not force:
            return False
        selected.append(candidate)
        keys.add(key)
        source_counts[candidate.source_media_path] = source_counts.get(candidate.source_media_path, 0) + 1
        estimated_duration += addition
        return True

    add(ordered[0], anchor=True, force=True)
    ending_anchor = selected_timeline_payoff_anchor(ordered)
    if ending_anchor:
        add(ending_anchor, anchor=True, force=True)
    for tag in required_tags:
        tagged = [candidate for candidate in ordered if tag in candidate.visual_tags.split(",")]
        for candidate in sorted(tagged, key=master_highlight_rank, reverse=True):
            if sum(1 for item in selected if tag in item.visual_tags.split(",")) >= per_required_tag:
                break
            add(candidate, anchor=tag in {"lit_tunnel", "group_reaction", "face_visible", "people_visible"})

    remaining_slots = max(0, min(max_clips, len(ordered)) - len(selected))
    for index in evenly_spaced_indexes(len(ordered), remaining_slots):
        add(ordered[index])

    for candidate in sorted(ordered, key=master_highlight_rank, reverse=True):
        if len(selected) >= max_clips:
            break
        add(candidate)
    return sorted(selected, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))


def selected_timeline_payoff_anchor(candidates: list[ReelCandidate]) -> ReelCandidate | None:
    if not candidates:
        return None
    payoff_tags = {
        "water_speed_run",
        "mud_water_run",
        "speed_action",
        "lit_tunnel",
        "splash",
        "rapids",
        "group_reaction",
        "face_visible",
        "people_visible",
        "scenic",
        "landscape",
    }
    tagged = [
        candidate
        for candidate in candidates
        if set(candidate.visual_tags.split(",")).intersection(payoff_tags)
        and not set(candidate.visual_tags.split(",")).intersection({"ground_only", "setup_surface", "weak_close_pov"})
    ]
    if not tagged:
        return candidates[-1]
    source_order = {candidate.source_media_path: source_chronology_key(candidate.source_media_path) for candidate in tagged}
    latest_source_key = max(source_order.values())
    recent = [candidate for candidate in tagged if source_order[candidate.source_media_path] == latest_source_key]
    preferred = payoff_zone_candidates(recent or tagged)
    return max(preferred or recent or tagged, key=payoff_anchor_rank)


def payoff_zone_candidates(candidates: list[ReelCandidate]) -> list[ReelCandidate]:
    preferred: list[ReelCandidate] = []
    for candidate in candidates:
        duration = candidate.source_video_duration_seconds or source_duration_for_path(candidate.source_media_path)
        if not duration:
            continue
        ratio = candidate.segment_start_seconds / max(duration, 0.1)
        if 0.45 <= ratio <= 0.86:
            preferred.append(candidate)
    return preferred


def payoff_anchor_rank(candidate: ReelCandidate) -> tuple[float, float, float]:
    tags = set(candidate.visual_tags.split(","))
    gray_floor = audit_metric(candidate.audit_reason, "gray_floor")
    vehicle = audit_metric(candidate.audit_reason, "vehicle")
    water = audit_metric(candidate.audit_reason, "water")
    mud = audit_metric(candidate.audit_reason, "mud")
    dry_penalty = max(0.0, gray_floor - 0.22) * 85.0 + max(0.0, vehicle - 0.45) * 20.0
    payoff_bonus = 0.0
    if "lit_tunnel" in tags:
        payoff_bonus += 20.0
    if "water_speed_run" in tags:
        payoff_bonus += 18.0
    if "mud_water_run" in tags or "water_crossing" in tags:
        payoff_bonus += 12.0
    if "speed_action" in tags:
        payoff_bonus += 8.0
    if tags.intersection({"group_reaction", "face_visible", "people_visible", "splash", "rapids"}):
        payoff_bonus += 14.0
    visual_bonus = min(12.0, (water + mud) * 18.0)
    duration = candidate.source_video_duration_seconds or source_duration_for_path(candidate.source_media_path)
    tail_penalty = 0.0
    if duration:
        ratio = candidate.segment_start_seconds / max(duration, 0.1)
        if ratio > 0.86:
            tail_penalty = (ratio - 0.86) * 260.0
    return (
        candidate.final_reel_score + payoff_bonus + visual_bonus - dry_penalty - tail_penalty,
        candidate.segment_start_seconds,
        candidate.segment_duration_seconds,
    )


def audit_metric(audit_reason: str, key: str) -> float:
    match = re.search(rf"\b{re.escape(key)}=([0-9]+(?:\.[0-9]+)?)", audit_reason)
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def select_instagram_timeline_candidates(config: Config, candidates: list[ReelCandidate]) -> list[ReelCandidate]:
    ordered = sorted(candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))
    if not ordered:
        return []
    source_duration = selected_timeline_source_duration(ordered)
    short_source_seconds = float(config_value(config, "reel_builder.instagram.short_source_seconds", 130))
    if source_duration <= short_source_seconds or len(ordered) <= int(config_value(config, "reel_builder.instagram.short_max_clips", 16)):
        return ordered

    max_clips = int(config_value(config, "reel_builder.instagram.max_clips", 30))
    min_clips = int(config_value(config, "reel_builder.instagram.min_clips", 18))
    target_seconds = float(config_value(config, "reel_builder.instagram.duration_seconds", 90))
    max_speed = instagram_max_playback_speed(config)
    budget_seconds = target_seconds * float(config_value(config, "reel_builder.instagram.budget_tolerance", 1.02))
    max_segments_per_source = int(config_value(config, "reel_builder.instagram.max_segments_per_source_video", 4))
    important_tags = [
        "lit_tunnel",
        "water_speed_run",
        "mud_water_run",
        "water_crossing",
        "speed_action",
        "rough_motion",
        "jungle_trail",
        "group_reaction",
        "face_visible",
        "people_visible",
        "river_people",
        "river_scene",
        "phone_perspective",
        "group_camera_perspective",
        "water",
        "scenic",
        "landscape",
    ]
    _ = min_clips
    return select_budgeted_timeline_candidates(
        candidates=ordered,
        target_seconds=target_seconds,
        max_speed=max_speed,
        budget_tolerance=float(config_value(config, "reel_builder.instagram.budget_tolerance", 1.02)),
        max_clips=max_clips,
        max_segments_per_source=max_segments_per_source,
        estimated_output_seconds=instagram_estimated_output_seconds,
        required_tags=important_tags,
        per_required_tag=2,
    )


def select_full_highlight_timeline_candidates(config: Config, candidates: list[ReelCandidate]) -> list[ReelCandidate]:
    ordered = sorted(candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))
    if not ordered:
        return []
    target_seconds = float(config_value(config, "reel_builder.full_highlight.duration_seconds", 180))
    max_speed = full_highlight_max_playback_speed(config)
    estimated_all = sum(
        full_highlight_estimated_output_seconds(candidate, max_speed, anchor=index in {0, len(ordered) - 1})
        for index, candidate in enumerate(ordered)
    )
    budget_tolerance = float(config_value(config, "reel_builder.full_highlight.budget_tolerance", 1.0))
    if estimated_all <= target_seconds * budget_tolerance:
        return ordered
    important_tags = [
        "lit_tunnel",
        "water_speed_run",
        "mud_water_run",
        "water_crossing",
        "speed_action",
        "rough_motion",
        "jungle_trail",
        "group_reaction",
        "face_visible",
        "people_visible",
        "river_people",
        "river_scene",
        "phone_perspective",
        "group_camera_perspective",
        "water",
        "scenic",
        "landscape",
    ]
    return select_budgeted_timeline_candidates(
        candidates=ordered,
        target_seconds=target_seconds,
        max_speed=max_speed,
        budget_tolerance=budget_tolerance,
        max_clips=int(config_value(config, "reel_builder.full_highlight.max_clips", 55)),
        max_segments_per_source=int(config_value(config, "reel_builder.full_highlight.max_segments_per_source_video", 8)),
        estimated_output_seconds=full_highlight_estimated_output_seconds,
        required_tags=important_tags,
        per_required_tag=3,
    )


def evenly_spaced_indexes(count: int, limit: int) -> list[int]:
    if count <= 0 or limit <= 0:
        return []
    if limit == 1:
        return [count // 2]
    return sorted({round(index * (count - 1) / (limit - 1)) for index in range(limit)})


def selected_timeline_anchor_indexes(candidates: list[ReelCandidate], variant: str, target_duration_seconds: float) -> set[int]:
    if not candidates:
        return set()
    anchors = {0, len(candidates) - 1}
    important_tags = {"lit_tunnel", "water_speed_run", "mud_water_run", "group_reaction", "face_visible", "people_visible"}
    max_anchors = 6 if variant == "story_continuity" else 4
    for index, candidate in enumerate(candidates):
        if len(anchors) >= max_anchors:
            break
        if set(candidate.visual_tags.split(",")).intersection(important_tags):
            anchors.add(index)
    if len(anchors) < max_anchors and len(candidates) > 2:
        for ratio in (0.25, 0.5, 0.75):
            anchors.add(round((len(candidates) - 1) * ratio))
            if len(anchors) >= max_anchors:
                break
    return anchors


def select_full_selected_timeline_reel(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelSelection]:
    ordered = sorted(candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))
    selections: list[ReelSelection] = []
    cursor = 0.0
    for index, candidate in enumerate(ordered, start=1):
        start = cursor
        end = start + candidate.segment_duration_seconds
        selections.append(ReelSelection(candidate, index, round(start, 3), round(end, 3), selection_reason(candidate)))
        cursor = end
    return selections


def select_selected_timeline_fun_reel(config: ReelConfig, candidates: list[ReelCandidate]) -> list[ReelSelection]:
    selected: list[ReelCandidate] = []
    duration = 0.0
    candidates = sorted(candidates, key=lambda item: (source_chronology_key(item.source_media_path), item.segment_start_seconds))

    def try_add(candidate: ReelCandidate) -> bool:
        nonlocal duration
        if len(selected) >= config.max_clips:
            return False
        if overlaps_selected_source_window(candidate, selected):
            return False
        if duration + candidate.segment_duration_seconds > config.target_duration_seconds + 8 and len(selected) >= config.min_clips:
            return False
        selected.append(candidate)
        duration += candidate.segment_duration_seconds
        return True

    def add_best_in_bands(tag: str, bands: int, per_band: int = 1) -> None:
        tagged = [candidate for candidate in candidates if tag in candidate.visual_tags.split(",")]
        if not tagged:
            return
        band_size = max(1, len(candidates) / float(bands))
        for band in range(bands):
            start_index = int(band * band_size)
            end_index = int((band + 1) * band_size) if band < bands - 1 else len(candidates)
            band_candidates = [candidate for index, candidate in enumerate(candidates) if start_index <= index < end_index and candidate in tagged]
            added = 0
            for candidate in sorted(band_candidates, key=master_highlight_rank, reverse=True):
                if try_add(candidate):
                    added += 1
                if added >= per_band:
                    break

    def add_evenly_spaced(limit: int) -> None:
        if not candidates or limit <= 0:
            return
        if limit == 1:
            indexes = [len(candidates) // 2]
        else:
            indexes = [round(index * (len(candidates) - 1) / (limit - 1)) for index in range(limit)]
        for index in indexes:
            if len(selected) >= config.max_clips or duration >= config.target_duration_seconds:
                break
            try_add(candidates[int(index)])

    def add_timeline_tail(limit: int) -> None:
        tail_count = max(limit * 3, limit)
        tail = candidates[-tail_count:]
        added = 0
        for candidate in tail[-limit:]:
            if try_add(candidate):
                added += 1
        if added >= limit:
            return
        for candidate in sorted(tail, key=master_highlight_rank, reverse=True):
            if try_add(candidate):
                added += 1
            if added >= limit:
                break

    # Build a reel from the whole ride: start with motion, preserve rare events,
    # keep the ending energy, then fill with evenly spaced action highlights.
    add_evenly_spaced(3)
    add_best_in_bands("lit_tunnel", bands=4, per_band=1)
    add_best_in_bands("water_speed_run", bands=5, per_band=1)
    add_best_in_bands("mud_water_run", bands=4, per_band=1)
    add_best_in_bands("water_crossing", bands=4, per_band=1)
    add_best_in_bands("speed_action", bands=5, per_band=1)
    add_timeline_tail(4)
    add_evenly_spaced(18)

    for candidate in sorted(candidates, key=master_highlight_rank, reverse=True):
        if duration >= config.target_duration_seconds or len(selected) >= config.max_clips:
            break
        try_add(candidate)

    ordered = order_selected(replace(config, chronological="strict"), selected)
    selections: list[ReelSelection] = []
    cursor = 0.0
    for index, candidate in enumerate(ordered, start=1):
        start = cursor
        end = start + candidate.segment_duration_seconds
        selections.append(ReelSelection(candidate, index, round(start, 3), round(end, 3), selection_reason(candidate)))
        cursor = end
    return selections


def run_ranked_reels_by_activity(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
) -> list[ReelResult]:
    base_config = load_reel_config(config, project_root)
    if execute:
        base_config = replace(base_config, dry_run=False)
    if not base_config.enabled and not include_disabled:
        raise ValueError("Reel Builder is disabled in config. Enable modules.reel_builder.enabled or pass --include-disabled.")

    activity_map = media_set_activity_map(config)
    configured_sets = configured_media_sets(config, include_disabled=include_disabled)
    selected_sets = sorted(base_config.media_sets) if base_config.media_sets else [item.name for item in configured_sets]
    load_source_chronology_index(config, project_root, set(selected_sets))

    def build_activity_reels(media_set: str) -> list[ReelResult]:
        activity = activity_map.get(media_set)
        profile_name = activity.activity_profile if activity else media_set
        profile = load_activity_profile(config, profile_name)
        activity_base_id = f"{base_config.trip_slug}_{media_set}_reel"
        activity_config = replace(
            activity_scoped_reel_config(base_config, media_set),
            reel_id=activity_base_id,
            media_sets={media_set},
            activity_profile=profile,
            output_dir=base_config.output_dir / media_set,
            exports_dir=base_config.exports_dir / media_set,
        )
        activity_results: list[ReelResult] = []
        timeline_path = (
            resolve_project_path(project_root, config_value(config, "reel_builder.input_selected_timeline", "MemoryCurator/08 Selected Timeline"))
            / media_set
            / "selected_timeline.csv"
        )

        def append_result(ranked_config: ReelConfig, candidates: list[ReelCandidate], selections: list[ReelSelection]) -> None:
            rendered_file = output_file_for(ranked_config)
            render_status, render_reason, rendered_count = render_reel(ranked_config, project_root, selections, rendered_file)
            candidates_csv, selection_csv, edit_decisions_csv, manifest_csv, report_md = write_reports(
                ranked_config,
                project_root,
                candidates,
                selections,
                rendered_file,
                render_status,
                render_reason,
            )
            activity_results.append(
                ReelResult(
                    candidate_count=len(candidates),
                    selected_count=len(selections),
                    actual_duration_seconds=round(sum(selection.candidate.segment_duration_seconds for selection in selections), 3),
                    rendered_count=rendered_count,
                    render_status=render_status,
                    rendered_file_path=rendered_file,
                    reel_candidates_csv=candidates_csv,
                    reel_selection_csv=selection_csv,
                    reel_edit_decisions_csv=edit_decisions_csv,
                    reel_manifest_csv=manifest_csv,
                    reel_report_md=report_md,
                    dry_run=ranked_config.dry_run,
                )
            )

        if timeline_path.exists():
            timeline_rows = read_csv_required(timeline_path, project_root, "selected-timeline")

            instagram_config = replace(
                activity_config,
                reel_id=f"{activity_base_id}_rank_01",
                style="instagram_reel",
                variant="instagram_reel",
                output_dir=activity_config.output_dir / "rank_01_instagram_reel",
                exports_dir=activity_config.exports_dir,
                target_duration_seconds=float(config_value(config, "reel_builder.instagram.duration_seconds", activity_config.target_duration_seconds)),
                max_clips=int(config_value(config, "reel_builder.instagram.max_clips", activity_config.max_clips)),
                max_speed_factor=instagram_max_playback_speed(config),
            )
            instagram_timeline_candidates = selected_timeline_reel_candidates(instagram_config, timeline_rows)
            instagram_source_candidates = select_instagram_timeline_candidates(config, instagram_timeline_candidates)
            instagram_config = replace(
                instagram_config,
                target_duration_seconds=instagram_reel_duration(config, instagram_config.target_duration_seconds, instagram_source_candidates),
            )
            instagram_candidates = compress_selected_timeline_candidates(instagram_config, instagram_source_candidates, "instagram_reel")
            append_result(instagram_config, instagram_candidates, select_full_selected_timeline_reel(instagram_config, instagram_candidates))

            if should_create_full_highlight(config, instagram_timeline_candidates):
                full_config = replace(
                    activity_config,
                    reel_id=f"{activity_base_id}_rank_02",
                    style="full_highlight",
                    variant="full_highlight",
                    output_dir=activity_config.output_dir / "rank_02_full_highlight",
                    exports_dir=activity_config.exports_dir,
                    target_duration_seconds=full_highlight_duration(config, activity_config.target_duration_seconds, instagram_timeline_candidates),
                    max_clips=max(activity_config.max_clips, len(instagram_timeline_candidates)),
                    max_speed_factor=full_highlight_max_playback_speed(config),
                )
                full_source_candidates = select_full_highlight_timeline_candidates(config, instagram_timeline_candidates)
                full_config = replace(
                    full_config,
                    target_duration_seconds=full_highlight_duration(config, activity_config.target_duration_seconds, full_source_candidates),
                    max_clips=max(activity_config.max_clips, len(full_source_candidates)),
                )
                full_candidates = compress_selected_timeline_candidates(full_config, full_source_candidates, "full_highlight")
                append_result(full_config, full_candidates, select_full_selected_timeline_reel(full_config, full_candidates))
        else:
            fallback_variants = REEL_VARIANTS[: max(1, min(base_config.reels_per_activity, len(REEL_VARIANTS)))]
            for rank, variant in enumerate(fallback_variants, start=1):
                ranked_config = apply_variant(activity_config, variant)
                ranked_config = replace(
                    ranked_config,
                    reel_id=f"{activity_base_id}_rank_{rank:02d}",
                    output_dir=activity_config.output_dir / f"rank_{rank:02d}_{variant}",
                    exports_dir=activity_config.exports_dir,
                )
                candidates = build_candidates(ranked_config, project_root)
                append_result(ranked_config, candidates, select_reel(ranked_config, candidates))
        return activity_results

    grouped_results = ordered_map(config, "reel_builder", build_activity_reels, selected_sets)
    return [result for activity_results in grouped_results for result in activity_results]


def apply_variant(config: ReelConfig, variant: str) -> ReelConfig:
    normalized = variant.strip().lower().replace("-", "_")
    if normalized not in REEL_VARIANTS:
        raise ValueError(f"Unknown reel variant: {variant}. Expected one of: {', '.join(REEL_VARIANTS)}")
    base_id = config.reel_id
    common_excludes = list(dict.fromkeys(config.exclude_source_patterns))
    common_order = reel_story_order_for_profile(config.activity_profile.name)
    action_types = reel_action_types_for_profile(config.activity_profile.name)
    people_types = [moment_type for moment_type in ["group_photo", "portrait", "cheers", "dancing"] if moment_type in common_order] or ["group_photo"]
    opening_types = [moment_type for moment_type in ["arrival", "transition", "travel_to_activity", "safety_briefing", "gear_up", "walk_to_start"] if moment_type in common_order]
    profile_min_segment = reel_min_segment_for_profile(config.activity_profile)
    adventure_profile = replace(config.activity_profile, middle_min_fraction=0.82, opening_duration_seconds=5, ending_duration_seconds=5)
    common = {
        "variant": normalized,
        "style": normalized,
        "reel_id": f"{base_id}_{normalized}",
        "output_dir": config.output_dir / normalized,
        "exclude_source_patterns": common_excludes,
        "group_perspective_patterns": list(dict.fromkeys([*config.group_perspective_patterns, "DANA"])),
        "group_perspective_min_segments": max(config.group_perspective_min_segments, 1),
        "max_segments_per_source_video": 2,
    }
    if normalized == "instagram_reel":
        return replace(
            config,
            **common,
            target_duration_seconds=90,
            max_clips=max(config.max_clips, 30),
            min_segment_seconds=min(config.min_segment_seconds, profile_min_segment),
            include_moment_types=set(common_order),
            required_moment_types=action_types,
            moment_story_order=common_order,
            promote_high_action_arrival=True,
        )
    if normalized == "full_highlight":
        return replace(
            config,
            **common,
            target_duration_seconds=180,
            max_clips=max(config.max_clips, 120),
            min_segment_seconds=min(config.min_segment_seconds, profile_min_segment),
            include_moment_types=set(common_order),
            required_moment_types=action_types,
            moment_story_order=common_order,
            promote_high_action_arrival=True,
        )
    if normalized == "story_continuity":
        return replace(
            config,
            **common,
            min_segment_seconds=min(config.min_segment_seconds, profile_min_segment),
            max_segments_per_moment=2,
            max_clips=max(config.max_clips, 18),
            include_moment_types=set(common_order),
            required_moment_types=action_types,
            moment_story_order=common_order,
            promote_high_action_arrival=True,
            activity_profile=replace(adventure_profile, middle_min_fraction=0.78, opening_duration_seconds=6, ending_duration_seconds=5),
        )
    if normalized == "action_audio":
        return replace(
            config,
            **common,
            max_segments_per_moment=4,
            max_clips=max(config.max_clips, 32),
            min_segment_seconds=min(config.min_segment_seconds, profile_min_segment, 3.0),
            max_segment_seconds=min(config.max_segment_seconds, 7.0),
            include_moment_types=set(opening_types + action_types + people_types),
            required_moment_types=action_types,
            moment_story_order=opening_types + action_types + people_types,
            promote_high_action_arrival=True,
            promoted_action_min_audio_score=50,
            speed_ramp_fraction=0.45,
            max_speed_factor=max(config.max_speed_factor, 3.0),
            activity_profile=replace(adventure_profile, middle_min_fraction=0.92, opening_duration_seconds=0, ending_duration_seconds=0),
        )
    if normalized == "water_focus":
        return replace(
            config,
            **common,
            max_segments_per_moment=3,
            max_clips=16,
            target_duration_seconds=50,
            min_segment_seconds=min(config.min_segment_seconds, profile_min_segment),
            include_moment_types=set(opening_types[-2:] + action_types + people_types),
            required_moment_types=action_types,
            moment_story_order=opening_types[-2:] + action_types + people_types,
            promote_high_action_arrival=True,
            promoted_action_min_audio_score=50,
            activity_profile=replace(adventure_profile, middle_min_fraction=0.90, opening_duration_seconds=2, ending_duration_seconds=3),
        )
    if normalized == "people_reactions":
        return replace(
            config,
            **common,
            max_segments_per_moment=2,
            max_clips=16,
            target_duration_seconds=50,
            min_segment_seconds=min(config.min_segment_seconds, profile_min_segment),
            include_moment_types=set(opening_types + action_types + people_types),
            required_moment_types=action_types[:2] + people_types[:1],
            moment_story_order=opening_types + action_types + people_types,
            promote_high_action_arrival=True,
            promoted_action_min_audio_score=50,
            activity_profile=replace(adventure_profile, middle_min_fraction=0.72, opening_duration_seconds=6, ending_duration_seconds=6),
        )
    return replace(
        config,
        **common,
        max_segments_per_moment=2,
        max_clips=18,
        target_duration_seconds=60,
        min_segment_seconds=min(config.min_segment_seconds, profile_min_segment),
        include_moment_types=set(common_order),
        required_moment_types=action_types,
        moment_story_order=common_order,
        promote_high_action_arrival=True,
        promoted_action_min_audio_score=85,
        activity_profile=replace(adventure_profile, middle_min_fraction=0.80, opening_duration_seconds=6, ending_duration_seconds=5),
    )


def reel_story_order_for_profile(profile_name: str) -> list[str]:
    orders = {
        "atv": ["arrival", "transition", "travel_to_activity", "safety_briefing", "gear_up", "launch", "trail", "mud_action", "speed_action", "jungle", "group_photo", "return_trip"],
        "beach": ["arrival", "transition", "travel_to_activity", "ocean_view", "beach_walk", "water_action", "sunset", "group_photo", "meal", "return_trip"],
        "waterfall": ["arrival", "transition", "travel_to_activity", "trail", "first_view", "waterfall", "water_action", "scenic", "group_photo", "return_trip"],
        "restaurants": ["arrival", "table_moment", "food", "cheers", "conversation", "group_photo", "return_trip"],
        "ricefield": ["arrival", "walk", "scenic", "portrait", "group_photo", "return_trip"],
        "savaya": ["arrival", "venue_view", "drinks", "music", "dancing", "sunset", "group_photo", "return_trip"],
        "clubbing": ["arrival", "venue_view", "drinks", "music", "dancing", "sunset", "group_photo", "return_trip"],
        "stay": ["arrival", "room", "villa", "pool", "relaxing", "group_photo", "transition"],
        "temple": ["arrival", "entrance", "temple_details", "cultural_moment", "portrait", "group_photo", "return_trip"],
    }
    return orders.get(profile_name, ["arrival", "transition", "travel_to_activity", "safety_briefing", "gear_up", "walk_to_start", "launch", "calm_river", "rapids", "water_action", "splash", "group_photo", "meal"])


def reel_action_types_for_profile(profile_name: str) -> list[str]:
    actions = {
        "atv": ["trail", "mud_action", "speed_action", "jungle"],
        "beach": ["ocean_view", "beach_walk", "water_action", "sunset"],
        "waterfall": ["trail", "first_view", "waterfall", "water_action", "scenic"],
        "restaurants": ["table_moment", "food", "cheers", "conversation"],
        "ricefield": ["walk", "scenic", "portrait"],
        "savaya": ["venue_view", "drinks", "music", "dancing", "sunset"],
        "clubbing": ["venue_view", "drinks", "music", "dancing", "sunset"],
        "stay": ["villa", "pool", "relaxing"],
        "temple": ["entrance", "temple_details", "cultural_moment", "portrait"],
    }
    return actions.get(profile_name, ["launch", "rapids", "water_action", "splash"])


def reel_min_segment_for_profile(profile: ActivityProfile) -> float:
    if profile.optimization_goal in {"memory", "social"}:
        return 2.0
    if profile.optimization_goal == "cinematic":
        return 3.0
    return 4.0
