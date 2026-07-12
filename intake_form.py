"""Self-service intakeformulier voor nieuwe klanten (publieke route).

De klant opent een deelbare link (?intake=<token>), vult het formulier in en
verzendt. De inzending landt in de intake-inbox (GitHub-backed) die de coach
in de Intake-module reviewt en aan een atleet koppelt. Geen login nodig voor
de klant; de token in de link beschermt tegen willekeurige bezoekers.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime

import streamlit as st

import intake_store

# Basis-URL van de app, voor de kant-en-klare deelbare intakelink. Overschrijfbaar
# via de secret APP_URL mocht het adres ooit veranderen (bijv. eigen domein).
_APP_URL_DEFAULT = "https://bebetter-coaching.streamlit.app"


def app_url() -> str:
    try:
        val = st.secrets.get("APP_URL", "")
        if val:
            return str(val).strip().rstrip("/")
    except Exception:
        pass
    return _APP_URL_DEFAULT


def volledige_intakelink() -> str:
    """De complete, kopieerbare link naar het klantformulier (of leeg zonder token)."""
    tok = link_token()
    return f"{app_url()}/?intake={tok}" if tok else ""


# Selectie-opties gelijk aan de coach-intake, zodat koppelen 1-op-1 werkt.
_KWALITEIT = ["Weinig/geen", "Enige ervaring", "Regelmatig"]
_HERSTEL = ["Langzaam", "Normaal", "Snel"]
_WERKDRUK = ["Laag", "Normaal", "Hoog"]
_ONDERGROND = ["Weg", "Trail", "Baan", "Loopband"]


def link_token() -> str:
    """Huidige geheime token van de deelbare intakelink (leeg als nog niet gemaakt)."""
    try:
        return (intake_store.load_intake_link() or {}).get("token", "")
    except Exception:
        return ""


def nieuwe_link_token() -> str:
    """Genereer en bewaar een nieuwe token (maakt oude links ongeldig)."""
    token = secrets.token_urlsafe(9)
    intake_store.save_intake_link({"token": token})
    return token


def token_geldig(token: str) -> bool:
    huidig = link_token()
    return bool(huidig) and secrets.compare_digest(token or "", huidig)


def _bewaar_inzending(velden: dict) -> tuple[bool, str]:
    try:
        inbox = intake_store.load_intake_inbox()
    except Exception:
        inbox = {}
    _id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    inbox[_id] = {**velden, "status": "nieuw",
                  "ingezonden": datetime.now().isoformat(timespec="minutes")}
    return intake_store.save_intake_inbox(inbox)


def render_publieke_intake() -> None:
    """Render het klantformulier. Alleen aanroepen als de token geldig is."""
    _bedankt = st.session_state.get("_intake_verzonden")
    if _bedankt:
        st.markdown(
            "<div style='max-width:640px;margin:3rem auto;text-align:center'>"
            "<h2 style='color:#5EE6EB'>Bedankt!</h2>"
            "<p style='color:#C9D8F0;font-size:1.05rem'>Je intake is verstuurd naar je coach. "
            "Je hoort snel van ons. Je kunt dit venster sluiten.</p></div>",
            unsafe_allow_html=True)
        return

    col_l, col_m, col_r = st.columns([0.4, 3, 0.4])
    with col_m:
        try:
            st.image("assets/logo_wit.png", width=180)
        except Exception:
            st.markdown("## BeBetter Coaching")
        st.markdown("### Intakeformulier")
        st.caption("Leuk dat je met ons gaat trainen! Vul dit even in, dan stellen we jouw "
                   "schema precies op jou af. Alleen je naam en je doel zijn verplicht; de rest "
                   "helpt ons, maar mag je overslaan als je het niet weet.")

        with st.form("publieke_intake", clear_on_submit=False):
            st.markdown("**Over jou**")
            naam = st.text_input("Je naam *")
            c1, c2 = st.columns(2)
            email = c1.text_input("E-mailadres")
            leeftijd = c2.text_input("Leeftijd")
            horloge = st.text_input("Welk sporthorloge gebruik je?", placeholder="bijv. Garmin, Coros, geen")

            st.markdown("**Je doel**")
            doel = st.text_area("Wat wil je bereiken? *", height=80,
                                placeholder="bijv. 10 km onder de 55 min, mijn eerste halve marathon, fitter worden")
            wedstrijd = st.text_input("Heb je al een wedstrijd of datum geprikt?",
                                      placeholder="bijv. Marathon Eindhoven, 12 oktober")

            st.markdown("**Je huidige niveau**")
            c3, c4 = st.columns(2)
            volume = c3.text_input("Hoeveel km loop je nu per week?", placeholder="bijv. 20 km")
            langste = c4.text_input("Wat is je langste recente loop?", placeholder="bijv. 15 km")
            referentie = st.text_input("Een recente prestatie/tijd om op te ijken?",
                                       placeholder="bijv. 10 km in 58 min vorige maand")
            loopervaring = st.text_area("Hoe lang en hoe consistent loop je al?", height=68)
            prs = st.text_input("Je beste tijden ooit (PR's), als je die weet")

            st.markdown("**Je training**")
            c5, c6 = st.columns(2)
            dagen = c5.text_input("Welke dagen kun/wil je trainen?", placeholder="bijv. di / do / zo")
            tijd = c6.text_input("Hoeveel tijd per training?", placeholder="bijv. 45-60 min")
            kwaliteit = st.selectbox("Hoeveel ervaring heb je met interval-/snelheidstraining?",
                                     _KWALITEIT, index=1)
            ondergrond = st.multiselect("Waar loop je meestal?", _ONDERGROND, default=["Weg"])
            eerdere = st.text_area("Heb je eerder met een schema of coach getraind? Hoe ging dat?", height=68)

            st.markdown("**Wat werkt voor jou**")
            wat_werkte = st.text_area("Wat werkte in het verleden goed voor jou?", height=68)
            wat_niet = st.text_area("En wat werkte juist niet?", height=68)
            leuk = st.text_input("Waar word je blij van in het lopen?")
            niet_leuk = st.text_input("Waar zie je tegenop of wat vind je niks?")

            st.markdown("**Je lijf & leven**")
            c7, c8 = st.columns(2)
            herstel = c7.selectbox("Hoe snel herstel je doorgaans?", _HERSTEL, index=1)
            werkdruk = c8.selectbox("Hoe druk is je werk/leven?", _WERKDRUK, index=1)
            slaap = st.text_input("Hoe is je slaap en leefritme?", placeholder="bijv. wisseldiensten, 6-7 uur")
            blessure = st.text_area("Blessures gehad (of nu)? Vertel kort.", height=68)
            klachten = st.text_input("Huidige klachten of aandachtspunten?")
            andere = st.text_input("Doe je nog andere sporten?", placeholder="bijv. krachttraining, voetbal")
            motivatie = st.text_area("Wat motiveert je het meest?", height=68)
            notities = st.text_area("Nog iets dat we moeten weten?", height=68)

            verzonden = st.form_submit_button("Verstuur intake", type="primary",
                                              use_container_width=True)

        if verzonden:
            if not naam.strip() or not doel.strip():
                st.error("Vul in elk geval je naam en je doel in.")
            else:
                velden = {
                    "naam": naam.strip(), "email": email.strip(), "leeftijd": leeftijd.strip(),
                    "horloge": horloge.strip(), "doel": doel.strip(),
                    "wedstrijddatum_tekst": wedstrijd.strip(),
                    "huidig_volume": volume.strip(), "langste_afstand": langste.strip(),
                    "referentie_prestatie": referentie.strip(), "loopervaring": loopervaring.strip(),
                    "prs": prs.strip(), "trainingsdagen": dagen.strip(),
                    "tijd_per_training": tijd.strip(), "kwaliteitservaring": kwaliteit,
                    "loopondergrond": ondergrond or ["Weg"], "eerdere_schemas": eerdere.strip(),
                    "wat_werkte": wat_werkte.strip(), "wat_niet_werkte": wat_niet.strip(),
                    "leuk": leuk.strip(), "niet_leuk": niet_leuk.strip(),
                    "herstelcapaciteit": herstel, "werkdruk": werkdruk, "slaap": slaap.strip(),
                    "blessurehistorie": blessure.strip(), "huidige_klachten": klachten.strip(),
                    "andere_sporten": andere.strip(), "motivatie": motivatie.strip(),
                    "notities": notities.strip(),
                }
                ok, err = _bewaar_inzending(velden)
                if ok:
                    st.session_state["_intake_verzonden"] = True
                    st.rerun()
                else:
                    st.error(f"Er ging iets mis bij het versturen: {err}. Probeer het zo nog eens.")
