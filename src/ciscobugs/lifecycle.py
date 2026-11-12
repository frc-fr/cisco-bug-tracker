"""Support dates of the branches, from endoflife.date, for the systems it covers.

Cisco publishes no single table of support dates. endoflife.date gathers those of
IOS XE from Cisco's bulletins: release date, end of maintenance, end of security
support, and the long-term (LTS) branches. Its robots.txt allows every robot.
Read when the data is collected, never by the browser. An answer that no longer
parses keeps the last dates.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

API = "https://endoflife.date/api/v1/products/{product}"
PRODUCTS = {"iosxe": "cisco-ios-xe"}
MINIMUM_BRANCHES = 5


def parse_product(data: dict) -> dict:
    """{page, policy, branches: {branch: {released, maintenance, support, lts}}}; raise if it looks wrong."""
    result = data["result"]
    branches = {}
    for release in result["releases"]:
        branches[release["name"]] = {
            "released": release.get("releaseDate"),
            "maintenance": release.get("eoasFrom"),
            "support": release.get("eolFrom"),
            "lts": bool(release.get("isLts")),
        }
    if len(branches) < MINIMUM_BRANCHES:
        raise ValueError(f"only {len(branches)} branches")
    links = result.get("links") or {}
    return {"page": links.get("html"), "policy": links.get("releasePolicy"), "branches": branches}


def load_lifecycle(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def update_lifecycle(path: Path, client) -> None:
    """Refresh the dates; the Release Notes must not depend on this source."""
    known = load_lifecycle(path)
    for system, product in PRODUCTS.items():
        try:
            response = client.request("GET", API.format(product=product))
            response.raise_for_status()
            known[system] = {"source": f"https://endoflife.date/{product}", **parse_product(response.json())}
        except (RuntimeError, ValueError, KeyError, OSError) as error:
            log.error("%s: support dates kept as they were: %s", system, error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(known, indent=2) + "\n", encoding="utf-8")


# Cisco's own sources, for the systems endoflife.date does not cover. A table gives every
# branch ("complete"); a list of end-of-life announcements only the branches announced so
# far: a branch it does not name is still supported, unless it is older than all of them.
import html as _html
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

NXOS_URL = "https://www.cisco.com/c/en/us/products/collateral/ios-nx-os-software/nx-os-software/guide_c07-658595.html"
FTD_URL = "https://www.cisco.com/c/en/us/td/docs/security/secure-firewall/compatibility/threat-defense-compatibility.html"
LISTINGS = {
    "iosxr": "https://www.cisco.com/c/en/us/products/ios-nx-os-software/ios-xr-software/eos-eol-notice-listing.html",
    "asa": "https://www.cisco.com/c/en/us/products/security/asa-firepower-services/eos-eol-notice-listing.html",
}
# The branch an announcement is about: "IOS XR Software Release 25.1", "ASA) Release 9.19(x)", "Software Release 9.2 and".
ANNOUNCED = {
    "iosxr": re.compile(r"IOS XR Software Release (\d+\.\d+)\b"),
    "asa": re.compile(r"Adaptive Security Appliance\s?\(ASA\)\s*(?:Software\s+)?(?:Release\s+)?(9\.\d+)"),
}
TABLE = re.compile(r"<table.*?</table>", re.S)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
LINK = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
MILESTONES = {
    "sale": re.compile(r"^End-of-Sale Date", re.I),
    "maintenance": re.compile(r"^End of SW Maintenance Releases", re.I),
    "support": re.compile(r"^Last Date of Support", re.I),
}


def text_of(fragment: str) -> str:
    return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def rows_of(page: str, marker: str) -> List[List[str]]:
    """The rows of the tables whose text holds the marker."""
    found = []
    for table in TABLE.findall(page):
        if marker in text_of(table):
            found += [[text_of(c) for c in CELL.findall(row)] for row in ROW.findall(table)]
    return found


def day(text: str) -> Optional[str]:
    text = re.sub(r"[*†]", "", text).strip()
    for layout in ("%Y-%m-%d", "%b %d %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, layout).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def parse_nxos(page: str) -> Dict[str, dict]:
    """The NX-OS lifecycle statement: per major release, end of software maintenance and last date of support.

    The last column can hold two dates ("Feb 28 2025/Aug 31 2025"): the later one ends the support.
    """
    branches = {}
    for cells in rows_of(page, "EoSWM"):
        match = re.match(r"^(\d+\.\d+)\(x\)", cells[0]) if cells else None
        if not match or len(cells) < 3:
            continue
        ends = [d for d in (day(part) for part in cells[2].split("/")) if d]
        branches[match.group(1)] = {"released": None, "maintenance": day(cells[1]), "support": max(ends) if ends else None,
                                    "lts": False}
    if len(branches) < 3:
        raise ValueError(f"only {len(branches)} NX-OS branches")
    return branches


def parse_ftd(page: str) -> dict:
    """The Threat Defense compatibility guide: end of life per release, and per platform its last release.

    "6.2.3" and "6.2" are both of branch 6.2: the branch lives as long as its last row.
    """
    branches: Dict[str, dict] = {}
    for cells in rows_of(page, "End of updates"):
        match = re.match(r"^(\d+\.\d+)(?:\.\d+)?$", cells[0]) if cells else None
        if not match or len(cells) < 4:
            continue
        entry = {"released": None, "sale": day(cells[1]), "maintenance": day(cells[2]), "support": day(cells[3]), "lts": False}
        old = branches.get(match.group(1))
        if not old or (entry["support"] or "") > (old["support"] or ""):
            branches[match.group(1)] = entry
    platforms = {}
    for cells in rows_of(page, "Last device version"):
        if len(cells) < 5 or not re.match(r"^\d+\.\d+", cells[1]):
            continue
        for model in platform_models(cells[0]):
            platforms[model] = {"last": ".".join(cells[1].split(".")[:2]), "sale": day(cells[3]), "support": day(cells[4]),
                                "platform": cells[0]}
    if len(branches) < 5:
        raise ValueError(f"only {len(branches)} FTD branches")
    return {"branches": branches, "platforms": platforms}


def platform_models(cell: str) -> List[str]:
    """The model names the site uses: "Firepower 2110, 2120" gives FPR2110, FPR2120; "ASA 5506-X, 5506H-X" ASA5506."""
    # "Firepower 9300: SM-24, SM-36, SM-44 modules": modules of a chassis that goes on with other modules.
    if ":" in cell or re.search(r"\bmodules?\b", cell, re.I):
        return []
    prefix = "ASA" if cell.startswith("ASA") else "FPR"
    return list(dict.fromkeys(f"{prefix}{number}" for number in re.findall(r"\b(\d{4})[A-Z]?\b", cell)))


def parse_announcement(page: str) -> dict:
    """The software milestones of an end-of-life bulletin."""
    found = {}
    for cells in rows_of(page, "Milestone"):
        for field, pattern in MILESTONES.items():
            if cells and pattern.search(cells[0]) and field not in found:
                found[field] = day(cells[-1])
    return found


def update_announcements(system: str, known: dict, client) -> dict:
    """The branches of a list of end-of-life announcements; each announcement is read once."""
    state = known.get(system, {})
    bulletins = state.get("bulletins", {})
    listing = client.request("GET", LISTINGS[system])
    listing.raise_for_status()
    for href, label in LINK.findall(listing.text):
        title = text_of(label)
        match = ANNOUNCED[system].search(title)
        url = urljoin(LISTINGS[system], href)
        if not match or re.search(r"-[a-z]{2}\.html$", url) or url in bulletins:
            continue
        response = client.request("GET", url)
        if response.status_code != 200:
            log.error("%s returned %s", url, response.status_code)
            continue
        bulletins[url] = {"branch": match.group(1), "title": title, **parse_announcement(response.text)}
    branches: Dict[str, dict] = {}
    for url, bulletin in bulletins.items():
        entry = {"released": None, "sale": bulletin.get("sale"), "maintenance": bulletin.get("maintenance"),
                 "support": bulletin.get("support"), "lts": False, "page": url}
        old = branches.get(bulletin["branch"])
        if entry["support"] and (not old or entry["support"] > (old["support"] or "")):
            branches[bulletin["branch"]] = entry
    if not branches:
        raise ValueError(f"no {system} announcement")
    return {"source": LISTINGS[system], "page": LISTINGS[system], "policy": None, "complete": False,
            "branches": branches, "bulletins": bulletins}


def update_cisco(path: Path, client) -> None:
    """Refresh the dates Cisco publishes itself; a source that fails keeps its last dates."""
    known = load_lifecycle(path)
    try:
        response = client.request("GET", NXOS_URL)
        response.raise_for_status()
        known["nxos"] = {"source": NXOS_URL, "page": NXOS_URL, "policy": NXOS_URL, "complete": True,
                         "branches": parse_nxos(response.text)}
    except (RuntimeError, ValueError, OSError) as error:
        log.error("nxos: support dates kept as they were: %s", error)
    try:
        response = client.request("GET", FTD_URL)
        response.raise_for_status()
        parsed = parse_ftd(response.text)
        known["ftd"] = {"source": FTD_URL, "page": FTD_URL, "policy": FTD_URL, "complete": False, **parsed}
    except (RuntimeError, ValueError, OSError) as error:
        log.error("ftd: support dates kept as they were: %s", error)
    for system in LISTINGS:
        try:
            known[system] = update_announcements(system, known, client)
        except (RuntimeError, ValueError, OSError) as error:
            log.error("%s: support dates kept as they were: %s", system, error)
    path.write_text(json.dumps(known, indent=2) + "\n", encoding="utf-8")
