"""Generate the static site: copy site/ and cross the extracted data into dist/data/<system>/."""
import json
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .collect import load_manifest, pdf_of
from .extract import load_documents, read_changes
from .feed import build_feed, latest_changes
from .lifecycle import load_lifecycle
from .normalize import families_in, family_of_model, model_sort_key, models_in
from .versions import SYSTEMS, branch_key, is_rebuild, parts, train_of, version_key

log = logging.getLogger(__name__)

STATUS_CODES = {"resolved": "r", "open": "k", "limitation": "l"}
ACTIVE_DAYS = 365


def read_schedule(path: Path) -> Optional[dict]:
    """The crons of the automatic update, read in sources/schedule.yml so the site cannot contradict it."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    crons = re.findall(r'cron:\s*"([^"]+)"', text)
    timezone_name = re.search(r'timezone:\s*"([^"]+)"', text)
    if not crons:
        return None
    return {"crons": crons, "timezone": timezone_name.group(1) if timezone_name else "UTC"}


def branch_lifecycle(system: str, branches: List[str], lifecycle: Optional[dict]) -> Dict[str, dict]:
    """Support dates of each branch. A branch missing from the table: older ones ended,
    newer ones are not dated yet."""
    if not lifecycle:
        return {}
    listed = lifecycle["branches"]
    newest = max((branch_key(system, b) for b in listed), default=())
    found = {}
    for branch in branches:
        if branch in listed:
            found[branch] = {**listed[branch], "listed": True}
        else:
            found[branch] = {"listed": False, "newer": branch_key(system, branch) > newest}
    return found


def cross_references(documents: Dict[str, dict]) -> Dict[str, Dict[str, set]]:
    """bug: {system: {(release, status code)}}, across the notes of every system.

    ASA and FTD share code, as IOS and IOS XE do: a bug that the notes of one system
    leave open may be listed as fixed in the notes of another."""
    found: Dict[str, Dict[str, set]] = {}
    for document in documents.values():
        for o in document["observations"]:
            found.setdefault(o["bug_id"], {}).setdefault(document["system"], set()).add((o["version"], STATUS_CODES[o["status"]]))
    return found


def build_system(system: str, documents: List[dict], manifest: Dict[str, dict], today: str,
                 lifecycle: Optional[dict] = None, references: Optional[Dict[str, Dict[str, set]]] = None) -> dict:
    """Index and bugs of one system.

    A release can be documented by several notes, one per product series; a bug
    keeps the notes that list it, so that its families and its links are exact.
    """
    documents = sorted(documents, key=lambda d: d["url"])
    if not documents:
        return {"index": {"system": system, "name": SYSTEMS[system], "families": [], "models": [], "versions": [],
                          "branches": {}, "lifecycle": None, "documents": []}, "bugs": [], "notices": []}
    doc_positions = {d["key"]: i for i, d in enumerate(documents)}
    versions = sorted({v for d in documents for v in d["versions"]}, key=lambda v: version_key(system, v))
    positions = {v: i for i, v in enumerate(versions)}
    families = sorted({f for d in documents for f in d["families"]}, key=str.lower)
    family_positions = {name: i for i, name in enumerate(families)}

    bugs: Dict[str, dict] = {}
    for document in documents:
        doc = doc_positions[document["key"]]
        for o in document["observations"]:
            bug = bugs.setdefault(o["bug_id"], {"events": {}, "families": set(), "descriptions": {}})
            bug["families"].update(document["families"])
            # The headline of the most recent release wins: Cisco rewords some over time.
            bug["descriptions"][version_key(system, o["version"])] = o["description"]
            # Where the fact is written: the note, and the page of the note (a chapter of a book).
            where = [doc, document["pages"].index(o["url"]) if o["url"] in document["pages"] else 0]
            event = bug["events"].setdefault((o["version"], o["status"]), [positions[o["version"]], STATUS_CODES[o["status"]], []])
            if where not in event[2]:
                event[2].append(where)

    rows = []
    cited_models = set()
    for bug_id, bug in sorted(bugs.items(), key=lambda item: item[0], reverse=True):
        description = bug["descriptions"][max(bug["descriptions"])] if bug["descriptions"] else ""
        models = [m for m in models_in(description, system) if family_of_model(m, system) in family_positions]
        cited_models.update(models)
        cited = (set(families_in(description)) | {family_of_model(m, system) for m in models}) & set(family_positions)
        rows.append([
            bug_id,
            description,
            models,
            sorted(family_positions[name] for name in bug["families"] | cited),
            sorted(bug["events"].values(), key=lambda event: (event[0], event[1])),
            # What the notes of the other systems say of the same bug: [system, release, status].
            sorted(([other, version, code] for other, facts in (references or {}).get(bug_id, {}).items() if other != system
                    for version, code in facts), key=lambda f: (f[0], version_key(f[0], f[1]), f[2])),
        ])

    revised_by_version: Dict[str, str] = {}
    released: Dict[str, str] = {}
    docs_by_version: Dict[str, List[int]] = {}
    for document in documents:
        doc = doc_positions[document["key"]]
        for version in document["versions"]:
            docs_by_version.setdefault(version, []).append(doc)
            if document.get("revised") and document["revised"] > revised_by_version.get(version, ""):
                revised_by_version[version] = document["revised"]
        for version, date in document["released"].items():
            if version in positions and (version not in released or date < released[version]):
                released[version] = date

    # A branch is active when one of its notes was revised in the last year: Cisco
    # publishes no single table of support dates for its releases.
    limit = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=ACTIVE_DAYS)).strftime("%Y-%m-%d")
    # The latest release of a branch tells its activity best; without release dates, the
    # latest revision of its notes. Cisco revises the notes of old branches too, all at once.
    branch_released: Dict[str, str] = {}
    branch_revised: Dict[str, str] = {}
    for version in versions:
        branch = parts(system, version)[0]
        branch_released[branch] = max(branch_released.get(branch, ""), released.get(version, ""))
        branch_revised[branch] = max(branch_revised.get(branch, ""), revised_by_version.get(version, ""))
    branch_activity = {branch: branch_released.get(branch) or branch_revised.get(branch, "") for branch in branch_revised}
    # A branch without release dates, older than a branch with some, cannot be more active
    # than that one: its notes were revised along with the others, not for a new release.
    dated = sorted((b for b in branch_released if branch_released[b]), key=lambda b: branch_key(system, b))
    for branch in branch_activity:
        newer = [b for b in dated if branch_key(system, b) > branch_key(system, branch)]
        if not branch_released.get(branch) and newer:
            branch_activity[branch] = min(branch_activity[branch], min(branch_released[b] for b in newer))
    index_versions = [{
        "v": version,
        "branch": parts(system, version)[0],
        "train": train_of(system, version),
        "rebuild": is_rebuild(system, version),
        "released": released.get(version),
        "revised": revised_by_version.get(version),
        "docs": sorted(docs_by_version.get(version, [])),
        "families": sorted({family_positions[f] for d in docs_by_version.get(version, []) for f in documents[d]["families"]}),
    } for version in versions]
    branches = sorted({entry["branch"] for entry in index_versions}, key=lambda b: branch_key(system, b))
    dates = branch_lifecycle(system, branches, lifecycle)
    index = {
        "system": system,
        "name": SYSTEMS[system],
        "families": families,
        "models": [[m, family_positions[family_of_model(m, system)]] for m in sorted(cited_models, key=model_sort_key)],
        "versions": index_versions,
        "branches": {b: {"activity": branch_activity.get(b) or None, "active": branch_activity.get(b, "") >= limit,
                         **dates.get(b, {})} for b in branches},
        # With support dates, the site says "supported" from them; without, "active" from the notes.
        "lifecycle": {"source": lifecycle["source"], "policy": lifecycle.get("policy")} if lifecycle else None,
        "documents": [{
            "url": d["url"],
            "pdf": None if manifest.get(d["key"], {}).get("unavailable") else pdf_of(d["url"]),
            "title": d["title"],
            "families": [family_positions[f] for f in d["families"]],
            "revised": d.get("revised"),
            "pages": d["pages"],
        } for d in documents],
    }
    # Sections to read before an upgrade, per note: a release reads those of its notes.
    notices = [d["notices"] for d in documents]
    return {"index": index, "bugs": rows, "notices": notices}


def build_site(extracted: Path, manifest_path: Path, changes_path: Path, schedule_path: Path,
               sources: Path, dist: Path, base_url: str, lifecycle_path: Path = Path("sources/lifecycle.json")) -> dict:
    documents = load_documents(extracted)
    manifest = load_manifest(manifest_path)
    now = datetime.now(timezone.utc)
    updated = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    schedule = read_schedule(schedule_path)
    all_changes = read_changes(changes_path)
    lifecycles = load_lifecycle(lifecycle_path)
    references = cross_references(documents)

    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(sources, dist)
    summary = {}
    descriptions: Dict[str, str] = {}
    for system in SYSTEMS:
        own = [d for d in documents.values() if d["system"] == system]
        # A system whose notes are not collected yet still gets its files: the page says so.
        data = build_system(system, own, manifest, now.strftime("%Y-%m-%d"), lifecycles.get(system), references)
        data["index"].update({"updated": updated, "schedule": schedule})
        changes = latest_changes([c for c in all_changes if c["system"] == system], documents)
        folder = dist / "data" / system
        folder.mkdir(parents=True)
        for name, content in (("index.json", data["index"]), ("bugs.json", data["bugs"]),
                              ("changes.json", changes), ("notices.json", data["notices"])):
            (folder / name).write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        descriptions.update({row[0]: row[1] for row in data["bugs"]})
        rows = data["bugs"]
        summary[system] = {
            "notes": len(own),
            "versions": len(data["index"]["versions"]),
            "families": len(data["index"]["families"]),
            "models": len(data["index"]["models"]),
            "bugs": len(rows),
            "with model": sum(1 for row in rows if row[2]),
            "cited elsewhere": sum(1 for row in rows if row[5]),
            "active branches": sum(1 for b in data["index"]["branches"].values() if b["active"]),
            "dated branches": sum(1 for b in data["index"]["branches"].values() if b.get("listed")),
        }
    # Every bug ID with the systems whose notes list it: a search on another tab can point there.
    ids = {bug: sorted(systems) for bug, systems in references.items()}
    (dist / "data" / "ids.json").write_text(json.dumps(ids, separators=(",", ":")), encoding="utf-8")
    (dist / "feed.xml").write_bytes(build_feed(latest_changes(all_changes, documents), descriptions, base_url))
    return summary
