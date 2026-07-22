"""AI-assisted Story Builder moment reports."""

from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.activity import ActivityProfile, activity_fit_score, load_activity_profile
from memory_curator_engine.common.execution import ordered_map
from memory_curator_engine.common.media import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, format_timestamp
from memory_curator_engine.common.media_sets import media_set_activity_map
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import parse_enabled


MOMENTS_COLUMNS = [
    "moment_id",
    "media_set",
    "activity",
    "moment_type",
    "title",
    "start_time",
    "end_time",
    "duration_seconds",
    "asset_count",
    "photo_count",
    "video_count",
    "hero_photo",
    "hero_video",
    "people",
    "mood",
    "ai_confidence",
    "moment_score",
    "album_score",
    "reel_score",
    "documentary_score",
    "time_capsule_score",
    "notes",
]

MOMENT_ASSETS_COLUMNS = [
    "moment_id",
    "media_set",
    "media_path",
    "original_path",
    "file_type",
    "captured_at",
    "duration_seconds",
    "quality_score",
    "album_score",
    "instagram_score",
    "movie_score",
    "activity_score",
    "reel_purpose_score",
    "documentary_purpose_score",
    "role",
]

STORY_MANIFEST_COLUMNS = [
    "moment_id",
    "media_set",
    "activity",
    "moment_type",
    "title",
    "start_time",
    "end_time",
    "hero_photo",
    "hero_video",
    "asset_count",
    "photo_count",
    "video_count",
    "moment_score",
    "album_score",
    "reel_score",
    "documentary_score",
    "time_capsule_score",
    "source_phase",
]

STORY_REVIEW_COLUMNS = [
    "moment_id",
    "title",
    "start_time",
    "end_time",
    "asset_count",
    "hero_photo",
    "hero_video",
    "review_status",
    "review_notes",
]


@dataclass(frozen=True)
class StoryConfig:
    enabled: bool
    dry_run: bool
    input_manifest: Path
    output_dir: Path
    activity_name: str
    moment_id_prefix: str
    max_gap_seconds: float
    min_assets_per_moment: int
    max_assets_per_moment: int
    target_moment_count: int
    merge_small_moments: bool
    title_hints: list[str]
    moment_taxonomy: list[str]
    ai_enabled: bool
    ai_required: bool
    ai_model: str
    ai_endpoint: str
    activity_profile: ActivityProfile
    media_set_activity_names: dict[str, str]
    media_set_profiles: dict[str, ActivityProfile]
    media_set_title_hints: dict[str, list[str]]
    media_set_taxonomies: dict[str, list[str]]
    media_set_target_counts: dict[str, int]


@dataclass(frozen=True)
class StoryAsset:
    media_set: str
    media_path: Path
    original_path: str
    file_type: str
    size_bytes: int
    width: int
    height: int
    duration_seconds: float
    quality_score: float
    album_score: float
    instagram_score: float
    movie_score: float
    activity_score: float
    reel_purpose_score: float
    documentary_purpose_score: float
    recommended_uses: list[str]
    captured_at: datetime


@dataclass(frozen=True)
class Moment:
    moment_id: str
    media_set: str
    activity: str
    assets: list[StoryAsset]
    moment_type: str
    title: str
    mood: str
    ai_confidence: float
    notes: str
    hero_photo: str
    hero_video: str
    moment_score: float
    album_score: float
    reel_score: float
    documentary_score: float
    time_capsule_score: float


@dataclass(frozen=True)
class StoryResult:
    asset_count: int
    moment_count: int
    ai_enabled: bool
    dry_run: bool
    moments_csv: Path
    moments_json: Path
    moment_assets_csv: Path
    story_manifest_csv: Path
    story_review_csv: Path


def load_story_config(config: Config, project_root: Path) -> StoryConfig:
    output_dir = resolve_project_path(project_root, config_value(config, "story_builder.output_dir", "MemoryCurator/05 Story Builder"))
    taxonomy = string_list(config_value(config, "story_builder.moment_taxonomy", []))
    if not taxonomy:
        taxonomy = ["arrival", "preparation", "activity", "highlight", "group_photo", "meal", "return_trip", "transition"]
    activity_map = media_set_activity_map(config)
    return StoryConfig(
        enabled=parse_enabled(config_value(config, "modules.story_builder.enabled", False), "story_builder"),
        dry_run=parse_enabled(config_value(config, "story_builder.dry_run", True), "story_builder.dry_run"),
        input_manifest=resolve_project_path(
            project_root,
            config_value(config, "story_builder.input_manifest", "MemoryCurator/03 Quality Scoring/quality_manifest.csv"),
        ),
        output_dir=output_dir,
        activity_name=str(config_value(config, "story_builder.activity_name", "Trip")),
        moment_id_prefix=str(config_value(config, "story_builder.moment_id_prefix", "moment")),
        max_gap_seconds=float(config_value(config, "story_builder.max_gap_seconds", 300)),
        min_assets_per_moment=int(config_value(config, "story_builder.min_assets_per_moment", 2)),
        max_assets_per_moment=int(config_value(config, "story_builder.max_assets_per_moment", 40)),
        target_moment_count=int(config_value(config, "story_builder.target_moment_count", 0)),
        merge_small_moments=parse_enabled(config_value(config, "story_builder.merge_small_moments", True), "story_builder.merge_small_moments"),
        title_hints=string_list(config_value(config, "story_builder.title_hints", [])),
        moment_taxonomy=taxonomy,
        ai_enabled=parse_enabled(config_value(config, "story_builder.ai.enabled", False), "story_builder.ai.enabled"),
        ai_required=parse_enabled(config_value(config, "story_builder.ai.required", False), "story_builder.ai.required"),
        ai_model=str(config_value(config, "story_builder.ai.model", "gpt-5.2-mini")),
        ai_endpoint=str(config_value(config, "story_builder.ai.endpoint", "https://api.openai.com/v1/responses")),
        activity_profile=load_activity_profile(
            config,
            str(config_value(config, "story_builder.activity_profile", config_value(config, "reel_builder.activity_profile", "default"))),
        ),
        media_set_activity_names={name: activity.activity_name for name, activity in activity_map.items()},
        media_set_profiles={
            name: load_activity_profile(config, activity.activity_profile)
            for name, activity in activity_map.items()
        },
        media_set_title_hints={
            name: story_title_hints_for_media_set(config, name, activity.activity_name, activity.activity_profile)
            for name, activity in activity_map.items()
        },
        media_set_taxonomies={
            name: story_taxonomy_for_media_set(config, name, activity.activity_profile)
            for name, activity in activity_map.items()
        },
        media_set_target_counts={
            name: int(config_value(config, f"story_builder.activities.{name}.target_moment_count", config_value(config, "story_builder.target_moment_count", 0)) or 0)
            for name in activity_map
        },
    )


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def story_title_hints_for_media_set(config: Config, media_set: str, activity_name: str, profile_name: str) -> list[str]:
    configured = string_list(config_value(config, f"story_builder.activities.{media_set}.title_hints", []))
    if configured:
        return configured
    defaults = {
        "rafting": ["Arriving at Rafting Center", "Putting on Helmets", "Walking to River", "Launching Raft", "First Rapids", "Big Splash", "River Run", "Group Photo", "Lunch", "Drive Home"],
        "atv": ["Arriving at ATV Base", "Getting Geared Up", "Starting Engines", "First Trail", "Mud Run", "Jungle Ride", "Fast Turns", "Group Ride", "Wrap Up"],
        "beach": ["Arriving at the Beach", "Ocean Views", "Beach Walk", "Water Time", "Sunset Moments", "Group Memories", "Leaving the Beach"],
        "waterfall": ["Arriving at the Trail", "Walking to Waterfall", "First View", "Waterfall Moment", "Swimming and Splash", "Scenic Shots", "Heading Back"],
        "restaurants": ["Arriving for Food", "Table Moments", "Food Highlights", "Cheers and Conversations", "Dessert or Closing", "Leaving the Restaurant"],
        "ricefield": ["Arriving at Rice Fields", "Walking the Terraces", "Scenic Views", "Portrait Moments", "Group Memories", "Leaving the Fields"],
        "savaya": ["Arriving at Savaya", "Venue Views", "Friends and Drinks", "Music and Crowd", "Sunset Energy", "Night Moments", "Closing Shot"],
        "stay": ["Villa and Stay", "Room Moments", "Pool and Relaxing", "Friends at Home Base", "Quiet Memories", "Leaving Stay"],
        "temple": ["Arriving at Temple", "Entrance and Courtyard", "Temple Details", "Portrait Moments", "Group Memories", "Leaving Temple"],
    }
    if media_set == "clubbing":
        return ["Arriving at Club", "Venue Views", "Friends and Drinks", "Music and Crowd", "Night Energy", "Dance Moments", "Closing Shot"]
    return defaults.get(profile_name, defaults.get(media_set, [f"{activity_name} Opening", f"{activity_name} Highlights", f"{activity_name} Group Moments", f"{activity_name} Closing"]))


def story_taxonomy_for_media_set(config: Config, media_set: str, profile_name: str) -> list[str]:
    configured = string_list(config_value(config, f"story_builder.activities.{media_set}.moment_taxonomy", []))
    if configured:
        return configured
    common = ["travel_to_activity", "arrival", "setup", "activity", "highlight", "group_photo", "meal", "return_trip", "transition", "other"]
    defaults = {
        "rafting": ["travel_to_activity", "arrival", "check_in", "safety_briefing", "gear_up", "walk_to_start", "launch", "calm_river", "rapids", "water_action", "splash", "group_photo", "meal", "return_trip", "transition", "other"],
        "atv": ["travel_to_activity", "arrival", "safety_briefing", "gear_up", "launch", "trail", "mud_action", "speed_action", "jungle", "group_photo", "return_trip", "transition", "other"],
        "beach": ["travel_to_activity", "arrival", "ocean_view", "beach_walk", "water_action", "sunset", "group_photo", "meal", "return_trip", "transition", "other"],
        "waterfall": ["travel_to_activity", "arrival", "trail", "first_view", "waterfall", "water_action", "scenic", "group_photo", "return_trip", "transition", "other"],
        "restaurants": ["travel_to_activity", "arrival", "table_moment", "food", "cheers", "conversation", "group_photo", "return_trip", "transition", "other"],
        "ricefield": ["travel_to_activity", "arrival", "walk", "scenic", "portrait", "group_photo", "return_trip", "transition", "other"],
        "savaya": ["travel_to_activity", "arrival", "venue_view", "drinks", "music", "dancing", "sunset", "group_photo", "return_trip", "transition", "other"],
        "stay": ["arrival", "room", "villa", "pool", "relaxing", "group_photo", "transition", "other"],
        "temple": ["travel_to_activity", "arrival", "entrance", "temple_details", "cultural_moment", "portrait", "group_photo", "return_trip", "transition", "other"],
    }
    return defaults.get(profile_name, defaults.get(media_set, common))


def story_config_for_media_set(config: StoryConfig, media_set: str) -> StoryConfig:
    title_hints = config.media_set_title_hints.get(media_set, config.title_hints)
    return replace(
        config,
        activity_name=config.media_set_activity_names.get(media_set, config.activity_name),
        moment_id_prefix=media_set,
        title_hints=title_hints,
        moment_taxonomy=config.media_set_taxonomies.get(media_set, config.moment_taxonomy),
        target_moment_count=config.media_set_target_counts.get(media_set, len(title_hints)),
        activity_profile=config.media_set_profiles.get(media_set, config.activity_profile),
    )


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PHOTO_EXTENSIONS:
        return "photo"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def parse_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_int(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def read_assets(config: StoryConfig, project_root: Path) -> list[StoryAsset]:
    if not config.input_manifest.exists():
        raise FileNotFoundError(
            f"Missing upstream manifest: {config.input_manifest.relative_to(project_root).as_posix()}. "
            "Run quality-scoring first."
        )
    with config.input_manifest.open(newline="", encoding="utf-8") as manifest_file:
        rows = list(csv.DictReader(manifest_file))
    if not rows:
        raise ValueError(
            f"Upstream manifest is empty: {config.input_manifest.relative_to(project_root).as_posix()}. "
            "Run quality-scoring first."
        )

    assets: list[StoryAsset] = []
    for row in rows:
        media_path_value = row.get("media_path", "")
        if not media_path_value:
            raise ValueError(f"quality_manifest row is missing media_path: {config.input_manifest}")
        media_path = resolve_project_path(project_root, media_path_value)
        if not media_path.exists():
            raise FileNotFoundError(f"Story Builder input media is missing: {media_path}")
        stat_result = media_path.stat()
        captured = stat_result.st_mtime
        assets.append(
            StoryAsset(
                media_set=row.get("media_set") or "default",
                media_path=media_path,
                original_path=row.get("original_path") or media_path_value,
                file_type=row.get("file_type") or file_kind(media_path),
                size_bytes=parse_int(row.get("size_bytes")),
                width=parse_int(row.get("width")),
                height=parse_int(row.get("height")),
                duration_seconds=parse_float(row.get("duration_seconds")),
                quality_score=parse_float(row.get("quality_score")),
                album_score=parse_float(row.get("album_score")),
                instagram_score=parse_float(row.get("instagram_score")),
                movie_score=parse_float(row.get("movie_score")),
                activity_score=parse_float(row.get("activity_score")),
                reel_purpose_score=parse_float(row.get("reel_purpose_score") or row.get("instagram_score")),
                documentary_purpose_score=parse_float(row.get("documentary_purpose_score") or row.get("movie_score")),
                recommended_uses=[use for use in (row.get("recommended_uses") or "").split(",") if use],
                captured_at=datetime.fromtimestamp(captured),
            )
        )
    return sorted(assets, key=lambda asset: (asset.media_set, asset.captured_at, asset.media_path.as_posix()))


def group_assets(config: StoryConfig, assets: list[StoryAsset]) -> list[list[StoryAsset]]:
    groups: list[list[StoryAsset]] = []
    by_set: dict[str, list[StoryAsset]] = {}
    for asset in assets:
        by_set.setdefault(asset.media_set, []).append(asset)

    for media_set, media_assets in by_set.items():
        activity_config = story_config_for_media_set(config, media_set)
        media_groups: list[list[StoryAsset]] = []
        current: list[StoryAsset] = []
        previous: StoryAsset | None = None
        for asset in media_assets:
            gap = (asset.captured_at - previous.captured_at).total_seconds() if previous else 0
            if current and (gap > activity_config.max_gap_seconds or len(current) >= activity_config.max_assets_per_moment):
                media_groups.append(current)
                current = []
            current.append(asset)
            previous = asset
        if current:
            media_groups.append(current)

        if activity_config.merge_small_moments:
            media_groups = merge_small_groups(media_groups, activity_config.min_assets_per_moment, activity_config.max_gap_seconds)
        groups.extend(split_to_target_moments(media_groups, target_moment_count(activity_config), activity_config.max_assets_per_moment))
    return groups


def target_moment_count(config: StoryConfig) -> int:
    if config.target_moment_count > 0:
        return config.target_moment_count
    return len(config.title_hints)


def split_to_target_moments(groups: list[list[StoryAsset]], target_count: int, max_assets_per_moment: int) -> list[list[StoryAsset]]:
    if target_count <= 0:
        target_count = len(groups)
    result = groups[:]
    while len(result) < target_count:
        split_index = largest_splittable_group_index(result)
        if split_index is None:
            break
        group = result.pop(split_index)
        left, right = split_group(group)
        result[split_index:split_index] = [left, right]

    final: list[list[StoryAsset]] = []
    for group in result:
        if len(group) <= max_assets_per_moment:
            final.append(group)
            continue
        chunk_count = (len(group) + max_assets_per_moment - 1) // max_assets_per_moment
        final.extend(split_group_into_chunks(group, chunk_count))
    return final


def largest_splittable_group_index(groups: list[list[StoryAsset]]) -> int | None:
    candidates = [(len(group), index) for index, group in enumerate(groups) if len(group) > 1]
    if not candidates:
        return None
    return max(candidates)[1]


def split_group(group: list[StoryAsset]) -> tuple[list[StoryAsset], list[StoryAsset]]:
    split_at = best_split_index(group)
    return group[:split_at], group[split_at:]


def best_split_index(group: list[StoryAsset]) -> int:
    if len(group) <= 2:
        return 1
    gaps = [
        ((group[index].captured_at - group[index - 1].captured_at).total_seconds(), index)
        for index in range(1, len(group))
    ]
    biggest_gap, gap_index = max(gaps)
    lower = max(1, len(group) // 4)
    upper = min(len(group) - 1, (len(group) * 3) // 4)
    if biggest_gap > 5 and lower <= gap_index <= upper:
        return gap_index
    return len(group) // 2


def split_group_into_chunks(group: list[StoryAsset], chunk_count: int) -> list[list[StoryAsset]]:
    chunks: list[list[StoryAsset]] = []
    for chunk_index in range(chunk_count):
        start = round(chunk_index * len(group) / chunk_count)
        end = round((chunk_index + 1) * len(group) / chunk_count)
        chunks.append(group[start:end])
    return [chunk for chunk in chunks if chunk]


def merge_small_groups(groups: list[list[StoryAsset]], min_assets: int, max_gap_seconds: float) -> list[list[StoryAsset]]:
    merged: list[list[StoryAsset]] = []
    for group in groups:
        gap = (group[0].captured_at - merged[-1][-1].captured_at).total_seconds() if merged and group else 0
        if merged and len(group) < min_assets and gap <= max_gap_seconds:
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def hero_photo(assets: list[StoryAsset], project_root: Path) -> str:
    photos = [asset for asset in assets if file_kind(asset.media_path) == "photo"]
    if not photos:
        return ""
    best = max(photos, key=lambda asset: (asset.album_score, asset.quality_score, asset.size_bytes, -abs((asset.captured_at - midpoint(assets)).total_seconds())))
    return best.media_path.relative_to(project_root).as_posix()


def hero_video(assets: list[StoryAsset], project_root: Path) -> str:
    videos = [asset for asset in assets if file_kind(asset.media_path) == "video"]
    if not videos:
        return ""
    best = max(videos, key=lambda asset: (asset.movie_score, asset.duration_seconds, asset.quality_score, asset.size_bytes))
    return best.media_path.relative_to(project_root).as_posix()


def midpoint(assets: list[StoryAsset]) -> datetime:
    timestamps = [asset.captured_at.timestamp() for asset in assets]
    return datetime.fromtimestamp((min(timestamps) + max(timestamps)) / 2)


def deterministic_moment(config: StoryConfig, assets: list[StoryAsset], index: int, project_root: Path) -> Moment:
    moment_id = f"{config.moment_id_prefix}_{index:03d}"
    photo_count = sum(file_kind(asset.media_path) == "photo" for asset in assets)
    video_count = sum(file_kind(asset.media_path) == "video" for asset in assets)
    album_score = round(mean([asset.album_score for asset in assets] or [0]), 2)
    reel_score = round(mean([asset.reel_purpose_score or asset.instagram_score for asset in assets] or [0]), 2)
    documentary_score = round(mean([asset.documentary_purpose_score or asset.movie_score for asset in assets] or [0]) + min(10, sum(asset.duration_seconds for asset in assets) / 60), 2)
    moment_score = round(mean([max(asset.quality_score, asset.activity_score) for asset in assets] or [0]) + min(8, len(assets) / 4) + (4 if photo_count and video_count else 0), 2)
    moment_type, mood, title, notes = classify_moment_with_python(config, assets, index, photo_count, video_count)
    return Moment(
        moment_id=moment_id,
        media_set=assets[0].media_set if assets else "default",
        activity=config.activity_name,
        assets=assets,
        moment_type=moment_type,
        title=title,
        mood=mood,
        ai_confidence=0.0,
        notes=notes,
        hero_photo=hero_photo(assets, project_root),
        hero_video=hero_video(assets, project_root),
        moment_score=moment_score,
        album_score=album_score,
        reel_score=reel_score,
        documentary_score=documentary_score,
        time_capsule_score=round(moment_score * 0.6 + max(album_score, documentary_score) * 0.4, 2),
    )


def classify_moment_with_python(
    config: StoryConfig,
    assets: list[StoryAsset],
    index: int,
    photo_count: int,
    video_count: int,
) -> tuple[str, str, str, str]:
    filenames = " ".join(asset.media_path.name.lower() for asset in assets)
    total_video_seconds = sum(asset.duration_seconds for asset in assets)
    uses = {use for asset in assets for use in asset.recommended_uses}
    taxonomy = set(config.moment_taxonomy)
    avg_activity = mean([asset.activity_score for asset in assets] or [0])
    avg_reel = mean([asset.reel_purpose_score for asset in assets] or [0])
    motion_text = " ".join(
        f"{asset.media_path.name} {'gopro gx pov' if asset.media_path.name.lower().startswith(('gx', 'gopr')) else ''}"
        for asset in assets
        if file_kind(asset.media_path) == "video"
    )
    launch_fit, _ = activity_fit_score(
        config.activity_profile,
        path=assets[0].media_path if assets else "",
        moment_type="launch",
        role="action",
        technical_score=mean([asset.quality_score for asset in assets] or [50]),
        motion_score=avg_activity,
        audio_score=60,
        story_score=avg_reel,
        text=f"{filenames} {motion_text}",
    )
    splash_fit, _ = activity_fit_score(
        config.activity_profile,
        path=assets[0].media_path if assets else "",
        moment_type="splash",
        role="action",
        technical_score=mean([asset.quality_score for asset in assets] or [50]),
        motion_score=avg_activity,
        audio_score=65,
        story_score=avg_reel,
        text=f"{filenames} {motion_text}",
    )

    ordered_defaults = [moment_type for moment_type in config.moment_taxonomy if moment_type != "other"]

    hinted_type = title_hint_type(config.title_hints[index - 1]) if index <= len(config.title_hints) else ""

    if splash_fit >= 88 and "splash" in taxonomy:
        moment_type = "splash"
    elif launch_fit >= 84 and "rapids" in taxonomy and avg_activity >= 70:
        moment_type = "rapids"
    elif hinted_type in taxonomy and avg_activity < 78:
        moment_type = hinted_type
    elif any(word in filenames for word in ["food", "dinner", "lunch", "breakfast", "restaurant"]) and "food" in taxonomy:
        moment_type = "food"
    elif any(word in filenames for word in ["drink", "cheers", "savaya", "club", "clubbing"]) and "drinks" in taxonomy:
        moment_type = "drinks"
    elif any(word in filenames for word in ["waterfall", "water fall"]) and "waterfall" in taxonomy:
        moment_type = "waterfall"
    elif any(word in filenames for word in ["sunset", "sun"]) and "sunset" in taxonomy:
        moment_type = "sunset"
    elif avg_activity >= 70 and "mud_action" in taxonomy:
        moment_type = "mud_action"
    elif avg_activity >= 70 and "speed_action" in taxonomy:
        moment_type = "speed_action"
    elif avg_activity >= 65 and "water_action" in taxonomy:
        moment_type = "water_action"
    elif avg_activity >= 65 and "activity" in taxonomy:
        moment_type = "activity"
    elif any(word in filenames for word in ["temple", "pura"]) and "temple_details" in taxonomy:
        moment_type = "temple_details"
    elif any(word in filenames for word in ["villa", "room", "pool"]) and "villa" in taxonomy:
        moment_type = "villa"
    elif "scenic" in taxonomy and (photo_count >= video_count or avg_activity < 55):
        moment_type = "scenic"
    elif "group" in filenames and "group_photo" in taxonomy:
        moment_type = "group_photo"
    elif photo_count >= 5 and video_count <= 1 and "group_photo" in taxonomy:
        moment_type = "group_photo"
    elif total_video_seconds >= 120 and avg_activity >= 60 and "rapids" in taxonomy:
        moment_type = "rapids"
    elif video_count >= photo_count and ("movie" in uses or "instagram" in uses) and avg_activity >= 60 and "rapids" in taxonomy:
        moment_type = "rapids"
    elif index <= len(ordered_defaults) and ordered_defaults[index - 1] in taxonomy:
        moment_type = ordered_defaults[index - 1]
    elif video_count and "activity" in taxonomy:
        moment_type = "activity"
    elif "transition" in taxonomy:
        moment_type = "transition"
    else:
        moment_type = "other"

    mood = mood_for_moment(moment_type, video_count, total_video_seconds)
    title = deterministic_title(config, index, moment_type)
    notes = f"python classification from timestamps, media mix, filenames, purpose scores, and activity profile {config.activity_profile.name}; avg_activity={avg_activity:.1f}"
    return moment_type, mood, title, notes


def title_hint_type(title: str) -> str:
    normalized = title.lower()
    mappings = [
        ("leaving", "travel_to_activity"),
        ("drive", "travel_to_activity"),
        ("coffee", "transition"),
        ("arriving", "arrival"),
        ("arrival", "arrival"),
        ("center", "arrival"),
        ("briefing", "safety_briefing"),
        ("helmet", "gear_up"),
        ("gear", "gear_up"),
        ("walking", "walk_to_start"),
        ("river", "walk_to_start"),
        ("launch", "launch"),
        ("rapid", "rapids"),
        ("splash", "splash"),
        ("group", "group_photo"),
        ("lunch", "meal"),
        ("meal", "meal"),
        ("home", "return_trip"),
        ("return", "return_trip"),
        ("trail", "trail"),
        ("mud", "mud_action"),
        ("jungle", "jungle"),
        ("beach", "beach_walk"),
        ("ocean", "ocean_view"),
        ("waterfall", "waterfall"),
        ("food", "food"),
        ("table", "table_moment"),
        ("cheers", "cheers"),
        ("drink", "drinks"),
        ("sunset", "sunset"),
        ("temple", "temple_details"),
        ("villa", "villa"),
        ("pool", "pool"),
        ("scenic", "scenic"),
    ]
    for needle, moment_type in mappings:
        if needle in normalized:
            return moment_type
    return ""


def deterministic_title(config: StoryConfig, index: int, moment_type: str) -> str:
    if index <= len(config.title_hints):
        return config.title_hints[index - 1]
    return moment_type.replace("_", " ").title() if moment_type != "other" else f"{config.activity_name} Moment {index:03d}"


def mood_for_moment(moment_type: str, video_count: int, total_video_seconds: float) -> str:
    if moment_type in {"rapids", "splash", "launch"}:
        return "Excitement"
    if moment_type in {"meal", "return_trip"}:
        return "Relaxed"
    if moment_type in {"safety_briefing", "gear_up", "walk_to_start"}:
        return "Anticipation"
    if video_count and total_video_seconds > 60:
        return "Action"
    return "Memory"


def classify_moment_with_ai(config: StoryConfig, moment: Moment, project_root: Path) -> Moment:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        if config.ai_required:
            raise ValueError("OPENAI_API_KEY is required for AI Story Builder. Set it or run story-builder without --ai.")
        return moment

    payload = {
        "model": config.ai_model,
        "temperature": 0.2,
        "input": build_ai_prompt(config, moment, project_root),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "moment_classification",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "moment_type", "mood", "confidence", "notes"],
                    "properties": {
                        "title": {"type": "string"},
                        "moment_type": {"type": "string"},
                        "mood": {"type": "string"},
                        "confidence": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                },
            }
        },
    }
    data = post_openai(config.ai_endpoint, api_key, payload)
    parsed = parse_response_json(data)
    taxonomy = set(config.moment_taxonomy)
    moment_type = str(parsed.get("moment_type") or moment.moment_type)
    if taxonomy and moment_type not in taxonomy:
        moment_type = "other"
    return replace(
        moment,
        title=str(parsed.get("title") or moment.title),
        moment_type=moment_type,
        mood=str(parsed.get("mood") or "unknown"),
        ai_confidence=max(0.0, min(1.0, parse_float(parsed.get("confidence")))),
        notes=str(parsed.get("notes") or "AI classified moment"),
    )


def build_ai_prompt(config: StoryConfig, moment: Moment, project_root: Path) -> str:
    assets_summary = []
    for asset in moment.assets:
        assets_summary.append(
            {
                "filename": asset.media_path.name,
                "media_path": asset.media_path.relative_to(project_root).as_posix(),
                "file_type": asset.file_type,
                "captured_at": asset.captured_at.isoformat(timespec="seconds"),
                "duration_seconds": asset.duration_seconds,
                "quality_score": asset.quality_score,
                "album_score": asset.album_score,
                "instagram_score": asset.instagram_score,
                "movie_score": asset.movie_score,
                "activity_score": asset.activity_score,
                "reel_purpose_score": asset.reel_purpose_score,
                "documentary_purpose_score": asset.documentary_purpose_score,
                "recommended_uses": asset.recommended_uses,
            }
        )
    return json.dumps(
        {
            "task": "Classify this travel media moment. Use the taxonomy when possible. Create a short human title.",
            "activity": config.activity_name,
            "allowed_moment_types": config.moment_taxonomy + ["other"],
            "deterministic_title": moment.title,
            "start_time": start_time(moment.assets),
            "end_time": end_time(moment.assets),
            "photo_count": sum(file_kind(asset.media_path) == "photo" for asset in moment.assets),
            "video_count": sum(file_kind(asset.media_path) == "video" for asset in moment.assets),
            "hero_photo": moment.hero_photo,
            "hero_video": moment.hero_video,
            "assets": assets_summary,
            "output_contract": {
                "title": "short title such as First Rapids",
                "moment_type": "one allowed_moment_types value",
                "mood": "one or two words",
                "confidence": "0.0 to 1.0",
                "notes": "brief rationale using metadata only",
            },
        },
        ensure_ascii=True,
    )


def post_openai(endpoint: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - user-configured HTTPS endpoint.
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"OpenAI API request failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"OpenAI API request failed: {exc}") from exc


def parse_response_json(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("output_text"), str):
        return json.loads(data["output_text"])
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return json.loads(content.get("text", "{}"))
    text = json.dumps(data)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("OpenAI response did not contain parseable JSON")


def start_time(assets: list[StoryAsset]) -> str:
    return min(asset.captured_at for asset in assets).isoformat(timespec="seconds") if assets else ""


def end_time(assets: list[StoryAsset]) -> str:
    if not assets:
        return ""
    latest = max(asset.captured_at.timestamp() + asset.duration_seconds for asset in assets)
    return datetime.fromtimestamp(latest).isoformat(timespec="seconds")


def duration_seconds(assets: list[StoryAsset]) -> float:
    if not assets:
        return 0.0
    start = min(asset.captured_at.timestamp() for asset in assets)
    end = max(asset.captured_at.timestamp() + asset.duration_seconds for asset in assets)
    return round(max(0, end - start), 3)


def asset_role(moment: Moment, asset: StoryAsset, project_root: Path) -> str:
    relative = asset.media_path.relative_to(project_root).as_posix()
    if relative == moment.hero_photo:
        return "hero_photo"
    if relative == moment.hero_video:
        return "hero_video"
    if file_kind(asset.media_path) == "video" and asset.movie_score >= 60:
        return "b_roll"
    return "supporting"


def write_reports(config: StoryConfig, project_root: Path, moments: list[Moment]) -> StoryResult:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    moments_csv = config.output_dir / "moments.csv"
    moments_json = config.output_dir / "moments.json"
    moment_assets_csv = config.output_dir / "moment_assets.csv"
    story_manifest_csv = config.output_dir / "story_manifest.csv"
    story_review_csv = config.output_dir / "story_review.csv"

    with moments_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MOMENTS_COLUMNS)
        writer.writeheader()
        for moment in moments:
            writer.writerow(moment_row(moment))

    with moment_assets_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MOMENT_ASSETS_COLUMNS)
        writer.writeheader()
        for moment in moments:
            for asset in moment.assets:
                writer.writerow(asset_row(moment, asset, project_root))

    with story_manifest_csv.open("w", newline="", encoding="utf-8") as file, story_review_csv.open("w", newline="", encoding="utf-8") as review_file:
        manifest_writer = csv.DictWriter(file, fieldnames=STORY_MANIFEST_COLUMNS)
        review_writer = csv.DictWriter(review_file, fieldnames=STORY_REVIEW_COLUMNS)
        manifest_writer.writeheader()
        review_writer.writeheader()
        for moment in moments:
            manifest_writer.writerow(manifest_row(moment))
            review_writer.writerow(review_row(moment))

    moments_json.write_text(json.dumps([moment_json(moment, project_root) for moment in moments], indent=2), encoding="utf-8")
    write_story_activity_reports(config, project_root, moments)
    return StoryResult(
        asset_count=sum(len(moment.assets) for moment in moments),
        moment_count=len(moments),
        ai_enabled=config.ai_enabled,
        dry_run=config.dry_run,
        moments_csv=moments_csv,
        moments_json=moments_json,
        moment_assets_csv=moment_assets_csv,
        story_manifest_csv=story_manifest_csv,
        story_review_csv=story_review_csv,
    )


def write_story_activity_reports(config: StoryConfig, project_root: Path, moments: list[Moment]) -> None:
    by_set: dict[str, list[Moment]] = {}
    for moment in moments:
        by_set.setdefault(moment.media_set, []).append(moment)
    for media_set, media_moments in by_set.items():
        activity_dir = config.output_dir / media_set
        activity_config = replace(config, output_dir=activity_dir)
        write_story_csv_set(activity_config, project_root, media_moments)


def write_story_csv_set(config: StoryConfig, project_root: Path, moments: list[Moment]) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    moments_csv = config.output_dir / "moments.csv"
    moments_json = config.output_dir / "moments.json"
    moment_assets_csv = config.output_dir / "moment_assets.csv"
    story_manifest_csv = config.output_dir / "story_manifest.csv"
    story_review_csv = config.output_dir / "story_review.csv"

    with moments_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MOMENTS_COLUMNS)
        writer.writeheader()
        for moment in moments:
            writer.writerow(moment_row(moment))

    with moment_assets_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MOMENT_ASSETS_COLUMNS)
        writer.writeheader()
        for moment in moments:
            for asset in moment.assets:
                writer.writerow(asset_row(moment, asset, project_root))

    with story_manifest_csv.open("w", newline="", encoding="utf-8") as file, story_review_csv.open("w", newline="", encoding="utf-8") as review_file:
        manifest_writer = csv.DictWriter(file, fieldnames=STORY_MANIFEST_COLUMNS)
        review_writer = csv.DictWriter(review_file, fieldnames=STORY_REVIEW_COLUMNS)
        manifest_writer.writeheader()
        review_writer.writeheader()
        for moment in moments:
            manifest_writer.writerow(manifest_row(moment))
            review_writer.writerow(review_row(moment))

    moments_json.write_text(json.dumps([moment_json(moment, project_root) for moment in moments], indent=2), encoding="utf-8")


def moment_row(moment: Moment) -> dict[str, object]:
    return {
        "moment_id": moment.moment_id,
        "media_set": moment.media_set,
        "activity": moment.activity,
        "moment_type": moment.moment_type,
        "title": moment.title,
        "start_time": start_time(moment.assets),
        "end_time": end_time(moment.assets),
        "duration_seconds": duration_seconds(moment.assets),
        "asset_count": len(moment.assets),
        "photo_count": sum(file_kind(asset.media_path) == "photo" for asset in moment.assets),
        "video_count": sum(file_kind(asset.media_path) == "video" for asset in moment.assets),
        "hero_photo": moment.hero_photo,
        "hero_video": moment.hero_video,
        "people": "",
        "mood": moment.mood,
        "ai_confidence": moment.ai_confidence,
        "moment_score": moment.moment_score,
        "album_score": moment.album_score,
        "reel_score": moment.reel_score,
        "documentary_score": moment.documentary_score,
        "time_capsule_score": moment.time_capsule_score,
        "notes": moment.notes,
    }


def asset_row(moment: Moment, asset: StoryAsset, project_root: Path) -> dict[str, object]:
    return {
        "moment_id": moment.moment_id,
        "media_set": asset.media_set,
        "media_path": asset.media_path.relative_to(project_root).as_posix(),
        "original_path": asset.original_path,
        "file_type": asset.file_type,
        "captured_at": format_timestamp(asset.captured_at.timestamp()),
        "duration_seconds": asset.duration_seconds or "",
        "quality_score": asset.quality_score,
        "album_score": asset.album_score,
        "instagram_score": asset.instagram_score,
        "movie_score": asset.movie_score,
        "activity_score": asset.activity_score,
        "reel_purpose_score": asset.reel_purpose_score,
        "documentary_purpose_score": asset.documentary_purpose_score,
        "role": asset_role(moment, asset, project_root),
    }


def manifest_row(moment: Moment) -> dict[str, object]:
    row = moment_row(moment)
    return {key: row[key] for key in STORY_MANIFEST_COLUMNS if key in row} | {"source_phase": "story_builder"}


def review_row(moment: Moment) -> dict[str, object]:
    return {
        "moment_id": moment.moment_id,
        "title": moment.title,
        "start_time": start_time(moment.assets),
        "end_time": end_time(moment.assets),
        "asset_count": len(moment.assets),
        "hero_photo": moment.hero_photo,
        "hero_video": moment.hero_video,
        "review_status": "needs_review",
        "review_notes": "",
    }


def moment_json(moment: Moment, project_root: Path) -> dict[str, object]:
    return moment_row(moment) | {
        "assets": [asset_row(moment, asset, project_root) for asset in moment.assets],
    }


def run_story_builder(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    no_ai: bool = False,
    force_ai: bool = False,
    execute: bool = False,
) -> StoryResult:
    story_config = load_story_config(config, project_root)
    if execute:
        story_config = replace(story_config, dry_run=False)
    if force_ai:
        story_config = replace(story_config, ai_enabled=True, ai_required=True)
    if no_ai:
        story_config = replace(story_config, ai_enabled=False, ai_required=False)
    if not story_config.enabled and not include_disabled:
        raise ValueError("Story Builder is disabled in config. Enable modules.story_builder.enabled or pass --include-disabled.")

    assets = read_assets(story_config, project_root)
    groups = group_assets(story_config, assets)
    counters: dict[str, int] = {}
    moment_jobs: list[tuple[StoryConfig, list[StoryAsset], int]] = []
    for group in groups:
        media_set = group[0].media_set if group else "default"
        counters[media_set] = counters.get(media_set, 0) + 1
        activity_config = story_config_for_media_set(story_config, media_set)
        moment_jobs.append((activity_config, group, counters[media_set]))
    moments = ordered_map(
        config,
        "story_builder",
        lambda job: deterministic_moment(job[0], job[1], job[2], project_root),
        moment_jobs,
    )
    if story_config.ai_enabled:
        moments = ordered_map(
            config,
            "story_builder_ai",
            lambda moment: classify_moment_with_ai(story_config_for_media_set(story_config, moment.media_set), moment, project_root),
            moments,
        )
    return write_reports(story_config, project_root, moments)
