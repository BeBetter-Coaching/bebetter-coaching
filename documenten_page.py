"""📄 Documenten — genereer een strak, persoonlijk BeBetter-document.

Kies een documenttype en een atleet. De naam (en waar relevant extra velden)
vult de intake van het sjabloon; de AI schrijft de persoonlijke stukjes in de
huisstijl, de rest is vaste, onderbouwde inhoud. Levert een deel-klare PDF.

De documentgenerator zelf leeft in de map docgen/ (engine + sjablonen). Die
zetten we op het pad en gebruiken we hier zonder iets te dupliceren.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

import streamlit as st

import intake_store

_DGDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docgen")
if _DGDIR not in sys.path:
    sys.path.insert(0, _DGDIR)

import template as _tpl  # noqa: E402
import generator as _gen  # noqa: E402
import reportlab_gen as _G  # noqa: E402
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


def _walk_text(node, fn):
    """Loop door een DOC en pas `fn` toe op elke tekst-leaf (tuples/lijsten/dicts intact)."""
    if isinstance(node, str):
        return fn(node)
    if isinstance(node, list):
        return [_walk_text(x, fn) for x in node]
    if isinstance(node, tuple):
        return tuple(_walk_text(x, fn) for x in node)
    if isinstance(node, dict):
        return {k: _walk_text(v, fn) for k, v in node.items()}
    return node


def _tokenize_naam(doc: dict, naam: str) -> dict:
    """Vervang de gebruikte voornaam door {{voornaam}} zodat we later kunnen personaliseren."""
    if not naam:
        return doc
    pat = re.compile(r"\b" + re.escape(naam) + r"\b")
    return _walk_text(doc, lambda s: pat.sub("{{voornaam}}", s))


def _apply_naam(doc: dict, naam: str) -> dict:
    """Vul {{voornaam}} in de hele DOC met `naam` (leeg = token blijft, wordt elders opgevangen)."""
    return _walk_text(doc, lambda s: _tpl.substitute(s, {"voornaam": naam}))


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
        c_dl, c_save = st.columns(2)
        with c_dl:
            st.download_button("⬇️ Download PDF", data=st.session_state["doc_pdf"],
                               file_name=st.session_state.get("doc_pdf_naam", "document.pdf"),
                               mime="application/pdf", key="doc_dl")
        with c_save:
            _bewaarknop()

    _render_bibliotheek(all_athletes)


def _bewaarknop():
    """Knop om het net gegenereerde document in de bibliotheek te bewaren."""
    saveable = st.session_state.get("doc_saveable")
    if not saveable:
        return
    if st.session_state.get("doc_saved_id"):
        st.caption("📚 Bewaard in de bibliotheek.")
        return
    if st.button("💾 Bewaar in bibliotheek", key="doc_save",
                 help="Bewaar dit document zodat je het later opnieuw kunt gebruiken."):
        ok, err, doc_id = intake_store.add_doc_library(saveable)
        if ok:
            st.session_state["doc_saved_id"] = doc_id
            st.rerun()
        else:
            st.error(f"Bewaren mislukt: {err}")


def _eerdere_documenten(user_key: str) -> list:
    """Documenten die deze atleet eerder ontving (nieuwste eerst)."""
    try:
        return intake_store.load_documenten().get(user_key, [])
    except Exception:
        return []


def _bewaar_pdf(doc: dict, out: str):
    """Render de engine-DOC naar PDF en zet de bytes in de sessie."""
    _G.build(doc, out)
    with open(out, "rb") as f:
        st.session_state["doc_pdf"] = f.read()


def _na_generatie(saveable: dict):
    """Reset de bewaarstatus zodat de nieuwe generatie apart bewaard kan worden."""
    st.session_state["doc_saveable"] = saveable
    st.session_state.pop("doc_saved_id", None)


def _genereer(label: str, mod, answers: dict, user_key: str | None = None):
    answers = {k: v for k, v in answers.items() if v not in (None, "")}
    if hasattr(mod, "derive"):
        answers = mod.derive(answers)

    with st.spinner("Document genereren…"):
        try:
            out = os.path.join(tempfile.gettempdir(), "bebetter_doc.pdf")
            resolved = _tpl.resolve_ai(mod.TEMPLATE, answers)  # echte AI voor de intro's (1x)
            doc = _tpl.merge(resolved, answers)
            _bewaar_pdf(doc, out)
        except Exception as e:  # AI-fout, ontbrekend bestand, enz.
            st.session_state.pop("doc_pdf", None)
            st.error(f"Genereren mislukt: {e}")
            return

    naam = answers.get("voornaam", "algemeen")
    st.session_state["doc_pdf_naam"] = f"{label} - {naam}.pdf"
    _titel = label + (f" ({answers['variant_kort']})" if answers.get("variant_kort") else "")
    _used = answers.get("voornaam", "")
    _na_generatie({"titel": _titel, "onderwerp": "", "guidance": "", "voornaam": _used,
                   "bron": f"sjabloon:{label}", "doc": _tokenize_naam(doc, _used)})

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
            spec = _gen.generate_spec(onderwerp, guidance, _gen._context(answers))  # AI 1x
            doc = _gen.build_doc(onderwerp, spec, answers)
            _bewaar_pdf(doc, out)
        except Exception as e:  # AI-fout, ongeldige JSON, ontbrekend bestand, enz.
            st.session_state.pop("doc_pdf", None)
            st.error(f"Genereren mislukt: {e}")
            return

    naam = answers.get("voornaam", "algemeen")
    st.session_state["doc_pdf_naam"] = f"{onderwerp} - {naam}.pdf"
    _used = answers.get("voornaam", "")
    _na_generatie({"titel": onderwerp, "onderwerp": onderwerp, "guidance": guidance,
                   "voornaam": _used, "bron": "vrij", "doc": _tokenize_naam(doc, _used)})

    # Registreer met onderwerp, zodat het dossier laat zien wat de atleet precies kreeg
    if user_key:
        ok, err = intake_store.log_document(user_key, "Vrij document (AI)", onderwerp)
        if not ok:
            st.warning(f"Document gemaakt, maar niet gelogd in dossier: {err}")


# ── Bibliotheek: bewaarde documenten opnieuw gebruiken ──────────────────────
def _render_bibliotheek(all_athletes: list):
    try:
        lib = intake_store.load_doc_library()
    except Exception as e:
        st.caption(f"Bibliotheek niet te laden: {e}")
        return

    st.divider()
    st.subheader("📚 Bibliotheek")
    if not lib:
        st.caption("Nog niks bewaard. Genereer een document en klik op "
                   "**Bewaar in bibliotheek**, dan bouw je hier je eigen database op.")
        return
    st.caption("Bewaarde documenten. Geef ze opnieuw uit (eventueel voor een atleet) "
               "zonder dat de AI het opnieuw hoeft te verzinnen.")

    namen = ["— Algemeen (geen naam) —"] + [a["name"] for a in all_athletes]
    for doc_id, e in sorted(lib.items(), reverse=True):
        titel = e.get("titel") or "(zonder titel)"
        with st.expander(f"{titel}  ·  {e.get('datum', '')}"):
            if e.get("guidance"):
                st.caption(f"Guidance: {e['guidance']}")

            keuze = st.selectbox("Voor welke atleet?", namen, key=f"lib_ath_{doc_id}")
            atleet = next((a for a in all_athletes if a["name"] == keuze), None)
            voornaam = "" if keuze.startswith("—") else keuze.split()[0]
            user_key = atleet.get("user_key") if atleet else None

            c1, c2 = st.columns(2)
            with c1:
                if st.button("♻️ Opnieuw uitgeven", key=f"lib_gen_{doc_id}"):
                    _hergebruik(doc_id, e, voornaam, user_key)
            with c2:
                if st.button("🗑 Verwijderen", key=f"lib_del_{doc_id}"):
                    ok, err = intake_store.delete_doc_library(doc_id)
                    if ok:
                        st.rerun()
                    else:
                        st.error(f"Verwijderen mislukt: {err}")

            if st.session_state.get("lib_pdf_id") == doc_id and st.session_state.get("lib_pdf"):
                st.download_button("⬇️ Download PDF", data=st.session_state["lib_pdf"],
                                   file_name=st.session_state.get("lib_pdf_naam", "document.pdf"),
                                   mime="application/pdf", key=f"lib_dl_{doc_id}")


def _hergebruik(doc_id: str, entry: dict, voornaam: str, user_key: str | None):
    """Render een bewaard document opnieuw (geen AI nodig), evt. voor een atleet."""
    doc = entry.get("doc")
    if not doc:
        st.error("Dit bibliotheek-item bevat geen document meer.")
        return
    # Naam overal in de tekst meelaten lopen: gekozen atleet, of de oorspronkelijke
    # naam als je 'm algemeen uitgeeft (dan blijft het document zoals bewaard).
    naam = voornaam or entry.get("voornaam", "")
    doc = _apply_naam(doc, naam) if naam else dict(doc)
    if voornaam:
        doc = {**doc, "voor": f"Voor {voornaam}"}

    try:
        out = os.path.join(tempfile.gettempdir(), "bebetter_lib.pdf")
        _G.build(doc, out)
        with open(out, "rb") as f:
            st.session_state["lib_pdf"] = f.read()
    except Exception as e:
        st.error(f"Opnieuw uitgeven mislukt: {e}")
        return

    naam = voornaam or "algemeen"
    st.session_state["lib_pdf_id"] = doc_id
    st.session_state["lib_pdf_naam"] = f"{entry.get('titel', 'document')} - {naam}.pdf"

    if user_key:
        ok, err = intake_store.log_document(user_key, entry.get("titel", "Document"),
                                            entry.get("onderwerp", ""))
        if not ok:
            st.warning(f"Uitgegeven, maar niet gelogd in dossier: {err}")
    st.rerun()
