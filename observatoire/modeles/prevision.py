#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
observatoire.modeles.prevision
==============================
Production reproductible des prévisions publiées par l'Observatoire.

Remplace l'exécution manuelle du notebook 03_modelisation.ipynb pour la
production. La méthode est strictement celle du notebook (aucun changement
statistique) :

    - modèle ARIMA(p, d, q), estimé avec statsmodels.SARIMAX sans composante
      saisonnière (données annuelles) ;
    - ordres retenus dans le notebook (recherche sur grille p∈{0,1,2},
      d∈{0,1}, q∈{0,1,2}) ;
    - validation glissante à un pas sur les 10 dernières années, comparée à un
      modèle naïf (dernière valeur connue) ;
    - prévision sur 2 ans avec intervalle de confiance analytique à 95 %.

Les années de prévision sont déduites de la dernière observation : aucune
année n'est codée en dur.

Fichiers produits (data/processed/) :
    previsions.json             une ligne par indicateur × année prévue
    previsions_metriques.json   une ligne par indicateur (MAE, ordre, période…)

Le dashboard les reçoit via export_dashboard.py.

Usage (depuis la racine du projet) :
    python -m observatoire.modeles.prevision
    python -m observatoire.modeles.prevision --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

for _flux in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _flux is not None and hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOSSIER_PROCESSED = PROJECT_ROOT / "data" / "processed"

# Paramètres de la méthode (identiques au notebook 03_modelisation.ipynb).
HORIZON = 2                 # nombre d'années prévues après la dernière observation
NB_ANNEES_VALIDATION = 10   # fenêtre de validation glissante
HORIZON_VALIDATION = 1      # la validation mesure l'erreur de prévision à un pas
NIVEAU_CONFIANCE = 0.95
MODELE = "ARIMA"
ESTIMATION = "statsmodels.tsa.statespace.SARIMAX, sans composante saisonnière"
SOURCE = "BCEAO via DBnomics"


@dataclass(frozen=True)
class SeriePrevue:
    indicateur: str       # identifiant utilisé par le dashboard
    pays: str
    fichier: str          # CSV dans data/processed/
    ordre: tuple          # (p, d, q) retenu dans le notebook
    serie_source: str     # identifiant DBnomics de la série historique
    publier: bool = True  # False : métriques exportées, prévision non publiée
    motif_non_publication: str | None = None


SERIES = [
    SeriePrevue("pib", "senegal", "pib_senegal_features.csv", (2, 1, 0), "BCEAO/PIBN/KKKSR1015A0BP"),
    SeriePrevue("inflation", "senegal", "inflation_senegal_features.csv", (1, 1, 2), "BCEAO/TAUXINFL_A/KKKSR3072A0BP"),
    SeriePrevue("agriculture", "senegal", "secteur_agriculture_senegal_features.csv", (1, 1, 1), "BCEAO/PIBN/KKKSR1038A0BP"),
    SeriePrevue("industrie", "senegal", "secteur_industrie_senegal_features.csv", (1, 1, 1), "BCEAO/PIBN/KKKSR1039A0BP"),
    SeriePrevue("services", "senegal", "secteur_services_senegal_features.csv", (2, 1, 2), "BCEAO/PIBN/KKKSR1040A0BP"),
    SeriePrevue("masse_monetaire", "senegal", "masse_monetaire_senegal_features.csv", (2, 0, 0), "BCEAO/AM_A/KKKSF1412A0AP"),
    SeriePrevue(
        "taux_change", "umoa", "taux_change_uemoa_features.csv", (1, 0, 0), "BCEAO/TC_A/ZZZSF3100A0GP",
        publier=False,
        motif_non_publication="marche aléatoire : le modèle ne fait pas mieux que la dernière valeur connue",
    ),
]


class ErreurControle(RuntimeError):
    """Un contrôle de cohérence a échoué : aucun fichier n'est écrit."""


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------

def charger_serie(chemin: Path) -> pd.DataFrame:
    """Charge une série annuelle {annee, valeur} et vérifie sa structure."""
    if not chemin.exists():
        raise ErreurControle(f"série introuvable : {chemin}")
    df = pd.read_csv(chemin)
    df = df[df["value"].notna()].copy()
    df["annee"] = pd.to_datetime(df["period"]).dt.year
    df = df[["annee", "value"]].rename(columns={"value": "valeur"}).reset_index(drop=True)
    controler_historique(df, chemin.name)
    return df


def controler_historique(df: pd.DataFrame, nom: str) -> None:
    """Historique chronologique, sans doublon, sans trou, sans valeur infinie."""
    if len(df) <= NB_ANNEES_VALIDATION + 1:
        raise ErreurControle(f"{nom} : {len(df)} observations, trop peu pour la validation glissante")
    annees = df["annee"].tolist()
    if annees != sorted(annees):
        raise ErreurControle(f"{nom} : historique non chronologique")
    if len(set(annees)) != len(annees):
        raise ErreurControle(f"{nom} : années en double dans l'historique")
    if annees != list(range(annees[0], annees[-1] + 1)):
        raise ErreurControle(f"{nom} : années manquantes dans l'historique")
    if not all(math.isfinite(v) for v in df["valeur"]):
        raise ErreurControle(f"{nom} : valeur non finie dans l'historique")


def annees_prevision(derniere_observation: int, horizon: int = HORIZON) -> list[int]:
    """Années prévues : les `horizon` années qui suivent la dernière observation."""
    if horizon < 1:
        raise ValueError("l'horizon doit être au moins égal à 1")
    return list(range(derniere_observation + 1, derniere_observation + 1 + horizon))


# ---------------------------------------------------------------------------
# Modèle (méthode du notebook, inchangée)
# ---------------------------------------------------------------------------

def _ajuster(valeurs: pd.Series, ordre: tuple):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return SARIMAX(valeurs, order=ordre).fit(disp=False)


def validation_glissante(valeurs: pd.Series, ordre: tuple, nb_annees: int = NB_ANNEES_VALIDATION) -> dict:
    """MAE à un pas du modèle et du naïf sur les `nb_annees` dernières années.

    Pour chaque année testée, le modèle n'est estimé que sur les années
    strictement antérieures (contrôle explicite contre la fuite de données).
    """
    erreurs_modele, erreurs_naif = [], []
    n = len(valeurs)
    for i in range(nb_annees, 0, -1):
        position_test = n - i
        train = valeurs.iloc[:position_test]
        if len(train) != position_test or train.index.max() >= valeurs.index[position_test]:
            raise ErreurControle("fuite de données : l'entraînement contient l'année testée")
        reel = valeurs.iloc[position_test]
        prevu = _ajuster(train, ordre).forecast(steps=1).iloc[0]
        erreurs_modele.append(abs(prevu - reel))
        erreurs_naif.append(abs(train.iloc[-1] - reel))
    return {
        "mae": sum(erreurs_modele) / len(erreurs_modele),
        "mae_naif": sum(erreurs_naif) / len(erreurs_naif),
    }


def prevoir(valeurs: pd.Series, ordre: tuple, horizon: int = HORIZON, niveau: float = NIVEAU_CONFIANCE):
    """Prévision centrale et intervalle de confiance, modèle estimé sur tout l'historique."""
    resultat = _ajuster(valeurs, ordre).get_forecast(steps=horizon)
    bornes = resultat.conf_int(alpha=1 - niveau)
    return (
        resultat.predicted_mean.tolist(),
        bornes.iloc[:, 0].tolist(),
        bornes.iloc[:, 1].tolist(),
    )


# ---------------------------------------------------------------------------
# Contrôles avant export
# ---------------------------------------------------------------------------

def controler_previsions(previsions: list[dict], metriques: list[dict], horizon: int = HORIZON) -> None:
    """Échoue explicitement si les sorties sont incohérentes."""
    attendus = {s.indicateur for s in SERIES if s.publier}
    derniere = {m["indicateur"]: m["derniere_observation"] for m in metriques}

    par_indicateur: dict[str, list[dict]] = {}
    for p in previsions:
        par_indicateur.setdefault(p["indicateur"], []).append(p)

    manquants = attendus - set(par_indicateur)
    if manquants:
        raise ErreurControle(f"prévisions manquantes : {sorted(manquants)}")
    inattendus = set(par_indicateur) - attendus
    if inattendus:
        raise ErreurControle(f"prévisions non attendues : {sorted(inattendus)}")

    for ind, lignes in par_indicateur.items():
        annees = [p["annee"] for p in lignes]
        if len(lignes) != horizon:
            raise ErreurControle(f"{ind} : {len(lignes)} prévisions au lieu de {horizon}")
        if min(annees) <= derniere[ind]:
            raise ErreurControle(f"{ind} : année prévue {min(annees)} ≤ dernière observation {derniere[ind]}")
        if annees != list(range(derniere[ind] + 1, derniere[ind] + 1 + horizon)):
            raise ErreurControle(f"{ind} : années prévues non consécutives après {derniere[ind]} : {annees}")
        for p in lignes:
            valeurs = (p["valeur_prevue"], p["borne_basse"], p["borne_haute"])
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in valeurs):
                raise ErreurControle(f"{ind} {p['annee']} : valeur NaN ou infinie")
            if not p["borne_basse"] <= p["valeur_prevue"] <= p["borne_haute"]:
                raise ErreurControle(f"{ind} {p['annee']} : prévision hors de son intervalle de confiance")

    for m in metriques:
        for cle in ("mae", "mae_naif"):
            if not (isinstance(m[cle], (int, float)) and math.isfinite(m[cle]) and m[cle] >= 0):
                raise ErreurControle(f"{m['indicateur']} : métrique {cle} invalide ({m[cle]})")


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------

def produire(dossier: Path = DOSSIER_PROCESSED, maintenant: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Calcule prévisions et métriques pour toutes les séries configurées."""
    maintenant = maintenant or datetime.now(timezone.utc)
    date_generation = maintenant.strftime("%Y-%m-%dT%H:%M:%SZ")
    previsions, metriques = [], []

    for s in SERIES:
        df = charger_serie(dossier / s.fichier)
        valeurs = df["valeur"]
        derniere_observation = int(df["annee"].iloc[-1])
        annees = annees_prevision(derniere_observation)
        validation = validation_glissante(valeurs, s.ordre)
        ordre_txt = "({},{},{})".format(*s.ordre)

        metriques.append({
            "indicateur": s.indicateur,
            "pays": s.pays,
            "modele": MODELE,
            "estimation": ESTIMATION,
            "ordre": ordre_txt,
            "horizon_validation": HORIZON_VALIDATION,
            "nb_annees_validation": NB_ANNEES_VALIDATION,
            "mae": round(validation["mae"], 4),
            "mae_naif": round(validation["mae_naif"], 4),
            "date_entrainement": date_generation,
            "premiere_observation": int(df["annee"].iloc[0]),
            "derniere_observation": derniere_observation,
            "nb_observations": len(df),
            "premiere_annee_prevision": annees[0] if s.publier else None,
            "derniere_annee_prevision": annees[-1] if s.publier else None,
            "publie": s.publier,
            "motif_non_publication": s.motif_non_publication,
            "source": SOURCE,
            "serie_source": s.serie_source,
        })

        if not s.publier:
            continue
        centrales, basses, hautes = prevoir(valeurs, s.ordre)
        for annee, centrale, basse, haute in zip(annees, centrales, basses, hautes):
            previsions.append({
                "indicateur": s.indicateur,
                "pays": s.pays,
                "annee": annee,
                "valeur_prevue": round(centrale, 2),
                "borne_basse": round(basse, 2),
                "borne_haute": round(haute, 2),
                "niveau_confiance": NIVEAU_CONFIANCE,
                "derniere_observation": derniere_observation,
                "premiere_annee_prevision": annees[0],
                "derniere_annee_prevision": annees[-1],
                "modele": MODELE,
                "ordre": ordre_txt,
                "mae": round(validation["mae"], 4),
                "date_generation": date_generation,
                "source": SOURCE,
                "serie_source": s.serie_source,
            })

    controler_previsions(previsions, metriques)
    return previsions, metriques


def ecrire(chemin: Path, contenu) -> None:
    with chemin.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(contenu, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produit les prévisions et métriques publiées par l'Observatoire.")
    parser.add_argument("--dossier", type=Path, default=DOSSIER_PROCESSED, help="data/processed (entrée et sortie)")
    parser.add_argument("--dry-run", action="store_true", help="calcule et contrôle sans écrire")
    args = parser.parse_args(argv)

    try:
        previsions, metriques = produire(args.dossier)
    except ErreurControle as exc:
        print(f"ÉCHEC : {exc}. Aucun fichier écrit.")
        return 1

    for m in metriques:
        periode = (
            f"{m['premiere_annee_prevision']}–{m['derniere_annee_prevision']}"
            if m["publie"] else "non publiée"
        )
        print(
            f"  {m['indicateur']:<16} {m['modele']}{m['ordre']}  "
            f"dernière obs. {m['derniere_observation']}  prévision {periode:<11} "
            f"MAE {m['mae']:.2f} (naïf {m['mae_naif']:.2f})"
        )
    print(f"{len(previsions)} prévisions, {len(metriques)} jeux de métriques — contrôles OK")

    if args.dry_run:
        print("--dry-run : aucun fichier écrit.")
        return 0
    ecrire(args.dossier / "previsions.json", previsions)
    ecrire(args.dossier / "previsions_metriques.json", metriques)
    print(f"Écrit : {args.dossier / 'previsions.json'}")
    print(f"Écrit : {args.dossier / 'previsions_metriques.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
