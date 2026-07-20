"""Command line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import db
from .ingest import (
    INGEST_MODES,
    backfill_wgsbn_only,
    classify_person_facets_existing,
    ingest,
    init_sample,
    reclassify_existing,
)
from .ollama import is_ollama_available
from .progress import ProgressReporter
from .server import serve
from .settings import (
    IDENTIFIER_BATCH_SIZE,
    IDENTIFIER_INTER_REQUEST_DELAY_SECONDS,
    IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS,
    IDENTIFIER_LONG_PAUSE_SECONDS,
    OLLAMA_HOST,
    ORBIT_INTER_REQUEST_DELAY_SECONDS,
    ORBIT_LONG_PAUSE_EVERY_REQUESTS,
    ORBIT_LONG_PAUSE_SECONDS,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mpnames")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample_parser = subparsers.add_parser("init-sample", help="Load fixture data into the local database")
    sample_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    sample_parser.add_argument("--fixtures", default="tests/fixtures")
    sample_parser.add_argument("--classifier", choices=["rules", "auto", "ollama"], default="rules")
    sample_parser.add_argument("--ollama-model", default=None)
    sample_parser.add_argument("--ollama-host", default=OLLAMA_HOST)

    ingest_parser = subparsers.add_parser("ingest", help="Fetch MPC data and update the local database")
    ingest_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    ingest_parser.add_argument("--limit", type=int, default=None)
    ingest_parser.add_argument("--mode", choices=sorted(INGEST_MODES), default="add")
    ingest_parser.add_argument("--delay", type=float, default=IDENTIFIER_INTER_REQUEST_DELAY_SECONDS)
    ingest_parser.add_argument("--batch-size", type=int, default=IDENTIFIER_BATCH_SIZE)
    ingest_parser.add_argument("--pause-every", type=int, default=IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS)
    ingest_parser.add_argument("--pause-seconds", type=float, default=IDENTIFIER_LONG_PAUSE_SECONDS)
    ingest_parser.add_argument("--orbit-delay", type=float, default=ORBIT_INTER_REQUEST_DELAY_SECONDS)
    ingest_parser.add_argument("--orbit-pause-every", type=int, default=ORBIT_LONG_PAUSE_EVERY_REQUESTS)
    ingest_parser.add_argument("--orbit-pause-seconds", type=float, default=ORBIT_LONG_PAUSE_SECONDS)
    ingest_parser.add_argument("--classifier", choices=["rules", "auto", "ollama"], default="rules")
    ingest_parser.add_argument("--ollama-model", default=None)
    ingest_parser.add_argument("--ollama-host", default=OLLAMA_HOST)
    ingest_parser.add_argument("--quiet", action="store_true", help="Hide progress output")

    reclassify_parser = subparsers.add_parser("reclassify", help="Reclassify existing citation categories")
    reclassify_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    reclassify_parser.add_argument("--classifier", choices=["rules", "auto", "ollama"], default="ollama")
    reclassify_parser.add_argument("--ollama-model", default=None)
    reclassify_parser.add_argument("--ollama-host", default=OLLAMA_HOST)
    reclassify_parser.add_argument("--limit", type=int, default=None)
    reclassify_parser.add_argument("--timeout", type=float, default=60.0, help="Ollama request timeout in seconds (default: 60)")
    reclassify_parser.add_argument(
        "--think", action="store_true", default=False,
        help="Enable native thinking/reasoning mode for Qwen3.5 etc. (slower but may improve accuracy)",
    )
    reclassify_parser.add_argument(
        "--think-on-review", action=argparse.BooleanOptionalAction, default=True,
        help="Enable thinking only for retry attempts if the first attempt is uncertain (default: True)",
    )
    reclassify_parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Only reclassify objects currently having this citation category; repeat or use commas",
    )
    reclassify_parser.add_argument("--quiet", action="store_true", help="Hide progress output")

    person_facets_parser = subparsers.add_parser(
        "classify-person-facets",
        help="Classify evidence-backed person roles and entity gender from citations",
    )
    person_facets_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    person_facets_parser.add_argument("--classifier", choices=["rules", "auto", "ollama"], default="rules")
    person_facets_parser.add_argument("--ollama-model", default=None)
    person_facets_parser.add_argument("--ollama-host", default=OLLAMA_HOST)
    person_facets_parser.add_argument("--limit", type=int, default=None)
    person_facets_parser.add_argument("--timeout", type=float, default=60.0)
    person_facets_parser.add_argument("--think", action="store_true", default=False)
    person_facets_parser.add_argument("--quiet", action="store_true", help="Hide progress output")

    wgsbn_only_parser = subparsers.add_parser(
        "backfill-wgsbn-only",
        help="Add explicitly selected WGSBN names that remain absent from MPC name data",
    )
    wgsbn_only_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    wgsbn_only_parser.add_argument("--permid", action="append", required=True, help="Permanent number; repeat as needed")
    wgsbn_only_parser.add_argument("--classifier", choices=["rules", "auto", "ollama"], default="ollama")
    wgsbn_only_parser.add_argument("--ollama-model", default=None)
    wgsbn_only_parser.add_argument("--ollama-host", default=OLLAMA_HOST)
    wgsbn_only_parser.add_argument("--timeout", type=float, default=60.0)
    wgsbn_only_parser.add_argument("--think", action="store_true", default=False)
    wgsbn_only_parser.add_argument("--quiet", action="store_true", help="Hide progress output")

    serve_parser = subparsers.add_parser("serve", help="Run the local Web UI and API")
    serve_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    serve_parser.add_argument("--web", default="web")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    subparsers.add_parser("ollama-status", help="Check optional ollama HTTP API availability")

    args = parser.parse_args(argv)

    if args.command == "init-sample":
        result = init_sample(
            Path(args.db),
            Path(args.fixtures),
            classifier_mode=args.classifier,
            ollama_model=args.ollama_model,
            ollama_host=args.ollama_host,
        )
        print(f"Loaded {result['records']} fixture records into {args.db}")
        return 0

    if args.command == "ingest":
        result = ingest(
            Path(args.db),
            limit=args.limit,
            mode=args.mode,
            delay=args.delay,
            batch_size=args.batch_size,
            pause_every=args.pause_every,
            pause_seconds=args.pause_seconds,
            orbit_delay=args.orbit_delay,
            orbit_pause_every=args.orbit_pause_every,
            orbit_pause_seconds=args.orbit_pause_seconds,
            classifier_mode=args.classifier,
            ollama_model=args.ollama_model,
            ollama_host=args.ollama_host,
            progress=ProgressReporter(enabled=not args.quiet),
        )
        print(
            f"Ingest mode={result['mode']}: selected {result['selected_records']} "
            f"of {result['listed_records']} listed names; "
            f"inserted {result['inserted']}, updated {result['updated']}, "
            f"unchanged {result['unchanged']}; "
            f"{result['identifier_records']} identifier records, "
            f"{result['orbit_records']} orbit records; "
            f"WGSBN {result['naming_metadata_updated']} metadata updates "
            f"({result['wgsbn_bulletins_fetched']} Bulletins / "
            f"{result['wgsbn_namings_fetched']} namings fetched)."
        )
        return 0

    if args.command == "reclassify":
        result = reclassify_existing(
            Path(args.db),
            classifier_mode=args.classifier,
            ollama_model=args.ollama_model,
            ollama_host=args.ollama_host,
            ollama_timeout=args.timeout,
            ollama_think=args.think,
            ollama_think_on_review=args.think_on_review,
            limit=args.limit,
            categories=args.category,
            progress=ProgressReporter(enabled=not args.quiet),
        )
        filter_text = (
            f" in categories {', '.join(result['category_filter'])}"
            if result.get("category_filter")
            else ""
        )
        print(
            f"Reclassified {result['records']} records{filter_text} using {result['classifier']}; "
            f"job={result['job_id']}."
        )
        return 0

    if args.command == "classify-person-facets":
        result = classify_person_facets_existing(
            Path(args.db),
            classifier_mode=args.classifier,
            ollama_model=args.ollama_model,
            ollama_host=args.ollama_host,
            ollama_timeout=args.timeout,
            ollama_think=args.think,
            limit=args.limit,
            progress=ProgressReporter(enabled=not args.quiet),
        )
        print(
            f"Person facets: {result['updated']} updated, {result['unchanged']} unchanged "
            f"of {result['records']} records; classifier={result['classifier']}; job={result['job_id']}."
        )
        return 0

    if args.command == "backfill-wgsbn-only":
        result = backfill_wgsbn_only(
            Path(args.db),
            permids=args.permid,
            classifier_mode=args.classifier,
            ollama_model=args.ollama_model,
            ollama_host=args.ollama_host,
            ollama_timeout=args.timeout,
            ollama_think=args.think,
            progress=ProgressReporter(enabled=not args.quiet),
        )
        print(
            f"WGSBN-only backfill: inserted {result['inserted']}, updated {result['updated']}, unchanged {result['unchanged']}, "
            f"missing {result['missing']} of {result['records']} requested; "
            f"classifier={result['classifier']}."
        )
        return 0

    if args.command == "serve":
        serve(Path(args.db), Path(args.web), host=args.host, port=args.port)
        return 0

    if args.command == "ollama-status":
        print("available" if is_ollama_available() else "unavailable")
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
