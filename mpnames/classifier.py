"""Citation classification strategies."""

from __future__ import annotations

from dataclasses import dataclass

from .categories import (
    CITATION_CATEGORY_VALUES,
    Category,
    categorize_citation,
    citation_categories_from_values,
)
from .ollama import DEFAULT_HOST, MAX_CLASSIFY_TRIES, classify_citation as ollama_classify_citation, is_ollama_available


@dataclass
class CitationClassifier:
    mode: str = "rules"
    model: str | None = None
    host: str = DEFAULT_HOST
    timeout: float = 20.0
    max_tries: int = MAX_CLASSIFY_TRIES
    think: bool = False
    think_on_review: bool = True
    _ollama_available: bool | None = None

    def classify(self, citation_text: str | None) -> list[Category]:
        if not citation_text:
            return [Category("citation", "No Citation", confidence=1.0)]

        # Strip trailing bibliographic references like "(Author, Journal, Vol, Page)"
        # This prevents false positives from words like "Society" or "Observatory" in the journal name.
        import re
        clean_text = citation_text.strip()
        clean_text = re.sub(
            r'\s*\([^)]*(?:society|journal|notices|dictionary|vol|pp?\.|\d+,\s*\d+)[^)]*\)\.?\s*$',
            '',
            clean_text,
            flags=re.IGNORECASE
        )

        rule_categories = categorize_citation(clean_text)

        if self.mode == "rules":
            return rule_categories

        if self.mode not in {"auto", "ollama"}:
            raise ValueError(f"Unknown classifier mode: {self.mode}")

        if self.mode == "auto" and not self._is_ollama_available():
            return rule_categories

        try:
            labels = ollama_classify_citation(
                clean_text,
                model=self.model,
                host=self.host,
                timeout=self.timeout,
                max_tries=self.max_tries,
                think=self.think,
                think_on_review=self.think_on_review,
            )
        except Exception as e:
            import sys
            print(f"Ollama classification failed: {e}", file=sys.stderr)
            return rule_categories

        categories = citation_categories_from_values(labels, source="ollama", confidence=0.85)
        return _reconcile_ollama_categories(categories, rule_categories)

    def _is_ollama_available(self) -> bool:
        if self._ollama_available is None:
            self._ollama_available = is_ollama_available(self.host)
        return self._ollama_available


def _only_uncertain_categories(categories: list[Category]) -> bool:
    return bool(categories) and all(category.value in {"No Citation", "Other", "Unknown"} for category in categories)


# Number of distinct specific citation category values (excluding uncertain placeholders).
# When Ollama returns this many or more, the result is treated as "too broad to be useful".
_SPECIFIC_CATEGORY_COUNT = len(CITATION_CATEGORY_VALUES - {"No Citation", "Other", "Unknown"})
_OVERBROAD_THRESHOLD = 4  # If it assigns 4 or more categories, it's considered uninformative.


def _is_overbroad(categories: list[Category]) -> bool:
    """Return True when so many categories were assigned that the result is uninformative.

    This catches the common failure mode where the model returns (almost)
    all available categories at once rather than narrowing down.
    """
    specific = [
        category for category in categories
        if category.value not in {"No Citation", "Other", "Unknown"}
    ]
    return len(specific) >= _OVERBROAD_THRESHOLD


def _reconcile_ollama_categories(ollama_categories: list[Category], rule_categories: list[Category]) -> list[Category]:
    """Merge Ollama and rule-based categories, preferring the more specific result.

    Decision table:
    - No Ollama output → fall back to rules.
    - Ollama says only uncertain (Other/Unknown/No Citation) but rules have something
      specific → use rules.
    - Ollama result is overbroad (≥ threshold specific categories) → fall back to rules
      so that at least a keyword-matched answer is returned instead of everything.
    - Ollama returned 1 category, or rules are only uncertain → trust Ollama.
    - Otherwise → filter Ollama to categories that also appear in rule output.
    """
    if not ollama_categories:
        return rule_categories
    if _only_uncertain_categories(ollama_categories) and not _only_uncertain_categories(rule_categories):
        return rule_categories
    # If the model returned too many categories at once it hasn't really classified;
    # prefer rule-based output (even if it is uncertain) over a meaningless "all of them".
    if _is_overbroad(ollama_categories):
        return rule_categories
    if len(ollama_categories) <= 1 or _only_uncertain_categories(rule_categories):
        return ollama_categories

    rule_values = {
        category.value for category in rule_categories if category.value not in {"No Citation", "Other", "Unknown"}
    }
    filtered = [category for category in ollama_categories if category.value in rule_values]
    return filtered or ollama_categories
