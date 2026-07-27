"""Intake-pagina — losgekoppeld uit main.py (stap 1 van het opknippen).

Binnengekomen self-service intakes, het intakeformulier voor nieuwe/bestaande
atleten, en de lijst met opgeslagen intakes. Aangeroepen vanuit main.py als
intake_page.render(athletes_by_group). Gedrag is identiek aan voorheen.
"""
import html as _html_mod
from datetime import date

import pandas as pd
import streamlit as st

import intake_form
import intake_store
import schema_builder


def _esc(s) -> str:
    """HTML-escape voor strings in unsafe_allow_html-blokken."""
    return _html_mod.escape(str(s or ""))


def render(athletes_by_group):

    # Intakes laden (gecached per sessie)
    if "intakes" not in st.session_state:
        st.session_state["intakes"] = intake_store.load_intakes()
    intakes = st.session_state["intakes"]

    # ── Self-service intake: inbox met inzendingen + deelbare link ──
    import intake_form
    if "_intake_inbox" not in st.session_state:
        try:
            st.session_state["_intake_inbox"] = intake_store.load_intake_inbox()
        except Exception:
            st.session_state["_intake_inbox"] = {}
    _inbox = st.session_state["_intake_inbox"]
    _wachtend = {k: v for k, v in _inbox.items() if v.get("status") == "nieuw"}
    _INBOX_LABELS = [
        ("E-mail", "email"), ("Leeftijd", "leeftijd"), ("Horloge", "horloge"),
        ("Doel", "doel"), ("Wedstrijd", "wedstrijddatum_tekst"),
        ("Volume/wk", "huidig_volume"), ("Langste loop", "langste_afstand"),
        ("Referentie", "referentie_prestatie"), ("Loopervaring", "loopervaring"),
        ("PR's", "prs"), ("Trainingsdagen", "trainingsdagen"), ("Tijd/training", "tijd_per_training"),
        ("Kwaliteitservaring", "kwaliteitservaring"), ("Ondergrond", "loopondergrond"),
        ("Eerdere schema's", "eerdere_schemas"), ("Wat werkte", "wat_werkte"),
        ("Wat niet werkte", "wat_niet_werkte"), ("Vindt leuk", "leuk"), ("Vindt niks", "niet_leuk"),
        ("Herstel", "herstelcapaciteit"), ("Werkdruk", "werkdruk"), ("Slaap", "slaap"),
        ("Blessures", "blessurehistorie"), ("Klachten", "huidige_klachten"),
        ("Andere sporten", "andere_sporten"), ("Motivatie", "motivatie"), ("Overig", "notities"),
    ]

    with st.expander(f"📨 Binnengekomen intakes van klanten ({len(_wachtend)})",
                     expanded=bool(_wachtend)):
        _hdr1, _hdr2 = st.columns([4, 1], vertical_alignment="center")
        _hdr1.caption("Klanten die je intakelink invulden. Bekijk, en neem over als nieuwe-klant-intake.")
        if _hdr2.button("🔄 Ververs", key="inbox_refresh", use_container_width=True):
            st.session_state["_intake_inbox"] = intake_store.load_intake_inbox()
            st.rerun()
        if not _wachtend:
            st.caption("Nog geen nieuwe inzendingen.")
        for _iid, _sub in sorted(_wachtend.items(), reverse=True):
            st.markdown(f"**{_esc(_sub.get('naam', '?'))}** — {_esc((_sub.get('doel', '') or '')[:90])}  \n"
                        f"<span style='color:#8FA8CE;font-size:.8rem'>ingezonden {_sub.get('ingezonden', '')}"
                        f"{' · ' + _esc(_sub.get('email', '')) if _sub.get('email') else ''}</span>",
                        unsafe_allow_html=True)
            _rijen = []
            for _lbl, _k in _INBOX_LABELS:
                _v = _sub.get(_k)
                if isinstance(_v, list):
                    _v = ", ".join(_v)
                if _v and str(_v).strip():
                    _rijen.append({"Vraag": _lbl, "Antwoord": str(_v)})
            if _rijen:
                st.dataframe(pd.DataFrame(_rijen), hide_index=True, use_container_width=True)
            _bt, _bd = st.columns(2)
            with _bt:
                if st.button("➕ Overnemen als intake", key=f"inbox_take_{_iid}",
                             type="primary", use_container_width=True):
                    _naam = (_sub.get("naam") or "Nieuwe klant").strip()
                    _key = "nieuw:" + _naam.lower().replace(" ", "_")
                    _velden = {k: v for k, v in _sub.items() if k not in ("status", "ingezonden")}
                    intakes[_key] = {"athlete_name": _naam, **_velden,
                                     "updated_at": date.today().isoformat()}
                    intake_store.save_intakes(intakes)
                    st.session_state["intakes"] = intakes
                    _inbox[_iid]["status"] = "verwerkt"
                    intake_store.save_intake_inbox(_inbox)
                    st.session_state["_intake_inbox"] = _inbox
                    st.success(f"'{_naam}' toegevoegd als nieuwe-klant-intake. Kies hieronder "
                               f"'Nieuwe klant' → '{_naam}' om te openen, aan te vullen en op te slaan.")
                    st.rerun()
            with _bd:
                if st.button("🗑 Verwijderen", key=f"inbox_del_{_iid}", use_container_width=True):
                    _inbox.pop(_iid, None)
                    intake_store.save_intake_inbox(_inbox)
                    st.session_state["_intake_inbox"] = _inbox
                    st.rerun()
            if st.checkbox("🔗 Aanvul-link (klant vult déze inzending verder aan)",
                           key=f"inbox_aanvul_{_iid}"):
                st.caption("Stuur deze link naar de klant. Het formulier opent voorgevuld met de "
                           "antwoorden hierboven; verzenden werkt déze inzending bij (geen nieuwe).")
                st.code(intake_form.aanvullink(_iid), language=None)
            st.divider()

    with st.expander("🔗 Deelbare intakelink (stuur naar een nieuwe klant)"):
        _tok = intake_form.link_token()
        st.caption("Stuur deze link naar een klant. Die vult het formulier in zonder in te loggen; "
                   "de inzending verschijnt hierboven in de inbox. Klik op het kopieer-icoon rechts "
                   "in het vak.")
        if _tok:
            st.code(intake_form.volledige_intakelink(), language=None)
        else:
            st.info("Nog geen link aangemaakt.")
        if st.button("Nieuwe link genereren (oude vervalt)" if _tok else "Genereer intakelink",
                     key="intake_link_gen"):
            intake_form.nieuwe_link_token()
            st.rerun()

    if not intake_store.is_cloud_backed():
        st.warning("⚠️ GH_TOKEN niet ingesteld in secrets — intakes worden alleen lokaal opgeslagen "
                   "en kunnen verloren gaan bij een herstart van de cloud-app.")

    # ── Voor wie is deze intake? ─────────────────────────────────────────
    all_athletes = sorted(
        [a for members in athletes_by_group.values() for a in members],
        key=lambda x: x["name"],
    )
    athlete_options = {a["name"]: a["user_key"] for a in all_athletes}

    _MODE_NIEUW = "🆕 Nieuwe klant"
    _MODE_BESTAAND = "Bestaande atleet (in FinalSurge)"
    _NIEUW_START = "➕ Nieuwe intake starten…"

    ik_mode = st.radio(
        "Voor wie is deze intake?",
        [_MODE_NIEUW, _MODE_BESTAAND],
        horizontal=True,
        key="ik_mode",
        help="Een intake gebeurt meestal vóórdat de klant in FinalSurge staat. "
             "Kies 'Nieuwe klant', sla de intake op, en koppel hem later aan het "
             "FinalSurge-account. 'Bestaande atleet' is voor een verlenging of update.",
    )

    # Nieuwe-klant-intakes herkennen we aan de sleutel-prefix "nieuw:"
    _nieuwe_intakes = {k: v for k, v in intakes.items() if k.startswith("nieuw:")}

    if ik_mode == _MODE_NIEUW:
        _naam_naar_key = {
            v.get("athlete_name", k[6:]): k for k, v in sorted(_nieuwe_intakes.items())
        }
        sel_col, status_col = st.columns([3, 2])
        with sel_col:
            _sel = st.selectbox(
                "Intake",
                options=[_NIEUW_START] + list(_naam_naar_key.keys()),
                key="ik_nieuw_sel",
            )
            if _sel == _NIEUW_START:
                _naam_nieuw = st.text_input(
                    "Naam nieuwe klant *", key="ik_nieuw_naam",
                    placeholder="bijv. Sanne de Vries",
                )
                ik_athlete_name = (_naam_nieuw or "").strip()
                ik_athlete_key = "nieuw:" + ik_athlete_name.lower().replace(" ", "_")
            else:
                ik_athlete_name = _sel
                ik_athlete_key = _naam_naar_key[_sel]
        with status_col:
            existing_ik = intakes.get(ik_athlete_key) if ik_athlete_name else None
            if existing_ik:
                st.success(f"✅ Intake aanwezig — laatst bijgewerkt {existing_ik.get('updated_at', '?')}")
                st.caption("Nog niet gekoppeld aan FinalSurge.")
            elif ik_athlete_name:
                st.info("Nieuwe klant — intake wordt los opgeslagen, koppelen kan later.")

        if not ik_athlete_name:
            st.info("Vul de naam van de nieuwe klant in om te beginnen.")
            st.stop()

        # ── Koppelen zodra de klant in FinalSurge staat ──
        if existing_ik:
            with st.expander("🔗 Klant staat inmiddels in FinalSurge? Koppel de intake aan het account"):
                st.caption("Na het koppelen verschijnt de intake in het atleet-dossier en "
                           "wordt hij automatisch gebruikt bij het bouwen van een schema.")
                c_kop, c_btn_kop = st.columns([3, 1], vertical_alignment="bottom")
                with c_kop:
                    _koppel_naam = st.selectbox("FinalSurge-atleet",
                                                list(athlete_options.keys()), key="ik_koppel_sel")
                with c_btn_kop:
                    if st.button("Koppel →", type="primary", key="btn_ik_koppel", use_container_width=True):
                        _doel_key = athlete_options[_koppel_naam]
                        if _doel_key in intakes:
                            st.error(f"{_koppel_naam} heeft al een intake. Verwijder die eerst "
                                     "(in het atleet-dossier) of werk die bij.")
                        else:
                            intakes[_doel_key] = {
                                **existing_ik,
                                "athlete_name": _koppel_naam,
                                "gekoppeld_op": date.today().isoformat(),
                            }
                            intakes.pop(ik_athlete_key, None)
                            ok, err = intake_store.save_intakes(intakes)
                            if ok:
                                st.session_state["intakes"] = intakes
                                st.session_state.pop("ik_loaded_for", None)
                                st.success(f"✅ Intake gekoppeld aan {_koppel_naam}!")
                                st.rerun()
                            else:
                                st.error(f"Koppelen mislukt: {err}")

    else:
        sel_col, status_col = st.columns([3, 2])
        with sel_col:
            ik_athlete_name = st.selectbox("Atleet *", options=list(athlete_options.keys()), key="ik_athlete")
            ik_athlete_key = athlete_options[ik_athlete_name]
        with status_col:
            existing_ik = intakes.get(ik_athlete_key)
            if existing_ik:
                st.success(f"✅ Intake aanwezig — laatst bijgewerkt {existing_ik.get('updated_at', '?')}")
            else:
                st.info("Nog geen intake voor deze atleet.")

    # Prefill widget-keys éénmalig per atleet-wissel
    if st.session_state.get("ik_loaded_for") != ik_athlete_key:
        _src = intakes.get(ik_athlete_key, {})
        st.session_state["ik_naam"]            = _src.get("naam", ik_athlete_name.split()[0])
        st.session_state["ik_leeftijd"]        = _src.get("leeftijd", "")
        st.session_state["ik_horloge"]         = _src.get("horloge", "")
        st.session_state["ik_doel"]            = _src.get("doel", "")
        st.session_state["ik_dagen"]           = _src.get("trainingsdagen", "")
        st.session_state["ik_volume"]          = _src.get("huidig_volume", "")
        st.session_state["ik_tijd"]            = _src.get("tijd_per_training", "")
        st.session_state["ik_referentie"]      = _src.get("referentie_prestatie", "")
        st.session_state["ik_langste"]         = _src.get("langste_afstand", "")
        st.session_state["ik_blessure"]        = _src.get("blessurehistorie", "")
        st.session_state["ik_andere"]          = _src.get("andere_sporten", "")
        st.session_state["ik_wat_werkte"]      = _src.get("wat_werkte", "")
        st.session_state["ik_wat_niet"]        = _src.get("wat_niet_werkte", "")
        st.session_state["ik_coach_notitie"]   = _src.get("coach_notitie", "")
        st.session_state["ik_notities"]        = _src.get("notities", "")
        st.session_state["ik_kwaliteit"]       = _src.get("kwaliteitservaring", "Enige ervaring")
        st.session_state["ik_herstel"]         = _src.get("herstelcapaciteit", "Normaal")
        st.session_state["ik_werkdruk"]        = _src.get("werkdruk", "Normaal")
        st.session_state["ik_ondergrond"]      = _src.get("loopondergrond", ["Weg"])
        st.session_state["ik_op_tijd"]         = _src.get("op_tijd", False)
        # Nieuwe-klant-velden
        st.session_state["ik_motivatie"]       = _src.get("motivatie", "")
        st.session_state["ik_loopervaring"]    = _src.get("loopervaring", "")
        st.session_state["ik_prs"]             = _src.get("prs", "")
        st.session_state["ik_eerdere"]         = _src.get("eerdere_schemas", "")
        st.session_state["ik_slaap"]           = _src.get("slaap", "")
        st.session_state["ik_klachten"]        = _src.get("huidige_klachten", "")
        st.session_state["ik_leuk"]            = _src.get("leuk", "")
        st.session_state["ik_niet_leuk"]       = _src.get("niet_leuk", "")
        st.session_state["ik_wedstrijd"]       = _src.get("wedstrijddatum_tekst", "")
        st.session_state["ik_loaded_for"]      = ik_athlete_key

    # ── AI-vulhulp: plak een intakegesprek of upload een bestand ──────────
    with st.expander("✨ Vul automatisch in vanuit een intakegesprek (plak tekst of upload)"):
        st.caption("Plak hier de notule of upload een bestand (PDF, Word, foto). De AI haalt eruit "
                   "wat erin staat en vult het formulier hieronder. Jij controleert en past aan.")
        _ai_tekst = st.text_area("Notule / vrije tekst", height=140, key="ik_ai_tekst",
                                 placeholder="Plak hier het hele intakeverhaal…")
        _ai_file = st.file_uploader("…of upload een bestand", key="ik_ai_file",
                                    type=["pdf", "docx", "txt", "png", "jpg", "jpeg"])
        if st.button("✨ Formulier invullen met AI", type="primary", key="ik_ai_run"):
            _bron_tekst = (_ai_tekst or "").strip()
            # Bestand → tekst (afbeeldingen worden als losse tekst niet ondersteund hier)
            if _ai_file is not None:
                try:
                    _fc = schema_builder.extract_file_content(_ai_file)
                    if _fc.get("type") == "text":
                        _bron_tekst = (_bron_tekst + "\n\n" + _fc.get("content", "")).strip()
                    else:
                        st.warning("Afbeeldingen kunnen hier nog niet automatisch gelezen worden. "
                                   "Typ of plak de tekst van de foto.")
                except Exception as e:
                    st.error(f"Bestand lezen mislukt: {e}")
            if not _bron_tekst:
                st.warning("Plak eerst tekst of upload een leesbaar bestand.")
            else:
                with st.spinner("Intake uitlezen…"):
                    try:
                        _velden = schema_builder.extract_intake_fields(_bron_tekst)
                    except Exception as e:
                        _velden = {}
                        _m = str(e).lower()
                        if "overloaded" in _m or "529" in _m or "rate limit" in _m:
                            st.warning("De AI is even overbelast (tijdelijk druk bij Anthropic). "
                                       "Wacht een halve minuut en klik nog een keer op "
                                       "'Formulier invullen met AI'. Je tekst/bestand blijft staan.")
                        else:
                            st.error(f"Uitlezen mislukt: {e}")
                if _velden:
                    # Map naar de ik_-sessiekeys (alleen niet-lege waarden)
                    _map = {
                        "naam": "ik_naam", "leeftijd": "ik_leeftijd", "horloge": "ik_horloge",
                        "doel": "ik_doel", "referentie": "ik_referentie", "langste": "ik_langste",
                        "volume": "ik_volume", "dagen": "ik_dagen", "tijd": "ik_tijd",
                        "kwaliteit": "ik_kwaliteit", "op_tijd": "ik_op_tijd",
                        "herstel": "ik_herstel", "werkdruk": "ik_werkdruk", "ondergrond": "ik_ondergrond",
                        "blessure": "ik_blessure", "andere": "ik_andere",
                        "motivatie": "ik_motivatie", "loopervaring": "ik_loopervaring",
                        "prs": "ik_prs", "eerdere": "ik_eerdere", "slaap": "ik_slaap",
                        "klachten": "ik_klachten", "leuk": "ik_leuk", "niet_leuk": "ik_niet_leuk",
                        "wat_werkte": "ik_wat_werkte", "wat_niet_werkte": "ik_wat_niet",
                        "wedstrijd": "ik_wedstrijd", "notities": "ik_notities",
                    }
                    _n = 0
                    for _k, _skey in _map.items():
                        if _k not in _velden:
                            continue
                        _val = _velden[_k]
                        if _val in ("", [], None):
                            continue
                        st.session_state[_skey] = _val
                        _n += 1
                    st.session_state["ik_loaded_for"] = ik_athlete_key  # prefill niet laten overschrijven
                    st.success(f"{_n} velden ingevuld. Controleer hieronder en pas aan waar nodig.")
                    st.rerun()
                else:
                    st.info("Kon geen velden uit de tekst halen.")

    st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)

    # ── Formulier ────────────────────────────────────────────────────────
    col_l, col_r = st.columns(2, gap="large")

    with col_l:
        st.markdown("<div class='bb-intake-label'>Persoonlijk & doel</div>", unsafe_allow_html=True)
        naam = st.text_input("Roepnaam (in coaching-tekst)", key="ik_naam")
        c1, c2 = st.columns(2)
        with c1:
            leeftijd = st.text_input("Leeftijd", key="ik_leeftijd", placeholder="bijv. 34")
        with c2:
            horloge = st.text_input("Horloge / GPS", key="ik_horloge", placeholder="bijv. Garmin 255")
        doel = st.text_area("Doelstelling", key="ik_doel", height=70,
                            placeholder="bijv. 10km in sub 55min")
        referentie = st.text_input("Recente referentieprestatie", key="ik_referentie",
                                   placeholder="bijv. 5km in 22:30 (vorige maand)")
        langste = st.text_input("Langste afstand recent", key="ik_langste",
                                placeholder="bijv. 14km (3 weken geleden)")

    with col_r:
        st.markdown("<div class='bb-intake-label'>Training & beschikbaarheid</div>", unsafe_allow_html=True)
        volume = st.text_input("Huidig wekelijks volume", key="ik_volume", placeholder="bijv. 25-30 km/week")
        dagen = st.text_input("Trainingsdagen", key="ik_dagen", placeholder="bijv. ma / wo / vr / zo")
        tijd = st.text_input("Tijd per training", key="ik_tijd",
                             placeholder="bijv. ma: 45min, wo: 60min, zo: 90min")
        kwaliteit = st.radio("Ervaring intervals/tempo",
                             options=["Weinig/geen", "Enige ervaring", "Regelmatig"],
                             horizontal=True, key="ik_kwaliteit")
        op_tijd = st.checkbox("Schema op tijd (minuten) i.p.v. kilometers", key="ik_op_tijd")

    st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
    st.markdown("<div class='bb-intake-label'>Atleetprofiel</div>", unsafe_allow_html=True)
    cp1, cp2, cp3 = st.columns(3)
    with cp1:
        herstel = st.radio("Herstelcapaciteit", options=["Langzaam", "Normaal", "Snel"],
                           horizontal=True, key="ik_herstel")
    with cp2:
        werkdruk = st.radio("Werkdruk buiten sport", options=["Laag", "Normaal", "Hoog"],
                            horizontal=True, key="ik_werkdruk")
    with cp3:
        ondergrond = st.multiselect("Loopondergrond", options=["Weg", "Trail", "Baan", "Loopband"],
                                    key="ik_ondergrond")

    ca, cb = st.columns(2)
    with ca:
        blessure = st.text_input("Blessurehistorie", key="ik_blessure",
                                 placeholder="bijv. linkerknie (2023), shin splints 2x")
    with cb:
        andere = st.text_input("Andere sporten / verplichtingen", key="ik_andere",
                               placeholder="bijv. HYROX 2x/week, voetbal op zaterdag")

    if ik_mode == _MODE_NIEUW:
        # ── Nieuwe klant: achtergrond die je nog niet kent ──
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
        st.markdown("<div class='bb-intake-label'>Loophistorie & achtergrond</div>", unsafe_allow_html=True)
        cn1, cn2 = st.columns(2)
        with cn1:
            loopervaring = st.text_input(
                "Hoe lang loop je al, en hoe consistent het laatste jaar?",
                key="ik_loopervaring",
                placeholder="bijv. 3 jaar, laatste half jaar 2-3x/week zonder onderbreking",
            )
            prs = st.text_input(
                "Beste prestaties ooit (PR's)", key="ik_prs",
                placeholder="bijv. 5km 24:10 (2024), 10km 51:30 (2023)",
            )
            eerdere = st.text_input(
                "Eerder een schema of coach gehad? Hoe beviel dat?", key="ik_eerdere",
                placeholder="bijv. Runkeeper-schema gevolgd, vond het te eentonig",
            )
        with cn2:
            wedstrijd = st.text_input(
                "Wedstrijd al geprikt? Welke en wanneer?", key="ik_wedstrijd",
                placeholder="bijv. Dam tot Damloop, 21 september — of: nog niet",
            )
            klachten = st.text_input(
                "Huidige klachten of fysieke aandachtspunten", key="ik_klachten",
                placeholder="bijv. stijve kuiten na lange duurloop, niets acuuts",
            )

        st.markdown("<div class='bb-intake-label'>Leefstijl & motivatie</div>", unsafe_allow_html=True)
        cm1, cm2 = st.columns(2)
        with cm1:
            motivatie = st.text_area(
                "Waarom dit doel — wat drijft je?", key="ik_motivatie", height=70,
                placeholder="bijv. 40 worden en fitter zijn dan ooit; samen met zus de halve lopen",
            )
            slaap = st.text_input(
                "Slaap & leefritme", key="ik_slaap",
                placeholder="bijv. 7 uur, jonge kinderen, onregelmatige diensten",
            )
        with cm2:
            leuk = st.text_input(
                "Waar word je blij van in training?", key="ik_leuk",
                placeholder="bijv. lange rustige duurlopen, buiten in het bos",
            )
            niet_leuk = st.text_input(
                "Waar zie je tegenop / wat haat je?", key="ik_niet_leuk",
                placeholder="bijv. baantraining, vroege ochtenden",
            )

        coach_notitie = st.text_area(
            "⭐ Eerste indruk & afspraken — jouw inschatting na het gesprek",
            key="ik_coach_notitie", height=80,
            placeholder="bijv. enthousiast maar wil te snel; eerst 4 wkn rustig opbouwen, "
                        "belastbaarheid kuiten in de gaten houden",
        )
    else:
        # ── Bestaande atleet: wat we al weten uit de samenwerking ──
        cw1, cw2 = st.columns(2)
        with cw1:
            wat_werkte = st.text_input("Wat werkte goed", key="ik_wat_werkte")
        with cw2:
            wat_niet = st.text_input("Wat werkte niet", key="ik_wat_niet")
        coach_notitie = st.text_area("⭐ Coach notitie — jouw kennis over deze atleet",
                                     key="ik_coach_notitie", height=80)

    notities = st.text_area("Vrije notities (intake-gesprek)", key="ik_notities", height=110,
                            placeholder="Alles wat verder ter sprake kwam…")

    # ── Opslaan / verwijderen ────────────────────────────────────────────
    col_save, col_del, _sp = st.columns([2, 2, 3])
    with col_save:
        if st.button("💾 Intake opslaan", type="primary", key="btn_ik_save", use_container_width=True):
            # Mode-specifieke velden uit session state: zo blijven waarden van
            # de andere modus bewaard (bijv. na koppelen van een nieuwe klant)
            intakes[ik_athlete_key] = {
                "athlete_name": ik_athlete_name,
                "naam": naam, "leeftijd": leeftijd, "horloge": horloge,
                "doel": doel, "referentie_prestatie": referentie, "langste_afstand": langste,
                "huidig_volume": volume, "trainingsdagen": dagen, "tijd_per_training": tijd,
                "kwaliteitservaring": kwaliteit, "op_tijd": op_tijd,
                "herstelcapaciteit": herstel, "werkdruk": werkdruk,
                "loopondergrond": ondergrond,
                "blessurehistorie": blessure, "andere_sporten": andere,
                "wat_werkte": st.session_state.get("ik_wat_werkte", ""),
                "wat_niet_werkte": st.session_state.get("ik_wat_niet", ""),
                "coach_notitie": coach_notitie, "notities": notities,
                "motivatie": st.session_state.get("ik_motivatie", ""),
                "loopervaring": st.session_state.get("ik_loopervaring", ""),
                "prs": st.session_state.get("ik_prs", ""),
                "eerdere_schemas": st.session_state.get("ik_eerdere", ""),
                "slaap": st.session_state.get("ik_slaap", ""),
                "huidige_klachten": st.session_state.get("ik_klachten", ""),
                "leuk": st.session_state.get("ik_leuk", ""),
                "niet_leuk": st.session_state.get("ik_niet_leuk", ""),
                "wedstrijddatum_tekst": st.session_state.get("ik_wedstrijd", ""),
                "updated_at": date.today().isoformat(),
            }
            ok, err = intake_store.save_intakes(intakes)
            if ok:
                st.session_state["intakes"] = intakes
                st.success(f"✅ Intake voor {ik_athlete_name} opgeslagen!")
            else:
                st.error(f"Opslaan mislukt: {err}")
    with col_del:
        if existing_ik and st.button("🗑️ Intake verwijderen", key="btn_ik_del", use_container_width=True):
            intakes.pop(ik_athlete_key, None)
            ok, err = intake_store.save_intakes(intakes)
            if ok:
                st.session_state["intakes"] = intakes
                st.session_state.pop("ik_loaded_for", None)
                st.rerun()
            else:
                st.error(f"Verwijderen mislukt: {err}")

    # ── Overzicht bestaande intakes ──────────────────────────────────────
    if intakes:
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
        st.markdown("<div class='bb-intake-label'>Opgeslagen intakes</div>", unsafe_allow_html=True)
        for ak, ik in sorted(intakes.items(), key=lambda x: x[1].get("athlete_name", "")):
            doel_kort = (ik.get("doel") or "—").split("\n")[0][:70]
            st.markdown(
                f"• **{ik.get('athlete_name', '?')}** — {doel_kort} "
                f"<span style='color:#8FA8CE; font-size:0.78rem'>(bijgewerkt {ik.get('updated_at', '?')})</span>",
                unsafe_allow_html=True,
            )
