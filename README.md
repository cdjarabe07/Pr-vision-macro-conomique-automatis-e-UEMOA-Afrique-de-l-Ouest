# Prévision macroéconomique UEMOA

Pipeline data science de bout en bout : collecte, modélisation et visualisation de 3 indicateurs macroéconomiques ouest-africains (inflation, taux de change, PIB).

## Pourquoi ce projet
Peu de projets data science publics traitent de données BCEAO/UEMOA. Ce pipeline montre une approche complète : ingestion automatisée, feature engineering, comparaison rigoureuse de modèles (naïf vs ARIMA), et dashboard interactif.

## Indicateurs suivis
| Indicateur | Source | Historique |
|---|---|---|
| Inflation (Sénégal) | BCEAO via DBnomics | 1998-2024 |
| Taux de change XOF/USD (UMOA) | BCEAO via DBnomics | 1960-2024 |
| PIB nominal (Sénégal) | BCEAO via DBnomics | 1960-2024 |

## Résultats clés
| Indicateur | MAE naïf | MAE ARIMA retenu |
|---|---|---|
| Inflation | 2.37 | 1.42 |
| Taux de change | 28.47 | 28.45 (marche aléatoire confirmée) |
| PIB | 1059.06 | 361.61 |

## Structure du projet
- src/ : code réutilisable (config, ingestion, features)
- notebooks/ : exploration et modélisation
- data/raw/ : données brutes collectées
- data/processed/ : données enrichies
- dashboard.py : dashboard Streamlit (prototype)

## Utilisation
1. pip install -r requirements.txt
2. python src/ingestion.py
3. python -m observatoire.modeles.prevision   (prévisions + métriques → data/processed/)
4. python export_dashboard.py                 (copie vers uemoa-dashboard/src/data/)
5. python -m unittest discover -s tests -v    (tests du module de prévision)

## Modèle de prévision
ARIMA(p, d, q) estimé avec `statsmodels.SARIMAX` sans composante saisonnière (données
annuelles). Les années prévues sont les deux qui suivent la dernière observation
disponible ; elles ne sont jamais codées en dur. Les MAE (validation glissante à un pas
sur 10 ans) sont exportées dans `data/processed/previsions_metriques.json`.

## Limites connues
- Peu de données pour l'inflation (27 ans) : modèles simples privilégiés
- Le taux de change suit une marche aléatoire, difficile à prévoir par nature