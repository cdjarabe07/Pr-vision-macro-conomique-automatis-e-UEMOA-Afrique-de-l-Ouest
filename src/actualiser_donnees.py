"""
Script d'actualisation automatique des données macroéconomiques UEMOA.
Récupère toutes les séries depuis DBnomics, applique le feature engineering,
et exporte les fichiers finaux dans data/processed/.
"""
import pathlib
from dbnomics import fetch_series
from features import construire_features  # adapte l'import selon ton organisation réelle

dossier_raw = pathlib.Path(__file__).parent.parent / "data" / "raw"
dossier_processed = pathlib.Path(__file__).parent.parent / "data" / "processed"

# Toutes les séries du projet, centralisées ici
SERIES = {
    "pib_senegal": "BCEAO/PIBN/KKKSR1015A0BP",
    "inflation_senegal": "BCEAO/TAUXINFL_A/KKKSR3072A0BP",
    "pib_cote_ivoire": "BCEAO/PIBN/AAASR1015A0BP",
    "inflation_cote_ivoire": "BCEAO/TAUXINFL_A/AAASR3072A0BP",
    "pib_burkina": "BCEAO/PIBN/CCCSR1015A0BP",
    "inflation_burkina": "BCEAO/TAUXINFL_A/CCCSR3072A0BP",
    "pib_mali": "BCEAO/PIBN/DDDSR1015A0BP",
    "inflation_mali": "BCEAO/TAUXINFL_A/DDDSR3072A0BP",
    "brent_oil_price": "IMF/PCPS/A.W00.POILBRE.USD",
}

def actualiser():
    print("Début de l'actualisation...")
    for nom, code in SERIES.items():
        try:
            df = fetch_series(code)
            df.to_csv(dossier_raw / f"{nom}.csv", index=False)
            print(f"  ✓ {nom} : {len(df)} lignes")
        except Exception as e:
            print(f"  ✗ {nom} a échoué : {e}")
    print("Actualisation terminée.")

if __name__ == "__main__":
    actualiser()