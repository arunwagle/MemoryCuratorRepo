"""Documentary Builder story planning."""

from __future__ import annotations

import csv
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.media_sets import configured_media_sets
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import parse_enabled
from memory_curator_engine.video.report import ffmpeg_executable


DOCUMENTARY_CHAPTER_COLUMNS = [
    "chapter_id",
    "chapter_order",
    "chapter_title",
    "chapter_type",
    "purpose",
    "emotional_tone",
    "target_duration_seconds",
    "actual_duration_seconds",
    "moment_ids",
    "clip_ids",
    "photo_paths",
    "transition_notes",
    "narration_notes",
]

DOCUMENTARY_TIMELINE_COLUMNS = [
    "sequence",
    "chapter_id",
    "media_set",
    "activity",
    "source_media_path",
    "source_file_type",
    "source_start_seconds",
    "source_end_seconds",
    "output_start_seconds",
    "output_end_seconds",
    "duration_seconds",
    "moment_id",
    "timeline_event_id",
    "clip_id",
    "audio_event_id",
    "transcript_segment_id",
    "story_role",
    "selection_reason",
]

DOCUMENTARY_STORY_COLUMNS = [
    "story_beat_id",
    "chapter_id",
    "beat_order",
    "moment_id",
    "moment_title",
    "moment_type",
    "media_set",
    "activity",
    "story_role",
    "emotional_tone",
    "selection_reason",
]

DOCUMENTARY_MANIFEST_COLUMNS = [
    "trip_slug",
    "documentary_id",
    "target_duration_minutes",
    "actual_duration_seconds",
    "chapter_count",
    "timeline_event_count",
    "story_path",
    "chapters_path",
    "timeline_path",
    "treatment_path",
    "dry_run",
    "source_phase",
]


@dataclass(frozen=True)
class DocumentaryConfig:
    enabled: bool
    dry_run: bool
    trip_slug: str
    documentary_id: str
    input_moments: Path
    input_moment_assets: Path
    input_clip_scores: Path
    input_video_timeline: Path
    input_selected_timeline: Path
    input_album_manifest: Path
    input_audio_events: Path
    input_transcript_segments: Path
    output_dir: Path
    target_duration_minutes: float
    min_scene_seconds: float
    preferred_scene_seconds: float
    max_scene_seconds: float
    max_events_per_chapter: int
    prefer_same_moment_runs: bool
    min_run_events: int
    max_hard_cuts_per_chapter: int
    require_transition_between_chapters: bool
    min_events_per_activity: int
    story_mode: str
    activity_order: tuple[str, ...]
    prefer_selected_timeline: bool
    selected_timeline_min_fraction: float
    render_enabled: bool
    render_exports_dir: Path
    render_width: int
    render_height: int
    render_fps: int
    render_crf: int
    render_preset: str
    render_overwrite_policy: str


@dataclass(frozen=True)
class DocumentaryResult:
    chapter_count: int
    story_beat_count: int
    timeline_event_count: int
    actual_duration_seconds: float
    documentary_story_csv: Path
    documentary_chapters_csv: Path
    documentary_timeline_csv: Path
    documentary_manifest_csv: Path
    documentary_treatment_md: Path
    dry_run: bool
    render_status: str
    render_message: str
    rendered_file_path: Path | None
    rendered_segment_count: int


@dataclass(frozen=True)
class ChapterSpec:
    chapter_id: str
    title: str
    chapter_type: str
    purpose: str
    emotional_tone: str
    target_fraction: float
    moment_types: tuple[str, ...]
    preferred_roles: tuple[str, ...]


CHAPTER_SPECS = [
    ChapterSpec("intro", "Introduction", "introduction", "Set up the people, place, and promise of the trip.", "anticipation", 0.08, (), ("context", "establishing")),
    ChapterSpec("setup", "Arrival and Setup", "setup", "Show preparation, briefing, gear, and the threshold before the activity.", "curiosity", 0.10, (), ("setup", "context")),
    ChapterSpec("adventure", "Adventure Begins", "adventure", "Move from preparation into motion and commitment.", "momentum", 0.16, (), ("action", "transition")),
    ChapterSpec("peak", "Peak Moments", "peak_action", "Carry the strongest action, energy, and sensory experience.", "excitement", 0.24, (), ("action", "peak")),
    ChapterSpec("people", "People and Reactions", "emotion", "Let the audience connect with faces, laughter, food, and group reactions.", "joy", 0.14, (), ("reaction", "people")),
    ChapterSpec("breath", "Calm and Beauty", "breathing_space", "Give the story room to breathe with scenery, atmosphere, and cinematic texture.", "wonder", 0.12, (), ("beauty", "context")),
    ChapterSpec("celebration", "Celebration", "celebration", "Pay off the experience with group energy and accomplishment.", "celebration", 0.10, (), ("celebration", "reaction")),
    ChapterSpec("reflection", "Reflection", "reflection", "Close with memory, meaning, and a feeling of return.", "warmth", 0.06, (), ("reflection", "closing")),
]

CHAPTER_BY_ID = {spec.chapter_id: spec for spec in CHAPTER_SPECS}

MOMENT_CHAPTER_MAP = {
    "travel_to_activity": "intro",
    "arrival": "intro",
    "venue_view": "intro",
    "check_in": "setup",
    "setup": "setup",
    "safety_briefing": "setup",
    "gear_up": "setup",
    "walk_to_start": "setup",
    "trail": "setup",
    "entrance": "setup",
    "beach_walk": "setup",
    "table_moment": "setup",
    "launch": "adventure",
    "activity": "adventure",
    "jungle": "adventure",
    "pool": "adventure",
    "temple_details": "adventure",
    "food": "people",
    "drinks": "people",
    "rapids": "peak",
    "water_action": "peak",
    "splash": "peak",
    "mud_action": "peak",
    "speed_action": "peak",
    "waterfall": "peak",
    "dancing": "peak",
    "sunset": "breath",
    "scenic": "breath",
    "ocean_view": "breath",
    "villa": "breath",
    "room": "breath",
    "group_photo": "people",
    "meal": "people",
    "cheers": "people",
    "conversation": "people",
    "portrait": "people",
    "relaxing": "reflection",
    "return_trip": "celebration",
    "transition": "reflection",
    "other": "reflection",
}


def load_documentary_config(config: Config, project_root: Path) -> DocumentaryConfig:
    output_dir = resolve_project_path(project_root, config_value(config, "documentary_builder.output_dir", "MemoryCurator/10 Documentary Builder"))
    render_exports_dir = resolve_project_path(project_root, config_value(config, "documentary_builder.render.exports_dir", "input_data/trips/sample/curated/10 Documentary Builder/exports"))
    return DocumentaryConfig(
        enabled=parse_enabled(config_value(config, "modules.documentary_builder.enabled", False), "documentary_builder"),
        dry_run=parse_enabled(config_value(config, "documentary_builder.dry_run", True), "documentary_builder.dry_run"),
        trip_slug=str(config_value(config, "project.trip_slug", "trip")),
        documentary_id=str(config_value(config, "documentary_builder.documentary_id", f"{config_value(config, 'project.trip_slug', 'trip')}_documentary")),
        input_moments=resolve_project_path(project_root, config_value(config, "documentary_builder.input_moments", "MemoryCurator/05 Story Builder/moments.csv")),
        input_moment_assets=resolve_project_path(project_root, config_value(config, "documentary_builder.input_moment_assets", "MemoryCurator/05 Story Builder/moment_assets.csv")),
        input_clip_scores=resolve_project_path(project_root, config_value(config, "documentary_builder.input_clip_scores", "MemoryCurator/07 Video Processing/clip-scoring/clip_scores.csv")),
        input_video_timeline=resolve_project_path(project_root, config_value(config, "documentary_builder.input_video_timeline", "MemoryCurator/07 Video Processing/timeline-builder/video_timeline.csv")),
        input_selected_timeline=resolve_project_path(project_root, config_value(config, "documentary_builder.input_selected_timeline", "MemoryCurator/08 Selected Timeline")),
        input_album_manifest=resolve_project_path(project_root, config_value(config, "documentary_builder.input_album_manifest", "MemoryCurator/06 Album Builder/album_manifest.csv")),
        input_audio_events=resolve_project_path(project_root, config_value(config, "documentary_builder.input_audio_events", "MemoryCurator/07 Video Processing/audio-analysis/audio_events.csv")),
        input_transcript_segments=resolve_project_path(project_root, config_value(config, "documentary_builder.input_transcript_segments", "MemoryCurator/07 Video Processing/transcript/transcript_segments.csv")),
        output_dir=output_dir,
        target_duration_minutes=float(config_value(config, "documentary_builder.target_duration_minutes", 35)),
        min_scene_seconds=float(config_value(config, "documentary_builder.min_scene_seconds", 8)),
        preferred_scene_seconds=float(config_value(config, "documentary_builder.preferred_scene_seconds", 18)),
        max_scene_seconds=float(config_value(config, "documentary_builder.max_scene_seconds", 45)),
        max_events_per_chapter=int(config_value(config, "documentary_builder.max_events_per_chapter", 18)),
        prefer_same_moment_runs=parse_enabled(config_value(config, "documentary_builder.continuity.prefer_same_moment_runs", True), "documentary_builder.continuity.prefer_same_moment_runs"),
        min_run_events=int(config_value(config, "documentary_builder.continuity.min_run_events", 2)),
        max_hard_cuts_per_chapter=int(config_value(config, "documentary_builder.continuity.max_hard_cuts_per_chapter", 4)),
        require_transition_between_chapters=parse_enabled(config_value(config, "documentary_builder.continuity.require_transition_between_chapters", True), "documentary_builder.continuity.require_transition_between_chapters"),
        min_events_per_activity=int(config_value(config, "documentary_builder.coverage.min_events_per_activity", 0)),
        story_mode=str(config_value(config, "documentary_builder.story_mode", "chapter_arc")),
        activity_order=parse_text_list(config_value(config, "documentary_builder.activity_order", [])),
        prefer_selected_timeline=parse_enabled(config_value(config, "documentary_builder.prefer_selected_timeline", True), "documentary_builder.prefer_selected_timeline"),
        selected_timeline_min_fraction=float(config_value(config, "documentary_builder.selected_timeline_min_fraction", 0.50)),
        render_enabled=parse_enabled(config_value(config, "documentary_builder.render.enabled", False), "documentary_builder.render.enabled"),
        render_exports_dir=render_exports_dir,
        render_width=int(config_value(config, "documentary_builder.render.width", 1920)),
        render_height=int(config_value(config, "documentary_builder.render.height", 1080)),
        render_fps=int(config_value(config, "documentary_builder.render.fps", 30)),
        render_crf=int(config_value(config, "documentary_builder.render.crf", 21)),
        render_preset=str(config_value(config, "documentary_builder.render.preset", "veryfast")),
        render_overwrite_policy=str(config_value(config, "documentary_builder.render.overwrite_policy", "replace")),
    )


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


def read_selected_timeline_rows(path: Path, enabled_media_sets: set[str] | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    for csv_path in sorted(path.glob("*/selected_timeline.csv")):
        with csv_path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                media_set = row.get("media_set") or csv_path.parent.name
                if enabled_media_sets and media_set not in enabled_media_sets:
                    continue
                source_path = row.get("source_media_path", "")
                start = row.get("source_start_seconds", "0")
                end = row.get("source_end_seconds", "")
                duration = row.get("source_duration_seconds", "")
                rows.append(
                    {
                        "media_set": media_set,
                        "video_path": source_path,
                        "moment_id": row.get("moment_id", ""),
                        "timeline_event_id": row.get("timeline_event_id", ""),
                        "event_label": row.get("timeline_label", ""),
                        "clip_id": row.get("clip_id", ""),
                        "audio_event_id": "",
                        "transcript_segment_id": "",
                        "start_seconds": start,
                        "end_seconds": end,
                        "duration_seconds": duration,
                        "documentary_value_score": row.get("highlight_score", row.get("final_reel_score", "85")),
                        "story_importance_score": row.get("highlight_score", "85"),
                        "source_phase": "selected_timeline",
                    }
                )
    return rows


def safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value if value not in {None, ""} else default)
    except ValueError:
        return default


def parse_text_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def path_text(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def moment_type(row: dict[str, str]) -> str:
    return row.get("moment_type", row.get("type", "other")) or "other"


def chapter_for_moment(moment: dict[str, str]) -> ChapterSpec:
    kind = moment_type(moment)
    return CHAPTER_BY_ID.get(MOMENT_CHAPTER_MAP.get(kind, "reflection"), CHAPTER_SPECS[-1])


def parse_datetime_value(value: str | None) -> float:
    if not value:
        return float("inf")
    text = value.strip()
    if not text:
        return float("inf")
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate).timestamp()
        except ValueError:
            pass
    return float("inf")


def load_capture_index(project_root: Path) -> dict[str, float]:
    inventory_root = project_root / "MemoryCurator" / "01 Inventory"
    index: dict[str, float] = {}
    if not inventory_root.exists():
        return index
    for csv_path in sorted(inventory_root.glob("*_inventory.csv")):
        with csv_path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                relative_path = row.get("relative_path", "")
                if not relative_path:
                    continue
                timestamp = min(
                    parse_datetime_value(row.get("capture_date")),
                    parse_datetime_value(row.get("created_date")),
                    parse_datetime_value(row.get("modified_date")),
                )
                if timestamp != float("inf"):
                    index[relative_path] = timestamp
    return index


def source_chronology_key(row: dict[str, str], capture_index: dict[str, float]) -> tuple[float, str, float]:
    source = row.get("video_path") or row.get("source_media_path") or ""
    return (capture_index.get(source, float("inf")), source, safe_float(row.get("start_seconds") or row.get("source_start_seconds")))


def clip_score_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("clip_id", ""), row.get("video_path", ""))


def build_story_beats(moments: list[dict[str, str]]) -> list[dict[str, object]]:
    beats: list[dict[str, object]] = []
    chapter_counts: dict[str, int] = {}
    for moment in moments:
        spec = chapter_for_moment(moment)
        chapter_counts[spec.chapter_id] = chapter_counts.get(spec.chapter_id, 0) + 1
        beat_order = chapter_counts[spec.chapter_id]
        title = moment.get("title", moment.get("moment_id", "Moment"))
        kind = moment_type(moment)
        beats.append(
            {
                "story_beat_id": f"{spec.chapter_id}_{beat_order:03d}",
                "chapter_id": spec.chapter_id,
                "beat_order": beat_order,
                "moment_id": moment.get("moment_id", ""),
                "moment_title": title,
                "moment_type": kind,
                "media_set": moment.get("media_set", ""),
                "activity": moment.get("activity", ""),
                "story_role": role_for_moment(kind),
                "emotional_tone": tone_for_moment(kind, spec),
                "selection_reason": "moment placed into documentary chapter by Story Builder moment type",
            }
        )
    return beats


def role_for_moment(kind: str) -> str:
    if kind in {"rapids", "water_action", "splash", "launch"}:
        return "action"
    if kind in {"group_photo", "meal"}:
        return "people"
    if kind in {"arrival", "travel_to_activity", "transition"}:
        return "context"
    if kind in {"safety_briefing", "gear_up", "walk_to_start"}:
        return "setup"
    if kind in {"return_trip"}:
        return "reflection"
    return "supporting"


def tone_for_moment(kind: str, spec: ChapterSpec) -> str:
    if kind in {"rapids", "water_action", "splash"}:
        return "excitement"
    if kind in {"group_photo", "meal"}:
        return "joy"
    return spec.emotional_tone


def build_documentary_timeline(
    config: DocumentaryConfig,
    project_root: Path,
    moments: list[dict[str, str]],
    clip_scores: list[dict[str, str]],
    timeline_rows: list[dict[str, str]],
    selected_timeline_rows: list[dict[str, str]],
    audio_rows: list[dict[str, str]],
    transcript_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    if config.story_mode == "activity_chronological":
        return build_activity_chronological_timeline(
            config,
            project_root,
            moments,
            clip_scores,
            timeline_rows,
            selected_timeline_rows,
            audio_rows,
            transcript_rows,
        )

    moments_by_id = {row.get("moment_id", ""): row for row in moments}
    clips_by_key = {clip_score_key(row): row for row in clip_scores}
    audio_by_video = group_by(audio_rows, "video_path")
    transcript_by_video = group_by(transcript_rows, "video_path")
    forced_keys = required_activity_row_keys(config, timeline_rows, clips_by_key)
    target_seconds = config.target_duration_minutes * 60
    chapter_targets = adjusted_chapter_targets(config, moments_by_id, timeline_rows, target_seconds)
    rows: list[dict[str, object]] = []
    selected_keys: set[tuple[str, str, str]] = set()
    output_cursor = 0.0
    sequence = 1
    previous_moment_id = ""
    previous_chapter_id = ""
    for spec in CHAPTER_SPECS:
        chapter_target = chapter_targets.get(spec.chapter_id, target_seconds * spec.target_fraction)
        chapter_rows = [row for row in timeline_rows if chapter_for_moment(moments_by_id.get(row.get("moment_id", ""), {})).chapter_id == spec.chapter_id]
        ranked = prioritize_forced_rows(continuity_order(chapter_rows, clips_by_key, config), forced_keys)
        chapter_cursor = 0.0
        hard_cuts = 0
        for row in ranked[: config.max_events_per_chapter]:
            current_key = timeline_row_key(row)
            is_forced = current_key in forced_keys and current_key not in selected_keys
            if current_key in selected_keys:
                continue
            if chapter_cursor >= chapter_target and len([item for item in rows if item["chapter_id"] == spec.chapter_id]) >= 2 and not is_forced:
                break
            duration = documentary_duration(row, config)
            moment = moments_by_id.get(row.get("moment_id", ""), {})
            clip = clips_by_key.get((row.get("clip_id", ""), row.get("video_path", "")), {})
            source_start = safe_float(row.get("start_seconds"))
            source_end = source_start + duration
            current_moment_id = row.get("moment_id", "")
            transition_type = transition_type_for(previous_chapter_id, spec.chapter_id, previous_moment_id, current_moment_id)
            if transition_type == "hard_cut":
                hard_cuts += 1
                if hard_cuts > config.max_hard_cuts_per_chapter and chapter_cursor > 0:
                    continue
            audio_id = first_overlapping_id(audio_by_video.get(row.get("video_path", ""), []), source_start, source_end, "event_id") or row.get("audio_event_id", "")
            transcript_id = first_overlapping_id(transcript_by_video.get(row.get("video_path", ""), []), source_start, source_end, "segment_id") or row.get("transcript_segment_id", "")
            rows.append(
                {
                    "sequence": sequence,
                    "chapter_id": spec.chapter_id,
                    "media_set": row.get("media_set", moment.get("media_set", "")),
                    "activity": moment.get("activity", row.get("media_set", "")),
                    "source_media_path": row.get("video_path", ""),
                    "source_file_type": "video",
                    "source_start_seconds": round(source_start, 3),
                    "source_end_seconds": round(source_end, 3),
                    "output_start_seconds": round(output_cursor, 3),
                    "output_end_seconds": round(output_cursor + duration, 3),
                    "duration_seconds": round(duration, 3),
                    "moment_id": row.get("moment_id", ""),
                    "timeline_event_id": row.get("timeline_event_id", ""),
                    "clip_id": row.get("clip_id", ""),
                    "audio_event_id": audio_id,
                    "transcript_segment_id": transcript_id,
                    "story_role": story_role_for_timeline(row, clip, moment, transition_type),
                    "selection_reason": selection_reason(row, clip, spec),
                }
            )
            selected_keys.add(current_key)
            output_cursor += duration
            chapter_cursor += duration
            sequence += 1
            previous_moment_id = current_moment_id
            previous_chapter_id = spec.chapter_id
    return rows


def build_activity_chronological_timeline(
    config: DocumentaryConfig,
    project_root: Path,
    moments: list[dict[str, str]],
    clip_scores: list[dict[str, str]],
    timeline_rows: list[dict[str, str]],
    selected_timeline_rows: list[dict[str, str]],
    audio_rows: list[dict[str, str]],
    transcript_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    moments_by_id = {row.get("moment_id", ""): row for row in moments}
    clips_by_key = {clip_score_key(row): row for row in clip_scores}
    audio_by_video = group_by(audio_rows, "video_path")
    transcript_by_video = group_by(transcript_rows, "video_path")
    capture_index = load_capture_index(project_root)
    target_seconds = config.target_duration_minutes * 60
    selected_source = selected_timeline_rows if config.prefer_selected_timeline and selected_timeline_rows else []
    selected_by_activity = group_by(selected_source, "media_set")
    raw_by_activity = group_by(timeline_rows, "media_set")
    configured_order = {media_set: index for index, media_set in enumerate(config.activity_order)}
    activities = sorted(
        set(raw_by_activity) | set(selected_by_activity),
        key=lambda media_set: activity_chronology_key(media_set, selected_by_activity, raw_by_activity, capture_index, configured_order),
    )
    available_by_activity = {
        media_set: sum(documentary_duration(row, config) for row in selected_by_activity.get(media_set, []) + raw_by_activity.get(media_set, []))
        for media_set in activities
    }
    total_available = sum(available_by_activity.values()) or 1.0
    rows: list[dict[str, object]] = []
    selected_keys: set[tuple[str, str, str]] = set()
    output_cursor = 0.0
    sequence = 1
    previous_moment_id = ""
    previous_chapter_id = ""
    for activity_index, media_set in enumerate(activities, start=1):
        if not media_set:
            continue
        chapter_id = f"activity_{activity_index:02d}_{media_set}"
        activity_target = max(
            config.min_events_per_activity * config.min_scene_seconds,
            target_seconds * (available_by_activity.get(media_set, 0.0) / total_available),
        )
        chapter_rows = documentary_rows_for_activity(
            config,
            media_set,
            selected_by_activity.get(media_set, []),
            raw_by_activity.get(media_set, []),
            clips_by_key,
            capture_index,
            activity_target,
        )
        chapter_cursor = 0.0
        for row in chapter_rows:
            current_key = timeline_row_key(row)
            if current_key in selected_keys:
                continue
            duration = documentary_duration(row, config)
            if chapter_cursor >= activity_target and len([item for item in rows if item["chapter_id"] == chapter_id]) >= config.min_events_per_activity:
                break
            moment = moments_by_id.get(row.get("moment_id", ""), {})
            clip = clips_by_key.get((row.get("clip_id", ""), row.get("video_path", "")), {})
            source_start = safe_float(row.get("start_seconds"))
            source_end = source_start + duration
            current_moment_id = row.get("moment_id", "")
            transition_type = transition_type_for(previous_chapter_id, chapter_id, previous_moment_id, current_moment_id)
            audio_id = first_overlapping_id(audio_by_video.get(row.get("video_path", ""), []), source_start, source_end, "event_id") or row.get("audio_event_id", "")
            transcript_id = first_overlapping_id(transcript_by_video.get(row.get("video_path", ""), []), source_start, source_end, "segment_id") or row.get("transcript_segment_id", "")
            rows.append(
                {
                    "sequence": sequence,
                    "chapter_id": chapter_id,
                    "media_set": media_set,
                    "activity": moment.get("activity", media_set.replace("_", " ").title()),
                    "source_media_path": row.get("video_path", ""),
                    "source_file_type": "video",
                    "source_start_seconds": round(source_start, 3),
                    "source_end_seconds": round(source_end, 3),
                    "output_start_seconds": round(output_cursor, 3),
                    "output_end_seconds": round(output_cursor + duration, 3),
                    "duration_seconds": round(duration, 3),
                    "moment_id": row.get("moment_id", ""),
                    "timeline_event_id": row.get("timeline_event_id", ""),
                    "clip_id": row.get("clip_id", ""),
                    "audio_event_id": audio_id,
                    "transcript_segment_id": transcript_id,
                    "story_role": "selected_timeline" if row.get("source_phase") == "selected_timeline" else story_role_for_timeline(row, clip, moment, transition_type),
                    "selection_reason": activity_selection_reason(row, clip, media_set),
                }
            )
            selected_keys.add(current_key)
            output_cursor += duration
            chapter_cursor += duration
            sequence += 1
            previous_moment_id = current_moment_id
            previous_chapter_id = chapter_id
    return rows


def adjusted_chapter_targets(
    config: DocumentaryConfig,
    moments_by_id: dict[str, dict[str, str]],
    timeline_rows: list[dict[str, str]],
    target_seconds: float,
) -> dict[str, float]:
    base_targets = {spec.chapter_id: target_seconds * spec.target_fraction for spec in CHAPTER_SPECS}
    available = {spec.chapter_id: 0.0 for spec in CHAPTER_SPECS}
    for row in timeline_rows:
        chapter_id = chapter_for_moment(moments_by_id.get(row.get("moment_id", ""), {})).chapter_id
        available[chapter_id] = available.get(chapter_id, 0.0) + documentary_duration(row, config)

    targets = dict(base_targets)
    deficit = 0.0
    for chapter_id, base_target in base_targets.items():
        cap = available.get(chapter_id, 0.0)
        if cap < base_target:
            targets[chapter_id] = cap
            deficit += base_target - cap

    if deficit <= 0:
        return targets

    redistribution_weights = {
        "peak": 0.42,
        "adventure": 0.24,
        "breath": 0.16,
        "intro": 0.08,
        "people": 0.05,
        "setup": 0.03,
        "celebration": 0.01,
        "reflection": 0.01,
    }
    while deficit > 0.01:
        eligible = {
            chapter_id: weight
            for chapter_id, weight in redistribution_weights.items()
            if available.get(chapter_id, 0.0) - targets.get(chapter_id, 0.0) > 0.01
        }
        if not eligible:
            break
        weight_total = sum(eligible.values())
        used = 0.0
        for chapter_id, weight in eligible.items():
            capacity = available.get(chapter_id, 0.0) - targets.get(chapter_id, 0.0)
            add = min(capacity, deficit * (weight / weight_total))
            targets[chapter_id] += add
            used += add
        if used <= 0.01:
            break
        deficit -= used
    return targets


def activity_chronology_key(
    media_set: str,
    selected_by_activity: dict[str, list[dict[str, str]]],
    raw_by_activity: dict[str, list[dict[str, str]]],
    capture_index: dict[str, float],
    configured_order: dict[str, int],
) -> tuple[float, float, str]:
    if media_set in configured_order:
        return (float(configured_order[media_set]), 0.0, media_set)
    rows = selected_by_activity.get(media_set, []) or raw_by_activity.get(media_set, [])
    if not rows:
        return (float("inf"), float("inf"), media_set)
    timestamps = sorted(
        timestamp
        for timestamp, _, _ in (source_chronology_key(row, capture_index) for row in rows)
        if timestamp != float("inf")
    )
    if not timestamps:
        return (float("inf"), float("inf"), media_set)
    median_timestamp = timestamps[len(timestamps) // 2]
    first_timestamp = timestamps[0]
    return (median_timestamp, first_timestamp, media_set)


def documentary_rows_for_activity(
    config: DocumentaryConfig,
    media_set: str,
    selected_rows: list[dict[str, str]],
    raw_rows: list[dict[str, str]],
    clips_by_key: dict[tuple[str, str], dict[str, str]],
    capture_index: dict[str, float],
    activity_target: float,
) -> list[dict[str, str]]:
    selected_sorted = sorted(selected_rows, key=lambda row: source_chronology_key(row, capture_index))
    selected_duration = sum(documentary_duration(row, config) for row in selected_sorted)
    selected_min = activity_target * config.selected_timeline_min_fraction
    selected_keys = {timeline_row_key(row) for row in selected_sorted}
    raw_candidates = [
        row
        for row in raw_rows
        if timeline_row_key(row) not in selected_keys and not overlaps_selected_timeline(row, selected_sorted)
    ]
    if media_set == "atv":
        raw_candidates = prioritize_atv_documentary_rows(raw_candidates, clips_by_key)
    else:
        raw_candidates = sorted(
            raw_candidates,
            key=lambda row: (
                source_chronology_key(row, capture_index)[0],
                -documentary_rank(row, clips_by_key),
                safe_float(row.get("start_seconds")),
            ),
        )
    output = list(selected_sorted)
    duration = selected_duration
    for row in raw_candidates:
        if duration >= activity_target and duration >= selected_min:
            break
        if len(output) >= config.max_events_per_chapter:
            break
        output.append(row)
        duration += documentary_duration(row, config)
    return sorted(output, key=lambda row: source_chronology_key(row, capture_index))


def overlaps_selected_timeline(row: dict[str, str], selected_rows: list[dict[str, str]]) -> bool:
    source = row.get("video_path", "")
    start = safe_float(row.get("start_seconds"))
    end = safe_float(row.get("end_seconds"), start + safe_float(row.get("duration_seconds")))
    if end <= start:
        end = start + safe_float(row.get("duration_seconds"))
    for selected in selected_rows:
        if selected.get("video_path", "") != source:
            continue
        selected_start = safe_float(selected.get("start_seconds"))
        selected_end = safe_float(selected.get("end_seconds"), selected_start + safe_float(selected.get("duration_seconds")))
        if selected_end <= selected_start:
            selected_end = selected_start + safe_float(selected.get("duration_seconds"))
        overlap = min(end, selected_end) - max(start, selected_start)
        if overlap > 0.5:
            return True
    return False


def prioritize_atv_documentary_rows(rows: list[dict[str, str]], clips_by_key: dict[tuple[str, str], dict[str, str]]) -> list[dict[str, str]]:
    def atv_key(row: dict[str, str]) -> tuple[int, float, float]:
        text = " ".join([row.get("event_label", ""), row.get("notes", ""), row.get("video_path", "")]).lower()
        clip = clips_by_key.get((row.get("clip_id", ""), row.get("video_path", "")), {})
        clip_text = " ".join(str(value) for value in clip.values()).lower()
        combined = f"{text} {clip_text}"
        event_bonus = 0
        if any(token in combined for token in ["water_speed_run", "water crossing", "water", "splash"]):
            event_bonus += 5
        if any(token in combined for token in ["lit_tunnel", "tunnel"]):
            event_bonus += 5
        if any(token in combined for token in ["mud", "slope", "speed", "rough", "jungle"]):
            event_bonus += 3
        return (-event_bonus, -documentary_rank(row, clips_by_key), safe_float(row.get("start_seconds")))

    return sorted(rows, key=atv_key)


def activity_selection_reason(row: dict[str, str], clip: dict[str, str], media_set: str) -> str:
    source_phase = row.get("source_phase", "video_processing")
    scores = [
        f"activity_chronological={media_set}",
        f"source={source_phase}",
        f"timeline documentary={safe_float(row.get('documentary_value_score'), 50):.1f}",
    ]
    if clip:
        scores.append(f"clip documentary={safe_float(clip.get('documentary_score'), 50):.1f}")
        scores.append(f"story={safe_float(clip.get('story_score'), 50):.1f}")
    return "; ".join(scores)


def timeline_row_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row.get("video_path", ""), row.get("start_seconds", ""), row.get("end_seconds", ""))


def required_activity_row_keys(
    config: DocumentaryConfig,
    timeline_rows: list[dict[str, str]],
    clips_by_key: dict[tuple[str, str], dict[str, str]],
) -> set[tuple[str, str, str]]:
    if config.min_events_per_activity <= 0:
        return set()
    grouped = group_by(timeline_rows, "media_set")
    required: set[tuple[str, str, str]] = set()
    for media_set, rows in grouped.items():
        if not media_set:
            continue
        ranked = sorted(rows, key=lambda row: documentary_rank(row, clips_by_key), reverse=True)
        for row in ranked[: config.min_events_per_activity]:
            required.add(timeline_row_key(row))
    return required


def prioritize_forced_rows(rows: list[dict[str, str]], forced_keys: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    forced = [row for row in rows if timeline_row_key(row) in forced_keys]
    regular = [row for row in rows if timeline_row_key(row) not in forced_keys]
    return forced + regular


def documentary_duration(row: dict[str, str], config: DocumentaryConfig) -> float:
    raw_duration = safe_float(row.get("duration_seconds"), config.preferred_scene_seconds)
    if raw_duration <= 0:
        return min(config.preferred_scene_seconds, config.max_scene_seconds)
    return min(raw_duration, config.max_scene_seconds)


def continuity_order(rows: list[dict[str, str]], clips_by_key: dict[tuple[str, str], dict[str, str]], config: DocumentaryConfig) -> list[dict[str, str]]:
    ranked = sorted(rows, key=lambda row: documentary_rank(row, clips_by_key), reverse=True)
    if not config.prefer_same_moment_runs:
        return ranked
    grouped = group_by(ranked, "moment_id")
    moment_order = sorted(grouped, key=lambda moment_id: max(documentary_rank(row, clips_by_key) for row in grouped[moment_id]), reverse=True)
    ordered: list[dict[str, str]] = []
    for moment_id in moment_order:
        moment_rows = sorted(grouped[moment_id], key=lambda row: (safe_float(row.get("start_seconds")), -documentary_rank(row, clips_by_key)))
        if len(moment_rows) < config.min_run_events:
            ordered.extend(moment_rows)
            continue
        ordered.extend(moment_rows)
    return ordered


def transition_type_for(previous_chapter_id: str, chapter_id: str, previous_moment_id: str, current_moment_id: str) -> str:
    if not previous_chapter_id:
        return "opening"
    if previous_chapter_id != chapter_id:
        return "chapter_bridge"
    if previous_moment_id and previous_moment_id == current_moment_id:
        return "continuous_sequence"
    return "hard_cut"


def documentary_rank(row: dict[str, str], clips_by_key: dict[tuple[str, str], dict[str, str]]) -> float:
    clip = clips_by_key.get((row.get("clip_id", ""), row.get("video_path", "")), {})
    return max(
        safe_float(row.get("documentary_value_score"), 50),
        safe_float(clip.get("documentary_score"), 50),
        safe_float(clip.get("story_score"), 50),
    ) + safe_float(clip.get("audio_score"), 50) * 0.12


def group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key, ""), []).append(row)
    return grouped


def first_overlapping_id(rows: list[dict[str, str]], start: float, end: float, id_key: str) -> str:
    for row in rows:
        row_start = safe_float(row.get("start_seconds"))
        row_end = safe_float(row.get("end_seconds"))
        if row_start < end and row_end > start:
            return row.get(id_key, "")
    return ""


def story_role_for_timeline(row: dict[str, str], clip: dict[str, str], moment: dict[str, str], transition_type: str) -> str:
    bucket = clip.get("activity_bucket", "")
    if transition_type in {"opening", "chapter_bridge", "continuous_sequence"}:
        return transition_type
    kind = moment_type(moment)
    if bucket in {"opening", "middle", "ending"}:
        return bucket
    return role_for_moment(kind)


def selection_reason(row: dict[str, str], clip: dict[str, str], spec: ChapterSpec) -> str:
    scores = [
        f"chapter={spec.title}",
        f"timeline documentary={safe_float(row.get('documentary_value_score'), 50):.1f}",
    ]
    if clip:
        scores.append(f"clip documentary={safe_float(clip.get('documentary_score'), 50):.1f}")
        scores.append(f"story={safe_float(clip.get('story_score'), 50):.1f}")
    scores.append("continuity-aware chapter placement")
    return "; ".join(scores)


def build_chapters(config: DocumentaryConfig, story_beats: list[dict[str, object]], timeline_rows: list[dict[str, object]], album_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    if config.story_mode == "activity_chronological":
        return build_activity_chapters(config, timeline_rows, album_rows)
    album_by_moment = group_by(album_rows, "moment_id")
    chapters = []
    for order, spec in enumerate(CHAPTER_SPECS, start=1):
        chapter_timeline = [row for row in timeline_rows if row["chapter_id"] == spec.chapter_id]
        chapter_beats = [row for row in story_beats if row["chapter_id"] == spec.chapter_id]
        moment_ids = unique_text(str(row["moment_id"]) for row in chapter_beats)
        photo_paths = unique_text(
            row.get("media_path", "")
            for moment_id in moment_ids
            for row in album_by_moment.get(moment_id, [])[:2]
        )
        chapters.append(
            {
                "chapter_id": spec.chapter_id,
                "chapter_order": order,
                "chapter_title": spec.title,
                "chapter_type": spec.chapter_type,
                "purpose": spec.purpose,
                "emotional_tone": spec.emotional_tone,
                "target_duration_seconds": round(config.target_duration_minutes * 60 * spec.target_fraction, 3),
                "actual_duration_seconds": round(sum(safe_float(str(row["duration_seconds"])) for row in chapter_timeline), 3),
                "moment_ids": ",".join(moment_ids),
                "clip_ids": ",".join(unique_text(str(row["clip_id"]) for row in chapter_timeline)),
                "photo_paths": ",".join(photo_paths),
                "transition_notes": transition_notes_for(spec),
                "narration_notes": narration_notes_for(spec),
            }
        )
    return chapters


def build_activity_chapters(config: DocumentaryConfig, timeline_rows: list[dict[str, object]], album_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    album_by_moment = group_by(album_rows, "moment_id")
    chapters = []
    chapter_ids = unique_text(str(row["chapter_id"]) for row in timeline_rows)
    for order, chapter_id in enumerate(chapter_ids, start=1):
        chapter_timeline = [row for row in timeline_rows if row["chapter_id"] == chapter_id]
        if not chapter_timeline:
            continue
        media_set = str(chapter_timeline[0].get("media_set", "activity"))
        activity_title = str(chapter_timeline[0].get("activity") or media_set.replace("_", " ").title())
        moment_ids = unique_text(str(row["moment_id"]) for row in chapter_timeline)
        photo_paths = unique_text(
            row.get("media_path", "")
            for moment_id in moment_ids
            for row in album_by_moment.get(moment_id, [])[:2]
        )
        chapters.append(
            {
                "chapter_id": chapter_id,
                "chapter_order": order,
                "chapter_title": activity_title,
                "chapter_type": "activity_chronological",
                "purpose": f"Tell the {activity_title} part of the trip in real capture order.",
                "emotional_tone": "memory",
                "target_duration_seconds": "",
                "actual_duration_seconds": round(sum(safe_float(str(row["duration_seconds"])) for row in chapter_timeline), 3),
                "moment_ids": ",".join(moment_ids),
                "clip_ids": ",".join(unique_text(str(row["clip_id"]) for row in chapter_timeline)),
                "photo_paths": ",".join(photo_paths),
                "transition_notes": "Keep source chronology inside the activity; bridge naturally into the next captured activity.",
                "narration_notes": f"Narration should introduce {activity_title}, then let the selected moments and natural audio carry the memory.",
            }
        )
    return chapters


def unique_text(values: object) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def transition_notes_for(spec: ChapterSpec) -> str:
    if spec.chapter_id == "intro":
        return "Open like a documentary: establish place, people, and promise before heavy action."
    if spec.chapter_id == "peak":
        return "Use faster pacing but keep action runs continuous; preserve natural sound."
    if spec.chapter_id == "reflection":
        return "Slow down, let the audience feel the memory settling."
    return "Use bridge shots or same-moment runs so the sequence does not feel choppy."


def narration_notes_for(spec: ChapterSpec) -> str:
    return f"Narration should support the chapter purpose: {spec.purpose}"


def write_treatment(config: DocumentaryConfig, project_root: Path, chapters: list[dict[str, object]], timeline: list[dict[str, object]]) -> Path:
    path = config.output_dir / "documentary_treatment.md"
    lines = [
        "# Documentary Treatment",
        "",
        f"Documentary ID: {config.documentary_id}",
        f"Target length: {config.target_duration_minutes:.0f} minutes",
        f"Planned timeline: {sum(safe_float(str(row['duration_seconds'])) for row in timeline) / 60:.1f} minutes",
        "",
        "## Logline",
        "",
        "A memory-first travel documentary that moves from anticipation into adventure, action, people, celebration, and reflection.",
        "",
        "## Narrative Arc",
        "",
        "Introduction -> Adventure -> Peak Experience -> People and Emotion -> Celebration -> Reflection",
        "",
    ]
    for chapter in chapters:
        lines.extend(
            [
                f"## {chapter['chapter_order']}. {chapter['chapter_title']}",
                "",
                f"- Purpose: {chapter['purpose']}",
                f"- Tone: {chapter['emotional_tone']}",
                f"- Planned duration: {safe_float(str(chapter['actual_duration_seconds'])):.1f}s",
                f"- Moments: {chapter['moment_ids'] or 'none'}",
                f"- Notes: {chapter['narration_notes']}",
                "",
            ]
        )
        chapter_events = [row for row in timeline if row["chapter_id"] == chapter["chapter_id"]][:6]
        for event in chapter_events:
            lines.append(f"- {event['sequence']:03d}: {event['source_media_path']} ({event['story_role']}, {event['duration_seconds']}s)")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_manifest(config: DocumentaryConfig, project_root: Path, chapters: list[dict[str, object]], timeline: list[dict[str, object]], story_path: Path, chapters_path: Path, timeline_path: Path, treatment_path: Path) -> Path:
    manifest_path = config.output_dir / "documentary_manifest.csv"
    write_csv(
        manifest_path,
        DOCUMENTARY_MANIFEST_COLUMNS,
        [
            {
                "trip_slug": config.trip_slug,
                "documentary_id": config.documentary_id,
                "target_duration_minutes": config.target_duration_minutes,
                "actual_duration_seconds": round(sum(safe_float(str(row["duration_seconds"])) for row in timeline), 3),
                "chapter_count": len(chapters),
                "timeline_event_count": len(timeline),
                "story_path": path_text(story_path, project_root),
                "chapters_path": path_text(chapters_path, project_root),
                "timeline_path": path_text(timeline_path, project_root),
                "treatment_path": path_text(treatment_path, project_root),
                "dry_run": "yes" if config.dry_run else "no",
                "source_phase": "documentary_builder",
            }
        ],
    )
    return manifest_path


def render_documentary(config: DocumentaryConfig, project_root: Path, timeline: list[dict[str, object]]) -> tuple[str, str, Path | None, int]:
    if config.dry_run:
        return "planned", "dry run: rendering skipped", None, 0
    if not config.render_enabled:
        return "skipped", "documentary_builder.render.enabled is false", None, 0
    if not timeline:
        return "failed", "no documentary timeline events to render", None, 0
    ffmpeg = ffmpeg_executable()
    if ffmpeg is None:
        return "failed", "ffmpeg is unavailable", None, 0

    output_file = config.render_exports_dir / f"{config.documentary_id}.mp4"
    if output_file.exists() and config.render_overwrite_policy == "fail":
        return "failed", f"output already exists: {output_file}", output_file, 0

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="memory_curator_documentary_") as tmp:
        tmp_dir = Path(tmp)
        segment_paths: list[Path] = []
        for index, row in enumerate(timeline, start=1):
            segment_file = tmp_dir / f"{index:04d}.mp4"
            render_documentary_segment(ffmpeg, config, project_root, row, segment_file)
            segment_paths.append(segment_file)

        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8")
        temp_output = tmp_dir / "documentary.mp4"
        subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(temp_output)],
            check=True,
        )
        if output_file.exists():
            output_file.unlink()
        temp_output.replace(output_file)
    return "rendered", "rendered with ffmpeg", output_file, len(segment_paths)


def render_documentary_segment(ffmpeg: str, config: DocumentaryConfig, project_root: Path, row: dict[str, object], destination: Path) -> None:
    source = resolve_project_path(project_root, str(row.get("source_media_path", "")))
    start = safe_float(str(row.get("source_start_seconds", 0)))
    duration = max(0.1, safe_float(str(row.get("duration_seconds", 0)), config.preferred_scene_seconds))
    vf = documentary_video_filter(config)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
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
        config.render_preset,
        "-crf",
        str(config.render_crf),
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-af",
        "aresample=async=1:first_pts=0",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        if destination.exists():
            destination.unlink()
        subprocess.run(documentary_command_without_audio(command), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def documentary_video_filter(config: DocumentaryConfig) -> str:
    width = config.render_width
    height = config.render_height
    fps = config.render_fps
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"setsar=1,fps={fps},format=yuv420p"
    )


def documentary_command_without_audio(command: list[str]) -> list[str]:
    stripped: list[str] = []
    index = 0
    skip_next_for = {"-c:a", "-b:a", "-af"}
    while index < len(command):
        item = command[index]
        if item in skip_next_for:
            index += 2
            continue
        if item == "-map" and index + 1 < len(command) and command[index + 1].startswith("0:a"):
            index += 2
            continue
        stripped.append(item)
        index += 1
    output = stripped[-1]
    return stripped[:-1] + ["-an", output]


def run_documentary_builder(config: Config, project_root: Path, include_disabled: bool = False, execute: bool = False) -> DocumentaryResult:
    documentary_config = load_documentary_config(config, project_root)
    if execute:
        documentary_config = replace(documentary_config, dry_run=False)
    if not documentary_config.enabled and not include_disabled:
        raise ValueError("Documentary Builder is disabled in config. Enable modules.documentary_builder.enabled or pass --include-disabled.")

    enabled_media_sets = {item.name for item in configured_media_sets(config, include_disabled=include_disabled)}
    moments = read_csv_required(documentary_config.input_moments, project_root, "story-builder")
    read_csv_required(documentary_config.input_moment_assets, project_root, "story-builder")
    clip_scores = read_csv_required(documentary_config.input_clip_scores, project_root, "video-processing")
    timeline_source = read_csv_required(documentary_config.input_video_timeline, project_root, "video-processing")
    if enabled_media_sets:
        moments = [row for row in moments if row.get("media_set", "") in enabled_media_sets]
        clip_scores = [row for row in clip_scores if row.get("media_set", "") in enabled_media_sets]
        timeline_source = [row for row in timeline_source if row.get("media_set", "") in enabled_media_sets]
    selected_timeline_source = read_selected_timeline_rows(documentary_config.input_selected_timeline, enabled_media_sets)
    album_rows = read_csv_optional(documentary_config.input_album_manifest)
    audio_rows = read_csv_optional(documentary_config.input_audio_events)
    transcript_rows = read_csv_optional(documentary_config.input_transcript_segments)
    if enabled_media_sets:
        album_rows = [row for row in album_rows if row.get("media_set", "") in enabled_media_sets]
        audio_rows = [row for row in audio_rows if row.get("media_set", "") in enabled_media_sets]
        transcript_rows = [row for row in transcript_rows if row.get("media_set", "") in enabled_media_sets]

    story_beats = build_story_beats(moments)
    timeline = build_documentary_timeline(documentary_config, project_root, moments, clip_scores, timeline_source, selected_timeline_source, audio_rows, transcript_rows)
    chapters = build_chapters(documentary_config, story_beats, timeline, album_rows)

    documentary_config.output_dir.mkdir(parents=True, exist_ok=True)
    story_path = documentary_config.output_dir / "documentary_story.csv"
    chapters_path = documentary_config.output_dir / "documentary_chapters.csv"
    timeline_path = documentary_config.output_dir / "documentary_timeline.csv"
    write_csv(story_path, DOCUMENTARY_STORY_COLUMNS, story_beats)
    write_csv(chapters_path, DOCUMENTARY_CHAPTER_COLUMNS, chapters)
    write_csv(timeline_path, DOCUMENTARY_TIMELINE_COLUMNS, timeline)
    treatment_path = write_treatment(documentary_config, project_root, chapters, timeline)
    manifest_path = write_manifest(documentary_config, project_root, chapters, timeline, story_path, chapters_path, timeline_path, treatment_path)
    render_status, render_message, rendered_file_path, rendered_segment_count = render_documentary(documentary_config, project_root, timeline)
    return DocumentaryResult(
        chapter_count=len(chapters),
        story_beat_count=len(story_beats),
        timeline_event_count=len(timeline),
        actual_duration_seconds=round(sum(safe_float(str(row["duration_seconds"])) for row in timeline), 3),
        documentary_story_csv=story_path,
        documentary_chapters_csv=chapters_path,
        documentary_timeline_csv=timeline_path,
        documentary_manifest_csv=manifest_path,
        documentary_treatment_md=treatment_path,
        dry_run=documentary_config.dry_run,
        render_status=render_status,
        render_message=render_message,
        rendered_file_path=rendered_file_path,
        rendered_segment_count=rendered_segment_count,
    )
