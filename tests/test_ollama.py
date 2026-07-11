import json
import unittest
from unittest.mock import patch

from mpnames.ollama import classify_citation


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class OllamaTests(unittest.TestCase):
    def test_other_result_gets_reviewed_with_second_prompt(self):
        responses = [
            _FakeResponse({"response": '{"categories":["Other"]}'}),
            _FakeResponse({"response": '{"categories":["Artifact/Concept"]}'}),
        ]

        with patch("mpnames.ollama.urllib.request.urlopen", side_effect=responses) as urlopen:
            labels = classify_citation(
                "(69263) Big Ben is the nickname of both the great bell and clock tower.",
                model="dummy",
            )

        self.assertEqual(labels, ["Artifact/Concept"])
        self.assertEqual(urlopen.call_count, 2)

    def test_overbroad_result_gets_reviewed_with_second_prompt(self):
        responses = [
            _FakeResponse(
                {
                    "response": (
                        '{"categories":["Artifact/Concept","Mythology","Place",'
                        '"Nature","Organization","Person"]}'
                    )
                }
            ),
            _FakeResponse({"response": '{"categories":["Artifact/Concept"]}'}),
        ]

        with patch("mpnames.ollama.urllib.request.urlopen", side_effect=responses) as urlopen:
            labels = classify_citation(
                "(2129) Cosicosi = 1973 SJ The Italian characterization of indifference.",
                model="dummy",
            )

        self.assertEqual(labels, ["Artifact/Concept"])
        self.assertEqual(urlopen.call_count, 2)

    def test_two_specific_categories_get_reviewed(self):
        responses = [
            _FakeResponse({"response": '{"categories":["Artifact/Concept","Place"]}'}),
            _FakeResponse({"response": '{"categories":["Artifact/Concept"]}'}),
        ]

        with patch("mpnames.ollama.urllib.request.urlopen", side_effect=responses) as urlopen:
            labels = classify_citation(
                "(69263) Big Ben is the nickname of both the great bell and clock tower.",
                model="dummy",
            )

        self.assertEqual(labels, ["Artifact/Concept"])
        self.assertEqual(urlopen.call_count, 2)

    def test_review_that_stays_multi_label_picks_best_across_all_tries(self):
        # モデルがすべての試行で複数カテゴリを返し続けた場合、
        # _select_best_labels が最小タグ数・最頻出の結果を選ぶ。
        # 全5回で ['Artifact/Concept', 'Place'] が返るので、
        # アルファベット順でソートされた同じ結果が採用される。
        multi = _FakeResponse({"response": '{"categories":["Artifact/Concept","Place"]}'})
        responses = [multi] * 5  # MAX_CLASSIFY_TRIES 分

        with patch("mpnames.ollama.urllib.request.urlopen", side_effect=responses) as urlopen:
            labels = classify_citation(
                "(69263) Big Ben is the nickname of both the great bell and clock tower.",
                model="dummy",
            )

        self.assertEqual(sorted(labels), ["Artifact/Concept", "Place"])
        self.assertEqual(urlopen.call_count, 5)


    def test_specific_result_does_not_get_reviewed(self):
        with patch(
            "mpnames.ollama.urllib.request.urlopen",
            return_value=_FakeResponse({"response": '{"categories":["Person"]}'}),
        ) as urlopen:
            labels = classify_citation(
                "(358167) Barbaralong Barbara Long (1939-2025) worked in public relations.",
                model="dummy",
            )

        self.assertEqual(labels, ["Person"])
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
