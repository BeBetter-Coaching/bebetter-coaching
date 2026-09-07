# Feedback — queue/detail-consistentie · Michael-case

**Productie:** `3f12f53` · **Scope:** één P1-consistentiecase, verder niets.
Onderzocht read-only; geen echte feedback gegenereerd of verstuurd.

## Waargenomen

Michael ter Horst · `Fartlek race prep` · week 37:

| | |
|---|---|
| Wachtrij-rij | badge `Reactie`, preview `Voelde mij goed. Nuchte…` |
| Detailpaneel | `Geen bericht van de atleet — reageer op de uitvoering.` |

Serkan en Esther renderen hun thread wél correct.

## Wat er NIET aan de hand is

De vijf hypothesen uit de opdracht zijn allemaal langsgelopen; vier vallen af op code:

* **Preview van een andere workout/sessie (hyp. 1 en 2).** Afgevallen. Zowel de badge als de
  preview komen uit `feedback_core._categorie(w)` → `_atleet_berichten(w)`, en die leest
  UITSLUITEND velden van dit ene workout-record (`w["thread"]`, `w["post_notes"]`,
  `w["athlete_comments"]`). Er is geen enkele lookup over meerdere workouts, geen "laatste
  bericht van deze atleet"-fallback en geen datum-scoping die kan verschuiven. De
  sessie-identiteit is per constructie één workout.
* **Preview en detail gebruiken andere bronvelden (hyp. 4).** Afgevallen als ZELFSTANDIGE
  oorzaak. `_atleet_berichten` heeft weliswaar een fallback (`post_notes` +
  `athlete_comments`) die `_gesprek` niet heeft, maar die kan hier niet vuren:
  `fs_client.build_thread` zet `post_notes` altijd als eerste thread-item, dus
  "post_notes gevuld terwijl de thread leeg is" bestaat niet binnen één record. Voor
  hetzelfde `w`-object kunnen queue en detail dus niet uit elkaar lopen.
* **Detail verliest de koppeling op workout_key (hyp. 3, lookup-variant).** Afgevallen.
  De client haalt het detail op met `encodeURIComponent(id)` en `id` IS de `workout_key`;
  `detail()` en `_queue_item()` lezen allebei via diezelfde sleutel uit `_cache`.

## Root cause

**Hypothese 5, en hij is exact aanwijsbaar:** `_cache` volgt de queue-snapshot alleen in
LIDMAATSCHAP, niet in INHOUD.

`pwa/feedback_core.py:1177 _herstel_cache()`:

```python
volle = snap.get("_volle") or {}
for wid, w in volle.items():
    _cache.setdefault(wid, w)          # ← bestaat de key al, dan blijft het OUDE object staan
```

Bij elke sweep gebeurt er daardoor twee verschillende dingen met dezelfde workout:

* **De queue-ITEMS worden vers gebouwd** (`_bouw_queue` → `_queue_item(wid, w_nieuw)`), dus
  `categorie` en `preview` komen uit de nieuwste FinalSurge-lezing.
* **`_cache[wid]` blijft het object van de EERSTE sweep die deze workout zag.** `setdefault`
  schrijft niet over een bestaande key heen.

`detail()` leest `_cache[wid]` (via `get_or_restore_workout`) en bouwt `gesprek` uit
`_gesprek(w)`. Die leest dus het bevroren object.

Voor Michael betekent dat:

1. Sweep A ziet de `Fartlek race prep` als een UITGEVOERDE geplande training zonder tekst
   (de queue neemt die mee via `include_planned_no_notes=True`). Item = `uitgevoerd`,
   `_cache[wid] = w_A` met een lege thread.
2. Michael schrijft daarna zijn post-workout-notitie.
3. Sweep B leest die notitie wél. Het nieuwe ITEM wordt `reactie` + preview
   `Voelde mij goed. Nuchter…`. Maar `_herstel_cache` doet `setdefault` → **`_cache[wid]`
   blijft `w_A`**.
4. De coach opent de case → `detail()` leest `w_A` → `gesprek == []` →
   "Geen bericht van de atleet".

Lokaal gereproduceerd met exact die twee sweeps:

```
A item: uitgevoerd        | detail gesprek: []
B item: reactie           | preview: 'Voelde mij goed. Nuchter gelopen.'
B detail gesprek: []      | cache is verse object? False
INCONSISTENT: True
```

## Welke kant is fout?

**Het detail.** De wachtrij toont de nieuwste waarheid; het detailpaneel verliest een geldig,
sessie-gekoppeld atleetbericht omdat het uit een bevroren kopie van dezelfde workout leest.
De invariant uit de opdracht wordt dus hersteld door het detail bij te trekken, niet door de
badge weg te halen.

## Kan dit andere cases raken?

Ja, en het verklaart ook waarom Serkan en Esther het niet laten zien.

De divergentie treedt op zodra **atleet-input binnenkomt NADAT de workout al in de queue
stond**. Serkan en Esther kwamen in de wachtrij *omdát* ze iets schreven: hun bericht zat er
bij de eerste sweep al in, dus hun bevroren object is toevallig correct. Michael's training
stond er al als uitgevoerde geplande sessie; zijn notitie kwam later.

Alles wat na de eerste sweep verandert, is in het detail bevroren: `post_notes`, `felt`,
`effort`, `athlete_comments`, `thread`, en ook `workout_name`. Eén restart of deploy maskeert
het (dan wordt `_cache` opnieuw uit de verse snapshot gevuld), wat het onregelmatig laat lijken.

Twee dingen die het effect tot nu toe hebben afgeschermd:

* De GENERATIE is beschermd: `genereer()` roept eerst `_refresh_thread(w)` aan, die de
  comments live herleest. Een ná de sweep binnengekomen *comment* haalt de prompt dus wel.
  Een ná de sweep binnengekomen *post_note* niet: `_refresh_thread` geeft
  `w.get("post_notes")` (de bevroren waarde) door aan `build_thread`.
* De ORDENING is niet geraakt: die draait op de verse `items`, niet op `_cache`.

Dit is **geen regressie van `3f12f53`**. De `setdefault` is oud; de veldronde raakte
queue/copy niet aan.

## Severity

**P1 — coach-vertrouwen, geen datacorruptie.** Er gaat niets verloren in FinalSurge en er
wordt niets verkeerds gepost. Maar de coach ziet een citaat in de lijst dat in de case
verdwenen is, en kan bij het handmatig beantwoorden een bericht missen dat de atleet wél
gestuurd heeft.

## Minimale fix

`_herstel_cache` laat `_cache` de snapshot óók in inhoud volgen, met behoud van precies de
twee redenen waarom `setdefault` er stond:

* **object-identiteit** voor overlevende keys → in-place `clear()` + `update()`, niet
  vervangen;
* **de lazy geladen `details`** (de geheugenreden uit de Render-ronde) → expliciet
  overgezet als het verse record ze niet heeft.

De pruning-helft van `_herstel_cache` (de grens uit `render-memory-bounded-caches-v1`) blijft
letterlijk staan. Er verandert niets aan `_categorie`, `_atleet_berichten`, `_gesprek`,
`_queue_item`, de sortering, `_CAT_RANK`, generatie/copy, MetricAuthority, klachtlogica, de
F1-F5-veldfixes of het post/skip/re-post-pad.

Bijvangst voor het geheugen: `_cache[wid]` en `snap["_volle"][wid]` zijn na de eerste sweep
niet langer hetzelfde object, dus `_ensure_details` schrijft de laps van een geopende training
niet meer in de durable snapshot. `_persist_payload` blijft als vangnet staan (die dekt de
sweep waarin de key nieuw is).
