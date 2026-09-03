from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mpnames import db
from mpnames.categories import Category
from mpnames.ingest import _unique_orbit_count, ingest, reclassify_existing
from mpnames.mpcorb import OrbitRecord
from mpnames.mpnames_parser import NameRecord
from mpnames.wgsbn import WgsbnNaming


def _identifier(permid: str, name: str, citation: str | None = None):
    return {
        "citation": citation if citation is not None else f"({permid}) {name}<br><br>{name} is a test city.",
        "found": 1,
        "iau_designation": f"({permid})",
        "name": name,
        "packed_permid": permid.zfill(5),
        "permid": permid,
        "unpacked_primary_provisional_designation": f"20{permid.zfill(2)} AA",
    }


def _records(*permids: str):
    return [NameRecord(permid=permid, name_ascii=f"Name{permid}", name_display=f"Name{permid}") for permid in permids]


class IngestModeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "modes.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_add_mode_skips_existing_before_applying_limit(self):
        self._upsert("1")
        seen: list[str] = []

        def fake_identifiers(names, **kwargs):
            seen.extend(record.permid for record in names)
            return {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in names}

        with self._patched_sources(_records("1", "2", "3"), fake_identifiers):
            result = ingest(self.db_path, mode="add", limit=2, classifier_mode="rules", wgsbn_sync=False)

        self.assertEqual(seen, ["2", "3"])
        self.assertEqual(result["selected_records"], 2)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(self._count(), 3)

    def test_add_mode_makes_no_detail_requests_when_everything_exists(self):
        self._upsert("1")
        fetch_identifiers = Mock(return_value={})
        fetch_orbits = Mock(return_value={})
        with patch.multiple(
            "mpnames.ingest",
            fetch_names=Mock(return_value=_records("1")),
            fetch_identifiers=fetch_identifiers,
            fetch_orbits=fetch_orbits,
            fetch_discoveries=Mock(return_value={}),
        ):
            result = ingest(self.db_path, mode="add", limit=10, classifier_mode="rules", wgsbn_sync=False)

        self.assertEqual(result["selected_records"], 0)
        fetch_identifiers.assert_not_called()
        fetch_orbits.assert_not_called()

    def test_update_mode_fetches_existing_but_skips_unchanged_write(self):
        self._upsert("1")

        def fake_identifiers(names, **kwargs):
            return {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in names}

        with self._patched_sources(_records("1"), fake_identifiers):
            result = ingest(self.db_path, mode="update", limit=1, classifier_mode="rules", wgsbn_sync=False)

        self.assertEqual(result["selected_records"], 1)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["updated"], 0)

    def test_repair_mode_fetches_incomplete_and_new_records(self):
        self._upsert("1")
        self._mark_complete("1")
        self._upsert("2", identifier={})
        seen: list[str] = []

        def fake_identifiers(names, **kwargs):
            seen.extend(record.permid for record in names)
            return {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in names}

        with self._patched_sources(_records("1", "2", "3"), fake_identifiers):
            result = ingest(self.db_path, mode="repair", limit=2, classifier_mode="rules", wgsbn_sync=False)

        self.assertEqual(seen, ["2", "3"])
        self.assertEqual(result["selected_records"], 2)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["inserted"], 1)

    def test_ingest_attaches_cached_wgsbn_metadata(self):
        connection = db.connect(self.db_path)
        db.initialize(connection)
        source_url = "https://www.wgsbn-iau.org/files/json/V002/WGSBNBull_V002_001.json"
        db.replace_wgsbn_bulletin(
            connection,
            source_url=source_url,
            volume=2,
            issue=1,
            published_date="2022-09-12",
            published_year=2022,
            namings=[WgsbnNaming("2", "Name2", "A test city.", "WGSBN Bull. 2, #1, 5")],
        )
        connection.commit()
        connection.close()

        def fake_identifiers(names, **kwargs):
            return {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in names}

        with self._patched_sources(_records("2"), fake_identifiers):
            result = ingest(self.db_path, mode="add", classifier_mode="rules", wgsbn_sync=False)

        connection = db.connect(self.db_path)
        row = connection.execute(
            "SELECT naming_published_year, naming_reference, naming_source, naming_source_url "
            "FROM minor_planets WHERE permid = '2'"
        ).fetchone()
        connection.close()

        self.assertEqual(result["naming_metadata_updated"], 1)
        self.assertEqual(
            tuple(row),
            (2022, "WGSBN Bull. 2, #1, 5", "WGSBN Bulletin", source_url),
        )

    def test_ingest_collects_new_wgsbn_bulletins_by_default(self):
        def fake_identifiers(names, **kwargs):
            return {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in names}

        with self._patched_sources(_records("2"), fake_identifiers), patch(
            "mpnames.ingest._collect_new_wgsbn_bulletins",
            return_value={"fetched_bulletins": 1, "fetched_namings": 2},
        ) as collect:
            result = ingest(self.db_path, mode="add", classifier_mode="rules")

        collect.assert_called_once()
        self.assertEqual(result["wgsbn_bulletins_fetched"], 1)
        self.assertEqual(result["wgsbn_namings_fetched"], 2)

    def test_ingest_classifies_ready_records_during_orbit_pause(self):
        records = _records("1", "2")
        identifiers = {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in records}
        events: list[tuple[str, str | None]] = []
        classifier = Mock()

        def fake_classify(citation_text):
            events.append(("classify", citation_text))
            return []

        def fake_fetch_orbits(names, **kwargs):
            events.append(("before_pause", None))
            kwargs["on_long_pause"](1, {})
            events.append(("after_pause", None))
            return {}

        classifier.classify.side_effect = fake_classify

        with patch.multiple(
            "mpnames.ingest",
            fetch_names=Mock(return_value=records),
            fetch_identifiers=Mock(return_value=identifiers),
            fetch_orbits=Mock(side_effect=fake_fetch_orbits),
            fetch_discoveries=Mock(return_value={}),
            CitationClassifier=Mock(return_value=classifier),
        ):
            result = ingest(self.db_path, mode="add", limit=2, classifier_mode="ollama", wgsbn_sync=False)

        self.assertEqual(events[0], ("before_pause", None))
        self.assertEqual(events[1][0], "classify")
        self.assertIn("Name1 is a test city.", events[1][1])
        self.assertEqual(events[2], ("after_pause", None))
        self.assertEqual(classifier.classify.call_count, 2)
        self.assertEqual(result["inserted"], 2)

    def test_unique_orbit_count_ignores_lookup_aliases(self):
        orbit = OrbitRecord(
            permid_or_packed="1862",
            readable_designation="(1862)",
            absolute_magnitude_h=None,
            slope_g=None,
            epoch="",
            mean_anomaly=None,
            argument_perihelion=None,
            ascending_node=None,
            inclination=None,
            eccentricity=None,
            mean_daily_motion=None,
            semimajor_axis=None,
            uncertainty="",
            observations=None,
            oppositions=None,
            rms_residual=None,
            flags_hex=None,
            orbit_type="Apollo",
            is_neo=True,
            is_one_km_neo=False,
            is_pha=False,
        )
        self.assertEqual(_unique_orbit_count({"1862": orbit, "01862": orbit, "Apollo": orbit}), 1)

    def test_reclassify_can_filter_by_existing_category(self):
        self._upsert("1", identifier=_identifier("1", "Name1", "Named for a boat."))
        self._upsert("2", identifier=_identifier("2", "Name2", "Name2 is a German city."))
        connection = db.connect(self.db_path)
        db.replace_citation_categories(connection, "1", [Category("citation", "Other", "test", 1.0)])
        db.replace_citation_categories(connection, "2", [Category("citation", "Place", "test", 1.0)])
        connection.commit()
        connection.close()

        result = reclassify_existing(self.db_path, classifier_mode="rules", categories=["Other"])

        self.assertEqual(result["records"], 1)
        self.assertEqual(result["category_filter"], ["Other"])
        self.assertEqual(self._citation_categories("1"), ["Artifact/Concept"])
        self.assertEqual(self._citation_categories("2"), ["Place"])

    def test_reclassify_records_one_job_for_categories_and_person_facets(self):
        self._upsert("1", identifier=_identifier("1", "Ada", "Ada Example was a female astronomer."))

        result = reclassify_existing(self.db_path, classifier_mode="rules")

        connection = db.connect(self.db_path)
        job = connection.execute(
            "SELECT status, classifier_mode, prompts_json FROM classification_jobs WHERE job_id = ?",
            (result["job_id"],),
        ).fetchone()
        assignments = connection.execute(
            "SELECT target, job_id FROM classification_assignments WHERE permid = '1' ORDER BY target"
        ).fetchall()
        connection.close()

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["classifier_mode"], "rules")
        self.assertIn("citation_category", job["prompts_json"])
        self.assertIn("person_facet", job["prompts_json"])
        self.assertEqual([(row["target"], row["job_id"]) for row in assignments], [
            ("citation_category", result["job_id"]),
            ("person_facet", result["job_id"]),
        ])

    def test_reclassify_filter_accepts_no_citation_alias(self):
        result = reclassify_existing(
            self.db_path,
            classifier_mode="rules",
            categories=["no citation"],
            limit=0,
        )

        self.assertEqual(result["records"], 0)
        self.assertEqual(result["category_filter"], ["No Citation"])

    def _patched_sources(self, records, fake_identifiers):
        return patch.multiple(
            "mpnames.ingest",
            fetch_names=Mock(return_value=records),
            fetch_identifiers=Mock(side_effect=fake_identifiers),
            fetch_orbits=Mock(return_value={}),
            fetch_discoveries=Mock(return_value={}),
        )

    def _upsert(self, permid: str, identifier=None):
        connection = db.connect(self.db_path)
        db.initialize(connection)
        identifier = _identifier(permid, f"Name{permid}") if identifier is None else identifier
        db.upsert_minor_planet(
            connection,
            permid=permid,
            name_ascii=f"Name{permid}",
            name_display=f"Name{permid}",
            identifier=identifier,
            orbit=None,
        )
        connection.commit()
        connection.close()

    def _count(self):
        connection = db.connect(self.db_path)
        count = connection.execute("SELECT COUNT(*) AS c FROM minor_planets").fetchone()["c"]
        connection.close()
        return count

    def _mark_complete(self, permid: str):
        connection = db.connect(self.db_path)
        connection.execute(
            """
            UPDATE minor_planets
            SET discovery_date = '2000-01-01', discovery_site = 'Test Observatory',
                discoverer_text = 'Test Discoverer', orbit_type = 'Main-belt'
            WHERE permid = ?
            """,
            (permid,),
        )
        connection.commit()
        connection.close()

    def _permids(self):
        connection = db.connect(self.db_path)
        rows = connection.execute("SELECT permid FROM minor_planets ORDER BY CAST(permid AS INTEGER)").fetchall()
        connection.close()
        return [row["permid"] for row in rows]

    def _citation_categories(self, permid: str):
        connection = db.connect(self.db_path)
        rows = connection.execute(
            "SELECT value FROM categories WHERE permid = ? AND kind = 'citation' ORDER BY value",
            (permid,),
        ).fetchall()
        connection.close()
        return [row["value"] for row in rows]


if __name__ == "__main__":
    unittest.main()
