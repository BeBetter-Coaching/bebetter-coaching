# Feedback Field Round — 7 september 2026

**Productiebaseline:** `9a506cd` (SW `bebetter-shell-v133`, assets `?v=137a`)
**Aanleiding:** echte Feedback-ronde over ~20 atleten op maandag 7 september.
**Algemeen oordeel van de coach:** kwaliteit overwegend goed. Dit is GEEN rebuild —
zes concrete veldbevindingen, per stuk eerst bewezen, daarna minimaal aangepast.

**Werkwijze:** per punt (1) waargenomen gedrag, (2) het exacte productiepad,
(3) de bewezen root cause, (4) severity, (5) FIX / NO FIX / PRODUCTBESLISSING,
(6) de minimale ingreep, (7) regressierisico.

Alle bewijs hieronder is uit de code van `9a506cd` gehaald en waar mogelijk
lokaal gereproduceerd (reproducties staan expliciet vermeld). Er is tijdens dit
onderzoek geen echte feedback gegenereerd of verstuurd.

---

## Samenvatting

| # | Onderwerp | Root cause bewezen | Uitkomst | Laag |
|---|-----------|--------------------|----------|------|
| F1 | Foutmelding, maar na refresh staat het er al | ja | **FIX** | client (`app.js`) |
| F2 | Klacht van 4 weken terug komt nog terug | ja (gereproduceerd) | **FIX** | server (`brain/adapter.py`) |
| F3 | Korte positieve afsluiter bij goede sessie | n.v.t. (feature) | **FIX** | server (`feedback_atoms.py`) |
| F4 | `vandaag` terwijl de training van zondag is | ja (3 oorzaken) | **FIX** | server (3 bestanden) |
| F5 | Zwemdata in loopfeedback | ja (gereproduceerd) | **FIX** | server (`fs_client.py` + `ai_feedback.py`) |
| F6 | Ongeplande uitgevoerde runs zonder reactie | n.v.t. | **PRODUCTBESLISSING — niet implementeren** | — |

---

## F1 — Foutmelding, maar na browser-refresh staat het resultaat er meteen

### Waargenomen
De app meldde dat laden/genereren niet goed ging. Eén browser-refresh later stond
het resultaat er direct. Dit was dus geen trage laadactie: het duurde niet lang,
het *leek* mislukt.

### Exact productiepad
`pwa/static/app.js:2889 fbEnter()` → `fbQueueGet(false)` → `GET /api/feedback/queue`
(zonder `refresh`) → `pwa/api.py:394 feedback_queue()` → `pwa/feedback_core.py:1545 queue(refresh=False)`
→ `_queue_current_diag()` (`pwa/feedback_core.py:1228`).

### Root cause (bewezen)
Twee feiten die elkaar precies opheffen:

1. **De client breekt het hot-pad af na 8 seconden.**
   `FB_HOT_DEADLINE = 8000` (`app.js:2803`). `fbQueueGet` zet een eigen
   `AbortController` en abort bij die deadline; `data` wordt dan `null`.
2. **`fbEnter` behandelt die abort als een TERMINALE fout en slaat de
   achtergrond-refresh volledig over.**

```js
if (!r) {
  if (!FB.items.length) { fbRenderError(q.timedOut ? "timeout" : "network"); return; }
  fbMarkStale(...);
}
```

De `return` verlaat `fbEnter` vóór de afsluitende `fbRefresh()` (`app.js:2917`).
De coach krijgt "Feedback laadt te lang." plus een handmatige *Opnieuw proberen*,
en er draait daarna niets meer.

**Waarom staat het er ná een refresh wél meteen?** De afgebroken request is alleen
aan CLIENT-zijde afgebroken. De server werkte gewoon door en `_queue_current_diag()`
schrijft het resultaat van de trage durable-load in `_QUEUE_MEM` + `_cache`
(`feedback_core.py:1236-1243`). De volgende call is daardoor `bron: "mem",
durable_load_ms: 0` — instant. Dat is exact het waargenomen patroon: de
backend-actie was al geslaagd, alleen de client-afhandeling liep niet mee.

De 8 seconden zijn haalbaar bij een koud proces: de durable-load is een
GitHub-store-read, en `prewarm_queue()` (`feedback_core.py:1247`) draait bij
startup — komt de eerste coach-open dáár doorheen, dan wacht die op dezelfde
trage read.

### Severity
**Hoog voor vertrouwen, nul voor data.** Er gaat niets verloren en er wordt niets
dubbel gedaan; de coach ziet alleen een foutmelding waar het systeem in orde was.

### FIX
Een DEADLINE-abort op het hot pad is geen serverfout en mag niet terminaal zijn.
Bij `timedOut` zonder items: geen foutkaart maar de bestaande wacht-shell
(`fbRenderColdWaiting()`, `app.js:2791`) + `FB.pendingInitial = true`, en dóórlopen
naar de al bestaande `fbRefresh()` met zijn ruimere deadline (`FB_REFRESH_DEADLINE
= 90000`). Faalt óók die, dan slaat de bestaande refresh-foutafhandeling alsnog
terminaal om (`app.js:2930`: `if (FB.pendingInitial && !FB.items.length) fbRenderError(...)`).

Een ECHTE netwerk-/HTTP-fout (`timedOut === false`) blijft direct terminaal —
fail-closed blijft fail-closed.

### Minimale ingreep
Eén `if`-tak in `fbEnter`. Geen nieuwe request, geen retry-lus, geen tweede
generation-call (er is in dit pad überhaupt geen generatie): het aantal
server-calls blijft exact één hot + één refresh, precies zoals nu.

### Regressierisico
Laag. De terminale staat verschuift van "direct bij hot-timeout" naar "na de
achtergrond-refresh", wat het bestaande koude-start-gedrag (`r.pending`) al is.

---

## F2 — Klacht van 11-08 wordt op 07-09 nog aangehaald

### Waargenomen
Klacht gemeld op 11 augustus; de feedback van 7 september verwijst er nog naar.
27 dagen later.

### Exact productiepad
`pwa/brain/complaints.py:107 build()` → `pwa/brain/projections.py:56 for_feedback()`
→ `pwa/brain/adapter.py:346 feedback_context()` → `prompt_block` → `pwa/feedback_core.py:629 _brein_context()`
→ prompt.

### Root cause (bewezen, lokaal gereproduceerd)
De klacht-lifecycle kent `ACTIVE` (≤7d), `RECENT` (≤21d), `RECURRING`, `RESOLVED`,
`HISTORICAL`. De volgorde in `complaints.build` is:

```python
if is_resolved:      status = RESOLVED
elif is_recurring:   status = RECURRING          # ← vóór elke leeftijdstoets
elif last_age <= COMPLAINT_ACUTE.days:  status = ACTIVE
elif last_age <= COMPLAINT_RECENT.days: status = RECENT
else:                status = HISTORICAL
```

`is_recurring` telt uitsluitend het AANTAL meldingen binnen 90 dagen
(`COMPLAINT_RECURRING_HISTORY = 90`, `COMPLAINT_RECURRING_MIN = 2`) en kijkt NIET
naar hoe lang de laatste melding geleden is. Twee meldingen in augustus maken de
klacht dus tot 90 dagen na de eerste melding `RECURRING` — een status die de
leeftijdstoets volledig overslaat.

Reproductie (meldingen 04-08 en 11-08, generatiedatum 07-09):

```
complaint.knie RECURRING {'count': 2, 'dates': ['2026-08-04', '2026-08-11'],
                          'last_seen_days': 27, 'recurring': True}
```

`for_feedback` houdt `ACTIVE/RECENT/RECURRING` (`projections.py:63`), en
`feedback_context` doet hetzelfde (`adapter.py:369-371`). Gevolg, twee keer raak:

1. `_klacht_coachregel(...)` schrijft een volledige regel in het promptblok:
   *"Terugkerende klacht rond knie (2x gemeld, voor het laatst ~27d geleden gemeld).
   Coachperspectief: dit patroon verdient concreter opvolgadvies…"*
2. `complaints` is niet-leeg, dus de **ACTUEEL-signaal-guard** vuurt
   (`adapter.py:481`): *"LET OP — er staat hierboven een ACTUEEL signaal. Laat dat
   je reactie MEE sturen."* Een 27 dagen oude klacht wordt zo expliciet als
   actueel signaal aan het model aangeboden.

De v-coachability-laag deed dit al goed voor de atoom-kant: `complaint_new`
(`adapter.py:500`) sluit `RECURRING` bewust uit, en `feedback_atoms.py:356-370`
neemt een klacht alleen op als de atleet hem NU noemt óf hij in `complaint_new`
staat. Dat is precies de juiste recency-regel — hij is alleen nooit toegepast op
het promptblok zelf.

### Severity
**Middel-hoog.** Coachinhoudelijk verkeerd (achterhaalde klacht als actueel), maar
niet onveilig.

### FIX
In `feedback_context` (Feedback-laag, niet in `complaints.py`) telt een `RECURRING`
klacht alleen mee als de LAATSTE melding binnen het recente venster valt
(`recency.COMPLAINT_RECENT`, 21 dagen). `ACTIVE` en `RECENT` zijn per definitie al
binnen dat venster en veranderen niet.

Dit is bewust NIET in `complaints.py` gerepareerd: die status voedt ook Home,
Dossier en Workspace, waar een terugkerend patroon juist wél zichtbaar moet
blijven (`for_home` houdt `ACTIVE/RECURRING`). Alleen Feedback krijgt de
recency-eis.

### Minimale ingreep
Eén filterfunctie op de `complaints`-lijst binnen `feedback_context`. Daarmee
schuift ook de ACTUEEL-signaal-guard automatisch mee (die leest dezelfde lijst)
en blijft `complaint_new` ongewijzigd.

### Regressierisico
Laag en beperkt tot Feedback. `complaints.py`, `for_home`, de Dossier-klachten en
de klacht-ordening (`dossier_cockpit._attention`: actief > recent > terugkerend)
blijven byte-identiek.

---

## F3 — Soms één korte positieve afsluiter

### Waargenomen / gewenst
Bij duidelijk goede uitvoering mag de reactie eindigen met één korte positieve
slotzin. Nooit automatische lof bij matige, slechte of onduidelijke uitvoering.
Maximaal één slotzin; 2-4 zinnen blijft leidend.

### Exact productiepad
`pwa/feedback_core.py:652 build_decision()` → `feedback_atoms.py:233 _build_decision()`
→ `assemble()` → AUTO_SAFE-tekst.

### Root cause
Geen defect — een ontbrekende, bewust toe te voegen bouwsteen. Belangrijk is
alleen dat het model dit NIET mag verzinnen: in het AUTO_SAFE-pad moet elke
athlete-facing zin uit een geregistreerd atoom komen (`_final_is_atoms_only`,
`feedback_atoms.py:429`).

### Severity
Laag (polish).

### FIX
Eén nieuw atoom `positive_close` in de categorie `close`, met een strikte
deterministische poort. De afsluiter komt er ALLEEN bij als:

* `ExecutionFit == ON_TARGET` op de autoritaire metriek — het enige deterministische
  bewijs in het systeem dat de sessie volgens plan is uitgevoerd
  (`feedback_atoms.py:148 execution_fit`, `_NOISE_SECONDS = 90`);
* er geen correctie-atoom is (`recovery_blocks_z2_not_z1`, de Douwe-tegenspraak);
* er geen klacht- of afwezigheidsatoom is;
* er geen open vraag van de atleet is.

`MOSTLY_ON_TARGET`, `MIXED` en `CLEARLY_ABOVE` krijgen dus expliciet géén lof.
Gestructureerde trainingen krijgen hem ook niet: daar is `execution_fit` per
constructie `None` en de blok-observatie
(`feedback_facts.block_sequence_sentence`) bewijst alleen dat de blokken schoon
IN een zone vielen, niet dat ze de BEDOELDE zone haalden. Geen bewijs = geen lof.

### Minimale ingreep
Eén atoom + één regel in `_ORDER` (categorie `close` sorteert als laatste). De
zin telt niet mee als `content`, dus hij kan nooit zelf een REVIEW_REQUIRED-case
naar AUTO_SAFE tillen. `assemble()` cap `[:5]` blijft staan; is de reactie al vol,
dan valt juist de afsluiter af.

### Regressierisico
Laag. Geen wijziging aan `_final_is_atoms_only`, `_passes_guards`, `validate_draft`,
MetricAuthority of de AUTO_SAFE/REVIEW_REQUIRED-beslisboom.

---

## F4 — `vandaag` verwijst naar zondag terwijl het maandag is

### Waargenomen
Feedback op maandag over de training van zondag noemde die training `vandaag`.

### Root cause — drie onafhankelijke oorzaken, alle drie bewezen

**(a) Het same-day-sessieblok schrijft letterlijk "vandaag" in de prompt.**
`pwa/feedback_core.py:466`:

> "Deze atleet heeft **vandaag** meerdere hardloop-registraties die WAARSCHIJNLIJK
> dezelfde sessie zijn…"

Dat blok wordt gebouwd voor de dag VAN DE TRAINING (`day = w["workout_date"]`,
`feedback_core.py:389`), niet voor de generatiedag. Beoordeel je op maandag een
zondagtraining met twee registraties, dan krijgt het model het woord `vandaag`
aangereikt over een sessie van gisteren. Dit is de enige plek in de hele
generatie-prompt die nog een absoluut tijdswoord aan de trainingsdag hangt; v6
heeft alle andere relatieve dagwoorden er al uitgehaald.

**(b) De datum-context van `ai_feedback` is niet tijdzone-bewust.**
`ai_feedback.py:959`: `_today = date.today()` — de naïeve serverdatum. Render
draait UTC; tussen 00:00 en 02:00 Amsterdamse tijd is dat de VORIGE dag. Dan wordt
`_gap = (_today - _wd).days` nul voor een zondagtraining en schrijft de prompt
"Je reageert op de dag van de training zelf" (`ai_feedback.py:973`) — een
expliciete same-day-instructie op een training van gisteren.

De correcte, al bestaande waarheid staat een module verderop en wordt hier niet
gebruikt: `feedback_core._generation_date()` (`pwa/feedback_core.py:168`) is
`Europe/Amsterdam`-bewust en is precies hiervoor gebouwd (P1, v2). `ai_feedback`
importeert `feedback_core` al lazy (`ai_feedback.py:539`), dus er is geen
cycle-bezwaar en geen tweede implementatie nodig.

**(c) De fail-closed dagguard kent `vandaag` niet.**
`feedback_facts.py:35`:

```python
_REL_DAY = re.compile(r"\b(gisteren|eergisteren|morgen|overmorgen)\b", re.I)
```

`vandaag` staat er niet in. Alle andere relatieve dagwoorden worden hard
geblokkeerd door `validate_draft` (regel 5), maar een onterecht `vandaag` glipt
er dus altijd doorheen — ook als (a) en (b) gerepareerd zijn en het model het uit
zichzelf schrijft. Dit is de reden dat de fout de coach heeft bereikt.

### Severity
**Middel.** Feitelijk onjuiste dagtaal richting de atleet; de guard die dit hoort
te vangen had een gat.

### FIX
Alle drie:

* **(a)** `_session_context` beschrijft de dag datum-neutraal ("op de dag van deze
  training") in plaats van "vandaag".
* **(b)** `ai_feedback` gebruikt `feedback_core._generation_date()` als "vandaag"
  (lazy import, met terugval op `date.today()` zoals nu). Eén tijdwaarheid voor de
  hele generatie.
* **(c)** `validate_draft` blokkeert `vandaag` wanneer de beoordeelde training NIET
  van de generatiedag is. `_validate_or_block` heeft `w` en kent dus de
  trainingsdatum; de vergelijking gebruikt dezelfde `_generation_date()`.
  Same-day feedback mag `vandaag` gewoon zeggen.

### Bewuste afwijking van de acceptatiecriteria (F4)
De acceptatie noemt "previous day mag `gisteren`". Dat is NIET ingebouwd en
`gisteren` blijft onvoorwaardelijk geblokkeerd. Reden: v6 is een gelockt
productbesluit — relatieve dagwoorden worden athlete-facing niet gebruikt, er
wordt naar de BETEKENIS verwezen ("deze training", "de intervaltraining"). Dat
lock loslaten is een copy-modelwijziging, geen veldfix, en zou
`test_feedback_context_relevance_v6` en de v7-dagguard raken. De bestaande regel
is bovendien strenger dan wat F4 vraagt en haalt F4's eigenlijke doel volledig:
er komt nooit verkeerde dagtaal uit. Dit staat expliciet in het opleverrapport.

### Regressierisico
Laag. (a) en (b) raken alleen prompttekst. (c) is een striktere fail-closed guard;
de enige manier om er tegenaan te lopen is een tekst die `vandaag` zegt over een
training van een andere dag — precies de fout die we willen blokkeren.

---

## F5 — Zwemdata in loopfeedback (belangrijkste correctness-punt)

### Waargenomen
Atleet zwom 140 m en liep dezelfde dag 4,7 km herstel. De feedback op de LOOPsessie
leek naar het zwemmen te verwijzen.

### Exact productiepad
`pwa/feedback_core.py:658 generate_feedback()` → `ai_feedback.py:1284` →
`ai_feedback.py:487 _build_workout_context()` → `ai_feedback.py:512` →
`fs_client.py:669 get_fastest_activity_on_day()`.

### Root cause (bewezen, lokaal gereproduceerd)
`_build_workout_context` vervangt de uitvoering van DEZE training door de snelste
activiteit van die dag:

```python
# Voor race-workouts: controleer of er een snellere activiteit op dezelfde dag is.
workout_date = workout_data.get("workout_date", "")
is_race = workout_data.get("details", {}).get("is_race") or False
if athlete_key and workout_date and activities:
    fastest_act = _fs.get_fastest_activity_on_day(athlete_key, workout_date)
    if fastest_act:
        current_pace = _fs._pace_to_float(activities[0].get("pace_display") or "")
        fastest_pace = _fs._pace_to_float(fastest_act.get("pace_display") or "")
        if fastest_pace < current_pace * 0.85:
            activities = [fastest_act]                      # ← wordt DE uitvoering
```

Twee defecten in dat blok:

1. **`get_fastest_activity_on_day` filtert niet op sport.** `fs_client.py:669` neemt
   ELKE voltooide workout van die dag (`completed = [w for w in day_workouts if
   w.get("has_actual_data")]`) en sorteert op `pace_display` van de eerste
   activiteit. Zwemtempo (min/100 m) en fietstempo staan numeriek altijd ver ONDER
   looptempo (min/km), dus een zwem- of fietsactiviteit wint die vergelijking
   structureel.
2. **`is_race` wordt berekend maar nooit gebruikt.** De guard is
   `if athlete_key and workout_date and activities:` — de swap draait dus op
   ELKE training, niet alleen op races. Dit is zo sinds de eerste versie
   (`f4e7f3a`, 4 juni).

Na de swap gaat het door de hele run-context heen: `activity_summary =
_format_activity(activities[0])` en `laps = activities[0].get("Laps", [])`
(`ai_feedback.py:521-522`). De zwemactiviteit wordt dus als uitvoering van de
hardloopsessie aan het model gepresenteerd, inclusief zijn laps.

Reproductie met exact het veldscenario (4,7 km loop op 6:00/km + 140 m zwem op
2:30/100 m, beide 7 september):

```
fastest activity -> {'pace_display': '2:30', 'amount': 0.14, ...}   # de ZWEM-activiteit
current_pace 6.0  fastest 2.5   swap? True
classify_workout_type(swim) = 'swim'   classify_workout_type(run) = 'run'
```

De typering is dus wél correct beschikbaar op workout-niveau — ze wordt alleen
niet gebruikt.

### Severity
**Hoog.** Dit is de harde eis uit de prompt: feedback op een hardloopsessie mag
geen zwem-/fiets-/krachtdata als uitvoering van die sessie behandelen. Hij werd
geschonden.

### FIX
`get_fastest_activity_on_day` krijgt een optionele `sport`-parameter. Is die
gezet, dan tellen alleen workouts mee waarvan `classify_workout_type(w)` exact
gelijk is aan die sport. Het aanroeppunt in `_build_workout_context` geeft het
al deterministisch bepaalde `workout_data["workout_type"]` mee — dezelfde bron
van waarheid die queue, detail en AI al delen.

Defense in depth: het aanroeppunt verwerpt de swap bovendien als de teruggegeven
ACTIVITEIT zelf een ander type draagt (`activity_type_key` / `activity_type_name`
zitten op activiteitniveau; `classify_workout_type` leest die al). Twee
onafhankelijke poorten, beide uit de bestaande canonieke classifier — geen nieuwe
typeringslogica.

Default `sport=""` houdt het oude gedrag voor elke andere aanroeper; er is er
geen (enige productie-aanroeper is dit ene call site).

### Bewust NIET gerepareerd (gedocumenteerd)
De ontbrekende `is_race`-gate blijft staan. Het effect ervan is dat twee
HARDLOOP-registraties op één dag ook buiten een race geswapt kunnen worden (de
snelste wint). Dat is met de sportfilter niet langer cross-sport, dus de harde eis
is gehaald, en er is geen veldbewijs voor die tweede situatie. `is_race` alsnog
afdwingen zou de swap uitschakelen op elke dag waarop FinalSurge `is_race` niet
zet — een groter en ongemeten risico voor racefeedback dan het probleem dat het
oplost. Losse observatie, geen blinde vlek.

### Regressierisico
Laag. Zonder same-day cross-sport activiteit verandert er niets. MetricAuthority,
`assess_workout_blocks`, `classify_pace_hr_zone`, de zone-classificatie en het
non-run-pad (`_build_nonrun_context`) blijven ongemoeid.

---

## F6 — Uitgevoerde ongeplande runs zonder reactie ontbreken in de Feedback-lijst

Dit was expliciet geen bugclaim maar een productvraag.

### Wat er nu gebeurt (exact)
`pwa/feedback_core.py:1465` roept
`FS.get_workouts_needing_feedback(days_back=7, include_planned_no_notes=True,
include_unplanned_reactions=True, ...)` aan — let op: `include_data_only` blijft
default `False`.

In `fs_client.py:1011` wordt een uitgevoerde ONGEPLANDE run zonder atleet-input
een PROBE-kandidaat (`_probe_unplanned`), puur om zijn comments op te halen. De
comment-filter (`fs_client.py:1080-1087`) laat hem daarna alleen door als er een
ECHTE atleet-comment blijkt. Geen reactie = geen queue-item. Dat is bewust
ontworpen gedrag (Feedback v1 D, "unplanned coverage"), geen omissie.

### Is de coach hierdoor blind?
Nee. Sinds de run-deviations-milestone (`4959360`) levert
`pwa/brain/derive.py:271-283` per ongeplande uitgevoerde run een canoniek
evidence-item `training.run_unplanned.<workout_key>` — **onafhankelijk van
atleetcommentaar**. Dat item:

* staat in de Feedback-generatiecontext via `projections.for_feedback`
  (`projections.py:73`, per-workout gefilterd), dus het model weet het al bij het
  beoordelen van die sessie;
* verschijnt in het Dossier als "Extra hardlooptraining (niet gepland)"
  (`pwa/dossier_cockpit.py:73`).

De ontbrekende functie is dus uitsluitend: *een verplicht af te handelen
queue-item*, niet zichtbaarheid.

### Risico van wél toevoegen
* **Queue-spam.** Elke losse ad-hoc run van elke atleet wordt een te beoordelen
  item. De queue is de dagelijkse werkvoorraad; bij ~20 atleten over 7 dagen tikt
  dat hard aan en verdringt het de items waar een atleet echt om een reactie vroeg.
* **Ordening.** De sorteervolgorde (`_queue_public`, `feedback_core.py:1521`) is
  datum → groep → categorie → timestamp → naam, en is een gelockte waarheid
  (Feedback v1 E). Een nieuwe categorie raakt `_CAT_RANK` en daarmee de volgorde
  van álle bestaande items.
* **Extra API-druk.** `include_data_only=True` betekent een comment-fetch en een
  detail-fetch per extra kandidaat, in de sweep die nu al de zwaarste call is.
* **Semantiek.** Een ongeplande run zonder een woord van de atleet vraagt niet om
  een reactie; hij is context.

### Beschikbaar bewijs — en de grens ervan
Het volume van deze categorie is NIET gemeten. Meten vereist een live
FinalSurge-sweep met `include_data_only=True` over het echte rooster; dat is een
productie-read buiten de scope van deze ronde en zou de gemeten
sweep-karakteristiek verstoren. Zonder dat cijfer is er geen bewijs dat één van
de opties veilig is, en de prompt schrijft dan voor: niet implementeren.

### Aanbeveling: **A — niet toevoegen**
De dekking bestaat al comment-onafhankelijk (`training.run_unplanned`), het
ontbrekende stuk is alleen "verplichte afhandeling", en dat is precies het stuk
met queue-spam- en orderingsrisico. Optie C (gewone queue, lagere prioriteit)
raakt de gelockte sorteervolgorde en verzwaart de sweep zonder bewezen behoefte.
Optie B (aparte data-only categorie/filter) is de enige serieuze kandidaat voor
later — maar pas nadat het volume gemeten is.

**Vervolgstap als dit terugkomt (aparte ronde, niet nu):** eerst één read-only
meting van het aantal `is_data_only`-runs per week over het echte rooster; komt
dat onder ~1 per atleet per week uit, dan is optie B een reële kandidaat als
eigen filterstand — nooit als item in de standaardqueue.

**Niet geïmplementeerd in deze batch.**

---

## Wat expliciet ONGEMOEID blijft

* Feedback v4-v8 safety-architectuur, MetricAuthority, AUTO_SAFE vs
  REVIEW_REQUIRED, `assemble_spine`, `build_decision`, `_final_is_atoms_only`.
* De queue: inclusion gates, sortering, skip/post-pad, re-post-guard,
  `is_executed_workout`.
* De run-deviation-feiten (`training.run_missed` / `training.run_unplanned`).
* `complaints.py` en de klacht-lifecycle zelf; Home, Teampuls, Workspace, Dossier
  en de Consolidation R1-laag.
* Routes, navigatie, cross-page-indeling.
* Geen nieuwe cache, store of truth-pad.
