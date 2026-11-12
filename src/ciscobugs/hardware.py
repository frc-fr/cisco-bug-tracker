"""Hardware status: Cisco's End-of-Sale and End-of-Life bulletins.

Read when the data is collected, never by the browser. Each product series
followed by the site has an "EoS/EoL notice listing" page on cisco.com, which
links to its bulletins. A hardware bulletin gives the milestones of a list of
product IDs (PID): end of sale, end of software maintenance releases, last
date of support. Only the chassis PIDs are kept: a line card, a fan, a power
supply, a spare ("=") or a Cisco ONE bundle ("C1-") says nothing of the model.
A bulletin about software (milestones "OS SW") is recorded, not used.

Cisco gives no last software release per model, unlike Juniper or Palo Alto
Networks: the end of software maintenance stands for it. Not every model has a
bulletin, and the listings are incomplete: a model without bulletin is shown
as "no end announced", never as supported.

A bulletin is read once: its URL is its identity. The listings are read again
once a week. A listing that fails keeps the bulletins already known.
"""
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

from .normalize import FIREWALL_MODEL, MODEL, canonical_model, family_of_model

log = logging.getLogger(__name__)

LISTING_DAYS = 7
TABLE = re.compile(r"<table.*?</table>", re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
TITLE = re.compile(r"<title>(.*?)</title>", re.S)
# English bulletins only: the translations repeat them.
BULLETIN_LINK = re.compile(r'<a[^>]*href="([^"]*/eos-eol-notice-(c\d+-\d+)\.html)"[^>]*>(.*?)</a>', re.S)
# A title about software or offers needs no download; a bulletin read anyway is recorded as such.
SOFTWARE_TITLE = re.compile(r"\b(?:Releases?|Software|IOS|NX-OS|FTD|FMC|FXOS|Versions?|Licen[cs]es?|Program|NDB|offer|Cisco ONE)\b", re.I)
HARDWARE_WORD = re.compile(r"\b(?:Switch(?:es)?|Routers?|Appliances?|Chassis|Platforms?|Series)\b", re.I)
MILESTONES = {
    "end_of_sale": re.compile(r"^End-of-Sale Date:? HW", re.I),
    "end_of_maintenance": re.compile(r"^End of SW Maintenance Releases Date.*HW", re.I),
    "end_of_support": re.compile(r"^Last Date of Support:? HW", re.I),
}
NOT_A_CHASSIS = re.compile(
    r"line ?card|linecard|module|\bfans?\b|fan tray|power suppl|\bpsu\b|supervisor|licen[cs]e|subscription|cable|"
    r"\bkit\b|bracket|transceiver|optic|blank|rack|accessor|bundle|upgrade|memory|\bssd\b|flash|\bdram\b|adapter|"
    r"\btray\b|spare|\d ?-?years?\b|\bpromo\b|\bpcb\b|\bnim\b|stacking cable|stack ?power|software|\bimage\b|route processor|\brp\d?\b|\besp\d*\b|\bsip\b|\bspa\b",
    re.I,
)
PID_SUFFIX = re.compile(r"-(?:K[789]|AC|DC|RF|WS)$")
# A segment naming a part of a chassis: ASR1000-ESP20 is a processor, ASR-9912-SFC110 a fabric card.
PART_SEGMENT = re.compile(r"-(?:ESP|RP|SIP|SPA|SFC|FC|FM|LC|SUP|FAN|PWR|PS|NM|MOD|\d*SSD|HD)\d*(?:GB)?(?:-|$)")


def cell_text(cell: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).replace("\xa0", " ").split())


def iso(text: str) -> Optional[str]:
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text).strip()
    for layout in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, layout).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def listing_bulletins(page: str, base: str) -> Dict[str, dict]:
    """The English bulletins a listing links to, by their URL."""
    found = {}
    for link, number, title in BULLETIN_LINK.findall(page):
        if re.search(r"-[a-z]{2}\.html$", link):
            continue
        found[urljoin(base, link)] = {"bulletin": number, "title": cell_text(title)}
    return found


def worth_reading(title: str) -> bool:
    return not SOFTWARE_TITLE.search(title) or bool(HARDWARE_WORD.search(title) and not re.search(r"Releases?\b", title))


# A Nexus chassis is N9K-C…: N9K-X… is a line card, N9K-M… a module.
NEXUS_PART = re.compile(r"^N[379]K-(?!C\d)")


def chassis_name(pid: str, description: str) -> Optional[tuple]:
    """(model, PID) of a chassis, None for a part: N9K-C9372PX is a chassis, N9K-C9372PX= a spare.

    The PID must start with a model the site recognizes in the notes (C9300,
    ASR1004, N9K-C9372PX, ASA5505, FPR2110): education, bundle and Cisco ONE
    PIDs (EDU-, NAL-, C1…) and the parts of a chassis do not.
    """
    pid = pid.strip().rstrip("+")
    if not pid or pid.endswith("=") or NEXUS_PART.match(pid) or PART_SEGMENT.search(pid) or NOT_A_CHASSIS.search(description):
        return None
    while PID_SUFFIX.search(pid):
        pid = PID_SUFFIX.sub("", pid)
    core = pid[3:] if pid.startswith("WS-") and not pid.startswith("WS-C3850") and not pid.startswith("WS-C2960X") else pid
    match = MODEL.match(core) or FIREWALL_MODEL.match(core)
    if not match:
        return None
    model = canonical_model(match.group(0))
    # A Nexus PID carries its airflow and power after the switch: N3K-C3064-X-BA-L3 is an N3K-C3064.
    nexus = re.match(r"^(N[379]K-C\d+[A-Z]*)", model)
    if nexus:
        model = nexus.group(1)
    if not (family_of_model(model) or FIREWALL_MODEL.fullmatch(match.group(0))):
        return None
    return model, pid


def parse_bulletin(page: str) -> dict:
    """The hardware milestones of a bulletin and all its part numbers; "hardware": False otherwise.

    The parts are kept whole: the build picks the chassis among them, so a better
    filter needs no new download.
    """
    dates: Dict[str, Optional[str]] = {}
    parts = []
    for table in TABLE.findall(page):
        rows = [[cell_text(cell) for cell in CELL.findall(row)] for row in ROW.findall(table)]
        if not rows:
            continue
        head = " ".join(rows[0]).lower()
        if head.startswith("milestone"):
            for cells in rows[1:]:
                for field, pattern in MILESTONES.items():
                    if cells and pattern.search(cells[0]) and field not in dates:
                        dates[field] = iso(cells[-1])
        elif "part number" in head:
            for cells in rows[1:]:
                if len(cells) >= 2 and cells[0]:
                    parts.append([cells[0], cells[1]])
    if not dates:
        return {"hardware": False}
    return {"hardware": True, **{field: dates.get(field) for field in MILESTONES}, "parts": parts}


def chassis_of(bulletin: dict) -> List[tuple]:
    return sorted({named for pid, description in bulletin.get("parts", []) for named in [chassis_name(pid, description)] if named})


def load_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"listings": [], "bulletins": []}


def save_state(path: Path, state: dict) -> None:
    """The listings as written by hand, then one bulletin per line for readable diffs."""
    listings = ",\n".join("  " + json.dumps(listing, ensure_ascii=False) for listing in state["listings"])
    bulletins = ",\n".join("  " + json.dumps(b, ensure_ascii=False)
                           for b in sorted(state["bulletins"], key=lambda b: b["url"]))
    head = {key: value for key, value in state.items() if key not in ("listings", "bulletins")}
    body = json.dumps(head, ensure_ascii=False)[:-1]
    separator = ", " if head else ""
    path.write_text(f'{body}{separator}"listings": [\n{listings}\n], "bulletins": [\n{bulletins}\n]}}\n', encoding="utf-8")


def update_hardware(path: Path, client, today: Optional[datetime] = None) -> None:
    """Read the listings due, then the bulletins not read yet."""
    today = today or datetime.now(timezone.utc)
    state = load_state(path)
    known = {b["url"]: b for b in state["bulletins"]}
    for listing in state["listings"]:
        checked = listing.get("checked")
        if checked and datetime.strptime(checked, "%Y-%m-%d").replace(tzinfo=timezone.utc) > today - timedelta(days=LISTING_DAYS):
            continue
        try:
            response = client.request("GET", listing["url"])
            response.raise_for_status()
        except (RuntimeError, OSError) as error:
            log.error("listing kept as it was: %s", error)
            continue
        for url, found in listing_bulletins(response.text, listing["url"]).items():
            entry = known.setdefault(url, {"url": url, **found, "families": []})
            entry["families"] = sorted(set(entry["families"]) | set(listing["families"]))
        listing["checked"] = today.strftime("%Y-%m-%d")
    read = 0
    for entry in known.values():
        if "hardware" in entry:
            continue
        if not worth_reading(entry["title"]):
            entry["hardware"] = False
            continue
        try:
            response = client.request("GET", entry["url"])
            response.raise_for_status()
        except (RuntimeError, OSError) as error:
            log.error("bulletin not read: %s", error)
            continue
        entry.update(parse_bulletin(response.text))
        read += 1
        # An interrupted run keeps the bulletins already read.
        if read % 10 == 0:
            state["bulletins"] = list(known.values())
            save_state(path, state)
    state["bulletins"] = list(known.values())
    save_state(path, state)


def base_of(name: str) -> str:
    """N9K-C9372PX and N9K-9372PX are the same switch: the notes drop the C as often as not."""
    return re.sub(r"^(N[379]K-)C(?=\d)", r"\1", name.upper().replace(" ", ""))


def hardware_index(families: List[str], cited: List[str], state: Optional[dict],
                   platforms: Optional[dict] = None, platforms_page: Optional[str] = None) -> dict:
    """The models of the Hardware tab of a system: those the notes cite and the chassis of its bulletins.

    A chassis is shown under the cited model it starts with (C9300-24T under
    C9300), as one of its variants; otherwise as a model of its own. The shape is
    that of juni-bug-tracker, with the end of software maintenance as sixth field.
    """
    bulletins = [b for b in (state or {}).get("bulletins", [])
                 if b.get("hardware") and chassis_of(b) and set(b["families"]) & set(families)]
    by_base = sorted(((base_of(model), model) for model in cited), key=lambda item: -len(item[0]))
    entries: Dict[str, dict] = {model: {"cited": True, "family": None, "eol": [], "suggested": []} for model in cited}
    for bulletin in bulletins:
        groups: Dict[str, List[str]] = {}
        for model, pid in chassis_of(bulletin):
            owner = next((cited_model for prefix, cited_model in by_base
                          for base in (base_of(model), base_of(pid)) if base == prefix or base.startswith(prefix + "-")), model)
            groups.setdefault(owner, []).append(pid)
        family = next(f for f in bulletin["families"] if f in families)
        for model, variants in groups.items():
            entry = entries.setdefault(model, {"cited": False, "family": family, "eol": [], "suggested": []})
            entry["family"] = entry["family"] or family
            entry["eol"].append([sorted(set(variants)), bulletin["bulletin"], None, bulletin["end_of_support"], bulletin["url"],
                                 bulletin["end_of_maintenance"]])
    # The Threat Defense guide gives the last release of each Firepower and ASA platform it dropped.
    family = families[0] if families else None
    for model, entry in (platforms or {}).items():
        owners = [m for m in entries if base_of(m).replace("-", "") == base_of(model)] or [model]
        for owner in owners:
            target = entries.setdefault(owner, {"cited": False, "family": family, "eol": [], "suggested": []})
            target["eol"].append([[owner], None, entry["last"], entry["support"], platforms_page, None])
    sources = sorted({listing["url"] for listing in (state or {}).get("listings", []) if set(listing["families"]) & set(families)})
    return {"eol_source": sources[0] if len(sources) == 1 else None, "suggested_source": None, "as_of": None, "general": [],
            "models": dict(sorted(entries.items()))}
