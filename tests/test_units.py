"""Unit tests on small pages written for the purpose, in the layouts Cisco uses."""
from datetime import datetime, timezone

from ciscobugs import collect
from ciscobugs.extract import diff_releases
from ciscobugs.build import branch_lifecycle
from ciscobugs.lifecycle import parse_product
from ciscobugs.normalize import families_in, family_of_model, models_in
from ciscobugs.parser import parse_document, parse_page, section_status
from ciscobugs.versions import find_branch, find_versions, parts, sort_versions, train_of, version_key

URL = "https://www.cisco.com/c/en/us/td/docs/x/notes.html"


def page(body: str, title: str) -> str:
    return f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>"


def table(*rows, header=("Bug ID", "Description")) -> str:
    cells = "".join(f"<tr>{''.join(f'<td><p>{c}</p></td>' for c in row)}</tr>" for row in rows)
    return f"<table><thead><tr>{''.join(f'<th>{h}</th>' for h in header)}</tr></thead><tbody>{cells}</tbody></table>"


def test_release_formats():
    assert parts("ios", "15.9(3)M0a") == ("15.9(3)M", 0, "a")
    assert parts("iosxe", "17.12.3a") == ("17.12", 3, "a")
    assert parts("iosxr", "7.11.21") == ("7.11", 2, "1")
    assert parts("nxos", "10.3(4a)M") == ("10.3", 4, "a")
    assert parts("asa", "9.22(1.1)") == ("9.22", 1, "1")
    assert parts("ftd", "7.4.2.1") == ("7.4", 2, "1")
    assert train_of("iosxe", "17.12.3a") == train_of("iosxe", "17.12.3")
    assert sort_versions("ios", ["15.9(3)M1", "15.9(3)M0a", "15.9(3)M", "15.9(3)M10"]) == [
        "15.9(3)M", "15.9(3)M0a", "15.9(3)M1", "15.9(3)M10"]
    assert version_key("iosxe", "17.12.3a") < version_key("iosxe", "17.12.4")


def test_releases_in_text():
    assert find_versions("ios", "Resolved Bugs—Cisco IOS Release 15.9(3)M13") == ["15.9(3)M13"]
    assert find_versions("ios", "Cisco IOS Release 15.2(6)Ex") == []
    assert find_versions("iosxe", "Open Caveats in Cisco IOS XE Gibraltar 16.12.x") == []
    assert find_branch("iosxe", "Open Caveats in Cisco IOS XE Gibraltar 16.12.x") == "16.12"
    assert find_branch("asa", "Open Bugs in Version 9.22(x)") == "9.22"
    assert find_versions("ftd", "Resolved Bugs in Version 7.6.7, not 7.6.7.1") == ["7.6.7", "7.6.7.1"]


def test_section_status():
    assert section_status("Resolved issues in Cisco IOS XE 26.1.2") == "resolved"
    assert section_status("Open Caveats—Cisco NX-OS Release 9.2(1)") == "open"
    assert section_status("Resolved and Open issues in Cisco IOS XE 26.1.1") is None
    assert section_status("Table 16. Resolved Security Bugs in Version 7.6.7") == "security"
    assert section_status("General/known issues") == "limitation"
    assert section_status("Table 1. Cisco ASR 9000 Series Router Specific Bugs") == "open"
    assert section_status("Cisco IOS XR Caveats Release 7.4.1") == "open"


def test_heading_gives_the_release_and_caption_the_status():
    html = page(
        '<p class="pToC_Subhead2">Resolved and Open issues in Cisco IOS XE 26.1.1</p>'
        '<p class="pTableCaptionCMT">Table 3. Open issues for Catalyst 8500, Release 26.1.1</p>'
        + table(("CSCws72902", "Overruns on interfaces with GRE tunnels."))
        + '<h3 class="title">Open Bugs—Cisco IOS Release 26.1.2</h3>'
        '<caption>Table 4. Resolved issues for Release 26.1.1</caption>'
        + table(("CSCwt00001", "Copied caption, wrong release.")),
        "Release Notes for Catalyst 8500, Release 26.1.x")
    document = parse_document([(URL, html)], "iosxe")
    found = {(o["bug_id"], o["version"], o["status"]) for o in document.observations}
    assert ("CSCws72902", "26.1.1", "open") in found
    assert ("CSCwt00001", "26.1.2", "resolved") in found


def test_security_and_unknown_sections_are_left_out():
    html = page(
        "<h3>Resolved Bugs in Version 7.6.7</h3>"
        + table(("CSCwq01495", "IKEv2 denial of service vulnerability."), ("CSCwr00001", "Crash in snort (CVE-2025-12345)"))
        + "<h3>Behavior Changes</h3>" + table(("CSCwr00002", "Something")),
        "Cisco Secure Firewall Threat Defense Release Notes, Version 7.6.x")
    document = parse_document([(URL, html)], "ftd")
    assert [(o["bug_id"], o["description"]) for o in document.observations] == [("CSCwr00001", "Crash in snort")]
    assert document.skipped == 1
    assert document.left_out and not document.warnings


def test_branch_wide_open_bugs_go_to_the_latest_release():
    html = page(
        "<h3>Open Bugs in Version 9.22(x)</h3>" + table(("CSCws68206", "Headline: VLAN lost after upgrade"))
        + "<h4>Resolved Bugs in Version 9.22(3)</h4>" + table(("CSCvh98118", "debug fails"))
        + "<h4>Resolved Bugs in Version 9.22(2)</h4><p>None.</p>",
        "Release Notes for the Cisco Secure Firewall ASA, 9.22(x)")
    document = parse_document([(URL, html)], "asa")
    found = {(o["bug_id"], o["version"], o["status"], o["description"]) for o in document.observations}
    assert ("CSCws68206", "9.22(3)", "open", "VLAN lost after upgrade") in found
    assert document.versions == ["9.22(2)", "9.22(3)"]


def test_title_release_and_revision_dates():
    html = page(
        table(("March 13, 2026", "Release 10.5(5)M became available."), header=("Date", "Description"))
        + '<p class="pToC_Subhead1">Open issues</p>' + table(("CSCwj48097", "n/a bps"), header=("Identifier", "Headline")),
        "Cisco Nexus 9000 Series NX-OS Release Notes, Release 10.5(5)M")
    document = parse_document([(URL, html)], "nxos")
    assert document.released == {"10.5(5)M": "2026-03-13"}
    assert [(o["bug_id"], o["version"], o["status"]) for o in document.observations] == [("CSCwj48097", "10.5(5)M", "open")]


def test_book_chapters():
    html = page('<a href="notes/caveats.html">Caveats</a><a href="notes/introduction.html">Intro</a>'
                '<a href="/c/en/us/td/docs/x/notes.pdf">PDF</a>', "Release Notes, Cisco IOS XE 17.12.x")
    assert parse_page(html, URL, "iosxe").chapters == ["https://www.cisco.com/c/en/us/td/docs/x/notes/caveats.html"]


def test_hardware():
    assert models_in("C9300X stack: N9K-C93180YC-FX crash on ISR4451 and ASR1001-X", "iosxe") == [
        "ASR1001-X", "C9300X", "ISR4451", "N9K-C93180YC-FX"]
    assert family_of_model("C9300X") == "Catalyst 9300"
    assert families_in("Nexus 9504 with N9K-X9736C-FX fails") == ["Nexus 9000"]


def test_etag_date_and_keys():
    assert collect.etag_date('"dc99d-65cbe4add47e2"') == "2026-10-01"
    assert collect.etag_date("W/abc") is None
    a = collect.document_key("https://www.cisco.com/c/en/us/td/docs/a/release-notes.html")
    b = collect.document_key("https://www.cisco.com/c/en/us/td/docs/b/release-notes.html")
    assert a != b and a.startswith("release-notes-")
    assert collect.normalize_link("/content/en/us/td/docs/x/y.html#top", "https://www.cisco.com/") == "https://www.cisco.com/c/en/us/td/docs/x/y.html"


def test_classification():
    catalog = collect.load_catalog(collect.Path("sources/catalog.json"))
    assert collect.classify("https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/release_notes/ol-17-12-9300.html", catalog) == ("iosxe", ["Catalyst 9300"])
    assert collect.classify("https://www.cisco.com/c/en/us/td/docs/routers/cloud_edge/c8300/rel_notes/26-x/release-notes-catalyst-8200-and-catalyst-8300-series-edge-platforms-release-26-1-x.html", catalog) == ("iosxe", ["Catalyst 8200", "Catalyst 8300"])
    assert collect.classify("https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/ip-fabric-for-media/x/cisco-nexus-9000-nxos-for-ipfm-release-notes-1043F.html", catalog) is None
    assert collect.classify("https://www.cisco.com/c/en/us/td/docs/security/asa/asa922/release/notes/asarn922.html", catalog) == ("asa", ["Secure Firewall ASA"])


def test_weekly_checks_of_old_notes():
    today = datetime(2026, 11, 9, tzinfo=timezone.utc)
    assert collect.due({"url": "u", "revised": "2026-10-01"}, today)
    old = [{"url": f"u{i}", "revised": "2020-01-01"} for i in range(70)]
    assert 0 < sum(collect.due(entry, today) for entry in old) < 70


def test_change_log():
    def doc(observations, versions):
        return {"system": "iosxe", "versions": versions, "released": {"17.12.4": "2026-01-02"}, "observations": observations}
    before = {"a": doc([{"bug_id": "CSCaa00001", "version": "17.12.4", "status": "open"}], ["17.12.4"])}
    after = {"a": doc([{"bug_id": "CSCaa00001", "version": "17.12.4", "status": "open"},
                       {"bug_id": "CSCaa00002", "version": "17.12.4", "status": "resolved"},
                       {"bug_id": "CSCaa00003", "version": "17.12.5", "status": "resolved"}], ["17.12.4", "17.12.5"])}
    changes = diff_releases(before, after, "2026-11-09", baseline=False)
    assert {(c["version"], c["kind"], tuple(c["bugs"])) for c in changes} == {
        ("17.12.4", "fixed_added", ("CSCaa00002",)), ("17.12.5", "version", ())}
    baseline = diff_releases({}, after, "2026-11-09", baseline=True)
    assert [(c["date"], c["version"]) for c in baseline] == [("2026-01-02", "17.12.4")]


def test_support_dates():
    releases = [{"name": f"17.{n}", "releaseDate": "2023-07-28", "eoasFrom": "2026-03-30", "eolFrom": "2027-09-30", "isLts": n == 12}
                for n in range(12, 18)]
    product = parse_product({"result": {"releases": releases, "links": {"html": "h", "releasePolicy": "p"}}})
    assert product["branches"]["17.12"] == {"released": "2023-07-28", "maintenance": "2026-03-30", "support": "2027-09-30", "lts": True}
    dates = branch_lifecycle("iosxe", ["16.9", "17.12", "26.1"], product)
    assert dates["16.9"] == {"listed": False, "newer": False}
    assert dates["26.1"] == {"listed": False, "newer": True}
    assert dates["17.12"]["listed"] and dates["17.12"]["lts"]


def test_caption_inside_the_table():
    html = page(
        "<h2>Resolved and Open Bugs for Cisco IOS XE 17.12.7b</h2>"
        "<table><caption>Table 4. Resolved Bugs for Cisco IOS XE 17.12.7b</caption><tr><th>Identifier</th><th>Headline</th></tr>"
        "<tr><td>CSCwr83968</td><td>Unexpected reload with static NAT</td></tr></table>"
        "<table><caption>Table 5. Open Bugs for Cisco IOS XE 17.12.7b</caption><tr><th>Identifier</th><th>Headline</th></tr>"
        "<tr><td>CSCws33718</td><td>Unicast packets dropped</td></tr></table>",
        "Release Notes for Cisco Catalyst 8500, Cisco IOS XE 17.12.x")
    document = parse_document([(URL, html)], "iosxe")
    assert {(o["bug_id"], o["status"]) for o in document.observations} == {("CSCwr83968", "resolved"), ("CSCws33718", "open")}


def test_release_dates_table():
    html = page(table(("7.6.7", "", ""), ("7.6.6", "115", "2026-09-15"), header=("Version", "Build", "Date"))
                + "<h3>Resolved Bugs in Version 7.6.6</h3>" + table(("CSCwr00001", "Crash")),
                "Cisco Secure Firewall Threat Defense Release Notes, Version 7.6.x")
    assert parse_document([(URL, html)], "ftd").released == {"7.6.6": "2026-09-15"}
