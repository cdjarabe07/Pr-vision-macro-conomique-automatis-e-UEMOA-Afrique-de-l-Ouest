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
portail.json et journal.json (journal des mises à jour, observatoire/journal.py).
export_dashboard.py et ses JSON restent inchangés.

Contrôles intégrés :
    - chaque ratio « en % du PIB » publié par la BCEAO est recalculé à partir
      de sa série en niveau ; un écart médian > 1 point bloque l'export ;
    - un ratio publié à exactement 0 alors que sa série en niveau est non nulle
      est un zéro de remplissage (ex. solde budgétaire 2001-2008 de certains
      pays) : il est exporté comme valeur manquante, et signalé ;
    - un indicateur absent pour une zone est signalé, jamais complété ;
    - les ruptures de série déclarées (RUPTURES) sont revérifiées dans les
      séries en niveau et exportées avec leurs sources ; aucune valeur n'est
      corrigée.

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

from observatoire import journal

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

    # --- Ajouts (structure de l'économie, finances publiques, échanges, monnaie).
    # Les ratios à libellé ambigu « (en % du PIB) » ont été identifiés en les
    # recalculant à partir des séries en niveau (écart médian ≤ 0,03 point).
    {"id": "poids_primaire", "suffixe": "SR1044A0BP", "famille": "production", "unite": "% du PIB",
     "libelle": "Poids du secteur primaire"},
    {"id": "poids_secondaire", "suffixe": "SR1045A0BP", "famille": "production", "unite": "% du PIB",
     "libelle": "Poids du secteur secondaire"},
    {"id": "poids_tertiaire", "suffixe": "SR1046A0BP", "famille": "production", "unite": "% du PIB",
     "libelle": "Poids du secteur tertiaire"},
    {"id": "contribution_primaire", "suffixe": "SR1047A0BP", "famille": "production", "unite": "points de %",
     "libelle": "Contribution du secteur primaire à la croissance", "groupe_zeros": "contributions"},
    {"id": "contribution_secondaire", "suffixe": "SR1048A0BP", "famille": "production", "unite": "points de %",
     "libelle": "Contribution du secteur secondaire à la croissance", "groupe_zeros": "contributions"},
    {"id": "contribution_tertiaire", "suffixe": "SR1049A0BP", "famille": "production", "unite": "points de %",
     "libelle": "Contribution du secteur tertiaire à la croissance", "groupe_zeros": "contributions"},
    {"id": "taux_epargne", "suffixe": "SR1043A0BP", "famille": "production", "unite": "% du PIB",
     "libelle": "Taux d'épargne intérieure"},
    {"id": "investissement_public_pib", "suffixe": "SR1051A0BP", "famille": "production", "unite": "% du PIB",
     "libelle": "Taux d'investissement public"},
    {"id": "inflation_glissement", "suffixe": "SR3073A0BP", "famille": "prix", "unite": "%",
     "libelle": "Taux d'inflation en glissement annuel (fin décembre)"},
    {"id": "solde_hors_dons_pib", "suffixe": "FP1090A0AP", "famille": "finances_publiques", "unite": "% du PIB",
     "libelle": "Solde budgétaire global, hors dons (base engagement)", "controle": "FP1042A0AP"},
    {"id": "depenses_courantes_pib", "suffixe": "FP1093A0AP", "famille": "finances_publiques", "unite": "% du PIB",
     "libelle": "Dépenses courantes", "controle": "FP1025A0AP"},
    {"id": "investissement_ressources_internes_pib", "suffixe": "FP1095A0AP", "famille": "finances_publiques",
     "unite": "% du PIB", "libelle": "Investissements sur ressources internes", "controle": "FP1094A0AP"},
    {"id": "exportations_biens", "suffixe": "SE1403A0AP", "famille": "echanges", "unite": "Mds FCFA",
     "libelle": "Exportations de biens FOB"},
    # Importations : enregistrées en négatif jusqu'en 2009 puis en positif (changement
    # de convention constaté dans toutes les zones) ; reprises à partir de 2010 seulement.
    {"id": "importations_biens", "suffixe": "SE1419A0AP", "famille": "echanges", "unite": "Mds FCFA",
     "libelle": "Importations de biens FOB", "debut": 2010,
     "motif_debut": "convention de signe différente avant 2010 (valeurs négatives)"},
    {"id": "ouverture_pib", "suffixe": "SE1487A0AP", "famille": "echanges", "unite": "% du PIB",
     "libelle": "Degré d'ouverture (exportations + importations de biens et services)"},
    {"id": "balance_courante_hors_dons_pib", "suffixe": "SE1489A0AP", "famille": "echanges", "unite": "% du PIB",
     "libelle": "Balance courante hors dons"},
    {"id": "creances_interieures_pib", "suffixe": "SF1581A0AP", "famille": "monnaie", "unite": "% du PIB",
     "libelle": "Créances intérieures", "controle": "SF1416A0AP"},
    {"id": "actifs_exterieurs_nets", "suffixe": "SF1413A0AP", "famille": "monnaie", "unite": "Mds FCFA",
     "libelle": "Actifs extérieurs nets"},
]

SUFFIXE_CROISSANCE = "SR1041A0BP"

# Taux de change : publié pour l'ensemble UMOA uniquement (dataset TC_A).
TAUX_CHANGE = {"id": "taux_change_usd", "serie": "BCEAO/TC_A/ZZZSF3100A0GP", "famille": "change",
               "unite": "FCFA pour 1 USD", "libelle": "Taux de change FCFA / dollar US", "zone": "ZZZ"}

SEUIL_ECART_MEDIAN = 1.0  # point de % du PIB

# Ruptures de série connues. Les valeurs ne sont jamais modifiées : la rupture
# est déclarée dans portail.json pour que le portail interrompe les graphiques,
# n'évalue pas les critères à travers elle et l'explique.
#
# « etabli » : ce que les publications BCEAO citées affirment explicitement.
# « deduit »  : ce que l'Observatoire conclut en recoupant ces chiffres avec IMECO.
RUPTURES = [
    {
        "id": "dette_perimetre_2022",
        "indicateurs": ["dette_pib"],
        "serie_niveau": "FP3001A0FA",
        "zones": "toutes",
        "premiere_annee": 2022,
        "nature": "perimetre",
        "statut": "deduit",
        "etabli": [
            {
                "source": "BCEAO, Rapport sur la politique monétaire dans l'UMOA, mars 2023",
                "reference": "tableau 33",
                "url": "https://www.bceao.int/sites/default/files/2023-05/BCEAO%20-%20Rapport%20sur%20la%20politique%20mone%CC%81taire_Umoa_Mars_2023.pdf",
                "zone": "uemoa", "annee": 2021, "grandeur": "dette_publique_totale",
                "montant_mds_fcfa": 54845.5, "pct_pib": 54.8,
            },
            {
                "source": "BCEAO, Rapport annuel 2023",
                "reference": "tableau 6",
                "url": "https://www.bceao.int/sites/default/files/2024-09/Rapport_Annuel_2023_BCEAO_20092024.pdf",
                "annee": 2022, "grandeur": "dette_publique_exterieure",
                "pct_pib": {"benin": 37.4, "burkina": 26.0, "cote_ivoire": 34.4, "guinee_bissau": 35.3,
                            "mali": 28.6, "niger": 32.7, "senegal": 53.9, "togo": 25.4, "uemoa": 35.7},
            },
        ],
        "verifie_le": "2026-10-08",
    },
]
SEUIL_SAUT_RUPTURE = 1.4  # encours 1re année / année précédente


def controler_ruptures(par_code: dict[str, dict[int, float]]) -> None:
    """Vérifie que chaque rupture déclarée est toujours visible dans la série en niveau.

    Non bloquant : si la BCEAO révise ses séries, l'avertissement invite à
    réexaminer la déclaration plutôt qu'à la retirer en silence.
    """
    for r in RUPTURES:
        an = r["premiere_annee"]
        sauts = {}
        for z, zone in ZONES.items():
            niveau = par_code.get(z + r["serie_niveau"], {})
            if niveau.get(an) and niveau.get(an - 1):
                sauts[zone["id"]] = niveau[an] / niveau[an - 1]
        nb = sum(v >= SEUIL_SAUT_RUPTURE for v in sauts.values())
        etat = "présente" if sauts and nb >= len(sauts) / 2 else "À RÉEXAMINER"
        detail = ", ".join(f"{k} ×{v:.2f}" for k, v in sauts.items())
        print(f"  rupture {r['id']} ({an - 1}→{an}) : {etat} — {detail}")


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

    print("Contrôle des ruptures déclarées…")
    controler_ruptures(par_code)

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
            if ind.get("debut"):
                obs = {a: v for a, v in obs.items() if a >= ind["debut"]}
            niveau = par_code.get(z + ind["controle"], {}) if ind.get("controle") else {}
            zeros = [a for a, v in obs.items() if v == 0 and niveau.get(a)]
            if ind.get("groupe_zeros") == "contributions":
                # Les trois contributions à 0 alors que la croissance ne l'est pas : remplissage.
                freres = [par_code.get(z + i["suffixe"], {}) for i in INDICATEURS if i.get("groupe_zeros") == "contributions"]
                croissance = par_code.get(z + SUFFIXE_CROISSANCE, {})
                zeros = [a for a in obs if all(f.get(a) == 0 for f in freres) and croissance.get(a)]
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
            "ratio_controle": bool(ind.get("controle")),
            **({"debut_retenu": ind["debut"], "motif_debut": ind["motif_debut"]} if ind.get("debut") else {}),
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
        "ruptures": RUPTURES,
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
    anciens = set()
    if cible.exists():
        anciens = {i["id"] for i in json.loads(cible.read_text(encoding="utf-8")).get("indicateurs", [])}
    cible.write_text(json.dumps(portail, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  portail -> {cible} ({cible.stat().st_size // 1024} Ko)")

    # Journal : export des données et ruptures déclarées (une seule fois chacune).
    nouveaux = [i["id"] for i in indicateurs_meta if anciens and i["id"] not in anciens]
    if nouveaux:
        e = journal.evenement("serie", portail["generated_at"], "export_portail.py", indicateurs=nouveaux)
        if journal.enregistrer(e):
            print(f"  journal : {len(nouveaux)} nouvelle(s) série(s)")
    for e in journal.evenements_portail(portail):
        if journal.enregistrer(e):
            print(f"  journal : {e['id']}")
    journal.ecrire(journal.charger(), args.dest / "journal.json")
    print(f"  journal -> {args.dest / 'journal.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
