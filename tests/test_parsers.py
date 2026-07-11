from pathlib import Path
import unittest

from mpnames.mpnames_parser import parse_mpnames_html
from mpnames.mpcorb import parse_mpcorb_lines
from mpnames.numbered_mps import parse_numbered_mps, split_discoverers


FIXTURES = Path(__file__).parent / "fixtures"


class ParserTests(unittest.TestCase):
    def test_parse_mpnames_html(self):
        records = parse_mpnames_html((FIXTURES / "mpnames_sample.html").read_text(encoding="utf-8"))
        self.assertEqual(records[0].permid, "9605")
        self.assertEqual(records[0].name_ascii, "A Coruna")
        self.assertEqual(records[0].name_display, "A Coruña")
        self.assertEqual(records[2].name_ascii, "Ceres")

    def test_parse_mpcorb_flags(self):
        records = parse_mpcorb_lines((FIXTURES / "mpcorb_sample.dat").read_text(encoding="utf-8").splitlines())
        apollo = records["1862"]
        self.assertEqual(apollo.orbit_type, "Apollo")
        self.assertTrue(apollo.is_pha)
        self.assertTrue(apollo.is_neo)

        aten = records["2062"]
        self.assertEqual(aten.orbit_type, "Aten")
        self.assertTrue(aten.is_neo)
        self.assertFalse(aten.is_pha)

    def test_parse_numbered_mps_discovery_records(self):
        text = (FIXTURES / "numbered_mps_sample.txt").read_text(encoding="utf-8")
        records = parse_numbered_mps(text)

        self.assertEqual(records["1"].discovery_date, "1801-01-01")
        self.assertEqual(records["1"].discovery_site, "Palermo")
        self.assertEqual(records["1"].discoverers, ("Piazzi, G.",))
        self.assertEqual(records["12349"].name, "Akebonozou")
        self.assertEqual(records["27967"].discoverer_text, "Osservatorio San Vittore")
        self.assertEqual(records["27967"].discoverers, ("Osservatorio San Vittore",))

    def test_split_multiple_discoverers(self):
        self.assertEqual(
            split_discoverers("Lesser, O., Forster, W."),
            ("Lesser, O.", "Forster, W."),
        )
        self.assertEqual(split_discoverers("Spacewatch"), ("Spacewatch",))


if __name__ == "__main__":
    unittest.main()
