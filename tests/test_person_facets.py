import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mpnames import db
from mpnames.person_facets import CitationFacet, PersonFacetClassifier


class PersonFacetRuleTests(unittest.TestCase):
    def setUp(self):
        self.classifier = PersonFacetClassifier(mode="rules")

    def test_person_can_have_scientist_role_and_explicit_female_gender(self):
        text = "Ada Example was a female astronomer. She studied comets."
        facets = self.classifier.classify(text, ["Person"])

        self.assertIn(CitationFacet("person_role", "Scientist", "Ada Example was a female astronomer.", "rule", 0.78), facets)
        self.assertIn(CitationFacet("entity_gender", "Female", "Ada Example was a female astronomer.", "rule", 0.78), facets)

    def test_mythological_entity_keeps_primary_category_but_can_have_explicit_gender(self):
        facets = self.classifier.classify("Athena is a Greek goddess of wisdom.", ["Mythology"])

        self.assertEqual([facet.value for facet in facets if facet.kind == "person_role"], [])
        self.assertEqual([facet.value for facet in facets if facet.kind == "entity_gender"], ["Female"])

    def test_person_without_evidence_is_unknown_and_nonperson_is_not_applicable(self):
        unknown = self.classifier.classify("Alex Example was a noted astronomer.", ["Person"])
        nonperson = self.classifier.classify("Named for the city of Exampleton.", ["Country/Region/Town"])

        self.assertEqual([facet.value for facet in unknown if facet.kind == "entity_gender"], ["Unknown"])
        self.assertEqual([facet.value for facet in nonperson if facet.kind == "entity_gender"], ["Non-person"])

    def test_multiple_named_people_without_explicit_gender_remain_unknown(self):
        facets = self.classifier.classify("Named for Alice Example and Bob Example.", ["Person"])

        self.assertEqual([facet.value for facet in facets if facet.kind == "entity_gender"], ["Unknown"])

    def test_unrelated_male_pronoun_or_job_and_does_not_override_named_person_gender(self):
        facets = self.classifier.classify(
            "Named for Cleopatra Selene II, who married the African king Juba II and raised twins.",
            ["Person"],
        )

        self.assertEqual([facet.value for facet in facets if facet.kind == "entity_gender"], ["Unknown"])

    def test_research_institute_director_is_not_assumed_to_be_a_cultural_role(self):
        facets = self.classifier.classify("Lee Example is director of an astronomical observatory.", ["Person"])

        self.assertNotIn("Cultural/Public Figure", [facet.value for facet in facets if facet.kind == "person_role"])

    def test_ollama_facet_is_accepted_only_with_exact_citation_evidence(self):
        classifier = PersonFacetClassifier(mode="ollama", model="dummy")
        text = "Ada Example was a female astronomer."
        with patch(
            "mpnames.person_facets.ollama_extract_person_facets",
            return_value={
                "roles": [{"value": "Scientist", "evidence": "Ada Example was a female astronomer."}],
                "gender": {"value": "Female", "evidence": "not present"},
            },
        ):
            facets = classifier.classify(text, ["Person"])

        scientist = [facet for facet in facets if facet.kind == "person_role" and facet.value == "Scientist"]
        gender = [facet for facet in facets if facet.kind == "entity_gender"]
        self.assertEqual(scientist[0].source, "rule")
        self.assertEqual(gender[0].source, "rule")

    def test_ollama_can_assign_multiple_only_with_an_exact_evidence_excerpt(self):
        classifier = PersonFacetClassifier(mode="ollama", model="dummy")
        text = "Named for Alice Example and Bob Example."
        with patch(
            "mpnames.person_facets.ollama_extract_person_facets",
            return_value={"roles": [], "gender": {"value": "Multiple/Mixed", "evidence": text}},
        ):
            facets = classifier.classify(text, ["Person"])

        gender = [facet for facet in facets if facet.kind == "entity_gender"]
        self.assertEqual(gender, [CitationFacet("entity_gender", "Multiple/Mixed", text, "ollama", 0.85)])


class PersonFacetDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "facets.sqlite3"
        self.connection = db.connect(self.db_path)
        db.initialize(self.connection)
        db.upsert_minor_planet(
            self.connection,
            permid="900001",
            name_ascii="Facetperson",
            name_display="Facetperson",
            identifier={"permid": "900001", "citation": "Ada Example was a female astronomer."},
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        self.tempdir.cleanup()

    def test_facets_are_searchable_exposed_and_include_evidence(self):
        result = db.search(self.connection, person_role="Scientist", gender="Female")
        item = result["items"][0]
        detail = db.get_object(self.connection, "900001")
        stats = db.stats(self.connection)

        self.assertEqual(result["total"], 1)
        self.assertEqual(item["person_roles"], ["Scientist"])
        self.assertEqual(item["gender"], "Female")
        self.assertTrue(any(facet["evidence_text"] for facet in detail["citation_facets"]))
        self.assertIn("Scientist", {item["value"] for item in stats["person_roles"]})
        self.assertIn("Female", {item["value"] for item in stats["genders"]})
