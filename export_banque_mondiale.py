#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_banque_mondiale.py
=========================
Indicateurs de population et de conditions de vie des 8 pays de l'UEMOA,
lus directement sur l'API de la Banque mondiale (World Development Indicators),
pour les profils pays du portail.

Les libellés source sont conservés dans le fichier exporté (ex. le seuil de
pauvreté, révisé par la Banque mondiale à 3,00 dollars par jour en PPA 2021).

Fichiers produits :
    data/raw/banque_mondiale_<AAAA-MM-JJ>.csv
    uemoa-dashboard/src/data/banque_mondiale.json
    journal des mises à jour (observatoire/journal.py)

Usage :
    python export_banque_mondiale.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from observatoire import journal

for _flux in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _flux is not None and hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DEST = PROJECT_ROOT.parent / "uemoa-dashboard" / "src" / "data"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
API = "https://api.worldbank.org/v2/country/{pays}/indicator/{code}?format=json&per_page=1000&date={debut}:{fin}"
DEBUT = 2000

PAYS = {"BEN": "benin", "BFA": "burkina", "CIV": "cote_ivoire", "GNB": "guinee_bissau",
        "MLI": "mali", "NER": "niger", "SEN": "senegal", "TGO": "togo"}
INDICATEURS = [
    {"id": "population", "code": "SP.POP.TOTL", "unite": "habitants"},
    {"id": "population_urbaine", "code": "SP.URB.TOTL.IN.ZS", "unite": "% de la population"},
    {"id": "pib_habitant_usd", "code": "NY.GDP.PCAP.CD", "unite": "USD courants"},
    {"id": "esperance_vie", "code": "SP.DYN.LE00.IN", "unite": "années"},
    {"id": "mortalite_moins_5_ans", "code": "SH.DYN.MORT", "unite": "pour 1 000 naissances"},
    {"id": "pauvrete", "code": "SI.POV.DDAY", "unite": "% de la population"},
    {"id": "acces_electricite", "code": "EG.ELC.ACCS.ZS", "unite": "% de la population"},
    {"id": "acces_eau", "code": "SH.H2O.BASW.ZS", "unite": "% de la population"},
    {"id": "scolarisation_primaire", "code": "SE.PRM.ENRR", "unite": "% (taux brut)"},
]


class ErreurControle(ValueError):
    pass


def lire(code: str, fin: int) -> tuple[dict, str, list]:
    url = API.format(pays=";".join(PAYS), code=code, debut=DEBUT, fin=fin)
    with urllib.request.urlopen(url, timeout=120) as r:
        entete, lignes = json.load(r)
    if not lignes:
        raise ErreurControle(f"{code} : aucune donnée")
    nom = lignes[0]["indicator"]["value"]
    series, brut = {}, []
    for x in lignes:
        if x["value"] is None or x["countryiso3code"] not in PAYS:
            continue
        zone, an, v = PAYS[x["countryiso3code"]], int(x["date"]), float(x["value"])
        series.setdefault(zone, []).append([an, round(v, 2)])
        brut.append({"indicateur": code, "zone": zone, "annee": an, "valeur": v})
    for z in series:
        series[z].sort()
        annees = [a for a, _ in series[z]]
        if len(set(annees)) != len(annees):
            raise ErreurControle(f"{code} / {z} : années en double")
    return series, nom, brut, entete.get("lastupdated")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    maintenant = datetime.now(timezone.utc)
    sortie_ind, series, brut, majs = [], {}, [], set()
    try:
        for ind in INDICATEURS:
            s, nom, b, maj = lire(ind["code"], maintenant.year)
            series[ind["id"]] = s
            brut += b
            majs.add(maj)
            fins = {z: v[-1][0] for z, v in s.items()}
            sortie_ind.append({"id": ind["id"], "code": ind["code"], "nom_source": nom, "unite": ind["unite"],
                               "periode": [min(v[0][0] for v in s.values()), max(fins.values())]})
            print(f"  {ind['id']:<24} {nom[:60]:<60} pays {len(s)}  dernière année {min(fins.values())}–{max(fins.values())}")
    except ErreurControle as exc:
        print(f"ARRÊT : {exc}. Aucun fichier écrit.")
        return 1

    sortie = {
        "generated_at": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Banque mondiale, World Development Indicators (API)",
        "mise_a_jour_source": max(m for m in majs if m) if any(majs) else None,
        "indicateurs": sortie_ind,
        "series": series,
    }
    if args.dry_run:
        print("--dry-run : aucun fichier écrit.")
        return 0
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    chemin_brut = RAW_DIR / f"banque_mondiale_{maintenant.strftime('%Y-%m-%d')}.csv"
    pd.DataFrame(brut).to_csv(chemin_brut, index=False)
    cible = args.dest / "banque_mondiale.json"
    cible.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  instantané brut -> {chemin_brut}\n  banque mondiale -> {cible} ({cible.stat().st_size // 1024} Ko)")
    e = journal.evenement(
        "donnees", sortie["generated_at"], "export_banque_mondiale.py", id_=f"donnees-bm:{sortie['generated_at']}",
        indicateurs=[i["id"] for i in sortie_ind], zones=sorted(PAYS.values()),
        details={"fournisseur": sortie["source"], "jeu": "bm", "mise_a_jour_source": sortie["mise_a_jour_source"]},
    )
    if journal.enregistrer(e):
        print(f"  journal : {e['id']}")
    journal.ecrire(journal.charger(), args.dest / "journal.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
