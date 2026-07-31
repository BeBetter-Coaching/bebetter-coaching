"""📄 Documenten — genereer een strak, persoonlijk BeBetter-document.

Kies een documenttype en een atleet. De naam (en waar relevant extra velden)
vult de intake van het sjabloon; de AI schrijft de persoonlijke stukjes in de
huisstijl, de rest is vaste, onderbouwde inhoud. Levert een deel-klare PDF.

De documentgenerator zelf leeft in de map docgen/ (engine + sjablonen). Die
zetten we op het pad en gebruiken we hier zonder iets te dupliceren.
"""

from __future__ import annotations

import os
import sys
import tempfile

import streamlit as st

import intake_store

_DGDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docgen")
if _DGDIR not in sys.path:
    sys.path.insert(0, _DGDIR)

import template as _tpl  # noqa: E402
from templates import handleiding, wedstrijd, voeding_training, kracht  # noqa: E402

# Label -> sjabloonmodule. Volgorde = weergavevolgorde.
_DOCS = {
    "Handleiding FinalSurge": handleiding,
    "Rondom je wedstrijd": wedstrijd,
    "Voeding rondom je trainingen": voeding_training,
    "Krachttraining voor hardlopers": kracht,
}


def _veld_input(veld: dict):
    key = f"doc_f_{veld['veld']}"
    t = veld.get("type")
    if t == "keuze":
        return st.selectbox(veld["vraag"], veld.get("opties", [""]), key=key)
    if t == "getal":
        return st.text_input(veld["vraag"], key=key, placeholder="bijv. 70")
    return st.text_input(veld["vraag"], key=key)


def render(all_athletes: list):
    st.caption("Kies een document en een atleet. De AI schrijft de persoonlijke stukjes in de "
               "huisstijl; de rest is vaste, onderbouwde inhoud. Je krijgt een deel-klare PDF.")

    label = st.selectbox("Documenttype", list(_DOCS.keys()), key="doc_type")
    mod = _DOCS[label]

    namen = ["— Algemeen (geen naam) —"] + [a["name"] for a in all_athletes]
    keuze = st.selectbox("Voor welke atleet?", namen, key="doc_athlete")
    atleet = next((a for a in all_athletes if a["name"] == keuze), None)
    voornaam = "" if keuze.startswith("—") else keuze.split()[0]
    user_key = atleet.get("user_key") if atleet else None

    answers: dict = {}
    if voornaam:
        answers["voornaam"] = voornaam

    # Eerder ontvangen documenten tonen + als context meegeven aan de AI
    eerder = _eerdere_documenten(user_key) if user_key else []
    if eerder:
        _regels = ", ".join(f"{d.get('type', '')} ({d.get('datum', '')})" for d in eerder)
        st.caption(f"📄 {voornaam} ontving eerder: {_regels}. Dit gaat mee als context, "
                   "zodat de AI voortbouwt in plaats van hetzelfde te herhalen.")
        answers["eerdere_documenten"] = _regels

    extra = [v for v in getattr(mod, "INTAKE", []) if v["veld"] != "voornaam"]
    if extra:
        cols = st.columns(min(len(extra), 3))
        for i, v in enumerate(extra):
            with cols[i % len(cols)]:
                answers[v["veld"]] = _veld_input(v)

    if st.button("📄 Genereer document", type="primary", key="doc_gen"):
        _genereer(label, mod, answers, user_key)

    # download-knop blijft staan ná de rerun die het downloaden veroorzaakt
    if st.session_state.get("doc_pdf"):
        st.success("Document klaar om te delen.")
        st.download_button("⬇️ Download PDF", data=st.session_state["doc_pdf"],
                           file_name=st.session_state.get("doc_pdf_naam", "document.pdf"),
                           mime="application/pdf", key="doc_dl")


def _eerdere_documenten(user_key: str) -> list:
    """Documenten die deze atleet eerder ontving (nieuwste eerst)."""
    try:
        return intake_store.load_documenten().get(user_key, [])
    except Exception:
        return []


def _genereer(label: str, mod, answers: dict, user_key: str | None = None):
    answers = {k: v for k, v in answers.items() if v not in (None, "")}
    if hasattr(mod, "derive"):
        answers = mod.derive(answers)

    with st.spinner("Document genereren…"):
        try:
            out = os.path.join(tempfile.gettempdir(), "bebetter_doc.pdf")
            _tpl.render(mod.TEMPLATE, answers, out)  # echte AI voor de intro's
            with open(out, "rb") as f:
                st.session_state["doc_pdf"] = f.read()
        except Exception as e:  # AI-fout, ontbrekend bestand, enz.
            st.session_state.pop("doc_pdf", None)
            st.error(f"Genereren mislukt: {e}")
            return

    naam = answers.get("voornaam", "algemeen")
    st.session_state["doc_pdf_naam"] = f"{label} - {naam}.pdf"

    # Registreer in het dossier dat deze atleet dit document ontving
    if user_key:
        ok, err = intake_store.log_document(user_key, label)
        if not ok:
            st.warning(f"Document gemaakt, maar niet gelogd in dossier: {err}")
