"""Turn the cached notes into data/extracted/<system>/<key>.json and log what changed.

A note can document several releases (17.12.1a to 17.12.8), and a release can be
documented by several notes, one per product series: the change log is kept per
release, across the notes of its system.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .collect import cached_pages, load_manifest
from .parser import Document, parse_document
from .versions import version_key

log = logging.getLogger(__name__)


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_document(path: Path, key: str, entry: dict, document: Document) -> None:
    """One observation per line, so that a revised note gives a readable git diff."""
    head = {
        "key": key,
        "system": entry["system"],
        "url": entry["url"],
        "families": entry["families"],
        "title": document.title,
        "revised": entry.get("revised"),
        "versions": document.versions,
        "released": document.released,
        "pages": document.pages,
        "notices": document.notices,
        "skipped": document.skipped,
        "left_out": document.left_out,
    }
    lines = ",\n".join("  " + json.dumps(o, ensure_ascii=False) for o in document.observations)
    body = json.dumps(head, ensure_ascii=False)[:-1]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{body}, "observations": [\n{lines}\n]}}\n', encoding="utf-8")


def load_documents(directory: Path) -> Dict[str, dict]:
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*/*.json")}


def release_facts(documents: Dict[str, dict]) -> Dict[Tuple[str, str], Tuple[Set[str], Set[str]]]:
    """(system, release): the fixed and the open bugs, across all the notes."""
    facts: Dict[Tuple[str, str], Tuple[Set[str], Set[str]]] = {}
    for document in documents.values():
        for version in document["versions"]:
            facts.setdefault((document["system"], version), (set(), set()))
        for o in document["observations"]:
            fixed, known = facts.setdefault((document["system"], o["version"]), (set(), set()))
            (fixed if o["status"] == "resolved" else known).add(o["bug_id"])
    return facts


def release_dates(documents: Dict[str, dict]) -> Dict[Tuple[str, str], str]:
    dates: Dict[Tuple[str, str], str] = {}
    for document in documents.values():
        for version, date in document["released"].items():
            key = (document["system"], version)
            if key not in dates or date < dates[key]:
                dates[key] = date
    return dates


def diff_releases(before: Dict[str, dict], after: Dict[str, dict], date: str, baseline: bool) -> List[dict]:
    """New releases, and the bugs added to the releases already known.

    Without a change log the data is a baseline: the releases are recorded with
    their release date when the notes give it, as nothing tells which bugs were added when.
    """
    old = release_facts(before)
    new = release_facts(after)
    dates = release_dates(after)
    entries = []
    for (system, version), (fixed, known) in new.items():
        if baseline or (system, version) not in old:
            released = dates.get((system, version)) or (None if baseline else date)
            if released:
                entries.append({"date": released, "system": system, "version": version, "kind": "version", "bugs": []})
            continue
        old_fixed, old_known = old[(system, version)]
        for kind, added in (("known_added", known - old_known), ("fixed_added", fixed - old_fixed)):
            if added:
                entries.append({"date": date, "system": system, "version": version, "kind": kind, "bugs": sorted(added)})
    return entries


def change_key(change: dict):
    return change["date"], change["system"], version_key(change["system"], change["version"]), change["kind"]


def read_changes(path: Path) -> List[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def write_changes(path: Path, changes: List[dict]) -> None:
    lines = ",\n".join("  " + json.dumps(change, ensure_ascii=False) for change in sorted(changes, key=change_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")


def extract_all(manifest_path: Path, cache: Path, output: Path, changes_path: Path,
                date: Optional[str] = None) -> Dict[str, List[str]]:
    """Parse every cached note; return the problems that must stop the update.

    Any warning stops it: a table the parser cannot place, a note that no longer
    parses, or that lost all the bugs it had. The layouts the site leaves out on
    purpose are listed in the "left_out" field of their note instead.
    """
    date = date or today()
    manifest = load_manifest(manifest_path)
    before = load_documents(output)
    baseline = not changes_path.exists()
    problems: Dict[str, List[str]] = {}
    written = {}
    for key, entry in sorted(manifest.items()):
        folder = cache / key
        if not (folder / "pages.json").exists():
            continue
        try:
            document = parse_document(cached_pages(folder), entry["system"])
        except Exception as error:  # A note that breaks the parser must not pass silently.
            problems[key] = [f"cannot parse: {error!r}"]
            continue
        previous = before.get(key)
        if previous and previous["observations"] and not document.observations:
            problems[key] = ["the note had bugs and has none now"]
            continue
        target = output / entry["system"] / f"{key}.json"
        write_document(target, key, entry, document)
        written[key] = json.loads(target.read_text(encoding="utf-8"))
        if document.warnings:
            problems[key] = document.warnings
        log.info("%s: %d observations, %d security entries left out", key, len(document.observations), document.skipped)
    if problems:
        return problems
    after = {**before, **written}
    changes = read_changes(changes_path) + diff_releases(before, after, date, baseline)
    write_changes(changes_path, changes)
    return problems
