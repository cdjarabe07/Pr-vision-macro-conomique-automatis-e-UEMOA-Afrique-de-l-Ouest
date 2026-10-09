"""Agenda (export_agenda.py) : lecture de la page « Événements » de la BCEAO."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import export_agenda as A

EXTRAIT = """
<li><div class="elemListActus"><div class="img"></div><div class="info">
    <div class="datePays"> <time datetime="00Z">27 Mars 2026</time>
 </div>
    <div class="ttr"><a href="/fr/evenement/conseil-des-ministres-de-lunion-2" hreflang="fr">Conseil des Ministres de l&#039;Union</a></div>
    <div class="desc">Session ordinaire du Conseil des Ministres de l&#039;Union prévue le vendredi 27 mars 2026 à 9h</div>
</div></div></li>
<li><div class="elemListActus"><div class="img"></div><div class="info">
    <div class="datePays"> <time datetime="00Z">04 Mars 2026</time>
 </div>
    <div class="ttr"><a href="/fr/evenement/reunion-du-comite-de-politique-monetaire-de-la-bceao-0" hreflang="fr">Réunion du Comité de Politique Monétaire de la BCEAO</a></div>
    <div class="desc"></div>
</div></div></li>
<li><div class="elemListActus"><div class="info">
    <div class="datePays"> <time datetime="00Z">08 Octobre 2026</time></div>
    <div class="ttr"><a href="/fr/communique-presse/liste" hreflang="fr">Un communiqué, pas un événement</a></div>
    <div class="desc"></div>
</div></div></li>
"""


class TestAgenda(unittest.TestCase):
    def test_dates_en_francais(self):
        self.assertEqual(A.date_fr("27 Mars 2026"), date(2026, 3, 27))
        self.assertEqual(A.date_fr("08 mai 2026"), date(2026, 5, 8))
        self.assertEqual(A.date_fr("1 août 2025"), date(2025, 8, 1))
        with self.assertRaises(A.ErreurControle):
            A.date_fr("bientôt")

    def test_extraction_des_evenements(self):
        ev = A.extraire_bceao(EXTRAIT)
        self.assertEqual([e["date"] for e in ev], ["2026-03-27", "2026-03-04"])
        self.assertEqual(ev[0]["titre"]["fr"], "Conseil des Ministres de l'Union")
        self.assertEqual(ev[0]["type"], "conseil_ministres")
        self.assertEqual(ev[1]["type"], "cpm")
        self.assertEqual(ev[0]["url"], "https://www.bceao.int/fr/evenement/conseil-des-ministres-de-lunion-2")
        self.assertIsNone(ev[1]["description"])

    def test_agenda_international_exige_source_et_verification(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "agenda.json"
            chemin.write_text(json.dumps([{"id": "x", "date": "2026-10-13", "institution": "FMI", "type": "publication",
                                           "titre": {"fr": "x"}, "url": "https://example.org"}]), encoding="utf-8")
            with self.assertRaises(A.ErreurControle):
                A.charger_international(chemin)


if __name__ == "__main__":
    unittest.main()
