from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mpnames.ingest import fetch_identifiers, ingest
from mpnames.mpnames_parser import NameRecord
from mpnames.progress import ProgressReporter


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b"{}"


class ProgressTests(unittest.TestCase):
    def test_identifier_progress_reports_batches_and_long_pause(self):
        output = StringIO()
        progress = ProgressReporter(stream=output)
        records = [
            NameRecord(permid=str(index), name_ascii=f"Name{index}", name_display=f"Name{index}")
            for index in range(11)
        ]

        with patch("mpnames.ingest.urllib.request.urlopen", return_value=_FakeResponse()), patch(
            "mpnames.ingest.time.sleep"
        ):
            fetch_identifiers(
                records,
                batch_size=1,
                delay=0,
                pause_every=10,
                pause_seconds=5,
                progress=progress,
            )

        text = output.getvalue()
        self.assertIn("Identifier API request: 1/11", text)
        self.assertIn("Identifier API request: 11/11", text)
        self.assertIn("Rate limit pause after 10 Identifier API requests: 5s", text)

    def test_ingest_progress_reports_major_phases(self):
        output = StringIO()
        progress = ProgressReporter(stream=output)
        records = [NameRecord(permid="1", name_ascii="Name1", name_display="Name1")]

        with tempfile.TemporaryDirectory() as tempdir, patch.multiple(
            "mpnames.ingest",
            fetch_names=Mock(return_value=records),
            fetch_identifiers=Mock(return_value={"Name1": {"permid": "1", "name": "Name1", "citation": None}}),
            fetch_orbits=Mock(return_value={}),
            fetch_discoveries=Mock(return_value={}),
        ):
            ingest(Path(tempdir) / "progress.sqlite3", mode="add", limit=1, progress=progress)

        text = output.getvalue()
        self.assertIn("Fetching named-object list", text)
        self.assertIn("selected 1 records", text)
        self.assertIn("Classifying and writing 1 selected records", text)
        self.assertIn("Ingest complete", text)


if __name__ == "__main__":
    unittest.main()
