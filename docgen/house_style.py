#!/usr/bin/env python3
"""Huisstijl-laag voor de BeBetter-documentgenerator.

Twee dingen:
1. `HUISSTIJL_SYSTEM` — de vaste coach-stem + harde stijlregels. Deze prompt
   gaat mee bij ELKE AI-tekst in een document, zodat de toon overal gelijk is.
2. `scrub_ai(text)` — deterministische vangrail die ná de AI (en ook bij
   handgeschreven tekst) elk gedachtestreepje repareert. De prompt is ~95%
   betrouwbaar; deze filter maakt het 100%: er komt nooit een '—' in de PDF.

Zo geldt: de AI schrijft en stemt af, maar het ziet er nooit uit als AI.
"""

from __future__ import annotations

import re

# ── De vaste coach-stem ─────────────────────────────────────────────────────
HUISSTIJL_SYSTEM = """Je schrijft klantdocumenten voor BeBetter Coaching, de hardloopcoaching van Jip en Remco. Je schrijft ALS de coach (Jip of Remco), niet als een AI.

TOON:
- Strak, persoonlijk, menselijk en duidelijk. Je staat naast de atleet, niet erboven.
- Jij-vorm. Korte, actieve zinnen. Concreet en to-the-point.
- Leg kort het waarom uit waar dat helpt, maar zonder te preken.
- Warm en motiverend, maar zakelijk. Zoals een ervaren coach die de atleet echt kent.

HARDE REGELS (niet onderhandelbaar):
- NOOIT gedachtestreepjes. Geen '—' (em-dash) en geen '–' (en-dash). Gebruik een komma, punt of dubbele punt. Koppeltekens binnen woorden mogen wel (auto-sync, e-mailadres).
- Geen AI-clichés: vermijd "duik in", "in de wereld van", "of je nu... of...", "het is belangrijk om te benoemen", "kortom", "in een notendop", opsommingsdrang en holle superlatieven.
- Alleen een opsomming als die echt iets verheldert, anders lopende tekst.
- De merknaam is ALTIJD voluit "BeBetter Coaching", nooit los "BeBetter".
- Schrijf in het Nederlands. App-termen laat je in het Engels staan (How I Felt, Perceived Effort, Move, Push to Garmin, Add Label, Calendar).
- Verzin geen feiten, cijfers of app-knoppen die je niet zijn aangereikt.

Lever alleen de gevraagde tekst. Geen kopjes, geen uitleg vooraf, geen afsluitende meta-opmerkingen."""


# ── De vangrail: streepjes weg, ná de AI en overal ──────────────────────────
def scrub_ai(text: str) -> str:
    """Haal gedachtestreepjes eruit die ondanks de instructies doorglippen.

    Zelfde logica als `ai_feedback._clean_text`, zodat documenten en de
    app-teksten identiek schoon zijn. Koppeltekens BINNEN woorden blijven staan.
    """
    if not text:
        return text
    # getalsbereik (5–10) wordt een gewoon koppelteken
    text = re.sub(r"(\d)\s*[—–]\s*(\d)", r"\1-\2", text)
    # opsommingsstreepje aan het begin van een regel weg (regeleindes behouden)
    text = re.sub(r"(?m)^[ \t]*[—–][ \t]*", "", text)
    # em-/en-dash tussen zinsdelen wordt een komma
    text = re.sub(r"[ \t]*[—–][ \t]*", ", ", text)
    # dubbele komma's na vervanging opruimen
    text = re.sub(r",\s*,", ",", text)
    return text


# ── AI-tekstgeneratie met de vaste stem ─────────────────────────────────────
def generate_prose(taak: str, context: str = "", *, max_tokens: int = 600,
                   model: str = "claude-opus-4-5") -> str:
    """Genereer één stuk documenttekst in de huisstijl.

    `taak` = wat de tekst moet doen (bv. "Schrijf de welkomstalinea ...").
    `context` = de klant-/intakegegevens waarop de tekst wordt afgestemd.
    De ai_client wordt lui geïmporteerd, zodat dit bestand ook zonder
    API-sleutel importeerbaar blijft (voor de deterministische render-tests).
    """
    from ai_client import create_message  # lazy: pas nodig bij echte generatie

    prompt = taak if not context else f"{taak}\n\nGEGEVENS OM OP AF TE STEMMEN:\n{context}"
    resp = create_message(
        model=model,
        max_tokens=max_tokens,
        system=HUISSTIJL_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return scrub_ai(resp.content[0].text).strip()
