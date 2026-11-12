"use strict";
const test = require("node:test");
const assert = require("node:assert");
const logic = require("../../site/logic.js");

// 17.12.3, 17.12.3a, 17.12.4, 17.12.5 on one branch, then 17.15.1 on another.
const versions = [
  { v: "17.12.3", branch: "17.12", train: "17.12#3", rebuild: false },
  { v: "17.12.3a", branch: "17.12", train: "17.12#3", rebuild: true },
  { v: "17.12.4", branch: "17.12", train: "17.12#4", rebuild: false },
  { v: "17.12.5", branch: "17.12", train: "17.12#5", rebuild: false },
  { v: "17.15.1", branch: "17.15", train: "17.15#1", rebuild: false },
].map((entry, i) => ({ ...entry, i, support: { supported: entry.branch === "17.15" } }));
const families = ["Catalyst 9300", "ISR 4000"];
const modelFamilies = new Map([["C9300X", 0], ["ISR4451", 1]]);

test("status follows the notes of the branch", () => {
  const bug = { events: [[0, "k"], [2, "r"]] };
  assert.strictEqual(logic.statusAt(bug, 0, versions).key, "affected");
  assert.strictEqual(logic.statusAt(bug, 1, versions).key, "potential");
  assert.strictEqual(logic.statusAt(bug, 2, versions).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, 3, versions).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, 4, versions).key, "unknown");
});

test("a fix in a rebuild only covers its own maintenance release", () => {
  const bug = { events: [[1, "r"]] };
  assert.strictEqual(logic.statusAt(bug, 1, versions).key, "fixed");
  assert.strictEqual(logic.statusAt(bug, 2, versions).key, "unknown");
  assert.strictEqual(logic.statusAt(bug, 0, versions).key, "potential");
  assert.deepStrictEqual(logic.firstFixes([[1, "r"], [2, "r"]], versions), [2, 1]);
  assert.deepStrictEqual(logic.firstFixes([[0, "r"], [1, "r"]], versions), [0]);
});

test("active branches of a bug", () => {
  assert.deepStrictEqual(logic.supportedBranches([[0, "k"], [4, "r"]], versions), ["17.15"]);
  assert.deepStrictEqual(logic.branchSupport("17.15", { "17.15": { active: true, activity: "2026-10-01" } }), { supported: true, activity: "2026-10-01" });
  assert.deepStrictEqual(logic.branchSupport("16.9", {}), { supported: false, activity: null });
  const dated = { "17.12": { listed: true, support: "2027-09-30", maintenance: "2026-03-30", lts: true }, "17.14": { listed: true, support: "2025-05-31" }, "16.9": { listed: false, newer: false }, "26.2": { listed: false, newer: true } };
  const on = (branch) => logic.branchSupport(branch, dated, true, "2026-11-09");
  assert.strictEqual(on("17.12").supported, true);
  assert.strictEqual(on("17.12").maintained, false);
  assert.strictEqual(on("17.14").supported, false);
  assert.strictEqual(on("16.9").supported, false);
  assert.strictEqual(on("26.2").supported, true);
});

test("hardware filter keeps the family bugs naming no model", () => {
  const cited = { models: ["C9300X"], families: [0] };
  const other = { models: ["C9300L"], families: [0] };
  const family = { models: [], families: [0] };
  const elsewhere = { models: [], families: [1] };
  const others = new Map([...modelFamilies, ["C9300L", 0]]);
  assert.strictEqual(logic.hardwareMatch(cited, "m:C9300X", families, others), "cited");
  assert.strictEqual(logic.hardwareMatch(other, "m:C9300X", families, others), null);
  assert.strictEqual(logic.hardwareMatch(family, "m:C9300X", families, others), "family");
  assert.strictEqual(logic.hardwareMatch(elsewhere, "m:C9300X", families, others), null);
  assert.strictEqual(logic.hardwareMatch(other, "f:Catalyst 9300", families, others), "family");
  assert.strictEqual(logic.selectedFamily("m:ISR4451", families, modelFamilies), 1);
});

test("a bug ID is found whatever its case", () => {
  const bug = { key: "cscwu11498", text: "cscwu11498 show interface counter" };
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("CSCwu11498")));
  assert.ok(logic.matchesTerms(bug, logic.searchTerms("cscwu11498, counter")));
  assert.ok(!logic.matchesTerms(bug, logic.searchTerms("CSCwu11499")));
});

test("an upgrade sorts the bugs", () => {
  assert.strictEqual(logic.upgradeGroup({ events: [[0, "k"], [2, "r"]] }, 0, 3, versions), "gained");
  assert.strictEqual(logic.upgradeGroup({ events: [[3, "k"]] }, 0, 3, versions), "introduced");
  assert.strictEqual(logic.upgradeGroup({ events: [[0, "k"], [3, "k"]] }, 0, 3, versions), "remaining");
  // Open in 17.12.4, crossed on the way to 17.12.5, never listed again nor fixed.
  assert.strictEqual(logic.upgradeGroup({ events: [[2, "k"]] }, 0, 3, versions), "unresolved");
  // Open in the current release, not listed in the target.
  assert.strictEqual(logic.upgradeGroup({ events: [[0, "k"]] }, 0, 3, versions), "unresolved");
  // Open on the way, then fixed by the target.
  assert.strictEqual(logic.upgradeGroup({ events: [[2, "k"], [3, "r"]] }, 0, 3, versions), "gained");
});

test("links point to the exact page and row", () => {
  const document = { url: "https://www.cisco.com/a.html", pages: ["https://www.cisco.com/a.html", "https://www.cisco.com/a/caveats.html"] };
  assert.strictEqual(logic.officialUrl(document, 1, "CSCwu11498"), "https://www.cisco.com/a/caveats.html#:~:text=CSCwu11498");
  assert.strictEqual(logic.officialUrl(document), "https://www.cisco.com/a.html");
});

test("upgrade notices follow the selected family", () => {
  const documents = [{ families: [0] }, { families: [1] }];
  const notices = [[["Upgrading the Switch Software", "u1"]], [["Upgrade ROMMON", "u2"], ["upgrade rommon", "u2"]]];
  const withDocs = versions.map((entry) => ({ ...entry, docs: [0, 1] }));
  assert.deepStrictEqual(logic.upgradeNotices(notices, withDocs, documents, 3, 1).map((n) => n.title), ["Upgrade ROMMON"]);
  assert.strictEqual(logic.upgradeNotices(notices, withDocs, documents, 3).length, 2);
});

test("copied tables are tab-separated", () => {
  assert.strictEqual(logic.tableText([["a b", null], ["c\nd", 1]]), "a b\t\nc d\t1");
});

test("a Cisco model is stopped once its software maintenance is over", () => {
  const entry = { eol: [[["N9K-C9372PX"], "c51-739451", null, "2023-02-28", "p", "2019-02-03"]], suggested: [] };
  assert.strictEqual(logic.hardwareStatus(entry, "2026-11-12").key, "stopped");
  const later = { eol: [[["C9300-24T"], "c51-1", null, "2031-01-31", "p", "2028-01-31"]], suggested: [] };
  assert.strictEqual(logic.hardwareStatus(later, "2026-11-12").key, "announced");
  assert.strictEqual(logic.hardwareStatus({ eol: [], suggested: [] }, "2026-11-12").key, "none");
});
