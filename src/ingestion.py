# Ce script récupère tous les indicateurs définis dans config.py
# et les sauvegarde localement dans data/raw/, avec un horodatage de collecte.

from datetime import datetime
from pathlib import Path

from dbnomics import fetch_series

from config import INDICATEURS, PROVIDER


def recuperer_un_indicateur(nom, infos):
    """Récupère une série et l'enrichit avec des métadonnées utiles."""
    # On construit l'identifiant complet attendu par dbnomics
    id_serie = f"{PROVIDER}/{infos['dataset_code']}/{infos['series_code']}"
    print(f"Récupération de {nom} ({id_serie})...")

    df = fetch_series(id_serie)

    # On ne garde que les colonnes utiles, pour un fichier propre
    df = df[["period", "value"]].copy()
    df["indicateur"] = nom
    df["description"] = infos["description"]

    return df


def sauvegarder(df, nom, dossier_sortie):
    """Sauvegarde un DataFrame en CSV avec la date de collecte dans le nom du fichier."""
    date_collecte = datetime.now().strftime("%Y-%m-%d")
    chemin = dossier_sortie / f"{nom}_{date_collecte}.csv"
    df.to_csv(chemin, index=False)
    print(f"  -> sauvegardé dans {chemin}")


def run():
    """Récupère et sauvegarde tous les indicateurs définis dans config.py."""
    dossier_sortie = Path(__file__).parent.parent / "data" / "raw"
    dossier_sortie.mkdir(parents=True, exist_ok=True)

    for nom, infos in INDICATEURS.items():
        df = recuperer_un_indicateur(nom, infos)
        sauvegarder(df, nom, dossier_sortie)


if __name__ == "__main__":
    run()