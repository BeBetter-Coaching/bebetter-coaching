# BeBetter PWA — proto (strippenkaart)

Een lokaal werkend proto van de strippenkaart als **PWA** (installeerbare web-app),
los van Streamlit. Doel: laten zien hoe "weg van Streamlit" voelt, zonder de live
app aan te raken.

## Belangrijk: zelfde data als Streamlit
De API praat via `strippen_core.py` met hetzelfde `intake_store` als de Streamlit-app.
Er is dus **één bron**: wat je hier afboekt of toevoegt, zie je in Streamlit terug
(bij verversen) en andersom.
- **Lokaal** (geen `GH_TOKEN`): beide gebruiken het bestand `../.strippenkaarten.json`.
- **Met token** (zoals op de cloud): beide gebruiken de gedeelde GitHub-opslag.

## Lokaal draaien
```bash
cd pwa
python3 -m pip install -r requirements.txt
python3 -m uvicorn api:app --reload --port 8000
```
Open daarna **http://localhost:8000**.

> Tip: start uvicorn als module (`python3 -m uvicorn ...`). Dan maakt het niet uit
> of de `uvicorn`-scriptmap wel of niet in je PATH staat (`zsh: command not found:
> uvicorn` komt daarvandaan).

## Installeren als app
- **Mac/Windows** (Chrome/Edge): install-icoon in de adresbalk, of menu → "App installeren".
- **iPhone** (Safari): deelknop → "Zet op beginscherm".
- **Android** (Chrome): menu → "App installeren".

## Wat het proto kan
- Strippenkaarten zien met voortgangsbalk (X van Y over).
- Strip afboeken / terugdraaien; na afboeken verschijnt een **WhatsApp-knop** met
  het nummer én het bericht al ingevuld (één tik verzenden).
- Nieuwe kaart toevoegen (naam, telefoon, 10/20).
- Bulk-import: "Naam, nummer" plakken of een `.vcf` kiezen, met controle-stap.

## Wat er nog NIET in zit (bewust, dit is een proto)
- Geen inlog/beveiliging (draait alleen lokaal op je eigen machine).
- Nog niet gehost; de "thuis voor de backend"-keuze komt als je dit goedkeurt.
- Alleen de strippenkaart; overige modules volgen scherm-voor-scherm.

## Structuur
```
pwa/
  api.py            FastAPI-backend (serveert de app + JSON-API)
  strippen_core.py  gedeelde logica op intake_store (herbruikbaar, ook door Streamlit)
  static/           frontend: index.html, app.js, styles.css, manifest, service worker, icons
  requirements.txt  proto-deps (raakt de Streamlit-requirements niet)
```
