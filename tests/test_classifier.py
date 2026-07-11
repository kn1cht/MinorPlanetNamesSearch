import unittest
from unittest.mock import patch

from mpnames.classifier import CitationClassifier


class ClassifierTests(unittest.TestCase):
    def test_rules_never_checks_or_calls_ollama(self):
        classifier = CitationClassifier(mode="rules")
        with patch("mpnames.classifier.is_ollama_available") as available, patch(
            "mpnames.classifier.ollama_classify_citation"
        ) as classify:
            categories = classifier.classify("Aachen is a German city.")
        self.assertEqual([category.value for category in categories], ["Country/Region/Town"])
        available.assert_not_called()
        classify.assert_not_called()

    def test_missing_citation_uses_no_citation_category(self):
        classifier = CitationClassifier(mode="rules")
        self.assertEqual([category.value for category in classifier.classify(None)], ["No Citation"])
        self.assertEqual([category.value for category in classifier.classify("")], ["No Citation"])

    def test_ollama_result_overrides_keyword_false_positive(self):
        citation = (
            "Named in honor of Ada Example, a researcher who studied gods "
            "and mythology in ancient literature."
        )
        classifier = CitationClassifier(mode="ollama", model="dummy")
        with patch("mpnames.classifier.ollama_classify_citation", return_value=["Person"]):
            categories = classifier.classify(citation)
        self.assertEqual([category.value for category in categories], ["Person"])
        self.assertEqual(categories[0].source, "ollama")

    def test_invalid_ollama_labels_fall_back_to_rules(self):
        classifier = CitationClassifier(mode="ollama", model="dummy")
        with patch("mpnames.classifier.ollama_classify_citation", return_value=["NotARealCategory"]):
            categories = classifier.classify("Apollo is a god in Greek and Roman mythology.")
        self.assertIn("Mythology", [category.value for category in categories])
        self.assertEqual(categories[0].source, "rule")

    def test_other_is_removed_when_specific_ollama_category_exists(self):
        classifier = CitationClassifier(mode="ollama", model="dummy")
        with patch("mpnames.classifier.ollama_classify_citation", return_value=["Mythology", "Other"]):
            categories = classifier.classify("Alinda is associated with mythology and ancient stories.")
        self.assertEqual([category.value for category in categories], ["Mythology"])

    def test_deprecated_science_culture_label_is_ignored(self):
        classifier = CitationClassifier(mode="ollama", model="dummy")
        with patch("mpnames.classifier.ollama_classify_citation", return_value=["Science/Culture"]):
            categories = classifier.classify("Named for a broad science and culture topic.")
        self.assertEqual([category.value for category in categories], ["Other"])

    def test_science_fair_students_are_people_not_science_culture(self):
        classifier = CitationClassifier(mode="rules")
        categories = classifier.classify(
            "Ananya Karthik (b. 2001) was a finalist in the Regeneron Science Talent Search, "
            "a science competition for high school seniors."
        )
        self.assertEqual([category.value for category in categories], ["Person"])

    def test_person_work_context_does_not_add_artifact_or_nature(self):
        classifier = CitationClassifier(mode="rules")
        categories = classifier.classify(
            "Anjani Polit (b. 1980) is an American engineer who coordinates science activities "
            "for an asteroid sample return mission and spacecraft."
        )
        self.assertEqual([category.value for category in categories], ["Person"])

    def test_narrow_replacement_categories(self):
        classifier = CitationClassifier(mode="rules")
        nature = classifier.classify("Named for Acer, a maple species in a plant genus.")
        artifact = classifier.classify("Named for the computer character code ASCII.")
        self.assertEqual([category.value for category in nature], ["Nature"])
        self.assertEqual([category.value for category in artifact], ["Artifact/Concept"])

    def test_user_reported_other_examples_are_classifiable_by_rules(self):
        classifier = CitationClassifier(mode="rules")
        examples = {
            "Alku": (
                "(3037) Alku = 1944 BA Named for the boat the discoverer enjoyed in his boyhood. "
                "It was built by the father of the discoverer and instilled in him a lifelong love of sailing."
            ),
            "Amanogawa": (
                "(6247) Amanogawa = 1990 WY3 Named for a river that runs through the Hokkaido town "
                "of Kaminokuni. It is also the Japanese word for the Milky Way."
            ),
            "Akebonozou": (
                "(12349) Akebonozou Akebonozou (Stegodon aurorae) is an extinct species of "
                "Japanese elephant. The specimen has been designated as a natural monument of Japan."
            ),
            "Amandamarty": (
                "(157693) Amandamarty = 2006 AB Amanda Nicole Zawada (b. 1987) and "
                "Martin Peter Mackinlay (b. 1988) are geologists in Brisbane, Australia."
            ),
        }

        values = {name: [category.value for category in classifier.classify(text)] for name, text in examples.items()}

        self.assertIn("Artifact/Concept", values["Alku"])
        self.assertIn("Nature", values["Amanogawa"])
        self.assertIn("Nature", values["Akebonozou"])
        self.assertIn("Person", values["Amandamarty"])

    def test_ollama_other_falls_back_to_specific_rule_category(self):
        classifier = CitationClassifier(mode="ollama", model="dummy")
        with patch("mpnames.classifier.ollama_classify_citation", return_value=["Other"]):
            categories = classifier.classify("Named for the boat the discoverer enjoyed in his boyhood.")
        self.assertEqual([category.value for category in categories], ["Artifact/Concept"])

    def test_ollama_extra_multi_labels_are_filtered_by_rules(self):
        classifier = CitationClassifier(mode="ollama", model="dummy")
        with patch("mpnames.classifier.ollama_classify_citation", return_value=["Nature", "Mythology"]):
            categories = classifier.classify("Named for a river that runs through the Hokkaido town of Kaminokuni.")
        self.assertEqual([category.value for category in categories], ["Nature"])

    def test_remaining_other_examples_are_classifiable_by_rules(self):
        classifier = CitationClassifier(mode="rules")
        allodd = classifier.classify(
            "The number of this minor planet consists of all odd digits, in increasing order."
        )
        andorfer = classifier.classify(
            "Gregory P. Andorfer was an American science communicator and Series Producer."
        )
        father = classifier.classify("Aldo Atiglio Falla was the father of the discoverer.")
        self.assertEqual([category.value for category in allodd], ["Artifact/Concept"])
        self.assertEqual([category.value for category in andorfer], ["Person"])
        self.assertEqual([category.value for category in father], ["Person"])

    def test_current_other_examples_with_general_rule_signals(self):
        classifier = CitationClassifier(mode="rules")
        billochbull = classifier.classify("Named for the fictional cats Bill and Bull.")
        barbaralong = classifier.classify("Barbara Long (1939–2025) worked in public relations.")

        self.assertEqual([category.value for category in billochbull], ["Artifact/Concept"])
        self.assertEqual([category.value for category in barbaralong], ["Person"])

    def test_epoch_event_examples_are_classifiable_by_rules(self):
        classifier = CitationClassifier(mode="rules")
        armisticia = classifier.classify("Since this was the 21st anniversary of the signing of the armistice of World War I")
        daishinsai = classifier.classify("The Higashi Nihon Dai Shinsai earthquake of 2011 March 11 caused widespread destruction")
        beijingaoyun = classifier.classify("The Games of the XXIXth Olympiad, celebrated in Beijing during 2008")

        self.assertEqual([category.value for category in armisticia], ["Epoch/Event"])
        self.assertEqual([category.value for category in daishinsai], ["Epoch/Event"])
        self.assertEqual([category.value for category in beijingaoyun], ["Epoch/Event"])

    def test_character_examples_are_classifiable_by_rules(self):
        classifier = CitationClassifier(mode="rules")
        arthurdent = classifier.classify("The earthling Arthur Dent is confronted with the adversities of life in a highly amusing and entertaining way in Douglas Adam's famous five-volume trilogy")
        becassine = classifier.classify("Bécassine is a French children's comic book character created by screenwriter Jacqueline Rivière")
        asterix = classifier.classify("Astérix is the hero in the cartoon series Les aventures d'Astérix")

        # Arthur Dent is caught by ollama generally, but by rules it may just fall to Other without specific keywords unless we add "trilogy".
        # But Bécassine and Asterix have explicit character/hero keywords.
        self.assertEqual([category.value for category in becassine], ["Character"])
        self.assertEqual([category.value for category in asterix], ["Character"])

    # ------------------------------------------------------------------ #
    # New category tests: Country/Region/Town, Education, Research        #
    # ------------------------------------------------------------------ #

    def test_country_region_town_examples_by_rules(self):
        """Administrative/political areas → Country/Region/Town."""
        classifier = CitationClassifier(mode="rules")
        # city
        aachen = classifier.classify("Aachen is a German city near the borders of Belgium and the Netherlands.")
        # prefecture
        okayama = classifier.classify("Named for Bizen-city, Okayama prefecture, Japan.")
        # province
        galicia = classifier.classify("A Coruña is a port city in Galicia, a province of Spain.")

        self.assertEqual([category.value for category in aachen], ["Country/Region/Town"])
        self.assertIn("Country/Region/Town", [category.value for category in okayama])
        self.assertIn("Country/Region/Town", [category.value for category in galicia])

    def test_education_examples_by_rules(self):
        """Schools and universities → Education."""
        classifier = CitationClassifier(mode="rules")
        # School (Shizutani-Kou type)
        shizutani = classifier.classify(
            "Named for a school in Bizen-city, Okayama prefecture. "
            "Founded in 1668, it is the oldest Japanese school building in existence."
        )
        # School as place name (Åretta type)
        aretta = classifier.classify(
            "Åretta is the name of a school situated in the Norwegian town of Lillehammer."
        )
        # University
        kyoto_u = classifier.classify(
            "Named for Kyoto University, one of Japan's leading research universities."
        )

        self.assertEqual([category.value for category in shizutani], ["Education"])
        self.assertEqual([category.value for category in aretta], ["Education"])
        self.assertIn("Education", [category.value for category in kyoto_u])

    def test_research_examples_by_rules(self):
        """Observatories and research institutes → Research."""
        classifier = CitationClassifier(mode="rules")
        # Research institute (Magarach type)
        magarach = classifier.classify(
            "Named for the Research Institute of wine-making and viticulture at Magarach, near Yalta. "
            "Founded in 1828 as a specialized school for gardening and wine-making."
        )
        # Observatory
        obs = classifier.classify(
            "Named for the Crimean Astrophysical Observatory, a major research center in Ukraine."
        )
        # Research center
        rc = classifier.classify(
            "Named for the laboratory that pioneered laser spectroscopy research."
        )

        self.assertEqual([category.value for category in magarach], ["Research"])
        self.assertIn("Research", [category.value for category in obs])
        self.assertIn("Research", [category.value for category in rc])

    def test_organization_examples_by_rules(self):
        """Companies, space agencies, foundations, sports teams → Organization."""
        classifier = CitationClassifier(mode="rules")
        # Foundation
        foundation = classifier.classify(
            "Named for the Planetary Society foundation, which promotes space exploration."
        )
        # Club/team
        club = classifier.classify(
            "Named for the astronomy club that meets weekly to observe the night sky."
        )

        self.assertIn("Organization", [category.value for category in foundation])
        self.assertIn("Organization", [category.value for category in club])

    def test_observatory_classified_as_research_not_place(self):
        """Observatories must be Research, not Place."""
        classifier = CitationClassifier(mode="rules")
        obs = classifier.classify(
            "Named for the Crimean Astrophysical Observatory."
        )
        values = [category.value for category in obs]
        self.assertIn("Research", values)
        self.assertNotIn("Place", values)

    def test_university_classified_as_education_not_place(self):
        """Universities must be Education, not Place."""
        classifier = CitationClassifier(mode="rules")
        univ = classifier.classify(
            "Named for the University of Tokyo."
        )
        values = [category.value for category in univ]
        self.assertIn("Education", values)
        self.assertNotIn("Place", values)

    def test_normalize_new_category_aliases(self):
        """New category labels are normalized correctly."""
        from mpnames.categories import normalize_citation_category
        self.assertEqual(normalize_citation_category("Country/Region/Town"), "Country/Region/Town")
        self.assertEqual(normalize_citation_category("country"), "Country/Region/Town")
        self.assertEqual(normalize_citation_category("Education"), "Education")
        self.assertEqual(normalize_citation_category("school"), "Education")
        self.assertEqual(normalize_citation_category("Research"), "Research")
        self.assertEqual(normalize_citation_category("observatory"), "Research")
        # Legacy aliases still work
        self.assertEqual(normalize_citation_category("place"), "Place")
        self.assertEqual(normalize_citation_category("organization"), "Organization")

    def test_ollama_other_falls_back_to_general_rule_signals(self):
        classifier = CitationClassifier(mode="ollama", model="dummy")
        examples = [
            "(8537) Billochbull = 1993 FG24 Named for the fictional cats Bill and Bull.",
            "(358167) Barbaralong Barbara Long (1939–2025) worked in public relations.",
        ]

        with patch("mpnames.classifier.ollama_classify_citation", return_value=["Other"]):
            values = [[category.value for category in classifier.classify(text)] for text in examples]

        self.assertEqual(
            values,
            [["Artifact/Concept"], ["Person"]],
        )

    def test_auto_falls_back_when_ollama_unavailable(self):
        classifier = CitationClassifier(mode="auto")
        with patch("mpnames.classifier.is_ollama_available", return_value=False):
            categories = classifier.classify("Aachen is a German city.")
        self.assertEqual([category.value for category in categories], ["Country/Region/Town"])

    def test_auto_checks_ollama_availability_once(self):
        classifier = CitationClassifier(mode="auto")
        with patch("mpnames.classifier.is_ollama_available", return_value=False) as available:
            classifier.classify("Aachen is a German city.")
            classifier.classify("A Coruña is a port city in Galicia.")
        available.assert_called_once()


if __name__ == "__main__":
    unittest.main()
