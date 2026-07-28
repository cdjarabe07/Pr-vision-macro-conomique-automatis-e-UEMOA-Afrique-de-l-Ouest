# Ce fichier centralise tous les indicateurs qu'on veut suivre.
# Si on veut ajouter un indicateur plus tard, on l'ajoute ici, nulle part ailleurs.

INDICATEURS = {
    "inflation_senegal": {
        "dataset_code": "TAUXINFL_A",
        "series_code": "KKKSR3072A0BP",
        "description": "Taux d'inflation moyen annuel (IPC), Sénégal",
    },
    "taux_change_uemoa": {
        "dataset_code": "TC_A",
        "series_code": "ZZZSF3100A0GP",
        "description": "Taux de change XOF/USD, ensemble UMOA",
    },
    "pib_senegal": {
        "dataset_code": "PIBN",
        "series_code": "KKKSR1015A0BP",
        "description": "PIB nominal, Sénégal",
    },
}

PROVIDER = "BCEAO"