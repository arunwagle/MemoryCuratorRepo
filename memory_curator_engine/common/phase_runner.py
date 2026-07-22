"""Generic phase runner helpers."""

from __future__ import annotations

from pathlib import Path

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.phases import PhaseDefinition
from memory_curator_engine.common.paths import resolve_project_path


def module_enabled(config: Config, phase: PhaseDefinition) -> bool:
    return bool(config_value(config, f"modules.{phase.config_key}.enabled", False))


def ensure_workflow_dir(config: Config, project_root: Path, phase: PhaseDefinition) -> Path:
    workflow_root = config_value(config, "project.workflow_root", "MemoryCurator")
    relative_dir = Path(phase.workflow_dir)
    if relative_dir.parts and relative_dir.parts[0] == "MemoryCurator":
        relative_dir = Path(*relative_dir.parts[1:])
    output_dir = resolve_project_path(project_root, Path(workflow_root) / relative_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def run_placeholder_phase(
    config: Config,
    project_root: Path,
    phase: PhaseDefinition,
    include_disabled: bool = False,
) -> tuple[bool, str]:
    if not module_enabled(config, phase) and not include_disabled:
        return False, f"[{phase.command}] Skipped because modules.{phase.config_key}.enabled is no."

    output_dir = ensure_workflow_dir(config=config, project_root=project_root, phase=phase)
    return False, f"[{phase.command}] Phase {phase.number:02d} ({phase.title}) is configured at {output_dir}, but is not implemented yet."
