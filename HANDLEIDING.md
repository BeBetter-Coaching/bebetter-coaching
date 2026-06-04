# BeBetter Coaching — Feedback Tool
## Handleiding voor de coach

---

## Wat doet deze app?

De app haalt elke dag automatisch alle trainingen op van je atleten in FinalSurge. Hij filtert eruit welke atleten iets hebben geschreven (post-workout notities of comments) en waar jij als coach nog niet op hebt gereageerd. Voor elk van die trainingen schrijft de AI een concept-reactie in jouw stijl. Jij leest het door, past het aan waar nodig, en post het met één klik terug in FinalSurge.

**Wat de app NIET doet:**
- De app post nooit automatisch iets. Jij keurt altijd goed voor het verstuurd wordt.
- De app vervangt jou niet — het is een hulpmiddel om sneller te reageren.

---

## Kan ik de app op een andere computer gebruiken?

Ja, maar je moet de installatiestappen opnieuw doorlopen op die computer. Alles wat je nodig hebt staat in deze handleiding. De Anthropic API key en je FinalSurge login heb je ook nodig op de andere computer.

**Vereisten voor elke computer:**
- Een Mac (de app is voor macOS gemaakt)
- Google Chrome (met je FinalSurge account ingelogd)
- Internetverbinding

---

## Onderdelen die je nodig hebt

| Onderdeel | Wat is het? | Eenmalig of herhalend? |
|---|---|---|
| Anthropic API key | Geeft de app toegang tot de AI | Eenmalig aanmaken |
| Tegoed bij Anthropic | De AI kost een paar cent per feedback | Bijkopen als het op is (~$20 gaat maanden mee) |
| FinalSurge auth-token | Geeft de app toegang tot je FinalSurge | Opnieuw nodig als je bent uitgelogd in Chrome |

---

## Installatie (eenmalig per computer)

### Stap 1: Installeer de app

Open de **Terminal** app op je Mac (zoek via Spotlight: druk **Cmd + Spatie**, typ "Terminal", druk Enter).

Kopieer deze regels één voor één in Terminal en druk telkens op Enter:

```
cd ~/Documents
mkdir finalsurge-feedback
```

Kopieer daarna de app-bestanden naar de map `~/Documents/finalsurge-feedback/`. Dit zijn de bestanden die je van de ontwikkelaar hebt ontvangen:
- `main.py`
- `fs_client.py`
- `ai_feedback.py`
- `requirements.txt`

Installeer vervolgens de benodigde software:
```
cd ~/Documents/finalsurge-feedback
python3 -m pip install -r requirements.txt
```

Dit kan een paar minuten duren. Wacht tot je de gewone prompt (`$`) weer ziet.

---

### Stap 2: Stel je Anthropic API key in

Ga naar **console.anthropic.com** en log in. Klik op **"Get API Key"** → **"Create Key"**. Kopieer de key (begint met `sk-ant-...`).

Open Terminal en plak dit commando (vervang de key door jouw eigen key):

```
echo 'export ANTHROPIC_API_KEY=sk-ant-JOUW-KEY-HIER' >> ~/.zshrc && source ~/.zshrc
```

Druk Enter. De key is nu permanent opgeslagen.

---

## De app starten

Open Terminal en typ:

```
cd ~/Documents/finalsurge-feedback && python3 -m streamlit run main.py
```

Druk Enter. Je browser opent automatisch met de app op het adres `http://localhost:8501`.

**Sluit Terminal nooit af terwijl je de app gebruikt** — de app draait via Terminal op de achtergrond.

Wil je de app stoppen? Klik in Terminal en druk **Ctrl + C**.

---

## Eerste keer: FinalSurge koppelen (eenmalig)

De eerste keer dat je de app opent, vraagt hij om een auth-token. Dit is een beveiligingscode waarmee de app jouw FinalSurge account mag lezen en reageren.

**Zo haal je de token op:**

1. Ga naar **beta.finalsurge.com** in Chrome (zorg dat je bent ingelogd)
2. Druk op **Fn + F12** op je toetsenbord (of: druk op de drie puntjes rechtsboven in Chrome → Meer tools → Ontwikkelaarstools)
3. Klik op het tabblad **"Console"** in het venster dat opent
4. Klik in het invoervak onderaan (waar een `>` staat)
5. Typ dit commando en druk Enter:
   ```
   localStorage.getItem('auth-token')
   ```
6. Er verschijnt een lange code tussen aanhalingstekens. Selecteer alles tussen de aanhalingstekens en kopieer het (**Cmd + C**)
7. Ga terug naar de app, plak de code in het veld "Auth token" (**Cmd + V**)
8. Klik op **Opslaan**

De app onthoudt de token. Je hoeft dit niet opnieuw te doen, tenzij je bent uitgelogd in Chrome op FinalSurge.

---

## Dagelijks gebruik

### De app openen
Start de app via Terminal (zie "De app starten" hierboven). Je browser opent automatisch.

### Overzicht van de interface

**Linkerzijbalk:**

| Onderdeel | Wat doet het? |
|---|---|
| Terugkijkperiode | Hoeveel dagen terug de app kijkt voor trainingen (standaard: 1 dag) |
| Atletengroepen | Vink aan voor welke atleten je feedback wil geven. Laat leeg = alle atleten |
| Ook trainingen zonder notities | Zet dit aan als je ook wil reageren op atleten die niks schreven maar wel gelopen hebben |
| Workouts opnieuw laden | Herlaadt de lijst (handig als er nieuwe trainingen binnenkomen) |
| Opnieuw inloggen | Gebruik dit alleen als de app zegt dat je sessie verlopen is |

**Hoofdscherm:**

De app toont kaarten per workout. Elke kaart heeft twee kolommen:

- **Links:** wat de atleet heeft geschreven (notities en/of comments) + de trainingsdata (afstand, tijd, pace, hartslag)
- **Rechts:** de gegenereerde concept-feedback

### Workflow per dag

1. Open de app
2. Kies eventueel een groep in de zijbalk als je niet alle atleten wil zien
3. Klik op **"Genereer alle concepten (AI)"** voor een concept voor elke openstaande workout
4. Ga de kaarten langs:
   - Lees de atleet-input (links)
   - Lees het concept (rechts)
   - **Pas aan** in het tekstvak waar nodig — dit is altijd aan te raden
   - Klik op **✅ Posten** om de reactie in FinalSurge te plaatsen
   - Klik op **⏭️ Overslaan** als je zelf later wil reageren of niets wil zeggen
   - Klik op **🔄 Opnieuw** als je een nieuw concept wil laten schrijven

---

## Wat toont de app wel en niet?

**De app toont een workout als:**
- De atleet post-workout notities heeft geschreven, EN/OF
- De atleet een comment heeft geplaatst in FinalSurge, EN
- Jij als coach nog niet het laatste woord hebt gehad

**De app toont een workout NIET als:**
- De atleet niks heeft geschreven (tenzij je "Ook trainingen zonder notities" aanzet)
- Jij al hebt gereageerd en de atleet daarna niks meer heeft gezegd
- De workout meer dan [ingestelde dagen] terug was

**Let op:** Als de atleet na jouw reactie nog een bericht heeft gestuurd, toont de app de workout opnieuw. Zo mis je nooit een reactie van een atleet.

---

## Tips voor goede feedback

- **Pas altijd iets aan.** Het concept is een startpunt, niet de eindtekst. Voeg iets persoonlijks toe dat de AI niet weet.
- **Korter is vaak beter.** Zoals je zelf ook doet: soms is één zin genoeg.
- **Gebruik de data.** Links zie je afstand, tempo en hartslag. Als je iets opvallends ziet (veel langzamer dan gepland, hoge hartslag), voeg dat toe aan je reactie.
- **Sla over als je twijfelt.** Liever geen reactie dan een slechte. Gebruik "Overslaan" en reageer handmatig in FinalSurge.

---

## Problemen oplossen

### "De app opent niet in de browser"
Ga zelf naar `http://localhost:8501` in Chrome.

### "Sessie verlopen" of de app vraagt om je token opnieuw
Je FinalSurge sessie in Chrome is verlopen. Doe het volgende:
1. Log opnieuw in op beta.finalsurge.com in Chrome
2. Haal de token opnieuw op (zie "Eerste keer: FinalSurge koppelen")
3. Klik in de app op **"Opnieuw inloggen"** en plak de nieuwe token

### "De comment verschijnt niet in FinalSurge"
Ververs de pagina in FinalSurge (Cmd + R). Als het na een minuut nog niet verschijnt, probeer dan de training opnieuw te openen.

### "De app laadt maar laadt niet klaar"
Met 33+ atleten kan het ophalen even duren (30-60 seconden). Wacht geduldig. Als het echt vastloopt, ververs de app (Cmd + R in de browser).

### "Ik zie een atleet niet in de lijst"
Klik op **"Workouts opnieuw laden"** in de zijbalk. Als de atleet nieuw is toegevoegd in FinalSurge, klik dan op **"Opnieuw inloggen"** om de atletenlijst volledig te verversen.

### "De AI schrijft toch nog met streepjes of formeel"
Klik op **"🔄 Opnieuw"** voor een nieuw concept. Pas het daarna zelf aan.

---

## Kosten

De app gebruikt de Claude AI van Anthropic. Je betaalt per gegenereerde feedback:
- Ongeveer €0,01-0,02 per feedback (1-2 cent)
- Bij 10 feedbacks per dag: ±€0,15 per dag
- $20 aan tegoed gaat gemiddeld 3-6 maanden mee

Je ziet je huidig tegoed op **console.anthropic.com** onder "Billing".

---

## Bestanden en mappen

Alles staat in: `~/Documents/finalsurge-feedback/`

| Bestand | Wat is het? |
|---|---|
| `main.py` | De app zelf (interface) |
| `fs_client.py` | Verbinding met FinalSurge |
| `ai_feedback.py` | De AI-instructies en feedbackgeneratie |
| `requirements.txt` | Lijst van benodigde software |
| `~/.fs_auth_token` | Je opgeslagen FinalSurge token (automatisch aangemaakt) |

---

*Vragen of problemen? Neem contact op met de ontwikkelaar.*
