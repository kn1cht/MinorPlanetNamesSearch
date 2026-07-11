"""Rule-based citation categorization."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    kind: str
    value: str
    source: str = "rule"
    confidence: float = 0.65


CITATION_CATEGORY_VALUES = {
    "Person",
    "Country/Region/Town",
    "Education",
    "Research",
    "Place",
    "Mythology",
    "Organization",
    "Nature",
    "Artifact/Concept",
    "Character",
    "Epoch/Event",
    "No Citation",
    "Other",
    "Unknown",
}


PERSON_PATTERNS = [
    r"\bwas born\b",
    r"\bborn in\b",
    r"\bprofessor\b",
    r"\bastronomer\b",
    r"\bphysicist\b",
    r"\bmathematician\b",
    r"\bgeologist(?:s)?\b",
    r"\bcommunicator\b",
    r"\bproducer\b",
    r"\bexecutive director\b",
    r"\bceo\b",
    r"\bwas (?:the )?(?:father|mother|son|daughter)\b",
    r"\(\d{4}[\u2013-]\d{4}\)",
    r"\bcomposer\b",
    r"\bscientist\b",
    r"\bengineer\b",
    r"\bwriter\b",
    r"\bauthor\b",
    r"\bpoet\b",
    r"\bartist\b",
    r"\bteacher\b",
    r"\bdiscovered\b",
    r"\bmember of\b",
    r"\bfinalist\b",
    r"\bawarded\b",
    r"\bwinner\b",
    r"\battends\b",
    r"\bstudent\b",
    r"\(b\.\s*\d{4}\)",
    r"\bhonor(?:s|ing)?\b",
]

# Administrative/political geographic areas with defined boundaries.
COUNTRY_REGION_TOWN_PATTERNS = [
    r"\bcity\b",
    r"\btown\b",
    r"\bvillage\b",
    r"\bprovince\b",
    r"\bprefecture\b",
    r"\bcounty\b",
    r"\bmunicipality\b",
    r"\bcommune\b",
    r"\bdistrict\b",
    r"\bregion\b",
    r"\brepublic\b",
    r"\bnation\b",
    r"\bcountry\b",
    r"\bstate\b",
    r"\bkingdom\b",
    r"\bempire\b",
    r"\bcanton\b",
]

# Educational institutions: primary purpose is teaching/training.
EDUCATION_PATTERNS = [
    r"\bschool\b",
    r"\buniversity\b",
    r"\bcollege\b",
    r"\bacademy\b",
    r"\blyc[eé]e\b",
    r"\bgymnasium\b",
    r"\bhigh school\b",
    r"\belementary school\b",
    r"\bprimary school\b",
    r"\bsecondary school\b",
    r"\bcram school\b",
    r"\bjuku\b",
]

# Research institutions: primary purpose is scientific research.
RESEARCH_PATTERNS = [
    r"\bobservatory\b",
    r"\bresearch institute\b",
    r"\bresearch center\b",
    r"\bresearch centre\b",
    r"\blaboratory\b",
    r"\blaboratories\b",
    r"\binstitute of\b",
    r"\bscientific\s+(?:institution|body|society|association)\b",
    r"\bastrophysical\b",
    r"\bastrophysics\b",
]

MYTH_PATTERNS = [
    r"\bgoddess\b",
    r"\bgod\b",
    r"\bmytholog",
    r"\bnymph\b",
    r"\btitan\b",
    r"\bhero\b",
    r"\bqueen\b",
    r"\bking\b",
]

# Generic organization patterns (catch-all for non-Education, non-Research orgs).
ORG_PATTERNS = [
    r"\bsociety\b",
    r"\bassociation\b",
    r"\bfoundation\b",
    r"\bclub\b",
    r"\bcompany\b",
    r"\bteam\b",
    r"\bgroup\b",
    r"\borganization\b",
    r"\bagency\b",
    r"\bcorporation\b",
    r"\bspace\s+agency\b",
]

NATURE_PATTERNS = [
    r"\bspecies\b",
    r"\bgenus\b",
    r"\bgenera\b",
    r"\bflora\b",
    r"\bfauna\b",
    r"\bplant\b",
    r"\briver\b",
    r"\belephant\b",
    r"\bskeleton\b",
    r"\bnatural monument\b",
    r"\btree\b",
    r"\bshrub\b",
    r"\bbird\b",
    r"\bduck\b",
    r"\bteal\b",
    r"\bmaple\b",
    r"\bcashew\b",
    r"\bmango\b",
    r"\bmountain\b",
    r"\bvolcano\b",
    r"\blake\b",
    r"\bdesert\b",
    r"\bvalley\b",
    r"\bisland\b",
    r"\bforest\b",
    r"\bgeological\b",
    r"\bmineral\b",
    r"\bfossil\b",
]

# Generic place patterns (after Country/Region/Town and Research are matched).
PLACE_PATTERNS = [
    r"\brunway\b",
    r"\bpark\b",
    r"\bruins?\b",
    r"\bcastle\b",
    r"\btemple\b",
    r"\bshrine\b",
    r"\bbridge\b",
    r"\bstreet\b",
    r"\bbuilding\b",
    r"\blandmark\b",
    r"\bmuseum\b",
    r"\blibrary\b",
    r"\bsituated in\b",
    r"\blocated in\b",
]

ARTIFACT_CONCEPT_PATTERNS = [
    r"\bcomputer character code\b",
    r"\bnumber of this minor planet\b",
    r"\bdigits?\b",
    r"\bboat\b",
    r"\bship\b",
    r"\bvessel\b",
    r"\bsailing\b",
    r"\bsubmersible\b",
    r"\borbiter\b",
    r"\bspacecraft\b",
    r"\bsatellite\b",
    r"\btelescope\b",
    r"\bbibliography\b",
    r"\babstracts\b",
    r"\bmagazine\b",
    r"\bpublication\b",
    r"\bfictional\b",
]

CHARACTER_PATTERNS = [
    r"\b(?:fictional|comic book|anime|cartoon|manga|television|tv)\s+character\b",
    r"\bcharacter in the\b",
    r"\bcharacter of the\b",
    r"\bhero in the\b",
    r"\bheroine in the\b",
    r"\bprotagonist\b",
    r"\bvillain\b",
]

EVENT_PATTERNS = [
    r"\banniversary\b",
    r"\bearth\s*quake\b",
    r"\bseism\b",
    r"\btyphoon\b",
    r"\btsunami\b",
    r"\bdisaster\b",
    r"\bflood\b",
    r"\bvolcan",
    r"\barmistice\b",
    r"\bpeace treaty\b",
    r"\bconstitution\b",
    r"\boccasion of\b",
    r"\bcommemorat",
    r"\bexhibition\b",
    r"\bfestival\b",
    r"\bceremony\b",
    r"\bolympiad\b",
    r"\bolympic\b",
    r"\bworld.*?cup\b",
    r"\bworld.*?expo\b",
    r"\bexposi(?:tion)?\b",
    r"\bworld.*?fair\b",
    r"\bworld.*?championship\b",
    r"\bcelebrat",
    r"\bnamed on the occasion\b",
]


def categorize_citation(citation_text: str | None) -> list[Category]:
    """Return coarse naming-origin categories from a citation."""
    if not citation_text:
        return [Category("citation", "No Citation", confidence=1.0)]

    text = citation_text.lower()
    categories: list[Category] = []

    if _matches(text, EVENT_PATTERNS):
        categories.append(Category("citation", "Epoch/Event", confidence=0.70))
    if _matches(text, CHARACTER_PATTERNS):
        categories.append(Category("citation", "Character", confidence=0.70))
    if _matches(text, PERSON_PATTERNS):
        categories.append(Category("citation", "Person", confidence=0.72))

    has_character = any(category.value == "Character" for category in categories)
    has_person = any(category.value == "Person" for category in categories)

    if not has_character and _matches(text, MYTH_PATTERNS):
        categories.append(Category("citation", "Mythology", confidence=0.68))

    # Place/Org sub-categories: specific ones first, then fall back to generic.
    # Research beats Education when both match (e.g. "research institute founded as a school").
    has_research = not has_person and not has_character and _matches(text, RESEARCH_PATTERNS)
    has_education = not has_person and not has_character and not has_research and _matches(text, EDUCATION_PATTERNS)
    # Country/Region/Town only when no institution type already matched.
    has_crt = (
        not has_person
        and not has_character
        and not has_research
        and not has_education
        and _matches(text, COUNTRY_REGION_TOWN_PATTERNS)
    )

    if has_research:
        categories.append(Category("citation", "Research", confidence=0.70))
    if has_education:
        categories.append(Category("citation", "Education", confidence=0.70))
    if has_crt:
        categories.append(Category("citation", "Country/Region/Town", confidence=0.70))

    has_specific_place_or_org = has_research or has_education or has_crt
    # Generic Organization: only when no specific sub-type matched
    if not has_person and not has_character and not has_specific_place_or_org and _matches(text, ORG_PATTERNS):
        categories.append(Category("citation", "Organization", confidence=0.68))
    # Generic Place: only when no specific sub-type matched
    if not has_person and not has_character and not has_specific_place_or_org and _matches(text, PLACE_PATTERNS):
        categories.append(Category("citation", "Place", confidence=0.68))

    if not has_person and not has_character and _matches(text, NATURE_PATTERNS):
        categories.append(Category("citation", "Nature", confidence=0.66))
    if not has_person and not has_character and _matches(text, ARTIFACT_CONCEPT_PATTERNS):
        categories.append(Category("citation", "Artifact/Concept", confidence=0.64))

    return categories or [Category("citation", "Other", confidence=0.4)]



def citation_categories_from_values(
    values: list[str],
    *,
    source: str,
    confidence: float,
) -> list[Category]:
    """Convert external category labels into validated citation categories."""
    normalized: list[Category] = []
    seen: set[str] = set()
    for value in values:
        canonical = normalize_citation_category(value)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(Category("citation", canonical, source, confidence))
    if any(category.value not in {"Other", "Unknown"} for category in normalized):
        normalized = [category for category in normalized if category.value not in {"Other", "Unknown"}]
    return normalized


def normalize_citation_category(value: str) -> str | None:
    cleaned = value.strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "person": "Person",
        "people": "Person",
        "human": "Person",
        # Fine-grained place/org categories
        "country/region/town": "Country/Region/Town",
        "country region town": "Country/Region/Town",
        "country": "Country/Region/Town",
        "region": "Country/Region/Town",
        "town": "Country/Region/Town",
        "city": "Country/Region/Town",
        "administrative area": "Country/Region/Town",
        "education": "Education",
        "educational institution": "Education",
        "school": "Education",
        "university": "Education",
        "research": "Research",
        "research institution": "Research",
        "observatory": "Research",
        "research institute": "Research",
        # Legacy aliases → mapped to closest new category
        "place": "Place",
        "location": "Place",
        "geography": "Place",
        "organization": "Organization",
        "organisation": "Organization",
        "institution": "Organization",
        # Other categories unchanged
        "myth": "Mythology",
        "mythology": "Mythology",
        "religion": "Mythology",
        "mythological": "Mythology",
        "nature": "Nature",
        "natural object": "Nature",
        "natural objects": "Nature",
        "species": "Nature",
        "flora": "Nature",
        "fauna": "Nature",
        "artifact": "Artifact/Concept",
        "artefact": "Artifact/Concept",
        "concept": "Artifact/Concept",
        "artifact/concept": "Artifact/Concept",
        "artifact concept": "Artifact/Concept",
        "technology": "Artifact/Concept",
        "publication": "Artifact/Concept",
        "mission": "Artifact/Concept",
        "character": "Character",
        "fictional character": "Character",
        "epoch/event": "Epoch/Event",
        "epoch event": "Epoch/Event",
        "event": "Epoch/Event",
        "epoch": "Epoch/Event",
        "occasion": "Epoch/Event",
        "disaster": "Epoch/Event",
        "historic event": "Epoch/Event",
        "historical event": "Epoch/Event",
        "no citation": "No Citation",
        "nocitation": "No Citation",
        "missing citation": "No Citation",
        "other": "Other",
        "unknown": "Unknown",
    }
    return aliases.get(cleaned)


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)
