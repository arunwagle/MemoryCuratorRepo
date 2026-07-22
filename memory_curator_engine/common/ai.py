"""Extension points for future AI modules.

No AI integrations are implemented yet. This file only defines a lightweight
interface shape that later modules can follow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AIModuleContext:
    name: str
    enabled: bool = False


class AIModule(Protocol):
    name: str

    def is_available(self) -> bool:
        """Return whether this module can run in the current environment."""
        ...
