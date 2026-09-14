// Trainingsweekend-beheer: bedraginvoer → centen (14 sep 2026).
//
//   node tests/js/weekend_beheer.test.mjs
//
// Beheer typt bedragen zoals een Nederlander dat doet ("249,50", "€ 1.249"). De server
// accepteert alleen hele centen; een verkeerd gelezen bedrag wordt een verkeerde prijs
// waarmee deelnemers akkoord gaan. Snijdt de ECHTE functies uit weekend_beheer.js.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SRC = readFileSync(join(ROOT, "pwa", "static", "weekend_beheer.js"), "utf8");
function sliceFrom(header) {
  const i = SRC.indexOf(header);
  if (i < 0) throw new Error("not found: " + header);
  const b = SRC.indexOf("{", i);
  let d = 0;
  for (let j = b; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) return SRC.slice(i, j + 1); }
  }
  throw new Error("unbalanced: " + header);
}
const { parseEuroCent, centNaarInvoer, niceMax, pct } = new Function(
  `${sliceFrom("function parseEuroCent(")}\n${sliceFrom("function centNaarInvoer(")}\n${sliceFrom("function niceMax(")}\n${sliceFrom("function pct(")}\nreturn { parseEuroCent, centNaarInvoer, niceMax, pct };`)();

const failures = [];
const eq = (a, b, n) => { if (!Object.is(a, b)) failures.push(`${n}: ${String(a)} !== ${String(b)}`); };

eq(parseEuroCent(""), null, "leeg = niet vastgesteld");
eq(parseEuroCent("  "), null, "spaties = niet vastgesteld");
eq(parseEuroCent("249"), 24900, "heel bedrag");
eq(parseEuroCent("249,50"), 24950, "NL-decimaal");
eq(parseEuroCent("249,5"), 24950, "één decimaal");
eq(parseEuroCent("€ 1.249,50"), 124950, "euroteken + duizendtal + decimaal");
eq(parseEuroCent("1.249"), 124900, "NL-duizendtal zonder decimalen");
eq(parseEuroCent("249.50"), 24950, "punt als decimaal");
eq(parseEuroCent("0"), 0, "nul is een bedrag, geen 'leeg'");
eq(parseEuroCent("0,07"), 7, "centen zonder afronding");
eq(parseEuroCent("19,99"), 1999, "geen zwevendekommafout");
eq(parseEuroCent("249,505"), NaN, "drie decimalen weigeren");
eq(parseEuroCent("-50"), NaN, "negatief weigeren");
eq(parseEuroCent("vijftig"), NaN, "tekst weigeren");
eq(parseEuroCent("1,2,3"), NaN, "rommel weigeren");

for (const cent of [0, 7, 1999, 24900, 24950, 124950]) {
  eq(parseEuroCent(centNaarInvoer(cent)), cent, `heen-en-terug ${cent}`);
}
eq(centNaarInvoer(null), "", "null → leeg veld");
eq(centNaarInvoer(24900), "249", "hele euro's zonder ,00");

// Dashboard-as: hele, nette bovengrens ≥ de waarde; percentages zonder delen door nul.
for (const [n, max] of [[0, 1], [1, 1], [3, 3], [5, 5], [6, 10], [8, 10], [21, 30], [49, 50], [51, 75]]) {
  eq(niceMax(n), max, `niceMax(${n})`);
}
eq(pct(1, 8), 13, "pct afgerond");
eq(pct(3, 0), 0, "pct zonder totaal");

if (failures.length) {
  console.error("FAIL weekend_beheer:\n  " + failures.join("\n  "));
  process.exit(1);
}
console.log("ok weekend_beheer");
