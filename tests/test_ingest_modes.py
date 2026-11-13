from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from unittest.mock import Mock, patch

from mpnames import db
from mpnames.__main__ import main
from mpnames.categories import Category
from mpnames.ingest import _unique_orbit_count, ingest, reclassify_existing
from mpnames.mpcorb import OrbitRecord
from mpnames.mpnames_parser import NameRecord
from mpnames.numbered_mps import DiscoveryRecord
from mpnames.progress import ProgressReporter
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

    def test_mpc_name_sync_warns_then_updates_names_and_search_only(self):
        self._upsert("1", identifier=_identifier("1", "Name1", "An existing citation."))
        self._mark_complete("1")
        self._upsert("3")  # Absent from the MPC list; leave it alone.
        self._upsert("4")
        self._upsert("5")
        mpc_names = [
            NameRecord("1", "Newname", "Néwname"),
            NameRecord("4", "Suran", "Suran"),
            NameRecord("5", "Othername", "Othername"),
            *_records("2"),
        ]
        details = Mock(side_effect=AssertionError("Name sync does not fetch object details"))
        output = StringIO()
        with patch.multiple(
            "mpnames.ingest", fetch_names=Mock(return_value=mpc_names), fetch_identifiers=details,
            fetch_orbits=details, fetch_discoveries=details, _collect_new_wgsbn_bulletins=details,
        ):
            warn = ingest(self.db_path, limit=0, wgsbn_sync=False, progress=ProgressReporter(stream=output))
            connection = db.connect(self.db_path)
            before = dict(connection.execute("SELECT * FROM minor_planets WHERE permid = '1'").fetchone())
            categories = self._citation_categories("1")
            self.assertEqual(before["name_display"], "Name1")
            self.assertEqual(db.search(connection, q="Name1", q_target="name")["total"], 1)
            self.assertEqual(warn["mpc_name_differences"], 3)
            self.assertEqual(warn["mpc_names_synced"], 0)
            self.assertIn("Warning: MPC name differs for (1): display 'Name1' -> 'Néwname'", output.getvalue())

            synced = ingest(self.db_path, limit=0, sync_mpc_names=("1", "5"))
            repeat = ingest(self.db_path, limit=0, sync_mpc_names=("1", "5"))
            after = dict(connection.execute("SELECT * FROM minor_planets WHERE permid = '1'").fetchone())
            self.assertEqual(db.search(connection, q="Newname", q_target="name")["total"], 1)
            self.assertEqual(db.search(connection, q="Name1", q_target="name")["total"], 0)
            self.assertEqual(db.get_object(connection, "4")["name_display"], "Name4")
            self.assertEqual(db.get_object(connection, "5")["name_display"], "Othername")
            connection.close()

        self.assertEqual((synced["mpc_name_differences"], synced["mpc_names_synced"]), (3, 2))
        self.assertEqual((repeat["mpc_name_differences"], repeat["mpc_names_synced"]), (1, 0))
        self.assertEqual((after["name_ascii"], after["name_display"]), ("Newname", "Néwname"))
        fields = before.keys() - {"name_ascii", "name_display", "updated_at"}
        self.assertEqual({k: before[k] for k in fields}, {k: after[k] for k in fields})
        self.assertEqual(self._citation_categories("1"), categories)
        self.assertEqual(self._permids(), ["1", "3", "4", "5"])

    def test_ingest_cli_guides_selective_sync_and_rejects_bare_option(self):
        self._upsert("1")
        args = ["ingest", "--db", str(self.db_path), "--limit", "0", "--quiet"]
        mpc = Mock(return_value=[NameRecord("1", "Newname", "Newname")])
        with patch.multiple(
            "mpnames.ingest", fetch_names=mpc,
            _collect_new_wgsbn_bulletins=Mock(return_value={"fetched_bulletins": 0, "fetched_namings": 0}),
        ):
            with redirect_stdout(StringIO()) as output:
                self.assertEqual(main(args), 0)
            self.assertIn("--sync-mpc-names NUMBER1 NUMBER2", output.getvalue())
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                main([*args, "--sync-mpc-names"])
            mpc.assert_called_once()

    def test_wgsbn_ingest_can_opt_in_to_mpc_name_sync(self):
        self._upsert("1")
        with patch("mpnames.ingest.fetch_names", return_value=[NameRecord("1", "Newname", "Newname")]) as fetch:
            synced = ingest(self.db_path, source="wgsbn", sync_mpc_names=("1",), wgsbn_sync=False)
        fetch.assert_called_once()
        self.assertEqual(synced["selected_records"], 0)
        self.assertEqual(synced["mpc_names_synced"], 1)

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

    def test_wgsbn_add_imports_cached_and_new_names_once_without_mpc_list(self):
        self._upsert("1")
        archive = "https://www.wgsbn-iau.org/files/json/index.html"
        cached_url = "https://www.wgsbn-iau.org/files/json/V006/WGSBNBull_V006_016.json"
        new_url = cached_url.replace("_016", "_017")
        connection = db.connect(self.db_path)
        db.replace_wgsbn_bulletin(
            connection, source_url=cached_url, volume=6, issue=16,
            published_date="2026-09-28", published_year=2026,
            namings=[WgsbnNaming("1", "AlreadyPresent", None, None), WgsbnNaming("2", "Étoile", "A French town.", "Ref 2")],
        )
        connection.commit()
        connection.close()
        archive_body = (
            '<li>Volume 6, #16 <a href="files/json/V006/WGSBNBull_V006_016.json">UTF-8 only</a> (2026 Sept. 28)\n'
            '<li>Volume 6, #17 <a href="files/json/V006/WGSBNBull_V006_017.json">UTF-8 only</a> (2026 Oct. 19)'
        )
        responses = {
            archive: archive_body,
            new_url: '[{"mp_number":"2","name":"Repeat"},{"mp_number":"3","name":"NewName","citation":"A new citation."}]',
        }
        identifiers = Mock(return_value={"2": _identifier("2", "Unnamed", "An outdated citation.")})
        discoveries = {"2": DiscoveryRecord("2", "", "2000-01-01", "Test Site", "Test Discoverer", ("Test Discoverer",))}
        mpc_names = Mock(side_effect=AssertionError("WGSBN ingest must not load the MPC list"))
        with patch.multiple(
            "mpnames.ingest", fetch_names=mpc_names, fetch_identifiers=identifiers,
            fetch_orbits=Mock(return_value={}), fetch_discoveries=Mock(return_value=discoveries),
            _read_text_url=Mock(side_effect=responses.__getitem__),
        ):
            first = ingest(self.db_path, source="wgsbn", limit=1)
            second = ingest(self.db_path, source="wgsbn", limit=1)
            repeat = ingest(self.db_path, source="wgsbn")

        self.assertEqual([r["inserted"] for r in (first, second, repeat)], [1, 1, 0])
        self.assertEqual(first["wgsbn_bulletins_fetched"], 1)
        self.assertEqual(second["wgsbn_bulletins_fetched"], 0)
        self.assertEqual([[n.permid for n in c.args[0]] for c in identifiers.call_args_list], [["2"], ["3"]])
        with db.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT name_ascii, name_display, citation_text, packed_permid, discovery_site, naming_source_url "
                "FROM minor_planets ORDER BY permid"
            ).fetchall()
        connection.close()
        self.assertEqual(rows[0][1], "Name1")
        self.assertEqual(tuple(rows[1]), ("Etoile", "Étoile", "A French town.", "00002", "Test Site", cached_url))
        self.assertEqual(tuple(rows[2][:3]), ("NewName", "NewName", "A new citation."))

    def test_wgsbn_add_keeps_name_and_citation_when_mpc_is_unavailable(self):
        self._upsert("1")
        connection = db.connect(self.db_path)
        db.replace_wgsbn_bulletin(
            connection, source_url="https://example.org/bulletin.json", volume=6, issue=1,
            published_date="2026-01-12", published_year=2026,
            namings=[WgsbnNaming("2", "Example", "A & B < C.", None)],
        )
        # Older caches can contain a naming that has since been withdrawn.
        connection.execute("INSERT INTO naming_publications SELECT '579513', source_url, published_date, "
                           "published_year, 'Withdrawn', citation_text, reference FROM naming_publications")
        connection.commit()
        connection.close()
        with patch.multiple(
            "mpnames.ingest", fetch_identifiers=Mock(side_effect=URLError("offline")),
            _fetch_orbit_payload=Mock(side_effect=URLError("offline")),
            fetch_discoveries=Mock(side_effect=URLError("offline")),
        ):
            result = ingest(self.db_path, source="wgsbn", wgsbn_sync=False)

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self._permids(), ["1", "2"])
        connection = db.connect(self.db_path)
        row = connection.execute(
            "SELECT iau_designation, citation_text, orbit_type FROM minor_planets WHERE permid = '2'"
        ).fetchone()
        connection.close()
        self.assertEqual(tuple(row), ("(2)", "A & B < C.", None))

    def test_ingest_classifies_ready_records_during_orbit_pause(self):
        records = _records("1", "2")
        identifiers = {record.name_ascii: _identifier(record.permid, record.name_ascii) for record in records}
        events: list[tuple[str, str | None]] = []
        classifier = Mock()
        citation_factory = Mock(return_value=classifier)
        facet_factory = Mock(return_value=Mock(classify=Mock(return_value=[])))

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
            CitationClassifier=citation_factory,
            PersonFacetClassifier=facet_factory,
        ):
            result = ingest(
                self.db_path, mode="add", limit=2, classifier_mode="ollama", wgsbn_sync=False,
                ollama_timeout=120, ollama_think_on_review=False,
            )

        self.assertEqual(events[0], ("before_pause", None))
        self.assertEqual(events[1][0], "classify")
        self.assertIn("Name1 is a test city.", events[1][1])
        self.assertEqual(events[2], ("after_pause", None))
        self.assertEqual(classifier.classify.call_count, 2)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(citation_factory.call_args.kwargs["timeout"], 120)
        self.assertFalse(citation_factory.call_args.kwargs["think_on_review"])
        self.assertEqual(facet_factory.call_args.kwargs["timeout"], 120)
        connection = db.connect(self.db_path)
        job = connection.execute("SELECT ollama_timeout, ollama_think_on_review FROM classification_jobs").fetchone()
        connection.close()
        self.assertEqual(tuple(job), (120, 0))

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

    def test_reclassify_source_and_job_select_only_rule_categories_in_that_job(self):
        for permid in ("1", "2", "3"):
            self._upsert(permid)
        batch = reclassify_existing(self.db_path, classifier_mode="rules")
        self._upsert("4")  # Rule result outside the batch.
        connection = db.connect(self.db_path)
        ollama = Category("citation", "Person", "ollama", 0.85)
        db.replace_citation_categories(connection, "2", [ollama])
        db.replace_citation_categories(connection, "3", [ollama, Category("citation", "Place")])
        facets_before = db.get_object(connection, "1")["citation_facets"]
        connection.commit()
        connection.close()

        classifier = Mock()
        classifier.classify.return_value = [ollama]
        with patch("mpnames.ingest.CitationClassifier", return_value=classifier), patch(
            "mpnames.ingest.PersonFacetClassifier", side_effect=AssertionError("citation-only must skip facets"),
        ), redirect_stdout(StringIO()) as output:
            self.assertEqual(main([
                "reclassify", "--db", str(self.db_path), "--classifier", "rules", "--source", "rule",
                "--job-id", batch["job_id"], "--citation-only", "--quiet",
            ]), 0)

        classifier.classify.assert_called_once()
        self.assertIn("Reclassified 1 records", output.getvalue())
        connection = db.connect(self.db_path)
        self.assertEqual(db.get_object(connection, "1")["citation_facets"], facets_before)
        assignments = {
            (row["permid"], row["target"]): row["job_id"]
            for row in connection.execute("SELECT permid, target, job_id FROM classification_assignments")
        }
        connection.close()
        self.assertNotEqual(assignments["1", "citation_category"], batch["job_id"])
        self.assertEqual(assignments["1", "person_facet"], batch["job_id"])
        self.assertEqual(assignments["2", "citation_category"], batch["job_id"])
        self.assertEqual(assignments["3", "citation_category"], batch["job_id"])
        self.assertNotIn(("4", "citation_category"), assignments)

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
