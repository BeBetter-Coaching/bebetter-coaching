"""Documenten-module voor de PWA — genereert de BeBetter template-PDF's.

Draait op de bestaande docgen-engine (ReportLab) in de map ../docgen. Vier
sjablonen: Handleiding FinalSurge, Rondom je wedstrijd, Voeding rondom je
trainingen, Krachttraining voor hardlopers. 1-op-1 met de Streamlit-module
`documenten_page.py` (zelfde `_DOCS`, zelfde INTAKE-velden, zelfde `derive`).

Key-bewust:
  * mét ANTHROPIC_API_KEY schrijft de AI de persoonlijke intro's (huisstijl);
  * zónder key blijven die intro's leeg en krijg je de vaste, onderbouwde
    inhoud — nog steeds een deel-klare PDF. De rest van het document is gelijk.

Zo is de module nu al bruikbaar; zodra de key op Render staat, vullen de
intro's zich vanzelf. Documenten worden in het dossier gelogd via intake_store
(zelfde opslag als Streamlit).
"""
from __future__ import annotations

import os
import sys
import tempfile

_HIER = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HIER)
_DG = os.path.join(_ROOT, "docgen")
for _p in (_ROOT, _DG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import intake_store                                    # noqa: E402  (repo-root)
import template as _tpl                                # noqa: E402  (docgen-engine)
import reportlab_gen as _G                             # noqa: E402
from templates import (handleiding, wedstrijd,         # noqa: E402
                       voeding_training, kracht)

# slug -> (module, zichtbaar label, korte omschrijving). Labels exact als in
# documenten_page._DOCS, zodat de dossier-log dezelfde types gebruikt.
_DOCS: dict[str, tuple] = {
    "handleiding": (handleiding, "Handleiding FinalSurge",
                    "Startgids: koppelen, je week lezen, trainingen verschuiven."),
    "wedstrijd": (wedstrijd, "Rondom je wedstrijd",
                  "Persoonlijk plan: aanloop, de dag zelf, voeding en tempo."),
    "voeding": (voeding_training, "Voeding rondom je trainingen",
                "Praktisch en onderbouwd eten rond je trainingen."),
    "kracht": (kracht, "Krachttraining voor hardlopers",
               "Kracht in drie varianten, kaart voor kaart."),
}


def heeft_key() -> bool:
    """Staat de Anthropic-sleutel gezet? Bepaalt of de AI-intro's meekomen."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def cloud_backed() -> bool:
    return intake_store.cloud_backed() if hasattr(intake_store, "cloud_backed") else False


def templates() -> list[dict]:
    """Lijst van documenttypes + hun extra invulvelden (voornaam komt van de atleet)."""
    out = []
    for slug, (mod, label, oms) in _DOCS.items():
        velden = [v for v in getattr(mod, "INTAKE", []) if v.get("veld") != "voornaam"]
        out.append({"slug": slug, "label": label, "omschrijving": oms, "velden": velden})
    return out


def _geen_ai(taak, context):
    """Fallback zonder sleutel: geen Anthropic-aanroep, lege intro."""
    return ""


def genereer(slug: str, answers: dict | None = None, user_key: str | None = None):
    """Genereer de PDF voor `slug`. Geeft (pdf_bytes, bestandsnaam) terug.

    `answers` bevat o.a. voornaam + eventuele extra velden (horloge/gewicht/variant).
    Logt het document in het dossier als er een `user_key` is meegegeven.
    """
    if slug not in _DOCS:
        raise ValueError(f"Onbekend documenttype: {slug}")
    mod, label, _ = _DOCS[slug]
    answers = {k: v for k, v in (answers or {}).items() if v not in (None, "")}
    if hasattr(mod, "derive"):
        answers = mod.derive(answers)

    ai_fn = None if heeft_key() else _geen_ai        # None = echte AI (huisstijl)
    resolved = _tpl.resolve_ai(mod.TEMPLATE, answers, ai_fn=ai_fn)
    doc = _tpl.merge(resolved, answers)

    fd, out = tempfile.mkstemp(suffix=".pdf", prefix="bb_doc_")
    os.close(fd)
    try:
        _G.build(doc, out)
        with open(out, "rb") as f:
            data = f.read()
    finally:
        try:
            os.remove(out)
        except OSError:
            pass

    naam = answers.get("voornaam") or "algemeen"
    bestandsnaam = f"{label} - {naam}.pdf"
    if user_key:
        try:
            intake_store.log_document(user_key, label)
        except Exception:
            pass                                       # PDF is er; log-fout mag niet blokkeren
    return data, bestandsnaam
