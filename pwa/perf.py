"""Coach Read Performance v1 — lichte, opt-in timing-instrumentatie.

Volledig no-op tenzij de omgevingsvariabele BEBETTER_PERF_TIMING truthy is: dan
verzamelt een Timer per benoemde stap de duur in milliseconden, die een endpoint
onder `_timing` in zijn payload kan meesturen. Bewust GEEN permanente logging en
GEEN productgedrag — puur meten. Zo kan de read-keten production-equivalent worden
opgemeten zonder noisy logs achter te laten.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager


def enabled() -> bool:
    return bool(os.environ.get("BEBETTER_PERF_TIMING", "").strip())


class Timer:
    """Verzamelt {stapnaam: ms}. Buiten de gate is `step()` een goedkope no-op."""

    def __init__(self) -> None:
        self.steps: dict[str, int] = {}

    @contextmanager
    def step(self, name: str):
        if not enabled():
            yield
            return
        t0 = time.monotonic()
        try:
            yield
        finally:
            self.steps[name] = round((time.monotonic() - t0) * 1000)

    def result(self):
        """De verzamelde tijden (of None als er niets te melden valt / gate uit)."""
        return dict(self.steps) if (enabled() and self.steps) else None
