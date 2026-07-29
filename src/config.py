# Ce fichier centralise tous les indicateurs qu'on veut suivre.
# Si on veut ajouter un indicateur plus tard, on l'ajoute ici, nulle part ailleurs.

INDICATEURS = {"masse_monetaire_senegal": {
        "dataset_code": "AM_A",
        "series_code": "KKKSF1412A0AP",
        "description": "Masse monétaire (M2), Sénégal",
    },
    "reserves_change_senegal": {
        "dataset_code": "SIM",
        "series_code": "KKKSF1253A0AP",
        "description": "Réserves de change (avoirs extérieurs nets), Sénégal — historique jusqu'en 2015, non actualisé depuis",
    },
    "balance_commerciale_senegal": {
        "dataset_code": "BDP4",
        "series_code": "KKKSE1010A0AP",
        "description": "Balance commerciale, Sénégal",
    },
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
    "secteur_agriculture_senegal": {
        "dataset_code": "PIBN",
        "series_code": "KKKSR1038A0BP",
        "description": "PIB - Agriculture, élevage, sylviculture, pêche, Sénégal",
    },
    "secteur_industrie_senegal": {
        "dataset_code": "PIBN",
        "series_code": "KKKSR1039A0BP",
        "description": "PIB - Industrie, mines, énergie, BTP, Sénégal",
    },
    "secteur_services_senegal": {
        "dataset_code": "PIBN",
        "series_code": "KKKSR1040A0BP",
        "description": "PIB - Services, Sénégal",
    },
}

PROVIDER = "BCEAO"