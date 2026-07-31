#!/usr/bin/env python3
"""Sjabloon: FinalSurge-handleiding voor BeBetter Coaching-atleten.

Ruwe tekst (nog geen opmaak toegepast). De templating-laag (`template.py`)
vult `{{placeholders}}` in, verwijdert conditionele blokken die niet gelden,
schoont streepjes op en zet opmaak om. De layout blijft de vaste engine.

Standaardwaarden reproduceren exact de goedgekeurde v6-handleiding. Geef je een
`voornaam` (en eventueel `horloge`) mee, dan wordt het document persoonlijk.
"""

# Wat de doc-intake voor dit sjabloon uitvraagt (voor de app-module later):
INTAKE = [
    {"veld": "voornaam", "vraag": "Voornaam atleet", "type": "tekst"},
    {"veld": "horloge", "vraag": "Sporthorloge", "type": "keuze",
     "opties": ["", "garmin", "coros", "polar", "suunto", "apple"]},
]

_is_garmin = lambda a: a.get("horloge") == "garmin"

TEMPLATE = {
    "defaults": {"voornaam": "onze atleten", "horloge": ""},

    "pdftitel": "FinalSurge Handleiding van BeBetter Coaching",
    "titel_1": "FINALSURGE",
    "titel_2": "HANDLEIDING",
    "ondertitel": "Alles wat je nodig hebt om te trainen met BeBetter Coaching",
    "voor": "Voor {{voornaam}}",
    "kop_links": "FinalSurge Handleiding",
    "kort": [
        ("Wat", "Schema, evaluatie en contact in één app"),
        ("Voor wie", "Atleten van BeBetter Coaching"),
        ("Tijd om te starten", "± 15 minuten"),
        ("Nodig", "Telefoon + (optioneel) sporthorloge"),
    ],
    "secties": [
        {"titel": "Welkom", "blocks": [
            {"t": "para", "x": "Leuk dat je met BeBetter Coaching gaat trainen! We werken met de app "
             "**FinalSurge**: hierin staat je persoonlijke schema, hierin leg je je trainingen vast, "
             "en hierin heb je contact met je coach. Deze handleiding zet je in een kwartier volledig "
             "op weg. Je hoeft niet technisch te zijn."},
            {"t": "why", "x": "**Waarom deze app?** Jouw schema is een levend plan. Hoe beter jij "
             "je trainingen vastlegt en evalueert, hoe scherper ik kan bijsturen: sneller vooruit, en "
             "met minder blessurerisico. FinalSurge is de plek waar jouw data en mijn coaching "
             "samenkomen."},
        ]},
        {"titel": "Aan de slag: account & je coach", "blocks": [
            {"t": "steps", "items": [
                ("Download **FinalSurge** in de App Store (iPhone) of Play Store (Android).", None),
                ("Maak een account of log in. **Let op:** gebruik hetzelfde e-mailadres waarop je de "
                 "uitnodiging hebt ontvangen, anders komt de koppeling niet binnen.", "p1_1.png"),
                ("Open de **Coaching Invitation** (mail: *View Coach Invitation*, app: *View Request*) "
                 "en kies **Accept Invite**. Vanaf nu verschijnt je schema in je Calendar.", "p2_1.png"),
            ]},
            {"t": "tip", "x": "Geen uitnodiging gezien? Check je spam, of stuur me een berichtje, "
             "dan stuur ik 'm opnieuw."},
        ]},
        {"titel": "Je sporthorloge koppelen", "blocks": [
            {"t": "why", "x": "**Waarom koppelen?** Zo komen je gelopen trainingen **automatisch** "
             "binnen. Jij hoeft niets over te typen, en ik zie je échte data (tempo, hartslag, afstand) "
             "naast het geplande."},
            {"t": "steps", "items": [
                ("Ga naar **More** (3 bolletjes rechtsonder) → **Connected Apps**.", "p4_0.png"),
                ("**Garmin:** koppel **Garmin Connect** én zet **auto-sync** aan. Koppelen alléén is "
                 "niet genoeg. Met auto-sync komen je **geplande** trainingen automatisch op je "
                 "horloge te staan, en je **gelopen** trainingen automatisch terug in FinalSurge.", None),
                ("**Coros / Polar / Suunto / Apple Watch:** koppel op dezelfde plek je eigen merk, zodat "
                 "je gelopen trainingen automatisch binnenkomen.", None),
            ]},
            {"t": "tip", "when": _is_garmin, "x": "Jij loopt met een **Garmin**, dus regel deze "
             "koppeling nu meteen. Dan staan je trainingen vanzelf klaar op je horloge en hoef je er "
             "nooit meer aan te denken."},
            {"t": "tip", "x": "**Koppel maar één bron.** Koppel je bijvoorbeeld óók Strava naast "
             "Garmin, dan komt elke training **dubbel** in je kalender. Geen horloge? Je kunt een "
             "training ook handmatig als ‘gedaan’ markeren."},
        ]},
        {"titel": "Zet de app op Nederlandse instellingen", "blocks": [
            {"t": "steps", "items": [
                ("Ga naar **More → Account & Workout Settings → User Preferences** en zet de "
                 "instellingen zoals op de afbeelding: week begint op **maandag**, afstanden in "
                 "**kilometers/meters**, en de juiste **datumnotatie**.", "p5_0.png"),
            ]},
        ]},
        {"titel": "Je week: trainingen en kleuren", "blocks": [
            {"t": "para", "x": "Je schema staat per dag in je **Calendar**; met de weekknop zie je "
             "een overzicht van de hele week. Zodra je een training hebt gedaan, krijgt die een kleur:"},
            {"t": "kleuren", "items": [
                ("#2e9d54", "Groen", "uitgevoerd zoals gepland"),
                ("#e0a325", "Geel", "deels of afwijkend uitgevoerd"),
                ("#d94a3d", "Rood", "niet of heel anders getraind"),
            ]},
            {"t": "why", "x": "De kleuren zijn **geen oordeel**. Ze helpen ons samen in één "
             "oogopslag zien hoe je week liep."},
        ]},
        {"titel": "Een training naar een andere dag verschuiven", "blocks": [
            {"t": "para", "x": "Je trainingen staan bewust op een **vaste dag** (je duurloop bijvoorbeeld "
             "op woensdag). Komt het een keer niet uit? Verschuif de training dan **vóórdat je begint** naar "
             "de dag waarop je wél loopt. Zo blijft je weekopbouw kloppen en zie ik precies wat je hebt gedaan."},
            {"t": "steps", "items": [
                ("Open de training en kies **Move**. Selecteer de dag waarop je de training wél doet.", None),
                ("**Let op, Garmin-gebruikers:** open daarna de verschoven training, tik op de "
                 "**3 bolletjes** rechtsboven en kies **Push to Garmin**. Doe je dit niet, dan staat de "
                 "training op de verkeerde dag in Garmin Connect en komt hij niet goed op je horloge.", None),
            ]},
            {"t": "tip", "x": "Verschuif altijd **vóór** aanvang van de training, niet achteraf. "
             "Achteraf verschuiven verstoort de match tussen je geplande en je gelopen training."},
        ]},
        {"titel": "Vakantie of een drukke periode? Zet het in je agenda", "blocks": [
            {"t": "para", "x": "Ga je op vakantie, ben je ziek of heb je een drukke werkweek? Zet het "
             "in je agenda. Dan houd ik er rekening mee in je planning en verwacht ik geen trainingen op "
             "die dagen."},
            {"t": "steps", "items": [
                ("Open je **Calendar** en tik rechtsboven op **+**. Kies **Add Label**.", "cal_addlabel_menu.png"),
                ("Stel bij **Date Range** de begindatum en einddatum in. Zo dek je in één keer "
                 "bijvoorbeeld je hele vakantie af, zonder het per dag te doen.", None),
                ("Geef de label een **naam** (bijvoorbeeld *Vakantie*, *Ziek* of *Drukke week*), kies "
                 "eventueel een kleur en tik op **Done**.", "add_label.png"),
            ]},
            {"t": "tip", "x": "Weet je een langere afwezigheid al op voorhand? Geef het een paar dagen "
             "van tevoren aan, dan pas ik je schema er alvast op aan."},
        ]},
        {"titel": "Na élke training: evalueren", "blocks": [
            {"t": "why", "x": "**Dit is het belangrijkste onderdeel.** De cijfers van je horloge "
             "vertellen de helft. Hoe je je vóélde en hoe zwaar het écht was, vertelt de andere helft. "
             "Samen bepalen ze of we doorbouwen, consolideren of gas terugnemen. **1 minuut invullen = "
             "veel gerichtere coaching.**"},
            {"t": "steps", "items": [
                ("Open de training en tik op **How I Felt & Perceived Effort**.", "eval_detail.png"),
                ("**How I Felt:** kies hoe je je voelde, van **Great** tot **Terrible**.", "eval_sheet.png"),
                ("**Perceived Effort:** hoe zwaar was het écht, van **Very Light** tot **Max Effort**, "
                 "ongeacht wat je horloge zegt.", None),
                ("**Post Workout Notes:** kort in je eigen woorden (benen zwaar, lekker gelopen, slecht "
                 "geslapen, warm weer…). Tik op **Save**.", None),
            ]},
            {"t": "tip", "x": "Vuistregel: **hoe eerlijker en nauwkeuriger, hoe beter je feedback.**"},
        ]},
        {"titel": "Pijn of klachten? Pain & Injury Report", "blocks": [
            {"t": "why", "x": "**Waarom melden?** Dit is mijn vroege waarschuwing tegen blessures. "
             "Ook lichte pijn is waardevolle informatie. Daarmee kan ik op tijd bijsturen voordat het "
             "een echte blessure wordt."},
            {"t": "steps", "items": [
                ("Open de training en tik onderaan op **Pain & Injury Report**.", "pain_map.png"),
                ("Tik op de plek waar je pijn had. Wissel tussen **Front / Back / Foot** voor de juiste "
                 "kant en plek.", None),
                ("Geef aan: **Pain Level** (Slight → Unbearable), **Pain Duration** (van start tot eind "
                 "van de training), **Pain Trend** (afnemend → toenemend) en eventueel **Pain Notes**. "
                 "Tik op **Add**.", "pain_detail.png"),
            ]},
            {"t": "tip", "x": "Geen pijn? Dan hoef je hier niets in te vullen. Twijfel je? Meld het "
             "toch, liever te vroeg dan te laat."},
        ]},
        {"titel": "Contact met je coach", "blocks": [
            {"t": "para", "x": "Kies de juiste weg, dan komt je bericht op de beste plek binnen:"},
            {"t": "steps", "items": [
                ("**Over een specifieke training?** Reageer in de **comments** bij díe training (open "
                 "de training → het comment-icoon). Daar reageer ik ook op.", None),
                ("**Iets los van een training?** Gebruik de **Mailbox**: plusje rechtsboven → kies "
                 "ontvanger, onderwerp en bericht → **Send**.", "p9_0.png"),
            ]},
            {"t": "spoed", "x": "**Spoed of haast?** Bel of app naar **+31 6 26773605**. Voor gewone "
             "vragen reageren we doorgaans binnen 24 uur."},
        ]},
        {"titel": "Checklist: ben je startklaar?", "blocks": [
            {"t": "check", "items": [
                "FinalSurge geïnstalleerd met het juiste e-mailadres",
                "Coaching-uitnodiging geaccepteerd (mijn schema staat in de Calendar)",
                "Sporthorloge gekoppeld mét auto-sync aan (één bron)",
                "App op Nederlandse instellingen gezet (week op maandag, km/meters)",
                "Ik weet hoe ik een training naar een andere dag verschuif, en als Garmin-gebruiker "
                "daarna push naar Garmin",
                "Ik weet hoe ik vakantie of een drukke periode in mijn agenda aangeef",
                "Ik weet hoe ik na élke training How I Felt, Perceived Effort en Post Workout Notes invul",
                "Ik weet hoe ik een Pain & Injury Report toevoeg",
                "Ik weet hoe ik contact opneem: comments bij de training, Mailbox los ervan, bellen bij "
                "spoed",
            ]},
        ]},
    ],
}
