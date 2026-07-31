#!/usr/bin/env python3
"""Render de FinalSurge-handleiding vanuit het sjabloon.

Gebruik:
    python3 build_handleiding.py                 -> standaard (algemeen)
    python3 build_handleiding.py Lisa garmin     -> persoonlijk voor Lisa (Garmin)
"""
import os
import sys

import template
from templates import handleiding

if __name__ == "__main__":
    answers = {}
    if len(sys.argv) > 1:
        answers["voornaam"] = sys.argv[1]
    if len(sys.argv) > 2:
        answers["horloge"] = sys.argv[2]
    out = os.path.join(template.G.HERE, "Handleiding_sjabloon.pdf")
    template.render(handleiding.TEMPLATE, answers, out)
    print("OK:", out, "| answers:", answers or "(standaard)")
