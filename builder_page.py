"""Schema bouwen (builder) — 4-staps flow: intake → plan → CSV → import in FinalSurge.

Uit main.py gelicht. De builder-specifieke helpers (_prefill_builder_from_prev,
_DAG_LABELS, _dagen_labels, _render_bijsturen_flow en de _*_builder_state-trio)
verhuisden mee; ze werden alleen door de builder gebruikt. Uitzondering: main.py
roept _load_builder_state() bij elke run aan (state-herstel), nu via
builder_page._load_builder_state(). Helper- en render-body verbatim (4-spatie
indent = functie-body, geen herindent).
"""
import html as _html_mod
from datetime import date, timedelta

import streamlit as st

import fs_client
import intake_store
import schema_builder


def _esc(s) -> str:
    return _html_mod.escape(str(s or ""))


def _prefill_builder_from_prev(prev: dict) -> None:
    """Vul de bouwer-velden op stap 1 vanuit een eerder opgeslagen builder-intake.

    Gebruikt door de teruglaad-knop en door 'bijsturen'. Zet
    builder_fields_loaded zodat de sync-blok het daarna niet overschrijft.
    De startdatum wordt bewust NIET gezet (die verschilt per scenario).
    """
    g = prev.get
    st.session_state["builder_naam"]              = g("naam", "")
    st.session_state["builder_doel"]              = g("doel", "")
    st.session_state["builder_volume"]            = g("huidig_volume", "")
    st.session_state["builder_dagen_sel"]         = _dagen_labels(g("trainingsdagen", ""))
    st.session_state["builder_referentie"]        = g("referentie_prestatie", "")
    st.session_state["builder_tijd_per_training"] = g("tijd_per_training", "")
    st.session_state["builder_langste_afstand"]   = g("langste_afstand", "")
    st.session_state["builder_blessure"]          = g("blessurehistorie", "")
    st.session_state["builder_andere"]            = g("andere_sporten", "")
    st.session_state["builder_coach_notitie"]     = g("coach_notitie", "")
    st.session_state["builder_wat_werkte"]        = g("wat_werkte", "")
    st.session_state["builder_wat_niet_werkte"]   = g("wat_niet_werkte", "")
    st.session_state["builder_tussenraces"]       = g("tussenraces", "")
    st.session_state["builder_werkdruk"]          = g("werkdruk", "Normaal")
    st.session_state["builder_op_tijd"]           = g("op_tijd", False)
    _pzt = g("zone_type", "tempo")
    st.session_state["builder_zone_type"]         = "hartslag (bpm)" if _pzt == "hartslag" else "tempo (min/km)"
    _psed = g("schema_einddatum", "")
    st.session_state["builder_schema_einddatum"]  = date.fromisoformat(_psed) if _psed else None
    st.session_state["builder_fields_loaded"] = True


_DAG_LABELS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]


def _dagen_labels(trainingsdagen_str: str) -> list[str]:
    """Zet een opgeslagen trainingsdagen-string ('ma/wo/vr') om naar multiselect-labels."""
    return [_DAG_LABELS[i] for i in schema_builder._parse_weekdagen(trainingsdagen_str or "")]


def _render_bijsturen_flow(athlete_key_selected: str) -> None:
    """Bijsturen: resterende geplande trainingen wissen en de weken herbouwen.

    Alleen getoond in de 'bijsturen'-modus. Bij volledig succes worden
    _pending_prefill/_pending_bijstuur/_pending_start gezet zodat de bovenkant van
    stap 1 de intake teruglaadt en de startdatum klaarzet. Beschermt het verleden
    (alleen geplande, niet-race, datum >= vanaf via fs_client.get_planned_workouts_from).
    """
    if st.session_state.get("bs_msg"):
        st.success(st.session_state.pop("bs_msg"))
    st.caption(
        "Verwijdert de **geplande** trainingen vanaf een datum, zodat je de "
        "resterende weken opnieuw kunt bouwen. Het verleden en al uitgevoerde "
        "trainingen blijven staan."
    )
    _bs_vanaf = st.date_input(
        "Wis geplande trainingen vanaf",
        value=st.session_state.get("builder_startdatum", date.today()),
        key="bs_vanaf", format="DD/MM/YYYY",
    )
    _has_prev = bool(st.session_state.get("laatste_intakes", {}).get(athlete_key_selected))
    st.text_area(
        "Bijstuur-instructie voor de AI",
        key="bs_instructie",
        height=80,
        placeholder="bijv. 3 weken niet getraind i.v.m. klachten — bouw omvang en "
                    "intensiteit rustig weer op. Doel blijft hetzelfde.",
        help="Wordt als belangrijke coach-notitie meegegeven bij het herbouwen. "
             "Beschrijf kort wat er veranderd is en hoe je wilt bijsturen.",
    )
    if _has_prev:
        st.caption("✅ Na wissen worden doel, zones en volume automatisch teruggeladen — je hoeft de intake niet opnieuw in te vullen.")
    else:
        st.caption("⚠️ Nog geen opgeslagen schema-intake voor deze atleet — na wissen vul je de intake één keer in (daarna wordt 'ie bewaard).")
    if st.button("🔍 Toon geplande trainingen", key="bs_show", use_container_width=True):
        with st.spinner("Ophalen uit FinalSurge…"):
            st.session_state["bs_lijst"] = fs_client.get_planned_workouts_from(athlete_key_selected, _bs_vanaf)
        st.session_state["bs_lijst_key"] = athlete_key_selected
        st.session_state.pop("bs_confirm", None)

    _lijst = (
        st.session_state.get("bs_lijst")
        if st.session_state.get("bs_lijst_key") == athlete_key_selected
        else None
    )
    if _lijst is not None:
        if not _lijst:
            st.info("Geen geplande trainingen gevonden vanaf die datum.")
        else:
            st.markdown(f"**{len(_lijst)} geplande trainingen worden verwijderd:**")
            for _w in _lijst[:40]:
                st.markdown(f"- {date.fromisoformat(_w['date']).strftime('%d-%m')} — {_w['name']}")
            if len(_lijst) > 40:
                st.caption(f"…en nog {len(_lijst) - 40} meer.")
            _confirm = st.checkbox(
                f"Ja, verwijder deze {len(_lijst)} trainingen definitief uit FinalSurge",
                key="bs_confirm",
            )
            if st.button("🗑️ Verwijderen", disabled=not _confirm, key="bs_delete"):
                _prog = st.progress(0)
                _fout = []
                for _i, _w in enumerate(_lijst):
                    try:
                        fs_client.delete_workout(_w["key"], athlete_key_selected)
                    except Exception as _e:
                        _fout.append(f"{_w['date']} {_w['name']}: {_e}")
                    _prog.progress((_i + 1) / len(_lijst))
                _prog.empty()
                _gelukt = len(_lijst) - len(_fout)
                if _fout:
                    # Deels mislukt: blijf staan zodat de coach ziet wat faalde.
                    st.warning(f"{_gelukt}/{len(_lijst)} verwijderd — {len(_fout)} mislukt.")
                    with st.expander("Fouten bekijken"):
                        for _f in _fout:
                            st.code(_f)
                    st.session_state["bs_lijst"] = fs_client.get_planned_workouts_from(athlete_key_selected, _bs_vanaf)
                else:
                    # Volledig gelukt: intake teruglaadklaarzetten + bijstuur-instructie +
                    # startdatum (via pending, want de widgets zijn deze run al geïnstantieerd).
                    _prev = st.session_state.get("laatste_intakes", {}).get(athlete_key_selected)
                    _instr = (st.session_state.get("bs_instructie") or "").strip()
                    if _prev:
                        st.session_state["_pending_prefill"] = _prev
                        if _instr:
                            st.session_state["_pending_bijstuur"] = _instr
                        _staart = " Doel, zones en volume zijn teruggeladen — check de velden en klik op genereren."
                    else:
                        _staart = " Vul de intake nog één keer in en genereer."
                    st.session_state["bs_msg"] = (
                        f"✅ {_gelukt} trainingen verwijderd. Startdatum staat op "
                        f"{_bs_vanaf.strftime('%d-%m-%Y')}." + _staart
                    )
                    st.session_state["_pending_start"] = _bs_vanaf
                    st.session_state.pop("bs_lijst", None)
                    st.session_state.pop("bs_confirm", None)
                    try:
                        del st.session_state["bs_instructie"]
                    except Exception:
                        pass
                    st.rerun()


def _save_builder_state():
    """Bewaar builder_intake, builder_plan, builder_step (GitHub-backed)."""
    state = {
        "builder_step":   st.session_state.get("builder_step", 1),
        "builder_intake": st.session_state.get("builder_intake"),
        "builder_plan":   st.session_state.get("builder_plan"),
    }
    # uploaded_images bevatten base64-data — te groot, weglaten
    if state["builder_intake"]:
        intake_copy = dict(state["builder_intake"])
        intake_copy.pop("uploaded_images", None)
        state["builder_intake"] = intake_copy
    try:
        intake_store.save_builder_state(state)
    except Exception:
        pass

def _load_builder_state():
    """Herstel builder-state als session state leeg is. Eén GitHub-call per sessie."""
    if st.session_state.get("_builder_state_checked"):
        return
    st.session_state["_builder_state_checked"] = True
    # Intake al in memory → niets doen, laat stap-navigatie intact
    if "builder_intake" in st.session_state:
        return
    try:
        state = intake_store.load_builder_state()
    except Exception:
        return
    if not state:
        return
    if state.get("builder_intake"):
        st.session_state["builder_intake"] = state["builder_intake"]
        st.session_state["builder_fields_loaded"] = False  # velden nog laden
    if state.get("builder_plan") is not None:
        st.session_state["builder_plan"] = state["builder_plan"]
    # Als intake aanwezig is maar stap=1, ga direct naar stap 2
    saved_step = state.get("builder_step", 1)
    if state.get("builder_intake") and saved_step == 1:
        saved_step = 2
    st.session_state["builder_step"] = saved_step

def _clear_builder_state():
    """Wis de persistente builder-state (na handmatig reset)."""
    try:
        intake_store.clear_builder_state()
    except Exception:
        pass


def render(athletes_by_group):
    # Toon herstel-melding als state hersteld is vanuit schijf
    if st.session_state.get("builder_intake") and st.session_state.get("builder_step", 1) > 1:
        intake_naam = st.session_state["builder_intake"].get("naam", "")
        c_msg, c_reset = st.columns([5, 1])
        c_msg.info(f"↩️ Sessie hersteld voor **{intake_naam}** — je kunt verder waar je gebleven was.")
        with c_reset:
            if st.button("🗑️ Nieuw", key="btn_reset_intake"):
                for k in ["builder_intake", "builder_plan", "builder_csv",
                          "builder_workouts", "builder_workouts_import",
                          "builder_chat_history", "builder_step", "builder_excluded",
                          "builder_referentie", "builder_tijd_per_training",
                          "builder_langste_afstand", "builder_kwaliteitservaring",
                          "builder_herstelcapaciteit", "builder_werkdruk",
                          "builder_ondergrond", "builder_race_prioriteit",
                          "builder_tussenraces", "builder_coach_notitie",
                          "builder_wat_werkte", "builder_wat_niet_werkte",
                          "builder_mode", "builder_dagen_sel",
                          "builder_import_done", "schema_bericht"]:
                    st.session_state.pop(k, None)
                _clear_builder_state()
                st.rerun()

    # ── Stap-indicator ──────────────────────────────────────────────────────
    if "builder_step" not in st.session_state:
        st.session_state["builder_step"] = 1

    step = st.session_state["builder_step"]

    def _set_step(s):
        if s == 1:
            # Reset de sync-vlag zodat velden opnieuw geladen worden vanuit builder_intake
            st.session_state["builder_fields_loaded"] = False
        st.session_state["builder_step"] = s
        st.rerun()

    step_labels = ["1 · Intake", "2 · Plan", "3 · CSV", "4 · Import"]
    pills_html = '<div class="bb-step-row">'
    for i, label in enumerate(step_labels, 1):
        cls = "active" if step == i else ("done" if step > i else "")
        suffix = " ✓" if step > i else ""
        pills_html += f'<div class="bb-step-pill {cls}">{label}{suffix}</div>'
    pills_html += '</div>'
    st.markdown(pills_html, unsafe_allow_html=True)
    st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)

    # ── Atleet selectie (altijd beschikbaar bovenaan) ───────────────────────
    all_athletes = sorted(
        [a for members in athletes_by_group.values() for a in members],
        key=lambda x: x["name"],
    )
    athlete_options = {a["name"]: a["user_key"] for a in all_athletes}

    # ===========================================================================
    # STAP 1 — INTAKE
    # ===========================================================================

    if step == 1:
        # ── Modus-keuze: tegels als ingang i.p.v. één groot formulier ──────────
        if not st.session_state.get("builder_mode"):
            st.markdown("<div class='bb-intake-label'>Waarmee wil je beginnen?</div>", unsafe_allow_html=True)
            _tiles = [
                ("nieuw", "🆕", "Nieuw schema",
                 "Volledige intake voor een nieuwe atleet of een frisse start.",
                 "Kies nieuw", "primary"),
                ("verlengen", "🔁", "Verlengen",
                 "Vervolgblok naar hetzelfde doel, sluit aan op het lopende schema.",
                 "Kies verlengen", "secondary"),
                ("bijsturen", "🩹", "Bijsturen",
                 "Resterende trainingen wissen en de weken opnieuw opbouwen.",
                 "Kies bijsturen", "secondary"),
            ]
            _tcols = st.columns(3, gap="large")
            for _col, (_mkey, _icon, _titel, _desc, _btn, _btype) in zip(_tcols, _tiles):
                with _col:
                    st.markdown(f"""
                    <div class="bb-card" style="height:210px; min-height:210px;">
                        <div class="bb-card-icon">{_icon}</div>
                        <p class="bb-card-title">{_esc(_titel)}</p>
                        <p class="bb-card-desc">{_esc(_desc)}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    st.markdown("")
                    if st.button(_btn, key=f"mode_{_mkey}", type=_btype, use_container_width=True):
                        st.session_state["builder_mode"] = _mkey
                        st.rerun()
            st.stop()

        builder_mode = st.session_state["builder_mode"]
        _MODE_LABEL = {"nieuw": "🆕 Nieuw schema", "verlengen": "🔁 Verlengen", "bijsturen": "🩹 Bijsturen"}
        _cmh, _cmb = st.columns([5, 1])
        _cmh.markdown(
            f"<div class='bb-intake-label'>Stap 1 — Intake · {_MODE_LABEL.get(builder_mode, '')}</div>",
            unsafe_allow_html=True,
        )
        with _cmb:
            if st.button("← Andere keuze", key="btn_mode_back"):
                st.session_state.pop("builder_mode", None)
                st.rerun()

        # Uitgestelde prefill (van bijsturen): moet VÓÓR alle stap-1-widgets worden
        # toegepast — een widget-key mag na instantiatie niet meer via session_state.
        if "_pending_prefill" in st.session_state:
            _prefill_builder_from_prev(st.session_state.pop("_pending_prefill"))
            _pend_instr = st.session_state.pop("_pending_bijstuur", "")
            if _pend_instr:
                _b = st.session_state.get("builder_coach_notitie", "") or ""
                # Strip een eventuele eerdere bijstuur-regel zodat die zich niet opstapelt.
                _b = "\n".join(
                    r for r in _b.splitlines() if not r.startswith("⚠️ BIJSTURING SCHEMA")
                ).strip()
                st.session_state["builder_coach_notitie"] = (
                    f"⚠️ BIJSTURING SCHEMA — {_pend_instr}" + ("\n\n" + _b if _b else "")
                )

        # Vul widget-keys vanuit builder_intake — eenmalig bij binnenkomst op stap 1.
        # Daarna niet meer overschrijven zodat gebruikerswijzigingen (zoals checkbox) bewaard blijven.
        _existing = st.session_state.get("builder_intake") or {}
        if _existing and not st.session_state.get("builder_fields_loaded", False):
            st.session_state["builder_naam"]              = _existing.get("naam", "")
            st.session_state["builder_doel"]              = _existing.get("doel", "")
            st.session_state["builder_volume"]            = _existing.get("huidig_volume", "")
            st.session_state["builder_dagen_sel"]         = _dagen_labels(_existing.get("trainingsdagen", ""))
            st.session_state["builder_referentie"]        = _existing.get("referentie_prestatie", "")
            st.session_state["builder_tijd_per_training"] = _existing.get("tijd_per_training", "")
            st.session_state["builder_langste_afstand"]   = _existing.get("langste_afstand", "")
            st.session_state["builder_blessure"]          = _existing.get("blessurehistorie", "")
            st.session_state["builder_andere"]            = _existing.get("andere_sporten", "")
            st.session_state["builder_coach_notitie"]     = _existing.get("coach_notitie", "")
            st.session_state["builder_wat_werkte"]        = _existing.get("wat_werkte", "")
            st.session_state["builder_wat_niet_werkte"]   = _existing.get("wat_niet_werkte", "")
            st.session_state["builder_tussenraces"]       = _existing.get("tussenraces", "")
            st.session_state["builder_werkdruk"]          = _existing.get("werkdruk", "")
            st.session_state["builder_op_tijd"]           = _existing.get("op_tijd", False)
            _zt = _existing.get("zone_type", "tempo")
            st.session_state["builder_zone_type"]         = "hartslag (bpm)" if _zt == "hartslag" else "tempo (min/km)"
            _sed = _existing.get("schema_einddatum", "")
            st.session_state["builder_schema_einddatum"]  = date.fromisoformat(_sed) if _sed else None
            st.session_state["builder_fields_loaded"]     = True  # niet opnieuw laden

        if builder_mode == "nieuw":
            client_type = st.radio(
                "Type klant",
                options=["🆕 Nieuwe klant", "🔄 Bestaande klant"],
                horizontal=True,
                key="builder_client_type",
            )
            is_new = "Nieuwe" in client_type
        else:
            # Verlengen/bijsturen betreft altijd een bestaande atleet met historie.
            is_new = False
            if builder_mode == "verlengen":
                st.caption("Doorbouwen naar hetzelfde doel. Laad het vorige schema terug en zet de startdatum ná de laatste training.")
            else:
                st.caption("Wis eerst de resterende trainingen hieronder; daarna worden doel/zones/volume automatisch teruggeladen.")
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)

        # ── KOLOM LINKS: Doel & Planning | RECHTS: Training & Niveau ─────────
        # Bij Nieuw: twee kolommen naast elkaar. Bij Verlengen/Bijsturen: essentie
        # breed, en 'Training & niveau' ingeklapt (details komen uit het vorige schema).
        if builder_mode == "nieuw":
            col_l, col_r = st.columns(2, gap="large")
        else:
            col_l = st.container()
            # Ingeklapt als de details al zijn teruggeladen; open als de intake nog
            # leeg is (bijv. bijsturen zonder opgeslagen schema) zodat verplichte
            # velden zichtbaar zijn i.p.v. een onverklaarbaar uitgeschakelde knop.
            _details_leeg = not (st.session_state.get("builder_volume") or "").strip()
            col_r = st.expander(
                "📋 Details uit vorig schema — aanpassen indien nodig",
                expanded=_details_leeg,
            )

        with col_l:
            st.markdown("<div class='bb-intake-label'>Doel & planning</div>", unsafe_allow_html=True)
            selected_athlete_name = st.selectbox(
                "Atleet *", options=list(athlete_options.keys()), key="builder_athlete",
            )
            athlete_key_selected = athlete_options[selected_athlete_name]
            # Voornaam betrouwbaar overnemen — óók bij wisselen van atleet (niet
            # alleen de eerste keer). Anders bleef de naam van de vorige atleet staan.
            if st.session_state.get("_builder_last_athlete") != athlete_key_selected:
                st.session_state["builder_naam"] = selected_athlete_name.split()[0] if selected_athlete_name else ""
                st.session_state["_builder_last_athlete"] = athlete_key_selected

            # ── Koppeling met intake-module: gegevens automatisch inladen ──
            if "intakes" not in st.session_state:
                st.session_state["intakes"] = intake_store.load_intakes()
            _saved_ik = st.session_state["intakes"].get(athlete_key_selected)
            # Dossier-intake in ALLE modi aanbieden: ook bij verlengen/bijsturen wil je
            # de bestaande intake kunnen inladen als er (nog) geen bouwer-schema bewaard is.
            if _saved_ik:
                if st.button(
                    f"📥 Intake van {_saved_ik.get('naam') or selected_athlete_name.split()[0]} laden "
                    f"(bijgewerkt {_saved_ik.get('updated_at', '?')})",
                    key="btn_load_intake",
                    use_container_width=True,
                ):
                    st.session_state["builder_naam"]              = _saved_ik.get("naam", "")
                    st.session_state["builder_doel"]              = _saved_ik.get("doel", "")
                    st.session_state["builder_volume"]            = _saved_ik.get("huidig_volume", "")
                    st.session_state["builder_dagen_sel"]         = _dagen_labels(_saved_ik.get("trainingsdagen", ""))
                    st.session_state["builder_referentie"]        = _saved_ik.get("referentie_prestatie", "")
                    st.session_state["builder_tijd_per_training"] = _saved_ik.get("tijd_per_training", "")
                    st.session_state["builder_langste_afstand"]   = _saved_ik.get("langste_afstand", "")
                    st.session_state["builder_blessure"]          = _saved_ik.get("blessurehistorie", "")
                    st.session_state["builder_andere"]            = _saved_ik.get("andere_sporten", "")
                    # Coach-notitie + intake-achtergrond (nieuwe-klant-velden)
                    # samenvoegen zodat alles in het AI-prompt terechtkomt
                    _ctx_extra = [
                        f"{_lbl}: {_saved_ik[_f]}"
                        for _lbl, _f in [
                            ("Motivatie", "motivatie"),
                            ("Loopervaring", "loopervaring"),
                            ("PR's", "prs"),
                            ("Eerdere schema-ervaring", "eerdere_schemas"),
                            ("Slaap/leefritme", "slaap"),
                            ("Huidige klachten", "huidige_klachten"),
                            ("Vindt leuk", "leuk"),
                            ("Vindt niet leuk", "niet_leuk"),
                            ("Wedstrijd", "wedstrijddatum_tekst"),
                        ]
                        if _saved_ik.get(_f)
                    ]
                    st.session_state["builder_coach_notitie"] = "\n".join(
                        filter(None, [_saved_ik.get("coach_notitie", "")] + _ctx_extra)
                    )
                    st.session_state["builder_wat_werkte"]        = _saved_ik.get("wat_werkte", "")
                    st.session_state["builder_wat_niet_werkte"]   = _saved_ik.get("wat_niet_werkte", "")
                    st.session_state["builder_kwaliteitservaring"] = _saved_ik.get("kwaliteitservaring", "Enige ervaring")
                    st.session_state["builder_herstelcapaciteit"] = _saved_ik.get("herstelcapaciteit", "Normaal")
                    st.session_state["builder_werkdruk"]          = _saved_ik.get("werkdruk", "Normaal")
                    st.session_state["builder_ondergrond"]        = _saved_ik.get("loopondergrond", ["Weg"]) or ["Weg"]
                    st.session_state["builder_op_tijd"]           = _saved_ik.get("op_tijd", False)
                    st.session_state["builder_leeftijd"]          = _saved_ik.get("leeftijd", "")
                    st.session_state["builder_horloge"]           = _saved_ik.get("horloge", "")
                    # Voorkom dat de sync-blok dit overschrijft
                    st.session_state["builder_fields_loaded"] = True
                    st.rerun()

            # ── Verlengen / bijsturen: laatst gebouwde schema-intake terugladen ──
            # Bevat de exacte bouwer-velden (doel, zones, volume, dagen…) van het
            # vorige schema, zodat je een vervolgblok of aanpassing niet opnieuw
            # hoeft in te vullen. Startdatum wordt bewust NIET teruggezet.
            if "laatste_intakes" not in st.session_state:
                st.session_state["laatste_intakes"] = intake_store.load_laatste_intakes()
            _prev_ik = st.session_state["laatste_intakes"].get(athlete_key_selected)
            if _prev_ik and builder_mode in ("verlengen", "bijsturen"):
                _opg = (_prev_ik.get("_opgeslagen", "") or "")[:10]
                if st.button(
                    f"🔁 Vorig schema terugladen — verlengen/bijsturen"
                    + (f" (van {_opg})" if _opg else ""),
                    key="btn_load_laatste_intake",
                    use_container_width=True,
                    help="Vult de intake van het vorige schema in (doel, zones, volume, "
                         "trainingsdagen…). Handig om door te bouwen naar hetzelfde doel of "
                         "de resterende weken bij te sturen. Kies daarna zelf de nieuwe startdatum.",
                ):
                    _prefill_builder_from_prev(_prev_ik)
                    st.rerun()
            naam = st.text_input("Naam in coaching-tekst *", key="builder_naam", placeholder="bijv. Lisa")
            doel = st.text_area(
                "Doelstelling *", key="builder_doel", height=70,
                placeholder="bijv. 10km in sub 55min, of: HYROX afmaken in Amsterdam",
            )
            # Pas een uitgestelde startdatum toe (gezet door de verleng-/bijstuur-knop)
            # VÓÓR de date_input instantieert — een widget-key mag daarna niet meer
            # via session_state gewijzigd worden.
            if "_pending_start" in st.session_state:
                st.session_state["builder_startdatum"] = st.session_state.pop("_pending_start")
            if "builder_startdatum" not in st.session_state:
                st.session_state["builder_startdatum"] = date.today() + timedelta(days=(7 - date.today().weekday()))
            startdatum = st.date_input(
                "Startdatum schema *",
                key="builder_startdatum",
                format="DD/MM/YYYY",
            )
            # Verlengen: zet de start op de dag ná de laatste geplande training,
            # zodat je een vervolgblok bouwt dat naadloos aansluit op het huidige schema.
            if builder_mode == "verlengen" and st.button(
                "📆 Verlengen: start ná laatste geplande training",
                key="btn_verleng_startdatum",
                use_container_width=True,
                help="Zoekt de laatste geplande training van deze atleet in FinalSurge "
                     "en zet de startdatum op de dag erna. Combineer met '🔁 Vorig schema "
                     "terugladen' om door te bouwen naar hetzelfde doel.",
            ):
                with st.spinner("Laatste geplande training zoeken…"):
                    _last = fs_client.get_last_planned_date(athlete_key_selected)
                if _last:
                    _nieuwe_start = date.fromisoformat(_last) + timedelta(days=1)
                    st.session_state["_pending_start"] = _nieuwe_start
                    st.session_state["_verleng_msg"] = f"Startdatum gezet op {_nieuwe_start.strftime('%d-%m-%Y')} (laatste training: {date.fromisoformat(_last).strftime('%d-%m-%Y')})."
                else:
                    st.session_state["_verleng_msg"] = "⚠️ Geen geplande trainingen gevonden — stel de startdatum handmatig in."
                st.rerun()
            if st.session_state.get("_verleng_msg"):
                st.caption(st.session_state.pop("_verleng_msg"))

            # Bijsturen-flow (alleen in bijsturen-modus): wis resterende trainingen
            # en bouw de weken opnieuw. Body staat in _render_bijsturen_flow.
            if builder_mode == "bijsturen":
                st.markdown("<div class='bb-intake-label'>Resterende trainingen wissen</div>", unsafe_allow_html=True)
                _render_bijsturen_flow(athlete_key_selected)

            # Aantal weken OF vaste einddatum — twee ingangen
            c_wk, c_of = st.columns([3, 1])
            with c_wk:
                weken_keuze = st.number_input(
                    "Aantal weken schema", min_value=1, max_value=52, value=8, step=1,
                    key="builder_weken_keuze",
                    help="De app berekent de einddatum automatisch op basis van de startdatum.",
                )
            with c_of:
                st.markdown("<div style='padding-top:1.8rem; color:#8FA8CE; font-size:0.8rem;'>of kies datum:</div>", unsafe_allow_html=True)

            # Maandag-uitgelijnd: einddatum = zondag van week N (geteld vanaf de maandag
            # van de startweek), zodat weken → datum → weken consistent terugrekent en
            # aansluit op hoe build_csv_prompt de weken opbouwt.
            _einddatum_auto = (
                startdatum - timedelta(days=startdatum.weekday())
                + timedelta(weeks=int(weken_keuze)) - timedelta(days=1)
            )
            c_datum1, c_datum2 = st.columns(2)
            with c_datum1:
                schema_einddatum = st.date_input(
                    "Schema eindigt op",
                    value=_einddatum_auto,
                    key="builder_schema_einddatum",
                    min_value=date.today(),
                    format="DD/MM/YYYY",
                    help="Automatisch berekend op basis van startdatum + weken. Pas aan als gewenst.",
                )
            with c_datum2:
                wedstrijddatum = st.date_input(
                    "Datum hoofddoel",
                    value=None,
                    key="builder_wedstrijddatum",
                    min_value=date.today(),
                    format="DD/MM/YYYY",
                    help="De uiteindelijke wedstrijddatum. Mag verder weg liggen dan het schema.",
                )
            schema_target = schema_einddatum or wedstrijddatum
            if schema_target and startdatum:
                # Maandag-uitgelijnd tellen — consistent met build_csv_prompt dat weken
                # vanaf de maandag van de startweek t/m de zondag van de eindweek opbouwt.
                # Floor-deling vanaf een losse startdatum telde eerder een week te veel/weinig.
                _start_monday = startdatum - timedelta(days=startdatum.weekday())
                _end_sunday = schema_target + timedelta(days=(6 - schema_target.weekday()))
                weken_berekend = max(1, ((_end_sunday - _start_monday).days + 1) // 7)
                if weken_berekend > 20:
                    st.warning(f"⚠️ {weken_berekend} weken is erg lang — overweeg dit schema in 2 blokken te splitsen.")
                else:
                    st.caption(f"📅 {weken_berekend} weken schema · eindigt {schema_einddatum.day}/{schema_einddatum.month}/{schema_einddatum.year}")
                if wedstrijddatum and schema_einddatum and wedstrijddatum > schema_einddatum:
                    st.caption(f"🎯 Hoofddoel: {wedstrijddatum.day}/{wedstrijddatum.month}/{wedstrijddatum.year} ({(wedstrijddatum - schema_einddatum).days // 7} weken na dit schema)")
            race_prioriteit = st.radio(
                "Race prioriteit",
                options=["A-race (volledig pieken)", "B-race (lichte taper)", "C-race (geen taper)"],
                horizontal=True, key="builder_race_prioriteit",
            )
            tussenraces = st.text_input(
                "Tussenraces", key="builder_tussenraces",
                placeholder="bijv. 15 jun 10km, 20 jul 5km",
            )

        with col_r:
            st.markdown("<div class='bb-intake-label'>Training & niveau</div>", unsafe_allow_html=True)
            referentie_prestatie = st.text_input(
                "Recente referentieprestatie *", key="builder_referentie",
                placeholder="bijv. 5km in 22:30 (vorige maand)",
            )
            huidig_volume = st.text_input(
                "Huidig wekelijks volume *", key="builder_volume",
                placeholder="bijv. 25-30 km/week",
            )
            # Klikbare weekdag-selectie i.p.v. vrije tekst — deterministisch, dus
            # geen di/do → wo/vr of "t/m"-verrassingen meer.
            _dagen_sel = st.multiselect(
                "Trainingsdagen *", options=_DAG_LABELS, key="builder_dagen_sel",
                help="Klik de dagen aan waarop getraind wordt.",
            )
            trainingsdagen = "/".join(
                lbl.lower() for lbl in sorted(_dagen_sel, key=_DAG_LABELS.index)
            )
            tijd_per_training = st.text_input(
                "Tijd per training *", key="builder_tijd_per_training",
                placeholder="bijv. ma: 45min, wo: 60min, zo: 90min",
            )
            langste_afstand = st.text_input(
                "Langste afstand recent", key="builder_langste_afstand",
                placeholder="bijv. 14km (3 weken geleden)",
            )
            kwaliteitservaring = st.radio(
                "Ervaring intervals/tempo",
                options=["Weinig/geen", "Enige ervaring", "Regelmatig"],
                horizontal=True, key="builder_kwaliteitservaring",
            )
            op_tijd = st.checkbox(
                "Schema op tijd (minuten) i.p.v. kilometers",
                key="builder_op_tijd",
                help="Trainingen worden beschreven in minuten (bijv. '45 min Z2') en geïmporteerd als tijdsduur.",
            )
            if is_new:
                c_lft, c_hor = st.columns(2)
                with c_lft:
                    leeftijd = st.text_input("Leeftijd", key="builder_leeftijd", placeholder="bijv. 34")
                with c_hor:
                    horloge = st.text_input("Horloge / GPS", key="builder_horloge", placeholder="bijv. Garmin 255")
            else:
                leeftijd = horloge = ""

        # ── ATLEETPROFIEL (compact, onder de twee kolommen) ─────────────────
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
        st.markdown("<div class='bb-intake-label'>Atleetprofiel</div>", unsafe_allow_html=True)
        cp1, cp2, cp3 = st.columns(3)
        with cp1:
            herstelcapaciteit = st.radio(
                "Herstelcapaciteit", options=["Langzaam", "Normaal", "Snel"],
                horizontal=True, index=1, key="builder_herstelcapaciteit",
            )
        with cp2:
            werkdruk = st.radio(
                "Werkdruk buiten sport", options=["Laag", "Normaal", "Hoog"],
                horizontal=True, index=1, key="builder_werkdruk",
            )
        with cp3:
            loopondergrond = st.multiselect(
                "Loopondergrond",
                options=["Weg", "Trail", "Baan", "Loopband"],
                default=["Weg"], key="builder_ondergrond",
            )

        ca, cb = st.columns(2)
        with ca:
            blessurehistorie = st.text_input(
                "Blessurehistorie", key="builder_blessure",
                placeholder="bijv. linkerknie (2023), schouder (recent)",
            )
        with cb:
            andere_sporten = st.text_input(
                "Andere sporten / verplichtingen", key="builder_andere",
                placeholder="bijv. HYROX 2x/week, zwemmen wo",
            )

        coach_notitie = st.text_area(
            "⭐ Coach notitie — jouw kennis over deze atleet",
            key="builder_coach_notitie", height=80,
            placeholder="bijv. neiging te snel op te bouwen, mentaal sterk, sloeg vorig schema half af door kniepijn bij hoge km",
        )

        if not is_new:
            cw1, cw2 = st.columns(2)
            with cw1:
                wat_werkte = st.text_input(
                    "Wat werkte goed", key="builder_wat_werkte",
                    placeholder="bijv. vaste weekstructuur, progressieve lange duurlopen",
                )
            with cw2:
                wat_niet_werkte = st.text_input(
                    "Wat werkte niet", key="builder_wat_niet_werkte",
                    placeholder="bijv. te veel intervals te snel",
                )
        else:
            wat_werkte = wat_niet_werkte = ""

        # ── ZONES ───────────────────────────────────────────────────────────
        if is_new:
            # Nieuwe klant: handmatige zone-invoer. De coach bepaalt zelf hoe snel
            # elke zone is (zonegrenzen staan in FinalSurge) — de app leidt geen
            # tempo's af.
            st.markdown("<div class='bb-intake-label'>Zones</div>", unsafe_allow_html=True)
            st.caption("Vul de zones handmatig in — jij bepaalt hoe snel elke zone is.")

            zone_type = st.radio(
                "Zones op basis van",
                options=["tempo (min/km)", "hartslag (bpm)"],
                horizontal=True,
                key="builder_zone_type",
                index=0 if st.session_state.get("builder_zone_type_prefill", "tempo") == "tempo (min/km)" else 1,
            )
            zones_placeholder = (
                "bijv. Z1: >6:30, Z2: 6:00-6:30, Z3: 5:30-6:00, Z4: 5:00-5:30, Z5: <5:00"
                if "tempo" in zone_type else
                "bijv. Z1: <130 bpm, Z2: 130-145 bpm, Z3: 145-158 bpm, Z4: 158-168 bpm, Z5: >168 bpm"
            )
            zones_prefill = st.session_state.pop("builder_zones_prefill", "") or ""
            zones = st.text_area(
                "Zones *",
                value=zones_prefill,
                key="builder_zones",
                placeholder=zones_placeholder,
                height=110,
            )

        else:
            # Bestaande klant: automatisch ophalen uit FinalSurge
            st.markdown("<div class='bb-intake-label'>Zones — FinalSurge</div>", unsafe_allow_html=True)

            zones_fetch_key = f"fetched_zones_{athlete_key_selected}"
            if zones_fetch_key not in st.session_state:
                with st.spinner("Zones ophalen uit FinalSurge…"):
                    fetched = fs_client.get_athlete_zones(athlete_key_selected)
                    st.session_state[zones_fetch_key] = fetched

            fetched = st.session_state.get(zones_fetch_key, {})

            if fetched and fetched.get("zones_text"):
                zone_type_fetched = fetched.get("zone_type", "tempo")
                zone_type_label_fetched = "hartslag (bpm)" if zone_type_fetched == "hartslag" else "tempo (min/km)"
                st.success(f"✅ Zones opgehaald ({zone_type_label_fetched})")
                zones = fetched["zones_text"]
                # Zorg dat session state overeenkomt met opgehaalde zones
                if st.session_state.get("builder_zones", "") != zones:
                    st.session_state["builder_zones"] = zones
                st.code(zones)
                # Keuze hartslag / tempo — ook als FinalSurge al één type heeft
                zone_type = st.radio(
                    "Sturing schema op",
                    options=["tempo (min/km)", "hartslag (bpm)"],
                    horizontal=True,
                    key="builder_zone_type",
                    index=1 if zone_type_fetched == "hartslag" else 0,
                )
                st.caption("Zones worden automatisch meegenomen. Je kunt ze hieronder nog aanpassen.")
                zones_override = st.text_area(
                    "Zones aanpassen (optioneel)",
                    key="builder_zones",
                    height=110,
                )
                zones = zones_override or zones
            else:
                st.warning("Geen zones gevonden in FinalSurge voor deze atleet. Vul ze handmatig in.")
                # Checkbox i.p.v. expander: in Verlengen/Bijsturen is col_r zelf al een
                # expander, en Streamlit staat geen geneste expanders toe.
                if st.checkbox("🔍 Debug API-respons", key="dbg_zones_resp"):
                    st.json(fetched)
                zone_type = st.radio(
                    "Zones op basis van",
                    options=["tempo (min/km)", "hartslag (bpm)"],
                    horizontal=True,
                    key="builder_zone_type",
                )
                zones = st.text_area(
                    "Zones *",
                    key="builder_zones",
                    placeholder="bijv. Z1: >6:30, Z2: 6:00-6:30, …",
                    height=110,
                )
                col_refetch, _ = st.columns([1, 3])
                with col_refetch:
                    if st.button("🔄 Opnieuw proberen", key="btn_refetch_zones"):
                        st.session_state.pop(zones_fetch_key, None)
                        st.rerun()

        # ── Trainingslog (alleen bestaande klant) ───────────────────────────
        auto_log_text = ""
        if not is_new:
            st.markdown("<div class='bb-intake-label'>Trainingslog — afgelopen 4 maanden</div>", unsafe_allow_html=True)
            log_fetch_key = f"training_log_{athlete_key_selected}"
            if log_fetch_key not in st.session_state:
                with st.spinner("Trainingslog ophalen uit FinalSurge… (even geduld)"):
                    log_workouts = fs_client.get_training_log(athlete_key_selected, months=4)
                    st.session_state[log_fetch_key] = log_workouts

            log_workouts = st.session_state.get(log_fetch_key, [])

            # Auto pre-fill langste afstand voor bestaande klanten
            if log_workouts and not is_new:
                completed_workouts = [w for w in log_workouts if w.get("completed")]
                if completed_workouts:
                    max_km_workout = max(completed_workouts, key=lambda w: w.get("actual_km") or 0)
                    max_km = max_km_workout.get("actual_km")
                    if max_km and "builder_langste_afstand" not in st.session_state:
                        st.session_state["builder_langste_afstand"] = f"{max_km} km ({max_km_workout.get('date', '')})"

            if log_workouts:
                total_w = len(log_workouts)
                done_w = sum(1 for w in log_workouts if w["completed"])
                st.success(f"✅ {total_w} trainingen opgehaald — {done_w} voltooid")
                auto_log_text = schema_builder.format_training_log(log_workouts)
                with st.expander("📋 Trainingslog bekijken"):
                    st.text(auto_log_text[:3000] + ("…" if len(auto_log_text) > 3000 else ""))
                col_relog, _ = st.columns([1, 3])
                with col_relog:
                    if st.button("🔄 Opnieuw laden", key="btn_reload_log"):
                        st.session_state.pop(log_fetch_key, None)
                        st.rerun()
            else:
                st.info("Geen trainingen gevonden voor de afgelopen 4 maanden.")

        # ── Bestandsupload ──────────────────────────────────────────────────
        st.markdown("<div class='bb-intake-label'>Documenten *(optioneel)*</div>", unsafe_allow_html=True)
        st.caption("Extra bestanden zoals printscreens of aanvullende info. De AI houdt hier rekening mee.")
        uploaded_files = st.file_uploader(
            "Sleep bestanden hierheen of klik om te uploaden",
            type=["pdf", "docx", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="builder_uploads",
        )
        if uploaded_files:
            st.success(f"{len(uploaded_files)} bestand(en) geladen: {', '.join(f.name for f in uploaded_files)}")

        # ── Validatie & doorgaan ────────────────────────────────────────────
        required = [naam, doel, trainingsdagen, huidig_volume, zones, referentie_prestatie, tijd_per_training]
        all_filled = all(str(r).strip() for r in required)

        if not all_filled:
            st.warning("Vul alle verplichte velden (*) in om door te gaan.")

        if st.button("Genereer plan →", type="primary", disabled=not all_filled, key="btn_gen_plan"):
            schema_target = schema_einddatum or wedstrijddatum
            # Maandag-uitgelijnd (identiek aan de weergave hierboven + build_csv_prompt).
            if schema_target:
                _sm = startdatum - timedelta(days=startdatum.weekday())
                _es = schema_target + timedelta(days=(6 - schema_target.weekday()))
                weken_val = str(max(1, ((_es - _sm).days + 1) // 7))
            else:
                weken_val = ""

            # Haal kalender-labels op. Venster iets ruimer (7 dagen vóór de
            # startdatum) zodat een vakantie/afwezigheid die net vóór of over de
            # startgrens loopt niet gemist wordt.
            labels_tekst = ""
            try:
                _label_start = startdatum - timedelta(days=7)
                _end_date = startdatum + timedelta(days=int(weken_val) * 7 + 7) if weken_val else startdatum + timedelta(days=90)
                labels = fs_client.get_calendar_labels(athlete_key_selected, _label_start, _end_date)
                if labels:
                    label_regels = [
                        f"  - {l['start_date']}{' t/m ' + l['end_date'] if l['end_date'] != l['start_date'] else ''}: {l['name']}"
                        for l in labels
                    ]
                    # Prominent, instruerend blok — niet slechts een opsomming. Zo
                    # weegt de AI de labels zwaar i.p.v. ze in de upload-ruis te laten verdwijnen.
                    labels_tekst = (
                        "━━━ KALENDER-LABELS — VERPLICHT VERWERKEN ━━━\n"
                        "Coach-reminders uit FinalSurge (bijv. vakantie, afwezigheid, wedstrijd). "
                        "Houd het schema hier EXPLICIET rekening mee: plan geen (zware) training "
                        "tijdens vakantie/afwezigheid, taper vóór een wedstrijd, en benoem dit "
                        "zichtbaar in de samenvatting.\n" + "\n".join(label_regels)
                    )
            except Exception:
                pass

            # Verwerk geüploade bestanden
            uploaded_summary_parts = []
            uploaded_images = []
            for f in (uploaded_files or []):
                f.seek(0)
                item = schema_builder.extract_file_content(f)
                if item["type"] == "text":
                    uploaded_summary_parts.append(item["content"][:3000])
                elif item["type"] == "image":
                    uploaded_images.append(item)
                    uploaded_summary_parts.append(f"[Afbeelding: {item['label']} — zie vision-context]")

            # Voeg automatisch opgehaalde trainingslog toe (bestaande klant)
            if auto_log_text:
                uploaded_summary_parts.insert(0, auto_log_text[:9000])

            # Extra context voor nieuwe klant
            extra_context_parts = []
            if is_new:
                if leeftijd:
                    extra_context_parts.append(f"Leeftijd: {leeftijd} jaar")
                if horloge:
                    extra_context_parts.append(f"Horloge/GPS: {horloge}")

            st.session_state["builder_intake"] = {
                "naam": naam,
                "athlete_key": athlete_key_selected,
                "athlete_name": selected_athlete_name,
                "client_type": "nieuw" if is_new else "bestaand",
                "mode": builder_mode,
                "doel": doel,
                "schema_einddatum": str(schema_einddatum) if schema_einddatum else "",
                "wedstrijddatum": str(wedstrijddatum) if wedstrijddatum else "",
                "weken": weken_val,
                "startdatum": str(startdatum),
                "trainingsdagen": trainingsdagen,
                "huidig_volume": huidig_volume,
                "zone_type": "tempo" if "tempo" in zone_type else "hartslag",
                "zones": zones,
                "andere_sporten": andere_sporten,
                "blessurehistorie": blessurehistorie,
                "extra": "\n".join(extra_context_parts),
                "uploaded_summary": "\n\n".join(filter(None, [labels_tekst] + uploaded_summary_parts)),
                "uploaded_images": uploaded_images,
                "referentie_prestatie": referentie_prestatie,
                "tijd_per_training": tijd_per_training,
                "langste_afstand": langste_afstand,
                "kwaliteitservaring": kwaliteitservaring,
                "herstelcapaciteit": herstelcapaciteit,
                "werkdruk": werkdruk,
                "loopondergrond": ", ".join(loopondergrond) if loopondergrond else "",
                "race_prioriteit": race_prioriteit,
                "tussenraces": tussenraces,
                "coach_notitie": coach_notitie,
                "wat_werkte": wat_werkte,
                "wat_niet_werkte": wat_niet_werkte,
                "op_tijd": op_tijd,
            }
            st.session_state["builder_plan"] = None
            st.session_state["builder_csv"] = None
            st.session_state["builder_step"] = 2
            st.session_state.pop("vdot_result", None)
            st.session_state.pop("vdot_zones_calc", None)
            _save_builder_state()
            # Bewaar deze intake per atleet zodat we later kunnen verlengen/bijsturen
            # zonder alles opnieuw in te vullen. Stil falen: opslag mag de bouw nooit blokkeren.
            try:
                if athlete_key_selected:
                    intake_store.save_laatste_intake(athlete_key_selected, st.session_state["builder_intake"])
                    # Ververs de sessie-cache zodat de teruglaad-knop meteen klopt
                    st.session_state["laatste_intakes"] = intake_store.load_laatste_intakes()
            except Exception:
                pass
            st.rerun()

    # ===========================================================================
    # STAP 2 — PLAN GENEREREN & BEOORDELEN
    # ===========================================================================

    elif step == 2:
        intake = st.session_state.get("builder_intake", {})
        naam = intake.get("naam", "")

        st.markdown(f"<div class='bb-intake-label'>Stap 2 — Plan voor {_esc(naam)}</div>", unsafe_allow_html=True)

        # Zichtbaar maken dat de Garmin-herstelstatus is meegewogen (alleen als die
        # er is voor deze atleet; bij klanten zonder Garmin-data verschijnt niets).
        _garmin_line = intake_store.garmin_summary_line(intake.get("athlete_key", ""))
        if _garmin_line:
            st.info(f"🏃 Garmin-herstel meegenomen: {_garmin_line}")

        # Auto-genereren als we hier net zijn aangekomen
        if st.session_state.get("builder_plan") is None:
            with st.spinner("Plan genereren… (±15-30 seconden, automatische retry bij serverfouten)"):
                try:
                    plan = schema_builder.generate_plan(intake)
                    st.session_state["builder_plan"] = plan
                    st.session_state["builder_chat_history"] = []
                    _save_builder_state()
                    st.rerun()
                except Exception as e:
                    st.error(f"Fout bij genereren: {e}")
                    # Laat builder_plan op None staan zodat de retry-knop werkt

        # Toon retry/terug-knoppen als genereren mislukt is
        if st.session_state.get("builder_plan") is None:
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                if st.button("🔄 Opnieuw proberen", key="btn_retry_plan"):
                    st.rerun()
            with col_r2:
                if st.button("← Terug naar intake", key="btn_retry_back"):
                    _set_step(1)
            st.stop()

        if "builder_chat_history" not in st.session_state:
            st.session_state["builder_chat_history"] = []

        plan = st.session_state.get("builder_plan", "")

        col_plan, col_chat = st.columns([3, 2], gap="large")

        with col_plan:
            plan_edited = st.text_area(
                "Plan (pas aan waar nodig voor je verdergaat naar de CSV):",
                value=plan,
                height=520,
            )
            st.session_state["builder_plan"] = plan_edited

            col_back, col_regen, col_next = st.columns([1, 2, 2])
            with col_back:
                if st.button("← Intake", key="btn_plan_back"):
                    _set_step(1)
            with col_regen:
                if st.button("🔄 Opnieuw genereren", key="btn_regen"):
                    st.session_state["builder_plan"] = None
                    st.session_state["builder_chat_history"] = []
                    st.session_state.pop("schema_bericht", None)
                    st.rerun()
            with col_next:
                if st.button("Genereer CSV →", type="primary", key="btn_to_csv",
                             disabled=not bool(st.session_state.get("builder_plan", "").strip())):
                    st.session_state["builder_csv"] = None
                    _set_step(3)

        with col_chat:
            st.markdown("**Sparren met AI**")
            st.caption("Stel vragen of vraag aanpassingen — de AI past het plan direct aan.")

            chat_history = st.session_state["builder_chat_history"]

            # Toon gespreksgeschiedenis
            chat_container = st.container(height=380)
            with chat_container:
                if not chat_history:
                    st.markdown(
                        "<div style='color:#C9D8F0;font-size:0.85rem;padding:0.5rem 0;'>"
                        "Nog geen gesprek. Stel een vraag hieronder.</div>",
                        unsafe_allow_html=True,
                    )
                for msg in chat_history:
                    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                        # Strip plan markers from displayed text
                        display_text = msg["content"]
                        if "===PLAN UPDATE===" in display_text:
                            before = display_text.split("===PLAN UPDATE===")[0].strip()
                            display_text = before + "\n\n*[Plan bijgewerkt — zie links]*" if before else "*[Plan bijgewerkt — zie links]*"
                        st.markdown(display_text)

            # Chat input
            user_input = st.chat_input("Stel een vraag of vraag een aanpassing…", key="builder_chat_input")
            if user_input:
                chat_history.append({"role": "user", "content": user_input})
                st.session_state["builder_chat_history"] = chat_history

                with st.spinner("AI denkt na…"):
                    try:
                        ai_response = schema_builder.chat_about_plan(
                            plan=st.session_state["builder_plan"],
                            intake=intake,
                            history=chat_history,
                        )
                    except Exception as e:
                        ai_response = f"[Fout: {e}]"

                # Detect plan update
                if "===PLAN UPDATE===" in ai_response and "===EINDE PLAN===" in ai_response:
                    new_plan = ai_response.split("===PLAN UPDATE===")[1].split("===EINDE PLAN===")[0].strip()
                    if new_plan.strip():
                        st.session_state["builder_plan"] = new_plan
                        _save_builder_state()
                        st.session_state["_pending_plan_update"] = True
                elif "===PLAN UPDATE===" in ai_response and "===EINDE PLAN===" not in ai_response:
                    # Plan update gestart maar niet afgesloten — respons was te lang
                    partial = ai_response.split("===PLAN UPDATE===")[1].strip()
                    if partial:
                        st.session_state["builder_plan"] = partial
                        _save_builder_state()
                    st.session_state["_pending_plan_update"] = "truncated"

                chat_history.append({"role": "assistant", "content": ai_response})
                st.session_state["builder_chat_history"] = chat_history
                st.rerun()

            update_state = st.session_state.get("_pending_plan_update")
            if update_state == "truncated":
                st.warning("⚠️ Plan deels bijgewerkt — de respons was te lang en is afgeknipt. Vraag de AI om te verdergaan of de resterende weken toe te voegen.")
                if st.button("Wis melding", key="btn_dismiss_update"):
                    st.session_state.pop("_pending_plan_update", None)
                    st.rerun()
            elif update_state:
                st.success("✅ Plan bijgewerkt. Zie het plan links.")
                if st.button("Wis melding", key="btn_dismiss_update"):
                    st.session_state.pop("_pending_plan_update", None)
                    st.rerun()

            if chat_history:
                if st.button("🗑️ Gesprek wissen", key="btn_clear_chat"):
                    st.session_state["builder_chat_history"] = []
                    st.session_state.pop("_pending_plan_update", None)
                    st.rerun()

    # ===========================================================================
    # STAP 3 — CSV GENEREREN & DOWNLOADEN
    # ===========================================================================

    elif step == 3:
        intake = st.session_state.get("builder_intake", {})
        plan = st.session_state.get("builder_plan", "")
        naam = intake.get("naam", "")

        st.markdown(f"<div class='bb-intake-label'>Stap 3 — CSV voor {_esc(naam)}</div>", unsafe_allow_html=True)

        # Auto-genereren als we hier net zijn aangekomen
        if st.session_state.get("builder_csv") is None:
            with st.spinner("CSV genereren voor het volledige schema… (±15-30 seconden)"):
                try:
                    csv_tekst = schema_builder.generate_csv(plan, intake)
                    st.session_state["builder_csv"] = csv_tekst
                    # Direct parsen
                    st.session_state["builder_workouts"] = schema_builder.parse_csv_text(csv_tekst)
                except Exception as e:
                    st.error(f"Fout bij CSV genereren: {e}")
                    st.stop()
            st.rerun()

        csv_tekst = st.session_state.get("builder_csv", "")
        workouts = st.session_state.get("builder_workouts", [])

        # Type icons
        _type_icon = {"Run": "🏃", "Bike": "🚴", "Swim": "🏊", "CrossTraining": "💪", "Rest": "😴", "Strength": "🏋️"}
        _dag_nl = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]

        # Selectie-state initialiseren
        if "builder_excluded" not in st.session_state:
            st.session_state["builder_excluded"] = set()

        # Toon preview tabel
        if workouts:
            n_excluded = len(st.session_state["builder_excluded"])
            n_included = len(workouts) - n_excluded
            c_info, c_sel_all, c_sel_none = st.columns([3, 1, 1])
            c_info.markdown(f"**{n_included} van {len(workouts)} trainingen geselecteerd** voor import.")
            with c_sel_all:
                if st.button("✅ Alles", key="btn_sel_all"):
                    st.session_state["builder_excluded"] = set()
                    st.rerun()
            with c_sel_none:
                if st.button("☐ Geen", key="btn_sel_none"):
                    st.session_state["builder_excluded"] = {i for i in range(len(workouts))}
                    st.rerun()

            # Groepeer per week — relatief t.o.v. startdatum (niet ISO-week)
            from collections import defaultdict as _dd
            from datetime import datetime as _dt
            _startdatum_str = intake.get("startdatum", "")
            try:
                _start_dt = _dt.strptime(_startdatum_str, "%Y-%m-%d")
                # Normaliseer naar maandag van de startweek
                _start_monday = _start_dt - timedelta(days=_start_dt.weekday())
            except Exception:
                _start_monday = None

            by_week = _dd(list)
            for idx, w in enumerate(workouts):
                try:
                    dt = _dt.strptime(w["date"], "%Y-%m-%d")
                    if _start_monday:
                        week_num = ((dt - _start_monday).days // 7) + 1
                        wk = f"week_{week_num:03d}"
                    else:
                        wk = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
                except Exception:
                    wk = "onbekend"
                by_week[wk].append((idx, w))

            for wk, week_items in sorted(by_week.items()):
                week_km = sum((w.get("planned_km") or 0) for _, w in week_items)
                km_str = f" · {week_km:.0f} km" if week_km else ""
                # Weeknummer afleiden voor weergave
                if wk.startswith("week_"):
                    disp_num = int(wk.split("_")[1])
                    # Datum­range van deze week berekenen voor weergave
                    if _start_monday:
                        _mon = _start_monday + timedelta(weeks=disp_num - 1)
                        _sun = _mon + timedelta(days=6)
                        _dag_kort = ["ma", "di", "wo", "do", "vr", "za", "zo"]
                        date_range = f" · {_mon.day}/{_mon.month} – {_sun.day}/{_sun.month}"
                    else:
                        date_range = ""
                    week_label = f"Week {disp_num}{date_range}{km_str}"
                else:
                    week_label = f"Week {wk[-2:]}{km_str}"
                st.markdown(f"<div class='bb-week-header'>{_esc(week_label)}</div>", unsafe_allow_html=True)
                for idx, w in week_items:
                    included = idx not in st.session_state["builder_excluded"]
                    col_cb, col_dag, col_icon, col_name, col_km = st.columns([0.5, 0.8, 0.5, 5, 1.2])
                    with col_cb:
                        checked = st.checkbox("", value=included, key=f"cb_w_{idx}", label_visibility="collapsed")
                        if checked and idx in st.session_state["builder_excluded"]:
                            st.session_state["builder_excluded"].discard(idx)
                            st.rerun()
                        elif not checked and idx not in st.session_state["builder_excluded"]:
                            st.session_state["builder_excluded"].add(idx)
                            st.rerun()
                    try:
                        dt = _dt.strptime(w["date"], "%Y-%m-%d")
                        dag = _dag_nl[dt.weekday()]
                        datum = f"{dt.day}/{dt.month}"
                    except Exception:
                        dag, datum = "", w["date"]
                    col_dag.markdown(f"<span style='color:#C9D8F0;font-size:0.82rem'>{dag} {datum}</span>", unsafe_allow_html=True)
                    col_icon.markdown(_type_icon.get(w.get("activity_type", "Run"), "🏃"))
                    style = "color:#C9D8F0;" if included else "color:#5B7396;text-decoration:line-through;"
                    col_name.markdown(f"<span style='{style}'>{w['name']}</span>", unsafe_allow_html=True)
                    km = round(w["planned_km"], 1) if w.get("planned_km") else ""
                    col_km.markdown(f"<span style='color:#C9D8F0;font-size:0.82rem'>{km} km</span>" if km else "", unsafe_allow_html=True)
        else:
            st.warning("Geen trainingen herkend in de CSV. Controleer de ruwe CSV hieronder.")

        # Ruwe CSV bekijken / bewerken
        with st.expander("Ruwe CSV bekijken / bewerken"):
            csv_edited = st.text_area(
                "CSV:",
                value=csv_tekst,
                height=300,
                key="builder_csv_edit",
            )
            if csv_edited != csv_tekst:
                if st.button("CSV opnieuw parsen", key="btn_reparse"):
                    st.session_state["builder_csv"] = csv_edited
                    st.session_state["builder_workouts"] = schema_builder.parse_csv_text(csv_edited)
                    st.rerun()

        # Download knop
        csv_bytes = csv_tekst.encode("utf-8")
        st.download_button(
            label="⬇️ Download CSV",
            data=csv_bytes,
            file_name=f"schema_{naam.lower().replace(' ','_')}_{date.today()}.csv",
            mime="text/csv",
            key="btn_download_csv",
        )

        col_back2, col_regen2, col_next2 = st.columns([1, 2, 2])
        with col_back2:
            if st.button("← Plan", key="btn_csv_back"):
                _set_step(2)
        with col_regen2:
            if st.button("🔄 Opnieuw genereren", key="btn_regen_csv"):
                st.session_state["builder_csv"] = None
                st.rerun()
        with col_next2:
            n_sel = len(workouts) - len(st.session_state.get("builder_excluded", set()))
            if workouts and n_sel > 0:
                if st.button(f"Importeer {n_sel} trainingen →", type="primary", key="btn_to_import"):
                    # Sla alleen geselecteerde workouts op voor import
                    excluded = st.session_state.get("builder_excluded", set())
                    st.session_state["builder_workouts_import"] = [w for i, w in enumerate(workouts) if i not in excluded]
                    _set_step(4)
            elif workouts:
                st.warning("Selecteer minimaal 1 training.")

    # ===========================================================================
    # STAP 4 — IMPORT IN FINALSURGE
    # ===========================================================================

    elif step == 4:
        intake = st.session_state.get("builder_intake", {})
        # Gebruik de gefilterde lijst (zonder uitgesloten trainingen)
        workouts = st.session_state.get("builder_workouts_import") or st.session_state.get("builder_workouts", [])
        naam = intake.get("naam", "")
        athlete_key = intake.get("athlete_key", "")
        athlete_name = intake.get("athlete_name", "")

        st.markdown("<div class='bb-intake-label'>Stap 4 — Import in FinalSurge</div>", unsafe_allow_html=True)

        st.markdown(f"""
        Je staat op het punt **{len(workouts)} trainingen** te importeren voor:

        **Atleet:** {athlete_name}
        **Schema:** {workouts[0]["date"] if workouts else "?"} t/m {workouts[-1]["date"] if workouts else "?"}
        """)

        st.warning(
            "⚠️ Dit plaatst alle trainingen direct in FinalSurge. "
            "Bestaande trainingen op dezelfde datums worden NIET overschreven — "
            "er worden nieuwe trainingen bijgevoegd. Controleer of de kalender leeg is."
        )

        fill_builder = st.toggle(
            "🔧 Vul ook de Workout Builder (zones/intervallen)",
            value=True,
            help="Laat AI automatisch de zone-stappen invullen op basis van de beschrijving. "
                 "Duurt iets langer maar geeft een mooier resultaat in FinalSurge.",
        )

        # Normaliseer zone_type: intake slaat "hartslag" of "tempo" op (NL), builder gebruikt "heart_rate" of "pace"
        _zt = intake.get("zone_type", "pace")
        zone_type = "heart_rate" if _zt in ("hartslag", "heart_rate") else "pace"

        # Debug: test met 1 workout
        with st.expander("🔍 Debug: test met 1 workout (toont ruwe API-respons)"):
            if workouts and st.button("Test eerste workout", key="btn_test_one"):
                w = workouts[0]
                try:
                    result = fs_client.save_workout(
                        user_key=athlete_key,
                        workout_date=w["date"],
                        name="[TEST] " + w["name"],
                        description=w.get("description", ""),
                        activity_type=w.get("activity_type", "Run"),
                        planned_distance_km=w.get("planned_km"),
                        planned_duration_min=w.get("planned_min"),
                    )
                    st.success("HTTP 200 ontvangen")
                    st.json(result)
                except Exception as e:
                    st.error(f"Fout: {e}")

        col_back3, col_import = st.columns([1, 2])
        with col_back3:
            if st.button("← CSV", key="btn_import_back"):
                _set_step(3)

        with col_import:
            label = f"✅ Importeer {len(workouts)} trainingen"
            if fill_builder:
                label += " + Workout Builder"
            if st.button(label, type="primary", key="btn_do_import"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                errors = []
                ok_count = [0]

                def _cb(i, total, w_name):
                    progress_bar.progress((i + 1) / total)
                    extra = " + builder" if fill_builder else ""
                    status_text.markdown(f"Importeren{extra}: **{w_name}** ({i+1}/{total})")

                with st.spinner("Bezig met importeren…"):
                    try:
                        ok, errors, builder_errors = schema_builder.import_to_finalsurge(
                            athlete_key=athlete_key,
                            workouts=workouts,
                            zone_type=zone_type,
                            progress_callback=_cb,
                            fill_builder=fill_builder,
                            op_tijd=intake.get("op_tijd", False),
                        )
                        ok_count[0] = ok
                    except Exception as e:
                        st.error(f"Importfout: {e}")
                        st.stop()

                progress_bar.empty()
                status_text.empty()

                if errors:
                    st.warning(f"**{ok_count[0]} van {len(workouts)} trainingen geïmporteerd.** "
                               f"Mislukt: {len(errors)}")
                    with st.expander("Workout-fouten bekijken"):
                        for err in errors:
                            st.code(err)
                else:
                    st.success(
                        f"🎉 **{ok_count[0]} trainingen succesvol geïmporteerd!** "
                        f"Open FinalSurge om het schema van {athlete_name} te controleren."
                    )

                if fill_builder and builder_errors:
                    st.warning(f"⚠️ Workout Builder: {len(builder_errors)} van {ok_count[0]} niet gelukt.")
                    with st.expander("Builder-fouten bekijken (debug)"):
                        for err in builder_errors:
                            st.code(err)
                elif fill_builder and not builder_errors and ok_count[0] > 0:
                    st.info("🔧 Workout Builder succesvol ingevuld voor alle trainingen.")

                if not errors:
                    st.balloons()
                    # Onthoud dat de import klaar is, zodat het WhatsApp-bericht en de
                    # reset-knop hieronder blijven staan (ook na een rerun, bijv. bij
                    # het genereren van het bericht).
                    st.session_state["builder_import_done"] = True

        # ── Ná een geslaagde import: WhatsApp-bericht + nieuw-schema-knop ──
        # Top-level in stap 4 (niet in de knop-handler) zodat het blijft staan.
        if st.session_state.get("builder_import_done"):
            st.markdown("---")
            # WhatsApp-bericht voor de atleet — kort, persoonlijk, met de
            # bijzonderheden van dit schema. Kopieer-knop (app verstuurt niets zelf).
            with st.expander("💬 WhatsApp-bericht voor de atleet", expanded=True):
                if st.button("Genereer bericht", key="btn_schema_msg"):
                    with st.spinner("Bericht schrijven…"):
                        try:
                            st.session_state["schema_bericht"] = schema_builder.genereer_schema_bericht(
                                st.session_state.get("builder_plan", ""), athlete_name,
                            )
                        except Exception as e:
                            st.error(f"Kon geen bericht maken: {e}")
                if st.session_state.get("schema_bericht"):
                    st.caption("Kopieer en plak in WhatsApp:")
                    st.code(st.session_state["schema_bericht"], language=None)

            if st.button("📋 Nieuw schema bouwen", type="primary"):
                for k in ["builder_step", "builder_intake", "builder_plan",
                          "builder_csv", "builder_workouts", "builder_mode",
                          "builder_dagen_sel", "builder_import_done", "schema_bericht"]:
                    st.session_state.pop(k, None)
                _set_step(1)
