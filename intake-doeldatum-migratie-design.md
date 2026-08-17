# Intake: doeldatum als primaire waarheid (migratie-ontwerp)

> Status: **ONTWERP — geparkeerd, niet geïmplementeerd.** Besloten in de live-
> herstelronde (17 aug 2026): F wordt niet in de correctness-ronde gebouwd omdat
> de enige gedrag-bepalende `weken`-consumer in LOCKED plan-generatie zit. Dit
> document legt de veilige, backwards-compatible route vast voor een aparte,
> expliciet goedgekeurde ronde.

## Kern van het probleem
De coach denkt in een **doeldatum** (wedstrijd-/streefdatum), niet in "over N
weken". `weken` is nu de opgeslagen waarheid en verschuift betekenis met de tijd:
"12 weken" op 1 aug ≠ "12 weken" op 15 aug. Een absolute datum is stabiel.

## Wat er nu al is (geen greenfield)
- **Echte datums bestaan al** in de builder-intake: `wedstrijddatum` (ISO, de
  uiteindelijke wedstrijd — mag verder liggen dan het schema) en
  `schema_einddatum` (ISO, einde van dít blok). De builder biedt al "aantal weken
  **OF** vaste einddatum" als twee ingangen aan (`builder_page.py:529-566`).
- **Vrije-tekst** `wedstrijddatum_tekst` uit de intakeformulieren
  (`intake_form.py`, `pwa/intake_core.py`) — nu puur weergave, geen ISO.
- **FinalSurge** draagt echte ISO-racedatums (`workout_date` op is_race).
- **Conversie bestaat al beide kanten op**: `schema_core._bereken_periode(start,
  weken, schema_einddatum)` is Monday-aligned en geeft `(weken_int, einddatum_iso)`
  terug — het accepteert al een einddatum en leidt daar weken uit af.

## Het enige echte knelpunt
1. **Load-bearing consumer in LOCKED code**: `schema_builder.py:1191`
   `weken_aantal = int(intake.get("weken") or 8)` — dit is de lusgrens die de
   week-voor-week datumkalender genereert (plan + CSV). Datum-primair maken
   betekent hier `weken` afleiden uit `(einddatum − start_monday)` i.p.v. lezen.
   **Dit raakt Schema-plan-generatie → mag alleen in een aparte, goedgekeurde
   Schema-ronde, met byte-identieke regressiegarantie voor bestaande intakes.**
2. **Startanker verdwijnt bij opslag**: `save_laatste_intake` stript `startdatum`
   (`intake_store.py:746`). Zonder duurzaam startanker is datum↔weken niet
   lossless over sessies: op herladen kiest `config_prefill` een nieuwe
   `startdatum` en herberekent einddatum uit `weken` — de opgeslagen absolute
   datum wordt effectief genegeerd. `weken` is nu dus de duurzame relatieve
   waarheid; de opgeslagen datum is niet gezaghebbend.

## Volledige `weken`-consumerinventaris (impact)
**Gedragsbepalend (moet via conversie):**
- `schema_builder.py:1191` — lusgrens weekkalender (LOCKED). *De enige echte.*
- `schema_builder.py:874-923` — prompt-/samenvattingstekst ("loopt tot … (N weken)").

**Conversie (single source):**
- `schema_core._bereken_periode` (`:245-264`), aangeroepen op `:348`, `:383`, `:693`.

**Weergave/hint (geen logica):**
- `schema_core.py:76/93/122/274/291/352`, `pwa/static/app.js` (list-card meta),
  `builder_page.py:571-579`.

## Voorgestelde eindtoestand
**Doeldatum is primair waar een echt tijdsgebonden doel bestaat; `weken` wordt
afgeleid.** Geen datum? Dan blijft `weken` bruikbaar (legacy pad intact).

Concreet:
1. **Eén gezaghebbende doeldatum kiezen.** Voorstel: behoud het bestaande
   onderscheid — `schema_einddatum` = einde van dít blok (stuurt de kalender),
   `wedstrijddatum` = het uiteindelijke doel (mag verder liggen). De **doeldatum
   voor planning = `schema_einddatum`**; `wedstrijddatum` blijft context. (Dit
   respecteert wat de builder nu al doet; geen nieuwe semantiek.)
2. **Startanker duurzaam maken.** Stop met `startdatum` strippen in
   `save_laatste_intake`, óf sla het gekozen doel op als absolute datum + een
   expliciete `startdatum`, zodat datum↔weken lossless blijft.
3. **`weken` afgeleid, niet leidend.** In de intake-UI wordt de doeldatum ingevoerd;
   `weken` wordt getoond als afgeleide ("= 11 weken tot 18 okt"). Opslag bewaart
   bij voorkeur **beide** (datum als bron van waarheid, `weken` als cache) om
   downstream niets te breken.
4. **Plan-generatie ongemoeid tot aparte ronde.** Tot dan leest
   `schema_builder.py` gewoon `weken` (dat we blijven meeschrijven). Zo is stap
   1-3 puur intake-laag en raakt Schema niet.

## Backwards compatibility
- Bestaande `laatste_intakes.json`-records met alleen `weken` blijven werken:
  ontbreekt een doeldatum → gedraag je exact als nu (weken leidend).
- Nieuwe records dragen doeldatum + afgeleide `weken`. `nieuwste_intake` en alle
  lezers blijven `weken` zien.
- Geen migratie-script nodig als we `weken` blijven meeschrijven; optioneel later
  een backfill die uit `weken` + laatst bekende start een doeldatum reconstrueert.

## Timezone/grens-risico
Alles is pure `datetime.date`-rekenkunde, Maandag=0 uitlijning overal. Geen tz/DST-
hazard, mits de Monday-alignment-invariant (waar elke conversie op leunt) intact
blijft. Jaarwisseling/lente: `timedelta`-gebaseerd, veilig.

## Acceptance (voor de latere bouwronde)
- Doeldatum kiezen → afgeleide weken klopt met de gegenereerde weekkalender.
- Bestaande weken-only intake: plan-output **byte-identiek** aan nu (regressietest).
- Jaarwisseling/leap/Monday-grenzen: conversie klopt in een matrix van (start, doel).
- Geen enkele wijziging aan gepubliceerde/bestaande schema's.

## Waarom nu geparkeerd
Elke echte doeldatum→weken-omslag raakt `schema_builder.py:1191` (LOCKED) en vraagt
het startanker terug + een migratiebesluit over welke datum gezaghebbend is. Dat
hoort in een aparte Schema-ronde met byte-identieke regressiegarantie — niet in een
correctness-herstelronde. De intake-laag-voorbereiding (stap 2-3) kan later
onafhankelijk, zonder Schema te raken.
