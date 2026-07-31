#!/usr/bin/env python3
"""Sjabloon: krachttraining voor hardlopers.

Elke oefening is een kaart met naam, sets/herhalingen, techniek-cue en een
begin- en eindbeeld. De beelden zijn nu plekhouders (`PH:...`); zodra we een
consistente illustratieset hebben, swappen we ze in (net als bij de screenshots).
"""

INTAKE = [
    {"veld": "voornaam", "vraag": "Voornaam atleet", "type": "tekst"},
]


def _oef(naam, sets, cue, begin="PH:Begin", eind="PH:Eind"):
    return {"t": "oefening", "naam": naam, "sets": sets, "cue": cue, "begin": begin, "eind": eind}


TEMPLATE = {
    "defaults": {"voornaam": "onze atleet"},

    "pdftitel": "Krachttraining voor hardlopers, van BeBetter Coaching",
    "titel_1": "KRACHT VOOR",
    "titel_2": "HARDLOPERS",
    "ondertitel": "Sterker, economischer en minder blessures",
    "voor": "Voor {{voornaam}}",
    "kop_links": "Krachttraining voor hardlopers",
    "kort": [
        ("Onderwerp", "Kracht en stabiliteit"),
        ("Voor wie", "Hardlopers in opbouw"),
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
            {"t": "para", "x": "Doe deze oefeningen **2 keer per week**, na een rustige loop of los "
             "ervan. Rust 60 tot 90 seconden tussen de sets en let vooral op je **techniek**."},
            _oef("Squat", "3 × 12",
                 "Voeten op schouderbreedte, knieën volgen je tenen, borst omhoog en rug neutraal. Zak "
                 "tot je dijen bijna horizontaal zijn en duw krachtig omhoog via je hielen.",
                 "oef_squat_begin.jpg", "oef_squat_eind.jpg"),
            _oef("Romanian deadlift", "3 × 10",
                 "Lichte kniebuiging, heupen naar achteren, rug recht. Laat het gewicht langs je benen "
                 "zakken tot je rek in je hamstrings voelt, kom dan omhoog door je heupen naar voren te "
                 "duwen.",
                 "oef_rdl_begin.jpg", "oef_rdl_eind.jpg"),
            _oef("Uitval (lunge)", "3 × 10 per been",
                 "Grote stap naar voren, beide knieën ongeveer 90 graden, romp rechtop. Duw vanuit je "
                 "voorste hiel terug naar de start. Laat je voorste knie niet naar binnen vallen.",
                 "oef_lunge_begin.jpg", "oef_lunge_eind.jpg"),
            _oef("Kuitverhoging", "3 × 15",
                 "Kom langzaam en zo hoog mogelijk op je tenen en laat gecontroleerd zakken. Doe 'm op "
                 "één been voor een extra prikkel, met steun van een muur voor balans.",
                 "oef_calf_begin.jpg", "oef_calf_eind.jpg"),
            _oef("Single-leg glute bridge", "3 × 10 per been",
                 "Lig op je rug, één voet plat, ander been gestrekt. Duw je heup omhoog tot een rechte "
                 "lijn van schouder tot knie en knijp je bil aan. Laat je heup niet wegzakken.",
                 "oef_bridge_begin.jpg", "oef_bridge_eind.jpg"),
            _oef("Plank", "3 × 30 tot 45 sec",
                 "Onderarmen onder je schouders, lichaam kaarsrecht van hoofd tot hielen. Span je buik "
                 "en billen aan en laat je heupen niet doorzakken. Adem rustig door.",
                 "oef_plank_begin.jpg", "oef_plank_eind.jpg"),
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
