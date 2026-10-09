"""Inflation mensuelle (export_fmi.py) : glissements, sauts d'indice, concordance BCEAO."""

import unittest

import export_fmi as E


def indice_constant(debut_an: int, fin_an: int, taux_annuel: float) -> dict[str, float]:
    """Indice croissant au même rythme chaque mois : glissement annuel = taux_annuel."""
    mensuel = (1 + taux_annuel / 100) ** (1 / 12)
    indice, v = {}, 100.0
    for an in range(debut_an, fin_an + 1):
        for m in range(1, 13):
            indice[f"{an}-{m:02d}"] = v
            v *= mensuel
    return indice


class TestInflationMensuelle(unittest.TestCase):
    def test_glissement_annuel(self):
        pts = E.glissements(indice_constant(2018, 2020, 5.0), debut="2019-01")
        self.assertEqual(pts[0][0], "2019-01")
        self.assertEqual(len(pts), 24)
        self.assertTrue(all(abs(v - 5.0) < 0.01 for _, v in pts))

    def test_glissement_ignore_les_mois_sans_reference(self):
        indice = indice_constant(2019, 2020, 2.0)
        del indice["2019-03"]
        mois = [m for m, _ in E.glissements(indice, debut="2020-01")]
        self.assertNotIn("2020-03", mois)
        self.assertIn("2020-04", mois)

    def test_saut_d_indice_detecte(self):
        indice = indice_constant(2020, 2021, 2.0)
        indice["2021-06"] = indice["2021-05"] * 0.5  # changement de base
        sauts = E.sauts_suspects(indice)
        self.assertEqual([m for m, _ in sauts], ["2021-06", "2021-07"])
        self.assertEqual(E.sauts_suspects(indice_constant(2020, 2021, 2.0)), [])

    def test_concordance_avec_la_bceao(self):
        indice = indice_constant(2020, 2024, 3.0)
        conc = E.concordance(indice, {2021: 3.0, 2022: 2.5, 2023: 3.0, 2024: 3.0}, n=3)
        self.assertEqual([c["annee"] for c in conc], [2024, 2023, 2022])
        self.assertEqual(conc[2]["ecart"], 0.5)
        self.assertTrue(all(c["fmi"] == 3.0 for c in conc))

    def test_concordance_ignore_les_annees_incompletes(self):
        indice = indice_constant(2022, 2024, 3.0)
        del indice["2024-12"]
        self.assertEqual([c["annee"] for c in E.concordance(indice, {2023: 3.0, 2024: 3.0})], [2023])


class TestProjectionsWEO(unittest.TestCase):
    def test_nom_du_jeu_date(self):
        self.assertEqual(E.flux_weo("2026-04"), "WEO_2026_APR_VINTAGE")
        self.assertEqual(E.flux_weo("2025-10"), "WEO_2025_OCT_VINTAGE")

    def test_edition_la_plus_recente(self):
        liste = ('<str:Dataflow id="WEO_2026_APR_VINTAGE"/><str:Dataflow id="WEO"/>'
                 '<str:Dataflow id="WEO_2025_OCT_VINTAGE"/><str:Dataflow id="AFRREO_2025_OCT_VINTAGE"/>')
        self.assertEqual(E.editions_dans(liste), ["2025-10", "2026-04"])

    def test_lecture_sdmx(self):
        xml = (
            '<?xml version="1.0"?><m:StructureSpecificData xmlns:m="urn:m"><m:DataSet>'
            '<Series COUNTRY="SEN" INDICATOR="NGDP_RPCH" COUNTRY_UPDATE_DATE="3/24/2026">'
            '<Obs TIME_PERIOD="2026" OBS_VALUE="2.17"/><Obs TIME_PERIOD="2027" OBS_VALUE="2.28"/></Series>'
            "</m:DataSet></m:StructureSpecificData>"
        )
        [(attrs, obs)] = E.lire_sdmx(xml)
        self.assertEqual(attrs["COUNTRY"], "SEN")
        self.assertEqual(obs, [("2026", "2.17"), ("2027", "2.28")])


if __name__ == "__main__":
    unittest.main()
