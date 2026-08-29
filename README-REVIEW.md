# BeBetter — Workspace Closure Review

**Branch:** `feature/app-design-system-athlete-shell-v1` · **commit:** zie COMMIT.txt
**Base:** `main = 39d2453` (SW v97 live) — deze branch is NIET gemerged.

## Wat dit is
De volledige stand van de Workspace visual-milestone bij SLUITING (closure-pass verwerkt):
de north-star passes (design system → visual wow → athlete canvas → north-star →
final pass) plus het Visual Design Lab-prototype dat de goedgekeurde eindrichting
draagt (`design-lab/workspace-lab.html` + still + motion-GIF).

## Leeswijzer (relevante bestanden)
- `pwa/static/app.js` — Workspace-render (`wsRender`, `wsAnchor`, `wsSignal`,
  `wsFigure`, `wsChart`, `wsOrbits`, `wsField`), Dossier (`dcRender`),
  Home-briefing (`prioDetailHtml`); generation-client (`noteGeneration`,
  `_genDominates`).
- `pwa/static/design-system.css` — token-laag, statussemantiek, shell/nav,
  Athlete Canvas (Workspace), Dossier living memory, Home-briefing.
- `pwa/static/styles.css` — basis-shell (ongewijzigde module-CSS).
- `pwa/static/index.html` — markup + asset-versies; `pwa/static/sw.js` — SW-cache.
- `pwa/coach_read.py` — Coach Read Model (ONGEWIJZIGD in deze milestone;
  alleen gelezen door de presentatie).
- `tests/test_app_design_system_v1.py` — design-contracttests (37).
- `design-lab/` — standalone prototype (geen productie-code) + renders.
- `review-screenshots/` — acceptance-shots van de laatste productie-stand.
- `FABLE-NORTHSTAR-v1.md` — gap-analyses, bouwlog, self-reviews, residuals.

## Extra in deze closure-versie
- `pwa/static/fonts/` — Space Grotesk (lokaal, preload + SW-cache v103).
- Rim-gauge, weekstrip, perspectiefvloer, cockpit-wrap, eyebrow/gradient-kop.
- `design-lab/workspace-live-recording.gif` — echte interface-opname
  (entree → idle → switcher → atleet-wissel).

## Teststatus
1026 passed — vaste én random volgorde (`python3 -m pytest tests/ -q`).

## Performance sanity (headless Chrome, koud, lokaal)
FCP 772–804 ms (gelijk aan baseline vóór alle visuele werk, A/B gemeten);
0 horizontale overflow op 1440px en 390px; geen nieuwe console-errors
(alleen pre-existing favicon-404 + vibrate-warning); 3 trage orbit-rotaties
als enige doorlopende animatie; geen library/canvas/WebGL in productie.

## Known residuals (bewust NIET in deze milestone)
1. Feedback: workoutinhoud onvoldoende zichtbaar vóór feedback geven.
2. Feedback: ongeplande/meerdere workouts per dag kunnen stil verdwijnen
   (ook coach-self athlete onderzoeken).
3. Teampuls/Feedback/Schema krijgen later ditzelfde visuele systeem.
4. Schema Maintenance v1 (Bijsturen, pace↔HR, Builder bijvullen).
5. Dossier history-capture activation (timeline bewust leeg).
6. Ongescopete `$(".md-list")` in `openDossier` (bekende latente bug).
7. Data-nit: km-afronding verschilt tussen bron-zin (74) en canonieke
   detailvelden (73.8) — percentages zijn overal genormaliseerd.
