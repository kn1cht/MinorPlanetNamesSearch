"""Optional local ollama integration."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .settings import OLLAMA_HOST


DEFAULT_HOST = OLLAMA_HOST

# Maximum number of classify attempts when the model returns too many categories.
MAX_CLASSIFY_TRIES = 5


def is_ollama_available(host: str = DEFAULT_HOST, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def list_models(host: str = DEFAULT_HOST, timeout: float = 2.0) -> list[str]:
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    models = body.get("models", [])
    names: list[str] = []
    for model in models:
        name = model.get("name") if isinstance(model, dict) else None
        if name:
            names.append(str(name))
    return names


def classify_citation(
    citation_text: str,
    model: str | None,
    host: str = DEFAULT_HOST,
    timeout: float = 20.0,
    max_tries: int = MAX_CLASSIFY_TRIES,
    think: bool = False,
    think_on_review: bool = True,
) -> list[str]:
    """Ask ollama for coarse citation categories.

    Retries up to *max_tries* times when the model returns too many or
    uncertain categories.  Each attempt beyond the first uses the
    ``review`` prompt that instructs the model to be more precise; the
    final attempt also adds ``force_single`` to demand a single answer.
    All successful responses are collected and the best one is chosen by
    :func:`_select_best_labels` (fewest categories, most frequent across
    attempts).

    *think* controls whether the model's native thinking/reasoning mode
    is enabled (Qwen3/Qwen3.5 etc.).  ``False`` (default) suppresses
    extended thinking for faster responses; ``True`` allows the model to
    reason internally before answering.

    *think_on_review* enables thinking only for retry attempts (2nd
    attempt onwards) when the first attempt returns too many categories.
    This combines speed (fast first pass) with accuracy (thinking on
    difficult cases). Mutually exclusive with *think*.

    This is intentionally optional. The application works without it.
    """
    selected_model = model or (list_models(host=host)[:1] or [None])[0]
    if not selected_model:
        raise RuntimeError("No ollama model is available")

    candidates: list[list[str]] = []

    for attempt in range(max(1, max_tries)):
        review = attempt > 0
        force_single = attempt == max(1, max_tries) - 1
        # think_on_review: enable thinking from the 2nd attempt onwards
        attempt_think = think or (think_on_review and review)
        labels = _classify_once(
            citation_text,
            model=selected_model,
            host=host,
            timeout=timeout,
            review=review,
            force_single=force_single,
            think=attempt_think,
        )
        if labels:
            candidates.append(labels)
            # Early exit: result is already specific enough.
            if not _needs_review(labels):
                break

    return _select_best_labels(candidates)


def extract_person_facets(
    citation_text: str,
    *,
    model: str | None,
    host: str | None = None,
    timeout: float = 60.0,
    think: bool = False,
) -> dict[str, object]:
    """Extract evidence-backed person-role and gender facets from one citation."""
    selected_host = host or DEFAULT_HOST
    selected_model = model or (list_models(host=selected_host)[:1] or [None])[0]
    if not selected_model:
        raise RuntimeError("No ollama model is available")
    prompt = _build_person_facet_prompt(citation_text)
    payload = json.dumps(
        {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": think,
            "options": {"temperature": 0, "num_predict": 500 if think else 250},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{selected_host.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    parsed = _parse_json_value(str(body.get("response", "")).strip())
    return parsed if isinstance(parsed, dict) else {}


def _build_person_facet_prompt(citation_text: str) -> str:
    return f'''You extract narrowly defined metadata from a minor-planet naming citation.

Return ONLY valid JSON in this exact shape:
{{"roles":[{{"value":"Scientist","evidence":"exact quotation"}}],"gender":{{"value":"Female","evidence":"exact quotation"}}}}

Allowed role values are exactly:
["Scientist","Cultural/Public Figure","Discoverer-relative/Friend"]

Allowed gender values are exactly:
["Female","Male","Unknown","Non-person","Multiple/Mixed"]

Rules:
- Add each role only if the citation explicitly supports it.
- Scientist includes scientists, researchers, engineers, and programmers.
- Cultural/Public Figure includes artists, writers, musicians, performers, athletes, and political/public figures.
- Discoverer-relative/Friend applies only when the citation explicitly states a family, friend, or colleague relation to the discoverer.
- Female, Male, and Multiple/Mixed require an explicit citation cue. Do not infer gender from a name, nationality, photograph, or external knowledge.
- Mythological and fictional characters may receive Female or Male only with an explicit cue in this citation.
- Use Unknown for a person-like entity with no explicit gender cue. Use Non-person for a place, organization, natural object, event, or other non-person entity.
- Every non-empty evidence value MUST be an exact contiguous excerpt from the citation. Use an empty string when no evidence applies.

Citation:
{citation_text}
'''


def citation_prompt_templates() -> dict[str, str]:
    """Return every citation-classification prompt variant without citation data."""
    marker = "{{CITATION_TEXT}}"
    return {
        "initial": _build_prompt(marker, review=False, force_single=False, think=False),
        "review": _build_prompt(marker, review=True, force_single=False, think=True),
        "force_single": _build_prompt(marker, review=True, force_single=True, think=True),
    }


def person_facet_prompt_template() -> str:
    """Return the reusable person-facet prompt template without citation data."""
    return _build_person_facet_prompt("{{CITATION_TEXT}}")


def _classify_once(
    citation_text: str,
    *,
    model: str,
    host: str,
    timeout: float,
    review: bool,
    force_single: bool,
    think: bool = False,
) -> list[str]:
    prompt = _build_prompt(citation_text, review=review, force_single=force_single, think=think)
    # With thinking ON, the model uses more tokens for internal reasoning;
    # increase num_predict accordingly. With thinking OFF, keep it compact.
    num_predict = 600 if think else 250
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": think,
            "options": {"temperature": 0, "num_predict": num_predict},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    raw = body.get("response", "[]").strip()
    parsed = _parse_json_value(raw)
    if isinstance(parsed, dict):
        parsed = parsed.get("categories", [])
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _build_prompt(citation_text: str, *, review: bool, force_single: bool, think: bool) -> str:
    review_instruction = ""
    if review:
        review_instruction = """
The previous attempt was uncertain or over-broad. Re-evaluate more carefully.
Other is a last resort. Prefer exactly one closest category for the main named
origin when it is identifiable, even if the wording is unusual.
"""
    single_instruction = ""
    if force_single:
        single_instruction = """
You must return exactly one category in the categories array. Choose the best
single category for the main named origin. DO NOT RETURN MULTIPLE CATEGORIES.
"""

    if think:
        # Native thinking mode: reasoning happens in the hidden thinking block.
        # Request compact JSON output only.
        preamble = "Return ONLY a compact JSON object in this exact format:"
    else:
        # No thinking: encourage a brief visible chain-of-thought for accuracy.
        preamble = (
            "First, provide a brief reasoning (1-2 sentences) for your classification.\n"
            "Then, on the final line, return ONLY a compact JSON object in this exact format:"
        )

    return f"""You classify why a minor planet was named.

{preamble}
{{"categories":["Person"]}}

Valid categories:
["Person","Country/Region/Town","Education","Research","Place","Mythology","Organization","Nature","Artifact/Concept","Character","Epoch/Event","No Citation","Other"]

Classification rules:
- Choose No Citation only when the citation is empty or says no citation is available.
- Choose Person when the naming origin is a real historical or living person. This includes authors, mangaka, and directors (e.g. Hayao Miyazaki, Koyoharu Gotoge).
- DO NOT choose Person for fictional characters, mythological figures, or non-human animals.
- Choose Country/Region/Town when the naming origin is a political or administrative geographic area: country, nation, state, province, prefecture, county, municipality, commune, city, town, or village.
- Choose Education when the naming origin is an institution whose PRIMARY purpose is teaching or training: school, university, college, academy, lycée, gymnasium, cram school. Universities count as Education even if they also do research.
- Choose Research when the naming origin is an institution whose PRIMARY purpose is scientific research: observatory, research institute, research center, laboratory, or scientific society/association. Classify "X University Observatory" as Research (function over affiliation).
- Choose Place when the naming origin is a specific location that is NOT a geographic administrative area (→ Country/Region/Town) and NOT a research/educational institution (→ Research/Education): e.g. ruins, historical site, museum, library, park, temple, shrine, landmark, building.
- Choose Organization when the naming origin is a body that does not fit Education or Research: company, corporation, space agency (NASA, ESA, JAXA), foundation, fund, sports team, club, cultural group, NGO, government agency (non-research).
- Choose Mythology ONLY for ancient mythological, legendary, or religious figures/concepts. DO NOT use Mythology for modern fictional characters.
- Choose Nature for a biological taxon, animal, plant, mountain, river, lake, desert, geological feature, or other natural object or landscape.
- Choose Artifact/Concept for a human-made object, vehicle, technology, computer program, publication, phrase, concept, or attitude. DO NOT use Artifact/Concept for fictional characters.
- Choose Character for fictional characters from modern media (e.g., novels, comics, TV shows, anime, movies, video games).
- Fictional characters (e.g., Arthur Dent, Obelix, Professor Moriarty) are ALWAYS Character, NEVER Person, Mythology, or Artifact/Concept, even if they have a title like "Professor" or a fake biography.
- Choose Epoch/Event for a historical event, disaster, festival, or anniversary.
- Return exactly one category unless the citation explicitly names multiple completely distinct origins.
- DO NOT return multiple categories for a single entity just because it has multiple attributes.
- For institutions that were originally one type but changed (e.g., founded as a school, now a research institute): classify by the PRIMARY function described in the citation.
- EXTREMELY IMPORTANT: IGNORE any journal references, publications, or author names found in parentheses at the end of the text (e.g., "Monthly Notices of the Royal Astronomical Society"). These are bibliographic sources, not the naming origin.
- DO NOT classify as Organization just because you see words like "Society", "Institute", or "Observatory" in the bibliographic reference.
- DO NOT classify based on the discoverer, the person who proposed the name, or the organization they belong to, unless the asteroid is specifically named IN HONOR OF them.
- If the text only describes how the name was proposed or provides bibliographic info, but contains NO information about what the name itself means, YOU MUST choose Other.

Examples:
- A real person, author, or director -> Person.
- Fictional characters (e.g., Sherlock Holmes, Totoro) from modern media -> Character.
- A country, prefecture, city, or town -> Country/Region/Town.
- A school, university, college -> Education.
- An observatory, research institute, research center -> Research.
- A "X University Observatory" -> Research (classified by function).
- A museum, ruins, temple, park, historical landmark -> Place.
- NASA, ESA, a foundation, a sports team, a company -> Organization.
- A spacecraft, boat, phrase, or abstract attitude -> Artifact/Concept.
- A Greek god or ancient mythological figure -> Mythology.
- A mountain, river, animal species, or plant -> Nature.
- An earthquake, festival, or Olympic Games -> Epoch/Event.
- "(72) Feronia At my request Mr. Safford has selected the name. (Christian Heinrich Friedrich Peters, Monthly Notices of the Royal Astronomical Society, 22, 257.)" -> Other.

{review_instruction}
{single_instruction}
Citation:
{citation_text}
"""


def _needs_review(labels: list[str]) -> bool:
    """Return True when the labels list is still too broad or uncertain.

    A result needs further review when it is empty, contains only
    uncertain placeholders (Other / Unknown), or contains more than one
    distinct specific category.
    """
    if not labels:
        return True
    uncertain = {"other", "unknown"}
    cleaned = [str(label).strip().lower() for label in labels]
    if all(label in uncertain for label in cleaned):
        return True
    specific = [label for label in cleaned if label not in {*uncertain, "no citation"}]
    return len(set(specific)) > 1


def _select_best_labels(candidates: list[list[str]]) -> list[str]:
    """Choose the best classification from multiple attempt results.

    Strategy:
    1. Discard candidates that contain only uncertain values
       (Other / Unknown / No Citation) if any specific ones exist.
    2. Among the remaining candidates, prefer the result with the
       fewest categories.
    3. Break ties by picking the most frequently occurring result
       across all attempts.
    """
    if not candidates:
        return []

    from collections import Counter

    uncertain = {"other", "unknown", "no citation"}
    good = [
        c for c in candidates
        if any(str(label).strip().lower() not in uncertain for label in c)
    ]
    pool = good if good else candidates

    # Normalise to sorted tuples so that order differences don't split counts.
    tuples = [tuple(sorted(str(label) for label in c)) for c in pool]
    counter = Counter(tuples)
    # Primary key: fewest categories.  Secondary key: highest frequency.
    best_tuple, _ = min(counter.items(), key=lambda x: (len(x[0]), -x[1]))
    return list(best_tuple)


def _parse_json_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        candidates = [
            (raw.find("{"), raw.rfind("}")),
            (raw.find("["), raw.rfind("]")),
        ]
        for start, end in candidates:
            if start == -1 or end == -1 or end <= start:
                continue
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                continue
        return []
