"""Executable frontend startup test (runs the real JS state machine via Node).

The P0 contract requires a REAL executable test — not source-string checks — proving:
  1. a never-resolving /api/feedback/queue does NOT leave an infinite skeleton
     (bounded deadline → terminal recoverable retry state);
  2. a warm queue stays usable while the background refresh hangs;
  3. cold pending → refresh resolves later → first server-ordered item opens;
  4. a refresh timeout never blanks an already-visible queue;
  5. enter/leave: a stale (late/aborted) request never overwrites the current view.

The heavy lifting lives in tests/js/feedback_startup.test.mjs, which slices the ACTUAL
fbEnter/fbRefresh/fbQueueGet/fbLeave + terminal/stale renderers verbatim from app.js and
drives them with a signal-honoring mock fetch + short real AbortController deadlines.

    python3 -m pytest tests/test_feedback_startup_browser.py -q
"""
import os
import shutil
import subprocess

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, "tests", "js", "feedback_startup.test.mjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node niet beschikbaar")
def test_feedback_startup_state_machine_executable():
    node = shutil.which("node")
    proc = subprocess.run([node, _SCRIPT], capture_output=True, text=True, timeout=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, "startup state-machine scenarios faalden:\n" + out
    assert "PASS:" in out, out
