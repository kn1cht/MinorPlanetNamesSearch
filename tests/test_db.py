from pathlib import Path
import tempfile
import unittest

from mpnames import db
from mpnames.categories import Category
from mpnames.ingest import init_sample
from mpnames.numbered_mps import DiscoveryRecord


FIXTURES = Path(__file__).parent / "fixtures"


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "sample.sqlite3"
        init_sample(self.db_path, FIXTURES)
        self.connection = db.connect(self.db_path)
        db.initialize(self.connection)

    def tearDown(self):
        self.connection.close()
        self.tempdir.cleanup()

    def test_initialize_creates_facet_query_indexes(self):
        index_names = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        self.assertTrue({
            "categories_kind_value_permid",
            "discovery_facets_kind_value_permid",
            "minor_planets_is_neo_permid",
            "minor_planets_is_pha_permid",
        }.issubset(index_names))

    def test_initialize_indexes_identifiers_in_fts(self):
        fts_columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(minor_planets_fts)"
            )
        }
        self.assertTrue({
            "permid",
            "packed_permid",
            "iau_designation",
            "name_ascii",
            "name_display",
            "citation_text",
        }.issubset(fts_columns))

    def test_long_query_clause_uses_fts_without_like_fallback(self):
        clause, params = db._query_clause("Charlemagne", q_target="both")
        self.assertIn("minor_planets_fts MATCH ?", clause)
        self.assertNotIn("LIKE", clause)
        self.assertEqual(len(params), 1)

        plan = self.connection.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT mp.permid FROM minor_planets mp "
            f"WHERE {clause}",
            params,
        ).fetchall()
        details = [row[3] for row in plan]
        self.assertTrue(any("minor_planets_fts" in detail for detail in details))
        self.assertFalse(any("SCAN mp" in detail for detail in details))

    def test_search_by_name(self):
        result = db.search(self.connection, q="Aachen")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name_ascii"], "Aachen")

    def test_search_by_two_character_name(self):
        db.upsert_minor_planet(
            self.connection,
            permid="4292",
            name_ascii="Aoba",
            name_display="Aoba",
            identifier={"permid": "4292", "citation": "(4292) Aoba Named for a longer short-name neighbor."},
        )
        db.upsert_minor_planet(
            self.connection,
            permid="697402",
            name_ascii="Ao",
            name_display="Ao",
            identifier={"permid": "697402", "citation": "(697402) Ao Named for a short test name."},
        )
        self.connection.commit()

        result = db.search(self.connection, q="Ao")

        self.assertGreaterEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name_ascii"], "Ao")

    def test_search_by_citation_term(self):
        result = db.search(self.connection, q="Charlemagne")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["permid"], "274835")

    def test_multi_query_terms_and_mode_requires_all_terms(self):
        result = db.search(self.connection, q=["Apollo", "mythology"], q_mode="and")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name_ascii"], "Apollo")

    def test_multi_query_terms_or_mode_matches_any_term(self):
        result = db.search(self.connection, q=["Apollo", "Aten"], q_mode="or")
        names = {item["name_ascii"] for item in result["items"]}
        self.assertEqual(result["total"], 2)
        self.assertEqual(names, {"Apollo", "Aten"})

    def test_multi_query_terms_invalid_mode_falls_back_to_and(self):
        result = db.search(self.connection, q=["Apollo", "mythology"], q_mode="invalid")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name_ascii"], "Apollo")

    def test_query_target_name_limits_search_to_name_fields(self):
        db.upsert_minor_planet(
            self.connection,
            permid="900101",
            name_ascii="Nameonlytarget",
            name_display="Nameonlytarget",
            identifier={"permid": "900101", "citation": "This citation intentionally omits the trigger."},
        )
        db.upsert_minor_planet(
            self.connection,
            permid="900102",
            name_ascii="CompletelyDifferent",
            name_display="CompletelyDifferent",
            identifier={"permid": "900102", "citation": "Contains Nameonlytarget only in citation text."},
        )
        self.connection.commit()

        result = db.search(self.connection, q="Nameonlytarget", q_target="name")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["permid"], "900101")

    def test_query_target_citation_limits_search_to_citation_field(self):
        db.upsert_minor_planet(
            self.connection,
            permid="900103",
            name_ascii="Citationcarrier",
            name_display="Citationcarrier",
            identifier={"permid": "900103", "citation": "Includes CitationOnlyNeedle in citation."},
        )
        db.upsert_minor_planet(
            self.connection,
            permid="900104",
            name_ascii="CitationOnlyNeedle",
            name_display="CitationOnlyNeedle",
            identifier={"permid": "900104", "citation": "No special keyword here."},
        )
        self.connection.commit()

        result = db.search(self.connection, q="CitationOnlyNeedle", q_target="citation")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["permid"], "900103")

    def test_query_target_invalid_falls_back_to_both(self):
        result = db.search(self.connection, q="Charlemagne", q_target="invalid")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["permid"], "274835")

    def test_multi_query_terms_not_prefix_excludes_matches(self):
        result = db.search(self.connection, q=["Apollo", "Aten", "!mythology"], q_mode="or")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name_ascii"], "Aten")

    def test_not_only_query_excludes_matching_records(self):
        all_items = db.search(self.connection)
        excluded = db.search(self.connection, q=["!Charlemagne"])

        self.assertEqual(excluded["total"], all_items["total"] - 1)
        self.assertNotIn("274835", {item["permid"] for item in excluded["items"]})

    def test_wordcloud_and_facets_accept_multi_query_terms(self):
        words = db.wordcloud(self.connection, q=["Apollo", "mythology"], q_mode="and")
        facets = db.facets(self.connection, q=["Apollo", "mythology"], q_mode="and")

        self.assertTrue(any(item["word"] == "mythology" for item in words))
        self.assertIn("orbit_types", facets)
        self.assertTrue(any(item["value"] == "Apollo" for item in facets["orbit_types"]))

    def test_search_by_number_prioritizes_object_identity_over_citation_text(self):
        db.upsert_minor_planet(
            self.connection,
            permid="824",
            name_ascii="Anastasia",
            name_display="Anastasia",
            identifier={"permid": "824"},
        )
        db.upsert_minor_planet(
            self.connection,
            permid="8241",
            name_ascii="Augustbetankur",
            name_display="Augustbetankur",
            identifier={
                "permid": "8241",
                "citation": "Named for Avgustin Avgustinovich Betankur (1758-1824).",
            },
        )
        self.connection.commit()

        by_number = db.search(self.connection, q="824")
        by_name = db.search(self.connection, q="Anastasia")

        self.assertGreaterEqual(by_number["total"], 2)
        self.assertEqual(by_number["items"][0]["permid"], "824")
        self.assertEqual(by_name["items"][0]["permid"], "824")
        self.assertEqual(by_name["items"][0]["citation_categories"], ["No Citation"])

    def test_search_by_discoverer_and_observatory(self):
        db.upsert_minor_planet(
            self.connection,
            permid="900001",
            name_ascii="Testdiscovery",
            name_display="Testdiscovery",
            identifier={"permid": "900001", "citation": "Named for a discovery test."},
            discovery=DiscoveryRecord(
                permid="900001",
                name="Testdiscovery",
                discovery_date="1860-09-14",
                discovery_site="Berlin",
                discoverer_text="Lesser, O., Forster, W.",
                discoverers=("Lesser, O.", "Forster, W."),
            ),
        )
        self.connection.commit()

        by_discoverer = db.search(self.connection, q="Forster")
        self.assertEqual(by_discoverer["total"], 1)
        self.assertEqual(by_discoverer["items"][0]["discovery_site"], "Berlin")

        by_filter = db.search(self.connection, discoverer="Lesser, O.", observatory="Berlin")
        self.assertEqual(by_filter["total"], 1)
        self.assertEqual(by_filter["items"][0]["discoverer_text"], "Lesser, O., Forster, W.")

        stats = db.stats(self.connection)
        self.assertIn("Lesser, O.", {item["value"] for item in stats["discoverers"]})
        self.assertIn("Berlin", {item["value"] for item in stats["observatories"]})

    def test_category_filter_and_wordcloud(self):
        result = db.search(self.connection, citation_category="Mythology")
        self.assertGreaterEqual(result["total"], 2)
        words = db.wordcloud(self.connection, citation_category="Mythology")
        self.assertTrue(any(item["word"] == "mythology" for item in words))

    def test_orbit_filter(self):
        result = db.search(self.connection, orbit="Apollo")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["name_ascii"], "Apollo")

    def test_search_items_include_citation_categories(self):
        result = db.search(self.connection, q="Apollo")
        self.assertEqual(result["total"], 1)
        self.assertIn("Mythology", result["items"][0]["citation_categories"])

    def test_missing_citation_is_labeled_no_citation(self):
        result = db.search(self.connection, q="Ceres")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["citation_categories"], ["No Citation"])

    def test_initialize_migrates_empty_unknown_to_no_citation(self):
        db.replace_citation_categories(
            self.connection,
            "1",
            [Category("citation", "Unknown", "test", 0.2)],
        )
        self.connection.commit()

        db.initialize(self.connection)

        categories = [
            row["value"]
            for row in self.connection.execute(
                "SELECT value FROM categories WHERE permid = ? AND kind = 'citation' ORDER BY value",
                ("1",),
            ).fetchall()
        ]
        self.assertEqual(categories, ["No Citation"])

    def test_initialize_migrates_deprecated_science_culture_category(self):
        db.replace_citation_categories(
            self.connection,
            "1862",
            [Category("citation", "Science/Culture", "ollama", 0.85)],
        )
        self.connection.commit()

        db.initialize(self.connection)

        categories = [
            row["value"]
            for row in self.connection.execute(
                "SELECT value FROM categories WHERE permid = ? AND kind = 'citation' ORDER BY value",
                ("1862",),
            ).fetchall()
        ]
        self.assertNotIn("Science/Culture", categories)
        self.assertEqual(categories, ["Mythology"])

    def test_sort_by_alpha_ascending_and_descending(self):
        ascending = db.search(self.connection, sort="alpha", direction="asc")
        descending = db.search(self.connection, sort="alpha", direction="desc")
        self.assertEqual(ascending["items"][0]["name_ascii"], "A Coruna")
        self.assertEqual(descending["items"][0]["name_ascii"], "Ceres")

    def test_sort_by_number_ascending_and_descending(self):
        ascending = db.search(self.connection, sort="number", direction="asc")
        descending = db.search(self.connection, sort="number", direction="desc")
        self.assertEqual(ascending["items"][0]["permid"], "1")
        self.assertEqual(descending["items"][0]["permid"], "274835")

    def test_sort_by_absolute_magnitude(self):
        ascending = db.search(self.connection, sort="absolute_magnitude", direction="asc")
        descending = db.search(self.connection, sort="absolute_magnitude", direction="desc")
        self.assertEqual(ascending["items"][0]["name_ascii"], "Ceres")
        self.assertEqual(descending["items"][0]["name_ascii"], "Aten")

    def test_sort_by_orbital_elements(self):
        semimajor = db.search(self.connection, sort="semimajor_axis", direction="desc")
        eccentricity = db.search(self.connection, sort="eccentricity", direction="desc")
        inclination = db.search(self.connection, sort="inclination", direction="desc")
        self.assertEqual(semimajor["items"][0]["name_ascii"], "A Coruna")
        self.assertEqual(eccentricity["items"][0]["name_ascii"], "Alinda")
        self.assertEqual(inclination["items"][0]["name_ascii"], "Aten")

    def test_multi_orbit_filter_uses_or_semantics(self):
        result = db.search(self.connection, orbit=["Apollo", "Aten"])
        self.assertEqual(result["total"], 2)
        self.assertEqual({item["name_ascii"] for item in result["items"]}, {"Apollo", "Aten"})

    def test_multi_citation_category_filter_uses_or_semantics(self):
        result = db.search(
            self.connection, citation_category=["Mythology", "Country/Region/Town"]
        )
        names = {item["name_ascii"] for item in result["items"]}
        self.assertIn("Apollo", names)
        self.assertIn("Aachen", names)

    def test_multi_flag_filter_uses_or_semantics(self):
        result = db.search(self.connection, flag=["NEO", "PHA"])
        names = {item["name_ascii"] for item in result["items"]}
        self.assertIn("Apollo", names)
        self.assertIn("Aten", names)


if __name__ == "__main__":
    unittest.main()
