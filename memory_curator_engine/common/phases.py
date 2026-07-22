"""Workflow phase definitions for MemoryCurator projects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseDefinition:
    number: int
    command: str
    config_key: str
    title: str
    workflow_dir: str
    implemented: bool = False


PHASES = [
    PhaseDefinition(1, "inventory", "inventory", "Inventory", "MemoryCurator/01 Inventory", implemented=True),
    PhaseDefinition(2, "duplicate-detection", "duplicate_detection", "Duplicate Detection", "MemoryCurator/02 Duplicate Detection", implemented=True),
    PhaseDefinition(3, "quality-scoring", "quality_scoring", "Quality Scoring", "MemoryCurator/03 Quality Scoring", implemented=True),
    PhaseDefinition(4, "media-intelligence", "media_intelligence", "Media Intelligence", "MemoryCurator/04 Media Intelligence"),
    PhaseDefinition(5, "story-builder", "story_builder", "Story Builder", "MemoryCurator/05 Story Builder", implemented=True),
    PhaseDefinition(6, "album-builder", "album_builder", "Album Builder", "MemoryCurator/06 Album Builder", implemented=True),
    PhaseDefinition(7, "video-processing", "video_processing", "Video Processing", "MemoryCurator/07 Video Processing", implemented=True),
    PhaseDefinition(8, "selected-timeline", "selected_timeline", "Selected Timeline", "MemoryCurator/08 Selected Timeline", implemented=True),
    PhaseDefinition(9, "reel-builder", "reel_builder", "Reel Builder", "MemoryCurator/09 Reel Builder", implemented=True),
    PhaseDefinition(10, "documentary-builder", "documentary_builder", "Documentary Builder", "MemoryCurator/10 Documentary Builder", implemented=True),
    PhaseDefinition(11, "time-capsule", "time_capsule", "Time Capsule", "MemoryCurator/11 Time Capsule"),
]

PHASES_BY_COMMAND = {phase.command: phase for phase in PHASES}


def phase_help() -> str:
    return "\n".join(f"{phase.command:22} Run phase {phase.number:02d}: {phase.title}" for phase in PHASES)
