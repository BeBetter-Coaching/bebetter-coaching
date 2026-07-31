#!/usr/bin/env python3
"""Render de kennisdocumenten (demo, zonder API-sleutel).

In de app draait `template.render(TEMPLATE, answers, out)` met de echte AI voor
de korte intro-alinea's. Hier vult een demo-ai_fn die intro's met voorbeeldtekst,
zodat je het volledige resultaat nu al ziet. De rest van de tekst is vaste,
onderbouwde inhoud.
"""
import os

import template
from templates import wedstrijd, voeding_training


def demo_ai(taak: str, context: str) -> str:
    naam = "Lisa"
    if "wedstrijdweek" in taak:
        return (f"{naam}, de grote dag komt eraan. Deze laatste week gaat niet meer over fitter worden, "
                f"maar over zo fris en scherp mogelijk aan de start komen. Volg deze punten en je haalt "
                f"alles uit je voorbereiding.")
    if "voeding rondom trainingen" in taak:
        return (f"{naam}, je traint hard, en met de juiste voeding haal je er meer uit én herstel je "
                f"sneller. Dit document zet op een rij wat je eet en drinkt rondom je trainingen, van je "
                f"ontbijt tot je herstelmaaltijd.")
    return taak


def carb_load(gewicht):
    g = float(gewicht)
    return str(round(g * 7)), str(round(g * 10))


if __name__ == "__main__":
    HERE = template.G.HERE

    w = {"voornaam": "Lisa", "gewicht": "68"}
    w["ch_laag"], w["ch_hoog"] = carb_load(w["gewicht"])
    template.render(wedstrijd.TEMPLATE, w, os.path.join(HERE, "Wedstrijd_sjabloon.pdf"), ai_fn=demo_ai)

    template.render(voeding_training.TEMPLATE, {"voornaam": "Lisa"},
                    os.path.join(HERE, "Voeding_sjabloon.pdf"), ai_fn=demo_ai)
    print("OK: Wedstrijd_sjabloon.pdf + Voeding_sjabloon.pdf")
