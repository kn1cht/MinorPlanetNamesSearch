"""Small CLI progress reporter."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import TextIO


@dataclass
class ProgressReporter:
    enabled: bool = True
    stream: TextIO = sys.stdout
    started_at: float = field(default_factory=time.monotonic)

    def message(self, text: str) -> None:
        if not self.enabled:
            return
        print(f"[{self._elapsed()}] {text}", file=self.stream, flush=True)

    def step(self, label: str, current: int, total: int, *, detail: str = "") -> None:
        if not self.enabled:
            return
        suffix = f" {detail}" if detail else ""
        print(f"[{self._elapsed()}] {label}: {current}/{total}{suffix}", file=self.stream, flush=True)

    def _elapsed(self) -> str:
        elapsed = max(0.0, time.monotonic() - self.started_at)
        minutes, seconds = divmod(int(elapsed), 60)
        return f"{minutes:02d}:{seconds:02d}"


QUIET_PROGRESS = ProgressReporter(enabled=False)

