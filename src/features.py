def construire_features(df):
    """Nettoie une série et ajoute les features standards : lag, moyenne mobile, variation."""
    df_propre = df[df['value'].notna()].copy()
    df_propre = df_propre.sort_values('period').reset_index(drop=True)
    df_propre['value_lag1'] = df_propre['value'].shift(1)
    df_propre['value_moy_mobile_3'] = df_propre['value'].rolling(window=3).mean()
    df_propre['value_variation_points'] = df_propre['value'].diff()
    return df_propre