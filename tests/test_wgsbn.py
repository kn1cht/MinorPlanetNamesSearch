import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mpnames import db
from mpnames.categories import Category
from mpnames.ingest import backfill_wgsbn_only
from mpnames.wgsbn import (
    WgsbnNaming,
    parse_wgsbn_archive,
    parse_wgsbn_namings,
    wgsbn_volume_year,
)


ARCHIVE_HTML = '''
<li>&nbsp;Volume 2, #2&nbsp;&nbsp;<a href="files/json/V002/WGSBNBull_V002_002.json">UTF-8 only</a>&nbsp;&nbsp;<a href="files/json/V002/WGSBNBull_V002_002_html.json">UTF-8 + HTML</a> (2022 Oct. 3)
<li>&nbsp;Volume 2, #1&nbsp;&nbsp;<a href="files/json/V002/WGSBNBull_V002_001.json">UTF-8 only</a>&nbsp;&nbsp;<a href="files/json/V002/WGSBNBull_V002_001_html.json">UTF-8 + HTML</a> (2022 Sept. 12)
'''


class WgsbnParserTests(unittest.TestCase):
    def test_archive_parser_uses_utf8_json_and_publication_date(self):
        bulletins = parse_wgsbn_archive(ARCHIVE_HTML, "https://www.wgsbn-iau.org/files/json/index.html")

        self.assertEqual([bulletin.published_date for bulletin in bulletins], ["2022-09-12", "2022-10-03"])
        self.assertEqual(bulletins[0].source_url, "https://www.wgsbn-iau.org/files/json/V002/WGSBNBull_V002_001.json")

    def test_naming_parser_keeps_minor_planets_only(self):
        namings = parse_wgsbn_namings(
            '[{"mp_number": "5627", "name": "Short", "citation": "A citation", '
            '"reference": "WGSBN Bull. 2, #1, 5"}, {"sat_id": 1, "name": "Moon"}]'
        )

        self.assertEqual(namings, [WgsbnNaming("5627", "Short", "A citation", "WGSBN Bull. 2, #1, 5")])

    def test_naming_parser_excludes_later_withdrawn_names(self):
        namings = parse_wgsbn_namings(
            '[{"mp_number": "511955", "name": "Katalinkarikó"}, '
            '{"mp_number": "5627", "name": "Short"}]'
        )

        self.assertEqual(namings, [WgsbnNaming("5627", "Short", None, None)])

    def test_volume_determines_the_publication_year(self):
        self.assertEqual(wgsbn_volume_year(1), 2021)
        self.assertEqual(wgsbn_volume_year(2), 2022)
        self.assertEqual(wgsbn_volume_year(6), 2026)


class WgsbnDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "wgsbn.sqlite3"
        self.connection = db.connect(self.db_path)
        db.initialize(self.connection)
        db.upsert_minor_planet(
            self.connection,
            permid="5627",
            name_ascii="Short",
            name_display="Short",
            identifier={"permid": "5627", "citation": "A citation"},
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.tempdir.cleanup()

    def test_sync_stores_earliest_publication_metadata_and_keeps_unmatched_records(self):
        first_url = "https://www.wgsbn-iau.org/files/json/V002/WGSBNBull_V002_001.json"
        db.replace_wgsbn_bulletin(
            self.connection,
            source_url=first_url,
            volume=2,
            issue=1,
            published_date="2022-09-12",
            published_year=2022,
            namings=[
                WgsbnNaming("5627", "Short", "A citation", "WGSBN Bull. 2, #1, 5"),
                WgsbnNaming("999999", "Future", None, "WGSBN Bull. 2, #1, 6"),
            ],
        )
        later_url = "https://www.wgsbn-iau.org/files/json/V003/WGSBNBull_V003_001.json"
        db.replace_wgsbn_bulletin(
            self.connection,
            source_url=later_url,
            volume=3,
            issue=1,
            published_date="2023-01-16",
            published_year=2023,
            namings=[WgsbnNaming("5627", "Short", "Updated citation", "WGSBN Bull. 3, #1, 4")],
        )

        result = db.sync_wgsbn_naming_metadata(self.connection)
        row = self.connection.execute(
            "SELECT naming_published_date, naming_published_year, naming_reference, naming_source, naming_source_url FROM minor_planets WHERE permid = '5627'"
        ).fetchone()

        self.assertEqual(result, {"publications": 2, "updated": 1, "unchanged": 0, "missing": 1})
        self.assertEqual(
            tuple(row),
            (None, 2022, "WGSBN Bull. 2, #1, 5", "WGSBN Bulletin", first_url),
        )
        self.assertEqual(db.existing_wgsbn_bulletin_urls(self.connection), {first_url, later_url})

    def test_same_bulletin_duplicate_keeps_the_first_record(self):
        source_url = "https://www.wgsbn-iau.org/files/json/V002/WGSBNBull_V002_001.json"
        stored = db.replace_wgsbn_bulletin(
            self.connection,
            source_url=source_url,
            volume=2,
            issue=1,
            published_date="2022-09-12",
            published_year=2022,
            namings=[
                WgsbnNaming("5627", "Short", "Original", "WGSBN Bull. 2, #1, 5"),
                WgsbnNaming("5627", "Short", "Repeated", "WGSBN Bull. 2, #1, 6"),
            ],
        )
        row = self.connection.execute(
            "SELECT citation_text, reference FROM naming_publications WHERE permid = '5627'"
        ).fetchone()

        self.assertEqual(stored, 1)
        self.assertEqual(tuple(row), ("Original", "WGSBN Bull. 2, #1, 5"))

    def test_purge_withdrawn_wgsbn_namings_removes_objects_and_publications(self):
        db.upsert_minor_planet(
            self.connection,
            permid="511955",
            name_ascii="Katalinkariko",
            name_display="Katalinkarikó",
            identifier={"permid": "511955", "citation": "Withdrawn citation."},
        )
        self.connection.execute(
            """
            INSERT INTO naming_publications(permid, source_url, published_date, published_year, name)
            VALUES ('511955', 'https://example.test/v2-5.json', '2022-04-11', 2022, 'Katalinkarikó')
            """
        )

        result = db.purge_withdrawn_wgsbn_namings(self.connection)

        self.assertEqual(result, {"minor_planets": 1, "naming_publications": 1})
        self.assertIsNone(self.connection.execute("SELECT 1 FROM minor_planets WHERE permid = '511955'").fetchone())
        self.assertIsNone(self.connection.execute("SELECT 1 FROM naming_publications WHERE permid = '511955'").fetchone())

    def test_backfill_adds_an_explicit_wgsbn_only_record_with_metadata(self):
        source_url = "https://www.wgsbn-iau.org/files/json/V002/WGSBNBull_V002_001.json"
        db.replace_wgsbn_bulletin(
            self.connection,
            source_url=source_url,
            volume=2,
            issue=1,
            published_date="2022-09-12",
            published_year=2022,
            namings=[WgsbnNaming("999999", "Katalinkarikó", "A biochemist (b. 1955).", "WGSBN Bull. 2, #1, 13")],
        )
        self.connection.commit()

        with patch("mpnames.ingest.CitationClassifier") as classifier_type:
            classifier_type.return_value.classify.return_value = [Category("citation", "Person", "ollama", 0.85)]
            result = backfill_wgsbn_only(self.db_path, permids=["999999"], classifier_mode="ollama")

        row = self.connection.execute(
            """
            SELECT name_ascii, name_display, citation_text, naming_published_date, naming_published_year,
                   naming_reference, naming_source, naming_source_url
            FROM minor_planets WHERE permid = '999999'
            """
        ).fetchone()
        category = self.connection.execute(
            "SELECT value, source FROM categories WHERE permid = '999999' AND kind = 'citation'"
        ).fetchone()

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(
            tuple(row),
            (
                "Katalinkariko",
                "Katalinkarikó",
                "A biochemist (b. 1955).",
                None,
                2022,
                "WGSBN Bull. 2, #1, 13",
                "WGSBN Bulletin",
                source_url,
            ),
        )
        self.assertEqual(tuple(category), ("Person", "ollama"))


if __name__ == "__main__":
    unittest.main()
