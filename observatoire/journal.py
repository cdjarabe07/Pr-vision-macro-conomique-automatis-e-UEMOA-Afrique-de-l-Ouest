"""
Journal des mises à jour de l'Observatoire.

Chaque script du pipeline enregistre ici ce qu'il vient réellement de produire
(date, type, indicateurs, chiffres de contrôle). Le journal ne contient aucun
texte éditorial : le portail rédige les phrases (FR/EN) à partir de ces champs.

Types d'événements :
    donnees     export des séries du portail (export_portail.py)
    previsions  recalcul des prévisions (observatoire.modeles.prevision)
    methode     changement méthodologique déclaré (ex. rupture de série)
    serie       ajout d'une série au portail
    analyse     publication d'une analyse validée

Fichier : data/processed/journal.json (liste, la plus récente en premier),
copié vers le portail par export_portail.py et export_dashboard.py.

Reconstitution à partir des fichiers déjà produits (dates lues dans ces fichiers) :
    python -m observatoire.journal --reconstituer
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOSSIER_PROCESSED = PROJECT_ROOT / "data" / "processed"
CHEMIN = DOSSIER_PROCESSED / "journal.json"
PORTAIL = PROJECT_ROOT.parent / "uemoa-dashboard" / "src" / "data" / "portail.json"

TYPES = ("donnees", "previsions", "methode", "serie", "analyse")


class ErreurJournal(ValueError):
    """Événement invalide : il n'est pas enregistré."""


def evenement(type_: str, date: str, source: str, *, id_: str | None = None,
              indicateurs: list[str] | None = None, zones: list[str] | None = None,
              details: dict | None = None) -> dict:
    """Construit un événement. date : ISO 8601 (AAAA-MM-JJ ou AAAA-MM-JJTHH:MM:SSZ)."""
    return {
        "id": id_ or f"{type_}:{date}",
        "type": type_,
        "date": date,
        "source": source,
        "indicateurs": indicateurs or [],
        "zones": zones or [],
        "details": details or {},
    }


def valider(e: dict) -> None:
    if e.get("type") not in TYPES:
        raise ErreurJournal(f"type inconnu : {e.get('type')!r}")
    date = e.get("date")
    try:
        datetime.fromisoformat(str(date).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ErreurJournal(f"date invalide : {date!r}") from exc
    for cle in ("id", "source"):
        if not e.get(cle):
            raise ErreurJournal(f"champ manquant : {cle}")


def charger(chemin: Path = CHEMIN) -> list[dict]:
    if not chemin.exists():
        return []
    return json.loads(chemin.read_text(encoding="utf-8"))


def ecrire(journal: list[dict], chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
        f.write("\n")


def enregistrer(e: dict, chemin: Path = CHEMIN) -> bool:
    """Ajoute l'événement s'il n'existe pas déjà (même id). Retourne True si ajouté."""
    valider(e)
    journal = charger(chemin)
    if any(x["id"] == e["id"] for x in journal):
        return False
    journal.append(e)
    journal.sort(key=lambda x: x["date"], reverse=True)
    ecrire(journal, chemin)
    return True


def evenements_portail(portail: dict, source: str = "export_portail.py") -> list[dict]:
    """Événements décrivant un portail.json : export des données, ruptures déclarées."""
    series = portail["series"]
    nb_obs = sum(len(v) for s in series.values() for v in s.values())
    fin = max(i["periode"][1] for i in portail["indicateurs"] if i.get("periode"))
    sortie = [evenement(
        "donnees", portail["generated_at"], source,
        indicateurs=[i["id"] for i in portail["indicateurs"]],
        zones=[z["id"] for z in portail["zones"]],
        details={"fournisseur": portail["source"], "observations": nb_obs, "derniere_annee": fin},
    )]
    for r in portail.get("ruptures", []):
        sortie.append(evenement(
            "methode", r["verifie_le"], source, id_=f"methode:{r['id']}",
            indicateurs=r["indicateurs"],
            details={"nature": "rupture", "rupture": r["id"], "premiere_annee": r["premiere_annee"], "statut": r["statut"]},
        ))
    return sortie


def evenement_previsions(metriques: list[dict], source: str = "observatoire.modeles.prevision") -> dict:
    """Événement décrivant un recalcul des prévisions (dates lues dans les métriques)."""
    publiees = [m for m in metriques if m.get("publie")]
    return evenement(
        "previsions", metriques[0]["date_entrainement"], source,
        indicateurs=[m["indicateur"] for m in publiees],
        zones=sorted({m["pays"] for m in publiees}),
        details={
            "premiere_annee": min(m["premiere_annee_prevision"] for m in publiees),
            "derniere_annee": max(m["derniere_annee_prevision"] for m in publiees),
            "derniere_observation": max(m["derniere_observation"] for m in publiees),
        },
    )


def reconstituer(chemin: Path = CHEMIN, portail: Path = PORTAIL,
                 metriques: Path = DOSSIER_PROCESSED / "previsions_metriques.json") -> list[str]:
    """Enregistre les événements correspondant aux fichiers déjà produits."""
    ajoutes = []
    if portail.exists():
        for e in evenements_portail(json.loads(portail.read_text(encoding="utf-8"))):
            if enregistrer(e, chemin):
                ajoutes.append(e["id"])
    if metriques.exists():
        e = evenement_previsions(json.loads(metriques.read_text(encoding="utf-8")))
        if enregistrer(e, chemin):
            ajoutes.append(e["id"])
    return ajoutes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Journal des mises à jour de l'Observatoire.")
    parser.add_argument("--reconstituer", action="store_true", help="enregistre les événements des fichiers déjà produits")
    args = parser.parse_args(argv)
    if args.reconstituer:
        for i in reconstituer():
            print(f"  ajouté : {i}")
    for e in charger():
        print(f"  {e['date']}  {e['type']:<10} {e['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
