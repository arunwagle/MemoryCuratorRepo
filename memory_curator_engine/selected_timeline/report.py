"""Selected Timeline phase.

This phase creates a canonical best activity timeline before Reel Builder and
Documentary Builder consume the material.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from memory_curator_engine.common.activity import load_activity_profile
from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.execution import ordered_map
from memory_curator_engine.common.media_sets import configured_media_sets, media_set_activity_map
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.report import parse_enabled
from memory_curator_engine.reels.report import (
    REEL_CANDIDATE_COLUMNS,
    REEL_EDIT_DECISION_COLUMNS,
    REEL_HIGHLIGHT_TIMELINE_COLUMNS,
    REEL_MANIFEST_COLUMNS,
    ReelConfig,
    ReelSelection,
    activity_scoped_reel_config,
    aspect_ratio_for,
    build_candidates,
    candidate_row,
    edit_decision_row,
    highlight_timeline_row,
    load_reel_config,
    load_segment_audit_cache,
    load_source_chronology_index,
    path_text,
    parse_media_sets,
    render_reel,
    save_segment_audit_cache,
    sample_video_frames,
    select_master_highlight,
    selected_timeline_candidate_text,
    write_csv,
)


OPENCLIP_STATE: dict[str, Any] = {}


@dataclass(frozen=True)
class SelectedTimelineResult:
    activity: str
    candidate_count: int
    selected_count: int
    actual_duration_seconds: float
    rendered_count: int
    render_status: str
    rendered_file_path: Path
    candidates_csv: Path
    selected_timeline_csv: Path
    edit_decisions_csv: Path
    manifest_csv: Path
    report_md: Path
    cache_file: Path
    cache_entries: int
    dry_run: bool


def selected_timeline_enabled(config: Config) -> bool:
    return parse_enabled(config_value(config, "modules.selected_timeline.enabled", True), "selected_timeline")


def selected_timeline_config(config: Config, project_root: Path, base: ReelConfig, media_set: str) -> ReelConfig:
    curated_root = str(config_value(config, "project.curated_root", "input_data/curated"))
    activity_map = media_set_activity_map(config)
    activity = activity_map.get(media_set)
    profile_name = activity.activity_profile if activity else media_set
    profile = load_activity_profile(config, profile_name)
    section = config_value(config, "selected_timeline", {}) or {}
    overrides = section.get("activity_overrides", {}) if isinstance(section, dict) else {}
    activity_section = overrides.get(media_set, {}) if isinstance(overrides, dict) else {}
    if not isinstance(activity_section, dict):
        activity_section = {}
    render_section = section.get("render", {}) or {}
    output_root = resolve_project_path(project_root, section.get("output_dir", "MemoryCurator/08 Selected Timeline"))
    exports_root = resolve_project_path(project_root, section.get("exports_dir", f"{curated_root}/08 Selected Timeline/exports"))
    target_duration = float(activity_section.get("target_duration_seconds", section.get("target_duration_seconds", 600)))
    min_segment = float(activity_section.get("min_segment_seconds", section.get("min_segment_seconds", max(3.0, base.min_segment_seconds))))
    people_terms = {"friends", "friend", "people", "person", "group", "group_reactions", "emotion", "celebration", "dancing"}
    profile_terms = {str(item).lower() for item in list(profile.maximize) + list(profile.required_context)}
    if profile.optimization_goal in {"memory", "social", "cinematic"} or profile_terms.intersection(people_terms):
        min_segment = min(min_segment, 2.0)
    max_segment = float(activity_section.get("max_segment_seconds", section.get("max_segment_seconds", max(8.0, base.max_segment_seconds))))
    max_clips = int(activity_section.get("max_clips", section.get("max_clips", max(80, base.max_clips))))
    max_per_source = int(activity_section.get("max_segments_per_source_video", section.get("max_segments_per_source_video", max(4, base.highlight_max_per_source_video))))
    windows_per_clip = int(activity_section.get("windows_per_clip", section.get("windows_per_clip", max(3, base.windows_per_clip))))
    max_window_candidates = int(activity_section.get("max_window_candidates", section.get("max_window_candidates", max(14, base.max_window_candidates))))
    render_enabled = parse_enabled(render_section.get("enabled", base.render.enabled), "selected_timeline.render.enabled")
    render = replace(
        base.render,
        enabled=render_enabled,
        width=int(render_section.get("width", 1920)),
        height=int(render_section.get("height", 1080)),
        fps=int(render_section.get("fps", base.render.fps)),
        crop_mode=str(render_section.get("crop_mode", "center_crop")),
        audio_mode=str(render_section.get("audio_mode", "keep_source")),
        music_enabled=False,
        music_path="",
        source_audio_volume=float(render_section.get("source_audio_volume", base.render.source_audio_volume or 1.0)),
        overwrite_policy=str(render_section.get("overwrite_policy", base.render.overwrite_policy)),
    )
    return replace(
        activity_scoped_reel_config(base, media_set),
        reel_id=f"{base.trip_slug}_{media_set}_selected_timeline",
        style="selected_timeline",
        variant="selected_timeline",
        media_sets={media_set},
        activity_profile=profile,
        output_dir=output_root / media_set,
        exports_dir=exports_root / media_set,
        target_duration_seconds=target_duration,
        min_segment_seconds=min_segment,
        max_segment_seconds=max_segment,
        max_segments_per_moment=max(6, base.max_segments_per_moment),
        max_segments_per_source_video=max_per_source,
        min_clips=1,
        max_clips=max_clips,
        chronological="strict",
        include_moment_types=set(),
        required_moment_types=[],
        moment_story_order=[],
        promote_high_action_arrival=True,
        promoted_action_min_audio_score=45,
        promoted_action_min_start_seconds=0,
        speed_ramps_enabled=False,
        speed_ramp_fraction=0.0,
        max_speed_factor=1.0,
        refine_segment_windows=True,
        max_window_candidates=max_window_candidates,
        windows_per_clip=windows_per_clip,
        highlight_timeline_enabled=True,
        highlight_max_per_source_video=max_per_source,
        render=render,
    )


def selected_timeline_diversity_enabled(config: Config) -> bool:
    return parse_enabled(
        config_value(config, "selected_timeline.diversity_filter.enabled", True),
        "selected_timeline.diversity_filter.enabled",
    )


def selected_timeline_semantic_similarity_enabled(config: Config) -> bool:
    return parse_enabled(
        config_value(config, "selected_timeline.semantic_similarity.enabled", False),
        "selected_timeline.semantic_similarity.enabled",
    )


def selected_timeline_face_filter_enabled(config: Config) -> bool:
    return parse_enabled(
        config_value(config, "selected_timeline.face_filter.reject_person_without_face", True),
        "selected_timeline.face_filter.reject_person_without_face",
    )


def selected_timeline_tag_set(selection: ReelSelection) -> set[str]:
    return {tag for tag in selection.candidate.visual_tags.split(",") if tag}


def selected_timeline_visual_signature(selection: ReelSelection) -> set[str]:
    generic_tags = {
        "face_visible",
        "people_visible",
        "phone_perspective",
        "action_camera_pov",
        "group_camera_perspective",
        "landscape",
        "scenic",
    }
    return selected_timeline_tag_set(selection) - generic_tags


def selected_timeline_background_signature(selection: ReelSelection) -> set[str]:
    background_tags = {
        "architecture",
        "beach",
        "celebration",
        "dancing",
        "food",
        "jungle_trail",
        "landscape",
        "lit_tunnel",
        "mud_water_run",
        "nightlife",
        "pool",
        "rapids",
        "restaurant",
        "ricefield",
        "river_scene",
        "savaya",
        "clubbing",
        "scenic",
        "speed_action",
        "temple",
        "tunnel_or_shade",
        "water",
        "water_crossing",
        "water_speed_run",
        "waterfall",
    }
    return selected_timeline_tag_set(selection).intersection(background_tags)


def selected_timeline_layout_signature(selection: ReelSelection) -> tuple[str, ...]:
    tags = selected_timeline_tag_set(selection)
    signature: list[str] = []
    if tags.intersection({"face_visible", "people_visible", "group_reaction"}):
        signature.append("people")
    if tags.intersection({"food", "restaurant"}):
        signature.append("food")
    if tags.intersection({"architecture", "temple"}):
        signature.append("architecture")
    if tags.intersection({"beach", "water", "waterfall", "river_scene", "rapids"}):
        signature.append("water")
    if tags.intersection({"ricefield", "jungle_trail", "scenic", "landscape"}):
        signature.append("scenic")
    if tags.intersection({"dancing", "nightlife", "celebration"}):
        signature.append("social")
    if tags.intersection({"water_speed_run", "mud_water_run", "lit_tunnel", "speed_action", "rough_motion"}):
        signature.append("action")
    return tuple(signature)


def selected_timeline_overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / max(1, len(left.union(right)))


def selected_timeline_preserve_selection(config: Config, selection: ReelSelection) -> bool:
    preserve_tags = set(
        str(item)
        for item in config_value(
            config,
            "selected_timeline.diversity_filter.preserve_high_value_tags",
            [
                "water_speed_run",
                "mud_water_run",
                "lit_tunnel",
                "pool_action",
                "swimming",
                "pool_jump",
                "splash",
                "rapids",
                "waterfall",
                "architecture",
                "food",
                "dancing",
                "sunset",
            ],
        )
    )
    tags = selected_timeline_tag_set(selection)
    if tags.intersection(preserve_tags):
        return True
    memory_profiles = {"stay", "beach", "restaurants", "savaya", "clubbing"}
    candidate_profile = (selection.candidate.media_set or selection.candidate.activity or "").lower()
    if (
        candidate_profile in memory_profiles
        and selection.candidate.final_reel_score >= 82
        and selection.candidate.activity_confidence >= 80
        and tags.intersection({"pool", "water", "scenic", "landscape", "group_reaction", "face_visible", "people_visible"})
    ):
        return True
    return False


def selected_timeline_has_face(selection: ReelSelection) -> bool:
    return bool(selected_timeline_tag_set(selection).intersection({"face_visible", "people_visible", "group_reaction"}))


def selected_timeline_activity_event_tags(selection: ReelSelection) -> set[str]:
    event_tags = {
        "water_speed_run",
        "mud_water_run",
        "lit_tunnel",
        "tunnel_or_shade",
        "speed_action",
        "rough_motion",
        "splash",
        "rapids",
        "river_scene",
        "river_people",
        "pool_action",
        "swimming",
        "pool_jump",
    }
    tags = selected_timeline_tag_set(selection)
    if selection.candidate.activity.lower() in {"rafting", "atv"} or selection.candidate.media_set.lower() in {"rafting", "atv"}:
        event_tags.add("water_crossing")
    return tags.intersection(event_tags)


def selected_timeline_person_without_face_reject(
    config: Config,
    project_root: Path,
    timeline_config: ReelConfig,
    selection: ReelSelection,
    semantic_cache: dict[str, Any] | None,
) -> bool:
    if not selected_timeline_face_filter_enabled(config) or selected_timeline_has_face(selection):
        return False
    if selected_timeline_activity_event_tags(selection) and parse_enabled(
        config_value(config, "selected_timeline.face_filter.preserve_activity_events", True),
        "selected_timeline.face_filter.preserve_activity_events",
    ):
        return False
    text = selected_timeline_candidate_text(selection.candidate)
    person_terms = ("person", "people", "friend", "friends", "group", "selfie", "portrait", "standing")
    if any(term in text for term in person_terms):
        return True
    if not semantic_cache or not selected_timeline_semantic_similarity_enabled(config):
        return False
    scores = selected_timeline_person_focus_scores(config, project_root, timeline_config, selection, semantic_cache)
    if not scores:
        return False
    margin = float(config_value(config, "selected_timeline.face_filter.person_focus_margin", 0.035))
    minimum = float(config_value(config, "selected_timeline.face_filter.person_focus_min_score", 0.20))
    return scores["person"] >= minimum and scores["person"] - scores["scene"] >= margin


def selected_timeline_person_focus_scores(
    config: Config,
    project_root: Path,
    timeline_config: ReelConfig,
    selection: ReelSelection,
    semantic_cache: dict[str, Any],
) -> dict[str, float]:
    image_embedding = selected_timeline_clip_embedding(config, project_root, timeline_config, selection, semantic_cache)
    if not image_embedding:
        return {}
    person_prompts = [
        "a video frame focused on a person",
        "a person standing with their back to the camera",
        "people standing in the scene",
        "friends on vacation from behind",
        "a close view of a person without a visible face",
        "a single person standing in water",
        "a person standing in shallow water",
        "a person walking in the ocean",
        "a full body person standing outdoors",
        "a person posing in a landscape",
    ]
    scene_prompts = [
        "a wide scenic landscape without people",
        "a beach ocean landscape",
        "a temple or architecture scene without people",
        "food on a table without people",
        "a waterfall or rice field landscape",
    ]
    person_scores = [cosine_similarity(image_embedding, embedding) for embedding in openclip_text_embeddings(config, person_prompts)]
    scene_scores = [cosine_similarity(image_embedding, embedding) for embedding in openclip_text_embeddings(config, scene_prompts)]
    if not person_scores or not scene_scores:
        return {}
    return {"person": max(person_scores), "scene": max(scene_scores)}


def selected_timeline_repetition_reason(
    config: Config,
    project_root: Path,
    timeline_config: ReelConfig,
    selection: ReelSelection,
    recent: list[ReelSelection],
    semantic_cache: dict[str, Any] | None = None,
) -> str:
    max_similar = int(config_value(config, "selected_timeline.diversity_filter.max_similar_visual_runs", 2))
    overlap_threshold = float(config_value(config, "selected_timeline.diversity_filter.similar_tag_overlap_threshold", 0.72))
    visual = selected_timeline_visual_signature(selection)
    background = selected_timeline_background_signature(selection)
    layout = selected_timeline_layout_signature(selection)
    similar_count = 0
    for existing in recent[-max(1, max_similar) :]:
        existing_visual = selected_timeline_visual_signature(existing)
        existing_background = selected_timeline_background_signature(existing)
        existing_layout = selected_timeline_layout_signature(existing)
        visual_overlap = selected_timeline_overlap(visual, existing_visual)
        background_overlap = selected_timeline_overlap(background, existing_background)
        if layout and existing_layout and layout == existing_layout and max(visual_overlap, background_overlap) >= overlap_threshold:
            similar_count += 1
        elif background and background_overlap >= overlap_threshold and selected_timeline_tag_set(selection).intersection({"face_visible", "people_visible"}):
            similar_count += 1
    if similar_count >= max_similar:
        return f"similar visual/background signature repeated {similar_count + 1} times"
    semantic_reason = selected_timeline_semantic_repetition_reason(config, project_root, timeline_config, selection, recent, semantic_cache)
    if semantic_reason:
        return semantic_reason
    return ""


def selected_timeline_semantic_repetition_reason(
    config: Config,
    project_root: Path,
    timeline_config: ReelConfig,
    selection: ReelSelection,
    recent: list[ReelSelection],
    semantic_cache: dict[str, Any] | None,
) -> str:
    if not semantic_cache or not selected_timeline_semantic_similarity_enabled(config):
        return ""
    embedding = selected_timeline_clip_embedding(config, project_root, timeline_config, selection, semantic_cache)
    if not embedding:
        return ""
    threshold = float(config_value(config, "selected_timeline.semantic_similarity.threshold", 0.91))
    recent_window = int(config_value(config, "selected_timeline.semantic_similarity.recent_window", 6))
    for existing in recent[-max(1, recent_window) :]:
        existing_embedding = selected_timeline_clip_embedding(config, project_root, timeline_config, existing, semantic_cache)
        if not existing_embedding:
            continue
        similarity = cosine_similarity(embedding, existing_embedding)
        if similarity >= threshold:
            return f"OpenCLIP visual similarity {similarity:.3f}"
    return ""


def selected_timeline_clip_embedding(
    config: Config,
    project_root: Path,
    timeline_config: ReelConfig,
    selection: ReelSelection,
    semantic_cache: dict[str, Any],
) -> list[float]:
    candidate = selection.candidate
    source_path = resolve_project_path(project_root, candidate.source_media_path)
    cache_key = selected_timeline_embedding_cache_key(config, source_path, candidate.segment_start_seconds, candidate.segment_end_seconds)
    cached = semantic_cache.get("embeddings", {}).get(cache_key)
    if isinstance(cached, list):
        return [float(value) for value in cached]
    embedding = compute_openclip_embedding(config, source_path, candidate.segment_start_seconds, candidate.segment_end_seconds)
    if embedding:
        semantic_cache.setdefault("embeddings", {})[cache_key] = embedding
        semantic_cache["dirty"] = True
    return embedding


def selected_timeline_embedding_cache_key(config: Config, source_path: Path, start_seconds: float, end_seconds: float) -> str:
    model_name = str(config_value(config, "selected_timeline.semantic_similarity.model", "ViT-B-32"))
    pretrained = str(config_value(config, "selected_timeline.semantic_similarity.pretrained", "openai"))
    try:
        stat = source_path.stat()
        identity = f"{source_path}|{stat.st_size}|{stat.st_mtime_ns}|{start_seconds:.3f}|{end_seconds:.3f}|{model_name}|{pretrained}"
    except OSError:
        identity = f"{source_path}|missing|{start_seconds:.3f}|{end_seconds:.3f}|{model_name}|{pretrained}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def compute_openclip_embedding(config: Config, source_path: Path, start_seconds: float, end_seconds: float) -> list[float]:
    state = openclip_state(config)
    if not state:
        return []
    try:
        import cv2  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return []
    frames = sample_video_frames(cv2, source_path, start_seconds, end_seconds, int(config_value(config, "selected_timeline.semantic_similarity.sample_frames", 3)))
    if not frames:
        return []
    images = []
    for frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        images.append(state["preprocess"](Image.fromarray(rgb)))
    if not images:
        return []
    device = state["device"]
    model = state["model"]
    with torch.no_grad():
        batch = torch.stack(images).to(device)
        features = model.encode_image(batch)
        features = features / features.norm(dim=-1, keepdim=True)
        vector = features.mean(dim=0)
        vector = vector / vector.norm()
    return [round(float(value), 6) for value in vector.detach().cpu().tolist()]


def openclip_state(config: Config) -> dict[str, Any]:
    if OPENCLIP_STATE.get("disabled"):
        return {}
    key = (
        str(config_value(config, "selected_timeline.semantic_similarity.model", "ViT-B-32")),
        str(config_value(config, "selected_timeline.semantic_similarity.pretrained", "openai")),
        str(config_value(config, "selected_timeline.semantic_similarity.device", "auto")),
        str(config_value(config, "selected_timeline.semantic_similarity.checkpoint_path", "") or ""),
    )
    if OPENCLIP_STATE.get("key") == key and OPENCLIP_STATE.get("model") is not None:
        return OPENCLIP_STATE
    try:
        if parse_enabled(config_value(config, "selected_timeline.semantic_similarity.disable_implicit_hf_token", True), "selected_timeline.semantic_similarity.disable_implicit_hf_token"):
            os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
        import open_clip  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
    except ImportError:
        OPENCLIP_STATE["disabled"] = True
        return {}
    device_setting = key[2]
    if device_setting == "auto":
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
    else:
        device = device_setting
    try:
        pretrained: str | None = key[1]
        checkpoint_path = key[3]
        if checkpoint_path:
            checkpoint = Path(checkpoint_path).expanduser()
            if checkpoint.exists():
                pretrained = checkpoint.as_posix()
        model, _, preprocess = open_clip.create_model_and_transforms(key[0], pretrained=pretrained, device=device)
        tokenizer = open_clip.get_tokenizer(key[0])
        model.eval()
    except Exception:
        OPENCLIP_STATE["disabled"] = True
        return {}
    OPENCLIP_STATE.clear()
    OPENCLIP_STATE.update({"key": key, "model": model, "preprocess": preprocess, "tokenizer": tokenizer, "text_embeddings": {}, "device": device})
    return OPENCLIP_STATE


def openclip_text_embeddings(config: Config, prompts: list[str]) -> list[list[float]]:
    state = openclip_state(config)
    if not state:
        return []
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return []
    model = state["model"]
    tokenizer = state["tokenizer"]
    device = state["device"]
    cache = state.setdefault("text_embeddings", {})
    missing = [prompt for prompt in prompts if prompt not in cache]
    if missing:
        with torch.no_grad():
            tokens = tokenizer(missing).to(device)
            features = model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        for prompt, vector in zip(missing, features.detach().cpu().tolist(), strict=False):
            cache[prompt] = [round(float(value), 6) for value in vector]
    return [cache[prompt] for prompt in prompts if prompt in cache]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def load_selected_timeline_semantic_cache(config: Config, output_dir: Path) -> dict[str, Any]:
    cache_path = output_dir / str(config_value(config, "selected_timeline.semantic_similarity.cache_file", "semantic_embedding_cache.json"))
    cache: dict[str, Any] = {"path": cache_path, "embeddings": {}, "dirty": False}
    if not selected_timeline_semantic_similarity_enabled(config) or not cache_path.exists():
        return cache
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cache
    embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
    if isinstance(embeddings, dict):
        cache["embeddings"] = embeddings
    return cache


def save_selected_timeline_semantic_cache(cache: dict[str, Any]) -> None:
    if not cache.get("dirty"):
        return
    cache_path = cache.get("path")
    if not isinstance(cache_path, Path):
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"embeddings": cache.get("embeddings", {})}
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def resequence_selected_timeline(selections: list[ReelSelection]) -> list[ReelSelection]:
    resequenced: list[ReelSelection] = []
    output_cursor = 0.0
    for index, selection in enumerate(selections, start=1):
        start = output_cursor
        end = start + selection.candidate.segment_duration_seconds
        resequenced.append(
            ReelSelection(
                candidate=selection.candidate,
                sequence=index,
                output_start_seconds=round(start, 3),
                output_end_seconds=round(end, 3),
                selection_reason=selection.selection_reason,
            )
        )
        output_cursor = end
    return resequenced


def reduce_repetitive_selected_timeline(
    config: Config,
    project_root: Path,
    timeline_config: ReelConfig,
    selections: list[ReelSelection],
) -> list[ReelSelection]:
    if not selections or not selected_timeline_diversity_enabled(config):
        return selections
    semantic_cache = load_selected_timeline_semantic_cache(config, timeline_config.output_dir)
    min_duration_fraction = float(config_value(config, "selected_timeline.diversity_filter.min_duration_fraction", 0.45))
    total_duration = sum(selection.candidate.segment_duration_seconds for selection in selections)
    minimum_duration = max(8.0, total_duration * min_duration_fraction)
    kept: list[ReelSelection] = []
    dropped_duration = 0.0
    for selection in selections:
        preserved = selected_timeline_preserve_selection(config, selection)
        if preserved:
            kept.append(selection)
            continue
        if selected_timeline_person_without_face_reject(config, project_root, timeline_config, selection, semantic_cache):
            dropped_duration += selection.candidate.segment_duration_seconds
            continue
        remaining_if_dropped = total_duration - dropped_duration - selection.candidate.segment_duration_seconds
        if remaining_if_dropped < minimum_duration:
            kept.append(selection)
            continue
        reason = selected_timeline_repetition_reason(config, project_root, timeline_config, selection, kept, semantic_cache)
        if reason and selection.candidate.final_reel_score < float(config_value(config, "selected_timeline.diversity_filter.preserve_score_threshold", 92)):
            dropped_duration += selection.candidate.segment_duration_seconds
            continue
        kept.append(selection)
    save_selected_timeline_semantic_cache(semantic_cache)
    return resequence_selected_timeline(kept)


def selected_timeline_output_file(config: ReelConfig) -> Path:
    return config.exports_dir / f"{config.reel_id}_master_16x9.mp4"


def write_selected_timeline_reports(
    config: ReelConfig,
    project_root: Path,
    candidates: list,
    selections: list,
    rendered_file: Path,
    render_status: str,
    render_reason: str,
) -> tuple[Path, Path, Path, Path, Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    candidates_csv = config.output_dir / "selected_timeline_candidates.csv"
    timeline_csv = config.output_dir / "selected_timeline.csv"
    edit_decisions_csv = config.output_dir / "selected_timeline_edit_decisions.csv"
    manifest_csv = config.output_dir / "selected_timeline_manifest.csv"
    report_md = config.output_dir / "selected_timeline_report.md"
    selected_keys = {
        (selection.candidate.source_media_path, selection.candidate.segment_start_seconds, selection.candidate.segment_end_seconds)
        for selection in selections
    }
    write_csv(candidates_csv, REEL_CANDIDATE_COLUMNS, [candidate_row(candidate, selected_keys) for candidate in candidates])
    write_csv(timeline_csv, REEL_HIGHLIGHT_TIMELINE_COLUMNS, [highlight_timeline_row(selection) for selection in selections])
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
                "selection_path": path_text(timeline_csv, project_root),
                "report_path": path_text(report_md, project_root),
                "dry_run": "yes" if config.dry_run else "no",
                "created_at": "",
                "render_status": render_status,
                "render_reason": render_reason,
            }
        ],
    )
    write_selected_timeline_markdown(config, project_root, candidates, selections, rendered_file, render_status, render_reason, report_md)
    return candidates_csv, timeline_csv, edit_decisions_csv, manifest_csv, report_md


def write_selected_timeline_markdown(
    config: ReelConfig,
    project_root: Path,
    candidates: list,
    selections: list,
    rendered_file: Path,
    render_status: str,
    render_reason: str,
    report_md: Path,
) -> None:
    tag_counts: dict[str, int] = {}
    for selection in selections:
        for tag in selection.candidate.visual_tags.split(","):
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    lines = [
        "# Selected Timeline Report",
        "",
        f"- Activity: {', '.join(sorted(config.media_sets))}",
        f"- Activity profile: {config.activity_profile.name}",
        f"- Candidates: {len(candidates)}",
        f"- Selected timeline segments: {len(selections)}",
        f"- Planned duration: {sum(selection.candidate.segment_duration_seconds for selection in selections):.1f}s",
        f"- Render status: {render_status}",
        f"- Render reason: {render_reason}",
        f"- Output: {path_text(rendered_file, project_root) if rendered_file else ''}",
        "",
        "## Visual Coverage",
        "",
    ]
    lines.extend(f"- {tag}: {count}" for tag, count in sorted(tag_counts.items()))
    lines.extend(["", "## Timeline", ""])
    for selection in selections:
        candidate = selection.candidate
        lines.append(
            f"- {selection.sequence:03d}. {candidate.source_media_path} "
            f"{candidate.segment_start_seconds:.1f}-{candidate.segment_end_seconds:.1f}s "
            f"score={candidate.final_reel_score} tags={candidate.visual_tags}"
        )
    report_md.write_text("\n".join(lines), encoding="utf-8")


def run_selected_timeline(
    config: Config,
    project_root: Path,
    include_disabled: bool = False,
    execute: bool = False,
) -> list[SelectedTimelineResult]:
    if not selected_timeline_enabled(config) and not include_disabled:
        raise ValueError("Selected Timeline is disabled in config. Enable modules.selected_timeline.enabled or pass --include-disabled.")
    base = load_reel_config(config, project_root)
    if execute:
        base = replace(base, dry_run=False)
    configured_sets = configured_media_sets(config, include_disabled=include_disabled)
    configured_media_set_filter = parse_media_sets(config_value(config, "selected_timeline.media_sets", []))
    selected_sets = sorted(configured_media_set_filter or base.media_sets) if (configured_media_set_filter or base.media_sets) else [item.name for item in configured_sets]
    load_source_chronology_index(config, project_root, set(selected_sets))

    def build_activity_timeline(media_set: str) -> SelectedTimelineResult:
        timeline_config = selected_timeline_config(config, project_root, base, media_set)
        cache_file = timeline_config.output_dir / "segment_audit_cache.json"
        load_segment_audit_cache(cache_file)
        candidates = build_candidates(timeline_config, project_root)
        cache_entries = save_segment_audit_cache(cache_file)
        selections = select_master_highlight(timeline_config, candidates)
        selections = reduce_repetitive_selected_timeline(config, project_root, timeline_config, selections)
        rendered_file = selected_timeline_output_file(timeline_config)
        render_status, render_reason, rendered_count = render_reel(timeline_config, project_root, selections, rendered_file)
        candidates_csv, timeline_csv, edit_decisions_csv, manifest_csv, report_md = write_selected_timeline_reports(
            timeline_config,
            project_root,
            candidates,
            selections,
            rendered_file,
            render_status,
            render_reason,
        )
        return SelectedTimelineResult(
            activity=media_set,
            candidate_count=len(candidates),
            selected_count=len(selections),
            actual_duration_seconds=round(sum(selection.candidate.segment_duration_seconds for selection in selections), 3),
            rendered_count=rendered_count,
            render_status=render_status,
            rendered_file_path=rendered_file,
            candidates_csv=candidates_csv,
            selected_timeline_csv=timeline_csv,
            edit_decisions_csv=edit_decisions_csv,
            manifest_csv=manifest_csv,
            report_md=report_md,
            cache_file=cache_file,
            cache_entries=cache_entries,
            dry_run=timeline_config.dry_run,
        )

    return ordered_map(config, "selected_timeline", build_activity_timeline, selected_sets)
