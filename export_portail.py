#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_portail.py
=================
Export des indicateurs macroéconomiques clés pour les 8 pays de l'UEMOA
et l'agrégat Union, destiné au portail (uemoa-dashboard).

Source : BCEAO via DBnomics
    - IMECO  « Principaux indicateurs macroéconomiques »
    - TC_A   « Taux de change annuel » (ensemble UMOA)

Fichiers produits :
    data/raw/portail_bceao_<AAAA-MM-JJ>.csv          (instantané brut, traçabilité)
    uemoa-dashboard/src/data/portail.json            (consommé par le frontend)

Ce script n'écrase aucun fichier existant du dashboard : il n'écrit que
portail.json. export_dashboard.py et ses JSON restent inchangés.

Contrôles intégrés :
    - chaque ratio « en % du PIB » publié par la BCEAO est recalculé à partir
      de sa série en niveau ; un écart médian > 1 point bloque l'export ;
    - un ratio publié à exactement 0 alors que sa série en niveau est non nulle
      est un zéro de remplissage (ex. solde budgétaire 2001-2008 de certains
      pays) : il est exporté comme valeur manquante, et signalé ;
    - un indicateur absent pour une zone est signalé, jamais complété.

Usage :
    python export_portail.py
    python export_portail.py --dry-run
    python export_portail.py --dest "C:/.../uemoa-dashboard/src/data"
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dbnomics import fetch_series

for _flux in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _flux is not None and hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DEST = PROJECT_ROOT.parent / "uemoa-dashboard" / "src" / "data"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Codes pays BCEAO (préfixe des codes de séries) -> identifiant du portail.
ZONES = {
    "BBB": {"id": "benin", "nom": "Bénin", "iso3": "BEN"},
    "CCC": {"id": "burkina", "nom": "Burkina Faso", "iso3": "BFA"},
    "AAA": {"id": "cote_ivoire", "nom": "Côte d'Ivoire", "iso3": "CIV"},
    "SSS": {"id": "guinee_bissau", "nom": "Guinée-Bissau", "iso3": "GNB"},
    "DDD": {"id": "mali", "nom": "Mali", "iso3": "MLI"},
    "HHH": {"id": "niger", "nom": "Niger", "iso3": "NER"},
    "KKK": {"id": "senegal", "nom": "Sénégal", "iso3": "SEN"},
    "TTT": {"id": "togo", "nom": "Togo", "iso3": "TGO"},
    "ZZZ": {"id": "uemoa", "nom": "UEMOA", "iso3": None},
}

# Indicateurs retenus (dataset IMECO). Le code complet = préfixe zone + suffixe.
INDICATEURS = [
    {"id": "pib_nominal", "suffixe": "SR1015A0BP", "famille": "production", "unite": "Mds FCFA",
     "libelle": "PIB nominal"},
    {"id": "croissance_reelle", "suffixe": "SR1041A0BP", "famille": "production", "unite": "%",
     "libelle": "Taux de croissance réel du PIB"},
    {"id": "taux_investissement", "suffixe": "SR1042A0BP", "famille": "production", "unite": "% du PIB",
     "libelle": "Taux d'investissement"},
    {"id": "inflation", "suffixe": "SR3072A0BP", "famille": "prix", "unite": "%",
     "libelle": "Taux d'inflation moyen annuel (IPC)"},
    {"id": "dette_pib", "suffixe": "FP3054A0FA", "famille": "finances_publiques", "unite": "% du PIB",
     "libelle": "Encours de la dette publique", "controle": "FP3001A0FA"},
    {"id": "solde_budgetaire_pib", "suffixe": "FP1098A0AP", "famille": "finances_publiques", "unite": "% du PIB",
     "libelle": "Solde budgétaire global, dons compris (base engagement)", "controle": "FP1043A0AP"},
    {"id": "pression_fiscale", "suffixe": "FP1092A0AP", "famille": "finances_publiques", "unite": "% du PIB",
     "libelle": "Recettes fiscales", "controle": "FP1004A0AP"},
    {"id": "balance_courante_pib", "suffixe": "SE1488A0AP", "famille": "echanges", "unite": "% du PIB",
     "libelle": "Solde du compte des transactions courantes", "controle": "SE1400A0AP"},
    {"id": "masse_monetaire", "suffixe": "SF1412A0AP", "famille": "monnaie", "unite": "Mds FCFA",
     "libelle": "Masse monétaire (M2)"},
    {"id": "credit_economie_pib", "suffixe": "SF1582A0AP", "famille": "monnaie", "unite": "% du PIB",
     "libelle": "Créances sur l'économie (autres secteurs)", "controle": "SF1420A0AP"},
]

# Taux de change : publié pour l'ensemble UMOA uniquement (dataset TC_A).
TAUX_CHANGE = {"id": "taux_change_usd", "serie": "BCEAO/TC_A/ZZZSF3100A0GP", "famille": "change",
               "unite": "FCFA pour 1 USD", "libelle": "Taux de change FCFA / dollar US", "zone": "ZZZ"}

SEUIL_ECART_MEDIAN = 1.0  # point de % du PIB


def annee(period) -> int:
    return int(str(period)[:4])


def serie_vers_dict(df: pd.DataFrame) -> dict[int, float]:
    df = df.dropna(subset=["value"])
    return {annee(p): float(v) for p, v in zip(df["period"], df["value"])}


def recuperer() -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Récupération BCEAO/IMECO (toutes zones)…")
    imeco = fetch_series("BCEAO", "IMECO", max_nb_series=2000)
    print(f"  {imeco['series_code'].nunique()} séries reçues")
    print(f"Récupération {TAUX_CHANGE['serie']}…")
    tc = fetch_series(TAUX_CHANGE["serie"])
    return imeco, tc


def controler_ratios(par_code: dict[str, dict[int, float]]) -> list[str]:
    """Recalcule chaque ratio publié à partir de sa série en niveau / PIB nominal."""
    erreurs = []
    for ind in INDICATEURS:
        niveau = ind.get("controle")
        if not niveau:
            continue
        ecarts = []
        for z in ZONES:
            pct = par_code.get(z + ind["suffixe"], {})
            num = par_code.get(z + niveau, {})
            pib = par_code.get(z + "SR1015A0BP", {})
            for an, v in pct.items():
                if an in num and pib.get(an):
                    ecarts.append(abs(v - 100 * num[an] / pib[an]))
        mediane = statistics.median(ecarts) if ecarts else float("nan")
        etat = "OK" if ecarts and mediane <= SEUIL_ECART_MEDIAN else "ÉCHEC"
        print(f"  contrôle {ind['id']:<24} n={len(ecarts):<4} écart médian={mediane:.2f} pt  {etat}")
        if etat != "OK":
            erreurs.append(ind["id"])
    return erreurs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    imeco, tc = recuperer()
    par_code = {code: serie_vers_dict(g) for code, g in imeco.groupby("series_code")}

    print("Contrôle des ratios publiés…")
    erreurs = controler_ratios(par_code)
    if erreurs:
        print(f"ARRÊT : ratios incohérents ({', '.join(erreurs)}). Aucun fichier écrit.")
        return 1

    # Séries du portail : {indicateur: {zone: [[année, valeur], …]}}
    series: dict[str, dict[str, list]] = {}
    indicateurs_meta = []
    lignes_brutes = []
    for ind in INDICATEURS:
        series[ind["id"]] = {}
        annees = []
        for z, zone in ZONES.items():
            code = z + ind["suffixe"]
            obs = dict(par_code.get(code, {}))
            niveau = par_code.get(z + ind["controle"], {}) if ind.get("controle") else {}
            zeros = [a for a, v in obs.items() if v == 0 and niveau.get(a)]
            for a in zeros:
                del obs[a]
            if zeros:
                print(f"  écartés (zéro de remplissage) : {ind['id']} / {zone['nom']} : {min(zeros)}–{max(zeros)} ({len(zeros)})")
            if not obs:
                print(f"  absent : {ind['id']} / {zone['nom']}")
                continue
            series[ind["id"]][zone["id"]] = [[a, round(v, 2)] for a, v in sorted(obs.items())]
            annees += list(obs)
            lignes_brutes += [{"serie": f"BCEAO/IMECO/{code}", "zone": zone["id"], "indicateur": ind["id"],
                               "annee": a, "valeur": v} for a, v in sorted(obs.items())]
        indicateurs_meta.append({
            "id": ind["id"], "famille": ind["famille"], "unite": ind["unite"], "libelle_source": ind["libelle"],
            "serie_bceao": f"BCEAO/IMECO/<zone>{ind['suffixe']}",
            "periode": [min(annees), max(annees)] if annees else None,
        })

    obs_tc = serie_vers_dict(tc)
    series[TAUX_CHANGE["id"]] = {"uemoa": [[a, round(v, 2)] for a, v in sorted(obs_tc.items())]}
    lignes_brutes += [{"serie": TAUX_CHANGE["serie"], "zone": "uemoa", "indicateur": TAUX_CHANGE["id"],
                       "annee": a, "valeur": v} for a, v in sorted(obs_tc.items())]
    indicateurs_meta.append({
        "id": TAUX_CHANGE["id"], "famille": TAUX_CHANGE["famille"], "unite": TAUX_CHANGE["unite"],
        "libelle_source": TAUX_CHANGE["libelle"], "serie_bceao": TAUX_CHANGE["serie"],
        "periode": [min(obs_tc), max(obs_tc)] if obs_tc else None,
    })

    maintenant = datetime.now(timezone.utc)
    portail = {
        "generated_at": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "BCEAO via DBnomics (datasets IMECO, TC_A)",
        "zones": [{"code_bceao": z, **v} for z, v in ZONES.items()],
        "indicateurs": indicateurs_meta,
        "series": series,
    }

    nb_points = sum(len(v) for s in series.values() for v in s.values())
    print(f"{len(indicateurs_meta)} indicateurs, {len(ZONES)} zones, {nb_points} observations")

    if args.dry_run:
        print("--dry-run : aucun fichier écrit.")
        return 0

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    brut = RAW_DIR / f"portail_bceao_{maintenant.strftime('%Y-%m-%d')}.csv"
    pd.DataFrame(lignes_brutes).to_csv(brut, index=False)
    print(f"  instantané brut -> {brut}")

    args.dest.mkdir(parents=True, exist_ok=True)
    cible = args.dest / "portail.json"
    cible.write_text(json.dumps(portail, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  portail -> {cible} ({cible.stat().st_size // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
