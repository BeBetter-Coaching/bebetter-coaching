"""Schemabouwer voor de PWA — intake -> AI-plan -> CSV (download).

Hergebruikt schema_builder.py (dezelfde AI-prompts en -logica als Streamlit) op
de GEDEELDE opslag. Vereist ANTHROPIC_API_KEY (staat op Render). De FinalSurge-
push (import_to_finalsurge) slaan we bewust over — dat is de rode stap; in de PWA
lever je het schema als CSV-download die je in FinalSurge importeert.

V1 hergebruikt de intake die de coach al per atleet in de bouwer opsloeg
(save_laatste_intake / load_laatste_intakes), zodat je niet 33 velden opnieuw
hoeft in te vullen: kies een atleet met opgeslagen intake -> plan -> CSV. Het
volledige intake-formulier in de PWA volgt later.

BELANGRIJK: schema_builder wordt LUI geïmporteerd (binnen de functies), want het
importeert ai_client -> anthropic.Anthropic() dat zonder key al bij import crasht.
Zo blijft het laden van deze module (en dus de app-boot) veilig, ook zonder key.
"""
from __future__ import annotations

import os
import sys

_HIER = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HIER)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import intake_store                                    # veilig: geen AI-import


def heeft_key() -> bool:
    """Staat de Anthropic-sleutel gezet? Zonder key kan er geen plan gemaakt worden."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _intakes() -> dict:
    try:
        return intake_store.load_laatste_intakes() or {}
    except Exception:
        return {}


def bouwbare_atleten() -> list[dict]:
    """Atleten met een opgeslagen bouwer-intake (klaar om een plan te maken)."""
    out = []
    for key, intake in _intakes().items():
        if not isinstance(intake, dict):
            continue
        out.append({
            "key": key,
            "naam": intake.get("athlete_name") or intake.get("naam") or key,
            "doel": intake.get("doel", ""),
            "weken": intake.get("weken", ""),
            "trainingsdagen": intake.get("trainingsdagen", ""),
        })
    out.sort(key=lambda a: str(a["naam"]).lower())
    return out


def get_intake(key: str):
    intake = _intakes().get(key)
    if not isinstance(intake, dict):
        return None
    intake = dict(intake)
    intake.setdefault("athlete_key", key)
    return intake


def genereer_plan(key: str) -> str:
    """Genereer de plan-tekst (AI). Vereist een opgeslagen intake + de sleutel."""
    intake = get_intake(key)
    if not intake:
        raise ValueError("Geen opgeslagen intake voor deze atleet. "
                         "Vul de bouwer-intake eerst in (Streamlit).")
    import schema_builder as SB                         # lui: pas hier is de key nodig
    return SB.generate_plan(intake)


def genereer_csv(key: str, plan_tekst: str):
    """Genereer de CSV op basis van het plan (AI). Geeft (csv_tekst, rijen) terug."""
    if not (plan_tekst or "").strip():
        raise ValueError("Geen plan om een CSV van te maken.")
    intake = get_intake(key)
    if not intake:
        raise ValueError("Geen opgeslagen intake voor deze atleet.")
    import schema_builder as SB                         # lui
    csv_tekst = SB.generate_csv(plan_tekst, intake)
    csv_clean = SB.extract_csv_block(csv_tekst)
    rijen = SB.parse_csv_text(csv_tekst)
    return csv_clean, rijen
