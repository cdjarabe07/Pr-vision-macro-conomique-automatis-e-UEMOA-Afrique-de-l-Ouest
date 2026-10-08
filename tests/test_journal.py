"""
Tests du journal des mises à jour.

Lancement (depuis la racine du projet) :
    python -m unittest discover -s tests -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from observatoire import journal as J


def portail_type():
    return {
        "generated_at": "2026-10-08T02:41:34Z",
        "source": "BCEAO via DBnomics (datasets IMECO, TC_A)",
        "zones": [{"id": "senegal"}, {"id": "uemoa"}],
        "indicateurs": [{"id": "dette_pib", "periode": [2001, 2024]}, {"id": "inflation", "periode": [1998, 2023]}],
        "series": {"dette_pib": {"senegal": [[2023, 1.0], [2024, 2.0]]}, "inflation": {"uemoa": [[2023, 3.0]]}},
        "ruptures": [{"id": "dette_perimetre_2022", "indicateurs": ["dette_pib"], "premiere_annee": 2022,
                      "statut": "deduit", "verifie_le": "2026-10-08"}],
    }


def metriques_type():
    base = {"pays": "senegal", "date_entrainement": "2026-10-07T23:44:22Z", "derniere_observation": 2024}
    return [
        {**base, "indicateur": "pib", "publie": True, "premiere_annee_prevision": 2025, "derniere_annee_prevision": 2026},
        {**base, "indicateur": "taux_change", "publie": False, "premiere_annee_prevision": None, "derniere_annee_prevision": None},
    ]


class Journal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chemin = Path(self.tmp.name) / "journal.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_enregistrement_et_doublon(self):
        e = J.evenement("donnees", "2026-10-08T02:41:34Z", "test")
        self.assertTrue(J.enregistrer(e, self.chemin))
        self.assertFalse(J.enregistrer(e, self.chemin))
        self.assertEqual(len(J.charger(self.chemin)), 1)

    def test_tri_du_plus_recent_au_plus_ancien(self):
        J.enregistrer(J.evenement("previsions", "2026-10-07T23:44:22Z", "test"), self.chemin)
        J.enregistrer(J.evenement("donnees", "2026-10-08T02:41:34Z", "test"), self.chemin)
        self.assertEqual([e["type"] for e in J.charger(self.chemin)], ["donnees", "previsions"])

    def test_type_inconnu_refuse(self):
        with self.assertRaises(J.ErreurJournal):
            J.enregistrer(J.evenement("annonce", "2026-10-08", "test"), self.chemin)

    def test_date_invalide_refusee(self):
        with self.assertRaises(J.ErreurJournal):
            J.enregistrer(J.evenement("donnees", "8 octobre", "test"), self.chemin)

    def test_evenements_portail_lus_dans_le_fichier(self):
        donnees, methode = J.evenements_portail(portail_type())
        self.assertEqual(donnees["date"], "2026-10-08T02:41:34Z")
        self.assertEqual(donnees["details"]["observations"], 3)
        self.assertEqual(donnees["details"]["derniere_annee"], 2024)
        self.assertEqual(methode["id"], "methode:dette_perimetre_2022")
        self.assertEqual(methode["date"], "2026-10-08")

    def test_evenement_previsions_ignore_les_series_non_publiees(self):
        e = J.evenement_previsions(metriques_type())
        self.assertEqual(e["date"], "2026-10-07T23:44:22Z")
        self.assertEqual(e["indicateurs"], ["pib"])
        self.assertEqual((e["details"]["premiere_annee"], e["details"]["derniere_annee"]), (2025, 2026))

    def test_evenements_fmi(self):
        fmi = {
            "generated_at": "2026-10-08T10:00:00Z",
            "matieres_premieres": {"source": "FMI PCPS", "dernier_mois": "2025-06", "produits": [{"id": "cacao"}]},
            "projections": {"source": "FMI WEO", "edition": "2025-04", "premiere_annee": 2025, "derniere_annee": 2030,
                            "indicateurs": [{"id": "inflation"}], "series": {"inflation": {"niger": [[2025, 4.7]]}}},
        }
        pcps, weo = J.evenements_fmi(fmi)
        self.assertEqual(pcps["details"]["dernier_mois"], "2025-06")
        self.assertEqual(weo["zones"], ["niger"])
        self.assertNotEqual(pcps["id"], weo["id"])
        for e in (pcps, weo):
            J.valider(e)

    def test_reconstitution_idempotente(self):
        portail = Path(self.tmp.name) / "portail.json"
        metriques = Path(self.tmp.name) / "metriques.json"
        portail.write_text(json.dumps(portail_type()), encoding="utf-8")
        metriques.write_text(json.dumps(metriques_type()), encoding="utf-8")
        premiers = J.reconstituer(self.chemin, portail, metriques)
        self.assertEqual(len(premiers), 3)
        self.assertEqual(J.reconstituer(self.chemin, portail, metriques), [])


if __name__ == "__main__":
    unittest.main()
