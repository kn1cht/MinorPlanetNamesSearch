"""Evidence-based person-role and entity-gender facets for naming citations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .ollama import extract_person_facets as ollama_extract_person_facets
from .ollama import is_ollama_available


PERSON_ROLE_VALUES = {"Scientist", "Cultural/Public Figure", "Discoverer-relative/Friend"}
GENDER_VALUES = {"Female", "Male", "Unknown", "Non-person", "Multiple/Mixed"}
PERSONLIKE_CITATION_CATEGORIES = {"Person", "Mythology", "Character"}


@dataclass(frozen=True)
class CitationFacet:
    kind: str
    value: str
    evidence_text: str | None
    source: str = "rule"
    confidence: float = 0.7


_SCIENTIST_RE = re.compile(
    r"\b(?:astronomer|astrophysicist|physicist|mathematician|chemist|biochemist|"
    r"biologist|geologist|scientist|researcher|paleontologist|engineer|computer programmer)\b",
    re.IGNORECASE,
)
_CULTURAL_PUBLIC_RE = re.compile(
    r"\b(?:author|writer|poet|novelist|composer|musician|singer|artist|painter|"
    r"sculptor|actor|actress|filmmaker|film director|photographer|"
    r"illustrator|journalist|politician|president|minister|athlete|olympian)\b",
    re.IGNORECASE,
)
_DISCOVERER_RELATION_RE = re.compile(
    r"\b(?:wife|husband|daughter|son|mother|father|parent|sister|brother|"
    r"grandmother|grandfather|relative|friend|colleague|companion)\s+"
    r"(?:of|to)\s+(?:the\s+)?discoverer\b|\bthe\s+discoverer['’]s\s+"
    r"(?:wife|husband|daughter|son|mother|father|parent|sister|brother|friend|colleague)\b",
    re.IGNORECASE,
)
_FEMALE_RE = re.compile(
    r"\b(?:she|hers)\b|\b(?:was|is)\s+(?:an?\s+)?(?:female|woman|girl)\b|"
    r"\b(?:goddess)\b|\bnamed(?:\s+by [^.]{0,80})?\s+(?:in\s+honou?r\s+of|for|after)\s+"
    r"(?:(?:the|a|an)\s+)?(?:wife|daughter|mother|sister|queen|goddess|actress)\b",
    re.IGNORECASE,
)
_MALE_RE = re.compile(
    r"\b(?:he)\b|\b(?:was|is)\s+(?:an?\s+)?(?:male|man|boy)\b|"
    r"\bnamed(?:\s+by [^.]{0,80})?\s+(?:in\s+honou?r\s+of|for|after)\s+"
    r"(?:(?:the|a|an)\s+)?(?:husband|son|father|brother|king|god|actor)\b",
    re.IGNORECASE,
)


class PersonFacetClassifier:
    """Classify person roles and entity gender without inferring from names.

    ``Female`` and ``Male`` require an explicit citation cue.  The optional
    local LLM may add a facet only when it returns an exact supporting excerpt
    from the citation; otherwise deterministic rules remain authoritative.
    """

    def __init__(
        self,
        *,
        mode: str = "rules",
        model: str | None = None,
        host: str | None = None,
        timeout: float = 60.0,
        think: bool = False,
    ) -> None:
        if mode not in {"rules", "auto", "ollama"}:
            raise ValueError(f"Unknown classifier mode: {mode}")
        self.mode = mode
        self.model = model
        self.host = host
        self.timeout = timeout
        self.think = think

    def classify(self, citation_text: str | None, citation_categories: list[str]) -> list[CitationFacet]:
        rule_facets = _rule_facets(citation_text, citation_categories)
        if self.mode == "rules" or not citation_text:
            return rule_facets
        available = is_ollama_available(host=self.host) if self.host else is_ollama_available()
        if self.mode == "auto" and not available:
            return rule_facets

        try:
            extracted = ollama_extract_person_facets(
                citation_text,
                model=self.model,
                host=self.host,
                timeout=self.timeout,
                think=self.think,
            )
        except Exception:
            return rule_facets
        return _merge_llm_facets(rule_facets, extracted, citation_text)


def _rule_facets(citation_text: str | None, citation_categories: list[str]) -> list[CitationFacet]:
    categories = set(citation_categories)
    personlike = bool(categories & PERSONLIKE_CITATION_CATEGORIES)
    if not personlike:
        return [CitationFacet("entity_gender", "Non-person", None, "derived", 1.0)]

    text = citation_text or ""
    facets: list[CitationFacet] = []
    # Mythological and fictional entities are eligible for an explicit gender
    # facet, but do not receive real-person role facets.
    if "Person" in categories:
        for value, pattern in (
            ("Scientist", _SCIENTIST_RE),
            ("Cultural/Public Figure", _CULTURAL_PUBLIC_RE),
            ("Discoverer-relative/Friend", _DISCOVERER_RELATION_RE),
        ):
            match = pattern.search(text)
            if match:
                facets.append(CitationFacet("person_role", value, _evidence_sentence(text, match.start(), match.end()), "rule", 0.78))

    female = _FEMALE_RE.search(text)
    male = _MALE_RE.search(text)
    if female and male:
        # Two cues can refer to different people mentioned in a citation.  Do
        # not turn that ambiguity into a demographic assertion; an evidence-
        # quoting LLM or human review may later assign Multiple/Mixed.
        facets.append(CitationFacet("entity_gender", "Unknown", None, "rule", 0.55))
    elif female:
        facets.append(CitationFacet("entity_gender", "Female", _evidence_sentence(text, female.start(), female.end()), "rule", 0.78))
    elif male:
        facets.append(CitationFacet("entity_gender", "Male", _evidence_sentence(text, male.start(), male.end()), "rule", 0.78))
    else:
        facets.append(CitationFacet("entity_gender", "Unknown", None, "rule", 0.55))
    return facets


def _merge_llm_facets(
    rule_facets: list[CitationFacet], extracted: dict[str, object], citation_text: str
) -> list[CitationFacet]:
    result = list(rule_facets)
    present = {(facet.kind, facet.value) for facet in result}
    for item in extracted.get("roles", []) if isinstance(extracted.get("roles"), list) else []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "")
        evidence = str(item.get("evidence") or "").strip()
        if value in PERSON_ROLE_VALUES and ("person_role", value) not in present and _is_exact_excerpt(evidence, citation_text):
            result.append(CitationFacet("person_role", value, evidence, "ollama", 0.85))
            present.add(("person_role", value))

    gender = extracted.get("gender")
    if isinstance(gender, dict):
        value = str(gender.get("value") or "")
        evidence = str(gender.get("evidence") or "").strip()
        if value in {"Female", "Male", "Multiple/Mixed"} and _is_exact_excerpt(evidence, citation_text):
            result = [facet for facet in result if facet.kind != "entity_gender"]
            result.append(CitationFacet("entity_gender", value, evidence, "ollama", 0.85))
    return result


def _evidence_sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [index for index in (text.find(".", end), text.find("\n", end)) if index != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()


def _is_exact_excerpt(evidence: str, citation_text: str) -> bool:
    if not evidence:
        return False
    normalize = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    return normalize(evidence) in normalize(citation_text)
