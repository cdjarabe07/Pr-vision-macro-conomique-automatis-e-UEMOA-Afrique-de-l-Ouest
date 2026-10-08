#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_dashboard.py
===================
Bloc 1 du hackathon — remplace la copie manuelle des données entre le pipeline
Python et le dashboard React.

Flux cible :
    previsions-macro-uemoa/data/processed/
        --> export_dashboard.py
        --> uemoa-dashboard/src/data/*.json
        --> React (import statique via indicateurs.js)

Fichiers générés (dans uemoa-dashboard/src/data/) :
    - inflation_senegal.json   (série [{period, value}] — consommée par indicateurs.js)
    - pib_senegal.json         (idem)
    - taux_change_uemoa.json   (idem)
    - previsions.json          (prévisions ARIMA + IC 95 %, années déduites de la
                                dernière observation — observatoire/modeles/prevision.py)
    - previsions_metriques.json (MAE modèle et naïf, ordre, période — idem)
    - comparaison_pays.json    (PIB + inflation, 4 pays — bloc 3)
    - meta.json                (horodatage + résumé de l'export)

Usage :
    python export_dashboard.py
    python export_dashboard.py --dest "C:/.../uemoa-dashboard/src/data"
    python export_dashboard.py --dry-run

Principes :
    - aucun chemin absolu propre à une machine (tout est relatif au script) ;
    - aucune donnée fictive : tout provient de data/processed/ ;
    - un fichier source manquant est signalé, jamais remplacé par un faux contenu ;
    - un JSON existant du frontend dont la structure serait différente n'est PAS
      écrasé (on le signale à la place).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Windows + sortie redirigée (>) : force l'UTF-8 sur stdout/stderr pour que
# les caractères non-ASCII (émojis, accents) n'étranglent pas la console.
# ---------------------------------------------------------------------------

for _flux in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _flux is not None and hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 1. Chemins robustes — relatifs à l'emplacement de ce script
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = PROJECT_ROOT / "data" / "processed"
DEFAULT_DEST = PROJECT_ROOT.parent / "uemoa-dashboard" / "src" / "data"

# Séries publiées sur la page "Données" du dashboard :
#   clé pipeline  ->  nom du fichier JSON attendu par le frontend (indicateurs.js)
SERIES = {
    "inflation_senegal": "inflation_senegal.json",
    "pib_senegal": "pib_senegal.json",
    "taux_change_uemoa": "taux_change_uemoa.json",
}

# Sources JSON déjà produites par le pipeline dans data/processed/,
# copiées telles quelles (structure stable) :
#   nom du fichier généré  ->  nom du fichier source
PASSTHROUGH = {
    "previsions.json": "previsions.json",
    "previsions_metriques.json": "previsions_metriques.json",
    "comparaison_pays.json": "comparaison_pays.json",
}


# ---------------------------------------------------------------------------
# 2. Outils d'écriture
# ---------------------------------------------------------------------------

def ecrire_json(chemin: Path, contenu, dry_run: bool, compact: bool = False) -> None:
    """Écrit un fichier JSON en UTF-8.

    - compact=True  : une ligne, sans indentation (format historique des
      séries du dashboard, produit à l'origine par le notebook).
    - compact=False : indenté et lisible (prévisions, comparaison, meta).
    """
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return
    if compact:
        with chemin.open("w", encoding="utf-8") as f:
            json.dump(contenu, f)
    else:
        with chemin.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(contenu, f, ensure_ascii=False, indent=2)
            f.write("\n")


def structure_serie(donnees) -> bool:
    """Retourne True si la structure correspond à [{period, value}, ...]."""
    return isinstance(donnees, list) and all(
        isinstance(d, dict) and "period" in d and "value" in d for d in donnees
    )


def cible_remplacable(cible: Path, valide_ok) -> bool:
    """Sécurité anti-destruction : on ne remplace un fichier existant que si
    on a validé sa structure. Retourne True si l'écriture est autorisée."""
    if not cible.exists():
        return True
    try:
        existant = json.loads(cible.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"  ⛔ {cible.name} : fichier existant illisible ({exc}) — non remplacé")
        return False
    if valide_ok(existant):
        return True
    print(
        f"  ⛔ {cible.name} : structure existante inattendue "
        f"({type(existant).__name__} de {len(existant)} éléments) — non remplacé"
    )
    return False


# ---------------------------------------------------------------------------
# 3. Export des séries (page "Données")
# ---------------------------------------------------------------------------

def exporter_serie(src_proc: Path, nom: str, dest: Path, dry_run: bool) -> int:
    """Génère le JSON [{period, value}] d'une série depuis son CSV de features."""
    chemin_csv = src_proc / f"{nom}_features.csv"
    cible = dest / SERIES[nom]

    if not chemin_csv.exists():
        print(f"  ⚠️  manquant : {chemin_csv.relative_to(PROJECT_ROOT)} — {nom} non exporté")
        return 0

    # Sélection stricte : uniquement les observations valides, triées par période.
    df = pd.read_csv(chemin_csv)
    df = df[["period", "value"]].dropna(subset=["value"]).sort_values("period")
    records = df.to_dict("records")

    if not cible_remplacable(cible, structure_serie):
        return 0

    ecrire_json(cible, records, dry_run, compact=True)
    suffixe = " [dry-run]" if dry_run else ""
    print(f"  ✅ {cible.name} — {len(records)} observations{suffixe}")
    return len(records)


# ---------------------------------------------------------------------------
# 4. Export pass-through (prévisions + comparaison pays)
# ---------------------------------------------------------------------------

def exporter_passthrough(src_proc: Path, cible_nom: str, dest: Path, dry_run: bool) -> int:
    """Copie un JSON déjà produit par le pipeline, sans en modifier la structure."""
    source_nom = PASSTHROUGH[cible_nom]
    chemin_src = src_proc / source_nom
    cible = dest / cible_nom

    if not chemin_src.exists():
        print(f"  ⚠️  manquant : {chemin_src.relative_to(PROJECT_ROOT)} — {cible_nom} non exporté")
        return 0

    try:
        contenu = json.loads(chemin_src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"  ⛔ {source_nom} : source illisible ({exc}) — {cible_nom} non exporté")
        return 0

    if not isinstance(contenu, list):
        print(f"  ⛔ {source_nom} : structure inattendue (liste attendue) — {cible_nom} non exporté")
        return 0

    if not cible_remplacable(cible, lambda d: isinstance(d, list)):
        return 0

    ecrire_json(cible, contenu, dry_run)
    suffixe = " [dry-run]" if dry_run else ""
    print(f"  ✅ {cible_nom} — {len(contenu)} enregistrements{suffixe}")
    return len(contenu)


# ---------------------------------------------------------------------------
# 5. Point d'entrée
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exporte data/processed/ du pipeline Python vers les JSON du dashboard React."
    )
    parser.add_argument(
        "--src", type=Path, default=DEFAULT_SRC,
        help="Répertoire source (défaut : data/processed à côté de ce script)",
    )
    parser.add_argument(
        "--dest", type=Path, default=DEFAULT_DEST,
        help="Répertoire destination (défaut : dossier frère uemoa-dashboard/src/data)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simule l'export sans rien écrire")
    args = parser.parse_args()

    src_proc = args.src.resolve()
    dest = args.dest.resolve()

    print("=" * 72)
    print("export_dashboard.py")
    print(f"Horodatage  : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Source      : {src_proc}")
    print(f"Destination : {dest}")
    print(f"Mode        : {'dry-run (aucune écriture)' if args.dry_run else 'écriture'}")
    print("=" * 72)

    if not src_proc.is_dir():
        print(f"\n❌ Répertoire source introuvable : {src_proc}")
        print("   Lancez le script depuis le projet 'previsions-macro-uemoa' "
              "ou précisez --src.")
        return 1

    # Export des 3 séries (page "Données")
    stats = {}
    for nom in SERIES:
        stats[SERIES[nom]] = exporter_serie(src_proc, nom, dest, args.dry_run)

    # Export pass-through : prévisions, métriques des modèles et comparaison pays
    for cible_nom in PASSTHROUGH:
        stats[cible_nom] = exporter_passthrough(src_proc, cible_nom, dest, args.dry_run)

    # Méta-information (horodatage + résumé), pour la traçabilité de l'export
    fichiers_exportes = {nom: nb for nom, nb in stats.items() if nb > 0}
    try:
        destination_rel = os.path.relpath(dest, PROJECT_ROOT)
    except ValueError:
        destination_rel = str(dest)
    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "data/processed",
        "destination": destination_rel,
        "files": fichiers_exportes,
    }
    ecrire_json(dest / "meta.json", meta, args.dry_run)
    if not args.dry_run:
        print("  ✅ meta.json — résumé de l'export")

    # Résumé final
    print("-" * 72)
    nb_fichiers = len(fichiers_exportes) + (0 if args.dry_run else 1)  # + meta.json
    print(
        f"Résumé : {nb_fichiers} fichier(s) JSON "
        f"{'seraient générés' if args.dry_run else 'générés'} "
        f"dans {dest}"
    )
    if args.dry_run:
        print("(dry-run — aucune écriture effectuée)")
    for nom in sorted(fichiers_exportes):
        print(f"   - {nom}")
    if len(fichiers_exportes) != len(stats):
        print("\n⚠️  Certains fichiers attendus n'ont pas pu être générés (voir messages ci-dessus).")
    return 0


if __name__ == "__main__":
    sys.exit(main())