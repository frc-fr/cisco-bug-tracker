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
from . import report
from .parser import Document, parse_document
from .versions import SYSTEMS, version_key

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


def extract_all(manifest_path: Path, cache: Path, output: Path, changes_path: Path, report_path: Path,
                date: Optional[str] = None) -> List[str]:
    """Parse every cached note, write what is read and the processing report; return why the update stops.

    A note is published for what the code reads of it; what it does not read is in the
    report. A note that no longer parses, or loses most of its bugs, keeps its last
    reading. The update stops only when too few notes are read (report.PUBLISH_MINIMUM):
    the site then keeps its last version rather than an empty one.
    """
    date = date or today()
    manifest = load_manifest(manifest_path)
    before = load_documents(output)
    previous = {d["key"]: d for d in report.load(report_path).get("documents", [])}
    baseline = not changes_path.exists()
    written = {}
    entries: List[dict] = []
    groups: Dict[str, dict] = {}
    headings: Dict[str, Dict[str, bool]] = {}
    urls: Dict[str, str] = {}
    prose: List[dict] = []
    total = 0
    for key, entry in sorted(manifest.items()):
        folder = cache / key
        old = before.get(key)
        if not (folder / "pages.json").exists() and not entry.get("unavailable"):
            continue
        total += 1
        url, group = entry["url"], SYSTEMS[entry["system"]]
        findings: List[dict] = []
        document = None
        if (folder / "pages.json").exists():
            try:
                document = parse_document(cached_pages(folder), entry["system"])
            except Exception as error:  # A note that breaks the parser must not pass silently.
                findings.append(report.finding("not_understood", "parse_error", url, "", [], f"the parser stops: {error!r}"))
        if entry.get("unavailable") == "withdrawn":
            findings.append(report.finding("left_out", "withdrawn", url, "", [],
                                           "Cisco withdrew the note: its address leads to a support landing page"))
        elif entry.get("unavailable"):
            findings.append(report.finding("unreachable", "http", url, "", [],
                                           "the note no longer answers: its last reading stays"))
        ids = {"vendor": set(), "read": set(), "ruled": set(), "failed": set(), "unaccounted": set()}
        if document:
            findings += document.findings
            ids = document.accounting()
            places: Dict[Tuple[str, str], List[str]] = {}
            for bug in sorted(ids["unaccounted"]):
                places.setdefault(document.listed[bug], []).append(bug)
            for (page, where), bugs in places.items():
                findings.append(report.finding("suspect", "unaccounted", page, where, bugs,
                                               "bug IDs the note lists that no rule of the code accounts for"))
            count = len(ids["read"])
            had = len({o["bug_id"] for o in old["observations"]}) if old else 0
            if had and not count:
                findings.append(report.finding("suspect", "lost_bugs", url, "", [], f"the note had {had} bugs and has none now"))
            elif had and count < (1 - report.DROP_LIMIT) * had:
                findings.append(report.finding("suspect", "drop", url, "", [], f"{count} bugs read, {had} before"))
            headings[key] = document.headings
            if document.prose:
                prose.append({"key": key, "title": document.title, "page": url, "count": len(document.prose),
                              "ids": sorted(document.prose)[:report.EXAMPLES]})
        urls[key] = url
        keep = document is None or any(f["rule"] in ("lost_bugs", "drop") for f in findings)
        if document and not keep:
            target = output / entry["system"] / f"{key}.json"
            write_document(target, key, entry, document)
            written[key] = json.loads(target.read_text(encoding="utf-8"))
            log.info("%s: %d observations, %d security entries left out", key, len(document.observations), document.skipped)
        totals = groups.setdefault(group, {"name": group, "documents": 0, "vendor": 0, "read": 0, "ruled": 0, "failed": 0, "unaccounted": 0})
        totals["documents"] += 1
        for bucket in ("vendor", "read", "ruled", "failed", "unaccounted"):
            totals[bucket] += len(ids[bucket])
        if report.status_of(findings) != "read":
            kept = (old.get("revised") or "—") if keep and old else None
            # An unreachable note may have cached a landing page: its last reading names it better.
            title = (old or {}).get("title") if old and (entry.get("unavailable") or not document) else None
            title = title or (document.title if document else url)
            if entry.get("unavailable") == "withdrawn":
                # What the address now shows is a landing page: the file name names the note better.
                title = url.rsplit("/", 1)[-1]
            entries.append(report.document(key, group, title, url, findings, ids, previous.get(key), kept))
    for found in entries:
        if found["status"] in report.TO_FIX:
            log.warning("%s: %s %s", found["key"], found["status"], ", ".join(sorted({f["rule"] for f in found["findings"]})))
    order = list(SYSTEMS.values())
    summary = report.build(report_path, entries, total, sorted(groups.values(), key=lambda g: order.index(g["name"])),
                           report.unused_sections(headings, urls), prose)
    publication = summary["publication"]
    if not publication["published"]:
        return [f"only {publication['read_share']:.0%} of the notes read, under {publication['minimum']:.0%}: the site keeps its last version"]
    after = {**before, **written}
    changes = read_changes(changes_path) + diff_releases(before, after, date, baseline)
    write_changes(changes_path, changes)
    return []
