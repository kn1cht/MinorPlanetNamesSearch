"""Command line entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import db
from .ingest import INGEST_MODES, enrich_discovery_existing, ingest, init_sample, reclassify_existing
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

    discovery_parser = subparsers.add_parser(
        "enrich-discovery",
        help="Fill discovery date/site/discoverer fields from cached NumberedMPs.txt",
    )
    discovery_parser.add_argument("--db", default=str(db.DEFAULT_DB))
    discovery_parser.add_argument("--limit", type=int, default=None)
    discovery_parser.add_argument("--refresh-cache", action="store_true", help="Download NumberedMPs.txt again")
    discovery_parser.add_argument("--quiet", action="store_true", help="Hide progress output")

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
            f"{result['orbit_records']} orbit records."
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
        print(f"Reclassified {result['records']} records{filter_text} using {result['classifier']}.")
        return 0

    if args.command == "enrich-discovery":
        result = enrich_discovery_existing(
            Path(args.db),
            limit=args.limit,
            refresh_cache=args.refresh_cache,
            progress=ProgressReporter(enabled=not args.quiet),
        )
        print(
            f"Discovery enrich: scanned {result['records']} records; "
            f"updated {result['updated']}, unchanged {result['unchanged']}, missing {result['missing']}."
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
