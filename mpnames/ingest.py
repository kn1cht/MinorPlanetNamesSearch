"""Data ingestion from MPC sources."""

from __future__ import annotations

import datetime
import json
import time
import urllib.error
import urllib.request
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import db
from .classifier import CitationClassifier
from .categories import normalize_citation_category
from .mpcorb import OrbitRecord, parse_mpcorb_lines, parse_orbits_api_response
from .mpnames_parser import NameRecord, parse_mpnames_html
from .numbered_mps import DiscoveryRecord, parse_numbered_mps
from .person_facets import PersonFacetClassifier
from .provenance import new_classification_job
from .progress import ProgressReporter, QUIET_PROGRESS
from .settings import (
    IDENTIFIER_BATCH_SIZE,
    IDENTIFIER_INTER_REQUEST_DELAY_SECONDS,
    IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS,
    IDENTIFIER_LONG_PAUSE_SECONDS,
    IDENTIFIER_URL,
    MPNAMES_URL,
    NUMBERED_MPS_CACHE,
    NUMBERED_MPS_URL,
    OLLAMA_HOST,
    ORBIT_INTER_REQUEST_DELAY_SECONDS,
    ORBIT_LONG_PAUSE_EVERY_REQUESTS,
    ORBIT_LONG_PAUSE_SECONDS,
    ORBITS_URL,
    WGSBN_ARCHIVE_URL,
    WGSBN_INTER_REQUEST_DELAY_SECONDS,
)
from .wgsbn import parse_wgsbn_archive, parse_wgsbn_namings, wgsbn_volume_year


INGEST_MODES = {"add", "update", "reset", "repair"}


def ingest(
    db_path: Path,
    *,
    limit: int | None = None,
    delay: float = IDENTIFIER_INTER_REQUEST_DELAY_SECONDS,
    batch_size: int = IDENTIFIER_BATCH_SIZE,
    pause_every: int = IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS,
    pause_seconds: float = IDENTIFIER_LONG_PAUSE_SECONDS,
    mpnames_url: str = MPNAMES_URL,
    identifier_url: str = IDENTIFIER_URL,
    orbit_url: str = ORBITS_URL,
    orbit_delay: float = ORBIT_INTER_REQUEST_DELAY_SECONDS,
    orbit_pause_every: int = ORBIT_LONG_PAUSE_EVERY_REQUESTS,
    orbit_pause_seconds: float = ORBIT_LONG_PAUSE_SECONDS,
    mode: str = "add",
    classifier_mode: str = "rules",
    ollama_model: str | None = None,
    ollama_host: str = OLLAMA_HOST,
    wgsbn_sync: bool = True,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, Any]:
    if mode not in INGEST_MODES:
        raise ValueError(f"Unknown ingest mode: {mode}")

    connection = db.connect(db_path)
    db.initialize(connection)

    progress.message(f"Fetching named-object list from {mpnames_url}")
    names = fetch_names(mpnames_url)
    progress.message(f"Named-object list contains {len(names)} records")
    selected_names = _select_names_for_mode(connection, names, mode=mode, limit=limit)
    progress.message(f"Ingest mode={mode}; selected {len(selected_names)} records for detail fetch")
    discoveries = fetch_discoveries(cache_path=NUMBERED_MPS_CACHE, progress=progress) if selected_names else {}

    identifiers = (
        fetch_identifiers(
            selected_names,
            identifier_url=identifier_url,
            delay=delay,
            batch_size=batch_size,
            pause_every=pause_every,
            pause_seconds=pause_seconds,
            progress=progress,
        )
        if selected_names
        else {}
    )
    classifier = CitationClassifier(mode=classifier_mode, model=ollama_model, host=ollama_host)
    facet_classifier = PersonFacetClassifier(mode=classifier_mode, model=ollama_model, host=ollama_host)
    job: dict[str, Any] | None = None
    orbits: dict[str, OrbitRecord] = {}
    stats = {
        "mode": mode,
        "listed_records": len(names),
        "selected_records": len(selected_names),
        "identifier_records": len(identifiers),
        "orbit_records": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "wgsbn_bulletins_fetched": 0,
        "wgsbn_namings_fetched": 0,
        "naming_metadata_updated": 0,
        "naming_metadata_unchanged": 0,
        "naming_metadata_missing": 0,
    }
    next_write_index = 0
    reset_done = False

    def ensure_job() -> dict[str, Any]:
        nonlocal job
        if job is None:
            job = new_classification_job(
                command="ingest", classifier_mode=classifier_mode, ollama_model=ollama_model,
                ollama_host=ollama_host, ollama_timeout=60.0, ollama_think=False,
                include_categories=True, include_person_facets=True,
            )
            db.create_classification_job(connection, job)
        return job

    def write_ready_records(upto_index: int, current_orbits: dict[str, OrbitRecord] | None = None) -> None:
        nonlocal next_write_index, reset_done
        upto_index = min(max(upto_index, next_write_index), len(selected_names))
        if upto_index == next_write_index:
            return
        orbit_lookup = current_orbits if current_orbits is not None else orbits
        if mode == "reset" and not reset_done:
            db.reset_database(connection)
            reset_done = True
        current_job = ensure_job()
        for zero_based_index in range(next_write_index, upto_index):
            record = selected_names[zero_based_index]
            identifier = (
                identifiers.get(record.permid)
                or identifiers.get(record.name_ascii)
                or identifiers.get(record.name_display)
                or {}
            )
            permid = str(identifier.get("permid") or record.permid)
            orbit = _orbit_for(permid, identifier, orbit_lookup)
            discovery = discoveries.get(record.permid) or discoveries.get(permid)
            citation_categories = classifier.classify(db.html_to_text(identifier.get("citation")))
            citation_facets = facet_classifier.classify(
                db.html_to_text(identifier.get("citation")), [category.value for category in citation_categories]
            )
            status = db.upsert_minor_planet(
                connection,
                permid=record.permid,
                name_ascii=record.name_ascii,
                name_display=record.name_display,
                identifier=identifier,
                orbit=orbit,
                discovery=discovery,
                citation_categories=citation_categories,
                citation_facets=citation_facets,
            )
            db.assign_classification_job(connection, record.permid, "citation_category", current_job["job_id"])
            db.assign_classification_job(connection, record.permid, "person_facet", current_job["job_id"])
            stats[status] += 1
            current = zero_based_index + 1
            if _should_report_item(current, len(selected_names)):
                progress.step(
                    "Classify/write",
                    current,
                    len(selected_names),
                    detail=(
                        f"inserted={stats['inserted']} updated={stats['updated']} "
                        f"unchanged={stats['unchanged']}"
                    ),
                )
        next_write_index = upto_index

    progress.message(
        f"Classifying and writing {len(selected_names)} selected records during Orbit API pauses and final flush"
    )
    if selected_names:
        orbits = fetch_orbits(
            selected_names,
            identifiers=identifiers,
            orbit_url=orbit_url,
            delay=orbit_delay,
            pause_every=orbit_pause_every,
            pause_seconds=orbit_pause_seconds,
            progress=progress,
            on_long_pause=write_ready_records,
        )
        stats["orbit_records"] = _unique_orbit_count(orbits)
        progress.message(f"Fetched {_unique_orbit_count(orbits)} orbit records")
    if mode == "reset" and selected_names and not reset_done:
        db.reset_database(connection)
        reset_done = True
    write_ready_records(len(selected_names))
    if job is not None:
        db.finish_classification_job(connection, job["job_id"], "completed")

    # Keep the MPC ingest durable even if a later WGSBN request fails. A
    # subsequent ``ingest --mode repair`` retries the WGSBN synchronization.
    connection.commit()

    try:
        if wgsbn_sync:
            wgsbn_result = _collect_new_wgsbn_bulletins(connection, progress=progress)
            stats["wgsbn_bulletins_fetched"] = wgsbn_result["fetched_bulletins"]
            stats["wgsbn_namings_fetched"] = wgsbn_result["fetched_namings"]
        naming_metadata = db.sync_wgsbn_naming_metadata(connection)
        stats["naming_metadata_updated"] = naming_metadata["updated"]
        stats["naming_metadata_unchanged"] = naming_metadata["unchanged"]
        stats["naming_metadata_missing"] = naming_metadata["missing"]
        connection.commit()
    finally:
        connection.close()
    progress.message("Ingest complete")
    return stats


def init_sample(
    db_path: Path,
    fixture_dir: Path,
    *,
    classifier_mode: str = "rules",
    ollama_model: str | None = None,
    ollama_host: str = OLLAMA_HOST,
) -> dict[str, Any]:
    connection = db.connect(db_path)
    db.initialize(connection)

    names = parse_mpnames_html((fixture_dir / "mpnames_sample.html").read_text(encoding="utf-8"))
    identifiers = json.loads((fixture_dir / "identifier_sample.json").read_text(encoding="utf-8"))
    orbits = parse_mpcorb_lines((fixture_dir / "mpcorb_sample.dat").read_text(encoding="utf-8").splitlines())
    classifier = CitationClassifier(mode=classifier_mode, model=ollama_model, host=ollama_host)
    facet_classifier = PersonFacetClassifier(mode=classifier_mode, model=ollama_model, host=ollama_host)
    job = new_classification_job(
        command="init-sample", classifier_mode=classifier_mode, ollama_model=ollama_model,
        ollama_host=ollama_host, ollama_timeout=60.0, ollama_think=False,
        include_categories=True, include_person_facets=True,
    )
    db.create_classification_job(connection, job)

    for record in names:
        identifier = identifiers.get(record.permid) or identifiers.get(record.name_ascii) or {}
        permid = str(identifier.get("permid") or record.permid)
        citation_categories = classifier.classify(db.html_to_text(identifier.get("citation")))
        citation_facets = facet_classifier.classify(
            db.html_to_text(identifier.get("citation")), [category.value for category in citation_categories]
        )
        db.upsert_minor_planet(
            connection,
            permid=record.permid,
            name_ascii=record.name_ascii,
            name_display=record.name_display,
            identifier=identifier,
            orbit=_orbit_for(permid, identifier, orbits),
            discovery=None,
            citation_categories=citation_categories,
            citation_facets=citation_facets,
        )
        db.assign_classification_job(connection, record.permid, "citation_category", job["job_id"])
        db.assign_classification_job(connection, record.permid, "person_facet", job["job_id"])
    db.finish_classification_job(connection, job["job_id"], "completed")
    connection.commit()
    connection.close()
    return {"records": len(names), "fixture_dir": str(fixture_dir)}


def reclassify_existing(
    db_path: Path,
    *,
    classifier_mode: str = "ollama",
    ollama_model: str | None = None,
    ollama_host: str = OLLAMA_HOST,
    ollama_timeout: float = 60.0,
    ollama_think: bool = False,
    ollama_think_on_review: bool = True,
    limit: int | None = None,
    categories: list[str] | None = None,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, Any]:
    connection = db.connect(db_path)
    db.initialize(connection)
    classifier = CitationClassifier(
        mode=classifier_mode, model=ollama_model, host=ollama_host,
        timeout=ollama_timeout, think=ollama_think, think_on_review=ollama_think_on_review,
    )
    facet_classifier = PersonFacetClassifier(
        mode=classifier_mode, model=ollama_model, host=ollama_host,
        timeout=ollama_timeout, think=ollama_think,
    )
    job = new_classification_job(
        command="reclassify", classifier_mode=classifier_mode, ollama_model=ollama_model,
        ollama_host=ollama_host, ollama_timeout=ollama_timeout, ollama_think=ollama_think,
        ollama_think_on_review=ollama_think_on_review, include_categories=True, include_person_facets=True,
    )
    db.create_classification_job(connection, job)
    category_filter = _normalize_category_filters(categories or [])
    sql = "SELECT DISTINCT mp.permid, mp.citation_text, mp.name_ascii FROM minor_planets mp"
    params: list[Any] = []
    if category_filter:
        sql += " JOIN categories c_filter ON c_filter.permid = mp.permid AND c_filter.kind = 'citation'"
        sql += f" WHERE c_filter.value IN ({', '.join('?' for _ in category_filter)})"
        params.extend(category_filter)
    sql += " ORDER BY CAST(mp.permid AS INTEGER)"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = connection.execute(sql, params).fetchall()

    updated = 0
    changed = 0
    log_file = db_path.parent / f"reclassify_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_fp = None

    filter_detail = f" categories={','.join(category_filter)}" if category_filter else ""
    progress.message(f"Reclassifying {len(rows)} existing records with classifier={classifier_mode}{filter_detail}")
    try:
        for index, row in enumerate(rows, start=1):
            old_rows = connection.execute("SELECT value FROM categories WHERE permid = ? AND kind = 'citation'", (row["permid"],)).fetchall()
            old_cats = {r["value"] for r in old_rows}

            citation_categories = classifier.classify(row["citation_text"])
            new_cats = {c.value for c in citation_categories}

            if old_cats != new_cats:
                if log_fp is None:
                    log_fp = open(log_file, "w", encoding="utf-8")
                log_fp.write(f"Name: {row['name_ascii']} ({row['permid']})\n")
                log_fp.write(f"Old Categories: {', '.join(sorted(old_cats)) if old_cats else 'None'}\n")
                log_fp.write(f"New Categories: {', '.join(sorted(new_cats)) if new_cats else 'None'}\n")
                log_fp.write(f"Citation: {row['citation_text']}\n")
                log_fp.write("-" * 80 + "\n")
                changed += 1

            db.replace_citation_categories(connection, row["permid"], citation_categories)
            facets = facet_classifier.classify(row["citation_text"], [category.value for category in citation_categories])
            db.replace_citation_facets(connection, row["permid"], facets)
            db.assign_classification_job(connection, row["permid"], "citation_category", job["job_id"])
            db.assign_classification_job(connection, row["permid"], "person_facet", job["job_id"])
            updated += 1
            if index % 100 == 0:
                connection.commit()
            if _should_report_item(index, len(rows)):
                progress.step("Reclassify", index, len(rows))
        db.finish_classification_job(connection, job["job_id"], "completed")
    except Exception:
        db.finish_classification_job(connection, job["job_id"], "failed")
        connection.commit()
        raise
    finally:
        if log_fp is not None:
            log_fp.close()
            progress.message(f"Logged {changed} category changes to {log_file}")
        connection.commit()
        connection.close()
    progress.message(f"Reclassification complete ({changed} changes out of {updated} processed)")
    return {"records": updated, "changed": changed, "classifier": classifier_mode, "category_filter": category_filter, "log_file": str(log_file) if log_fp else None, "job_id": job["job_id"]}


def classify_person_facets_existing(
    db_path: Path,
    *,
    classifier_mode: str = "rules",
    ollama_model: str | None = None,
    ollama_host: str = OLLAMA_HOST,
    ollama_timeout: float = 60.0,
    ollama_think: bool = False,
    limit: int | None = None,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, int | str]:
    """Classify evidence-backed person roles and entity gender for local records."""
    connection = db.connect(db_path)
    db.initialize(connection)
    classifier = PersonFacetClassifier(
        mode=classifier_mode,
        model=ollama_model,
        host=ollama_host,
        timeout=ollama_timeout,
        think=ollama_think,
    )
    job = new_classification_job(
        command="classify-person-facets", classifier_mode=classifier_mode, ollama_model=ollama_model,
        ollama_host=ollama_host, ollama_timeout=ollama_timeout, ollama_think=ollama_think,
        include_categories=False, include_person_facets=True,
    )
    db.create_classification_job(connection, job)
    sql = """
        SELECT mp.permid, mp.citation_text, GROUP_CONCAT(c.value, CHAR(31)) AS citation_values
        FROM minor_planets AS mp
        LEFT JOIN categories AS c ON c.permid = mp.permid AND c.kind = 'citation'
        GROUP BY mp.permid
        ORDER BY CAST(mp.permid AS INTEGER)
    """
    if limit is not None:
        sql += " LIMIT ?"
        rows = connection.execute(sql, (max(0, limit),)).fetchall()
    else:
        rows = connection.execute(sql).fetchall()

    updated = unchanged = 0
    progress.message(f"Classifying person facets for {len(rows)} records with classifier={classifier_mode}")
    try:
        for index, row in enumerate(rows, start=1):
            categories = str(row["citation_values"] or "").split(chr(31))
            facets = classifier.classify(row["citation_text"], categories)
            if db._citation_facets_match(connection, row["permid"], facets):
                unchanged += 1
            else:
                db.replace_citation_facets(connection, row["permid"], facets)
                updated += 1
            db.assign_classification_job(connection, row["permid"], "person_facet", job["job_id"])
            if index % 100 == 0:
                connection.commit()
            if _should_report_item(index, len(rows)):
                progress.step("Person facet classify", index, len(rows), detail=f"updated={updated}")
        db.finish_classification_job(connection, job["job_id"], "completed")
    except Exception:
        db.finish_classification_job(connection, job["job_id"], "failed")
        connection.commit()
        raise
    finally:
        connection.commit()
        connection.close()
    return {"records": len(rows), "updated": updated, "unchanged": unchanged, "classifier": classifier_mode, "job_id": job["job_id"]}


def _collect_new_wgsbn_bulletins(
    connection: Any,
    *,
    archive_url: str = WGSBN_ARCHIVE_URL,
    delay: float = WGSBN_INTER_REQUEST_DELAY_SECONDS,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, Any]:
    """Collect WGSBN Bulletins not already cached in the local database.

    WGSBN JSON files are authoritative for Bulletin contents beginning in 2021.
    A Bulletin's publication year is derived from its volume number (Volume 1 is
    2021), because the JSON archive's date labels need not be issue dates. Each
    JSON record is joined to local MPC data after collection.
    """
    if delay < 0:
        raise ValueError("delay must be greater than or equal to zero")

    progress.message(f"Fetching WGSBN Bulletin archive from {archive_url}")
    bulletins = parse_wgsbn_archive(_read_text_url(archive_url), archive_url)
    if not bulletins:
        raise ValueError("No WGSBN Bulletin JSON files found in archive")

    known_urls = db.existing_wgsbn_bulletin_urls(connection)
    selected = [bulletin for bulletin in bulletins if bulletin.source_url not in known_urls]
    fetched_bulletins = fetched_namings = 0
    progress.message(
        f"Found {len(bulletins)} WGSBN Bulletins; fetching {len(selected)} "
        "new records"
    )
    for index, bulletin in enumerate(selected, start=1):
        progress.step(
            "WGSBN Bulletin",
            index,
            len(selected),
            detail=f"V{bulletin.volume}, #{bulletin.issue} ({bulletin.published_date})",
        )
        namings = parse_wgsbn_namings(_read_text_url(bulletin.source_url))
        fetched_namings += db.replace_wgsbn_bulletin(
            connection,
            source_url=bulletin.source_url,
            volume=bulletin.volume,
            issue=bulletin.issue,
            published_date=bulletin.published_date,
            published_year=wgsbn_volume_year(bulletin.volume),
            namings=namings,
        )
        fetched_bulletins += 1
        if delay and index < len(selected):
            time.sleep(delay)

    return {
        "bulletins": len(bulletins),
        "fetched_bulletins": fetched_bulletins,
        "fetched_namings": fetched_namings,
    }


def backfill_wgsbn_only(
    db_path: Path,
    *,
    permids: list[str],
    classifier_mode: str = "ollama",
    ollama_model: str | None = None,
    ollama_host: str = OLLAMA_HOST,
    ollama_timeout: float = 60.0,
    ollama_think: bool = False,
    ollama_think_on_review: bool = True,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, int | str]:
    """Add selected WGSBN-named objects that are absent from MPC name data.

    This is deliberately an explicit opt-in: a recent local MPC snapshot can
    temporarily lag the WGSBN archive, so every unmatched Bulletin record
    should not automatically become a permanent local record.
    """
    normalized_permids = list(dict.fromkeys(str(permid).strip() for permid in permids if str(permid).strip()))
    if not normalized_permids:
        raise ValueError("At least one permanent minor-planet number is required")

    connection = db.connect(db_path)
    db.initialize(connection)
    classifier = CitationClassifier(
        mode=classifier_mode,
        model=ollama_model,
        host=ollama_host,
        timeout=ollama_timeout,
        think=ollama_think,
        think_on_review=ollama_think_on_review,
    )
    facet_classifier = PersonFacetClassifier(
        mode=classifier_mode, model=ollama_model, host=ollama_host,
        timeout=ollama_timeout, think=ollama_think,
    )
    job = new_classification_job(
        command="backfill-wgsbn-only", classifier_mode=classifier_mode, ollama_model=ollama_model,
        ollama_host=ollama_host, ollama_timeout=ollama_timeout, ollama_think=ollama_think,
        ollama_think_on_review=ollama_think_on_review, include_categories=True, include_person_facets=True,
    )
    db.create_classification_job(connection, job)
    inserted = updated = unchanged = missing = 0
    for index, permid in enumerate(normalized_permids, start=1):
        publication = connection.execute(
            """
            SELECT permid, name, citation_text, published_year, reference, source_url
            FROM naming_publications
            WHERE permid = ?
            ORDER BY published_year, source_url
            LIMIT 1
            """,
            (permid,),
        ).fetchone()
        if publication is None:
            missing += 1
            continue

        citation_text = publication["citation_text"]
        categories = classifier.classify(citation_text)
        facets = facet_classifier.classify(citation_text, [category.value for category in categories])
        status = db.upsert_minor_planet(
            connection,
            permid=permid,
            name_ascii=_ascii_name(publication["name"]),
            name_display=publication["name"],
            identifier={
                "permid": permid,
                "iau_designation": f"({permid})",
                "citation": citation_text,
            },
            citation_categories=categories,
            citation_facets=facets,
        )
        db.assign_classification_job(connection, permid, "citation_category", job["job_id"])
        db.assign_classification_job(connection, permid, "person_facet", job["job_id"])
        connection.execute(
            """
            UPDATE minor_planets
            SET naming_published_date = NULL, naming_published_year = ?, naming_reference = ?,
                naming_source = 'WGSBN Bulletin', naming_source_url = ?
            WHERE permid = ?
            """,
            (
                publication["published_year"],
                publication["reference"],
                publication["source_url"],
                permid,
            ),
        )
        if status == "inserted":
            inserted += 1
        elif status == "updated":
            updated += 1
        else:
            unchanged += 1
        progress.step("WGSBN-only backfill", index, len(normalized_permids), detail=permid)

    db.finish_classification_job(connection, job["job_id"], "completed")
    connection.commit()
    connection.close()
    return {
        "records": len(normalized_permids),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "missing": missing,
        "classifier": classifier_mode,
        "job_id": job["job_id"],
    }


def _ascii_name(name: str) -> str:
    """Make an MPC-list-compatible ASCII search form while retaining display text."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")


def _normalize_category_filters(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in values:
        for part in str(raw).split(","):
            cleaned = part.strip()
            if not cleaned:
                continue
            canonical = normalize_citation_category(cleaned) or cleaned
            if canonical not in normalized:
                normalized.append(canonical)
    return normalized


def fetch_names(url: str = MPNAMES_URL) -> list[NameRecord]:
    return parse_mpnames_html(_read_text_url(url))


def fetch_discoveries(
    *,
    numbered_mps_url: str = NUMBERED_MPS_URL,
    cache_path: Path = NUMBERED_MPS_CACHE,
    refresh_cache: bool = False,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, DiscoveryRecord]:
    if refresh_cache or not cache_path.exists():
        progress.message(f"Fetching discovery circumstances from {numbered_mps_url}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(_read_bytes_url(numbered_mps_url))
    else:
        progress.message(f"Using cached discovery circumstances from {cache_path}")
    text = cache_path.read_text(encoding="utf-8", errors="replace")
    discoveries = parse_numbered_mps(text)
    progress.message(f"Parsed {len(discoveries)} discovery records")
    return discoveries


def _select_names_for_mode(
    connection,
    names: list[NameRecord],
    *,
    mode: str,
    limit: int | None,
) -> list[NameRecord]:
    if limit is not None and limit < 0:
        raise ValueError("limit must be greater than or equal to zero")

    if mode == "reset":
        candidates = names
    elif mode == "update":
        candidates = names
    elif mode == "add":
        existing = db.existing_permids(connection)
        candidates = [record for record in names if record.permid not in existing]
    elif mode == "repair":
        existing = db.existing_permids(connection)
        incomplete = db.incomplete_permids(connection)
        candidates = [record for record in names if record.permid not in existing or record.permid in incomplete]
    else:
        raise ValueError(f"Unknown ingest mode: {mode}")

    if limit is None:
        return candidates
    return candidates[:limit]


def fetch_identifiers(
    names: list[NameRecord],
    *,
    identifier_url: str = IDENTIFIER_URL,
    delay: float = IDENTIFIER_INTER_REQUEST_DELAY_SECONDS,
    batch_size: int = IDENTIFIER_BATCH_SIZE,
    pause_every: int = IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS,
    pause_seconds: float = IDENTIFIER_LONG_PAUSE_SECONDS,
    progress: ProgressReporter = QUIET_PROGRESS,
) -> dict[str, dict[str, Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    results: dict[str, dict[str, Any]] = {}
    total_batches = (len(names) + batch_size - 1) // batch_size

    def query_api(ids_list: list[str], use_group: bool = True) -> dict[str, dict[str, Any]]:
        payload: dict[str, Any] = {
            "ids": ids_list,
        }
        if use_group:
            payload["group"] = "Minor Planets"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            identifier_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        res: dict[str, dict[str, Any]] = {}
        for key, value in body.items():
            if isinstance(value, dict):
                res[key] = value
        return res

    for start in range(0, len(names), batch_size):
        batch = names[start : start + batch_size]
        batch_number = (start // batch_size) + 1
        progress.step(
            "Identifier API request",
            batch_number,
            total_batches,
            detail=f"objects {start + 1}-{start + len(batch)}",
        )
        try:
            body = query_api([record.permid for record in batch], use_group=True)
            results.update(body)
        except urllib.error.HTTPError as e:
            print(f"Error fetching identifiers for batch {batch_number}: {e}. Retrying individually...")
            for record in batch:
                time.sleep(delay)
                try:
                    indiv_res = query_api([record.permid], use_group=True)
                    results.update(indiv_res)
                except urllib.error.HTTPError as indiv_err:
                    print(
                        f"Error fetching identifier for {record.name_ascii} (permid={record.permid}) (with group): {indiv_err}. "
                        "Retrying without group constraint..."
                    )
                    time.sleep(delay)
                    try:
                        indiv_res = query_api([record.permid], use_group=False)
                        results.update(indiv_res)
                    except urllib.error.HTTPError as retry_err:
                        print(f"Failed to fetch identifier for {record.name_ascii} (permid={record.permid}) even without group constraint: {retry_err}")
        _sleep_after_mpc_request(
            request_number=batch_number,
            has_more=start + batch_size < len(names),
            delay=delay,
            pause_every=pause_every,
            pause_seconds=pause_seconds,
            progress=progress,
            label="Identifier API",
        )
    return results


def fetch_orbits(
    names: list[NameRecord],
    *,
    identifiers: dict[str, dict[str, Any]],
    orbit_url: str = ORBITS_URL,
    delay: float = ORBIT_INTER_REQUEST_DELAY_SECONDS,
    pause_every: int = ORBIT_LONG_PAUSE_EVERY_REQUESTS,
    pause_seconds: float = ORBIT_LONG_PAUSE_SECONDS,
    progress: ProgressReporter = QUIET_PROGRESS,
    on_long_pause: Callable[[int, dict[str, OrbitRecord]], None] | None = None,
) -> dict[str, OrbitRecord]:
    records: dict[str, OrbitRecord] = {}
    total = len(names)
    for index, record in enumerate(names, start=1):
        identifier = (
            identifiers.get(record.permid)
            or identifiers.get(record.name_ascii)
            or identifiers.get(record.name_display)
            or {}
        )
        desig = _orbit_api_designation(record, identifier)
        progress.step("Orbit API request", index, total, detail=desig)
        payload = _fetch_orbit_payload(orbit_url, desig)
        orbit = parse_orbits_api_response(payload)
        if orbit:
            for key in _orbit_keys(record, identifier, orbit):
                records[key] = orbit
        _sleep_after_mpc_request(
            request_number=index,
            has_more=index < total,
            delay=delay,
            pause_every=pause_every,
            pause_seconds=pause_seconds,
            progress=progress,
            label="Orbit API",
            long_pause_work=(lambda index=index, records=records: on_long_pause(index, records))
            if on_long_pause
            else None,
        )
    return records


def _fetch_orbit_payload(orbit_url: str, desig: str) -> Any:
    data = json.dumps({"desig": desig}).encode("utf-8")
    request = urllib.request.Request(
        orbit_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise


def _orbit_api_designation(record: NameRecord, identifier: dict[str, Any]) -> str:
    return str(
        identifier.get("permid")
        or record.permid
        or identifier.get("iau_designation")
        or identifier.get("packed_permid")
        or record.name_ascii
    ).strip("()")


def _orbit_keys(record: NameRecord, identifier: dict[str, Any], orbit: OrbitRecord) -> set[str]:
    keys = {
        record.permid,
        record.name_ascii,
        record.name_display,
        orbit.permid_or_packed,
        orbit.readable_designation,
        str(identifier.get("permid") or ""),
        str(identifier.get("iau_designation") or ""),
        str(identifier.get("packed_permid") or ""),
    }
    return {key.strip().strip("()") for key in keys if key and key.strip()}


def _unique_orbit_count(orbits: dict[str, OrbitRecord]) -> int:
    return len({id(orbit) for orbit in orbits.values()})


def _sleep_after_mpc_request(
    *,
    request_number: int,
    has_more: bool,
    delay: float,
    pause_every: int,
    pause_seconds: float,
    progress: ProgressReporter = QUIET_PROGRESS,
    label: str,
    long_pause_work: Callable[[], None] | None = None,
) -> None:
    if not has_more:
        return
    if pause_every > 0 and request_number % pause_every == 0:
        if pause_seconds > 0:
            remaining = pause_seconds
            if long_pause_work:
                progress.message(
                    f"Rate limit pause after {request_number} {label} requests: "
                    f"using up to {pause_seconds:g}s for local work"
                )
                started_at = time.monotonic()
                long_pause_work()
                elapsed = max(0.0, time.monotonic() - started_at)
                remaining = max(0.0, pause_seconds - elapsed)
                if remaining > 0:
                    progress.message(
                        f"Rate limit pause remaining wait: {remaining:.2f}s "
                        f"(local work {elapsed:.2f}s)"
                    )
                else:
                    progress.message(
                        f"Rate limit pause covered by local work: {elapsed:.2f}s "
                        f">= {pause_seconds:g}s"
                    )
            else:
                progress.message(
                    f"Rate limit pause after {request_number} {label} requests: {pause_seconds:g}s"
                )
            if remaining > 0:
                time.sleep(remaining)
        return
    if delay > 0:
        time.sleep(delay)


def _should_report_item(current: int, total: int) -> bool:
    if total <= 0:
        return False
    if current == 1 or current == total:
        return True
    interval = 10 if total <= 100 else max(25, total // 20)
    return current % interval == 0


def _orbit_for(
    permid: str,
    identifier: dict[str, Any],
    orbits: dict[str, OrbitRecord],
) -> OrbitRecord | None:
    keys = [
        permid,
        str(identifier.get("permid") or ""),
        str(identifier.get("iau_designation") or ""),
        str(identifier.get("packed_permid") or ""),
    ]
    for key in keys:
        cleaned = key.strip()
        if cleaned in orbits:
            return orbits[cleaned]
        stripped = cleaned.strip("()")
        if stripped in orbits:
            return orbits[stripped]
    return None


def _read_text_url(url: str) -> str:
    return _read_bytes_url(url).decode("utf-8", errors="replace")


def _read_bytes_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Minor Planet Names Search/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()
