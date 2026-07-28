import streamlit as st
import pandas as pd
from pathlib import Path
from statsmodels.tsa.statespace.sarimax import SARIMAX
import warnings
warnings.filterwarnings("ignore")

st.title("Prévision macroéconomique — UEMOA")

dossier = Path("data/processed")
df_inflation = pd.read_csv(dossier / "inflation_senegal_features.csv")
df_taux_change = pd.read_csv(dossier / "taux_change_uemoa_features.csv")
df_pib = pd.read_csv(dossier / "pib_senegal_features.csv")

# Configuration par indicateur : quel dataset, quel ordre SARIMA optimal, quel MAE
CONFIG_INDICATEURS = {
    "Inflation (Sénégal)": {"df": df_inflation, "ordre": (1, 1, 2), "mae": 1.42},
    "Taux de change (FCFA pour 1 USD)": {"df": df_taux_change, "ordre": (1, 0, 0), "mae": 28.45},
    "PIB (Sénégal)": {"df": df_pib, "ordre": (2, 1, 0), "mae": 361.61},
}

indicateur_choisi = st.selectbox("Choisir un indicateur", list(CONFIG_INDICATEURS.keys()))
config = CONFIG_INDICATEURS[indicateur_choisi]
df = config["df"]

# On entraîne le modèle sur toute la série disponible et on prédit l'année suivante
modele = SARIMAX(df["value"], order=config["ordre"])
resultat = modele.fit(disp=False)
prevision = resultat.forecast(steps=1).iloc[0]

derniere_annee = pd.to_datetime(df["period"]).dt.year.max()

col1, col2 = st.columns(2)
col1.metric(f"Prévision {derniere_annee + 1}", round(prevision, 2))
col2.metric("Précision du modèle (MAE)", config["mae"])

st.line_chart(df.set_index("period")["value"])

st.subheader("Dernières valeurs")
st.dataframe(df[["period", "value"]].tail(10))