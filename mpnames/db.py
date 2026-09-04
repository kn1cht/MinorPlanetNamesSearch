"""SQLite storage and query layer."""

from __future__ import annotations

import html
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .categories import Category, categorize_citation
from .latex import decode_latex
from .mpcorb import OrbitRecord
from .numbered_mps import DiscoveryRecord
from .person_facets import CitationFacet, PersonFacetClassifier
from .settings import DEFAULT_DB
from .wgsbn import WITHDRAWN_NAMING_PERMIDS


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "are",
    "asteroid",
    "astronomer",
    "been",
    "being",
    "born",
    "city",
    "for",
    "from",
    "has",
    "his",
    "honor",
    "honored",
    "honours",
    "into",
    "its",
    "minor",
    "named",
    "planet",
    "professor",
    "she",
    "the",
    "their",
    "this",
    "was",
    "were",
    "who",
    "with",
}

DEPRECATED_CITATION_CATEGORIES = {"Science/Culture"}
QUERY_TARGETS = {"both", "name", "citation"}

SEARCH_SORTS = {
    "alpha": "mp.name_ascii COLLATE NOCASE",
    "number": "CAST(mp.permid AS INTEGER)",
    "absolute_magnitude": "mp.absolute_magnitude_h",
    "semimajor_axis": "mp.semimajor_axis",
    "eccentricity": "mp.eccentricity",
    "inclination": "mp.inclination",
}

NUMERIC_NULL_LAST_SORTS = {
    "absolute_magnitude",
    "semimajor_axis",
    "eccentricity",
    "inclination",
}


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS minor_planets (
            permid TEXT PRIMARY KEY,
            name_ascii TEXT NOT NULL,
            name_display TEXT NOT NULL,
            iau_designation TEXT,
            citation_html TEXT,
            citation_text TEXT,
            naming_published_date TEXT,
            naming_published_year INTEGER,
            naming_reference TEXT,
            naming_source TEXT,
            naming_source_url TEXT,
            discovery_date TEXT,
            discovery_site TEXT,
            discoverer_text TEXT,
            discovery_source TEXT,
            unpacked_primary_provisional_designation TEXT,
            packed_primary_provisional_designation TEXT,
            packed_permid TEXT,
            orbit_type TEXT,
            is_neo INTEGER NOT NULL DEFAULT 0,
            is_one_km_neo INTEGER NOT NULL DEFAULT 0,
            is_pha INTEGER NOT NULL DEFAULT 0,
            absolute_magnitude_h REAL,
            slope_g REAL,
            epoch TEXT,
            mean_anomaly REAL,
            argument_perihelion REAL,
            ascending_node REAL,
            inclination REAL,
            eccentricity REAL,
            mean_daily_motion REAL,
            semimajor_axis REAL,
            uncertainty TEXT,
            observations INTEGER,
            oppositions INTEGER,
            rms_residual REAL,
            flags_hex TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        -- The public initial view always uses the same aggregate data for one
        -- imported dataset.  Materialize it during ingest so the Pages API
        -- does not need to scan the source tables on every cache miss.
        CREATE TABLE IF NOT EXISTS dataset_stats (
            cache_key TEXT PRIMARY KEY CHECK (cache_key = 'base'),
            payload_json TEXT NOT NULL,
            initial_search_json TEXT NOT NULL,
            refreshed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS categories (
            permid TEXT NOT NULL,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            source TEXT NOT NULL,
            confidence REAL NOT NULL,
            PRIMARY KEY (permid, kind, value, source),
            FOREIGN KEY (permid) REFERENCES minor_planets(permid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS categories_kind_value_permid
        ON categories(kind, value, permid);

        CREATE TABLE IF NOT EXISTS citation_facets (
            permid TEXT NOT NULL,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            evidence_text TEXT,
            source TEXT NOT NULL,
            confidence REAL NOT NULL,
            PRIMARY KEY (permid, kind, value, source),
            FOREIGN KEY (permid) REFERENCES minor_planets(permid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS citation_facets_kind_value
        ON citation_facets(kind, value, permid);

        CREATE TABLE IF NOT EXISTS classification_jobs (
            job_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            classifier_mode TEXT NOT NULL,
            ollama_model TEXT,
            ollama_host TEXT NOT NULL,
            ollama_timeout REAL NOT NULL,
            ollama_think INTEGER NOT NULL,
            ollama_think_on_review INTEGER NOT NULL,
            code_commit TEXT,
            worktree_dirty INTEGER NOT NULL,
            prompts_json TEXT NOT NULL,
            prompt_sha256 TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS classification_assignments (
            permid TEXT NOT NULL,
            target TEXT NOT NULL,
            job_id TEXT NOT NULL,
            assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (permid, target),
            FOREIGN KEY (permid) REFERENCES minor_planets(permid) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES classification_jobs(job_id) ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS classification_assignments_job
        ON classification_assignments(job_id);

        CREATE TABLE IF NOT EXISTS discovery_facets (
            permid TEXT NOT NULL,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (permid, kind, value),
            FOREIGN KEY (permid) REFERENCES minor_planets(permid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS discovery_facets_kind_value_permid
        ON discovery_facets(kind, value, permid);

        CREATE INDEX IF NOT EXISTS minor_planets_is_neo_permid
        ON minor_planets(is_neo, permid);

        CREATE INDEX IF NOT EXISTS minor_planets_is_pha_permid
        ON minor_planets(is_pha, permid);

        CREATE TABLE IF NOT EXISTS ingest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            status TEXT NOT NULL,
            message TEXT
        );

        CREATE TABLE IF NOT EXISTS identifier_cache (
            input_name TEXT PRIMARY KEY,
            response_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS wgsbn_bulletins (
            source_url TEXT PRIMARY KEY,
            volume INTEGER NOT NULL,
            issue INTEGER NOT NULL,
            published_date TEXT NOT NULL,
            published_year INTEGER NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS naming_publications (
            permid TEXT NOT NULL,
            source_url TEXT NOT NULL,
            published_date TEXT NOT NULL,
            published_year INTEGER NOT NULL,
            name TEXT NOT NULL,
            citation_text TEXT,
            reference TEXT,
            PRIMARY KEY (permid, source_url)
        );

        CREATE INDEX IF NOT EXISTS naming_publications_permid_date
        ON naming_publications(permid, published_date);

        CREATE VIRTUAL TABLE IF NOT EXISTS minor_planets_fts
        USING fts5(
            permid,
            packed_permid,
            iau_designation,
            name_ascii,
            name_display,
            citation_text,
            discovery_site,
            discoverer_text,
            content='minor_planets',
            content_rowid='rowid',
            tokenize='trigram'
        );

        CREATE TRIGGER IF NOT EXISTS minor_planets_ai AFTER INSERT ON minor_planets BEGIN
            INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES (
                new.rowid,
                new.permid,
                COALESCE(new.packed_permid, ''),
                COALESCE(new.iau_designation, ''),
                new.name_ascii,
                new.name_display,
                COALESCE(new.citation_text, ''),
                COALESCE(new.discovery_site, ''),
                COALESCE(new.discoverer_text, '')
            );
        END;

        CREATE TRIGGER IF NOT EXISTS minor_planets_ad AFTER DELETE ON minor_planets BEGIN
            INSERT INTO minor_planets_fts(minor_planets_fts, rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES(
                'delete',
                old.rowid,
                old.permid,
                COALESCE(old.packed_permid, ''),
                COALESCE(old.iau_designation, ''),
                old.name_ascii,
                old.name_display,
                COALESCE(old.citation_text, ''),
                COALESCE(old.discovery_site, ''),
                COALESCE(old.discoverer_text, '')
            );
        END;

        CREATE TRIGGER IF NOT EXISTS minor_planets_au AFTER UPDATE ON minor_planets BEGIN
            INSERT INTO minor_planets_fts(minor_planets_fts, rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES(
                'delete',
                old.rowid,
                old.permid,
                COALESCE(old.packed_permid, ''),
                COALESCE(old.iau_designation, ''),
                old.name_ascii,
                old.name_display,
                COALESCE(old.citation_text, ''),
                COALESCE(old.discovery_site, ''),
                COALESCE(old.discoverer_text, '')
            );
            INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES (
                new.rowid,
                new.permid,
                COALESCE(new.packed_permid, ''),
                COALESCE(new.iau_designation, ''),
                new.name_ascii,
                new.name_display,
                COALESCE(new.citation_text, ''),
                COALESCE(new.discovery_site, ''),
                COALESCE(new.discoverer_text, '')
            );
        END;
        """
    )
    _ensure_minor_planet_columns(connection)
    _ensure_dataset_stats_columns(connection)
    _ensure_wgsbn_publication_year_columns(connection)
    _ensure_fts_schema(connection)
    _migrate_deprecated_citation_categories(connection)
    _migrate_missing_citation_categories(connection)
    connection.commit()




def _ensure_minor_planet_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(minor_planets)").fetchall()
    }
    required = {
        "discovery_date": "TEXT",
        "discovery_site": "TEXT",
        "discoverer_text": "TEXT",
        "discovery_source": "TEXT",
        "naming_published_date": "TEXT",
        "naming_published_year": "INTEGER",
        "naming_reference": "TEXT",
        "naming_source": "TEXT",
        "naming_source_url": "TEXT",
    }
    for name, column_type in required.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE minor_planets ADD COLUMN {name} {column_type}")


def _ensure_dataset_stats_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(dataset_stats)").fetchall()
    }
    if "initial_search_json" not in existing:
        connection.execute(
            "ALTER TABLE dataset_stats ADD COLUMN initial_search_json TEXT NOT NULL DEFAULT '{}'"
        )


def _ensure_wgsbn_publication_year_columns(connection: sqlite3.Connection) -> None:
    bulletin_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(wgsbn_bulletins)").fetchall()
    }
    if "published_year" not in bulletin_columns:
        connection.execute("ALTER TABLE wgsbn_bulletins ADD COLUMN published_year INTEGER")
    connection.execute(
        "UPDATE wgsbn_bulletins SET published_year = 2020 + volume WHERE published_year IS NULL"
    )

    publication_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(naming_publications)").fetchall()
    }
    if "published_year" not in publication_columns:
        connection.execute("ALTER TABLE naming_publications ADD COLUMN published_year INTEGER")
    connection.execute(
        """
        UPDATE naming_publications
        SET published_year = (
            SELECT published_year FROM wgsbn_bulletins
            WHERE wgsbn_bulletins.source_url = naming_publications.source_url
        )
        WHERE published_year IS NULL
        """
    )


def existing_wgsbn_bulletin_urls(connection: sqlite3.Connection) -> set[str]:
    return {
        row["source_url"]
        for row in connection.execute("SELECT source_url FROM wgsbn_bulletins").fetchall()
    }


def replace_wgsbn_bulletin(
    connection: sqlite3.Connection,
    *,
    source_url: str,
    volume: int,
    issue: int,
    published_date: str,
    published_year: int,
    namings: list[Any],
) -> int:
    """Store the complete naming list for one WGSBN Bulletin."""
    # A few official JSON files repeat an object in the same Bulletin (for
    # example when a related correction is included).  The publication date is
    # identical, so retain the first naming record for this date-level index.
    unique_namings: dict[str, Any] = {}
    for naming in namings:
        if naming.permid in WITHDRAWN_NAMING_PERMIDS:
            continue
        unique_namings.setdefault(naming.permid, naming)
    connection.execute("DELETE FROM naming_publications WHERE source_url = ?", (source_url,))
    connection.executemany(
        """
        INSERT INTO naming_publications(permid, source_url, published_date, published_year, name, citation_text, reference)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (naming.permid, source_url, published_date, published_year, naming.name, naming.citation, naming.reference)
            for naming in unique_namings.values()
        ],
    )
    connection.execute(
        """
        INSERT INTO wgsbn_bulletins(source_url, volume, issue, published_date, published_year)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_url) DO UPDATE SET
            volume = excluded.volume,
            issue = excluded.issue,
            published_date = excluded.published_date,
            published_year = excluded.published_year,
            fetched_at = CURRENT_TIMESTAMP
        """,
        (source_url, volume, issue, published_date, published_year),
    )
    return len(unique_namings)




def sync_wgsbn_naming_metadata(connection: sqlite3.Connection) -> dict[str, int]:
    """Apply the earliest WGSBN publication year to locally stored minor planets."""
    rows = connection.execute(
        """
        SELECT np.permid, np.published_year, np.reference, np.source_url
        FROM naming_publications AS np
        JOIN (
            SELECT permid, MIN(published_year) AS published_year
            FROM naming_publications
            GROUP BY permid
        ) AS first_publication
          ON first_publication.permid = np.permid
         AND first_publication.published_year = np.published_year
        ORDER BY np.permid, np.source_url
        """
    ).fetchall()
    selected: set[str] = set()
    updated = unchanged = missing = 0
    for row in rows:
        permid = row["permid"]
        if permid in selected:
            continue
        selected.add(permid)
        current = connection.execute(
            """
            SELECT naming_published_date, naming_published_year, naming_reference, naming_source, naming_source_url
            FROM minor_planets WHERE permid = ?
            """,
            (permid,),
        ).fetchone()
        if current is None:
            missing += 1
            continue
        values = (None, row["published_year"], row["reference"], "WGSBN Bulletin", row["source_url"])
        if tuple(current) == values:
            unchanged += 1
            continue
        connection.execute(
            """
            UPDATE minor_planets
            SET naming_published_date = ?, naming_published_year = ?, naming_reference = ?, naming_source = ?, naming_source_url = ?
            WHERE permid = ?
            """,
            (*values, permid),
        )
        updated += 1
    return {"publications": len(selected), "updated": updated, "unchanged": unchanged, "missing": missing}


def _ensure_fts_schema(connection: sqlite3.Connection) -> None:
    expected = {
        "permid",
        "packed_permid",
        "iau_designation",
        "name_ascii",
        "name_display",
        "citation_text",
        "discovery_site",
        "discoverer_text",
    }
    rows = connection.execute("PRAGMA table_info(minor_planets_fts)").fetchall()
    existing = {row["name"] for row in rows}
    if expected.issubset(existing):
        return

    connection.executescript(
        """
        DROP TRIGGER IF EXISTS minor_planets_ai;
        DROP TRIGGER IF EXISTS minor_planets_ad;
        DROP TRIGGER IF EXISTS minor_planets_au;
        DROP TABLE IF EXISTS minor_planets_fts;

        CREATE VIRTUAL TABLE minor_planets_fts
        USING fts5(
            permid,
            packed_permid,
            iau_designation,
            name_ascii,
            name_display,
            citation_text,
            discovery_site,
            discoverer_text,
            content='minor_planets',
            content_rowid='rowid',
            tokenize='trigram'
        );

        INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
        SELECT
            rowid,
            permid,
            COALESCE(packed_permid, ''),
            COALESCE(iau_designation, ''),
            name_ascii,
            name_display,
            COALESCE(citation_text, ''),
            COALESCE(discovery_site, ''),
            COALESCE(discoverer_text, '')
        FROM minor_planets;

        CREATE TRIGGER minor_planets_ai AFTER INSERT ON minor_planets BEGIN
            INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES (
                new.rowid,
                new.permid,
                COALESCE(new.packed_permid, ''),
                COALESCE(new.iau_designation, ''),
                new.name_ascii,
                new.name_display,
                COALESCE(new.citation_text, ''),
                COALESCE(new.discovery_site, ''),
                COALESCE(new.discoverer_text, '')
            );
        END;

        CREATE TRIGGER minor_planets_ad AFTER DELETE ON minor_planets BEGIN
            INSERT INTO minor_planets_fts(minor_planets_fts, rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES(
                'delete',
                old.rowid,
                old.permid,
                COALESCE(old.packed_permid, ''),
                COALESCE(old.iau_designation, ''),
                old.name_ascii,
                old.name_display,
                COALESCE(old.citation_text, ''),
                COALESCE(old.discovery_site, ''),
                COALESCE(old.discoverer_text, '')
            );
        END;

        CREATE TRIGGER minor_planets_au AFTER UPDATE ON minor_planets BEGIN
            INSERT INTO minor_planets_fts(minor_planets_fts, rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES(
                'delete',
                old.rowid,
                old.permid,
                COALESCE(old.packed_permid, ''),
                COALESCE(old.iau_designation, ''),
                old.name_ascii,
                old.name_display,
                COALESCE(old.citation_text, ''),
                COALESCE(old.discovery_site, ''),
                COALESCE(old.discoverer_text, '')
            );
            INSERT INTO minor_planets_fts(rowid, permid, packed_permid, iau_designation, name_ascii, name_display, citation_text, discovery_site, discoverer_text)
            VALUES (
                new.rowid,
                new.permid,
                COALESCE(new.packed_permid, ''),
                COALESCE(new.iau_designation, ''),
                new.name_ascii,
                new.name_display,
                COALESCE(new.citation_text, ''),
                COALESCE(new.discovery_site, ''),
                COALESCE(new.discoverer_text, '')
            );
        END;
        """
    )


def existing_permids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT permid FROM minor_planets").fetchall()
    return {str(row["permid"]) for row in rows}


def incomplete_permids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        """
        SELECT permid
        FROM minor_planets
        WHERE iau_designation IS NULL
           OR packed_permid IS NULL
           OR discovery_date IS NULL
           OR discovery_site IS NULL
           OR discoverer_text IS NULL
           OR orbit_type IS NULL
        """
    ).fetchall()
    return {str(row["permid"]) for row in rows}


def upsert_minor_planet(
    connection: sqlite3.Connection,
    *,
    permid: str,
    name_ascii: str,
    name_display: str,
    identifier: dict[str, Any] | None = None,
    orbit: OrbitRecord | None = None,
    discovery: DiscoveryRecord | None = None,
    citation_categories: list[Category] | None = None,
    citation_facets: list[CitationFacet] | None = None,
) -> str:
    identifier = identifier or {}
    values = minor_planet_values(
        permid=permid,
        name_ascii=name_ascii,
        name_display=name_display,
        identifier=identifier,
        orbit=orbit,
        discovery=discovery,
    )
    categories = _categories_for(values["citation_text"], orbit, citation_categories=citation_categories)
    facets = (
        list(citation_facets)
        if citation_facets is not None
        else PersonFacetClassifier(mode="rules").classify(
            values["citation_text"], [category.value for category in categories if category.kind == "citation"]
        )
    )
    existing = connection.execute(
        f"SELECT {', '.join(values)} FROM minor_planets WHERE permid = ?",
        (values["permid"],),
    ).fetchone()
    status = "inserted" if existing is None else "updated"
    discovery_values = _discovery_facet_values(discovery)
    if (
        existing is not None
        and _row_matches(existing, values)
        and _categories_match(connection, values["permid"], categories)
        and _citation_facets_match(connection, values["permid"], facets)
        and _discovery_facets_match(connection, values["permid"], discovery_values)
    ):
        return "unchanged"

    columns = ", ".join(values)
    placeholders = ", ".join(f":{key}" for key in values)
    updates = ", ".join(f"{key}=excluded.{key}" for key in values if key != "permid")
    connection.execute(
        f"""
        INSERT INTO minor_planets ({columns})
        VALUES ({placeholders})
        ON CONFLICT(permid) DO UPDATE SET
            {updates},
            updated_at=CURRENT_TIMESTAMP
        """,
        values,
    )

    replace_categories(connection, values["permid"], categories)
    replace_citation_facets(connection, values["permid"], facets)
    replace_discovery_facets(connection, values["permid"], discovery_values)
    return status


def minor_planet_values(
    *,
    permid: str,
    name_ascii: str,
    name_display: str,
    identifier: dict[str, Any],
    orbit: OrbitRecord | None,
    discovery: DiscoveryRecord | None = None,
) -> dict[str, Any]:
    citation_html = identifier.get("citation")
    citation_text = html_to_text(citation_html)
    return {
        "permid": str(identifier.get("permid") or permid),
        "name_ascii": name_ascii,
        "name_display": name_display,
        "iau_designation": identifier.get("iau_designation"),
        "citation_html": citation_html,
        "citation_text": citation_text,
        "discovery_date": discovery.discovery_date if discovery else None,
        "discovery_site": discovery.discovery_site if discovery else None,
        "discoverer_text": discovery.discoverer_text if discovery else None,
        "discovery_source": "NumberedMPs.txt" if discovery else None,
        "unpacked_primary_provisional_designation": identifier.get("unpacked_primary_provisional_designation"),
        "packed_primary_provisional_designation": identifier.get("packed_primary_provisional_designation"),
        "packed_permid": identifier.get("packed_permid"),
        "orbit_type": orbit.orbit_type if orbit else None,
        "is_neo": int(orbit.is_neo) if orbit else 0,
        "is_one_km_neo": int(orbit.is_one_km_neo) if orbit else 0,
        "is_pha": int(orbit.is_pha) if orbit else 0,
        "absolute_magnitude_h": orbit.absolute_magnitude_h if orbit else None,
        "slope_g": orbit.slope_g if orbit else None,
        "epoch": orbit.epoch if orbit else None,
        "mean_anomaly": orbit.mean_anomaly if orbit else None,
        "argument_perihelion": orbit.argument_perihelion if orbit else None,
        "ascending_node": orbit.ascending_node if orbit else None,
        "inclination": orbit.inclination if orbit else None,
        "eccentricity": orbit.eccentricity if orbit else None,
        "mean_daily_motion": orbit.mean_daily_motion if orbit else None,
        "semimajor_axis": orbit.semimajor_axis if orbit else None,
        "uncertainty": orbit.uncertainty if orbit else None,
        "observations": orbit.observations if orbit else None,
        "oppositions": orbit.oppositions if orbit else None,
        "rms_residual": orbit.rms_residual if orbit else None,
        "flags_hex": orbit.flags_hex if orbit else None,
    }


def replace_categories(connection: sqlite3.Connection, permid: str, categories: list[Category]) -> None:
    connection.execute("DELETE FROM categories WHERE permid = ?", (permid,))
    connection.executemany(
        """
        INSERT OR REPLACE INTO categories (permid, kind, value, source, confidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(permid, category.kind, category.value, category.source, category.confidence) for category in categories],
    )


def replace_citation_categories(
    connection: sqlite3.Connection,
    permid: str,
    categories: list[Category],
) -> None:
    connection.execute("DELETE FROM categories WHERE permid = ? AND kind = 'citation'", (permid,))
    connection.executemany(
        """
        INSERT OR REPLACE INTO categories (permid, kind, value, source, confidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (permid, category.kind, category.value, category.source, category.confidence)
            for category in categories
            if category.kind == "citation"
        ],
    )


def replace_citation_facets(
    connection: sqlite3.Connection,
    permid: str,
    facets: list[CitationFacet],
) -> None:
    connection.execute("DELETE FROM citation_facets WHERE permid = ?", (permid,))
    connection.executemany(
        """
        INSERT OR REPLACE INTO citation_facets(permid, kind, value, evidence_text, source, confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (permid, facet.kind, facet.value, facet.evidence_text, facet.source, facet.confidence)
            for facet in facets
        ],
    )


def create_classification_job(connection: sqlite3.Connection, job: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO classification_jobs (
            job_id, command, started_at, status, classifier_mode, ollama_model,
            ollama_host, ollama_timeout, ollama_think, ollama_think_on_review,
            code_commit, worktree_dirty, prompts_json, prompt_sha256
        ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job["job_id"], job["command"], job["started_at"], job["classifier_mode"],
            job["ollama_model"], job["ollama_host"], job["ollama_timeout"],
            int(job["ollama_think"]), int(job["ollama_think_on_review"]), job["code_commit"],
            int(job["worktree_dirty"]), job["prompts_json"], job["prompt_sha256"],
        ),
    )


def assign_classification_job(connection: sqlite3.Connection, permid: str, target: str, job_id: str) -> None:
    connection.execute(
        """
        INSERT INTO classification_assignments (permid, target, job_id, assigned_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(permid, target) DO UPDATE SET job_id = excluded.job_id, assigned_at = CURRENT_TIMESTAMP
        """,
        (permid, target, job_id),
    )


def finish_classification_job(connection: sqlite3.Connection, job_id: str, status: str) -> None:
    connection.execute(
        "UPDATE classification_jobs SET status = ?, finished_at = CURRENT_TIMESTAMP WHERE job_id = ?",
        (status, job_id),
    )


def replace_discovery_facets(
    connection: sqlite3.Connection,
    permid: str,
    values: list[tuple[str, str]],
) -> None:
    connection.execute("DELETE FROM discovery_facets WHERE permid = ?", (permid,))
    connection.executemany(
        """
        INSERT OR REPLACE INTO discovery_facets (permid, kind, value)
        VALUES (?, ?, ?)
        """,
        [(permid, kind, value) for kind, value in values],
    )


def update_discovery(
    connection: sqlite3.Connection,
    permid: str,
    discovery: DiscoveryRecord,
) -> str:
    values = {
        "discovery_date": discovery.discovery_date,
        "discovery_site": discovery.discovery_site,
        "discoverer_text": discovery.discoverer_text,
        "discovery_source": "NumberedMPs.txt",
    }
    existing = connection.execute(
        """
        SELECT discovery_date, discovery_site, discoverer_text, discovery_source
        FROM minor_planets
        WHERE permid = ?
        """,
        (permid,),
    ).fetchone()
    if existing is None:
        return "missing"

    discovery_values = _discovery_facet_values(discovery)
    if _row_matches(existing, values) and _discovery_facets_match(connection, permid, discovery_values):
        return "unchanged"

    connection.execute(
        """
        UPDATE minor_planets
        SET discovery_date = :discovery_date,
            discovery_site = :discovery_site,
            discoverer_text = :discoverer_text,
            discovery_source = :discovery_source,
            updated_at = CURRENT_TIMESTAMP
        WHERE permid = :permid
        """,
        {**values, "permid": permid},
    )
    replace_discovery_facets(connection, permid, discovery_values)
    return "updated"


def _discovery_facet_values(discovery: DiscoveryRecord | None) -> list[tuple[str, str]]:
    if not discovery:
        return []
    values = [("observatory", discovery.discovery_site)]
    values.extend(("discoverer", discoverer) for discoverer in discovery.discoverers)
    return sorted({(kind, value.strip()) for kind, value in values if value and value.strip()})


def _discovery_facets_match(
    connection: sqlite3.Connection,
    permid: str,
    values: list[tuple[str, str]],
) -> bool:
    rows = connection.execute(
        """
        SELECT kind, value
        FROM discovery_facets
        WHERE permid = ?
        ORDER BY kind, value
        """,
        (permid,),
    ).fetchall()
    current = [(row["kind"], row["value"]) for row in rows]
    return current == values


def _migrate_deprecated_citation_categories(connection: sqlite3.Connection) -> None:
    if not DEPRECATED_CITATION_CATEGORIES:
        return

    deprecated = sorted(DEPRECATED_CITATION_CATEGORIES)
    rows = connection.execute(
        f"""
        SELECT DISTINCT mp.permid, mp.citation_text
        FROM minor_planets mp
        JOIN categories c ON c.permid = mp.permid
        WHERE c.kind = 'citation'
          AND c.value IN ({_placeholders(deprecated)})
        """,
        deprecated,
    ).fetchall()
    if not rows:
        return

    connection.execute(
        f"""
        DELETE FROM categories
        WHERE kind = 'citation'
          AND value IN ({_placeholders(deprecated)})
        """,
        deprecated,
    )

    for row in rows:
        remaining = connection.execute(
            "SELECT COUNT(*) AS count FROM categories WHERE permid = ? AND kind = 'citation'",
            (row["permid"],),
        ).fetchone()["count"]
        if remaining:
            continue
        categories = categorize_citation(row["citation_text"])
        connection.executemany(
            """
            INSERT OR REPLACE INTO categories (permid, kind, value, source, confidence)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (row["permid"], category.kind, category.value, category.source, category.confidence)
                for category in categories
            ],
        )


def _migrate_missing_citation_categories(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT permid
        FROM minor_planets
        WHERE citation_text IS NULL OR TRIM(citation_text) = ''
        """
    ).fetchall()
    if not rows:
        return

    permids = [row["permid"] for row in rows]
    connection.execute(
        f"""
        DELETE FROM categories
        WHERE kind = 'citation'
          AND value IN ('Unknown', 'Other')
          AND permid IN ({_placeholders(permids)})
        """,
        permids,
    )
    connection.executemany(
        """
        INSERT OR REPLACE INTO categories (permid, kind, value, source, confidence)
        VALUES (?, 'citation', 'No Citation', 'rule', 1.0)
        """,
        [(permid,) for permid in permids],
    )


def _row_matches(row: sqlite3.Row, values: dict[str, Any]) -> bool:
    return all(row[key] == value for key, value in values.items())


def _categories_match(connection: sqlite3.Connection, permid: str, categories: list[Category]) -> bool:
    current_rows = connection.execute(
        """
        SELECT kind, value, source, confidence
        FROM categories
        WHERE permid = ?
        ORDER BY kind, value, source
        """,
        (permid,),
    ).fetchall()
    current = [(row["kind"], row["value"], row["source"], row["confidence"]) for row in current_rows]
    incoming = sorted((category.kind, category.value, category.source, category.confidence) for category in categories)
    return current == incoming


def _citation_facets_match(connection: sqlite3.Connection, permid: str, facets: list[CitationFacet]) -> bool:
    rows = connection.execute(
        """
        SELECT kind, value, evidence_text, source, confidence
        FROM citation_facets
        WHERE permid = ?
        ORDER BY kind, value, source
        """,
        (permid,),
    ).fetchall()
    current = [
        (row["kind"], row["value"], row["evidence_text"], row["source"], row["confidence"])
        for row in rows
    ]
    incoming = sorted(
        (facet.kind, facet.value, facet.evidence_text, facet.source, facet.confidence) for facet in facets
    )
    return current == incoming


def search(
    connection: sqlite3.Connection,
    *,
    q: str | list[str] = "",
    q_mode: str = "and",
    q_target: str = "both",
    orbit: str | list[str] = "",
    citation_category: str | list[str] = "",
    person_role: str | list[str] = "",
    gender: str | list[str] = "",
    discoverer: str | list[str] = "",
    observatory: str | list[str] = "",
    flag: str | list[str] = "",
    sort: str = "number",
    direction: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    where, params, joins = _filters(
        q=q,
        q_mode=q_mode,
        q_target=q_target,
        orbit=orbit,
        citation_category=citation_category,
        person_role=person_role,
        gender=gender,
        discoverer=discoverer,
        observatory=observatory,
        flag=flag,
    )
    representative_q = _representative_query(q)
    order_by, order_params = _search_order_by(sort, direction, q=representative_q)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    count_row = connection.execute(
        f"SELECT COUNT(DISTINCT mp.permid) AS total FROM minor_planets mp {joins} {where}",
        params,
    ).fetchone()
    total = int(count_row["total"])

    rows = connection.execute(
        f"""
        SELECT DISTINCT
            mp.permid,
            mp.name_ascii,
            mp.name_display,
            mp.iau_designation,
            mp.citation_text,
            mp.discovery_date,
            mp.discovery_site,
            mp.discoverer_text,
            mp.orbit_type,
            mp.is_neo,
            mp.is_pha,
            mp.absolute_magnitude_h,
            mp.semimajor_axis,
            mp.eccentricity,
            mp.inclination
        FROM minor_planets mp
        {joins}
        {where}
        {order_by}
        LIMIT ? OFFSET ?
        """,
        [*params, *order_params, limit, offset],
    ).fetchall()

    items = [_row_to_search_item(row, q=q) for row in rows]
    _attach_citation_categories(connection, items)
    _attach_citation_facets(connection, items)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "facets": facets(
            connection,
            q=q,
            q_mode=q_mode,
            q_target=q_target,
            orbit=orbit,
            citation_category=citation_category,
            person_role=person_role,
            gender=gender,
            discoverer=discoverer,
            observatory=observatory,
            flag=flag,
        ),
    }


def get_object(connection: sqlite3.Connection, permid: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM minor_planets WHERE permid = ?", (permid,)).fetchone()
    if not row:
        return None
    categories = connection.execute(
        "SELECT kind, value, source, confidence FROM categories WHERE permid = ? ORDER BY kind, value",
        (permid,),
    ).fetchall()
    data = dict(row)
    data["is_neo"] = bool(data["is_neo"])
    data["is_one_km_neo"] = bool(data["is_one_km_neo"])
    data["is_pha"] = bool(data["is_pha"])
    data["categories"] = [dict(category) for category in categories]
    data["citation_facets"] = [
        dict(facet)
        for facet in connection.execute(
            """
            SELECT kind, value, evidence_text, source, confidence
            FROM citation_facets WHERE permid = ? ORDER BY kind, value, source
            """,
            (permid,),
        ).fetchall()
    ]
    # Citation text is intentionally omitted from the detail API response.
    # Users are directed to the official MPC/WGSBN source via an external link.
    data.pop("citation_text", None)
    data.pop("citation_html", None)
    return data


def stats(connection: sqlite3.Connection) -> dict[str, Any]:
    """Calculate the current base statistics from the source tables.

    This intentionally remains a live calculation for local maintenance code.
    ``refresh_dataset_stats`` stores the same result after a completed ingest,
    and the public APIs read that materialized payload instead.
    """
    total = connection.execute("SELECT COUNT(*) AS c FROM minor_planets").fetchone()["c"]
    latest = connection.execute("SELECT MAX(updated_at) AS latest FROM minor_planets").fetchone()["latest"]
    orbit_rows = connection.execute(
        "SELECT COALESCE(orbit_type, 'Unclassified') AS value, COUNT(*) AS count "
        "FROM minor_planets GROUP BY 1 ORDER BY count DESC, 1"
    ).fetchall()
    citation_rows = connection.execute(
        "SELECT value, COUNT(*) AS count FROM categories WHERE kind = 'citation' "
        "GROUP BY 1 ORDER BY count DESC, 1"
    ).fetchall()
    person_role_rows = connection.execute(
        "SELECT value, COUNT(*) AS count FROM citation_facets WHERE kind = 'person_role' "
        "GROUP BY 1 ORDER BY count DESC, 1"
    ).fetchall()
    gender_rows = connection.execute(
        "SELECT value, COUNT(*) AS count FROM citation_facets WHERE kind = 'entity_gender' "
        "GROUP BY 1 ORDER BY count DESC, 1"
    ).fetchall()
    discoverer_rows = connection.execute(
        "SELECT value, COUNT(*) AS count FROM discovery_facets WHERE kind = 'discoverer' "
        "GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80"
    ).fetchall()
    observatory_rows = connection.execute(
        "SELECT value, COUNT(*) AS count FROM discovery_facets WHERE kind = 'observatory' "
        "GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80"
    ).fetchall()
    flag_rows = [
        {"value": "NEO", "count": connection.execute("SELECT COUNT(*) AS c FROM minor_planets WHERE is_neo = 1").fetchone()["c"]},
        {"value": "PHA", "count": connection.execute("SELECT COUNT(*) AS c FROM minor_planets WHERE is_pha = 1").fetchone()["c"]},
    ]
    return {
        "total": total,
        "latest_updated_at": latest,
        "orbit_types": [dict(row) for row in orbit_rows],
        "citation_categories": [dict(row) for row in citation_rows],
        "person_roles": [dict(row) for row in person_role_rows],
        "genders": [dict(row) for row in gender_rows],
        "discoverers": [dict(row) for row in discoverer_rows],
        "observatories": [dict(row) for row in observatory_rows],
        "flags": flag_rows,
    }


def refresh_dataset_stats(connection: sqlite3.Connection) -> dict[str, Any]:
    """Materialize the public initial-view payloads for the current dataset."""
    payload = stats(connection)
    initial_search = search(connection, sort="alpha", direction="asc", limit=50, offset=0)
    connection.execute(
        """
        INSERT INTO dataset_stats (cache_key, payload_json, initial_search_json, refreshed_at)
        VALUES ('base', ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(cache_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            initial_search_json = excluded.initial_search_json,
            refreshed_at = excluded.refreshed_at
        """,
        (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            json.dumps(initial_search, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    return payload


def dataset_stats_snapshot(connection: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the materialized public statistics, if this DB has one."""
    row = connection.execute(
        "SELECT payload_json FROM dataset_stats WHERE cache_key = 'base'"
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def dataset_initial_search_snapshot(connection: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the materialized all-object initial search page, if available."""
    row = connection.execute(
        "SELECT initial_search_json FROM dataset_stats WHERE cache_key = 'base'"
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["initial_search_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def wordcloud(
    connection: sqlite3.Connection,
    *,
    q: str | list[str] = "",
    q_mode: str = "and",
    q_target: str = "both",
    orbit: str | list[str] = "",
    citation_category: str | list[str] = "",
    person_role: str | list[str] = "",
    gender: str | list[str] = "",
    discoverer: str | list[str] = "",
    observatory: str | list[str] = "",
    flag: str | list[str] = "",
    max_words: int = 80,
) -> list[dict[str, Any]]:
    where, params, joins = _filters(
        q=q,
        q_mode=q_mode,
        q_target=q_target,
        orbit=orbit,
        citation_category=citation_category,
        person_role=person_role,
        gender=gender,
        discoverer=discoverer,
        observatory=observatory,
        flag=flag,
    )
    rows = connection.execute(
        f"""
        SELECT DISTINCT mp.name_ascii, mp.citation_text, mp.discovery_site, mp.discoverer_text
        FROM minor_planets mp {joins} {where}
        """,
        params,
    ).fetchall()
    counter: Counter[str] = Counter()
    for row in rows:
        text = row['citation_text'] or ''
        for word in WORD_RE.findall(text):
            normalized = word.strip("'-").lower()
            if len(normalized) < 3 or normalized in STOPWORDS:
                continue
            counter[normalized] += 1
    return [{"word": word, "count": count} for word, count in counter.most_common(max_words)]


def facets(
    connection: sqlite3.Connection,
    *,
    q: str | list[str] = "",
    q_mode: str = "and",
    q_target: str = "both",
    orbit: str | list[str] = "",
    citation_category: str | list[str] = "",
    person_role: str | list[str] = "",
    gender: str | list[str] = "",
    discoverer: str | list[str] = "",
    observatory: str | list[str] = "",
    flag: str | list[str] = "",
) -> dict[str, Any]:
    where, params, joins = _filters(
        q=q,
        q_mode=q_mode,
        q_target=q_target,
        orbit=orbit,
        citation_category=citation_category,
        person_role=person_role,
        gender=gender,
        discoverer=discoverer,
        observatory=observatory,
        flag=flag,
    )
    orbit_rows = connection.execute(
        f"""
        SELECT COALESCE(mp.orbit_type, 'Unclassified') AS value, COUNT(DISTINCT mp.permid) AS count
        FROM minor_planets mp {joins} {where}
        GROUP BY 1 ORDER BY count DESC, 1
        """,
        params,
    ).fetchall()
    citation_rows = connection.execute(
        f"""
        SELECT c2.value AS value, COUNT(DISTINCT mp.permid) AS count
        FROM minor_planets mp
        {joins}
        JOIN categories c2 ON c2.permid = mp.permid AND c2.kind = 'citation'
        {where}
        GROUP BY c2.value ORDER BY count DESC, 1
        """,
        params,
    ).fetchall()
    person_role_rows = _citation_facet_rows(connection, joins, where, params, "person_role")
    gender_rows = _citation_facet_rows(connection, joins, where, params, "entity_gender")
    discoverer_rows = _discovery_facet_rows(connection, joins, where, params, "discoverer")
    observatory_rows = _discovery_facet_rows(connection, joins, where, params, "observatory")
    neo_count = _facet_flag_count(connection, joins, where, params, "mp.is_neo = 1")
    pha_count = _facet_flag_count(connection, joins, where, params, "mp.is_pha = 1")
    return {
        "orbit_types": [dict(row) for row in orbit_rows],
        "citation_categories": [dict(row) for row in citation_rows],
        "person_roles": [dict(row) for row in person_role_rows],
        "genders": [dict(row) for row in gender_rows],
        "discoverers": [dict(row) for row in discoverer_rows],
        "observatories": [dict(row) for row in observatory_rows],
        "flags": [{"value": "NEO", "count": neo_count}, {"value": "PHA", "count": pha_count}],
    }


def _discovery_facet_rows(
    connection: sqlite3.Connection,
    joins: str,
    where: str,
    params: list[Any],
    kind: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        f"""
        SELECT df2.value AS value, COUNT(DISTINCT mp.permid) AS count
        FROM minor_planets mp
        {joins}
        JOIN discovery_facets df2 ON df2.permid = mp.permid AND df2.kind = ?
        {where}
        GROUP BY df2.value ORDER BY count DESC, 1
        LIMIT 80
        """,
        [kind, *params],
    ).fetchall()


def _citation_facet_rows(
    connection: sqlite3.Connection,
    joins: str,
    where: str,
    params: list[Any],
    kind: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        f"""
        SELECT cf2.value AS value, COUNT(DISTINCT mp.permid) AS count
        FROM minor_planets mp
        {joins}
        JOIN citation_facets cf2 ON cf2.permid = mp.permid AND cf2.kind = ?
        {where}
        GROUP BY cf2.value ORDER BY count DESC, 1
        """,
        [kind, *params],
    ).fetchall()


def _facet_flag_count(
    connection: sqlite3.Connection,
    joins: str,
    where: str,
    params: list[Any],
    flag_clause: str,
) -> int:
    flag_where = f"{where} AND {flag_clause}" if where else f"WHERE {flag_clause}"
    row = connection.execute(
        f"SELECT COUNT(DISTINCT mp.permid) AS count FROM minor_planets mp {joins} {flag_where}",
        params,
    ).fetchone()
    return int(row["count"])


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = decode_latex(text)
    return re.sub(r"\s+", " ", text).strip()


def _categories_for(
    citation_text: str | None,
    orbit: OrbitRecord | None,
    *,
    citation_categories: list[Category] | None = None,
) -> list[Category]:
    categories = list(citation_categories) if citation_categories is not None else categorize_citation(citation_text)
    if orbit and orbit.orbit_type:
        categories.append(Category("orbit", orbit.orbit_type, "mpcorb", 1.0))
    if orbit and orbit.is_neo:
        categories.append(Category("flag", "NEO", "mpcorb", 1.0))
    if orbit and orbit.is_pha:
        categories.append(Category("flag", "PHA", "mpcorb", 1.0))
    return categories


def _filters(
    *,
    q: str | list[str] = "",
    q_mode: str = "and",
    q_target: str = "both",
    orbit: str | list[str] = "",
    citation_category: str | list[str] = "",
    person_role: str | list[str] = "",
    gender: str | list[str] = "",
    discoverer: str | list[str] = "",
    observatory: str | list[str] = "",
    flag: str | list[str] = "",
) -> tuple[str, list[Any], str]:
    clauses: list[str] = []
    params: list[Any] = []
    joins: list[str] = []
    normalized_q_target = _normalize_q_target(q_target)

    include_terms, exclude_terms = _split_query_terms(q)
    if include_terms:
        query_clauses: list[str] = []
        for query in include_terms:
            query_clause, query_params = _query_clause(query, q_target=normalized_q_target)
            query_clauses.append(query_clause)
            params.extend(query_params)
        joiner = " OR " if _normalize_q_mode(q_mode) == "or" else " AND "
        clauses.append("(" + joiner.join(query_clauses) + ")")
    for query in exclude_terms:
        query_clause, query_params = _query_clause(query, q_target=normalized_q_target)
        clauses.append(f"NOT {query_clause}")
        params.extend(query_params)

    orbit_values = _normalize_filter_values(orbit)
    if orbit_values:
        orbit_clauses: list[str] = []
        concrete_orbits = [value for value in orbit_values if value != "Unclassified"]
        if "Unclassified" in orbit_values:
            orbit_clauses.append("mp.orbit_type IS NULL")
        if concrete_orbits:
            orbit_clauses.append(f"mp.orbit_type IN ({_placeholders(concrete_orbits)})")
            params.extend(concrete_orbits)
        clauses.append("(" + " OR ".join(orbit_clauses) + ")")

    citation_values = _normalize_filter_values(citation_category)
    if citation_values:
        joins.append("JOIN categories c_filter ON c_filter.permid = mp.permid")
        clauses.append(f"c_filter.kind = 'citation' AND c_filter.value IN ({_placeholders(citation_values)})")
        params.extend(citation_values)

    person_role_values = _normalize_filter_values(person_role)
    if person_role_values:
        joins.append("JOIN citation_facets cf_role_filter ON cf_role_filter.permid = mp.permid")
        clauses.append(
            "cf_role_filter.kind = 'person_role' "
            f"AND cf_role_filter.value IN ({_placeholders(person_role_values)})"
        )
        params.extend(person_role_values)

    gender_values = _normalize_filter_values(gender)
    if gender_values:
        joins.append("JOIN citation_facets cf_gender_filter ON cf_gender_filter.permid = mp.permid")
        clauses.append(
            "cf_gender_filter.kind = 'entity_gender' "
            f"AND cf_gender_filter.value IN ({_placeholders(gender_values)})"
        )
        params.extend(gender_values)

    discoverer_values = _normalize_filter_values(discoverer, split_commas=False)
    if discoverer_values:
        joins.append("JOIN discovery_facets df_discoverer_filter ON df_discoverer_filter.permid = mp.permid")
        clauses.append(
            "df_discoverer_filter.kind = 'discoverer' "
            f"AND df_discoverer_filter.value IN ({_placeholders(discoverer_values)})"
        )
        params.extend(discoverer_values)

    observatory_values = _normalize_filter_values(observatory, split_commas=False)
    if observatory_values:
        joins.append("JOIN discovery_facets df_observatory_filter ON df_observatory_filter.permid = mp.permid")
        clauses.append(
            "df_observatory_filter.kind = 'observatory' "
            f"AND df_observatory_filter.value IN ({_placeholders(observatory_values)})"
        )
        params.extend(observatory_values)

    flag_values = _normalize_filter_values(flag)
    if flag_values:
        flag_clauses: list[str] = []
        if "NEO" in flag_values:
            flag_clauses.append("mp.is_neo = 1")
        if "PHA" in flag_values:
            flag_clauses.append("mp.is_pha = 1")
        if flag_clauses:
            clauses.append("(" + " OR ".join(flag_clauses) + ")")

    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params, " ".join(joins)


def _query_clause(query: str, *, q_target: str = "both") -> tuple[str, list[Any]]:
    like_query = f"%{_escape_like(query)}%"

    # Trigram FTS supports substring search for three or more characters. Keep
    # the candidate set in the FTS index, then look up only matching rowids in
    # minor_planets. Combining LIKE with FTS via OR made SQLite scan every
    # minor_planets row, which is particularly costly for multi-term searches.
    if not _use_short_text_search(query):
        return (
            "(mp.rowid IN ("
            "SELECT rowid FROM minor_planets_fts WHERE minor_planets_fts MATCH ?"
            "))",
            [_fts_query_for_target(query, q_target)],
        )

    if q_target == "citation":
        return (
            "(COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE)",
            [like_query],
        )

    if q_target == "name":
        return (
            "("
            "mp.permid LIKE ? ESCAPE '\\' OR "
            "COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
            "COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
            "mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
            "mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE"
            ")",
            [like_query] * 5,
        )

    return (
        "("
        "mp.permid LIKE ? ESCAPE '\\' OR "
        "COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
        "COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
        "mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
        "mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
        "COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
        "COALESCE(mp.discovery_site, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR "
        "COALESCE(mp.discoverer_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE"
        ")",
        [like_query] * 8,
    )


def _normalize_query_terms(q: str | list[str]) -> list[str]:
    raw_values = q if isinstance(q, list) else [q]
    terms: list[str] = []
    for raw in raw_values:
        term = re.sub(r"\s+", " ", str(raw)).strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _split_query_terms(q: str | list[str]) -> tuple[list[str], list[str]]:
    include_terms: list[str] = []
    exclude_terms: list[str] = []
    for term in _normalize_query_terms(q):
        if term.startswith("!"):
            negated = term[1:].strip()
            if negated and negated not in exclude_terms:
                exclude_terms.append(negated)
            continue
        include_terms.append(term)
    return include_terms, exclude_terms


def _normalize_q_mode(q_mode: str) -> str:
    return "or" if q_mode.lower() == "or" else "and"


def _normalize_q_target(q_target: str) -> str:
    normalized = q_target.lower()
    return normalized if normalized in QUERY_TARGETS else "both"


def _representative_query(q: str | list[str]) -> str:
    include_terms, _exclude_terms = _split_query_terms(q)
    return include_terms[0] if include_terms else ""


def _fts_query(q: str) -> str:
    cleaned = re.sub(r"\s+", " ", q.replace('"', " ")).strip()
    return f'"{cleaned}"'


def _fts_query_for_target(q: str, q_target: str) -> str:
    base = _fts_query(q)
    normalized_q_target = _normalize_q_target(q_target)
    if normalized_q_target == "name":
        return " OR ".join(
            [
                f"permid:{base}",
                f"packed_permid:{base}",
                f"iau_designation:{base}",
                f"name_ascii:{base}",
                f"name_display:{base}",
            ]
        )
    if normalized_q_target == "citation":
        return f"citation_text:{base}"
    return base


def _use_short_text_search(q: str) -> bool:
    return len(q.strip()) < 3


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_filter_values(value: str | list[str], *, split_commas: bool = True) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for raw in raw_values:
        parts = str(raw).split(",") if split_commas else [str(raw)]
        for part in parts:
            cleaned = part.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
    return normalized


def _placeholders(values: list[str]) -> str:
    return ", ".join("?" for _ in values)


def _search_order_by(sort: str, direction: str, *, q: str = "") -> tuple[str, list[Any]]:
    sort_key = sort if sort in SEARCH_SORTS else "number"
    direction_key = "DESC" if direction.lower() == "desc" else "ASC"
    expression = SEARCH_SORTS[sort_key]
    clauses: list[str] = []
    params: list[Any] = []
    query = q.strip()
    if query:
        permid_query = _normalize_permid_query(query)
        permid_prefix_query = f"{_escape_like(permid_query)}%"
        permid_contains_query = f"%{_escape_like(permid_query)}%"
        text_prefix_query = f"{_escape_like(query)}%"
        text_contains_query = f"%{_escape_like(query)}%"
        clauses.append(
            """
            CASE
                WHEN mp.permid = ? THEN 0
                WHEN mp.name_ascii = ? COLLATE NOCASE
                  OR mp.name_display = ? COLLATE NOCASE THEN 1
                WHEN mp.permid LIKE ? ESCAPE '\\'
                  OR COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 2
                WHEN mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 3
                WHEN mp.permid LIKE ? ESCAPE '\\'
                  OR COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 4
                WHEN mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE
                  OR mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 5
                WHEN COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 6
                ELSE 7
            END ASC
            """
        )
        params.extend(
            [
                permid_query,
                query,
                query,
                permid_prefix_query,
                text_prefix_query,
                text_prefix_query,
                text_prefix_query,
                text_prefix_query,
                permid_contains_query,
                text_contains_query,
                text_contains_query,
                text_contains_query,
                text_contains_query,
                text_contains_query,
            ]
        )
    if sort_key in NUMERIC_NULL_LAST_SORTS:
        clauses.append(f"{expression} IS NULL ASC")
    clauses.append(f"{expression} {direction_key}")
    if sort_key != "number":
        clauses.append("CAST(mp.permid AS INTEGER) ASC")
    return "ORDER BY " + ", ".join(clauses), params


def _normalize_permid_query(q: str) -> str:
    cleaned = q.strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        inner = cleaned[1:-1].strip()
        if inner.isdigit():
            return inner
    return cleaned


# Maximum characters shown as a snippet when there is no search query.
# Citations shorter than this threshold are shown in full (UX-friendly).
_SNIPPET_HARD_MAX = 80
# Context window (chars) around the matched keyword in query-driven snippets.
_SNIPPET_CONTEXT = 90


def _make_citation_snippet(citation: str, q: str) -> str:
    """Return a short excerpt of *citation* suitable for display.

    * If *q* is non-empty, locate the first occurrence of *q* (case-insensitive)
      in the text and return up to ``_SNIPPET_CONTEXT`` characters on each side,
      surrounded by ellipses where text was omitted.  The matched region is
      wrapped in a ``\x00`` … ``\x01`` sentinel pair so the frontend can
      highlight it without needing an additional regex pass.
    * If *q* is empty (or not found), return the leading ``_SNIPPET_HARD_MAX``
      characters.  Citations shorter than that threshold are shown in full.
    """
    if not citation:
        return ""

    if q:
        lower_text = citation.lower()
        lower_q = q.lower()
        pos = lower_text.find(lower_q)
        if pos != -1:
            start = max(0, pos - _SNIPPET_CONTEXT)
            end   = min(len(citation), pos + len(q) + _SNIPPET_CONTEXT)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(citation) else ""
            # Wrap the actual match with sentinels (\x00…\x01) so JS can highlight it.
            snippet = (
                prefix
                + citation[start:pos]
                + "\x00"
                + citation[pos : pos + len(q)]
                + "\x01"
                + citation[pos + len(q) : end]
                + suffix
            )
            return snippet
        # Query not found in citation – fall through to leading-text strategy.

    # No query (or query not found): leading text up to _SNIPPET_HARD_MAX chars.
    # Short citations (≤ hard max) are displayed in full; longer ones are cut.
    return citation[:_SNIPPET_HARD_MAX] + ("..." if len(citation) > _SNIPPET_HARD_MAX else "")


def _row_to_search_item(row: sqlite3.Row, q: str | list[str] = "") -> dict[str, Any]:
    data = dict(row)
    data["is_neo"] = bool(data["is_neo"])
    data["is_pha"] = bool(data["is_pha"])
    data["citation_categories"] = []
    data["person_roles"] = []
    data["gender"] = None
    citation = data.get("citation_text") or ""
    data["citation_snippet"] = _make_citation_snippet(citation, _representative_query(q))
    data.pop("citation_text", None)
    return data


def _attach_citation_categories(connection: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    permids = [item["permid"] for item in items]
    rows = connection.execute(
        f"""
        SELECT permid, value
        FROM categories
        WHERE kind = 'citation'
          AND permid IN ({_placeholders(permids)})
        ORDER BY value
        """,
        permids,
    ).fetchall()
    by_permid = {permid: [] for permid in permids}
    for row in rows:
        by_permid.setdefault(row["permid"], []).append(row["value"])
    for item in items:
        item["citation_categories"] = by_permid.get(item["permid"], [])


def _attach_citation_facets(connection: sqlite3.Connection, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    permids = [item["permid"] for item in items]
    rows = connection.execute(
        f"""
        SELECT permid, kind, value
        FROM citation_facets
        WHERE permid IN ({_placeholders(permids)})
        ORDER BY kind, value
        """,
        permids,
    ).fetchall()
    roles = {permid: [] for permid in permids}
    genders: dict[str, str] = {}
    for row in rows:
        if row["kind"] == "person_role":
            roles.setdefault(row["permid"], []).append(row["value"])
        elif row["kind"] == "entity_gender":
            genders[row["permid"]] = row["value"]
    for item in items:
        item["person_roles"] = roles.get(item["permid"], [])
        item["gender"] = genders.get(item["permid"])
