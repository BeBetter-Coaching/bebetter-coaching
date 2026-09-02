"""Test-brede fixtures.

P0 (fix/feedback-p0-terminating): `feedback_core._SKIP_MEM` is een nieuwe in-proces
skip-mirror (hot-read cache). Het is procesglobale state; zonder reset lekt hij tussen
tests (test-volgorde-afhankelijke fouten). Deze autouse-fixture reset hem vóór élke test,
zodat elke test zijn eigen (gemockte of lege) skip-state lazy hydrateert — exact zoals de
bestaande fixtures `_QUEUE_MEM`/`_cache` al resetten.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))


def _reset_process_caches():
    """Reset procesglobale hot-read caches zodat ze niet tussen tests lekken."""
    try:
        import feedback_core as FC
        FC._SKIP_MEM = None
    except Exception:
        pass
    # Canonical Athlete Read Layer v1 (pwa/athlete_read.py): in-proces AthleteState hot-cache.
    # Zelfde reden als _SKIP_MEM hierboven — zonder reset lekt een gecachete state tussen tests.
    try:
        import athlete_read as AR
        AR.reset()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_feedback_skip_mem():
    _reset_process_caches()
    yield
    _reset_process_caches()
