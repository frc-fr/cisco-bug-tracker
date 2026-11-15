"""Command line entry point."""
import argparse
import logging
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="ciscobugs")
    parser.add_argument("--catalog", type=Path, default=Path("sources/catalog.json"))
    parser.add_argument("--manifest", type=Path, default=Path("sources/manifest.json"))
    parser.add_argument("--lifecycle", type=Path, default=Path("sources/lifecycle.json"))
    parser.add_argument("--hardware", type=Path, default=Path("sources/hardware.json"))
    parser.add_argument("--schedule", type=Path, default=Path("sources/schedule.yml"))
    parser.add_argument("--cache", type=Path, default=Path(".cache/html"))
    parser.add_argument("--output", type=Path, default=Path("data/extracted"))
    parser.add_argument("--changes", type=Path, default=Path("data/changes.json"))
    parser.add_argument("--report", type=Path, default=Path("data/report.json"))
    parser.add_argument("--site", type=Path, default=Path("site"))
    parser.add_argument("--base-url", default="https://frc-fr.github.io/cisco-bug-tracker/")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect", help="update the manifest and download new or revised notes")
    commands.add_parser("extract", help="parse the cached notes; fails on any warning")
    commands.add_parser("build", help="generate the static site from the extracted data")
    commands.add_parser("check", help="fail when the processing report lists something to fix")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "collect":
        from . import collect, hardware, lifecycle, report
        client = collect.Client()
        with report.source(args.report, "lifecycle"):
            lifecycle.update_cisco(args.lifecycle, client)
        with report.source(args.report, "hardware"):
            hardware.update_hardware(args.hardware, client)
        with report.source(args.report, "notes"):
            downloaded = collect.update(args.manifest, args.catalog, args.cache, client)
        logging.info("%d notes downloaded", len(downloaded))
    elif args.command == "extract":
        from . import extract
        stops = extract.extract_all(args.manifest, args.cache, args.output, args.changes, args.report)
        for reason in stops:
            logging.error("%s", reason)
        sys.exit(1 if stops else 0)
    elif args.command == "check":
        from . import report
        left = report.check(report.load(args.report))
        for line in left:
            print(line)
        sys.exit(1 if left else 0)
    elif args.command == "build":
        from . import build
        summary = build.build_site(args.output, args.manifest, args.changes, args.schedule, args.site, args.dist, args.base_url,
                                   args.lifecycle, args.hardware, args.report)
        for system, counts in summary.items():
            logging.info("%s: %s", system, counts)
