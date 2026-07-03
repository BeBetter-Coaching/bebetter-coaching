"""Gedeelde Anthropic-client met automatische retry bij tijdelijke API-fouten.

Eén plek voor alle AI-aanroepen in de app. Tijdelijke fouten (overbelasting 529,
rate limit 429, 5xx, verbindingsfouten) worden automatisch opnieuw geprobeerd
met oplopende wachttijd; andere fouten gaan direct door naar de aanroeper.
"""

from __future__ import annotations

import time

import anthropic

client = anthropic.Anthropic()

_TIJDELIJKE_STATUS = {429, 500, 502, 503, 504, 529}
_MAX_POGINGEN = 5


def _is_tijdelijk(e: Exception) -> bool:
    if isinstance(e, anthropic.APIConnectionError):
        return True
    if isinstance(e, anthropic.APIStatusError):
        return e.status_code in _TIJDELIJKE_STATUS
    m = str(e).lower()
    return ("overloaded" in m or "rate limit" in m or "timeout" in m or "529" in m)


def create_message(**kwargs):
    """client.messages.create met retry + backoff (1.5s, 2.5s, 4.5s, 8.5s)."""
    laatste: Exception | None = None
    for poging in range(_MAX_POGINGEN):
        try:
            return client.messages.create(**kwargs)
        except Exception as e:
            laatste = e
            if not _is_tijdelijk(e) or poging == _MAX_POGINGEN - 1:
                raise
            time.sleep(min(2 ** poging, 8) + 0.5)
    raise laatste  # onbereikbaar, maar houdt type-checkers tevreden
