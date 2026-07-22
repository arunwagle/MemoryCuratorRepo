"""Helpers for trip media set/activity configuration."""

from __future__ import annotations

from dataclasses import dataclass

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.inventory.report import parse_enabled


@dataclass(frozen=True)
class MediaSetActivity:
    name: str
    activity_name: str
    activity_profile: str
    enabled: bool


def configured_media_sets(config: Config, include_disabled: bool = False) -> list[MediaSetActivity]:
    media_sets = config_value(config, "inventory.media_sets", {}) or {}
    if not isinstance(media_sets, dict):
        return []
    items: list[MediaSetActivity] = []
    for name, values in media_sets.items():
        section = values if isinstance(values, dict) else {}
        enabled = parse_enabled(section.get("enabled", False), f"inventory.media_sets.{name}.enabled")
        if not enabled and not include_disabled:
            continue
        activity_profile = str(section.get("activity_profile") or name)
        activity_name = str(section.get("activity_name") or name.replace("_", " ").title())
        items.append(
            MediaSetActivity(
                name=str(name),
                activity_name=activity_name,
                activity_profile=activity_profile,
                enabled=enabled,
            )
        )
    return sorted(items, key=lambda item: item.name)


def media_set_activity_map(config: Config, include_disabled: bool = True) -> dict[str, MediaSetActivity]:
    return {item.name: item for item in configured_media_sets(config, include_disabled=include_disabled)}
