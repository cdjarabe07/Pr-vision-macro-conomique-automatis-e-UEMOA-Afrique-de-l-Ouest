#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_fmi.py
=============
Données internationales du FMI pour le portail (uemoa-dashboard), via DBnomics :

    - PCPS  « Primary Commodity Price System » : prix mensuels des matières
      premières qui comptent pour l'Union (pétrole, cacao, coton, or, uranium,
      arachide, riz, blé) ;
    - WEO   « Perspectives de l'économie mondiale » : projections annuelles par
      pays (croissance, inflation, dette, solde budgétaire, balance courante).

Les projections du FMI ne sont jamais mêlées aux séries BCEAO : leur champ
(administrations publiques, révisions) peut différer. Seules les années de
projection (à partir de PREMIERE_ANNEE_PROJECTION) sont exportées.

Fichiers produits :
    data/raw/fmi_<AAAA-MM-JJ>.csv                    (instantané brut)
    uemoa-dashboard/src/data/fmi.json                (consommé par le frontend)
    journal des mises à jour (observatoire/journal.py)

Usage :
    python export_fmi.py
    python export_fmi.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dbnomics import fetch_series

from observatoire import journal

for _flux in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _flux is not None and hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DEST = PROJECT_ROOT.parent / "uemoa-dashboard" / "src" / "data"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Unités : FMI, tableau des prix des matières premières (Monthly, table 3).
URL_UNITES = "https://www.imf.org/-/media/files/research/commodityprices/monthly/table3.pdf"
PRODUITS = [
    {"id": "petrole", "code": "POILBRE", "unite": "USD/baril", "zones": ["niger", "senegal"]},
    {"id": "cacao", "code": "PCOCO", "unite": "USD/tonne", "zones": ["cote_ivoire", "togo"]},
    {"id": "coton", "code": "PCOTTIND", "unite": "cents USD/livre", "zones": ["benin", "burkina", "mali", "cote_ivoire", "togo"]},
    {"id": "or", "code": "PGOLD", "unite": "USD/once", "zones": ["mali", "burkina", "cote_ivoire", "niger"]},
    {"id": "uranium", "code": "PURAN", "unite": "USD/livre", "zones": ["niger"]},
    {"id": "arachide", "code": "PGNUTS", "unite": "USD/tonne", "zones": ["senegal"]},
    {"id": "riz", "code": "PRICENPQ", "unite": "USD/tonne", "zones": []},
    {"id": "ble", "code": "PWHEAMT", "unite": "USD/tonne", "zones": []},
]
DEBUT_PRIX = "2015-01"

EDITION_WEO = "2025-04"
PREMIERE_ANNEE_PROJECTION = 2025
DERNIERE_ANNEE_PROJECTION = 2030
PAYS = {"BEN": "benin", "BFA": "burkina", "CIV": "cote_ivoire", "GNB": "guinee_bissau",
        "MLI": "mali", "NER": "niger", "SEN": "senegal", "TGO": "togo"}
PROJECTIONS = [
    {"id": "croissance_reelle", "code": "NGDP_RPCH", "unite_weo": "pcent_change", "unite": "%"},
    {"id": "inflation", "code": "PCPIPCH", "unite_weo": "pcent_change", "unite": "%"},
    {"id": "dette_apu", "code": "GGXWDG_NGDP", "unite_weo": "pcent_gdp", "unite": "% du PIB"},
    {"id": "solde_apu", "code": "GGXCNL_NGDP", "unite_weo": "pcent_gdp", "unite": "% du PIB"},
    {"id": "balance_courante", "code": "BCA_NGDPD", "unite_weo": "pcent_gdp", "unite": "% du PIB"},
]


class ErreurControle(ValueError):
    pass


def valeur_ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def recuperer_prix() -> tuple[list[dict], list[dict]]:
    ids = [f"IMF/PCPS/M.W00.{p['code']}.USD" for p in PRODUITS]
    df = fetch_series(ids)
    produits, brut = [], []
    for p in PRODUITS:
        g = df[df["series_code"] == f"M.W00.{p['code']}.USD"].copy()
        g["mois"] = g["original_period"].astype(str).str[:7]
        g = g[g["mois"] >= DEBUT_PRIX].sort_values("mois")
        points = [[m, round(float(v), 2)] for m, v in zip(g["mois"], g["value"]) if valeur_ok(v)]
        if len(points) < 24:
            raise ErreurControle(f"{p['id']} : {len(points)} mois seulement")
        mois = [m for m, _ in points]
        if len(set(mois)) != len(mois) or mois != sorted(mois):
            raise ErreurControle(f"{p['id']} : mois en double ou désordonnés")
        produits.append({**p, "serie": f"IMF/PCPS/M.W00.{p['code']}.USD", "points": points})
        brut += [{"serie": f"IMF/PCPS/M.W00.{p['code']}.USD", "periode": m, "valeur": v} for m, v in points]
    fins = {p["points"][-1][0] for p in produits}
    if len(fins) != 1:
        print(f"  attention : derniers mois différents selon les produits : {sorted(fins)}")
    return produits, brut


def recuperer_projections() -> tuple[dict, list[dict]]:
    ids = [f"IMF/WEO:{EDITION_WEO}/{iso}.{p['code']}.{p['unite_weo']}" for iso in PAYS for p in PROJECTIONS]
    df = fetch_series(ids)
    series, brut = {}, []
    for p in PROJECTIONS:
        series[p["id"]] = {}
        for iso, zone in PAYS.items():
            code = f"{iso}.{p['code']}.{p['unite_weo']}"
            g = df[df["series_code"] == code]
            pts = []
            for per, v in zip(g["original_period"], g["value"]):
                an = int(str(per)[:4])
                if PREMIERE_ANNEE_PROJECTION <= an <= DERNIERE_ANNEE_PROJECTION and valeur_ok(v):
                    pts.append([an, round(float(v), 2)])
            pts.sort()
            if not pts:
                print(f"  absent : {p['id']} / {zone}")
                continue
            series[p["id"]][zone] = pts
            brut += [{"serie": f"IMF/WEO:{EDITION_WEO}/{code}", "periode": a, "valeur": v} for a, v in pts]
    if not any(series.values()):
        raise ErreurControle("aucune projection récupérée")
    return series, brut


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Récupération IMF/PCPS (prix des matières premières)…")
    try:
        produits, brut_prix = recuperer_prix()
        print(f"Récupération IMF/WEO:{EDITION_WEO} (projections)…")
        projections, brut_weo = recuperer_projections()
    except ErreurControle as exc:
        print(f"ARRÊT : {exc}. Aucun fichier écrit.")
        return 1

    maintenant = datetime.now(timezone.utc)
    sortie = {
        "generated_at": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "matieres_premieres": {
            "source": "FMI, Primary Commodity Price System (PCPS), via DBnomics",
            "url_unites": URL_UNITES,
            "debut": DEBUT_PRIX,
            "dernier_mois": max(p["points"][-1][0] for p in produits),
            "produits": [{k: v for k, v in p.items() if k != "code"} for p in produits],
        },
        "projections": {
            "source": f"FMI, Perspectives de l'économie mondiale (WEO), édition {EDITION_WEO}, via DBnomics",
            "edition": EDITION_WEO,
            "premiere_annee": PREMIERE_ANNEE_PROJECTION,
            "derniere_annee": DERNIERE_ANNEE_PROJECTION,
            "indicateurs": [{"id": p["id"], "unite": p["unite"], "serie": f"IMF/WEO:{EDITION_WEO}/<ISO>.{p['code']}.{p['unite_weo']}"} for p in PROJECTIONS],
            "series": projections,
        },
    }
    for p in produits:
        print(f"  {p['id']:<9} {p['points'][0][0]} → {p['points'][-1][0]}  dernier : {p['points'][-1][1]} {p['unite']}")
    nb = sum(len(v) for s in projections.values() for v in s.values())
    print(f"  projections : {len(projections)} indicateurs, {nb} valeurs ({PREMIERE_ANNEE_PROJECTION}–{DERNIERE_ANNEE_PROJECTION})")

    if args.dry_run:
        print("--dry-run : aucun fichier écrit.")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    brut = RAW_DIR / f"fmi_{maintenant.strftime('%Y-%m-%d')}.csv"
    pd.DataFrame(brut_prix + brut_weo).to_csv(brut, index=False)
    print(f"  instantané brut -> {brut}")
    cible = args.dest / "fmi.json"
    cible.write_text(json.dumps(sortie, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  fmi -> {cible} ({cible.stat().st_size // 1024} Ko)")

    for e in journal.evenements_fmi(sortie):
        if journal.enregistrer(e):
            print(f"  journal : {e['id']}")
    journal.ecrire(journal.charger(), args.dest / "journal.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
