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
import generator as _gen  # noqa: E402
from templates import handleiding, wedstrijd, voeding_training, kracht  # noqa: E402

# Label -> sjabloonmodule. Volgorde = weergavevolgorde.
_DOCS = {
    "Handleiding FinalSurge": handleiding,
    "Rondom je wedstrijd": wedstrijd,
    "Voeding rondom je trainingen": voeding_training,
    "Krachttraining voor hardlopers": kracht,
}

# Speciaal type: geen vast sjabloon, maar de AI bedenkt zelf een heel document.
_VRIJ = "✍️ Vrij document (AI bedenkt het)"


def _veld_input(veld: dict, index: int = 0):
    key = f"doc_f_{veld['veld']}"
    t = veld.get("type")
    if t == "keuze":
        opties = veld.get("opties", [""])
        return st.selectbox(veld["vraag"], opties, index=min(index, len(opties) - 1), key=key)
    if t == "getal":
        return st.text_input(veld["vraag"], key=key, placeholder="bijv. 70")
    return st.text_input(veld["vraag"], key=key)


def render(all_athletes: list):
    st.caption("Kies een document en een atleet. De AI schrijft de persoonlijke stukjes in de "
               "huisstijl; de rest is vaste, onderbouwde inhoud. Je krijgt een deel-klare PDF.")

    label = st.selectbox("Documenttype", list(_DOCS.keys()) + [_VRIJ], key="doc_type")
    is_vrij = label == _VRIJ

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
        _regels = ", ".join(f"{d.get('type', '')}" + (f" — {d['onderwerp']}" if d.get("onderwerp") else "")
                            + f" ({d.get('datum', '')})" for d in eerder)
        st.caption(f"📄 {voornaam} ontving eerder: {_regels}. Dit gaat mee als context, "
                   "zodat de AI voortbouwt in plaats van hetzelfde te herhalen.")
        answers["eerdere_documenten"] = _regels

    if is_vrij:
        st.caption("Geef een onderwerp en wat sturing. De AI bedenkt zelf een compleet "
                   "document (titel, secties, tips, tabellen) in onze huisstijl.")
        onderwerp = st.text_input("Onderwerp", key="doc_vrij_onderwerp",
                                  placeholder="bijv. Vragenlijst hardloopblessures")
        guidance = st.text_area("Guidance (optioneel)", key="doc_vrij_guidance",
                                placeholder="bijv. invulbare vragenlijst, 10 vragen, "
                                            "voor nieuwe atleten, kort en duidelijk")
        if st.button("✍️ Laat AI het document maken", type="primary", key="doc_gen_vrij"):
            if not onderwerp.strip():
                st.warning("Vul eerst een onderwerp in.")
            else:
                _genereer_vrij(onderwerp.strip(), guidance.strip(), answers, user_key)
    else:
        mod = _DOCS[label]

        # Slim voorstel: kreeg deze atleet dit type al eerder? Stel dan de
        # volgende kracht-variant voor (Basis -> Variatie -> Gevorderd).
        suggesties = {}
        if mod is kracht:
            eerder_kracht = sum(1 for d in eerder if d.get("type") == label)
            if eerder_kracht:
                suggesties["variant"] = min(eerder_kracht, 2)  # 1->Variatie, 2+->Gevorderd
                _volgende = list(kracht.VARIANTS.keys())[suggesties["variant"]]
                st.caption(f"💡 {voornaam} kreeg al **{eerder_kracht}×** een krachtdocument. "
                           f"Voorstel: **{_volgende}** voor een frisse prikkel.")

        extra = [v for v in getattr(mod, "INTAKE", []) if v["veld"] != "voornaam"]
        if extra:
            cols = st.columns(min(len(extra), 3))
            for i, v in enumerate(extra):
                with cols[i % len(cols)]:
                    answers[v["veld"]] = _veld_input(v, suggesties.get(v["veld"], 0))

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


def _genereer_vrij(onderwerp: str, guidance: str, answers: dict, user_key: str | None = None):
    answers = {k: v for k, v in answers.items() if v not in (None, "")}

    with st.spinner("De AI bedenkt en schrijft je document…"):
        try:
            out = os.path.join(tempfile.gettempdir(), "bebetter_doc.pdf")
            _gen.render(onderwerp, guidance, answers, out)  # AI verzint + engine rendert
            with open(out, "rb") as f:
                st.session_state["doc_pdf"] = f.read()
        except Exception as e:  # AI-fout, ongeldige JSON, ontbrekend bestand, enz.
            st.session_state.pop("doc_pdf", None)
            st.error(f"Genereren mislukt: {e}")
            return

    naam = answers.get("voornaam", "algemeen")
    st.session_state["doc_pdf_naam"] = f"{onderwerp} - {naam}.pdf"

    # Registreer met onderwerp, zodat het dossier laat zien wat de atleet precies kreeg
    if user_key:
        ok, err = intake_store.log_document(user_key, "Vrij document (AI)", onderwerp)
        if not ok:
            st.warning(f"Document gemaakt, maar niet gelogd in dossier: {err}")
