# Werkinstructie: BeBetter Coaching App (Windows)

**Voor wie:** Jip — niet-technische gebruiker op Windows  
**Wat is dit:** Een coachtool die verbinding maakt met FinalSurge en AI (Claude) om coaching te ondersteunen.

---

## Inhoudsopgave

1. [Eenmalige installatie](#1-eenmalige-installatie)
2. [API-sleutel instellen](#2-api-sleutel-instellen-eenmalig)
3. [App opstarten](#3-app-opstarten-elke-keer)
4. [FinalSurge-token ophalen](#4-finalsurge-token-ophalen)
5. [Module 1 — Feedback geven](#5-module-1--feedback-geven)
6. [Module 2 — Schema-verloop](#6-module-2--schema-verloop)
7. [Module 3 — Schema bouwen](#7-module-3--schema-bouwen)
8. [Problemen oplossen](#8-problemen-oplossen)

---

## 1. Eenmalige installatie

Dit doe je maar één keer. Daarna hoef je dit nooit meer te doen.

### Python installeren

1. Ga naar [python.org/downloads](https://www.python.org/downloads/) en klik op de grote gele knop **Download Python 3.11** (of hoger).
2. Open het gedownloade installatiebestand.
3. **Belangrijk:** Zet een vinkje bij **"Add Python to PATH"** onderaan het installatiescherm voordat je op Install klikt. Zonder dit vinkje werkt de app niet.
4. Klik op **Install Now** en wacht tot de installatie klaar is.
5. Klik op **Close**.

### App-bestanden klaarzetten

Zorg dat de app-map op je computer staat. Je mag de map **zelf kiezen en een naam geven die je makkelijk terugvindt**, bijvoorbeeld:

```
C:\Users\Jip\Documents\BeBetter\
```

of

```
C:\BeBetter\
```

Onthoud waar je de map hebt neergezet — je hebt het pad nodig in de volgende stap.

### Benodigde onderdelen installeren

1. Druk op de Windows-toets, typ `cmd` en druk op **Enter**. Er opent een zwart scherm — dat is de Opdrachtprompt (Command Prompt).
2. Navigeer naar de app-map door het volgende te typen en op Enter te drukken — vervang het pad door de map die jij hebt gekozen:
   ```
   cd C:\Users\Jip\Documents\BeBetter
   ```
3. Typ het volgende en druk op **Enter**:
   ```
   pip install -r requirements.txt
   ```
4. Wacht. Er wordt van alles gedownload en geïnstalleerd. Dit kan een paar minuten duren. Je ziet veel tekst voorbijkomen — dat is normaal.
5. Klaar als je weer een knipperende cursor ziet.

---

## 2. API-sleutel instellen (eenmalig)

De app heeft een sleutel nodig om verbinding te maken met de AI. Dit stel je eenmalig in als Windows-omgevingsvariabele.

1. Klik op de Windows-startknop en typ: **omgevingsvariabelen**
2. Klik op **"De omgevingsvariabelen voor uw account bewerken"**
3. Er opent een venster. Klik in het bovenste gedeelte (jouw gebruikersvariabelen) op **Nieuw**.
4. Vul in:
   - **Naam van variabele:** `ANTHROPIC_API_KEY`
   - **Waarde van variabele:** plak hier de API-sleutel die je van Anthropic hebt gekregen
5. Klik op **OK**, dan nog een keer op **OK**.
6. Start de app opnieuw op als deze al open was.

---

## 3. App opstarten (elke keer)

Je hebt twee opties. Optie A is het makkelijkst.

### Optie A — Dubbelklikken (aanbevolen)

Ga naar de app-map in Verkenner en dubbelklik op het bestand:

```
start_windows.bat
```

Er opent een zwart scherm even, en daarna gaat de app automatisch open in je browser. Als de browser niet vanzelf opengaat, ga dan naar: [http://localhost:8501](http://localhost:8501)

### Optie B — Via de Opdrachtprompt

1. Open de Opdrachtprompt (`cmd`).
2. Typ het pad naar jouw app-map (vervang dit door jouw eigen map):
   ```
   cd C:\Users\Jip\Documents\BeBetter
   ```
3. Typ:
   ```
   python -m streamlit run main.py
   ```
4. Open je browser en ga naar [http://localhost:8501](http://localhost:8501)

> **Let op:** Sluit het zwarte scherm (Opdrachtprompt) niet af zolang je de app gebruikt. De app draait daarin.

---

## 4. FinalSurge-token ophalen

De app moet weten wie jij bent op FinalSurge. Dit doe je via een token — een soort tijdelijk wachtwoord. Je hoeft dit alleen opnieuw te doen als je uitgelogd bent bij FinalSurge.

1. Open **Google Chrome** en ga naar [beta.finalsurge.com](https://beta.finalsurge.com).
2. Log in met je FinalSurge-account.
3. Druk op de toets **F12** op je toetsenbord. Er opent een paneel aan de rechterkant of onderkant van het scherm.
4. Klik bovenin dat paneel op het tabblad **Application** (soms moet je op `>>` klikken om het te zien).
5. Aan de linkerkant zie je een lijstje. Klik op **Local Storage** en dan op **https://beta.finalsurge.com**.
6. Zoek in de lijst rechts naar de rij met de naam **auth-token**.
7. Klik op die rij. Rechts (of onderaan) zie je een lange tekst — dat is je token. Klik erop en kopieer de hele waarde (Ctrl+A, dan Ctrl+C).
8. Ga terug naar de app in je browser en plak de token in het veld **"FinalSurge Token"**.
9. Klik op **Opslaan** of **Verbinding maken**.

De token wordt opgeslagen. Je hoeft dit niet elke keer opnieuw te doen — alleen als je bent uitgelogd bij FinalSurge.

---

## 5. Module 1 — Feedback geven

In deze module zie je welke atleten een aantekening of RPE-score hebben achtergelaten na hun training en nog wachten op een reactie van jou.

### Stap voor stap

1. Klik in de app op **Module 1 — Feedback**.
2. Je ziet een lijst van atleten met hun trainingsnoten en/of RPE-score.
3. Klik op een atleet om de details te zien: wat ze hebben geschreven, de training zelf, en de door AI gegenereerde conceptreactie in jouw stijl.
4. Lees de conceptreactie door. Pas hem aan waar nodig — het is een startpunt, geen definitief bericht.
5. Als je tevreden bent met de tekst, klik je op **Verstuur feedback**.
6. De reactie wordt direct in FinalSurge geplaatst als coachremark bij de training.
7. Ga door naar de volgende atleet.

> **Tip:** De AI probeert jouw schrijfstijl na te bootsen, maar jij kent je atleten het best. Vertrouw op je eigen gevoel bij het aanpassen.

---

## 6. Module 2 — Schema-verloop

In deze module krijg je een overzicht van kritische atleten en hun trainingsopvolging — wie loopt achter, wie traint te hard, of wie al een tijdje niets heeft ingevuld.

### Wat je ziet

- Een tabel of kaartjes per atleet met hun recente trainingsactiviteit.
- Kleurcodering geeft snel aan hoe het gaat: groen is goed, oranje vraagt aandacht, rood betekent actie nodig.
- Je ziet geplande versus uitgevoerde trainingen, en eventuele opvallende afwijkingen.

### Wat je doet

1. Klik in de app op **Module 2 — Schema-verloop**.
2. Bekijk de lijst. Atleten met een rode of oranje status verdienen eerst aandacht.
3. Klik op een atleet voor meer detail: een weergave van de afgelopen weken met geplande en uitgevoerde trainingen.
4. Gebruik deze informatie als input voor je coaching — bel de atleet, stuur een berichtje, of pas het schema aan in Module 3.

---

## 7. Module 3 — Schema bouwen

Met deze module bouw je trainingsschema's met behulp van AI en importeer je ze direct in FinalSurge.

### Nieuwe atleet

1. Klik op **Module 3 — Schema bouwen**.
2. Kies **Nieuwe atleet** of vul de naam in het zoekveld in.
3. Vul het formulier in:
   - **Naam atleet**
   - **Doel** (bijv. marathon, 10 km, algemene conditie)
   - **Startdatum schema**
   - **Einddatum / wedstrijddatum**
   - **Aantal trainingsdagen per week**
   - **Huidig niveau** (bijv. beginner, gevorderd)
   - Eventuele extra opmerkingen of blessurehistorie
4. Klik op **Genereer schema**.
5. De AI maakt een trainingsplan op basis van jouw input.

### Bestaande atleet

1. Zoek de atleet op via het zoekveld — de app haalt bestaande gegevens op uit FinalSurge.
2. Pas het formulier aan waar nodig (bijv. nieuwe wedstrijddatum of gewijzigd trainingsvolume).
3. Klik op **Genereer schema**.

### Schema beoordelen en importeren

1. Na het genereren zie je het schema week voor week weergegeven, met trainingstype, duur en intensiteitszone per dag.
2. Controleer het schema. Klik op een training om details te zien of handmatig aan te passen.
3. De zones zijn gekoppeld aan de werkplekzones uit FinalSurge (bijv. Zone 2, drempeltraining) — die worden automatisch correct ingevuld.
4. Als je tevreden bent, klik je op **Importeer in FinalSurge**.
5. De trainingen worden direct in de FinalSurge-kalender van de atleet gezet.
6. Open FinalSurge om te controleren of alles goed staat.

> **Tip:** Importeer liever wat te vroeg dan te laat. Je kunt trainingen in FinalSurge altijd nog aanpassen nadat ze zijn geïmporteerd.

---

## 8. Problemen oplossen

### De app start, maar toont een foutmelding

**Oorzaak:** Je FinalSurge-token is verlopen (je bent uitgelogd bij FinalSurge).  
**Oplossing:** Haal een nieuw token op via de stappen in [hoofdstuk 4](#4-finalsurge-token-ophalen) en plak het opnieuw in de app.

---

### "pip is not recognized" of "pip wordt niet herkend"

**Oorzaak:** Python is niet correct toegevoegd aan het PATH tijdens de installatie.  
**Oplossing:**
1. Verwijder Python via **Instellingen > Apps**.
2. Download Python opnieuw van [python.org](https://www.python.org/downloads/).
3. Start de installatie opnieuw en let erop dat je het vinkje bij **"Add Python to PATH"** zet.
4. Voer daarna opnieuw de stappen uit in [hoofdstuk 1](#1-eenmalige-installatie).

---

### "Port 8501 already in use" of de app start niet op

**Oorzaak:** Er draait al een ander exemplaar van de app in een ander terminalvenster.  
**Oplossing:**
1. Kijk of er een zwart Opdrachtprompt-venster open staat dat je eerder hebt gebruikt voor de app.
2. Sluit dat venster.
3. Start de app opnieuw op.

Als je het venster niet kunt vinden: herstart je computer en probeer het dan opnieuw.

---

### De browser opent niet vanzelf

**Oplossing:** Open je browser handmatig en ga naar:

```
http://localhost:8501
```

---

### De AI-feedback werkt niet of geeft een foutmelding over de API

**Oorzaak:** De `ANTHROPIC_API_KEY` is niet juist ingesteld.  
**Oplossing:** Controleer of je de stappen in [hoofdstuk 2](#2-api-sleutel-instellen-eenmalig) correct hebt uitgevoerd. Let op: na het instellen van de omgevingsvariabele moet je de app opnieuw opstarten.

---

*Vragen of iets werkt niet? Neem contact op met de persoon die de app heeft gebouwd.*
