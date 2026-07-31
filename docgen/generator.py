#!/usr/bin/env python3
"""Vrije AI-documentgenerator voor BeBetter Coaching.

Naast de vaste sjablonen (handleiding, wedstrijd, voeding, kracht) kan de coach
hier een ONDERWERP + GUIDANCE opgeven, waarna de AI zélf een heel document
bedenkt: titel, secties, tekst, tips, tabellen, checklists en bronnen. De AI
levert een gestructureerd document (in ons blok-schema), dat we vervolgens door
de bestaande engine renderen. Zo blijft de layout deterministisch en in de
huisstijl (cover met logo + team-foto, geen streepjes), maar is de INHOUD vrij.

De AI kiest de blokken uit een vaste, veilige set (geen afbeeldingen, want die
kan de AI niet aanleveren). Alle tekst gaat door `scrub_ai`, dus ook een vrij
document is gegarandeerd streepjesvrij.
"""

from __future__ import annotations

import json
import re

import reportlab_gen as G
from house_style import HUISSTIJL_SYSTEM, scrub_ai
from template import md

# Bloktypes die de AI mag gebruiken. Bewust GEEN steps/kleuren/oefening: die
# hangen aan screenshots/oefeningfoto's die de AI niet kan aanleveren.
_ALLOWED = {"para", "why", "tip", "spoed", "check", "tabel", "bronnen"}

_SCHEMA_SYSTEM = HUISSTIJL_SYSTEM + """

OPDRACHT NU: je bouwt een compleet klantdocument en levert het als JSON. Alleen
JSON, geen tekst eromheen, geen ```-blokken.

Structuur:
{
  "titel_1": "EERSTE TITELREGEL (kort, in hoofdletters)",
  "titel_2": "TWEEDE TITELREGEL (kort, in hoofdletters)",
  "ondertitel": "een korte zin die het document samenvat",
  "kort": [["Label", "Waarde"], ...],           // 0 tot 4 kerndingen voor op de cover, mag leeg []
  "secties": [
    {
      "titel": "Sectietitel",
      "blocks": [ ...blokken... ]
    }
  ]
}

Toegestane blokken (gebruik alleen deze):
  {"t": "para",   "x": "lopende tekst"}                         // gewone alinea
  {"t": "why",    "x": "het waarom / de onderbouwing"}          // rustig kader
  {"t": "tip",    "x": "een concrete tip"}                      // amber tip-kader
  {"t": "spoed",  "x": "let-op / waarschuwing"}                 // rood kader, spaarzaam
  {"t": "check",  "items": ["punt 1", "punt 2"]}               // afvinkbare checklist
  {"t": "tabel",  "head": ["Kolom A", "Kolom B"], "rows": [["1a","1b"], ["2a","2b"]]}
  {"t": "bronnen","items": ["Auteur (jaar). Titel.", ...]}     // alleen bij wetenschappelijke claims

REGELS:
- 3 tot 6 secties. Elke sectie 1 tot 5 blokken. Begin een sectie met een "para".
- Opmaak binnen tekst mag met **vet** en *cursief*. Geen kopjes in de tekst zelf (dat doen de secties).
- Gebruik "tabel" alleen als een tabel echt verheldert. Gebruik "bronnen" alleen als je concrete studies noemt, en verzin geen bronnen.
- Stem af op de meegegeven gegevens (naam, doel enz.) als die er zijn. Spreek de atleet aan met de voornaam als die bekend is.
- Houd je aan ALLE stijlregels hierboven (geen streepjes, "BeBetter Coaching" voluit, jij-vorm)."""


def _clean_str(v) -> str:
    """Voor titels/labels die via de canvas worden getekend: alleen streepjes weg."""
    return scrub_ai(str(v)).strip() if v is not None else ""


def _rich(v) -> str:
    """Voor bloktekst die als Paragraph rendert: streepjes weg + **vet**/*cursief*
    naar opmaak + &<> escapen (zelfde pijplijn als de sjablonen)."""
    return md(scrub_ai(str(v))).strip() if v is not None else ""


def _sanitize_block(blk: dict) -> dict | None:
    """Maak een AI-blok engine-klaar of gooi het weg als het niet klopt."""
    if not isinstance(blk, dict):
        return None
    t = blk.get("t")
    if t not in _ALLOWED:
        return None
    if t in ("para", "why", "tip", "spoed"):
        x = _rich(blk.get("x"))
        return {"t": t, "x": x} if x else None
    if t in ("check", "bronnen"):
        items = [_rich(i) for i in blk.get("items", []) if _clean_str(i)]
        return {"t": t, "items": items} if items else None
    if t == "tabel":
        head = [_rich(h) for h in blk.get("head", [])]
        rows = [[_rich(c) for c in r] for r in blk.get("rows", []) if isinstance(r, list)]
        rows = [r for r in rows if any(r)]
        # rijen op de kolombreedte van de kop brengen
        if head and rows:
            n = len(head)
            rows = [(r + [""] * n)[:n] for r in rows]
            return {"t": "tabel", "head": head, "rows": rows}
        return None
    return None


def _parse_json(raw: str) -> dict:
    """Haal het JSON-object uit de modeltekst, ook als er rommel omheen staat."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def build_doc(onderwerp: str, spec: dict, answers: dict | None = None) -> dict:
    """Zet de (rauwe) AI-spec om naar een engine-klare DOC-dict."""
    answers = answers or {}
    voornaam = _clean_str(answers.get("voornaam"))

    secties = []
    for sec in spec.get("secties", []):
        if not isinstance(sec, dict):
            continue
        titel = _clean_str(sec.get("titel"))
        blocks = [b for b in (_sanitize_block(x) for x in sec.get("blocks", [])) if b]
        if titel and blocks:
            secties.append({"titel": titel, "blocks": blocks})

    if not secties:
        raise ValueError("De AI leverde geen bruikbare secties op. Probeer het opnieuw.")

    kort = []
    for item in spec.get("kort", []) or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            lbl, val = _clean_str(item[0]), _clean_str(item[1])
            if lbl and val:
                kort.append((lbl, val))
    kort = kort[:4]
    if not kort:
        kort = [("Voor", voornaam or "Onze atleten"), ("Van", "Je coach bij BeBetter Coaching")]

    titel_1 = _clean_str(spec.get("titel_1")) or onderwerp.upper()
    titel_2 = _clean_str(spec.get("titel_2"))
    ondertitel = _clean_str(spec.get("ondertitel")) or onderwerp

    return {
        "pdftitel": onderwerp,
        "titel_1": titel_1,
        "titel_2": titel_2,
        "ondertitel": ondertitel,
        "voor": f"Voor {voornaam}" if voornaam else "Voor onze atleten",
        "kop_links": (titel_1 + (" " + titel_2 if titel_2 else "")).strip() or onderwerp,
        "kort": kort,
        "secties": secties,
    }


def _context(answers: dict | None) -> str:
    if not answers:
        return ""
    return "\n".join(f"{k}: {v}" for k, v in answers.items() if v not in (None, ""))


def generate_spec(onderwerp: str, guidance: str = "", context: str = "", *,
                  max_tokens: int = 2200, model: str = "claude-opus-4-5",
                  ai_fn=None) -> dict:
    """Laat de AI een document-spec (rauwe dict) bedenken.

    `ai_fn(system, user) -> str` levert de rauwe modeltekst. Standaard gaat het
    via `ai_client.create_message` (echte AI, alleen op de cloud). Geef een eigen
    `ai_fn` mee om lokaal te testen zonder API-sleutel.
    """
    user = f"ONDERWERP: {onderwerp}"
    if guidance:
        user += f"\n\nGUIDANCE VAN DE COACH:\n{guidance}"
    if context:
        user += f"\n\nGEGEVENS OM OP AF TE STEMMEN:\n{context}"

    if ai_fn is not None:
        raw = ai_fn(_SCHEMA_SYSTEM, user)
    else:
        from ai_client import create_message  # lazy: alleen nodig bij echte generatie
        resp = create_message(
            model=model,
            max_tokens=max_tokens,
            system=_SCHEMA_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text

    return _parse_json(raw)


def render(onderwerp: str, guidance: str, answers: dict | None, out: str,
           ai_fn=None) -> str:
    """Genereer een vrij document en render het naar `out` (PDF-pad)."""
    answers = answers or {}
    spec = generate_spec(onderwerp, guidance, _context(answers), ai_fn=ai_fn)
    G.build(build_doc(onderwerp, spec, answers), out)
    return out
