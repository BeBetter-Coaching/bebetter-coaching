# Dossier Fase B — Menselijke Masterbrein-cockpit (topniveau design-doc)

Status: **DEFINITIEF v1 — klaar voor bouw-GO.** Scope-keuzes A–E vastgelegd (§12),
drie 10s-scenario's bewezen (§15), hertoetst aan de zes principes (§16).
**Nog niets gebouwd.** Datum: 17 aug 2026. Auteur: Claude (voor Jip). Verwant:
`dossier-architecture-design.md`, `pwa/brain/` (Masterbrein V2), memory
`dossier-fase-a-history-foundation`, `bebetter-masterbrein-context`.

---

## 0. Wat dit is (en niet is)

Fase B = de **menselijke cockpit** op Masterbrein V2. Het is een **view/leeslaag**,
**geen tweede intelligence-engine**. Alle betekenis (status, klacht-lifecycle, load,
conflicten, source-health, provenance) komt uit `AthleteState` + de bestaande
projecties. De cockpit **berekent zelf niets** en **schrijft niets** — hij
selecteert, prioriteert en presenteert wat Masterbrein al weet.

**Productlat (hard):** binnen **~10 seconden** begrijpt de coach vier dingen over
één atleet:
1. **Hoe staat hij ervoor?** (overall + betrouwbaarheid van dat oordeel)
2. **Wat is er veranderd?** (betekenisvolle recente verschuivingen)
3. **Wat vraagt aandacht?** (actionable nu)
4. **Waarom?** (onderbouwing/provenance, op afroep)

**v1 = read-only.** Coach-edit-acties (confirm/correct/resolve/add-context) komen
expliciet later (zie §11).

---

## 1. Toetssteen: de zes principes als ontwerp-rubric

Elke sectie/keuze hieronder is getoetst aan:

| Principe | Concrete eis in dit ontwerp |
|---|---|
| **Eén waarheid** | Cockpit leest uitsluitend `AthleteState`/projecties/history-store via de bestaande read-API's. Geen tweede afleiding, geen eigen intake-parser, geen kopie. |
| **Longitudinale samenhang** | Huidige status + (later) event-tijdlijn komen uit dezelfde `athlete_key`; history-events dragen `effective_at`/`transition`/provenance. |
| **Herbruikbaarheid** | Gedeelde Athlete Picker, hash-routing (`#dossier/<user_key>`), `ui_sections`-patroon, source-health-degradatie (net als de intake-flow-fix). |
| **Coach-efficiëntie** | Niets dat de coach al invoerde opnieuw vragen; deep-links naar Schema/Feedback; 10s-antwoord bovenaan; provenance op afroep, niet default. |
| **Veiligheid** | truth_type / provenance / freshness / **unknown blijft unknown** / conflict zichtbaar; bronfout ≠ "niets bekend" (source-health-onderscheid). |
| **Schaalbaarheid** | Eén view-model-endpoint per atleet uit `for_dossier`; geen fan-out; history via de geabstraheerde store-API (sharding-klaar). Werkt bij 100+ atleten. |

---

## 2. Databronnen (single truth) — content → bron-mapping

De cockpit put **alleen** uit bestaande lagen:

| Cockpit-content | Bron (bestaand) | Opmerking |
|---|---|---|
| Overall status (GOOD/STABLE/ATTENTION/INSUFFICIENT_DATA) | `AthleteState.overall` via `projections.for_dossier` | good-is-good-gate: nooit GOOD zonder taak-relevante bron |
| Aandachtspunten (actionable) | `projections.for_home`-logica (active/recurring klacht, `load.signal=hoog`, `possible_relation`, zone-review) + `state.conflicts` | zelfde selectie als Home, MEDIUM/HIGH |
| Huidige toestand per domein | `for_dossier` evidence (load, health, recovery, goal, zones, training_response, profile, coach) | inclusief de nieuwe intake-evidence (merge `bbe537b`) |
| Klacht-lifecycle (actief/recent/terugkerend/hersteld/historisch) | `complaint.*` groep-evidence + status | verbatim melding + status, geen her-interpretatie |
| Source-health / bronuitval | `AthleteState.sources` (`SourceHealth`), `source_gaps` | available/stale/last_success/coverage |
| Last-known-good / verouderd | evidence `status=STALE` + `detail.last_known_good` | "laatst bekend, mogelijk verouderd" |
| Provenance / "waarom" | `brain.state.explain(evidence_id, state)` | truth-type + bronketen + datums + strength |
| Betekenisvolle veranderingen (tijdlijn) | `history_store.get_events` / `get_recent_events` / `index` | **zie §3 — capture OFF-constraint** |
| Doel/planning-context | `goal.*` evidence + deep-link naar Schema | geen dubbele planning-UI |

**Geen nieuwe store, geen nieuwe intelligentie.** Eén nieuw *leesendpoint*
(`/api/dossier/cockpit?key=`) dat een **view-model** samenstelt uit `for_dossier`
+ (indien aanwezig) history-index. Één `build_state` per load (zoals Schema/Feedback).

---

## 3. Cruciale constraint: history-capture staat OFF (en is vanaf-nu)

- **Productie-capture is bewust OFF** (`BEBETTER_DOSSIER_HISTORY=off`, Fase A gelockt).
- Zelfs bij aanzetten geldt **vanaf-nu** (geen backfill) → de event-tijdlijn is
  **initieel leeg** en vult zich pas over tijd.

**Ontwerpgevolg (belangrijk):** de pijler *"wat is er veranderd?"* mag in v1 **niet**
afhangen van de event-log. v1 leidt "veranderd/aandacht" af uit **AthleteState-status-
semantiek** die er nu al is:
- `status ∈ {RECENT, RECURRING}` op klachten = recent/terugkerend;
- `load.interruption` = onderbreking/hervat;
- `status=STALE` + last-known-good = bron verouderd (aandacht voor betrouwbaarheid);
- `state.conflicts` / `source_gaps` = onzekerheid die aandacht vraagt;
- `overall=ATTENTION/INSUFFICIENT_DATA` = kop-signaal.

De **event-tijdlijn** (Zone 4) is een **additieve, progressive-disclosure sectie**
met een **eerlijke lege staat die "geen events" nadrukkelijk NIET gelijkstelt aan
"geen historie"**:

> *"Er is nog geen longitudinale tijdlijn vastgelegd. BeBetter bouwt de historie op
> vanaf het moment dat history-capture wordt geactiveerd (vanaf-nu; er is bewust
> geen terugwerkende reconstructie). 'Geen events' betekent hier dus niet 'deze
> atleet heeft geen historie' — alleen dat er nog niets is vastgelegd."*

Zo blokkeert v1 niet op een aparte capture-aan-beslissing, en liegt de lege tijdlijn
niet. **BESLIST (§12-A):** cockpit-first; productie-capture blijft voorlopig OFF;
aanzetten is een latere, aparte gated beslissing.

---

## 4. Informatie-architectuur — prioriteitsstapel (het 10s-budget)

De cockpit is een **prioriteitsstapel**, niet een profielpagina. Van boven naar
beneden, met een expliciet "seconden-budget":

**Zone 0 — Statuskop (≈2s): "hoe staat hij ervoor + kan ik dit vertrouwen"**
- Naam + groep (identiteit, canonieke `user_key`).
- **Overall-badge**: GOOD / STABLE / ATTENTION / INSUFFICIENT_DATA — met kleur.
- **Betrouwbaarheids-stip**: source-health samenvatting (alle taak-bronnen vers /
  één stale / kernbron uitgevallen). INSUFFICIENT_DATA = expliciet "te weinig data
  voor een oordeel", niet "goed".
- Sticky op mobiel; blijft in beeld tijdens scrollen.

**Zone 1 — Aandacht nu (≈4s): "wat vraagt aandacht en waarom"**
- 0–4 aandachtskaarten uit de for_home-selectie + conflicten + kernbron-gaps.
- Elke kaart: 1 regel **wat** + 1 regel **waarom** (verbatim onderbouwing/datum/bron).
- Leeg = expliciet groen: *"Geen actiepunten — geen actieve klacht/signaal bekend."*
  (Alleen als de bronnen gezond zijn; anders "onzeker door bronuitval".)
- **Dit is het hart van de 10s-regel.** Als hier niets fout-positief of leeg-
  misleidend staat, heeft de coach binnen ~6s een correct beeld.

**Zone 2 — Recent veranderd (≈2s): "wat is er verschoven" — alleen als betrouwbaar**
- **BESLIST (§12-D): v1 toont hier UITSLUITEND verschuivingen die AthleteState nú
  echt als recency draagt** — géén pseudo-history, reconstructie of verzonnen
  gebeurtenis. Toegestane v1-bronnen (alle bestaand, met echte temporele betekenis):
  - klacht-groep `status ∈ {RECENT, RECURRING}` mét `detail.dates` → "recent/terugkerend";
  - `load.interruption` aanwezig → "onderbreking/hervat";
  - evidence `status=STALE` + `detail.last_known_good` → "bron verouderd sinds …";
  - nieuw aanwezige `state.conflicts` → "tegenstrijdige bron".
- **Geen betrouwbare recency → de sectie toont niets** (geen "geen verandering"-ruis
  forceren; afwezig = afwezig).
- **Drop-in-pad naar echte HistoryEvents (geen parallelle waarheid):** Zone 2 leest
  uit één `changes[]`-slice van het view-model met een **vaste vorm**
  (`{title, effective_at, transition, entity, provenance_refs, source}`). In v1 vult
  de backend die slice deterministisch uit AthleteState-status en labelt elk item
  `derived_from="state"`. Zodra history-capture aanstaat, vult dezelfde slice zich uit
  **echte HistoryEvents** (`derived_from="event"`); bij dezelfde `entity`+`transition`
  **wint het event** en verdwijnt het status-afgeleide item (dedup) → nooit twee
  waarheden voor hetzelfde feit. De frontend verandert niet mee.

*Zone 0–2 samen = het volledige 10-seconden-antwoord. Alles daaronder is
verdieping (progressive disclosure), niet nodig voor het snelle oordeel.*

**Zone 3 — Huidige toestand per domein (verdieping) — dynamisch open o.b.v. aandacht**
- Domeinkaarten (zelfde semantiek als "Bekende atleetcontext"): Belastbaarheid &
  trainingshistorie · Gezondheid & klachten · Herstel & leefritme · Doelen & agenda ·
  Profiel & voorkeuren · Coachkennis.
- **BESLIST (§12-C): welk(e) domein(en) standaard open staan wordt bepaald door de
  ATTENTION-oorzaak** — niet statisch. Mapping (oorzaak → domein):
  - actieve/terugkerende **klacht** → **Gezondheid & klachten**;
  - **belastingssignaal** (`load.signal=hoog` / `possible_relation` / zone-review) →
    **Belastbaarheid & trainingshistorie**;
  - **herstelsignaal** (`recovery.rpe_trend=zwaarder` / `feeling_trend=slechter`) →
    **Herstel & leefritme**;
  - **conflict** → het domein van de conflicterende evidence (bv. on_hold-vs-activiteit
    → Belastbaarheid).
  - **source-gap in een kernbron opent GÉÉN domein** (het is een betrouwbaarheids-
    signaal, geen domeinfeit) → het kleurt de statusstip (Z0) en verschijnt als
    onzekerheids-kaart in Z1.
- **Max. 2 domeinen standaard open** bij meerdere oorzaken, gerangschikt op
  importance/strength (dan recency). De rest ingeklapt.
- **Stabiele atleet (geen ATTENTION-oorzaak): geen enkel domein kunstmatig open** —
  alles ingeklapt, coach opent zelf wat hij wil.
- Per regel: waarde + **licht** provenance-label (zie §5/§12-E); "Waarom?" opent de
  volle keten. **unknown blijft unknown** ("onbekend"); bronfout ≠ leeg.

**Zone 4 — Longitudinale tijdlijn (progressive disclosure, initieel leeg)**
- Event-stream (`get_recent_events`) met `effective_at` + `transition` + titel.
- v1 lege staat = eerlijke aankondiging (zie §3). Additief, blokkeert niets.

**Zone 5 — Provenance & bron-detail (drill-down, op afroep)**
- Per claim: `explain(evidence_id)` → truth-type, bronketen, datums, strength.
- Source-health-paneel: per bron available/stale/last_success/coverage.

---

## 5. Prioritering — boven de vouw vs. verdieping

| Boven de vouw (altijd zichtbaar) | Progressive disclosure (op afroep/scroll) |
|---|---|
| Overall + source-health stip (Z0) | Domein-detailregels (Z3) — dynamisch open o.b.v. aandacht |
| Aandachtskaarten wat+waarom (Z1) | Volledige event-tijdlijn (Z4) |
| Recent veranderd, compact (Z2) | Volledige `explain()`-keten via "Waarom?" (Z5) |
| — | Historische/resolved klachten (default ingeklapt) |

**Provenance is standaard licht (BESLIST §12-E).** Bij elke claim staat inline een
kort label: **truth-type + bron + relevante datum/status/strength** (bv. "coach-
gemeld · 12 aug · terugkerend"). De **volledige `explain()`-keten** (bronketen,
provenance-ids, diepte) zit achter één **"Waarom?"**-affordance — één laag dieper,
op afroep. Zo leest het Dossier als coach-beslisscherm, niet als technisch
inspectiescherm.

Regel: **niets boven de vouw dat de coach niet binnen 10s nodig heeft**; alles
wat "volledig bewijs/geschiedenis" is, zit één tik dieper.

---

## 6. Interaction-design — desktop

- **Master–detail.** Links de gedeelde **Athlete Picker** (canonieke groepsvolgorde,
  zoek over alle groepen); rechts de cockpit voor de gekozen atleet.
- **Deep-link** `#dossier/<user_key>` via de bestaande `pushRoute/applyRoute`-
  primitive (zelfde als Schema `#schema/<user_key>`). Refresh/terug-vooruit behoudt
  atleet + scrollpositie.
- **Kruisnavigatie:** vanuit Zone 0/1 knoppen "Naar Schema" (`#schema/<user_key>`) en
  "Naar Feedback" — zonder herinvoer (coach-efficiëntie).
- **Verdieping in situ:** provenance/`explain` opent inline (popover/expander), geen
  paginawissel.
- Statuskop blijft sticky bij scrollen door de domeinkaarten.

## 6b. Interaction-design — mobiel

**BESLIST (§12-B): desktop-first uitgewerkt, maar mobiel is vanaf v1 volwaardig
bruikbaar** — goede structuur, sticky gedrag, leesbaarheid en ergonomie. Geen
tweede-rangs mobiele ervaring; wél geen 50/50 polish-verplichting (desktop is de
primaire werkplek van de coach).

- **Eén kolom.** Sticky **statuskop** (Z0) bovenaan; daaronder aandacht (Z1) en recent
  (Z2) als eerste, dan **accordeon**-domeinkaarten (Z3). De dynamische open-logica van
  §12-C geldt óók mobiel: alleen het/de door de ATTENTION-oorzaak bepaalde domein(en)
  staan open (max 2), rest ingeklapt; stabiele atleet = alles ingeklapt.
- Atleetkeuze via de Picker als **bottom-sheet** (bestaand patroon).
- Tijdlijn (Z4) en provenance/"Waarom?" (Z5) als uitklap onderaan.
- Touch-doelen ≥ rijhoogte-norm; **geen hover-afhankelijke info** (alle provenance ook
  op tap); leesbare regellengte, geen horizontaal scrollen van de body.
- Bottom-nav ongewijzigd; Dossier krijgt zijn eigen view.

---

## 7. Progressive-disclosure-model (vier niveaus)

1. **Oordeel** (Z0): één badge + betrouwbaarheid.
2. **Aandacht + recent** (Z1/Z2): wat + waarom, compact.
3. **Toestand per domein** (Z3): de volledige actuele kennis, verbatim.
4. **Bewijs & geschiedenis** (Z5/Z4): provenance-keten + event-tijdlijn.

Elk niveau is zelfstandig leesbaar; dieper = meer detail, nooit nieuw "verzonnen"
inzicht.

---

## 8. Deep-links & cross-module

- `#dossier/<user_key>` — directe cockpit-deeplink (roster, e-mail, andere modules).
- Dossier → `#schema/<user_key>` (planning) en → Feedback (sessie) zonder herinvoer.
- Roster/Atleten → Dossier via de gedeelde Picker (navigate-modus).
- Alles op de canonieke `user_key`; `nieuw:` alleen pre-link (geen dossier vóór koppeling).

---

## 9. States — loading / empty / error / source-health

Hergebruik de **eerlijke degradatie** uit de intake-flow-fix (bronfout ≠ "niets bekend").

- **Loading:** skeleton per zone; statuskop laadt eerst (10s-first). Geen spinner-only.
- **Empty — écht niets bekend:** per domein "onbekend"; overall = INSUFFICIENT_DATA
  met uitleg "te weinig data". Nooit een vals-positief "alles goed".
- **Empty — tijdlijn:** eerlijke aankondiging (§3) — "geen events" ≠ "geen historie";
  historie wordt opgebouwd vanaf activatie van capture, geen reconstructie.
- **Error / bronfout:** expliciete "context tijdelijk niet beschikbaar (bronfout) —
  dit betekent niet dat er niets bekend is", met retry. Nooit een blanco cockpit.
- **Source-health:** per bron badge (vers / stale / uitgevallen); STALE-claims gemarkeerd
  "laatst bekend, mogelijk verouderd"; kernbron-gap kleurt de betrouwbaarheids-stip
  en degradeert overall (nooit stil "stabiel").

---

## 10. Toets aan de 10-secondenregel (oog-volgorde)

1. **0–2s:** oog landt op statuskop → overall-badge + betrouwbaarheids-stip →
   "ATTENTION, bronnen vers" of "STABIEL" of "te weinig data".
2. **2–6s:** aandachtskaarten (Z1) → "knieklacht terugkerend (2× in 3 wk, coach-notitie
   4 aug)" + "trainingslog 6 dagen stil" → **wat + waarom** direct.
3. **6–8s:** recent veranderd (Z2) → "sinds vorige build: onderbreking gestart".
4. **8–10s:** blik-bevestiging in de relevante domeinkaart (Gezondheid) zonder klikken.

→ Binnen 10s: **hoe / wat veranderd / aandacht / waarom** beantwoord, zonder scroll-
diepte. Provenance en tijdlijn zijn er als de coach één tik dieper wil.

## 10b. Toets aan coach-efficiëntie

- ✅ Geen herinvoer: alle intake/planning-kennis komt uit Masterbrein (na `bbe537b`).
- ✅ Eén deep-link brengt de coach direct bij de juiste atleet-cockpit.
- ✅ Van cockpit in één tik naar Schema/Feedback met dezelfde `user_key`.
- ✅ Gedeelde Picker/routing/patronen → geen nieuw mentaal model.
- ✅ 10s-antwoord bovenaan; details kosten alleen tijd als de coach ze wil.

---

## 11. Wat bewust NIET in v1 komt

- **Geen coach-edit-acties** (confirm / correct / resolve / add-context / coach-memory
  schrijven). v1 = strikt read-only. Edit = aparte, gecontroleerde fase daarna.
- **Geen aanzetten van productie history-capture** in deze ronde (aparte gated GO).
- **Geen backfill** van historie (vanaf-nu blijft het principe).
- **Geen Teampuls-aggregatie / cross-atleet-overzichten** (aparte consumer later).
- **Geen klant-/voortgangsrapportgeneratie** vanuit de cockpit (later downstream).
- **Geen nieuwe intelligentie/derivaties, geen AI-samenvatting** in de cockpit —
  puur projectie van bestaande evidence.
- **Geen FinalSurge-writes, geen notificaties/alerts, geen realtime.**
- **Geen nieuwe athlete-identity/koppelflows** (die zijn gelockt).

---

## 12. Vastgestelde scope-keuzes (DEFINITIEF — Jip, 17 aug 2026)

- **A. Tijdlijn/capture:** **cockpit-first.** Productie history-capture blijft
  voorlopig **OFF**. De tijdlijn communiceert eerlijk dat historie vanaf activatie
  wordt opgebouwd; "geen events" ≠ "geen historie" (§3/§9).
- **B. Platform:** **desktop-first** uitwerken; mobiel vanaf v1 **volwaardig bruikbaar**
  (structuur, sticky, leesbaarheid, ergonomie) — geen tweede-rangs mobiel, geen
  50/50 polish-plicht (§6b).
- **C. Standaard open domein = dynamisch, o.b.v. de ATTENTION-oorzaak** (niet statisch):
  klacht→Gezondheid · belastingssignaal→Belastbaarheid · herstelsignaal→Herstel ·
  conflict→domein van de conflictbron · source-gap→géén domein (betrouwbaarheids-
  signaal). Max. 2 domeinen open; stabiele atleet = niets kunstmatig open (§4-Z3).
- **D. "Recent veranderd" = status-semantiek in v1, maar UITSLUITEND waar AthleteState
  echte recency draagt.** Geen pseudo-history/reconstructie/verzinsel. Ontworpen als
  één `changes[]`-slice die later drop-in overschakelt op echte HistoryEvents zonder
  parallelle waarheid (event wint bij dezelfde entity+transition) (§4-Z2).
- **E. Provenance standaard licht** (truth-type + bron + datum/status/strength inline);
  volledige `explain()`-keten alleen via een extra **"Waarom?"**-laag. Dossier =
  coach-beslisscherm, geen technisch inspectiescherm (§5).

---

## 13. Architectuur-fit (geen bouwopdracht, wel de contouren)

- **Backend:** één leesendpoint `GET /api/dossier/cockpit?key=<user_key>` →
  view-model uit `adapter.build_state` → `projections.for_dossier` (+ for_home-selectie
  voor aandacht, `sources`/`source_gaps` voor health, `history_store.get_recent_events`
  voor de tijdlijn indien aanwezig). Eén `build_state`, geen fan-out; hot-read = snapshot.
- **Frontend:** nieuwe `#dossier`-view; gedeelde Picker; `ui_sections`-achtige
  domeinrendering; source-health-badges; deep-links.
- **Geen nieuwe store, geen schrijfpad, geen wijziging aan Masterbrein-kernel of aan
  de gelockte Schema/Feedback/intake-flow.**
- Bestaande `pwa/dossier_core.py`/`dossier.py` (Streamlit) = concepten hergebruiken,
  niet de bron van waarheid; de cockpit leest Masterbrein, niet de losse intake-dump.

---

## 14. Definition of Done voor de Fase B-review (deze stap)

Dit doc is "klaar voor bouw-GO" als het antwoord geeft op: IA + prioritering (§4/§5),
desktop/mobiel interactie (§6), bronnen (§2), progressive disclosure (§7), deep-links
(§8), states incl. source-health (§9), expliciete non-goals (§11), de vastgestelde
keuzes A–E (§12), de drie bewezen 10s-scenario's (§15) en de hertoets aan de zes
principes (§16). **Bouwen pas na expliciete GO.**

---

## 15. Ontwerpcheck: 10-seconden-oogvolgorde op drie concrete scenario's

Per scenario moet boven de vouw binnen ~10s duidelijk zijn: **hoe staat hij ervoor ·
wat vraagt aandacht · wat is veranderd (indien betrouwbaar) · waarom · hoe zeker.**

### Scenario 1 — gezonde/stabiele atleet (bronnen vers)
- **0–2s (Z0):** overall **STABLE**, betrouwbaarheids-stip **groen** ("alle bronnen vers").
- **2–6s (Z1):** groene lege staat — *"Geen actiepunten — geen actieve klacht/signaal
  bekend (bronnen vers)."* **Geen domein kunstmatig open** (§12-C).
- **6–8s (Z2):** geen betrouwbaar vastgestelde recente verandering → **sectie afwezig**
  (geen ruis).
- **Uitkomst:** *hoe* = stabiel; *aandacht* = geen; *veranderd* = niets betrouwbaars;
  *waarom* = n.v.t.; *zeker* = hoog (vers). ✔ ≤10s.
- **Randvoorwaarde/veiligheid:** is er in werkelijkheid te weinig data, dan toont Z0
  **INSUFFICIENT_DATA** ("te weinig data voor een oordeel"), nooit een vals "stabiel".

### Scenario 2 — één duidelijke klacht (bronnen vers)
- **0–2s (Z0):** overall **ATTENTION**, stip **groen**.
- **2–6s (Z1):** één kaart — **"Klacht knie — terugkerend"** · *waarom:* "2 meldingen,
  laatst coach-notitie 12 aug". **Gezondheid** staat automatisch open (§12-C).
- **6–8s (Z2):** "Knie: recent/terugkerend" — alléén omdat `status=RECURRING` +
  `detail.dates` echte recency dragen (§12-D); geen verzinsel.
- **Waarom-laag:** inline licht label (COACH_REPORTED · 12 aug · terugkerend · MEDIUM);
  "Waarom?" → volledige `explain()`-keten.
- **Uitkomst:** *hoe* = aandacht; *aandacht* = knieklacht; *veranderd* = terugkerend;
  *waarom* = 2 gedateerde meldingen; *zeker* = hoog (vers). ✔ ≤10s.

### Scenario 3 — meerdere relevante signalen + source-gap
- **0–2s (Z0):** overall **ATTENTION** (of **INSUFFICIENT_DATA** als de uitgevallen bron
  de kernbron voor het oordeel is), stip **amber/rood** — "trainingslog uitgevallen".
- **2–6s (Z1):** max. relevante kaarten: **klacht** (→ Gezondheid open) + **belasting-
  signaal** (→ Belastbaarheid open) = **2 domeinen open** (§12-C, cap 2). Plus een
  **betrouwbaarheids-kaart** "trainingslog niet beschikbaar — belastbaarheid onzeker";
  die **opent géén domein** (§12-C).
- **6–8s (Z2):** alleen betrouwbare verschuivingen; een load-verandering die op de
  **uitgevallen** bron zou leunen wordt **niet** getoond (zelfde source-health-gate als
  `derive_events`) → geen onzekere claim als feit.
- **Waarom + zekerheid:** per kaart licht label; STALE/last-known-good gemarkeerd
  "laatst bekend, mogelijk verouderd"; de zekerheid is **zichtbaar gedegradeerd**
  door de gap — nooit stil "stabiel".
- **Uitkomst:** *hoe* = aandacht/onzeker; *aandacht* = klacht + belasting, één onzeker;
  *veranderd* = alleen wat betrouwbaar is; *waarom* = per kaart onderbouwd; *zeker* =
  expliciet verlaagd door bronuitval. ✔ ≤10s.

**Conclusie:** in alle drie de gevallen levert Zone 0–2 het volledige vijf-punts-
antwoord zonder scroll-diepte; verdieping (Z3-detail, Z4-tijdlijn, Z5-"Waarom?") is
er alleen als de coach die zoekt.

---

## 16. Hertoets aan de vaste BeBetter-endstate (na de keuzes A–E)

| Principe | Blijft het ontwerp kloppen? |
|---|---|
| **Eén centrale waarheid** | ✅ Cockpit leest uitsluitend `AthleteState`/projecties/history-store; Z2 `changes[]` is één slice die van status→echte events overschakelt met dedup (event wint) — nooit twee waarheden. |
| **Longitudinale samenhang** | ✅ Zelfde `athlete_key`; Z2 en Z4 delen de event-vorm; capture-aan verrijkt dezelfde plek zonder herontwerp. "Geen events" ≠ "geen historie" is expliciet. |
| **Herbruikbare projecties/UX** | ✅ `for_dossier`/`for_home`, gedeelde Picker, hash-routing, `ui_sections`-patroon, source-health-degradatie (hergebruik van de intake-flow-fix). |
| **Coach-efficiëntie** | ✅ Dynamisch open toont meteen het relevante domein (geen zoeken); 10s-antwoord bovenaan; deep-links naar Schema/Feedback; provenance licht, "Waarom?" alleen op afroep. |
| **Veiligheid / provenance / source-health** | ✅ truth-type/bron/datum inline; unknown blijft unknown; bronfout ≠ "niets bekend"; source-gap degradeert zekerheid en opent géén domein; geen pseudo-history. |
| **Schaalbaarheid** | ✅ Eén view-model-endpoint per atleet, één `build_state`, geen fan-out; history via geabstraheerde store-API (sharding-klaar). Werkt bij 100+ atleten. |

**Uitkomst:** de definitieve keuzes A–E versterken alle zes principes; geen enkel
principe verzwakt. Ontwerp is **klaar voor bouw-GO** binnen read-only v1.
