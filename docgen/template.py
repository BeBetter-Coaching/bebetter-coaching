#!/usr/bin/env python3
"""Templating-laag voor de BeBetter-documentgenerator.

Een SJABLOON is een dict in dezelfde vorm als wat de engine (`reportlab_gen`)
verwacht, maar met twee extra's:

  * `{{placeholders}}` in de teksten            -> ingevuld uit `answers`
  * een optionele `"when": lambda a: ...` op een sectie of blok
                                                 -> blok/sectie valt weg als False

`render(template, answers, out)` doet de merge en rendert de PDF. De teksten
gaan door de pijplijn  substitueer -> scrub_ai (streepjes weg) -> md (opmaak),
zodat het resultaat engine-klaar en gegarandeerd streepjesvrij is, of de tekst
nu handgeschreven of AI-gegenereerd is.

De LAYOUT blijft volledig deterministisch (de engine); alleen de INHOUD kan per
klant verschillen (placeholders, conditionele blokken, of AI-tekst die je vóór
het renderen in het sjabloon zet).
"""

from __future__ import annotations

import copy
import re

import reportlab_gen as G
from house_style import scrub_ai

_PH = re.compile(r"\{\{\s*(\w+)\s*\}\}")


# ── Tekstpijplijn ───────────────────────────────────────────────────────────
def substitute(text: str, answers: dict) -> str:
    """Vervang {{naam}} door answers['naam'] (ontbreekt -> lege string)."""
    return _PH.sub(lambda m: str(answers.get(m.group(1), "")), text)


def md(text: str) -> str:
    """**vet**/*cursief* -> ReportLab-markup; &<> escapen; pijl -> ›."""
    text = text.replace("→", "›")            # Open Sans mist de pijl
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text


def _pipe(text: str, answers: dict) -> str:
    """Volledige pijplijn voor één tekstveld."""
    return md(scrub_ai(substitute(text, answers)))


# ── Conditie ────────────────────────────────────────────────────────────────
def _visible(node: dict, answers: dict) -> bool:
    cond = node.get("when")
    return True if cond is None else bool(cond(answers))


# ── Merge: sjabloon + answers -> engine-klare DOC ───────────────────────────
def merge(template: dict, answers: dict | None = None) -> dict:
    a = {**template.get("defaults", {}), **(answers or {})}
    doc: dict = {}

    for key in ("pdftitel", "titel_1", "titel_2", "ondertitel", "voor", "kop_links"):
        if key in template:
            doc[key] = substitute(template[key], a)

    doc["kort"] = [(substitute(lbl, a), substitute(val, a))
                   for lbl, val in template.get("kort", [])]

    doc["secties"] = []
    for sec in template.get("secties", []):
        if not _visible(sec, a):
            continue
        blocks = [_merge_block(b, a) for b in sec.get("blocks", []) if _visible(b, a)]
        doc["secties"].append({"titel": substitute(sec["titel"], a), "blocks": blocks})

    return doc


def _merge_block(blk: dict, a: dict) -> dict:
    t = blk["t"]
    if t in ("para", "why", "tip", "spoed"):
        return {"t": t, "x": _pipe(blk["x"], a)}
    if t == "steps":
        return {"t": t, "items": [(_pipe(txt, a), img) for txt, img in blk["items"]]}
    if t == "kleuren":
        return {"t": t, "items": [(hexc, substitute(lbl, a), _pipe(desc, a))
                                  for hexc, lbl, desc in blk["items"]]}
    if t == "check":
        return {"t": t, "items": [_pipe(x, a) for x in blk["items"]]}
    if t == "tabel":
        return {"t": t,
                "head": [_pipe(h, a) for h in blk["head"]],
                "rows": [[_pipe(c, a) for c in r] for r in blk["rows"]]}
    if t == "bronnen":
        return {"t": t, "items": [_pipe(x, a) for x in blk["items"]]}
    if t == "oefening":
        return {"t": t,
                "naam": substitute(blk["naam"], a),
                "sets": substitute(blk.get("sets", ""), a),
                "cue": _pipe(blk.get("cue", ""), a),
                "begin": blk.get("begin"), "eind": blk.get("eind")}
    return copy.deepcopy(blk)


# ── AI-blokken invullen (proza dat zich afstemt op de intake) ───────────────
# Een blok met een "ai"-sleutel laat de huisstijl-AI de tekst schrijven:
#   {"t": "para", "ai": "Schrijf de openingsalinea ... {{voornaam}} ..."}
# De layout blijft deterministisch; alleen deze tekst wordt gegenereerd.
def _context(a: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in a.items() if v not in (None, ""))


def resolve_ai(template: dict, answers: dict | None = None, ai_fn=None) -> dict:
    """Vervang elk 'ai'-blok door een concreet tekstblok met gegenereerde tekst.

    `ai_fn(taak, context) -> str`. Standaard = `house_style.generate_prose`
    (echte AI, vereist API-sleutel). Geef een eigen `ai_fn` mee om te testen
    of te demonstreren zonder sleutel. Onzichtbare blokken (`when` False) worden
    NIET gegenereerd (scheelt kosten)."""
    a = {**template.get("defaults", {}), **(answers or {})}
    ctx = _context(a)

    def _fn(taak, context):
        nonlocal ai_fn
        if ai_fn is None:
            from house_style import generate_prose
            ai_fn = generate_prose
        return ai_fn(taak, context)

    tpl = copy.deepcopy(template)
    for sec in tpl.get("secties", []):
        for blk in sec.get("blocks", []):
            if "ai" in blk and _visible(blk, a):
                blk["x"] = _fn(substitute(blk["ai"], a), ctx)
                del blk["ai"]
    return tpl


# ── Renderen ────────────────────────────────────────────────────────────────
def render(template: dict, answers: dict | None, out: str, ai_fn=None) -> str:
    resolved = resolve_ai(template, answers, ai_fn)
    G.build(merge(resolved, answers), out)
    return out
