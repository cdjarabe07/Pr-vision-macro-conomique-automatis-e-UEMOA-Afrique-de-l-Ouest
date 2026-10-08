"""
Tests du module de prévision.

Lancement (depuis la racine du projet) :
    python -m unittest discover -s tests -v
"""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from observatoire.modeles import prevision as P


def preparer_series(dossier: Path, decalage: int = 0, couper_apres: int | None = None) -> None:
    """Copie de test des vraies séries de data/processed/ (jamais publiée).

    decalage    : ajoute n années à chaque période (simule une mise à jour des données) ;
    couper_apres: retire les observations postérieures à cette année.
    """
    for s in P.SERIES:
        df = pd.read_csv(P.DOSSIER_PROCESSED / s.fichier)
        annees = pd.to_datetime(df["period"]).dt.year
        if couper_apres is not None:
            df, annees = df[annees <= couper_apres], annees[annees <= couper_apres]
        df = df.assign(period=[f"{a + decalage}-01-01" for a in annees])
        df.to_csv(dossier / s.fichier, index=False)


def prevision_type(indicateur="pib", annee=2025, derniere=2024, centrale=10.0, basse=9.0, haute=11.0):
    return {
        "indicateur": indicateur,
        "annee": annee,
        "valeur_prevue": centrale,
        "borne_basse": basse,
        "borne_haute": haute,
        "derniere_observation": derniere,
    }


def jeu_valide(derniere=2024):
    """Prévisions et métriques minimales cohérentes pour tous les indicateurs publiés."""
    previsions, metriques = [], []
    for s in P.SERIES:
        metriques.append({"indicateur": s.indicateur, "derniere_observation": derniere, "mae": 1.0, "mae_naif": 2.0})
        if s.publier:
            for annee in P.annees_prevision(derniere):
                previsions.append(prevision_type(s.indicateur, annee, derniere))
    return previsions, metriques


class AnneesPrevision(unittest.TestCase):
    def test_derniere_observation_2024(self):
        self.assertEqual(P.annees_prevision(2024), [2025, 2026])

    def test_derniere_observation_2025(self):
        self.assertEqual(P.annees_prevision(2025), [2026, 2027])

    def test_horizon_variable(self):
        self.assertEqual(P.annees_prevision(2024, horizon=3), [2025, 2026, 2027])

    def test_horizon_invalide(self):
        with self.assertRaises(ValueError):
            P.annees_prevision(2024, horizon=0)

    def test_aucune_annee_codee_en_dur(self):
        source = Path(P.__file__).read_text(encoding="utf-8")
        for annee in ("2025", "2026", "2027"):
            self.assertNotIn(annee, source, f"année {annee} codée en dur dans prevision.py")


class ProductionDeBoutEnBout(unittest.TestCase):
    """Les années prévues suivent toujours la dernière observation des données."""

    def _produire(self, **options):
        with tempfile.TemporaryDirectory() as tmp:
            preparer_series(Path(tmp), **options)
            return P.produire(Path(tmp))

    def _verifier(self, previsions, metriques, derniere, attendues):
        self.assertEqual(sorted({p["annee"] for p in previsions}), attendues)
        for p in previsions:
            self.assertEqual(p["derniere_observation"], derniere)
            self.assertEqual((p["premiere_annee_prevision"], p["derniere_annee_prevision"]), tuple(attendues))
            self.assertLessEqual(p["borne_basse"], p["valeur_prevue"])
            self.assertLessEqual(p["valeur_prevue"], p["borne_haute"])
            self.assertEqual(p["niveau_confiance"], 0.95)
        attendus = {s.indicateur for s in P.SERIES if s.publier}
        self.assertEqual({p["indicateur"] for p in previsions}, attendus)
        for ind in attendus:
            self.assertEqual(sum(p["indicateur"] == ind for p in previsions), P.HORIZON)
        champs = {"indicateur", "pays", "modele", "ordre", "horizon_validation", "mae", "mae_naif",
                  "date_entrainement", "derniere_observation"}
        self.assertEqual(len(metriques), len(P.SERIES))
        for m in metriques:
            self.assertTrue(champs <= set(m), f"champs manquants : {champs - set(m)}")
            self.assertEqual(m["modele"], "ARIMA")
            self.assertEqual(m["derniere_observation"], derniere)

    def test_donnees_jusqu_en_2023(self):
        self._verifier(*self._produire(couper_apres=2023), derniere=2023, attendues=[2024, 2025])

    def test_donnees_jusqu_en_2025(self):
        self._verifier(*self._produire(decalage=1), derniere=2025, attendues=[2026, 2027])


class Controles(unittest.TestCase):
    def test_jeu_valide_accepte(self):
        P.controler_previsions(*jeu_valide())

    def _doit_echouer(self, modifier):
        previsions, metriques = jeu_valide()
        previsions = copy.deepcopy(previsions)
        modifier(previsions, metriques)
        with self.assertRaises(P.ErreurControle):
            P.controler_previsions(previsions, metriques)

    def test_annee_egale_derniere_observation(self):
        def modifier(prev, _):
            for p in prev:
                p["annee"] -= 1
        self._doit_echouer(modifier)

    def test_annees_non_consecutives(self):
        self._doit_echouer(lambda prev, _: prev[1].__setitem__("annee", prev[1]["annee"] + 1))

    def test_prevision_hors_intervalle(self):
        self._doit_echouer(lambda prev, _: prev[0].__setitem__("valeur_prevue", 99.0))

    def test_valeur_nan(self):
        self._doit_echouer(lambda prev, _: prev[0].__setitem__("borne_haute", math.nan))

    def test_valeur_infinie(self):
        self._doit_echouer(lambda prev, _: prev[0].__setitem__("valeur_prevue", math.inf))

    def test_indicateur_manquant(self):
        def modifier(prev, _):
            prev[:] = [p for p in prev if p["indicateur"] != "pib"]
        self._doit_echouer(modifier)

    def test_nombre_de_previsions_incorrect(self):
        self._doit_echouer(lambda prev, _: prev.pop())

    def test_metrique_invalide(self):
        self._doit_echouer(lambda _, met: met[0].__setitem__("mae", math.nan))


class Historique(unittest.TestCase):
    def _df(self, annees):
        return pd.DataFrame({"annee": annees, "valeur": [float(i) for i in range(len(annees))]})

    def test_historique_valide(self):
        P.controler_historique(self._df(list(range(2000, 2025))), "ok")

    def test_non_chronologique(self):
        annees = list(range(2000, 2025))
        annees[3], annees[4] = annees[4], annees[3]
        with self.assertRaises(P.ErreurControle):
            P.controler_historique(self._df(annees), "desordre")

    def test_doublon(self):
        annees = list(range(2000, 2024)) + [2023]
        with self.assertRaises(P.ErreurControle):
            P.controler_historique(self._df(sorted(annees)), "doublon")

    def test_annee_manquante(self):
        annees = [a for a in range(2000, 2026) if a != 2010]
        with self.assertRaises(P.ErreurControle):
            P.controler_historique(self._df(annees), "trou")


class PasDeFuite(unittest.TestCase):
    def test_entrainement_strictement_anterieur(self):
        """Chaque année testée n'est jamais présente dans l'échantillon d'entraînement."""
        valeurs = pd.Series([float(v) for v in range(30)])
        longueurs = []

        class Faux:
            def __init__(self, train):
                self.train = train

            def forecast(self, steps):
                return pd.Series([self.train.iloc[-1]])

        def faux_ajuster(train, ordre):
            longueurs.append(len(train))
            return Faux(train)

        with mock.patch.object(P, "_ajuster", side_effect=faux_ajuster):
            P.validation_glissante(valeurs, (1, 0, 0))
        self.assertEqual(longueurs, list(range(30 - P.NB_ANNEES_VALIDATION, 30)))


class FichiersExportes(unittest.TestCase):
    """Vérifie les fichiers réellement générés dans data/processed/ (s'ils existent)."""

    def setUp(self):
        self.chemin_prev = P.DOSSIER_PROCESSED / "previsions.json"
        self.chemin_met = P.DOSSIER_PROCESSED / "previsions_metriques.json"
        if not (self.chemin_prev.exists() and self.chemin_met.exists()):
            self.skipTest("lancer d'abord : python -m observatoire.modeles.prevision")
        self.previsions = json.loads(self.chemin_prev.read_text(encoding="utf-8"))
        self.metriques = json.loads(self.chemin_met.read_text(encoding="utf-8"))

    def test_controles_passent(self):
        P.controler_previsions(self.previsions, self.metriques)

    def test_annees_relatives_a_l_historique(self):
        for s in P.SERIES:
            df = P.charger_serie(P.DOSSIER_PROCESSED / s.fichier)
            derniere = int(df["annee"].iloc[-1])
            m = next(m for m in self.metriques if m["indicateur"] == s.indicateur)
            self.assertEqual(m["derniere_observation"], derniere)
            if s.publier:
                annees = [p["annee"] for p in self.previsions if p["indicateur"] == s.indicateur]
                self.assertEqual(annees, P.annees_prevision(derniere))


if __name__ == "__main__":
    unittest.main()
