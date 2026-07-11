import json
import unittest
from unittest.mock import Mock, patch

from mpnames.ingest import _sleep_after_mpc_request, fetch_identifiers
from mpnames.mpnames_parser import NameRecord


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class IngestRateLimitTests(unittest.TestCase):
    def test_identifier_fetch_pauses_every_ten_requests(self):
        records = [
            NameRecord(permid=str(index), name_ascii=f"Name{index}", name_display=f"Name{index}")
            for index in range(25)
        ]

        def fake_urlopen(request, timeout):
            return _FakeResponse({})

        with patch("mpnames.ingest.urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "mpnames.ingest.time.sleep"
        ) as sleep:
            fetch_identifiers(
                records,
                batch_size=1,
                delay=0.25,
                pause_every=10,
                pause_seconds=5.0,
            )

        sleeps = [call.args[0] for call in sleep.call_args_list]
        self.assertEqual(sleeps.count(5.0), 2)
        self.assertEqual(sleeps[9], 5.0)
        self.assertEqual(sleeps[19], 5.0)
        self.assertEqual(sleeps.count(0.25), 22)

    def test_identifier_fetch_rejects_invalid_batch_size(self):
        with self.assertRaises(ValueError):
            fetch_identifiers([], batch_size=0)

    def test_long_pause_work_time_is_subtracted_from_sleep(self):
        work = Mock()

        with patch("mpnames.ingest.time.monotonic", side_effect=[100.0, 103.25]), patch(
            "mpnames.ingest.time.sleep"
        ) as sleep:
            _sleep_after_mpc_request(
                request_number=10,
                has_more=True,
                delay=0.25,
                pause_every=10,
                pause_seconds=5.0,
                label="Orbit API",
                long_pause_work=work,
            )

        work.assert_called_once()
        sleep.assert_called_once_with(1.75)

    def test_identifier_fetch_fallback_on_http_error(self):
        records = [
            NameRecord(permid="12383", name_ascii="Eboshi", name_display="Eboshi"),
            NameRecord(permid="60558", name_ascii="Echeclus", name_display="Echeclus"),
        ]

        import urllib.error

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            ids = payload.get("ids", [])
            group = payload.get("group")
            
            # If it's a batch of 2, raise 500 error
            if len(ids) == 2:
                raise urllib.error.HTTPError(
                    request.full_url, 500, "Internal Server Error", {}, None
                )
            
            # If it's 60558 and group is Minor Planets, raise 500 error
            if ids == ["60558"] and group == "Minor Planets":
                raise urllib.error.HTTPError(
                    request.full_url, 500, "Internal Server Error", {}, None
                )
            
            # If it's 12383 (group=Minor Planets), return success
            if ids == ["12383"] and group == "Minor Planets":
                return _FakeResponse({"12383": {"permid": "12383"}})
            
            # If it's 60558 (without group), return success
            if ids == ["60558"] and group is None:
                return _FakeResponse({"60558": {"permid": "60558"}})

            raise ValueError(f"Unexpected query: ids={ids}, group={group}")

        with patch("mpnames.ingest.urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "mpnames.ingest.time.sleep"
        ) as sleep:
            results = fetch_identifiers(
                records,
                batch_size=2,
                delay=0.1,
                pause_every=10,
                pause_seconds=5.0,
            )

        self.assertEqual(results, {
            "12383": {"permid": "12383"},
            "60558": {"permid": "60558"}
        })
        self.assertTrue(sleep.call_count >= 2)


if __name__ == "__main__":
    unittest.main()
