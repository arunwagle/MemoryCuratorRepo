"""Activity profiles and purpose-aware scoring helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_curator_engine.common.config import Config, config_value


@dataclass(frozen=True)
class ActivityProfile:
    name: str
    optimization_goal: str
    opening_duration_seconds: float
    ending_duration_seconds: float
    middle_min_fraction: float
    maximize: list[str]
    minimize: list[str]
    required_context: list[str]
    reject_context: list[str]
    essence_chapters: dict[str, list[str]]
    reel_weights: dict[str, float]
    moment_weights: dict[str, float]


def load_activity_profile(config: Config, profile_name: str | None) -> ActivityProfile:
    name = (profile_name or "default").strip() or "default"
    profile = config_value(config, f"activity_profiles.{name}", {}) or {}
    default = default_activity_profile(name)
    return ActivityProfile(
        name=name,
        optimization_goal=str(profile.get("optimization_goal", default.optimization_goal)),
        opening_duration_seconds=float(profile.get("opening_duration_seconds", default.opening_duration_seconds)),
        ending_duration_seconds=float(profile.get("ending_duration_seconds", default.ending_duration_seconds)),
        middle_min_fraction=float(profile.get("middle_min_fraction", default.middle_min_fraction)),
        maximize=parse_list(profile.get("maximize", default.maximize)),
        minimize=parse_list(profile.get("minimize", default.minimize)),
        required_context=parse_list(profile.get("required_context", default.required_context)),
        reject_context=parse_list(profile.get("reject_context", default.reject_context)),
        essence_chapters=parse_chapter_map(profile.get("essence_chapters", default.essence_chapters), default.essence_chapters),
        reel_weights=parse_weight_map(profile.get("reel_weights", default.reel_weights), default.reel_weights),
        moment_weights=parse_weight_map(profile.get("moment_weights", default.moment_weights), default.moment_weights),
    )


def default_activity_profile(name: str) -> ActivityProfile:
    if name == "rafting":
        return ActivityProfile(
            name="rafting",
            optimization_goal="adventure",
            opening_duration_seconds=5.0,
            ending_duration_seconds=5.0,
            middle_min_fraction=0.82,
            maximize=["action", "water", "rapids", "splash", "excitement", "gopro", "group_reactions"],
            minimize=["static", "waiting", "walking", "talking", "parking", "meal"],
            required_context=["rafting", "river", "water", "rapid", "splash", "paddle", "raft", "gopro", "gx", "helmet"],
            reject_context=["atv", "quad", "temple", "restaurant", "beach", "pool", "villa"],
            essence_chapters={
                "setup": ["arrival", "gear", "helmet", "walk", "briefing"],
                "launch": ["launch", "raft", "river"],
                "rapids": ["rapid", "splash", "water", "action", "gopro"],
                "reaction": ["group", "reaction", "laugh", "cheer", "people"],
                "closing": ["group", "photo", "ending", "return"],
            },
            reel_weights={
                "activity": 0.45,
                "adventure": 0.25,
                "emotion": 0.15,
                "story": 0.10,
                "technical": 0.03,
                "diversity": 0.02,
            },
            moment_weights={
                "arrival": 0.25,
                "safety_briefing": 0.12,
                "gear_up": 0.20,
                "walk_to_start": 0.30,
                "launch": 0.78,
                "calm_river": 0.55,
                "rapids": 1.00,
                "water_action": 1.00,
                "splash": 1.00,
                "group_photo": 0.45,
                "meal": 0.10,
                "return_trip": 0.08,
                "travel_to_activity": 0.08,
                "transition": 0.30,
                "other": 0.30,
            },
        )
    return ActivityProfile(
        name=name,
        optimization_goal="balanced",
        opening_duration_seconds=5.0,
        ending_duration_seconds=5.0,
        middle_min_fraction=0.60,
        maximize=["story", "emotion", "people", "action"],
        minimize=["static", "duplicates", "waiting"],
        required_context=[],
        reject_context=[],
        essence_chapters={},
        reel_weights={
            "activity": 0.35,
            "adventure": 0.20,
            "emotion": 0.15,
            "story": 0.15,
            "technical": 0.10,
            "diversity": 0.05,
        },
        moment_weights={},
    )


def parse_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def parse_weight_map(value: Any, default: dict[str, float]) -> dict[str, float]:
    if not isinstance(value, dict):
        return dict(default)
    parsed = dict(default)
    for key, raw in value.items():
        try:
            parsed[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return parsed


def parse_chapter_map(value: Any, default: dict[str, list[str]]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {str(key): list(values) for key, values in default.items()}
    parsed = {str(key): list(values) for key, values in default.items()}
    for key, raw in value.items():
        parsed[str(key)] = parse_list(raw)
    return parsed


def clamp_score(value: float) -> float:
    return max(0.0, min(value, 100.0))


def source_camera_score(path: str | Path) -> float:
    name = Path(path).name.lower()
    if name.startswith("gx") or "gopro" in name or name.startswith("gopr"):
        return 100.0
    if name.startswith("img_") and name.endswith(".mov"):
        return 72.0
    if "meta" in name:
        return 70.0
    return 55.0


def profile_term_matches(term: str, text: str) -> bool:
    aliases = {
        "group_reactions": ["group", "reaction", "cheer", "laugh", "scream", "people"],
        "gopro": ["gopro", "gopr", "gx", "pov"],
        "helmet_cam": ["helmet", "helmet cam", "pov", "gopro", "gopr", "gx"],
        "rapids": ["rapid", "rapids"],
        "excitement": ["excite", "cheer", "laugh", "scream", "reaction"],
        "static": ["static", "still", "photo", "low_motion"],
        "walking": ["walk", "walking"],
        "talking": ["talk", "conversation", "briefing"],
        "water": ["water", "river", "splash"],
        "mud": ["mud", "muddy"],
        "trail": ["trail", "jungle", "path", "ride"],
        "water_crossing": ["water crossing", "water", "splash", "puddle"],
        "swimming": ["swim", "swimming", "pool", "water"],
        "pool_action": ["pool action", "pool", "swim", "splash", "jump"],
        "pool_jump": ["pool jump", "diving", "dive", "jump", "splash"],
        "diving": ["diving", "dive", "jump", "pool jump", "splash"],
        "slope": ["slope", "hill", "climb", "descent", "downhill", "uphill"],
        "tunnel": ["tunnel", "underpass", "narrow"],
        "turns": ["turn", "turns", "curve", "fast turns"],
        "speed": ["speed", "fast", "motion", "action"],
        "quad": ["quad", "atv", "ride"],
    }
    needles = aliases.get(term, [term.replace("_", " ")])
    return any(needle in text for needle in needles)


def activity_bucket(profile: ActivityProfile, moment_type: str, role: str = "") -> str:
    if moment_type in {"arrival", "safety_briefing", "gear_up", "walk_to_start"} or role in {"hook", "setup"}:
        return "opening"
    if moment_type in {"group_photo", "meal", "return_trip"} or role == "closing":
        return "ending"
    return "middle"


def activity_fit_score(
    profile: ActivityProfile,
    *,
    path: str | Path,
    moment_type: str = "",
    role: str = "",
    technical_score: float = 50.0,
    motion_score: float = 50.0,
    audio_score: float = 50.0,
    story_score: float = 50.0,
    people_score: float = 50.0,
    text: str = "",
) -> tuple[float, str]:
    blob = f"{Path(path).name.lower()} {moment_type} {role} {text.lower()}"
    maximize_hits = [term for term in profile.maximize if profile_term_matches(term, blob)]
    minimize_hits = [term for term in profile.minimize if profile_term_matches(term, blob)]
    moment_component = profile.moment_weights.get(moment_type, 0.45) * 100
    camera = source_camera_score(path)
    role_component = 100 if role in {"action", "group_action"} else 78 if role == "reaction" else 55
    score = (
        moment_component * 0.22
        + motion_score * 0.20
        + audio_score * 0.16
        + story_score * 0.14
        + technical_score * 0.10
        + people_score * 0.08
        + role_component * 0.05
        + camera * 0.05
    )
    score += min(len(maximize_hits) * 6, 24)
    score -= min(len(minimize_hits) * 8, 28)
    if profile.optimization_goal == "adventure" and moment_type in {"launch", "rapids", "water_action", "splash"}:
        score += 10
    reason = f"profile={profile.name}; bucket={activity_bucket(profile, moment_type, role)}"
    if maximize_hits:
        reason += f"; maximize={','.join(maximize_hits[:4])}"
    if minimize_hits:
        reason += f"; minimize={','.join(minimize_hits[:4])}"
    return clamp_score(score), reason


def purpose_scores(
    profile: ActivityProfile,
    *,
    path: str | Path,
    media_kind: str,
    technical_score: float,
    quality_score: float,
    album_score: float,
    instagram_score: float,
    movie_score: float,
    motion_score: float,
    stability_score: float,
    duration_seconds: float,
    moment_type: str = "",
    role: str = "",
    story_score: float = 50.0,
    people_score: float = 50.0,
    audio_score: float = 50.0,
    text: str = "",
) -> dict[str, float | str]:
    fit, reason = activity_fit_score(
        profile,
        path=path,
        moment_type=moment_type,
        role=role,
        technical_score=technical_score,
        motion_score=motion_score,
        audio_score=audio_score,
        story_score=story_score,
        people_score=people_score,
        text=text,
    )
    if media_kind == "video":
        duration_component = clamp_score((duration_seconds / 20) * 100)
        reel = clamp_score(fit * 0.48 + motion_score * 0.18 + audio_score * 0.12 + instagram_score * 0.12 + technical_score * 0.10)
        documentary = clamp_score(movie_score * 0.28 + fit * 0.24 + story_score * 0.24 + duration_component * 0.14 + stability_score * 0.10)
        time_capsule = clamp_score(max(quality_score, fit) * 0.45 + story_score * 0.25 + duration_component * 0.20 + people_score * 0.10)
    else:
        reel = clamp_score(instagram_score * 0.40 + fit * 0.25 + people_score * 0.20 + technical_score * 0.15)
        documentary = clamp_score(movie_score * 0.35 + story_score * 0.30 + fit * 0.20 + technical_score * 0.15)
        time_capsule = clamp_score(max(quality_score, album_score, fit) * 0.60 + story_score * 0.25 + people_score * 0.15)
    album = clamp_score(album_score * 0.55 + people_score * 0.25 + technical_score * 0.20)
    return {
        "activity_score": round(fit, 2),
        "album_purpose_score": round(album, 2),
        "reel_purpose_score": round(reel, 2),
        "documentary_purpose_score": round(documentary, 2),
        "time_capsule_purpose_score": round(time_capsule, 2),
        "activity_reason": reason,
    }
