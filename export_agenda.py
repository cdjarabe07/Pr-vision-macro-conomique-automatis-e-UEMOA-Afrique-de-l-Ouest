#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_agenda.py
================
Agenda institutionnel du portail : événements annoncés par les institutions,
à venir et passés, chacun avec le lien vers sa page officielle.

Sources :
    - BCEAO, page « Événements » (https://www.bceao.int/fr/evenements) :
      réunions du Comité de politique monétaire, sessions du Conseil des
      ministres de l'Union, présentation du rapport annuel, conférences.
      La page est lue telle quelle : date, titre, lien, description.
    - data/agenda_international.json : événements du FMI et de la Banque
      mondiale, saisis à partir de leur annonce officielle (lien et date de
      vérification obligatoires).

Aucune date n'est déduite d'un rythme habituel : seuls les événements
annoncés figurent. Arrêt sans écriture si la page de la BCEAO ne donne aucun
événement (structure modifiée).

Fichier produit :
    uemoa-dashboard/src/data/agenda.json

Usage :
    python export_agenda.py [--dry-run]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

for _flux in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _flux is not None and hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DEST = PROJECT_ROOT.parent / "uemoa-dashboard" / "src" / "data"
INTERNATIONAL = PROJECT_ROOT / "data" / "agenda_international.json"
BCEAO = "https://www.bceao.int"
PAGES_BCEAO = [f"{BCEAO}/fr/evenements", f"{BCEAO}/fr/evenements?page=1"]
MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
HISTORIQUE_JOURS = 400  # événements passés conservés

BLOC = re.compile(
    r'<time[^>]*>\s*(?P<date>[^<]+?)\s*</time>.*?<div class="ttr"><a href="(?P<url>[^"]+)"[^>]*>(?P<titre>[^<]+)</a></div>'
    r'\s*<div class="desc">(?P<desc>.*?)</div>',
    re.S,
)


class ErreurControle(ValueError):
    pass


def date_fr(texte: str) -> date:
    """« 27 Mars 2026 » -> date(2026, 3, 27)."""
    m = re.fullmatch(r"(\d{1,2})\s+([^\s]+)\s+(\d{4})", texte.strip())
    if not m or m.group(2).lower() not in MOIS:
        raise ErreurControle(f"date illisible : {texte!r}")
    return date(int(m.group(3)), MOIS[m.group(2).lower()], int(m.group(1)))


def type_bceao(titre: str) -> str:
    t = titre.lower()
    if "politique monétaire" in t or "politique monetaire" in t:
        return "cpm"
    if "conseil des ministres" in t:
        return "conseil_ministres"
    if "rapport annuel" in t:
        return "rapport_annuel"
    return "autre"


def lire_page(url: str) -> str:
    requete = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Observatoire UEMOA)"})
    for essai in range(3):
        try:
            with urllib.request.urlopen(requete, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except OSError as exc:
            if essai == 2:
                raise ErreurControle(f"{url} injoignable ({exc})") from exc
            time.sleep(5 * (essai + 1))
    return ""


def extraire_bceao(page: str) -> list[dict]:
    """Événements d'une page de liste de la BCEAO (blocs date / titre / lien / description)."""
    sortie = []
    for m in BLOC.finditer(page):
        if "/evenement/" not in m.group("url"):
            continue
        d = date_fr(html.unescape(m.group("date")))
        titre = html.unescape(m.group("titre")).strip()
        desc = html.unescape(re.sub(r"<[^>]+>", " ", m.group("desc"))).strip()
        url = m.group("url") if m.group("url").startswith("http") else BCEAO + m.group("url")
        sortie.append({
            "id": "bceao-" + url.rstrip("/").rsplit("/", 1)[-1],
            "date": d.isoformat(),
            "institution": "BCEAO",
            "type": type_bceao(titre),
            "titre": {"fr": titre},
            "description": {"fr": re.sub(r"\s+", " ", desc)} if desc else None,
            "url": url,
        })
    return sortie


def recuperer_bceao() -> list[dict]:
    vus, evenements = set(), []
    for url in PAGES_BCEAO:
        for e in extraire_bceao(lire_page(url)):
            if e["id"] not in vus:
                vus.add(e["id"])
                evenements.append(e)
    if not evenements:
        raise ErreurControle("aucun événement lu sur la page de la BCEAO (structure modifiée ?)")
    return evenements


def charger_international(chemin: Path = INTERNATIONAL) -> list[dict]:
    if not chemin.exists():
        return []
    evenements = json.loads(chemin.read_text(encoding="utf-8"))
    for e in evenements:
        for cle in ("id", "date", "institution", "type", "titre", "url", "verifie_le"):
            if not e.get(cle):
                raise ErreurControle(f"agenda international, {e.get('id')} : champ manquant {cle}")
        date.fromisoformat(e["date"])
    return evenements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    maintenant = datetime.now(timezone.utc)
    print("Lecture de l'agenda de la BCEAO…")
    try:
        bceao = recuperer_bceao()
        international = charger_international()
    except ErreurControle as exc:
        print(f"ARRÊT : {exc}. Aucun fichier écrit.")
        return 1

    limite = maintenant.date().toordinal() - HISTORIQUE_JOURS
    evenements = [e for e in bceao + international if date.fromisoformat(e.get("date_fin") or e["date"]).toordinal() >= limite]
    evenements.sort(key=lambda e: e["date"], reverse=True)
    for e in evenements:
        print(f"  {e['date']}  {e['institution']:<22} {e['titre']['fr'][:70]}")

    sortie = {
        "generated_at": maintenant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {"institution": "BCEAO", "titre": "BCEAO, Événements", "url": PAGES_BCEAO[0]},
            {"institution": "FMI · Banque mondiale", "titre": "Annonces officielles, vérifiées à la main", "url": None},
        ],
        "evenements": evenements,
    }
    if args.dry_run:
        print("--dry-run : aucun fichier écrit.")
        return 0
    cible = args.dest / "agenda.json"
    cible.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  agenda -> {cible} ({len(evenements)} événements)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
