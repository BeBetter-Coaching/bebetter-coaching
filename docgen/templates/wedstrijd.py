#!/usr/bin/env python3
"""Sjabloon: rondom je wedstrijd (wedstrijdweek + racedag).

Herschreven en aangescherpt uit het originele 'Marathon voorbereiding'-document,
onderbouwd met actuele sportwetenschap. Licht te personaliseren (voornaam,
lichaamsgewicht voor het koolhydraten-rekenvoorbeeld).
"""

INTAKE = [
    {"veld": "voornaam", "vraag": "Voornaam atleet", "type": "tekst"},
    {"veld": "gewicht", "vraag": "Lichaamsgewicht (kg)", "type": "getal"},
]


def derive(answers):
    """Reken uit het gewicht het koolhydraten-stapeladvies (7 tot 10 g/kg)."""
    g = answers.get("gewicht")
    if g:
        try:
            gv = float(str(g).replace(",", "."))
            answers["ch_laag"] = str(round(gv * 7))
            answers["ch_hoog"] = str(round(gv * 10))
        except ValueError:
            pass
    return answers

TEMPLATE = {
    "defaults": {"voornaam": "onze atleet", "gewicht": "70", "ch_laag": "490", "ch_hoog": "700"},

    "pdftitel": "Rondom je wedstrijd, van BeBetter Coaching",
    "titel_1": "RONDOM JE",
    "titel_2": "WEDSTRIJD",
    "ondertitel": "Taperen, eten en de racedag, tot in de puntjes",
    "voor": "Voor {{voornaam}}",
    "kop_links": "Rondom je wedstrijd",
    "kort": [
        ("Onderwerp", "Wedstrijdweek en racedag"),
        ("Voor wie", "(Halve) marathonlopers"),
        ("Leestijd", "± 8 minuten"),
        ("Vragen?", "06 26 77 36 05"),
    ],
    "secties": [
        {"titel": "De laatste week: minder is meer", "blocks": [
            {"t": "para", "id": "intro",
             "ai": "Schrijf een korte, motiverende openingsalinea (2 zinnen) voor een document over de "
                   "wedstrijdweek, gericht aan {{voornaam}}. Benoem dat de laatste week niet meer over "
                   "fitter worden gaat, maar over fris en scherp aan de start komen."},
            {"t": "why", "x": "**Waarom minder trainen?** Je conditie bouw je niet meer op in de laatste "
             "week. Je bouwt 'm juist af als je te veel doet. Onderzoek naar taperen laat zien dat slim "
             "minderen je prestatie gemiddeld zo'n 3 procent verbetert. De truc: verlaag je **omvang** "
             "flink, maar houd een beetje **scherpte** erin."},
            {"t": "steps", "items": [
                ("Loop **40 tot 60 procent minder kilometers** dan in je piekweken. Je benen worden er "
                 "fris van, niet lui.", None),
                ("Houd wat **korte, vlotte stukjes** in je rustige duurlopen (bijvoorbeeld 4 tot 6 keer "
                 "20 seconden op wedstrijdtempo). Zo blijft je systeem scherp.", None),
                ("Cross-training mag: **fietsen of zwemmen**, rustig en maximaal 45 minuten. Handig als "
                 "je wilt bewegen zonder je benen te belasten.", None),
            ]},
            {"t": "tip", "x": "Voel je je de laatste dagen loom of stijf? Dat is normaal bij het "
             "taperen. Vertrouw op je opbouw, dat gevoel verdwijnt op de startlijn."},
        ]},
        {"titel": "Koolhydraten stapelen", "blocks": [
            {"t": "why", "x": "**Waarom stapelen?** Je spieren slaan koolhydraten op als glycogeen, je "
             "belangrijkste brandstof op wedstrijdtempo. Door je voorraad de laatste dagen te "
             "maximaliseren houd je het langer vol en stel je 'de muur' uit. De sportvoedingsrichtlijnen "
             "adviseren hiervoor **7 tot 10 gram koolhydraten per kilo lichaamsgewicht per dag** in de "
             "laatste twee tot drie dagen."},
            {"t": "para", "x": "Reken het simpel uit: weeg je **{{gewicht}} kg**, dan mik je op ongeveer "
             "**{{ch_laag}} tot {{ch_hoog}} gram** koolhydraten per dag, verspreid over je maaltijden. "
             "Denk aan pasta, rijst, brood, aardappels, havermout en fruit."},
            {"t": "tip", "x": "Ga niet ineens véél meer eten, maar **verschuif de verhouding** naar "
             "koolhydraten en iets minder vet en eiwit. Eén bidon sportdrank per dag is een makkelijke "
             "manier om er wat bij te stapelen."},
        ]},
        {"titel": "Drinken, slapen, ontspannen", "blocks": [
            {"t": "steps", "items": [
                ("**Drink verspreid over de dag**, ongeveer 2 tot 2,5 liter. Meer hoeft niet. Een snuf "
                 "sportdrank of wat extra zout helpt je het vocht vasthouden.", None),
                ("**Slaap 7 tot 9 uur.** Slaap is je sterkste hersteltool, en juist de nachten vroeg in "
                 "de week tellen. De nacht vóór de race slaap je vaak slechter, dat geeft niet.", None),
                ("**Ontspan, maar hang niet de hele dag op de bank.** Een rustige wandeling houdt je "
                 "losser dan stilzitten. Vermijd de laatste twee dagen stress en drukte waar je kunt.", None),
            ]},
        ]},
        {"titel": "De dag ervoor: alles klaar", "blocks": [
            {"t": "steps", "items": [
                ("**Eet 's avonds koolhydraatrijk en niet pittig** (pasta of rijst). Pittig of vet eten "
                 "kan zich de volgende ochtend wreken.", None),
                ("**Leg alles klaar**: schoenen, wedstrijdoutfit, startnummer, hartslagband, gels en "
                 "drinken. Doe dit twee tot drie dagen van tevoren, dan vergeet je niets.", None),
                ("**Vul je bidons** al de avond ervoor met de juiste mix sportdrank.", None),
                ("**Plan je reis en parkeren.** Sta ruim op tijd in het startvak en zet daar je horloge "
                 "vast aan voor een goede GPS-fix.", None),
            ]},
        ]},
        {"titel": "Racedag: zo eet en drink je", "blocks": [
            {"t": "steps", "items": [
                ("**Ontbijt 2 tot 3 uur voor de start**, ook als je geen honger hebt. Licht verteerbaar "
                 "en koolhydraatrijk (ongeveer 1 tot 3 gram per kilo). Drink er water met sportdrank bij, "
                 "een halve tot hele liter.", None),
                ("**Een half uur ervoor**: een banaan of vast een gel. Dat vult je glycogeen net even "
                 "bij.", None),
                ("**Tijdens de race**: neem elke **5 tot 7 kilometer** een gel en drink bij de posten. "
                 "Vanaf kilometer 25 is dit cruciaal, ook als je denkt het niet nodig te hebben.", None),
                ("**Bij de waterposten**: knijp het bekertje in een **V-vorm**, dan zuig je minder lucht "
                 "naar binnen. Wees voorzichtig met sportdrank van de organisatie: soms een ander merk "
                 "dan je gewend bent, en dat kan je maag verrassen.", None),
            ]},
            {"t": "why", "x": "**Hoeveel koolhydraten onderweg?** Voor inspanningen boven de 2,5 uur "
             "adviseert de wetenschap tot ongeveer **60 tot 90 gram koolhydraten per uur**, het best uit "
             "meerdere bronnen (glucose én fructose) zodat je maag het beter opneemt. Oefen dit in je "
             "lange duurlopen, niet pas op wedstrijddag."},
            {"t": "tip", "x": "Niks nieuws op wedstrijddag. Alles wat je eet, drinkt en aantrekt heb je "
             "al getest in training."},
            {"t": "spoed", "x": "**Vragen in de laatste week?** App of bel gerust: **06 26 77 36 05**. "
             "Geniet, hier heb je al die maanden voor gewerkt. Dit wordt jouw dag."},
        ]},
        {"titel": "Bronnen", "blocks": [
            {"t": "bronnen", "items": [
                "Thomas D.T., Erdman K.A., Burke L.M. (2016). Nutrition and Athletic Performance. "
                "Joint Position Statement. *Medicine & Science in Sports & Exercise.*",
                "Bosquet L. et al. (2007). Effects of tapering on performance: a meta-analysis. "
                "*Medicine & Science in Sports & Exercise.*",
                "Jeukendrup A.E. (2014). A step towards personalized sports nutrition: carbohydrate "
                "intake during exercise. *Sports Medicine.*",
                "Burke L.M. et al. (2011). Carbohydrates for training and competition. "
                "*Journal of Sports Sciences.*",
            ]},
        ]},
    ],
}
