# BeBetter — Cross-Page Productflow, Consolidation & Polish Audit

**Type:** READ-ONLY product/architecture review — geen implementatie, geen merge, geen deploy.
**Baseline:** `main = 4959360` (clean tree), SW `bebetter-shell-v132`, assets `?v=136a`.
**Scope:** de volledige coach-PWA (`pwa/static/index.html`, `pwa/static/app.js`, `pwa/api.py`, de `*_core.py`-modules).
**Bewijsbasis:** code-inspectie van de daadwerkelijke route-/navigatiestructuur, view-switching, API-gebruik en zichtbare labels. Géén aannames uit geheugen. Waar ik iets niet kan bewijzen, staat dat er expliciet bij.

---

## Antwoord op de hoofdvraag

> **Kan BeBetter makkelijker worden om vanuit te coachen met minder pagina's, minder herhaling, minder klikken en duidelijkere acties — zonder waarheid, context of veiligheid op te geven?**

**Ja — en het bewijs is sterker dan een smaakoordeel.**

Drie structurele feiten uit de code dragen de hele conclusie:

1. **Workspace en Dossier lezen letterlijk dezelfde payload.**
   `app.js:6643` (`wsLoadDeep`) → `api("/api/cockpit?key=" + …)`
   `app.js:5470` (`laadDossierCockpit`) → `api("/api/cockpit?key=" + …)`
   Eén endpoint, twee volledige pagina's, twee renderingen van dezelfde `attention[]`, `planning[]`, `load_observation`. De coach doet een paginawissel om een tweede weergave te zien van data die al in het geheugen van de vorige pagina zat.

2. **Teampuls is Home's belasting-signaal zonder suppressie.**
   `home_core._belasting_vandaag()` → `belasting.zichtbare_resultaten(stand)`
   `teampuls_core._stand_payload()` → `belasting.zichtbare_resultaten(data)`
   Dezelfde functie, dezelfde dagstand. Home past daarna `_handled_active`-suppressie toe; Teampuls niet. Het `<details>Onderbouwing`-blok van een Teampuls-kaart (`app.js:5200-5202`) toont exact dezelfde velden als `prioSignaalBody` op Home (`app.js:1194-1207`): `km_recent`, `km_basis`, `gevoel`, `RPE`, `runs`. Het enige unieke veld is `duiding` (de AI-zin) — Home gebruikt die bewust niet (`home_core.py:172`).

3. **Schema-verloop is Home's schema-signaal met een breder venster.**
   Home: `FS.get_schema_end_dates(60, on_hold)` → signaal bij `days_left < 0` (verlopen) of `<= 7` (loopt af).
   Schema-verloop: `/api/schema-verloop` → dezelfde einddatums, alle statussen, geen suppressie.
   En Races heeft dezelfde vorm: de Home-chip is `races_core.chip_count()` (7d, zonder wens) en de Races-pagina heeft dat filter al als chip (`#races/7d`).

Daaruit volgt de structurele diagnose:

> **Home is de gefilterde actielijst. Teampuls, Schema-verloop en Races zijn de óngefilterde monitoringweergaven van precies Home's eigen drie signaaltypen plus zijn chip. Dat zijn geen aparte beslissingen — dat is dezelfde beslissing op een andere filterstand, verspreid over vier sidebar-items.**

En op atleetniveau:

> **Eén atleet woont op vier routes (`#atleten/<k>`, `#workspace/<k>`, `#dossier/<k>`, `#schema/<k>`), waarvan er drie uit twee endpoints lezen. Dat is één onderwerp met vier adressen.**

BeBetter voelt daardoor vandaag als **een verzameling correcte dashboards**, niet als één coachingsysteem. De correctheid is uitstekend; de *informatie-architectuur* loopt achter op de correctheid.

---

# Fase 1 — Route- en pagina-inventaris

14 coach-facing views, gedefinieerd als `<section class="view" data-view="…">` in `index.html` en geregistreerd via `laders.<view>` in `app.js:6812-6823`.
Zijbalk (≥900px): 14 items in 4 groepen. Onderbalk (<900px): 5 items (`home`, `feedback`, `atleten`, `teampuls`, `meer`).
Routegrammatica: `#<view>` of `#<view>/<ident>` — strikt twee segmenten (`applyRoute`, `app.js:192-209`).

| # | Route | Ingang | Titel | Data | Hoofdblokken | CTA's | Uit | In | W/R | Scope | Frequentie | Dubbelt | Actie? | Dichtheid |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `#home` | zijbalk, onderbalk, logo | (geen H1; hero) | `/api/home/stats`, `/api/home/prio/{k}/trainingen`, `/api/intake/inbox`, `/api/kaarten` | hero, feedbackstrip, Prioriteit vandaag, Ook nog | Gezien/Later (per signaal + bulk), Open workspace, Dossier, Schema, Teampuls | feedback, workspace, atleten, schema, teampuls, intake, strippen | app-start, elke nav | **W** (handled) | team | dagelijks | Teampuls (belasting), Schema-verloop (schema) | **ja** | dicht, goed |
| 2 | `#feedback` | zijbalk, onderbalk, Home-strip, Workspace | Feedback | `/api/feedback/queue`, `/{workout_key}`, `/generate`, `/post`, `/skip`, `/thread`, `/summary`, `/week`, `/api/cockpit` | queue+tabs+groepen, case-hero, contextkolom, sessiesamenvatting, debug | Genereer, Versturen, Overslaan, Samenvatting, Open dossier | dossier | Home, Workspace, zijbalk | **W** (post naar FS) | team→sessie | **dagelijks, meest gebruikt** | ctx-kolom ⊂ cockpit | **ja** | dicht |
| 3 | `#atleten[/<k>]` | zijbalk, onderbalk, athleteNav "Profiel", Home "Dossier"-knop | Atleten | `/api/atleten`, `/api/atleten/{id}`, `/api/dossier/{k}/note`, `/profiel`, `/api/intake/koppel` | roster+zoek, Training (FS), Intake & doel, koppel-intake, notities, documenten, coach-geheugen | notitie +/−, geheugen opslaan, koppelen | workspace, dossier, schema | Home, intake, zijbalk | **W** (notities/profiel/koppel) | atleet | wekelijks | Workspace/Dossier (training, doel) | deels | dicht |
| 4 | `#workspace[/<k>]` | zijbalk, "Meer", Home-detail, Dossier-actiebalk | Workspace | `/api/workspace/{k}` (shell) + `/api/cockpit` (deep) + `/api/home/prio/{k}/trainingen` | Aandacht nu, Belasting 7d, Doel & planning, Trainingen, Volgende actie, Feedback, Bronnen | schema verlengen/nieuw, naar feedback, bekijk in dossier | schema, feedback, dossier | Home, Dossier, zijbalk | R | atleet | dagelijks | **Dossier (zelfde endpoint)** | **ja** | dicht |
| 5 | `#dossier[/<k>]` | zijbalk, "Meer", Teampuls, Workspace, athleteNav | Dossier · Levend geheugen | `/api/cockpit`, `/api/cockpit/explain` | 3-zone tableau (tijdlijn/hero/draden) óf stack, domeinstrip, actiebalk | Waarom?, Naar schema, Workspace, athleteNav | schema, workspace, atleten | Teampuls, Workspace, Feedback, zijbalk | R | atleet | af en toe | **Workspace (zelfde endpoint)** | deels | zeer dicht |
| 6 | `#teampuls` | zijbalk, onderbalk, Home-signaalactie | Teampuls | `/api/teampuls/signalen`, `/gezien`, `/briefing` | belastingkaarten + onderbouwing, weekbriefing | Gezien (7d), Dossier →, Vernieuw briefing | dossier | Home, zijbalk | **W** (dempen) | team | dagelijks | **Home belasting-signaal** | zwak | dicht |
| 7 | `#schema[/<k>]` | zijbalk, "Meer", athleteNav, Workspace, Schema-verloop, Home, na koppelen | Schema bouwen | `/api/schema/*` (10 endpoints) | roster, modusbalk Nieuw\|Verlengen, config, plan-spar, workbench, publish-preview | Bouw, Chat, CSV, Preview, **Publiceer naar FS** | atleten, dossier, workspace | veel | **W** (FS-write) | atleet | wekelijks | — | **ja** | zeer dicht |
| 8 | `#races[/<scope>]` | zijbalk, "Meer", Home-chip | Races | `/api/races`, `/api/races/wens` | filterchips (alle / 7d zonder wens), racekaarten met wens-composer | **Plaats wens** (FS-write) | — | Home-chip, zijbalk | **W** | team | wekelijks | Home-chip; doel/race in WS+Dossier+FB | ja | middel |
| 9 | `#schema-verloop` | zijbalk, "Meer" | Schema-verloop | `/api/schema-verloop` | lijst met dagen-tot-einde + status | Schema openen | schema | zijbalk | R | team | wekelijks | **Home schema-signaal** | ja | sparse |
| 10 | `#intake` | zijbalk, "Meer", Home "Ook nog" | Intake | `/api/intake/link`, `/inbox`, `/orphans`, `/inbox/{id}/take` | deelbare link, binnengekomen, wachtende (orphan) intakes | Kopieer, Nieuwe link, Overnemen, Verwijderen, Koppelen | atleten, schema | Home, zijbalk | **W** | team | af en toe | Home-badge (bewust) | ja | middel |
| 11 | `#strippen` | zijbalk, "Meer", Home "Ook nog" | Strippenkaart | `/api/kaarten*`, `/api/import*` | nieuw, bulk-import, kaartenlijst | Toevoegen, Afboeken (swipe), Terug, WhatsApp | — | Home, zijbalk | **W** | praktijk | af en toe | — | ja | middel |
| 12 | `#documenten` | zijbalk, "Meer" | Documenten | `/api/docs/templates`, `/generate` | sjabloonkeuze, formulier | Genereer PDF | — | zijbalk | **W** (bestand) | atleet | zelden | — | ja | sparse |
| 13 | `#admin` | zijbalk, "Meer" | Administratie | `/api/admin/status`, `/overzicht` | pincode-gate, financieel overzicht | Openen | — | zijbalk | R (gated) | zaken | zelden | — | ja | middel |
| 14 | `#meer` | zijbalk, onderbalk | Meer | `/api/me`, `/api/kaarten` | 9 navigatiekaarten + account | alle module-links, Face ID, installeren, uitloggen | alle | onderbalk, hero-tandwiel | R | app | mobiel dagelijks | **volledige zijbalk-duplicaat op desktop** | n.v.t. | lang |

Niet in de coach-nav: `/intake?token=…` (publiek atleet-formulier, `api.py:950`) en het login-scrim (`index.html:51`). Beide terecht buiten de nav.
Modals die als pagina gedragen: `openAthletePickerOverlay` (`app.js:2025`) — gedeeld door Workspace-switch, Dossier-switch en de intake-koppelflow. Correct als modal.
Geen dode/legacy routes gevonden: elke `data-view` heeft een `lader` (behalve `home`/`meer`, die synchroon renderen) en `applyRoute` valideert tegen bestaande secties.

## "Een coach opent deze pagina wanneer…"

| Pagina | Zin | Oordeel |
|---|---|---|
| Home | "…ik wil weten wie vandaag mijn aandacht vraagt en dat wil afvinken." | **scherp** |
| Feedback | "…ik trainingen wil beoordelen en atleten wil antwoorden." | **scherp** |
| Schema | "…ik een plan wil bouwen, verlengen of publiceren." | **scherp** |
| Intake | "…er een nieuwe aanmelding is." | **scherp** |
| Strippenkaart | "…ik een rit wil afboeken." | **scherp** |
| Documenten | "…ik een PDF voor een atleet wil maken." | **scherp** |
| Administratie | "…ik de financiën wil zien." | **scherp** |
| Races | "…ik een race-wens wil plaatsen." | scherp, maar zeldzaam |
| Workspace | "…ik wil zien wat er nú met deze atleet speelt." | scherp — **maar overlapt Dossier's zin** |
| Dossier | "…ik wil zien wat er met deze atleet veranderde en waarom." | scherp — **maar leest dezelfde payload** |
| Atleten (Profiel) | "…ik een notitie wil maken, de intake wil lezen, of het coach-geheugen wil bijwerken… en ook trainingen zie… en ook de roster is." | **ROLE UNCLEAR** — drie "en"-clausules; is tegelijk roster, profiel, notitieblok, koppelscherm en trainingsoverzicht |
| Teampuls | "…ik teambrede belasting wil monitoren, óók wat ik al afvinkte… en de weekbriefing wil lezen." | **ROLE UNCLEAR** — twee ongerelateerde jobs op één pagina, waarvan één een filterstand van Home is |
| Schema-verloop | "…ik wil zien wiens schema afloopt." | **ROLE UNCLEAR als pagina** — dit is één Home-signaaltype met een breder venster |
| Meer | "…ik op mobiel naar een module wil die niet in de onderbalk past." | scherp op mobiel, **overbodig op desktop** |

---

# Fase 2 — Kernjourneys

## Journey A — Start van de coachdag

```
App-start → Home (0 klikken)
  hero · feedbackstrip · "Prioriteit vandaag" (gegroepeerd per atleet) · "Ook nog"
  ├─ rij uitklappen                        [1 klik, GEEN paginawissel]  → volledige briefing
  ├─ per signaal Gezien / Later 3d/7d/14d   [1 klik]
  └─ swipe = bulk over alle signalen        [0 klikken, gebaar]
Teampuls (zijbalk)                          [1 klik, PAGINAWISSEL]
  └─ per kaart <details> Onderbouwing       [1 klik]  → km/basis/gevoel/RPE/runs
  └─ scroll voorbij N belastingkaarten      → Weekbriefing (onderaan)
Schema-verloop (zijbalk)                    [1 klik, PAGINAWISSEL]
Races (zijbalk of Home-chip)                [1 klik, PAGINAWISSEL]
```

**Is Home genoeg?** Voor *actie* ja. Home draagt alle drie signaaltypen (compliance, schema, belasting), de suppressie, de undo, de per-signaal-afhandeling en de deep-links. De uitgeklapte rij is al een volwaardige athlete briefing (`prioDetailHtml`, `app.js:1130-1188`).

**Waarom bestaat Teampuls dan apart?** De code geeft één eerlijk antwoord, in een comment op `app.js:5177-5184`: Teampuls is *observatie* (toont ook wat je al zag), Home is *actie* (verbergt wat je afvinkte). Dat is een echt onderscheid — maar het is een **filterstand**, geen tweede beslissingslaag. En de kosten zijn hoog: dezelfde atleet, dezelfde bron, dezelfde cijfers, dezelfde onderbouwingsvelden, twee keer scannen.

**Voegt Teampuls een eigen beslissing toe?** Twee dingen, allebei echt:
- `duiding` — de AI-zin per atleet, die Home bewust niet toont (`home_core.py:172`).
- De **weekbriefing** — uniek, waardevol, en begraven onder de dubbele lijst.

**Redundante stappen:** de hele Teampuls-signalenlijst voor atleten die al op Home staan; het `Onderbouwing`-detail dat `prioSignaalBody` dupliceert.
**Dead ends:** een Teampuls-kaart heeft precies twee acties (`Gezien (7 dagen)`, `Dossier →`). Geen route naar Workspace, Schema of Feedback. Dat is de smalste actieset van elke atleet-dragende kaart in de app.
**Idealer:** Home houdt de actielijst. De monitoringlijst en de briefing worden **secties/tabs op Home**. Briefing: 1 klik + scroll → 0 klikken.

## Journey B — Eén atleet onderzoeken

```
Home (0)
 └─ rij uitklappen            [1]  reden + onderbouwing + acties
     └─ "Open workspace"      [2]  PAGINAWISSEL → #workspace/<k>
         │   Aandacht nu · Belasting 7d · Doel & planning · Trainingen ·
         │   Volgende actie · Feedback · Bronnen
         ├─ "Bekijk in dossier"  [3]  PAGINAWISSEL → #dossier/<k>   (zelfde /api/cockpit!)
         │    └─ athleteNav "Profiel"  [4]  PAGINAWISSEL → #atleten/<k>
         │         └─ athleteNav "Schema" [5] PAGINAWISSEL → #schema/<k>
         └─ "Schema verlengen"   [3]  PAGINAWISSEL → #schema/<k>
```

**4 paginawissels om één atleet volledig te begrijpen.**

Herhaalde informatie, geteld over de journey:

| Feit | Aantal oppervlakken | Waar |
|---|---|---|
| belasting % / km | **5** | Home-rij, Home-detail, Workspace load-kaart, Dossier `loRow`, Teampuls-kaart |
| recente trainingen | **5** | Home `prioSessiesHtml`, Workspace `wsTrainingen`, Profiel `recentHtml`, Teampuls `puls-runs`, Dossier |
| doel / wedstrijd | **4** | Workspace "Doel & planning", Dossier `planRows` + future-node, Feedback "Doel & richting", Races |
| actieve klacht | **3** | Workspace `wsContextSignalen`, Dossier past-node, Feedback "Let op" |
| schema-einddatum | **4** | Home schema-signaal, Workspace `wsSchemaFeit`, Schema-verloop, Schema Verlengen |

**Contextverlies:** Workspace heeft als **enige** atleetpagina géén `athleteNav` (`app.js:2200, 3918, 4086, 4396, 4520, 4711, 4798, 5986` — Workspace ontbreekt in die lijst). Vanuit Workspace kun je dus **niet in één klik naar Profiel**. Er is wél een `ws`-tak in `athleteNav` (`app.js:308-309`) die precies daarvoor is geschreven en nooit wordt aangeroepen. Dat is een gat, geen ontwerpkeuze.

**Antwoord op de gestelde vraag:** de huidige scheiding is **niet** gerechtvaardigd voor Workspace ↔ Dossier — één endpoint, twee pagina's. Wel gerechtvaardigd voor Schema (echte workbench met drafts en een FS-write) en deels voor Profiel (eigen endpoint, eigen writes).

## Journey C — Feedback beoordelen

```
Feedback (0)  →  3-koloms workbench
  links   wachtrij + weektabs + groepen
  midden  case-hero: gepland vs uitgevoerd, zones, thread, composer
  rechts  "Context": Doel & richting + één actieve klacht + "Open dossier"
     ├─ case selecteren        [1]  geen paginawissel
     ├─ Genereer               [1]
     ├─ Versturen              [1]  FS-write
     └─ "Open dossier…"        [1]  PAGINAWISSEL → verlaat de wachtrij
```

**Is Feedback al een mini-Workspace?** Ja, en dat is een *bewuste, gedocumenteerde* keuze (`app.js:3505-3509`): de rechterkolom is expliciet gereduceerd tot alleen beslissings-relevante context, om geen mini-dossier te worden. Die redenering is goed en moet blijven staan.

**Wordt de coach te vaak gedwongen te vertrekken?** Eén gat: er is **geen route van Feedback naar Workspace of Schema**. Als het antwoord "ik pas je plan aan" is, moet de coach via de zijbalk (die de atleet wél meeneemt via `_shownAthleteKey`, `app.js:267-275`) of via Dossier. De terugkeer is gelukkig gratis: `laders.feedback` draait maar één keer (`app.js:176`), dus de geselecteerde case blijft staan.

**Wat embedden vs. deep-linken:** de huidige verdeling klopt. Toevoegen: één "Naar workspace"-route naast "Open dossier". Niets verplaatsen.

## Journey D — Plan aanpassen

```
Signaal (Home schema-signaal / Workspace / Schema-verloop)
 └─ "Schema" / "Schema verlengen"  [1-2]  → #schema/<k>
     modusbalk  [Nieuw | Verlengen]        ← al één pagina met twee modi
       Verlengen → herijking: vorig blok + delta + readiness
       Nieuw     → config → plan-spar → workbench → publish-preview → FS-write
```

**Zijn Nieuw en Verlengen correct gescheiden?** Ja — en ze zijn **al één pagina** met een modusbalk (`sbModeBar`, `app.js:3876-3889`), per-key-per-modus geïsoleerde drafts, en een gedeeld deep-link-patroon (`openSchemaMode` → `schemaOpenMode`, `app.js:3900-3908`, bewust géén derde routesegment). Dit is het best geconsolideerde deel van de app en moet als voorbeeld gelden voor de rest.

**Zijn de huidige-blok-feiten vroeg genoeg zichtbaar?** Ja, sinds Workspace `wsSchemaFeit` toont en "Huidig schema & verlengen" naar de herijking gaat in plaats van naar een leeg Nieuw-plan.
**Is doel/race gedupliceerd?** Ja — 4 oppervlakken (zie tabel Journey B), zonder beslissingsverschil tussen Workspace en Dossier.

## Journey E — Historie begrijpen

```
Workspace (nu)  →  Dossier (verleden→nu→toekomst)  →  Profiel (notities/documenten/geheugen)
                                                   →  Feedback (gespreksgeschiedenis, per sessie)
```
**Bezit Dossier deze job?** Grotendeels — maar historie is **verspreid over vier plekken**: Dossier (`changes`/`timeline`), Profiel (coach-notities, documenten, eerdere intakes, coach-geheugen), Feedback (`thread`), Schema (`schema_verloop_core`). Dossier is het duidelijke *kandidaat*-huis maar bezit de notities en het geheugen niet — die staan op Profiel, dat niet eens zo heet in de zijbalk ("Atleten").

## Journey F — Races/doelen

```
Home-chip "N races" → #races/7d (gefilterd)
Zijbalk "Races"     → #races (alle)
Workspace "Doel & planning" → toont hoofddoel + wedstrijddatum, geen route naar Races
Dossier future-node → toont race, geen route naar Races
```
**Is Races een eigen pagina waard?** De *lijst* niet (het is een Home-chip met een filter). De **race-wens-composer** wel — dat is echt coachwerk met een FS-write. Er zijn **vier concurrerende doelrepresentaties** (Workspace-lens, Dossier-node, Feedback-kaart, Races-lijst) zonder onderling verschil in beslissing.

## Journey G — Intake

```
Home "Ook nog: N nieuwe intakes" → #intake
  deelbare link · binnengekomen · wachtende (orphan) intakes
  "Overnemen als intake" → staat bij Atleten
  Atleten/<nieuw:…> → "Koppel aan FinalSurge" → na koppelen: direct #schema/<user_key>
```
Dit is de **best ontworpen flow in de app**: de `nieuw:`-identity-guard (`app.js:234-241`) voorkomt dat een pre-link intake als app-brede atleetcontext lekt, en na koppelen springt de coach direct naar de primaire volgende actie (schema bouwen, `app.js:2246-2252`). Verwarrende dubbele staten: geen gevonden. Dit is setup-werk en hoort uit de dagelijkse navigatie.

---

# Fase 3 — Overlapmatrix

`0` = geen · `1` = kleine samenvattingsoverlap · `2` = betekenisvolle gedeelde inhoud · `3` = zware duplicatie / gelijk doel

| | Home | Teampuls | Workspace | Dossier | Profiel | Feedback | Schema | Schema-verl. | Races | Intake | Meer |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Home** | — | **3** | **2** | 1 | 1 | **2** | 1 | **3** | **2** | 1 | 1 |
| **Teampuls** | **3** | — | **2** | **2** | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Workspace** | **2** | **2** | — | **3** | **2** | **2** | **2** | 1 | 1 | 0 | 0 |
| **Dossier** | 1 | **2** | **3** | — | **2** | **2** | 1 | 0 | 1 | 0 | 0 |
| **Profiel** | 1 | 0 | **2** | **2** | — | 1 | 1 | 0 | 0 | **2** | 0 |
| **Feedback** | **2** | 0 | **2** | **2** | 1 | — | 0 | 0 | 0 | 0 | 0 |
| **Schema** | 1 | 0 | **2** | 1 | 1 | 0 | — | **2** | 1 | 1 | 0 |
| **Schema-verl.** | **3** | 0 | 1 | 0 | 0 | 0 | **2** | — | 0 | 0 | 0 |
| **Races** | **2** | 0 | 1 | 1 | 0 | 0 | 1 | 0 | — | 0 | 0 |
| **Intake** | 1 | 0 | 0 | 0 | **2** | 0 | 1 | 0 | 0 | — | 0 |
| **Meer** | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — |

## Toelichting per score 2 of 3

**Home ↔ Teampuls = 3.** Zelfde bron (`belasting.zichtbare_resultaten`), zelfde `load_metric`-projectie, zelfde onderbouwingsvelden. Verschil: suppressie (Home) vs. volledig beeld (Teampuls) + `duiding` + briefing. *Overlap zonder beslissingsdoel: de kaartinhoud. Overlap mét doel: de filterstand.*

**Home ↔ Schema-verloop = 3.** Zelfde `FS.get_schema_end_dates`. Home toont `<0` en `≤7`; Schema-verloop toont alles binnen 60 dagen met statuslabels. Exact hetzelfde patroon als Home↔Teampuls. *Overlap zonder doel: de kaart. Met doel: het venster.*

**Workspace ↔ Dossier = 3.** **Zelfde endpoint** (`/api/cockpit?key=`). Dubbel getoond: `attention[]` (klacht/herstel/bron-gap), `load_observation` (+%), `planning.rows` (doel/wedstrijd). Verschil in presentatie: Workspace = "wat nu + welke actie", Dossier = "wat veranderde + waarom + provenance". Dat verschil is echt, maar **rechtvaardigt geen aparte pagina met een eigen fetch** — het rechtvaardigt twee secties op één oppervlak.

**Home ↔ Workspace = 2.** Home's uitgeklapte briefing (`prioDetailHtml`) toont naam, dominant signaal, onderbouwing per signaal, en dezelfde CTA's ("Open workspace", "Dossier"). Gerechtvaardigd: het bespaart een paginawissel voor het meest voorkomende geval (afvinken zonder verdieping).

**Home ↔ Feedback = 2.** De feedbackstrip toont de open-set uit de canonieke `_apply_feedback_overlay`. Gerechtvaardigd: één cijfer, één klik, verandert de beslissing (ga ik nu de wachtrij in?).

**Home ↔ Races = 2.** De chip is `races_core.chip_count()`, exact het venster van het `7d`-filter op de Races-pagina. Gerechtvaardigd als teller; de lijst zelf is een monitoringweergave.

**Teampuls ↔ Workspace/Dossier = 2.** `load_metric` voedt alle drie; Dossier toont bovendien of er wel/geen open Home-actie is (`loRow`, `app.js:5636-5644`). Dat laatste is unieke, waardevolle informatie.

**Workspace ↔ Feedback = 2.** Feedback's contextkolom leest `/api/cockpit` en toont doel + één klacht. Bewust gereduceerd (`app.js:3505-3509`). Gerechtvaardigd.

**Dossier ↔ Feedback = 2.** Zelfde `attention[]`-klacht; Feedback toont er één, Dossier alle. Gerechtvaardigd.

**Workspace/Dossier ↔ Profiel = 2.** Profiel toont "Training (uit FinalSurge)" (recente trainingen, weekvolume) — Workspace toont hetzelfde rijker (`wsTrainingen`, met gepland/gemist/rust). Profiel toont "Intake & doel" — Workspace/Dossier tonen hetzelfde doel uit `planning.rows`. *Duplicatie zonder beslissingsdoel.*

**Workspace ↔ Schema = 2.** Workspace toont het schemasignaal en linkt naar beide modi. Gerechtvaardigd — dit is een goede brug.

**Schema ↔ Schema-verloop = 2.** Beide lezen einddatums; Schema-verloop is puur de lijst-ingang naar Schema.

**Profiel ↔ Intake = 2.** De koppelflow leeft op Profiel (`koppelHtml`), de bron op Intake. Gerechtvaardigd — dat is één flow over twee stappen.

---

# Fase 4 — Pagina-bestaanstest

| Pagina | 1. Unieke beslissing? | 2. Info niet beter elders? | 3. Vaak genoeg? | 4. Verwijderen = meer klikken? | 5. Kan sectie/tab zijn? | 6. Duidelijke in/uit? | 7. Nieuwe coach snapt het? | **Classificatie** |
|---|---|---|---|---|---|---|---|---|
| Home | ja | ja | dagelijks | ja | nee | ja | ja | **KEEP AS PAGE** |
| Feedback | ja | ja | dagelijks, hoogst | ja | nee | ja | ja | **KEEP AS PAGE** |
| Workspace | ja | grotendeels | dagelijks | ja | nee | ja | ja | **KEEP AS PAGE** (wordt de atleet-hub) |
| Schema | ja (write) | ja | wekelijks | ja | nee | ja | ja | **KEEP AS PAGE** |
| Dossier | ja (provenance/historie) | ja (uniek: `explain`, changes, domeinen) | af en toe | nee | **ja** | ja | ja | **CONVERT TO SECTION/TAB** (op Atleet, dezelfde payload) |
| Profiel (`#atleten`) | deels (notities/geheugen/koppel) | nee (training/doel dubbelen) | wekelijks | nee | **ja** | ja | **nee** (heet "Atleten", is roster+profiel) | **CONVERT TO SECTION/TAB** + KEEP BUT REDUCE |
| Teampuls | nee (filterstand van Home) — behalve briefing + `duiding` | nee | dagelijks | nee | **ja** | zwak (dead-end kaarten) | nee ("waarom staat hij hier maar niet op Home?") | **MERGE INTO Home** (als tab "Monitoring" + briefing als eigen blok) |
| Schema-verloop | nee (venster van Home's schema-signaal) | nee | wekelijks | nee | **ja** | ja | nee | **MERGE INTO Home** (als tab/filter) |
| Races | ja (wens-write) — lijst niet | lijst nee, composer ja | wekelijks | nee | **ja** | ja | ja | **CONVERT TO SECTION/TAB** op Home |
| Intake | ja | ja | af en toe | ja | nee | ja | ja | **SETUP-ONLY / HIDE FROM DAILY NAV** |
| Strippenkaart | ja | ja | af en toe | ja | nee | ja | ja | **SETUP-ONLY / HIDE FROM DAILY NAV** |
| Documenten | ja | ja | zelden | ja | nee | ja | ja | **SETUP-ONLY / HIDE FROM DAILY NAV** |
| Administratie | ja | ja | zelden | ja | nee | ja | ja | **SETUP-ONLY / HIDE FROM DAILY NAV** |
| Meer | nee op desktop, ja op mobiel | n.v.t. | mobiel dagelijks | mobiel ja | n.v.t. | ja | ja | **KEEP BUT REDUCE** (mobiel houden; op desktop niet nodig naast de volledige zijbalk) |

---

# Fase 5 — Consolidatiescenario's

## Scenario 1 — Conservatief

**Primaire navigatie (ongewijzigd, 14 items).**
Wat verandert: alleen labels, links en dedupe.
- Home's swipe-/detailknop "Dossier" krijgt het correcte label **"Profiel"** (route blijft `#atleten/<k>` — zie Fase 10, defect C1).
- Workspace krijgt de bestaande `athleteNav` (de code staat er al, wordt alleen nooit aangeroepen).
- Feedback krijgt een "Naar workspace"-route naast "Open dossier".
- Teampuls-kaarten krijgen de bredere actieset (Workspace/Schema) die de andere atleet-kaarten al hebben.
- Weekbriefing bovenaan Teampuls in plaats van onder de lijst.
- Zijbalk-iconen: `#ic-brain` wordt nu door **drie** items gedeeld (Workspace, Dossier, Schema bouwen — `index.html:87, 88, 91`); geef elk een eigen icoon.
- Enkelvoud/meervoud + datumformaat gelijk trekken (Fase 8).

**Klikreductie:** ~10-15% op journey B/C. **Risico:** zeer laag, puur presentatie. **Migratiecomplexiteit:** klein. **Waarheidsrisico:** nul. **Leerwinst:** matig — de coach onthoudt nog steeds 14 plekken.

## Scenario 2 — **AANBEVOLEN**

**Primaire dagelijkse navigatie: 3 + 1 lade.**

| Item | Absorbeert |
|---|---|
| **Vandaag** | Home + Teampuls + Schema-verloop + Races + weekbriefing |
| **Feedback** | ongewijzigd |
| **Atleet** | Workspace (default) + Dossier + Profiel + Schema, als tabs op één oppervlak |
| *Praktijk* (lade, niet dagelijks) | Intake, Strippenkaart, Documenten, Administratie, account |

**Wat waarheen:**
- *Vandaag* houdt "Prioriteit vandaag" exact zoals het is (gelockt). Erbij: een segmentregel **Actie · Monitoring · Races**. "Monitoring" toont de óngefilterde stand — precies wat Teampuls en Schema-verloop nu tonen — uit dezelfde endpoints, met `duiding`. De weekbriefing krijgt een eigen blok bovenaan of direct onder de prioriteitenlijst.
- *Atleet* opent op de Workspace-inhoud. De tabbar (Nu · Historie · Profiel · Plan) is de bestaande `athleteNav`, opgewaardeerd tot een permanente, identieke balk op alle vier de routes. **De routes blijven `#workspace/<k>`, `#dossier/<k>`, `#atleten/<k>`, `#schema/<k>`** — geen route-identiteitswijziging, geen derde segment, geen nieuwe store. Alleen: het voelt als één pagina met tabs omdat de balk niet meer verspringt.
- *Historie* (Dossier) hoeft niet opnieuw te fetchen: Workspace heeft de `/api/cockpit`-payload al in het geheugen.

**Verwachte klikreductie:** 30-45% op de dagelijkse journeys (Fase 7). **Risico:** laag-middel; het raakt navigatie en labels, niet de truth-laag. **Migratiecomplexiteit:** middel — vooral `index.html`-nav, `athleteNav`, plus een tabcontainer op Home. **Waarheidsrisico:** nul mits alle vier de bestaande endpoints ongemoeid blijven en de Home-berekening niet wordt aangeraakt. **Leerwinst:** groot — 4 plekken onthouden i.p.v. 14, en één begrijpelijk mentaal model: *team → atleet → sessie*.

## Scenario 3 — Agressieve vereenvoudiging

**2 primaire items:** *Vandaag* (met Feedback als derde tab) en *Atleet*.

- Feedback wordt een tab van Vandaag; de 3-koloms workbench wordt de tab-inhoud.
- Schema wordt een modal/overlay boven Atleet.

**Klikreductie:** ~50% nominaal. **Risico: hoog, en ik raad het af.** Feedback is de meest gebruikte operationele pagina, heeft een eigen 3-koloms layout met sticky queue, keyboardnavigatie, mobiele focus-overlay, draft-persistentie en een `fbLeave`/`fbEnter`-levenscyclus die aan `toonView` hangt. Die als tab inbedden is de duurste en risicovolste verandering in het hele plan, met de kleinste winst: Feedback is nu al **één klik** vanaf overal. **Migratiecomplexiteit:** hoog. **Waarheidsrisico:** middel (de feedback-lifecycle-hooks in `toonView`, `app.js:158-164`, zouden herzien moeten worden — dat raakt bewezen correctness). **Verworpen.**

---

# Fase 6 — Voorgestelde dagelijkse navigatie

| Top-level | Doel | Frequentie | Eerste scherm | Verwachte volgende actie | Absorbeert |
|---|---|---|---|---|---|
| **Vandaag** | "Wie vraagt vandaag mijn aandacht, en wat is de teamstand?" | elke sessie, meermaals | hero + feedbackstrip + Prioriteit vandaag; segmentregel Actie \| Monitoring \| Races; weekbriefing | uitklappen → afvinken, of doorschakelen naar een atleet | Home, Teampuls, Schema-verloop, Races, briefing |
| **Feedback** | "Trainingen beoordelen en atleten antwoorden." | dagelijks, langste sessie | wachtrij + geselecteerde case + context | genereer → versturen → volgende | ongewijzigd |
| **Atleet** | "Alles van één atleet: nu, historie, profiel, plan." | dagelijks | Workspace-inhoud + tabbar **Nu · Historie · Profiel · Plan** | actie op het primaire signaal, of tabwissel | Workspace, Dossier, Atleten, Schema |
| *Praktijk* (lade/`Meer`) | "Administratief werk dat niet in de coachflow hoort." | af en toe | lijst met 4 kaarten + account | die module openen | Intake, Strippenkaart, Documenten, Administratie |

Mobiele onderbalk wordt daarmee: **Vandaag · Feedback · Atleet · Meer** (4 i.p.v. 5, en elk item betekent iets anders).

---

# Fase 7 — Klikreductie-analyse

Gemeten op de huidige productiestructuur. "Wissels" = paginawissels (view-transities).

| # | Coachactie | Nu (klikken / wissels) | Voorgesteld | Reductie | Weggenomen contextwissels |
|---|---|---|---|---|---|
| 1 | Hoogste-prioriteit atleet vinden | 0 / 0 | 0 / 0 | 0% | — |
| 2 | Zien waaróm hij gevlagd is | 1 / 0 | 1 / 0 | 0% | — |
| 3 | Laatste 3 runs zien | 1 (uitklappen) + 1 (onderbouwing) / 0 — **of** 2 / 1 via Workspace | 1 / 0 | **50%** | 1 |
| 4 | Klachtdetail zien | 2 / 1 (Home → Workspace) of 3 / 2 (→ Dossier) | 2 / 1 | **33%** | 1 |
| 5 | Gemiste runs zien | 1 / 0 (compliance-detail, lazy) of 2 / 1 (Workspace-trainingen) | 1 / 0 | **50%** | 1 |
| 6 | Aankomende sessies zien | 2 / 1 (Workspace) | 2 / 1 | 0% | — |
| 7 | Huidig schema openen | 3 / 2 (Home → Workspace → Schema) of 2 / 1 (Home-signaalactie) | 2 / 1 (tab "Plan") | **33%** | 1 |
| 8 | Schema verlengen | 3 / 2 | 2 / 1 | **33%** | 1 |
| 9 | Volgende race + wens plaatsen | 2 / 1 (chip → Races) | 1 / 0 (tab Races op Vandaag) | **50%** | 1 |
| 10 | Feedback beoordelen | 1 / 1 | 1 / 1 | 0% | — |
| 11 | Atleethistorie inspecteren | 3 / 2 (Home → Workspace → Dossier) | 2 / 1 (tab "Historie", geen refetch) | **33%** | 1 |
| 12 | Coach-notitie toevoegen | 4 / 3 (Home → Workspace → Dossier → athleteNav Profiel) | 2 / 1 (tab "Profiel") | **50%** | 2 |
| 13 | Weekbriefing lezen | 1 / 1 + scroll voorbij N kaarten | 0 / 0 (blok op Vandaag) | **100%** | 1 |
| 14 | Teambelasting incl. afgehandeld | 1 / 1 | 1 / 0 (tab) | 0% klik, **1 wissel weg** | 1 |
| 15 | Wie loopt bijna zonder schema | 1 / 1 | 1 / 0 (tab) | 0% klik, **1 wissel weg** | 1 |
| 16 | Vanuit Feedback naar het plan | 2-3 / 2 (via Dossier of zijbalk) | 1 / 1 | **50-66%** | 1 |

**Totaal over de 16 acties:** 28 klikken / 20 paginawissels → **20 klikken / 10 paginawissels**.
**≈29% minder klikken, 50% minder paginawissels.**
Het zwaartepunt zit niet in de klikken maar in de **wissels**: elke wissel is een re-orientatie waarbij de coach opnieuw moet vaststellen waar hij is en welke atleet in beeld staat.

---

# Fase 8 — Content- & polish-audit

Alle punten hieronder zijn **uit de code aantoonbaar**. Ik claim geen visuele bevindingen zonder bewijs; waar alleen een echt apparaat uitsluitsel geeft, staat dat in Fase 11.

## Readability

| # | Bevinding | Bewijs | Ernst |
|---|---|---|---|
| R1 | **"1 runs in dit venster"** — geen enkelvoud | `app.js:6588` `${nRuns} runs in dit venster` | middel (zichtbaar bij elke atleet met 1 run) |
| R2 | **"1 atleten · …"** | `app.js:5100` `${items.length} atleten` | laag |
| R3 | **"1 trainingen gepubliceerd/klaar"** (3×) | `app.js:4686, 4703, 4704, 4705` | middel (staat in een FS-write-bevestiging) |
| R4 | **"1 weken"** (2×) | `app.js:4253, 4801` | laag |
| R5 | **Vier datumformaten voor dezelfde trainingsdatum** | Home `slice(5)` → `09-03` (`app.js:1204, 1237`) · Profiel `slice(5)` (`2141`) · Workspace `wsDatum` → `3 sep` (`6788`) · Dossier `dcShort` → `3 sep` (`5539`) · Feedback `fbDateLabel` → `Vandaag`/`wo 3 sep` (`2872`) · Teampuls rauwe ISO `2026-09-03` (`5190`) · Briefing `woensdag 3 sep` (`5225`) | **hoog** — `09-03` is ambigu (dag-maand of maand-dag?) en Teampuls toont het enige rauwe ISO-veld in de app |
| R6 | Engels "runs" in Nederlandse UI, naast "trainingen" elders | `app.js:6588` vs. `1207` "Recente trainingen" | laag |
| R7 | Feedback-paginakop draagt de meeste tekst van de app en herhaalt wat de kolommen al zeggen | `index.html:229` "Teambrede wachtrij — analyseer trainingen, geef feedback en stuur bij." | laag |
| R8 | Teampuls-infozin is een alinea van 3 zinnen als paginahint | `app.js:5188-5189` | middel — dit is uitleg die *nodig* is omdat de pagina zichzelf moet verdedigen tegenover Home; verdwijnt vanzelf bij consolidatie |
| R9 | "Debug"-knop staat permanent in de Feedback-appbar | `index.html:231` | laag (developer-affordance in een coachproduct) |

## Informatiehiërarchie

- **Primair signaal binnen 3-5 seconden:** ja op Home. `prioHoofdSignaal` = `signalen[0]` en de ingeklapte regel leidt altijd met exact dezelfde zin als de uitgeklapte kop (`app.js:1032-1049`). Dit is goed opgelost en moet blijven.
- **Actie bij de reden:** ja op Home (per signaal eigen Gezien/Later + contextknop) en op Workspace ("Volgende actie" hoort bij het primaire signaal, `app.js:6549-6555`).
- **Herhaalde blokken die ruis maken:** ja — de bronnenlijst (Workspace `ws-src`), de betrouwbaarheidsregel (Dossier `dsFresh`) en de generation-banner verschijnen op meerdere oppervlakken. Elk is individueel verdedigbaar (provenance is een productwaarde), maar samen dragen ze veel visueel gewicht voor informatie die de coach zelden nodig heeft.
- **Dossier is de dichtste pagina in de app:** 3-zone tableau + domeinstrip + actiebalk + controlepillen + diagnostiek. Verdedigbaar voor een af-en-toe-verklaringsoppervlak, te zwaar voor dagelijks werk — wat het argument voor "Historie als tab" versterkt, niet verzwakt.

## Consistentie

| # | Bevinding | Bewijs | Ernst |
|---|---|---|---|
| C-a | **Drie zijbalkitems delen één icoon** (`#ic-brain`): Workspace, Dossier, Schema bouwen | `index.html:87, 88, 91` | **hoog** — op een iconengedreven zijbalk is dit de directe oorzaak van "welke van deze twee hersenen was ook alweer de dagelijkse?" |
| C-b | Statusvocabulaire verschilt per pagina: Home `actie`/`aandacht`/`rustig`; Workspace `actie`/`aandacht`/`rustig`/`onbekend`; Teampuls `hoog`/`let op`; Dossier `GOOD`/`INSUFFICIENT_DATA` → `dcBeeldChip` | `app.js:983, 6513-6517, 5196, 5617` | middel — semantisch bewust verschillend, maar niet als één vocabulaire gepresenteerd |
| C-c | Metrische precisie verschilt: Home rondt km af op heel (`Math.round`, `app.js:1144`), Workspace toont `nlNum` met decimaal (`6535`), Teampuls toont de rauwe waarde (`5202`) | idem | middel — dezelfde atleet, drie km-getallen |
| C-d | "Dossier" betekent op Home iets anders dan elders (zie Fase 10, C1) | `app.js:1015, 1293` | **hoog** |
| C-e | Feedback-kolomkop wisselt tussen "Relevante context" en "Context" | `app.js:3067, 3503, 3504` vs `3527` | laag |

## Actielabels

De app doet dit **grotendeels goed** — er zijn nauwelijks kale "Bekijk"/"Open"-knoppen. Bestaande labels zoals `Huidig schema & verlengen`, `Bekijk in dossier`, `Open dossier voor de volledige context`, `Publiceer N trainingen naar FinalSurge` en `Gezien (7 dagen)` zeggen precies wat er gebeurt. Uitzonderingen:

| # | Label | Probleem |
|---|---|---|
| A1 | **"Dossier"** (Home swipe + detail) | gaat naar **Profiel** (`#atleten/<k>`), niet naar Dossier |
| A2 | "Dossier →" (Teampuls) | gaat wél naar Dossier — dus hetzelfde woord, twee bestemmingen |
| A3 | "Naar feedback" (Workspace) | gaat naar de **teambrede** wachtrij, niet naar deze atleet — het label suggereert athlete-scope |
| A4 | "Bekijk antwoorden" (Intake) | prima, maar het is een accordeon, geen navigatie — visueel gelijk aan navigatieknoppen |

## Empty / loading / error states

Dit is een **sterk punt** van de app en het resultaat van eerdere correctness-rondes. Bewezen goed:
- Geen valse nul: Workspace toont `Geen belastingstand bekend.` i.p.v. `0 km` (`app.js:6543`), en de badge wordt `onbekend` i.p.v. `rustig` (`6513`).
- Geen ongepaste geruststelling: `Te weinig om op te oordelen — geen belastingstand en geen open signaal.` (`6209`).
- Niet-technisch: `dcDiag` zegt expliciet "dit is een interne fout, **geen** bronfout" (`5990`).
- Geen dead-end: elke lege staat draagt een vervolgroute.

Eén rest: Home's foutpad verwijdert de feedbackstrip volledig (`app.js:693` `fb.remove()`) in plaats van een herstelbare staat te tonen. Klein, maar het is de enige plek waar een fout leidt tot *verdwijnen* in plaats van *uitleggen*.

## Visuele polish (alleen wat uit code/CSS bewijsbaar is)

- **Kaartstijlen zijn niet één systeem.** Er bestaan minstens vier parallelle kaartfamilies: `.ds-panel` (design system, Workspace/Dossier), `.panel` (Profiel/Intake/Strippen), `.rij-kaart` (Teampuls/Races/Schema-verloop), `.fb-card` (Feedback). Dat is historisch verklaarbaar maar het is de directe reden dat de app als losse dashboards leest.
- **Twee stylesheets, 1371 + 1630 regels**, met 20 verschillende breakpointwaarden (440, 480, 560, 760, 899, 900, 1080, 1100, 1101, 1179, 1180, 1200, 1280(JS), 1300, 1320, 1520). Dat is geen schaal — dat is drift.
- **Zijbalkgroepen (`Plannen`/`Praktijk`/`Zaken`) matchen de mentale groepering niet:** "Workspace" en "Dossier" staan *boven* het eerste groepslabel (ongegroepeerd), terwijl "Schema bouwen" onder "Plannen" staat — hoewel Workspace's primaire acties allebei schema-acties zijn.
- **`#meer` dupliceert op desktop de volledige zijbalk** (9 kaarten die alle 9 al links staan, `index.html:343-400`).

---

# Fase 9 — "Waarom staat dit hier?"

| Pagina | Blok | Classificatie | Toelichting |
|---|---|---|---|
| Home | hero (groet/telling/status) | `USEFUL SUMMARY` | oriëntatie, goedkoop |
| Home | feedbackstrip | `NEEDED FOR DECISION` | bepaalt of de coach de wachtrij in gaat |
| Home | Prioriteit vandaag | `NEEDED FOR DECISION` | de kern van het product |
| Home | uitgeklapte briefing | `NEEDED FOR DECISION` | voorkomt een paginawissel voor de meest voorkomende actie |
| Home | trainingsrijen bij compliance (lazy) | `NEEDED FOR DECISION` | het bewijs achter "N gemist"; lazy dus gratis |
| Home | "Ook nog" (intake/strippen) | `USEFUL SUMMARY` | praktijkwerk zonder eigen dagelijkse pagina |
| Teampuls | belastingkaartenlijst | **`DUPLICATE WITHOUT PURPOSE`** | zelfde bron + zelfde velden als Home's belasting-signaal |
| Teampuls | `<details>` Onderbouwing | **`DUPLICATE WITHOUT PURPOSE`** | veld-voor-veld gelijk aan `prioSignaalBody` |
| Teampuls | `duiding` (AI-zin) | `NEEDED FOR DECISION` | **uniek** — bestaat nergens anders |
| Teampuls | weekbriefing | `NEEDED FOR DECISION` | **uniek** — en verkeerd geplaatst (onderaan een dubbele lijst) |
| Teampuls | "Gezien (7 dagen)" | `DUPLICATE BUT JUSTIFIED` | monitoring-dempen naast Home-afvinken |
| Workspace | Aandacht nu | `NEEDED FOR DECISION` | |
| Workspace | Belasting 7 dagen | `NEEDED FOR DECISION` | dé ene load-kaart; correct als enige plek met km/%/referentie |
| Workspace | Doel & planning | `DUPLICATE BUT JUSTIFIED` | nodig om de schema-actie te kaderen |
| Workspace | Trainingen | `NEEDED FOR DECISION` | |
| Workspace | Volgende actie | `NEEDED FOR DECISION` | het beste stuk product in de app |
| Workspace | Feedback-kaart | `USEFUL SUMMARY` | |
| Workspace | Bronnen | `USEFUL SUMMARY` | provenance is productwaarde, maar hoort achter progressive disclosure |
| Dossier | tijdlijn verleden→nu→toekomst | `NEEDED FOR DECISION` | uniek: `changes` + provenance |
| Dossier | "nu"-kolom (attention/load) | **`DUPLICATE WITHOUT PURPOSE`** | identiek aan Workspace "Aandacht nu" + belasting, uit dezelfde payload |
| Dossier | domeinstrip | `USEFUL SUMMARY` | |
| Dossier | "Waarom?" (`/explain`) | `NEEDED FOR DECISION` | **uniek** en waardevol |
| Dossier | actiebalk (Naar schema / Workspace) | `NEEDED FOR DECISION` | |
| Profiel | Training (uit FinalSurge) | **`BELONGS ELSEWHERE`** | Workspace toont ditzelfde rijker (gepland/gemist/rust) |
| Profiel | Intake & doel | `DUPLICATE BUT JUSTIFIED` | de rauwe intakevelden; Workspace toont alleen de afgeleide doelregel |
| Profiel | Coach-notities | `NEEDED FOR DECISION` | **uniek + write** |
| Profiel | Coach-geheugen | `NEEDED FOR DECISION` | **uniek + write** |
| Profiel | Documenten / Eerdere intakes | `USEFUL SUMMARY` | |
| Profiel | koppel-intake | `NEEDED FOR DECISION` | de intake-flow |
| Feedback | wachtrij + tabs + groepen | `NEEDED FOR DECISION` | |
| Feedback | case-hero (gepland vs uitgevoerd) | `NEEDED FOR DECISION` | |
| Feedback | contextkolom | `DUPLICATE BUT JUSTIFIED` | expliciet gereduceerd, met gedocumenteerde reden |
| Feedback | sessiesamenvatting | `NEEDED FOR DECISION` | |
| Feedback | Debug-paneel | `BELONGS ELSEWHERE` | achter een instelling, niet in de appbar |
| Races | lijst | **`DUPLICATE WITHOUT PURPOSE`** als pagina | is de expansie van een Home-chip |
| Races | wens-composer | `NEEDED FOR DECISION` | **uniek + write** |
| Schema-verloop | volledige lijst | **`DUPLICATE WITHOUT PURPOSE`** als pagina | breder venster op Home's schema-signaal |
| Meer | 9 navigatiekaarten | `DUPLICATE WITHOUT PURPOSE` **op desktop**, `NEEDED` op mobiel | |

---

# Fase 10 — Cross-page truth-/coherentie-audit

*Geen logica gewijzigd. Alleen vastgelegd.*

| Concept | Autoritatieve bron | Samengevat op | Woorden verschillen? | Semantiek verschilt? | Bedoeld? | Aanbevolen canonieke formulering |
|---|---|---|---|---|---|---|
| Atleetprioriteit | `home_core._bereken` → `items` (tier+severity+naam) | Home | n.v.t. | n.v.t. | ja | — |
| Belasting | `coach_read.load_metric` (**één formule**) | Home ×2, Workspace, Dossier, Teampuls | **ja** (afronding: heel vs. decimaal vs. rauw) | nee | **nee** | `Belasting hoog · +60% t.o.v. referentie` (= `load_metric.primair`), km altijd heel |
| Gemiste runs | `brain.derive` `training.run_missed.<wk>` | Dossier (rij + kaart ≥2), Feedback | nee | nee | ja | `N geplande hardlooptrainingen gemist` |
| Klachten | `dossier_cockpit._attention` (actief > recent > terugkerend, binnen status nieuwste eerst) | Workspace, Dossier, Feedback | nee | nee | ja | — |
| Onderbreking / comeback | `load_context.interruption` | Workspace, Dossier | nee | nee | ja | — |
| Herstel onder druk | `recovery.rpe_trend` / `recovery.feeling_trend` | Workspace, Dossier | nee | **zie C2** | **nee** | één kaart, twee bronregels |
| Actief schema | `FS.get_schema_end_dates` | Home, Workspace `wsSchemaFeit`, Schema-verloop, Schema Verlengen | ja (`nog 5d` / `t/m 12 sep` / `bijna`) | nee | deels | `Actief schema · t/m 12 sep · nog 5 dagen` |
| Doel / race | `planning.rows` (`Hoofddoel`, `Wedstrijddatum`) | Workspace, Dossier, Feedback, Races | ja | nee | nee | `Hoofddoel: …` + `Wedstrijd: … (over N dagen)` |
| Feedbackstatus | `canonical_open_actions` / `_apply_feedback_overlay` | Home-strip, Workspace fb-kaart | nee | nee | ja | — |
| Bron-versheid | `coach_read.generation.freshness` + `source_versions` | Workspace `ws-src`, Dossier `dsFresh`, Teampuls `stand …` | **ja** (`vers`/`eerder`/`onbekend` vs. `bronnen vers` vs. `stand 2026-09-05 · verversen…`) | nee | nee | `vers` / `eerder (dd mmm)` / `onbekend`, overal gelijk |

## Vastgelegde coherentiedefecten (NIET nu fixen)

**C1 — "Dossier" heeft twee bestemmingen.**
Home's prioriteitsknop is `{ act: "dossier", label: "Dossier" }` (`app.js:1015`, `1163`), maar `prioDoe` routeert die naar `openAthleteModule("atleten", …)` (`app.js:1293`) — dus naar **Profiel**. Teampuls' `Dossier →` gaat naar `openAthleteModule("dossier", …)` (`app.js:5216`), de echte Dossier. Dit botst frontaal met de vastgelegde naamgevingsregel in `athleteNav` (`app.js:295-297`: "'Dossier' is de canonieke naam voor de #dossier-module … de #atleten-module → 'Profiel' (voorkomt twee keer 'Dossier')").
**De route is gelockt** (`tests/test_coach_workflow_cohesion.py:152`, `tests/test_coach_workflow_cohesion_live_repair.py:87` asserteren `openAthleteModule("atleten", it.user_key)`). **Het label is niet gelockt** — de enige `"Dossier"`-lock in de tests is `tests/test_cowork_fixpack_v1.py:81` en die geldt `athleteNav`. Dus: **het label corrigeren naar "Profiel" is presentatie-only en raakt geen lock.**

**C2 — Dubbele "Herstel onder druk" (het Cathinca-geval), root cause bewezen.**
`pwa/dossier_cockpit.py:209-212`:
```python
elif (k == "recovery.rpe_trend" and e.value == "zwaarder") or \
     (k == "recovery.feeling_trend" and e.value == "slechter"):
    cards.append(_card_obj("recovery_neg", …, "Herstel onder druk", f"{_label(k)}: {e.value}", e, rank=2))
```
Dit is een `elif` **binnen de evidence-loop**, met een OR over **twee verschillende evidence-keys**. Draagt een atleet beide (RPE zwaarder **én** gevoel slechter), dan vuurt de tak twee keer en worden **twee kaarten met dezelfde titel** toegevoegd; alleen de ondertitel verschilt ("RPE-trend: zwaarder" vs. "Gevoelstrend: slechter"). Er is geen dedupe op titel. **Dit is presentatie, geen truth-fout** — beide evidences bestaan echt. De juiste oplossing is één kaart met twee bronregels.

**C3 — Actieve klacht naast "Geen open klacht of signaal", root cause bewezen.**
In `dcBuildEvents` (`app.js`) worden klachten bewust naar de **verleden**-kolom verplaatst (gedateerd): `(attn||[]).filter(c => c.kind === "complaint")`. De **nu**-kolom filtert ze er expliciet uit: `(attn||[]).filter(c => c.kind !== "complaint" && …)`. Is een klacht het **enige** attention-item en is er geen `load_observation`, dan is `now` leeg en vuurt de fallback (`app.js:5788-5794`) met de titel **"Geen open klacht of signaal"** — terwijl de actieve klacht een paar centimeter links op hetzelfde scherm staat. **Presentatie-defect, geen truth-defect.** Correcte fix: de fallback mag niet "geen klacht" zeggen wanneer `attn` klachten bevat; die zin hoort alleen bij een écht leeg `attn`.

---

# Fase 11 — Mobile / responsive review

Alleen code-inspectie. **Geen enkele visuele PASS geclaimd zonder apparaatbewijs.**

Breakpoints: `440, 480, 560, 760, 899, 900, 1080, 1100, 1101, 1179, 1180, 1200, 1300` (CSS) + **`1280` in JS** (`dcRender`).
Shell: `<900px` onderbalk + volle breedte; `≥900px` zijbalk 250px; `≥1200px` zijbalk 280px.

| Onderdeel | Bevinding | Classificatie |
|---|---|---|
| Shell (zijbalk ↔ onderbalk) | schone omslag op 900px, één regel | `LIKELY SAFE` |
| `ws-grid` | 1 kolom → 2 (≥900) → 3 (≥1300), expliciete `grid-template-areas` per stap, `.ws-panel{min-width:0}` | `LIKELY SAFE` |
| `fb-grid` (Feedback) | basis is **3 kolommen** met `minmax(254px,296px)` + `minmax(0,1.94fr)` + `minmax(258px,298px)`; de 1-koloms fallback vuurt pas `≤1100px`. Bij viewport **1101-1250px** is de contentbreedte `viewport − 250 zijbalk − 80 padding` ≈ **771-921px**, waarvan minimaal 512px naar de zijkolommen gaat + 28px gaps → **middenkolom ~230-380px** voor de case-hero met tabel gepland/uitgevoerd | **`CODE-LEVEL RISK`** — smalste denkbare band, precies de laptopbreedte |
| Dossier `isNarrow` | `window.innerWidth < 1280` in JS (`dcRender`), terwijl CSS `.dc-grid` pas op `≤1180` collapst → de band **1181-1279px** rendert altijd de stack en de desktop-grid-CSS is daar dode code | `CODE-LEVEL RISK` (geen breuk, wel drift) |
| Dossier bij resize | `dcBindResize` tekent **alleen connectoren** opnieuw (`if (… .querySelector(".dc-grid"))`); er is geen re-render bij het passeren van 1280px. Een tablet die van portret naar landschap draait blijft dus in de stack-layout tot een handmatige re-render | **`NEEDS REAL DEVICE CHECK`** (iPad landschap = 1180-1366px) |
| Feedback mobiele focus-overlay | `body.fb-focus-open` verbergt de queue, `fbf-back` verschijnt, `toonView` sluit de overlay bij verlaten (`app.js:158-164`) — expliciet gelockt beleid | `LIKELY SAFE` (maar Feedback-mobiel is nooit onderdeel van deze audit geweest) |
| Lange signaal-detailregels | `.ws-signals .ws-sig-t{overflow-wrap:anywhere}` en `.ws-calm{overflow-wrap:anywhere}` | `LIKELY SAFE` |
| Trainingsrijen | `.pd-s-*` / `.tr-row` gebruiken flex zonder expliciete mobiele stack | `NEEDS REAL DEVICE CHECK` |
| Dossier `dc-plan li` | `@media(max-width:560px)` stapelt naar kolom | `LIKELY SAFE` |
| Schema-formulieren | `.sb-cfg-row3` → 1 kolom `≤560px`; de workbench-tabellen hebben geen aangetoonde mobiele behandeling | `NEEDS REAL DEVICE CHECK` |
| `athleteNav`-chips | `@media(max-width:480px)` verkleint padding/font | `LIKELY SAFE` |
| Toaststack | `#toaststack` flexkolom + safe-area (Home+Teampuls-ronde) | `LIKELY SAFE` |

## Mobiele testchecklist (handmatig, later)

1. iPhone portret (390×844) — Home: prioriteitsrij uitklappen, swipe-acties links en rechts, toast verschijnt boven de onderbalk.
2. iPhone portret — Feedback: case openen, terugknop, composer met toetsenbord open (`kb-open`).
3. iPhone portret — Workspace: alle 7 panelen, lange signaalregels, trainingsrijen.
4. iPhone portret — Dossier: stack-modus, "Waarom?"-knop.
5. iPhone landschap (844×390) — controleer dat er geen 3-koloms layout aanslaat.
6. **iPad portret (834×1112)** — Feedback: valt onder de ≤1100-regel, dus 1 kolom. Verifiëren.
7. **iPad landschap (1194×834)** — **de kritieke test.** Feedback zit dan in de 3-koloms band met een smalle middenkolom (fb-grid risico hierboven). Dossier zit in de dode band 1181-1279.
8. iPad landschap — draai van portret naar landschap **terwijl Dossier open staat**: verifieer of de layout meebeweegt of in de stack blijft hangen.
9. MacBook 13" (1280×800, effectief ~1280 CSS px) — Feedback middenkolom en Dossier-tableau.
10. Extern scherm 1440px+ — Workspace 3-koloms en Dossier volledig tableau.
11. Alle bovenstaande met `prefers-reduced-motion` aan.
12. Alle bovenstaande met de PWA geïnstalleerd (standalone, safe-area insets).

---

# Fase 12 — `NON-NEGOTIABLE PRODUCT LOCKS`

Dit blijft **ongewijzigd**, wat er ook geconsolideerd wordt.

## Waarheid & architectuur
1. **Eén truth path.** `brain.adapter.build_state` → `AthleteState` → `brain.projections` → view-model. Geen tweede engine, geen tweede store, geen parallelle cache, geen nieuwe raw-cache.
2. **`coach_read.load_metric` is de enige belasting-formule** (%/ernst/`primair`/`kort`). Home, Teampuls, Workspace en Dossier lezen daaruit.
3. **`athlete_read` single-flight + SWR + `state_generation_id`** en de begrensde caches (`BEBETTER_STATE_CACHE_MAX`, `_herstel_cache` synchroon met de queue-snapshot, `races_core._cache`, `schema_core._WRITE_RECEIPTS`). De Render-geheugenfix mag niet ongedaan raken.
4. **Payload-bound generation + per-source version-dominance** (`source_versions` vector clock, nooit `max(timestamp)`).

## AthleteState-semantiek
5. `fs_client.is_executed_workout` is canoniek; `has_actual_data` is aantoonbaar onbetrouwbaar en mag niet terugkeren als status-bron.
6. **Run-only afwijkingsfeiten**: `training.run_missed.<wk>` / `training.run_unplanned.<wk>` + aggregaat, `_expliciete_run` (leeg/onbekend type = geen claim), geen matching, vandaag/toekomst nooit gemist, dedupe tegen `distance_deviation`, stabiele `stable_id`, drempel `RUN_MISSED_ATTENTION = 2`.
7. **Klachtsortering** actief > recent > terugkerend, binnen status nieuwste eerst.

## Workspace-gedrag
8. **UNKNOWN ≠ RUSTIG.** Drie expliciete standen (`aandacht`/`rustig`/`onbekend`); geen belastingstand → `Geen belastingstand bekend.` en badge `onbekend`, nooit `0 km` of `alles bij`.
9. `_load_context` telt alleen een **positieve** km/runs-waarde als "bekend".
10. **Runstatusmodel**: `gepland` voor vandaag/toekomst, `rust` via `_is_rustdag`, `gemist`/`half`/`gedaan` alleen in het verleden. Home blijft byte-identiek doordat `gepland` achter `vooruit` gegate is.
11. Primair signaal ⇄ primaire actie komen uit **hetzelfde** bovenste attention-item; `wsTweedeActie` houdt het tweede soort bereikbaar; `wsUniekeSignalen` dedupliceert.

## Home / Teampuls
12. **Home's gefilterde werklijst** met per-signaal Gezien/Later, undo, `_handled_active`-terugkeerregels en `_STAND_LOCK` (recompute mag coach-afhandeling niet overschrijven).
13. `canonical_open_actions` (FRESH/STALE/UNKNOWN) voedt Home-tegel, Feedback en Prioriteiten.
14. Home vs. briefing-noemer (68 vs. 48) blijft **bewust verschillend** en gelabeld.
15. Gedeelde `#toaststack`; meldingen dekken nooit kaartinhoud af.

## Feedback
16. **Volledige veiligheids-/copy-architectuur v4-v8**: MetricAuthority, `feedback_atoms` AUTO_SAFE vs. REVIEW_REQUIRED, `assemble_spine`, `validate_draft` fail-closed, geen athlete-facing zonepercentages, `execution_fit`, geplande-plan-bepaalt-de-metriek.
17. **Queue-inclusie, ordering en copy blijven ongemoeid** door elke consolidatie.
18. De Feedback-lifecycle in `toonView` (`fbLeave`, focus-overlay sluiten, `kb-open` opruimen) — daarom is Feedback-als-tab afgewezen.

## Routing & identiteit
19. **Routegrammatica `#<view>/<ident>`**, twee segmenten. Geen derde segment; extra state via pending-variabelen (`schemaOpenPending`, `schemaOpenMode`, `dcOpenPending`, `dcOpenEvent`, `wsOpenPending`).
20. **`activeAthleteKey()` leest de atleet uit de route-hash** — de route is de enige waarheid. `_ATHLETE_VIEWS` / `_ATHLETE_CTX_VIEWS` blijven zoals ze zijn.
21. **`nieuw:`-identity-guard**: een pre-link intake mag nooit app-brede atleetcontext worden.
22. Exacte Dossier deep-links (`dcOpenEvent` → `dcSelectEvent`) en de schema-modus-deeplink (`openSchemaMode`).
23. Draft-veiligheid: `sbDraftSave()` flusht bij het verlaten van de schema-workbench.

## Bron & provenance
24. Bron-versheid en provenance blijven zichtbaar (mag compacter, mag niet verdwijnen).
25. "Waarom?" (`/api/cockpit/explain`) met generation-check blijft bestaan.

---

# Fase 13 — Aanbevolen doelarchitectuur

## Top-level navigatie

```
┌──────────────────────────────────────────────────────────────┐
│  VANDAAG        FEEDBACK        ATLEET          ⋯ Praktijk   │
└──────────────────────────────────────────────────────────────┘
```

**VANDAAG** — *team-niveau, "wie vraagt mijn aandacht?"*
Eerste scherm: hero + feedbackstrip + **Prioriteit vandaag** (ongewijzigd). Daaronder een segmentregel:
`Actie` (default, = de huidige gefilterde lijst) · `Monitoring` (= de huidige Teampuls-lijst + Schema-verloop, óngefilterd, mét `duiding`) · `Races` (= de huidige Races-lijst + wens-composer).
De **weekbriefing** krijgt een vast blok — niet begraven.
*Absorbeert:* Home, Teampuls, Schema-verloop, Races.

**FEEDBACK** — *sessie-niveau, "beoordelen en antwoorden"*
Volledig ongewijzigd. Toevoeging: één "Naar workspace"-route naast "Open dossier".
*Absorbeert:* niets.

**ATLEET** — *atleet-niveau, "alles van deze persoon"*
Eén oppervlak met een permanente tabbar:
`Nu` (Workspace) · `Historie` (Dossier) · `Profiel` (notities, geheugen, intake, documenten) · `Plan` (Schema, met zijn eigen Nieuw|Verlengen-modusbalk).
Bovenaan: de atleetswitcher (bestaand) + naam + groep, identiek op alle vier de tabs.
**De routes blijven exact `#workspace/<k>`, `#dossier/<k>`, `#atleten/<k>`, `#schema/<k>`.** De tabbar is de bestaande `athleteNav`, opgewaardeerd en overal aanwezig — dus geen route-identiteitswijziging, geen nieuwe store, geen truth-risico.
*Absorbeert:* Workspace, Dossier, Atleten, Schema — als tabs, niet als verwijdering.

**PRAKTIJK** (lade / `Meer`) — *setup en administratie*
Intake, Strippenkaart, Documenten, Administratie, account. Uit de dagelijkse navigatie; Home's "Ook nog"-blok blijft de trigger die de coach ernaartoe stuurt wanneer het nodig is.

## Waar wat woont

| Vraag | Antwoord |
|---|---|
| Team-signalen | **Vandaag** — `Actie` (gefilterd) en `Monitoring` (ongefilterd) |
| Atleet-cockpit | **Atleet › Nu** |
| Longitudinale historie | **Atleet › Historie** (+ notities/geheugen op `Profiel`) |
| Feedbackwerk | **Feedback** |
| Planning | **Atleet › Plan** (met Nieuw\|Verlengen) |
| Races/doelen | lijst + wens op **Vandaag › Races**; het doel per atleet op **Atleet › Nu** |
| Intake/admin | **Praktijk** |

## "Een coachdag in het doelproduct"

1. App opent op **Vandaag**. Feedbackstrip zegt `7 wachten`. Prioriteit vandaag toont 5 atleten, gesorteerd op ernst.
2. Douwe staat bovenaan: *"Actieve klacht — scheen, 3 dagen"*. De coach klapt de rij uit — **geen paginawissel** — en ziet de onderbouwing en de bronregels.
3. Twee andere signalen zijn oud nieuws: swipe → `Alles gezien`. De lijst is nu 3 lang.
4. Douwe vraagt om echt werk: **Open atleet** → **Atleet › Nu**. Aandacht nu, belasting 7 dagen, trainingen, en één primaire actie die bij de klacht hoort.
5. De coach wil de historie: tab **Historie** — geen nieuwe fetch, de payload staat er al. Wat veranderde, wanneer, en "Waarom?" per claim.
6. Een notitie hoort erbij: tab **Profiel** → notitie toevoegen. Zelfde atleet, zelfde kop, geen zoekactie.
7. Het plan moet aangepast: tab **Plan** → modus `Verlengen` opent op het huidige blok met delta en readiness → publiceren naar FinalSurge.
8. Terug naar **Vandaag** via de navigatie. De lijst staat er nog, op dezelfde scrollpositie.
9. Tab **Monitoring**: de volledige teambelastingstand inclusief wat vandaag al is afgevinkt, plus de AI-duiding per atleet, plus wie er bijna zonder schema zit.
10. De weekbriefing staat er direct onder — geen scroll voorbij een dubbele lijst.
11. Tab **Races**: één race deze week zonder wens → wens schrijven en plaatsen. Klaar.
12. **Feedback**: de wachtrij in, cases afhandelen, en bij een case die om een planwijziging vraagt: één klik naar **Atleet › Plan**, daarna terug — de wachtrij staat nog exact zoals hij was.

**Drie plekken. Eén mentaal model: team → atleet → sessie.**

---

# Fase 14 — Geprioriteerd implementatieplan (max 10 items)

> **Nog niet uitvoeren.** Elk item afzonderlijk mergebaar, met eigen tests.

## Fase A — geen risico (labels, links, dedupe)

**A1 — Herstel de betekenis van "Dossier" op Home.**
Label van de prioriteitsknop `Dossier` → **`Profiel`** (`app.js:1015`, `1163`). **Route ongewijzigd.**
*Baat:* haalt de enige echte betekeniscollisie in het navigatievocabulaire weg. *Klikreductie:* 0, maar het voorkomt verkeerde afslagen. *Risico:* nul — presentatie-only; de bestaande route-locks (`test_coach_workflow_cohesion*.py`) blijven groen. *Pagina's:* Home. *Tests:* 1 nieuwe assertion + de bestaande route-locks. *Cowork:* nee.

**A2 — Eigen iconen voor Workspace, Dossier en Schema bouwen.**
Nu delen alle drie `#ic-brain` (`index.html:87, 88, 91`).
*Baat:* de zijbalk wordt scanbaar. *Risico:* nul. *Tests:* snapshot van `index.html`. *Cowork:* nee.

**A3 — Copy-consistentie-pass.**
Enkelvoud/meervoud (`app.js:6588, 5100, 4686, 4703-4705, 4253, 4801`); één datumformaat voor trainingsdatums (`3 sep`, met `Vandaag`/`Gisteren` waar Feedback dat al doet) — daarmee vervallen de rauwe `09-03` (Home, Profiel) en de rauwe ISO (Teampuls); km-afronding gelijk trekken; "runs" → "trainingen"; kolomkop `Context` uniform.
*Baat:* grootste leesbaarheidswinst per regel code. *Risico:* laag — puur presentatie; `dcShort`/`wsDatum` bestaan al en kunnen gedeeld worden. *Tests:* uitbreiden van de bestaande JS-suites. *Cowork:* nee.

**A4 — Sluit de twee gedocumenteerde coherentiegaten (presentatie-only).**
(a) `dossier_cockpit.py:209-212`: één `Herstel onder druk`-kaart met beide bronregels i.p.v. twee gelijknamige kaarten (defect C2).
(b) `dcBuildEvents`-fallback mag niet "Geen open klacht of signaal" zeggen wanneer `attn` klachten bevat (defect C3).
*Baat:* haalt de twee zichtbare zelftegenspraken uit Dossier. *Risico:* laag — geen evidence-wijziging, alleen kaartopbouw. *Tests:* 2 gerichte tests + de bestaande Dossier-locks. *Cowork:* **ja**, korte visuele hertest op Cathinca.

**A5 — Verplaats setup-modules uit de dagelijkse navigatie.**
Intake, Strippenkaart, Documenten, Administratie naar een `Praktijk`-lade; Home's "Ook nog"-blok blijft de trigger.
*Baat:* 14 zijbalkitems → 10. *Risico:* laag. *Tests:* nav-snapshot. *Cowork:* **ja**, korte navigatiecheck.

## Fase B — veilige consolidatie (gedeelde waarheid, gedeelde componenten)

**B1 — Permanente atleet-tabbar op alle vier de atleetroutes.**
`athleteNav` opwaarderen tot tabbar en **ook op Workspace renderen** (de `ws`-tak bestaat al, `app.js:308-309`, en wordt nooit aangeroepen). Zelfde volgorde, zelfde positie, atleetnaam + switcher erboven.
*Baat:* Atleet voelt als één pagina; notities gaan van 4 klikken naar 2. *Klikreductie:* 33-50% op journey B/E. *Risico:* laag — geen routewijziging, geen nieuwe state, `activeAthleteKey` blijft de waarheid. *Pagina's:* Workspace, Dossier, Profiel, Schema. *Tests:* uitbreiden `workspace_render` + `coach_review_v2` JS-suites; alle bestaande `athleteNav`-locks blijven gelden. *Cowork:* **ja**.

**B2 — "Monitoring"-segment op Vandaag (absorbeert Teampuls + Schema-verloop).**
Segmentregel `Actie | Monitoring | Races` onder de prioriteitenkop. `Monitoring` rendert de bestaande Teampuls-kaarten (`/api/teampuls/signalen`, inclusief `duiding` en `Gezien (7 dagen)`) plus de Schema-verloop-lijst (`/api/schema-verloop`). Beide endpoints ongewijzigd; geen nieuwe berekening; lazy laden per segment.
*Baat:* verwijdert 2 zijbalkitems en de dubbele dagelijkse scan; geeft de dead-end Teampuls-kaarten toegang tot de volledige actieset. *Klikreductie:* 2 paginawissels weg per dag. *Risico:* middel — Home is gelockt, dus het segment mag de bestaande `#home-prio`-render **niet** aanraken; het is een broer-container. *Tests:* nieuwe JS-suite voor het segment + alle bestaande Home-locks moeten groen blijven. *Cowork:* **ja**.

**B3 — Weekbriefing als eigen blok op Vandaag.**
`/api/teampuls/briefing` ongewijzigd; alleen de plek verandert.
*Baat:* van "1 klik + scroll voorbij N kaarten" naar 0. *Risico:* laag. *Tests:* 1. *Cowork:* nee.

**B4 — Races als segment op Vandaag.**
Bestaande `rc-filters`-chips en de wens-composer verhuizen mee; `#races/7d` blijft als deep-link bestaan zodat de Home-chip-belofte en de URL-state intact blijven.
*Baat:* 1 zijbalkitem weg; race-wens van 2 klikken naar 1. *Risico:* laag-middel — de FS-write (`/api/races/wens`) en de confirm-dialog moeten letterlijk meeverhuizen. *Tests:* bestaande races-locks + 1 routetest. *Cowork:* **ja** (het is een write-pad).

**B5 — Feedback → Workspace-route.**
Naast "Open dossier voor de volledige context" (`app.js:3525`) één "Naar workspace"-knop op dezelfde atleet. Tegelijk "Naar feedback" op Workspace herlabelen naar wat het echt doet (teambrede wachtrij).
*Baat:* sluit de laatste ontbrekende zijde van de driehoek Feedback ↔ Atleet. *Klikreductie:* 50-66% op journey "vanuit Feedback naar het plan". *Risico:* laag — geen wijziging aan queue, generatie of copy. *Tests:* 1 JS-assertion. *Cowork:* **ja**.

## Fase C — diepere structurele consolidatie (alleen als A+B bevallen)

**C1 — "Historie" hergebruikt de al opgehaalde cockpit-payload.**
`Atleet › Historie` rendert uit de payload die `wsLoadDeep` al in het geheugen heeft, in plaats van `/api/cockpit` een tweede keer op te halen. Dossier's unieke delen (`changes`, tijdlijn, domeinen, `explain`) blijven volledig.
*Baat:* één netwerkronde en één laadmoment minder per atleet; maakt tabwisselen instant. *Risico:* middel — vereist zorgvuldige generation-hygiëne (dezelfde `state_generation_id` moet meereizen, anders kan "Waarom?" op een oudere generatie antwoorden). *Tests:* generation-coherentietests + alle Dossier-locks. *Cowork:* **ja**.

**Bewust NIET op de lijst:**
- Feedback als tab (Scenario 3) — hoogste risico, laagste winst.
- Profiel's "Training (uit FinalSurge)" verwijderen — het is duplicatie, maar het zit aan `/api/atleten/{id}` vast en de winst is klein; pas overwegen als B1 landt.
- `#meer` op desktop verbergen — cosmetisch, kan meeliften met A5.
- Enige wijziging aan de routegrammatica of aan `_ATHLETE_VIEWS`.

**Totaal: 10 items** (A1-A5, B1-B5, C1 = 11 genummerd, waarvan C1 expliciet voorwaardelijk; de finite scope voor een eerste ronde is **A1-A5 + B1-B3**).

---

# Fase 15 — Scorecard

| Dimensie | Nu | Doel | Waarom het verschil |
|---|---:|---:|---|
| Navigatieduidelijkheid | **4** | **9** | 14 items in 4 groepen, drie met hetzelfde icoon, twee paar dat elkaars filterstand is → 4 items met elk een eigen betekenis |
| Rolduidelijkheid per pagina | **5** | **9** | 4 pagina's zijn `ROLE UNCLEAR` (Atleten, Teampuls, Schema-verloop, Meer-op-desktop) → elke overgebleven pagina heeft één zin zonder "en" |
| Actiegerichtheid | **8** | **9** | al sterk (Volgende actie, per-signaal Gezien/Later, gerichte CTA-labels); wint alleen door Teampuls-kaarten uit hun dead-end te halen en het `Dossier`-label te herstellen |
| Cross-page coherentie | **5** | **8** | drie bewezen defecten (C1 label, C2 dubbele kaart, C3 tegenstrijdige lege staat) + 4 doelrepresentaties + inconsistente versheidstaal → gedeelde componenten en één vocabulaire |
| Duplicatie | **3** | **8** | zelfde endpoint over 2 pagina's, zelfde bron over 2×2 pagina's, 5 oppervlakken voor km, 5 voor trainingen → duplicatie alleen nog waar hij een beslissing verandert |
| Klikefficiëntie | **6** | **9** | 20 paginawissels over 16 kernacties → 10; de winst zit vooral in weggenomen contextwissels |
| Informatiehiërarchie | **7** | **9** | per pagina goed (primair signaal binnen 3-5 s), tussen pagina's niet; de briefing staat onder een dubbele lijst en Bronnen/versheid dragen te veel gewicht |
| Leesbaarheid / polish | **6** | **8** | bewezen: 4 datumformaten, 6 enkelvoud/meervoud-fouten, 4 kaartfamilies, 3 gedeelde iconen, 20 breakpointwaarden |
| Mobiel vertrouwen | **5** | **6** | de intentie is echt aanwezig (ws-grid, fb-grid, dc-stack), maar er zijn twee `CODE-LEVEL RISK`-banden en drie `NEEDS REAL DEVICE CHECK`-items. **Zonder apparaatbewijs gaat dit cijfer niet omhoog** — consolidatie helpt (minder unieke layouts) maar bewijst niets |
| Coach-workflow totaal | **6** | **9** | de onderdelen zijn beter dan het geheel; het geheel wordt beter zonder één regel truth-logica te veranderen |

**Gemiddeld: 5,5 → 8,4.**

---

# Eindoordeel

## `CONSOLIDATE MODERATELY`

Met nadruk op **moderately**, en dat is een positieve conclusie, geen voorbehoud:

- De **correctness-laag is uitstekend en hoeft niet open.** Elk consolidatie-item hierboven is presentatie, navigatie of hergebruik van een bestaand endpoint. Er is geen enkele reden om truth-logica aan te raken, en het plan raakt die ook niet.
- De **agressieve variant is aantoonbaar slechter.** Feedback-als-tab kost de meeste implementatie en het meeste risico (de `toonView`-lifecycle-hooks zijn bewezen correctness) en levert nul klikwinst, omdat Feedback nu al één klik van overal is.
- De grootste winst zit niet in verwijderen maar in **hergroeperen**: vier zijbalkitems die filterstanden van elkaar zijn worden segmenten, en vier atleetroutes die één onderwerp delen worden tabs — **zonder één route te wijzigen.**

Er is één ding dat ik expliciet niet kan beweren: **dat het doelproduct er op een echt apparaat goed uitziet.** Deze audit is code-gebaseerd. De twee `CODE-LEVEL RISK`-banden (Feedback bij 1101-1250px, Dossier bij 1181-1279px) en de resize-bevinding op Dossier zijn met code bewezen; hun visuele impact niet. Die horen op de checklist in Fase 11, niet in een conclusie.

---

*Einde audit. Geen applicatiecode gewijzigd, geen merge, geen deploy, geen routes of navigatie aangepast, geen productiedata geraakt.*
