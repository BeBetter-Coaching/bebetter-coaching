#!/usr/bin/env python3
"""Sjabloon: krachttraining voor hardlopers.

Drie varianten van dezelfde workout, zodat een atleet die doorgaat met kracht
een frisse prikkel krijgt in plaats van steeds exact dezelfde oefeningen:

  * Basis (workout A)   — de standaardset, ideaal om mee te beginnen
  * Variatie (workout B) — zelfde spiergroepen, andere oefeningen
  * Gevorderd            — meer eenbenig en explosief, voor wie kracht vast doet

De coach kiest de variant in de intake (`variant`). Elke oefening is een kaart
met naam, sets/herhalingen, techniek-cue en een begin- en eindbeeld.
"""

# Keuzelabel (intake) -> interne sleutel
VARIANTS = {
    "Basis (workout A)": "A",
    "Variatie (workout B)": "B",
    "Gevorderd": "gev",
}
_KORT = {"A": "Basis", "B": "Variatie", "gev": "Gevorderd"}

INTAKE = [
    {"veld": "voornaam", "vraag": "Voornaam atleet", "type": "tekst"},
    {"veld": "variant", "vraag": "Welke workout?", "type": "keuze",
     "opties": list(VARIANTS.keys())},
]


def _vkey(a):
    """Interne variant-sleutel uit het antwoord (val terug op Basis)."""
    return VARIANTS.get(a.get("variant") or "", "A")


def _is(key):
    return lambda a: _vkey(a) == key


def _oef(naam, sets, cue, begin, eind, *, when=None):
    blk = {"t": "oefening", "naam": naam, "sets": sets, "cue": cue,
           "begin": begin, "eind": eind}
    if when is not None:
        blk["when"] = when
    return blk


def derive(answers):
    """Vul afgeleide velden in (korte variant-naam voor op de cover)."""
    a = dict(answers)
    a["variant_kort"] = _KORT[_vkey(a)]
    return a


# ── De drie workouts (elk 6 oefeningen) ─────────────────────────────────────
_WORKOUT_A = [
    _oef("Squat", "3 × 12",
         "Voeten op schouderbreedte, knieën volgen je tenen, borst omhoog en rug neutraal. Zak "
         "tot je dijen bijna horizontaal zijn en duw krachtig omhoog via je hielen.",
         "oef_squat_begin.jpg", "oef_squat_eind.jpg", when=_is("A")),
    _oef("Romanian deadlift", "3 × 10",
         "Lichte kniebuiging, heupen naar achteren, rug recht. Laat het gewicht langs je benen "
         "zakken tot je rek in je hamstrings voelt, kom dan omhoog door je heupen naar voren te "
         "duwen.",
         "oef_rdl_begin.jpg", "oef_rdl_eind.jpg", when=_is("A")),
    _oef("Uitval (lunge)", "3 × 10 per been",
         "Grote stap naar voren, beide knieën ongeveer 90 graden, romp rechtop. Duw vanuit je "
         "voorste hiel terug naar de start. Laat je voorste knie niet naar binnen vallen.",
         "oef_lunge_begin.jpg", "oef_lunge_eind.jpg", when=_is("A")),
    _oef("Kuitverhoging", "3 × 15",
         "Kom langzaam en zo hoog mogelijk op je tenen en laat gecontroleerd zakken. Doe 'm op "
         "één been voor een extra prikkel, met steun van een muur voor balans.",
         "oef_calf_begin.jpg", "oef_calf_eind.jpg", when=_is("A")),
    _oef("Single-leg glute bridge", "3 × 10 per been",
         "Lig op je rug, één voet plat, ander been gestrekt. Duw je heup omhoog tot een rechte "
         "lijn van schouder tot knie en knijp je bil aan. Laat je heup niet wegzakken.",
         "oef_bridge_begin.jpg", "oef_bridge_eind.jpg", when=_is("A")),
    _oef("Plank", "3 × 30 tot 45 sec",
         "Onderarmen onder je schouders, lichaam kaarsrecht van hoofd tot hielen. Span je buik "
         "en billen aan en laat je heupen niet doorzakken. Adem rustig door.",
         "oef_plank_begin.jpg", "oef_plank_eind.jpg", when=_is("A")),
]

_WORKOUT_B = [
    _oef("Goblet squat", "3 × 12",
         "Houd een gewicht voor je borst, ellebogen naar binnen. Zak recht naar beneden tot je "
         "dijen bijna horizontaal zijn, borst omhoog, en duw via je hielen weer omhoog.",
         "oef_goblet_begin.jpg", "oef_goblet_eind.jpg", when=_is("B")),
    _oef("Split squat", "3 × 10 per been",
         "Sta in een uitvalstand, achterste hiel omhoog. Zak recht naar beneden tot je achterste "
         "knie bijna de grond raakt, romp rechtop, en duw via je voorste hiel omhoog.",
         "oef_splitsq_begin.jpg", "oef_splitsq_eind.jpg", when=_is("B")),
    _oef("Step-up met kniehef", "3 × 10 per been",
         "Stap met je hele voet op een stevige verhoging, strek je standbeen en breng je andere "
         "knie omhoog. Stap gecontroleerd terug en laat je knie niet naar binnen zakken.",
         "oef_stepup_begin.jpg", "oef_stepup_eind.jpg", when=_is("B")),
    _oef("Good morning", "3 × 10",
         "Lichte stang of stok op je schouders, kleine kniebuiging. Scharnier vanuit je heupen "
         "naar voren met een rechte rug tot je rek in je hamstrings voelt, kom dan terug omhoog.",
         "oef_goodmorning_begin.jpg", "oef_goodmorning_eind.jpg", when=_is("B")),
    _oef("Staande kuitverhoging", "3 × 15",
         "Kom langzaam en zo hoog mogelijk op je tenen, houd even vast en laat gecontroleerd "
         "zakken. Eventueel op een klein opstapje voor meer bereik.",
         "oef_calfstand_begin.jpg", "oef_calfstand_eind.jpg", when=_is("B")),
    _oef("Zijplank (side plank)", "3 × 20 tot 30 sec per kant",
         "Steun op één onderarm, lichaam in een rechte lijn, heupen omhoog. Span je zij en billen "
         "aan en laat je heup niet doorzakken.",
         "oef_sidebridge_begin.jpg", "oef_sidebridge_eind.jpg", when=_is("B")),
]

_WORKOUT_GEV = [
    _oef("Bulgarian split squat", "3 × 8 per been",
         "Achterste voet op een bankje, gewicht in je handen. Zak recht naar beneden op je "
         "voorste been tot je dij horizontaal is, romp licht voorover, en duw krachtig omhoog.",
         "oef_bulgarian_begin.jpg", "oef_bulgarian_eind.jpg", when=_is("gev")),
    _oef("Single-leg deadlift", "3 × 8 per been",
         "Sta op één been, knie licht gebogen, gewicht in je hand. Scharnier vanuit je heup naar "
         "voren en breng je vrije been naar achteren tot je romp horizontaal is, kom gecontroleerd "
         "terug. Houd je heupen recht.",
         "oef_sldl_begin.jpg", "oef_sldl_eind.jpg", when=_is("gev")),
    _oef("Walking lunge", "3 × 10 per been",
         "Grote stap naar voren met gewicht in je handen, beide knieën 90 graden. Duw door en stap "
         "direct door met je andere been. Romp rechtop, knie niet naar binnen.",
         "oef_dblunge_begin.jpg", "oef_dblunge_eind.jpg", when=_is("gev")),
    _oef("Eenbenige kuitverhoging", "3 × 12 per been",
         "Op één been op de rand van een opstapje, gewicht in dezelfde hand. Zak diep, kom zo hoog "
         "mogelijk op je tenen en laat langzaam zakken.",
         "oef_calf1_begin.jpg", "oef_calf1_eind.jpg", when=_is("gev")),
    _oef("Glute-ham raise (nordic)", "3 × 6 tot 8",
         "Fixeer je hielen, romp rechtop. Laat jezelf zo langzaam mogelijk gecontroleerd naar voren "
         "zakken met een rechte lijn van knie tot schouder, en duw jezelf terug. Begin met een klein "
         "bereik, dit is zwaar.",
         "oef_ghr_begin.jpg", "oef_ghr_eind.jpg", when=_is("gev")),
    _oef("Box jump", "4 × 5",
         "Zak licht door je knieën, zwaai je armen en spring explosief op een stevige verhoging. "
         "Land zacht met gebogen knieën. Stap rustig terug, niet naar beneden springen.",
         "oef_boxjump_begin.jpg", "oef_boxjump_eind.jpg", when=_is("gev")),
]


TEMPLATE = {
    "defaults": {"voornaam": "onze atleet", "variant": "Basis (workout A)",
                 "variant_kort": "Basis"},

    "pdftitel": "Krachttraining voor hardlopers, van BeBetter Coaching",
    "titel_1": "KRACHT VOOR",
    "titel_2": "HARDLOPERS",
    "ondertitel": "Sterker, economischer en minder blessures",
    "voor": "Voor {{voornaam}}",
    "kop_links": "Krachttraining voor hardlopers",
    "kort": [
        ("Onderwerp", "Kracht en stabiliteit"),
        ("Workout", "{{variant_kort}}"),
        ("Frequentie", "2 keer per week"),
        ("Tijd", "± 20 minuten"),
    ],
    "secties": [
        {"titel": "Waarom krachttraining", "blocks": [
            {"t": "para", "id": "intro",
             "ai": "Schrijf een korte openingsalinea (2 zinnen) voor een krachttrainingsdocument voor "
                   "hardlopers, gericht aan {{voornaam}}. Benoem dat kracht je sterker en efficiënter "
                   "maakt en blessures helpt voorkomen."},
            {"t": "why", "x": "**Waarom als hardloper de sportschool in?** Sterke benen en een stabiele "
             "romp maken je loop **efficiënter** (je gebruikt minder energie op hetzelfde tempo) en "
             "**robuuster**. Onderzoek laat zien dat krachttraining de loopeconomie verbetert en het "
             "blessurerisico flink verlaagt. Je hoeft er geen bodybuilder voor te worden: techniek en "
             "regelmaat winnen het van zwaar."},
        ]},
        {"titel": "De workout", "blocks": [
            {"t": "para", "when": _is("A"),
             "x": "Dit is je **basisworkout**. Doe deze oefeningen **2 keer per week**, na een rustige "
             "loop of los ervan. Rust 60 tot 90 seconden tussen de sets en let vooral op je **techniek**."},
            {"t": "para", "when": _is("B"),
             "x": "Dit is een **variatie** op de basis: zelfde spiergroepen, andere oefeningen. Ideaal als "
             "je de basisworkout een tijd hebt gedaan en toe bent aan een frisse prikkel. Zelfde aanpak: "
             "**2 keer per week**, rust 60 tot 90 seconden, **techniek** voorop."},
            {"t": "para", "when": _is("gev"),
             "x": "Deze **gevorderde workout** is voor als kracht een vast onderdeel is geworden. Meer "
             "eenbenig en explosief, dus zwaarder voor je coördinatie en pezen. Bouw rustig op, "
             "**kwaliteit boven kwantiteit**, en houd 60 tot 90 seconden rust."},
            *_WORKOUT_A,
            *_WORKOUT_B,
            *_WORKOUT_GEV,
        ]},
        {"titel": "Zo haal je er het meeste uit", "blocks": [
            {"t": "steps", "items": [
                ("**Techniek eerst.** Doe elke herhaling rustig en netjes. Liever lichter en goed dan "
                 "zwaar en slordig.", None),
                ("**Bouw geleidelijk op.** Voegt het makkelijk? Maak het zwaarder of doe er een set bij, "
                 "niet alles tegelijk.", None),
                ("**Plan het slim.** Doe kracht bij voorkeur niet vlak vóór een zware loopsleutel, zodat "
                 "je benen fris zijn voor je belangrijkste trainingen.", None),
            ]},
            {"t": "tip", "x": "Voelt een oefening scherp of pijnlijk (niet 'zwaar', maar 'fout')? Stop "
             "ermee en laat het me weten, dan zoeken we een alternatief."},
        ]},
        {"titel": "Bronnen", "blocks": [
            {"t": "bronnen", "items": [
                "Lauersen J.B. et al. (2014). The effectiveness of exercise interventions to prevent "
                "sports injuries: a systematic review and meta-analysis. *British Journal of Sports "
                "Medicine.*",
                "Blagrove R.C. et al. (2018). Effects of Strength Training on the Physiological "
                "Determinants of Middle- and Long-Distance Running Performance. *Sports Medicine.*",
                "Beattie K. et al. (2014). The effect of strength training on performance in endurance "
                "athletes. *Sports Medicine.*",
            ]},
        ]},
    ],
}
