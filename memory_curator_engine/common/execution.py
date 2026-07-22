"""Config-driven execution helpers."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

from memory_curator_engine.common.config import Config, config_value


T = TypeVar("T")
R = TypeVar("R")


def configured_workers(config: Config, phase_key: str, default: int = 1) -> int:
    value = config_value(config, f"execution.phases.{phase_key}.workers", config_value(config, "execution.workers", default))
    if isinstance(value, str) and value.strip().lower() == "auto":
        return max(1, min(8, os.cpu_count() or 1))
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, default)


def parallel_enabled(config: Config, phase_key: str) -> bool:
    phase_value = config_value(config, f"execution.phases.{phase_key}.parallel", None)
    if phase_value is not None:
        return bool(phase_value)
    return bool(config_value(config, "execution.parallel", False))


def ordered_map(config: Config, phase_key: str, function: Callable[[T], R], items: Iterable[T]) -> list[R]:
    item_list = list(items)
    workers = configured_workers(config, phase_key)
    if not parallel_enabled(config, phase_key) or workers <= 1 or len(item_list) <= 1:
        return [function(item) for item in item_list]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(function, item_list))
