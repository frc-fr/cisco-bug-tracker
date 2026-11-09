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
