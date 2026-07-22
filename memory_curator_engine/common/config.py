"""YAML configuration loading.

PyYAML is used when available. A small fallback parser supports the simple
project config shape so this project can run without third-party packages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


Config = dict[str, Any]


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return parse_simple_yaml(text)

    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration root must be a mapping: {path}")
    return loaded


def config_value(config: Config, dotted_key: str, default: Any = None) -> Any:
    current: Any = config
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def parse_simple_yaml(text: str) -> Config:
    root: Config = {}
    stack: list[tuple[int, Config]] = [(-1, root)]

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line).rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent % 2:
            raise ValueError(f"Only two-space YAML indentation is supported near line {line_number}")

        stripped = line.strip()
        if ":" not in stripped:
            raise ValueError(f"Expected key/value YAML line near line {line_number}")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"Invalid YAML indentation near line {line_number}")

        parent = stack[-1][1]
        if raw_value == "":
            child: Config = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = parse_scalar(raw_value)

    return root


def strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, character in enumerate(line):
        if character == "'" and not in_double:
            in_single = not in_single
        elif character == '"' and not in_single:
            in_double = not in_double
        elif character == "#" and not in_single and not in_double:
            return line[:index]
    return line


def parse_scalar(value: str) -> Any:
    if value in {"true", "True", "yes", "Yes", "on", "On"}:
        return True
    if value in {"false", "False", "no", "No", "off", "Off"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].strip()
        if not items:
            return []
        return [parse_scalar(item.strip()) for item in items.split(",")]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
