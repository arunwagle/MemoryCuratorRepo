"""Project-level reset support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.paths import resolve_project_path


@dataclass(frozen=True)
class RestorePlanItem:
    source: Path
    destination: Path


@dataclass(frozen=True)
class ResetResult:
    dry_run: bool
    review_file_count: int
    restorable_count: int
    restored_count: int
    blocked_count: int
    generated_file_count: int
    removed_generated_file_count: int
    workflow_root: Path
    generated_roots: list[Path]


def workflow_root_from_config(config: Config, project_root: Path) -> Path:
    return resolve_project_path(project_root, config_value(config, "project.workflow_root", "MemoryCurator"))


def curated_root_from_config(config: Config, project_root: Path) -> Path | None:
    value = config_value(config, "project.curated_root")
    if not value:
        return None
    return resolve_project_path(project_root, value)


def generated_roots_from_config(config: Config, project_root: Path) -> list[Path]:
    roots = [workflow_root_from_config(config, project_root)]
    curated_root = curated_root_from_config(config, project_root)
    if curated_root is not None:
        roots.append(curated_root)
    return roots


def duplicate_review_dir_from_config(config: Config, project_root: Path) -> Path:
    return resolve_project_path(
        project_root,
        config_value(config, "duplicate_detection.review_dir", "MemoryCurator/02 Duplicate Detection/review_duplicates"),
    )


def quality_selected_dir_from_config(config: Config, project_root: Path) -> Path:
    return resolve_project_path(
        project_root,
        config_value(config, "quality_scoring.selected_dir", "MemoryCurator/03 Quality Scoring/selected_quality"),
    )


def reversible_move_roots_from_config(config: Config, project_root: Path) -> list[Path]:
    return [
        duplicate_review_dir_from_config(config, project_root),
        quality_selected_dir_from_config(config, project_root),
    ]


def iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def restore_destination_for_moved_file(project_root: Path, move_root: Path, moved_file: Path) -> Path:
    relative_to_review = moved_file.relative_to(move_root)
    parts = relative_to_review.parts
    if len(parts) < 2:
        raise ValueError(f"Moved file is not inside a media-set restore path: {moved_file}")
    destination = project_root / Path(*parts[1:])
    try:
        destination.resolve().relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"Moved file would restore outside the project: {moved_file}") from exc
    return destination


def build_restore_plan(config: Config, project_root: Path) -> tuple[list[RestorePlanItem], list[Path], int]:
    restorable: list[RestorePlanItem] = []
    blocked: list[Path] = []
    moved_file_count = 0

    for move_root in reversible_move_roots_from_config(config, project_root):
        for moved_file in iter_files(move_root):
            moved_file_count += 1
            destination = restore_destination_for_moved_file(project_root, move_root, moved_file)
            if destination.exists():
                blocked.append(destination)
                continue
            restorable.append(RestorePlanItem(source=moved_file, destination=destination))

    return restorable, blocked, moved_file_count


def workflow_cleanup_files(generated_roots: list[Path], restore_plan: list[RestorePlanItem]) -> list[Path]:
    restore_sources = {item.source for item in restore_plan}
    cleanup_files: list[Path] = []
    for root in generated_roots:
        cleanup_files.extend(path for path in iter_files(root) if path not in restore_sources)
    return sorted(set(cleanup_files))


def cleanup_empty_directories(start: Path, stop_at: Path) -> None:
    current = start
    while current != stop_at and stop_at in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def run_reset(config: Config, project_root: Path, execute: bool = False) -> ResetResult:
    workflow_root = workflow_root_from_config(config, project_root)
    generated_roots = generated_roots_from_config(config, project_root)
    restore_plan, blocked, review_file_count = build_restore_plan(config, project_root)
    cleanup_files = workflow_cleanup_files(generated_roots, restore_plan)

    if execute and blocked:
        preview = "\n".join(str(path) for path in blocked[:10])
        suffix = "\n..." if len(blocked) > 10 else ""
        raise FileExistsError(f"Cannot reset because destination files already exist:\n{preview}{suffix}")

    restored_count = 0
    removed_generated_file_count = 0

    if execute:
        for item in restore_plan:
            item.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item.source), str(item.destination))
            restored_count += 1
            cleanup_empty_directories(item.source.parent, workflow_root)

        for path in cleanup_files:
            if path.exists():
                path.unlink()
                removed_generated_file_count += 1
                for root in generated_roots:
                    if path == root or root in path.parents:
                        cleanup_empty_directories(path.parent, root)
                        break

    return ResetResult(
        dry_run=not execute,
        review_file_count=review_file_count,
        restorable_count=len(restore_plan),
        restored_count=restored_count,
        blocked_count=len(blocked),
        generated_file_count=len(cleanup_files),
        removed_generated_file_count=removed_generated_file_count,
        workflow_root=workflow_root,
        generated_roots=generated_roots,
    )
