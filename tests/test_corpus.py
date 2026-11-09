"""Checks on the real notes; skipped when .cache/html is empty."""
import json
import os
from pathlib import Path

import pytest

from ciscobugs.collect import cached_pages, document_key, load_manifest
from ciscobugs.parser import parse_document

CACHE = Path(os.environ.get("CISCOBUGS_CACHE", ".cache/html"))
MANIFEST = load_manifest(Path("sources/manifest.json"))
CACHED = sorted(key for key in MANIFEST if (CACHE / key / "pages.json").exists())
pytestmark = pytest.mark.corpus
DOCS = "https://www.cisco.com/c/en/us/td/docs/"


def document(path: str):
    key = document_key(DOCS + path)
    if key not in MANIFEST or not (CACHE / key / "pages.json").exists():
        pytest.skip(f"{path} not cached")
    entry = MANIFEST[key]
    return parse_document(cached_pages(CACHE / key), entry["system"])


def facts(doc):
    return {(o["bug_id"], o["version"], o["status"]) for o in doc.observations}


@pytest.mark.skipif(not CACHED, reason="no cached note")
def test_most_notes_give_bugs():
    """Some notes list no bug: "There are no caveats in this release" (IOS XR), security fixes
    only (NX-OS 9.3(16)), or bugs left to the Bug Search Tool. About four in five do."""
    with_bugs = 0
    for key in CACHED:
        doc = parse_document(cached_pages(CACHE / key), MANIFEST[key]["system"])
        with_bugs += bool(doc.observations)
    assert with_bugs >= 0.7 * len(CACHED)


def test_ios_15_9_3_m():
    doc = document("ios-xml/ios/15-9m/release/notes/15-9-3-m-rel-notes.html")
    assert ("CSCvd19860", "15.9(3)M", "resolved") in facts(doc)
    assert ("CSCwk79078", "15.9(3)M10", "open") in facts(doc)
    assert "15.9(3)M13" in doc.versions
    assert not any(o["bug_id"] == "CSCwq01495" for o in doc.observations)  # an IKEv2 vulnerability


def test_nexus_9000_10_5_5_m():
    doc = document("dcn/nx-os/nexus9000/105x/release-notes/cisco-nexus-9000-nxos-release-notes-1055M.html")
    assert ("CSCwj48097", "10.5(5)M", "open") in facts(doc)
    assert ("CSCwq07875", "10.5(5)M", "resolved") in facts(doc)
    assert doc.released["10.5(5)M"] == "2026-03-13"


def test_nexus_9000_9_2_1():
    doc = document("switches/datacenter/nexus9000/sw/92x/release/notes/921_9000_nxos_rn.html")
    assert ("CSCvf92051", "9.2(1)", "resolved") in facts(doc)
    assert ("CSCuy08187", "9.2(1)", "open") in facts(doc)


def test_catalyst_8300_26_1():
    doc = document("routers/cloud_edge/c8300/rel_notes/26-x/release-notes-catalyst-8200-and-catalyst-8300-series-edge-platforms-release-26-1-x.html")
    assert ("CSCwu11498", "26.1.2", "resolved") in facts(doc)
    assert ("CSCws72902", "26.1.1", "open") in facts(doc)
    assert doc.versions == ["26.1.1", "26.1.2"]
