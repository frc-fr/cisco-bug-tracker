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


def test_an_etag_seen_before_means_unchanged(tmp_path, monkeypatch):
    """Cisco's servers answer with different ETags for the same PDF: none of those seen triggers a download."""
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"listings": [], "exclude": "x^", "documents": [], "seeds": []}')
    url = "https://www.cisco.com/c/en/us/td/docs/a/notes.html"
    manifest = tmp_path / "manifest.json"
    entry = {"url": url, "system": "iosxe", "families": ["ISR 4000"], "chapters": [], "revised": "2026-10-05",
             "etag": "8c0fd-6406e3384ad3e"}
    collect.save_manifest(manifest, {collect.document_key(url): entry})
    # Copies of 2025-09-25, 2026-10-05 (the one known) and 2025-07-22: none newer than the one known.
    answers = iter(["8c0fd-63fa0bd001c20", "8c0fd-6406e3384ad3e", "c-63a7f398a8da6", "9-65cbe4add47e2"])
    downloads = []
    monkeypatch.setattr(collect, "pdf_state", lambda client, u: next(answers))
    monkeypatch.setattr(collect, "download_document", lambda client, e, folder: downloads.append(e["url"]) or True)
    for _ in range(3):
        collect.update(manifest, catalog, tmp_path / "cache", None, datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert downloads == []
    assert collect.load_manifest(manifest)[collect.document_key(url)]["revised"] == "2026-10-05"
    # A copy of 2026-10-01 is older too.
    collect.update(manifest, catalog, tmp_path / "cache", None, datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert downloads == []
    # A revision of the note gives a newer copy, of 2026-11-11: it is read.
    answers = iter(["9-6600000000000"])
    collect.update(manifest, catalog, tmp_path / "cache", None, datetime(2026, 11, 9, tzinfo=timezone.utc))
    assert downloads == [url]
    assert collect.load_manifest(manifest)[collect.document_key(url)]["revised"] == "2026-11-11"


from ciscobugs.hardware import chassis_name, chassis_of, hardware_index, listing_bulletins, parse_bulletin, worth_reading


def test_bulletin_keeps_hardware_milestones_and_chassis():
    page = (
        "<table><tr><th>Milestone</th><th>Definition</th><th>Date</th></tr>"
        "<tr><td>End-of-Sale Date: HW</td><td>x</td><td>February 3, 2018</td></tr>"
        "<tr><td>End of SW Maintenance Releases Date: HW</td><td>x</td><td>February 3, 2019</td></tr>"
        "<tr><td>Last Date of Support: HW</td><td>x</td><td>February 28, 2023</td></tr></table>"
        "<table><tr><th>End-of-Sale Product Part Number</th><th>Product Description</th></tr>"
        "<tr><td>N9K-C9372PX</td><td>Nexus 9300 with 48p 10G SFP+ and 6p 40G QSFP+</td></tr>"
        "<tr><td>N9K-C9372PX=</td><td>Nexus 9K, Spare</td></tr>"
        "<tr><td>C1-N9K-C9372PX</td><td>Cisco ONE Nexus 9300</td></tr>"
        "<tr><td>N9K-C9372PX-BUN</td><td>Nexus 9372PX bundle PID</td></tr>"
        "<tr><td>NXA-FAN-30CFM-F</td><td>Nexus fan, port side intake</td></tr></table>"
    )
    bulletin = parse_bulletin(page)
    assert {k: v for k, v in bulletin.items() if k != "parts"} == {
        "hardware": True, "end_of_sale": "2018-02-03", "end_of_maintenance": "2019-02-03", "end_of_support": "2023-02-28"}
    assert len(bulletin["parts"]) == 5 and chassis_of(bulletin) == [("N9K-C9372PX", "N9K-C9372PX")]
    software = "<table><tr><th>Milestone</th></tr><tr><td>Last Date of Support: OS SW</td><td>x</td><td>May 1, 2020</td></tr></table>"
    assert parse_bulletin(software) == {"hardware": False}
    assert chassis_name("ASA5515-K9", "ASA 5515-X with SW, 6GE Data, 1GE Mgmt, AC, 3DES/AES") == ("ASA5515", "ASA5515")
    assert chassis_name("C9300-24T", "Catalyst 9300 24-port data only") == ("C9300", "C9300-24T")
    assert chassis_name("EDU-C2960X-24PD-L", "Catalyst 2960-X 24 GigE, EDU") is None
    assert chassis_name("N9K-X9736PQ", "Nexus 9500 linecard") is None
    assert chassis_name("ASA5545-2SSD120", "ASA 5545-X IPS SSD 120GB") is None
    assert chassis_name("WS-C2960X-24PD-L++", "Catalyst 2960-X 24 GigE PoE 370W") == ("WS-C2960X", "WS-C2960X-24PD-L")
    assert chassis_name("ASR1000-ESP20", "Cisco ASR1000 Embedded Services Processor, 20G") is None
    assert chassis_name("ASR-9912-SFC110", "ASR 9912 Fabric Card") is None
    assert chassis_name("A9K-24X10GE-SE", "ASR 9000 24-port 10GE Service Edge Optimized LC") is None


def test_listing_and_titles():
    page = ('<a href="/c/en/us/products/collateral/x/eos-eol-notice-c51-739451.html">EoS for the Nexus 9372PX Switches</a>'
            '<a href="/c/en/us/products/collateral/x/eos-eol-notice-c51-739451-fr.html">Annonce</a>')
    assert listing_bulletins(page, "https://www.cisco.com/a/b.html") == {
        "https://www.cisco.com/c/en/us/products/collateral/x/eos-eol-notice-c51-739451.html":
            {"bulletin": "c51-739451", "title": "EoS for the Nexus 9372PX Switches"}}
    assert not worth_reading("End-of-Sale and End-of-Life Announcement for the Cisco IOS XE 16.9.x")
    assert worth_reading("End-of-Sale and End-of-Life Announcement for the Cisco Catalyst 3850 switches")


def test_chassis_go_under_the_model_the_notes_cite():
    state = {"listings": [], "bulletins": [
        {"url": "u", "bulletin": "c51-1", "families": ["Nexus 9000"], "hardware": True, "end_of_sale": None,
         "end_of_maintenance": "2019-02-03", "end_of_support": "2023-02-28",
         "parts": [["N9K-C9372PX", "Nexus 9300 with 48p 10G SFP+"], ["N9K-C9396TX", "Nexus 9300 with 48p 1/10G-T"]]},
        {"url": "v", "bulletin": "c51-2", "families": ["Catalyst 9300"], "hardware": True, "end_of_sale": None,
         "end_of_maintenance": None, "end_of_support": None, "parts": [["C9300-24T", "Catalyst 9300 24-port"]]},
    ]}
    index = hardware_index(["Nexus 9000"], ["N9K-9372PX"], state)
    assert list(index["models"]) == ["N9K-9372PX", "N9K-C9396TX"]
    assert index["models"]["N9K-9372PX"]["eol"] == [[["N9K-C9372PX"], "c51-1", None, "2023-02-28", "u", "2019-02-03"]]
    assert index["models"]["N9K-C9396TX"]["family"] == "Nexus 9000"


from ciscobugs.lifecycle import parse_announcement, parse_ftd, parse_nxos, platform_models
from ciscobugs.build import branch_lifecycle


def test_nxos_lifecycle_table():
    page = ("<table><tr><th>NX-OS Major Release</th><th>EoSWM Date</th><th>EoVSS/LDoS</th></tr>"
            "<tr><td>10.2(x)</td><td>Nov 30 2023</td><td>Feb 28 2025/Aug 31 2025</td></tr>"
            "<tr><td>10.3(x)</td><td>Nov 30 2024</td><td>Feb 28 2027 *</td></tr>"
            "<tr><td>10.5(x)</td><td>Feb 28 2027</td><td>Feb 28 2029</td></tr></table>")
    branches = parse_nxos(page)
    assert branches["10.2"]["support"] == "2025-08-31" and branches["10.3"]["support"] == "2027-02-28"
    assert branches["10.5"]["maintenance"] == "2027-02-28"


def test_ftd_guide_tables():
    rows = "".join(f"<tr><td>{v}</td><td>2025-11-18</td><td>2026-11-18</td><td>{s}</td><td>x</td></tr>"
                   for v, s in [("7.3", "2027-11-30"), ("7.2", "2027-11-30"), ("6.2.3", "2025-02-28"), ("6.2", "2022-03-31"), ("7.0", "2027-11-30"), ("7.7", "2028-09-30")])
    platforms = ("<table><tr><th>Platform</th><th>Last device version</th><th>Last Mgmt. Center</th><th>End of sale</th><th>End of support</th></tr>"
                 "<tr><td>Firepower 2110, 2120</td><td>7.4</td><td>TBD</td><td>2025-05-27</td><td>2030-05-31</td></tr>"
                 "<tr><td>2022-01-31</td><td>2027-01-31</td><td>Subscriptions</td></tr>"
                 "<tr><td>Firepower 9300: SM-24, SM-36 modules</td><td>7.2</td><td>7.7</td><td>2024-08-31</td><td>2025-08-31</td></tr>"
                 "<tr><td>ASA 5506-X, 5506H-X</td><td>6.2.3</td><td>6.6</td><td>2021-08-02</td><td>2026-08-31</td></tr></table>")
    parsed = parse_ftd("<table><tr><th>Version</th><th>End of sale</th><th>End of updates</th><th>End of support</th></tr>"
                       + rows + "</table>" + platforms)
    assert parsed["branches"]["6.2"]["support"] == "2025-02-28" and parsed["branches"]["7.3"]["maintenance"] == "2026-11-18"
    assert parsed["platforms"]["FPR2110"]["last"] == "7.4" and parsed["platforms"]["ASA5506"]["last"] == "6.2"
    assert "FPR9300" not in parsed["platforms"]
    assert platform_models("ASA 5525-X, 5545-X, 5555-X") == ["ASA5525", "ASA5545", "ASA5555"]


def test_announcement_milestones():
    page = ("<table><tr><th>Milestone</th><th>Definition</th><th>Date</th></tr>"
            "<tr><td>End-of-Sale Date: OS SW</td><td>x</td><td>September 30, 2026</td></tr>"
            "<tr><td>End of SW Maintenance Releases Date: OS SW</td><td>x</td><td>March 31, 2027</td></tr>"
            "<tr><td>Last Date of Support: OS SW</td><td>x</td><td>September 30, 2029</td></tr></table>")
    assert parse_announcement(page) == {"sale": "2026-09-30", "maintenance": "2027-03-31", "support": "2029-09-30"}


def test_a_branch_not_announced_yet_is_still_supported():
    announced = {"complete": False, "branches": {"7.3": {"support": "2027-11-30"}, "7.7": {"support": "2028-09-30"}}}
    found = branch_lifecycle("ftd", ["6.4", "7.4", "7.6", "7.7"], announced)
    assert found["7.4"] == {"listed": False, "newer": True} and found["6.4"] == {"listed": False, "newer": False}
    table = {"branches": {"10.4": {"support": "2028-02-29"}, "10.6": {"support": "2030-02-28"}}}
    assert branch_lifecycle("nxos", ["10.5"], table)["10.5"]["newer"] is False
