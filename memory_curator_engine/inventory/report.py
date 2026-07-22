"""Create CSV media inventories."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from memory_curator_engine.common.config import Config, config_value
from memory_curator_engine.common.media import (
    INVENTORY_CSV_COLUMNS,
    MEDIA_EXTENSIONS,
    MediaRecord,
    classify_file,
    file_created_time,
    format_timestamp,
)
from memory_curator_engine.common.paths import resolve_project_path
from memory_curator_engine.inventory.metadata import get_metadata


@dataclass(frozen=True)
class InventoryJob:
    name: str
    input_dir: Path
    output_csv: Path
    enabled: bool = True


@dataclass(frozen=True)
class InventoryResult:
    name: str
    count: int
    output_csv: Path


def iter_media_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            yield path


def build_media_record(path: Path, project_root: Path) -> MediaRecord:
    stat_result = path.stat()
    metadata = get_metadata(path)
    created_date = format_timestamp(file_created_time(stat_result))
    modified_date = format_timestamp(stat_result.st_mtime)
    return MediaRecord(
        path=path,
        project_root=project_root,
        file_type=classify_file(path),
        size_bytes=stat_result.st_size,
        capture_date=metadata.capture_date or created_date or modified_date,
        capture_date_source=metadata.capture_date_source or ("filesystem_created" if created_date else "filesystem_modified"),
        created_date=created_date,
        modified_date=modified_date,
        metadata=metadata,
    )


def record_to_row(record: MediaRecord) -> dict[str, object]:
    return {
        "filename": record.filename,
        "relative_path": record.relative_path,
        "file_type": record.file_type,
        "size_bytes": record.size_bytes,
        "capture_date": record.capture_date,
        "capture_date_source": record.capture_date_source,
        "created_date": record.created_date,
        "modified_date": record.modified_date,
        "width": record.metadata.width or "",
        "height": record.metadata.height or "",
        "duration_seconds": record.metadata.duration_seconds if record.metadata.duration_seconds is not None else "",
        "metadata_notes": record.metadata.notes,
    }


def inventory_media(input_dir: Path, output_csv: Path, project_root: Path) -> int:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with output_csv.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=INVENTORY_CSV_COLUMNS)
        writer.writeheader()

        for path in iter_media_files(input_dir):
            writer.writerow(record_to_row(build_media_record(path, project_root)))
            count += 1

    return count


def inventory_from_config(
    config: Config,
    project_root: Path,
    input_override: str | None = None,
    output_override: str | None = None,
) -> tuple[int, Path]:
    input_value = input_override or config_value(config, "inventory.input_dir", "input_data")
    output_value = output_override or config_value(
        config,
        "inventory.output_csv",
        "MemoryCurator/01 Inventory/rafting_inventory.csv",
    )

    input_dir = resolve_project_path(project_root, input_value)
    output_csv = resolve_project_path(project_root, output_value)

    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_dir}")

    count = inventory_media(input_dir=input_dir, output_csv=output_csv, project_root=project_root)
    return count, output_csv


def inventory_jobs_from_config(
    config: Config,
    project_root: Path,
    only_names: set[str] | None = None,
) -> list[InventoryJob]:
    configured_sets = config_value(config, "inventory.media_sets")
    jobs: list[InventoryJob] = []

    if isinstance(configured_sets, dict):
        for name, media_set in configured_sets.items():
            if not isinstance(media_set, dict):
                raise ValueError(f"inventory.media_sets.{name} must be a mapping")
            if only_names is not None and name not in only_names:
                continue

            input_value = media_set.get("input_dir")
            output_value = media_set.get("output_csv")
            if not input_value:
                raise ValueError(f"inventory.media_sets.{name}.input_dir is required")
            if not output_value:
                raise ValueError(f"inventory.media_sets.{name}.output_csv is required")

            jobs.append(
                InventoryJob(
                    name=name,
                    input_dir=resolve_project_path(project_root, input_value),
                    output_csv=resolve_project_path(project_root, output_value),
                    enabled=parse_enabled(media_set.get("enabled", False), name),
                )
            )

        if only_names is not None:
            found_names = {job.name for job in jobs}
            missing_names = sorted(only_names - found_names)
            if missing_names:
                raise ValueError(f"Unknown inventory media set(s): {', '.join(missing_names)}")
        return jobs

    if only_names is not None:
        raise ValueError("Specific media sets require inventory.media_sets in the config")

    input_value = config_value(config, "inventory.input_dir", "input_data")
    output_value = config_value(config, "inventory.output_csv", "MemoryCurator/01 Inventory/inventory.csv")
    return [
        InventoryJob(
            name="default",
            input_dir=resolve_project_path(project_root, input_value),
            output_csv=resolve_project_path(project_root, output_value),
            enabled=True,
        )
    ]


def parse_enabled(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ValueError(f"inventory.media_sets.{name}.enabled must be yes/no or true/false")


def run_inventory_jobs(
    config: Config,
    project_root: Path,
    only_names: set[str] | None = None,
    include_disabled: bool = False,
) -> list[InventoryResult]:
    jobs = inventory_jobs_from_config(config=config, project_root=project_root, only_names=only_names)
    results: list[InventoryResult] = []

    for job in jobs:
        if not job.enabled and not include_disabled:
            continue
        if not job.input_dir.exists() or not job.input_dir.is_dir():
            raise FileNotFoundError(f"Input folder not found for inventory set '{job.name}': {job.input_dir}")

        count = inventory_media(input_dir=job.input_dir, output_csv=job.output_csv, project_root=project_root)
        results.append(InventoryResult(name=job.name, count=count, output_csv=job.output_csv))

    return results
