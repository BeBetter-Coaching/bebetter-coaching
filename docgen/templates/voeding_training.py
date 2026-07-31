#!/usr/bin/env python3
"""Sjabloon: voeding rondom je trainingen.

Herschreven en aangescherpt uit het originele 'Marathon voorbereiding -
trainingen'-document, onderbouwd met actuele sportwetenschap. Bevat de
koolhydraten-per-uur-tabel als nette datatabel.
"""

INTAKE = [
    {"veld": "voornaam", "vraag": "Voornaam atleet", "type": "tekst"},
]

TEMPLATE = {
    "defaults": {"voornaam": "onze atleet"},

    "pdftitel": "Voeding rondom je trainingen, van BeBetter Coaching",
    "titel_1": "VOEDING",
    "titel_2": "RONDOM JE TRAININGEN",
    "ondertitel": "Wat, wanneer en hoeveel, voor, tijdens en na",
    "voor": "Voor {{voornaam}}",
    "kop_links": "Voeding rondom je trainingen",
    "kort": [
        ("Onderwerp", "Voeding en hydratatie"),
        ("Voor wie", "Hardlopers in opbouw"),
        ("Leestijd", "± 7 minuten"),
        ("Vragen?", "06 26 77 36 05"),
    ],
    "secties": [
        {"titel": "Voor je training", "blocks": [
            {"t": "para", "id": "intro",
             "ai": "Schrijf een korte openingsalinea (2 zinnen) voor een document over voeding rondom "
                   "trainingen, gericht aan {{voornaam}}. Benoem dat de juiste voeding je trainingen "
                   "scherper maakt en je herstel versnelt."},
            {"t": "why", "x": "**Waarom vooraf eten?** Koolhydraten zijn je snelste brandstof. Goed "
             "gevulde voorraden betekenen scherpere trainingen en minder kans dat je halverwege "
             "inzakt."},
            {"t": "steps", "items": [
                ("**Grote maaltijd: 3 tot 4 uur ervoor.** Koolhydraatrijk en vertrouwd (brood, pasta, "
                 "rijst, havermout).", None),
                ("**Korter van tevoren (1 tot 2 uur): klein en licht.** Een banaan, wat havermout of een "
                 "boterham. Vermijd vlak ervoor veel vet, vezels of een zware maaltijd, dat ligt zwaar "
                 "op de maag.", None),
                ("**Kies wat jouw maag aankan.** Makkelijk verteerbaar wint het van 'gezond maar zwaar' "
                 "vlak voor een training.", None),
            ]},
        ]},
        {"titel": "Tijdens: koolhydraten per uur", "blocks": [
            {"t": "para", "x": "Hoe langer en intensiever de training, hoe meer brandstof je onderweg "
             "nodig hebt. Houd deze richtlijn aan:"},
            {"t": "tabel",
             "head": ["Duur van de inspanning", "Koolhydraten per uur"],
             "rows": [
                 ["Tot 1 uur", "Meestal niet nodig"],
                 ["1 tot 2 uur", "30 tot 60 gram"],
                 ["2 tot 3 uur", "60 tot 90 gram"],
                 ["Boven 2,5 uur", "Tot maximaal 90 gram*"],
             ]},
            {"t": "para", "x": "*Boven de 60 gram per uur werkt alleen met **meerdere koolhydraatbronnen** "
             "(glucose én fructose), zodat je darmen het aankunnen. Begin na **20 tot 30 minuten** en "
             "verdeel je inname. Rustige duurloop? Houd de ondergrens aan. Tempo of interval? Ga richting "
             "de bovengrens."},
            {"t": "why", "x": "**Waarom oefenen?** Je darmen kun je trainen. Wie regelmatig koolhydraten "
             "tijdens het lopen oefent, verdraagt op wedstrijddag meer zonder maagklachten."},
        ]},
        {"titel": "Sportdrank en gels", "blocks": [
            {"t": "steps", "items": [
                ("**Sportdrank** vult vocht, **elektrolyten** (vooral natrium) én koolhydraten aan. "
                 "Handig op lange, warme of zweterige duurlopen.", None),
                ("**Gels** geven snel koolhydraten (ongeveer 25 gram per gel). Neem er water bij voor een "
                 "betere opname.", None),
                ("**Test merken in training**, niet in de wedstrijd. Bekende opties zijn SIS, Maurten, GU "
                 "en Isostar. Ieder lijf reageert anders.", None),
            ]},
            {"t": "tip", "x": "Overdrijf niet. Te veel gel of drank in één keer geeft juist maagklachten. "
             "Kleine beetjes, mooi verspreid."},
        ]},
        {"titel": "Na je training: herstel", "blocks": [
            {"t": "why", "x": "**Waarom herstelvoeding?** Na een zware training zijn je "
             "glycogeenvoorraden leeg en zijn je spieren toe aan herstel. Eiwit levert de bouwstenen, "
             "koolhydraten vullen de tank weer aan."},
            {"t": "steps", "items": [
                ("**Eiwit: ongeveer 20 tot 40 gram** na de training (vlees, vis, zuivel, ei, peulvruchten "
                 "of een shake).", None),
                ("**Koolhydraten erbij**, zeker als je binnen een dag weer traint.", None),
                ("**Geen paniek over 'de 30 minuten'.** Dat strakke tijdvenster is grotendeels een "
                 "mythe. Belangrijker is je **totale eiwitinname over de dag**, ongeveer 1,6 tot 2 gram "
                 "per kilo lichaamsgewicht.", None),
            ]},
        ]},
        {"titel": "De basis op orde", "blocks": [
            {"t": "steps", "items": [
                ("**Drink verspreid over de dag** (ongeveer 2 liter, meer bij warmte of zweten).", None),
                ("**Gezonde vetten** (noten, zaden, vette vis, olijfolie) horen in je dagmenu, alleen "
                 "niet vlak voor een training.", None),
                ("**Groente en fruit** leveren de vitamines en mineralen die je herstel en weerstand "
                 "ondersteunen.", None),
            ]},
            {"t": "tip", "x": "Voeding rondom trainingen is de bonus. De basis is en blijft een "
             "gevarieerd, volwaardig dagmenu."},
        ]},
        {"titel": "Bronnen", "blocks": [
            {"t": "bronnen", "items": [
                "Thomas D.T., Erdman K.A., Burke L.M. (2016). Nutrition and Athletic Performance. "
                "Joint Position Statement. *Medicine & Science in Sports & Exercise.*",
                "Jeukendrup A.E. (2014). A step towards personalized sports nutrition: carbohydrate "
                "intake during exercise. *Sports Medicine.*",
                "Jäger R. et al. (2017). ISSN Position Stand: Protein and Exercise. "
                "*Journal of the International Society of Sports Nutrition.*",
                "Kerksick C.M. et al. (2017). ISSN Position Stand: Nutrient Timing. "
                "*Journal of the International Society of Sports Nutrition.*",
            ]},
        ]},
    ],
}
