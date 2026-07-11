import json
import unittest
from unittest.mock import patch

from mpnames.ingest import fetch_orbits
from mpnames.mpcorb import parse_orbits_api_response
from mpnames.mpnames_parser import NameRecord


ORBIT_RESPONSE = [
    {
        "mpc_orb": [
            {
                "KEP": {
                    "coefficient_names": ["a", "e", "i", "node", "argperi", "mean_anomaly"],
                    "coefficient_values": [1.4709238, 0.559918, 6.351396, 35.541637, 286.050879, 113.884537],
                },
                "categorization": {
                    "orbit_type_int": 2,
                    "orbit_type_str": "Apollo",
                },
                "designation_data": {
                    "iau_designation": "(1862)",
                    "name": "Apollo",
                    "packed_permid": "01862",
                    "permid": "1862",
                },
                "epoch_data": {"epoch": 61000.0},
                "magnitude_data": {"H": 16.094, "G": 0.09},
                "moid_data": {"Earth": 0.02602},
                "orbit_fit_statistics": {
                    "U_param": 1,
                    "nobs_total": 123,
                    "nopp": 4,
                    "not_normalized_RMS": 0.2,
                },
            }
        ]
    },
    200,
]

COM_ONLY_RESPONSE = [
    {
        "mpc_orb": [
            {
                "COM": {
                    "coefficient_names": ["q", "e", "i", "node", "argperi", "peri_time"],
                    "coefficient_values": [0.790166373380553, 0.18280496521003, 18.9341894308854, 108.5405811622926, 148.0536882414564, 59926.57152603],
                },
                "categorization": {
                    "orbit_type_int": None,
                    "orbit_type_str": "",
                },
                "designation_data": {
                    "iau_designation": "(2062)",
                    "name": "Aten",
                    "packed_permid": "02062",
                    "permid": "2062",
                },
                "epoch_data": {"epoch": 61000.0},
                "magnitude_data": {"H": 17.108, "G": 0.15},
                "moid_data": {"Earth": 0.113},
                "orbit_fit_statistics": {
                    "U_param": 0,
                    "nobs_total": 2100,
                    "nopp": 25,
                    "not_normalized_RMS": 0.3,
                },
            }
        ]
    },
    200,
]

MAIN_BELT_WITH_EMPTY_CATEGORY_RESPONSE = [
    {
        "mpc_orb": [
            {
                "COM": {
                    "coefficient_names": ["q", "e", "i", "node", "argperi", "peri_time"],
                    "coefficient_values": [2.730993, 0.083635865839327, 0.571795209526, 0.0, 0.0, 0.0],
                },
                "categorization": {
                    "orbit_type_int": None,
                    "orbit_type_str": "",
                },
                "designation_data": {
                    "iau_designation": "(56795)",
                    "name": "Amandagorman",
                    "packed_permid": "56795",
                    "permid": "56795",
                },
                "magnitude_data": {"H": 16.9, "G": 0.15},
                "orbit_fit_statistics": {},
            }
        ]
    },
    200,
]


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(ORBIT_RESPONSE).encode("utf-8")


class OrbitsApiTests(unittest.TestCase):
    def test_parse_orbits_api_response(self):
        orbit = parse_orbits_api_response(ORBIT_RESPONSE)
        self.assertIsNotNone(orbit)
        self.assertEqual(orbit.permid_or_packed, "1862")
        self.assertEqual(orbit.orbit_type, "Apollo")
        self.assertTrue(orbit.is_neo)
        self.assertTrue(orbit.is_pha)
        self.assertAlmostEqual(orbit.semimajor_axis, 1.4709238)
        self.assertAlmostEqual(orbit.eccentricity, 0.559918)
        self.assertEqual(orbit.observations, 123)

    def test_parse_orbits_api_response_uses_com_when_kep_is_absent(self):
        orbit = parse_orbits_api_response(COM_ONLY_RESPONSE)

        self.assertIsNotNone(orbit)
        self.assertEqual(orbit.permid_or_packed, "2062")
        self.assertEqual(orbit.orbit_type, "Aten")
        self.assertTrue(orbit.is_neo)
        self.assertAlmostEqual(orbit.semimajor_axis, 0.9669250787648707)
        self.assertAlmostEqual(orbit.eccentricity, 0.18280496521003)
        self.assertAlmostEqual(orbit.inclination, 18.9341894308854)
        self.assertAlmostEqual(orbit.ascending_node, 108.5405811622926)
        self.assertAlmostEqual(orbit.argument_perihelion, 148.0536882414564)

    def test_parse_orbits_api_response_classifies_empty_main_belt_category(self):
        orbit = parse_orbits_api_response(MAIN_BELT_WITH_EMPTY_CATEGORY_RESPONSE)

        self.assertIsNotNone(orbit)
        self.assertEqual(orbit.permid_or_packed, "56795")
        self.assertEqual(orbit.orbit_type, "Main Belt")
        self.assertFalse(orbit.is_neo)

    def test_fetch_orbits_uses_single_object_orbits_api(self):
        records = [NameRecord(permid="1862", name_ascii="Apollo", name_display="Apollo")]
        identifiers = {"Apollo": {"permid": "1862", "packed_permid": "01862"}}
        with patch("mpnames.ingest.urllib.request.urlopen", return_value=_FakeResponse()) as urlopen:
            orbits = fetch_orbits(records, identifiers=identifiers, delay=0)

        self.assertIn("1862", orbits)
        self.assertIn("01862", orbits)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://data.minorplanetcenter.net/api/get-orb")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"desig": "1862"})


if __name__ == "__main__":
    unittest.main()
