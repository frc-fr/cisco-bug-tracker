"use strict";
// What the site concludes from the notes, kept apart from the page so it can be tested.

/** The release as Cisco writes it. */
function nameOf(entry) {
  return entry.v;
}

/**
 * Whether a fix in one release is in another of the same branch. A maintenance
 * release carries the fixes of the earlier releases of its branch; a rebuild only
 * those of its own maintenance release: 17.12.3a is in 17.12.3b, and nothing says
 * it is in 17.12.4. Entries are in release order, `i` being their position.
 */
function covers(fix, target) {
  if (fix.branch !== target.branch) return false;
  if (!fix.rebuild) return fix.i <= target.i;
  return fix.train === target.train && fix.i <= target.i;
}

/** Status of a bug on one release, from what the notes of its branch say. */
function statusAt(bug, index, versions) {
  const target = versions[index];
  const own = bug.events.filter(([v]) => versions[v].branch === target.branch);
  if (own.some(([v, status]) => v === index && status !== "r")) return { key: "affected" };

  const fixed = own.find(([v, status]) => status === "r" && covers(versions[v], target));
  if (fixed) return { key: "fixed", detail: { id: "fixedSince", version: nameOf(versions[fixed[0]]) } };

  // Open in the release a rebuild derives from, with no fix documented on the way.
  // Only for a rebuild: a maintenance note that drops an open issue may have fixed it silently.
  const inherited = target.rebuild && [...own].reverse().find(([v, status]) => status !== "r" && v !== index && covers(versions[v], target));
  if (inherited) return { key: "potential", detail: { id: "openSince", version: nameOf(versions[inherited[0]]) } };

  const fixedLater = own.find(([v, status]) => status === "r" && v > index);
  if (fixedLater) return { key: "potential", detail: { id: "fixedIn", version: nameOf(versions[fixedLater[0]]) } };

  const knownLater = own.find(([v]) => v > index);
  if (knownLater) return { key: "potential", detail: { id: "knownIn", version: nameOf(versions[knownLater[0]]) } };

  if (own.length) {
    const last = own[own.length - 1][0];
    return { key: "unknown", detail: { id: "dropped", version: nameOf(versions[last]) } };
  }
  return { key: "unknown", detail: { id: "noMention" } };
}

/** The first fix of each maintenance release, newest first, as positions in the list of releases. */
function firstFixes(events, versions) {
  const found = new Map();
  for (const [v, status] of events) {
    if (status !== "r") continue;
    const { train } = versions[v];
    if (!found.has(train)) found.set(train, v);
  }
  // A fix in a maintenance release already covers the later releases of its branch.
  const kept = [...found.values()].filter((v) => ![...found.values()].some((other) => other !== v && !versions[other].rebuild && covers(versions[other], versions[v])));
  return kept.sort((a, b) => b - a);
}

/**
 * Support of a branch on a date. With support dates (IOS XE, from endoflife.date): supported
 * until the end of security support; a branch missing from the table ended if it is older than
 * those listed, and is not dated yet if newer. Without dates: active when one of its notes was
 * revised in the last year.
 */
function branchSupport(branch, branches, dated = false, today = "") {
  const entry = branches[branch] || {};
  const activity = entry.activity || null;
  if (!dated) return { supported: Boolean(entry.active), activity };
  if (!entry.listed) return { supported: Boolean(entry.newer), activity, dated };
  return {
    supported: !entry.support || today <= entry.support, activity, dated,
    support: entry.support, maintenance: entry.maintenance, lts: entry.lts,
    maintained: !entry.maintenance || today <= entry.maintenance,
  };
}

/** Active branches where the notes mention a bug, newest first. */
function supportedBranches(events, versions) {
  const found = new Map();
  for (const [version] of events) {
    const entry = versions[version];
    if (entry.support.supported) found.set(entry.branch, Math.max(found.get(entry.branch) ?? -1, version));
  }
  return [...found.entries()].sort((a, b) => b[1] - a[1]).map(([branch]) => branch);
}

/**
 * Inclusive filter. The selection is "f:<family>" or "m:<model>".
 * "cited": the headline names the model. "family": the bug is in a note of the
 * family, or the headline names it, without naming one of its models.
 */
function hardwareMatch(bug, selection, families, modelFamilies) {
  if (!selection) return "all";
  const kind = selection.slice(0, 1);
  const name = selection.slice(2);
  const family = kind === "f" ? families.indexOf(name) : modelFamilies.get(name);
  if (kind === "f") return bug.families.includes(family) ? "family" : null;
  if (bug.models.includes(name)) return "cited";
  if (bug.models.some((model) => modelFamilies.get(model) === family)) return null;
  return bug.families.includes(family) ? "family" : null;
}

/** Family of a selection, as a position in the list of families, or -1. */
function selectedFamily(selection, families, modelFamilies) {
  if (!selection) return -1;
  const name = selection.slice(2);
  if (selection.startsWith("f:")) return families.indexOf(name);
  return modelFamilies.has(name) ? modelFamilies.get(name) : -1;
}

function searchTerms(query) {
  return query.toLowerCase().split(/[\s,;]+/).filter(Boolean);
}

const BUG_TERM = /^csc[a-z]{2}\d{5}$/;

function isBugTerm(term) {
  return BUG_TERM.test(term);
}

function matchesTerms(bug, terms) {
  return terms.every((term) => (isBugTerm(term) ? bug.key === term : bug.text.includes(term)));
}

/**
 * What an upgrade does to a bug. Cisco lists the open bugs of a release in its own
 * section only, and seldom lists them again in the next releases: a bug open in the
 * current release, or in a release crossed on the way, with no documented fix by
 * the target, is "unresolved" rather than ignored.
 */
function upgradeGroup(bug, from, to, versions) {
  const before = statusAt(bug, from, versions).key;
  const after = statusAt(bug, to, versions).key;
  if (after === "fixed" && before !== "fixed") return "gained";
  if (after === "affected") return before === "affected" ? "remaining" : "introduced";
  if (after === "fixed") return null;
  const branch = versions[to].branch;
  const openOnTheWay = bug.events.some(([v, status]) => status !== "r" && v > from && v < to && versions[v].branch === branch);
  return before === "affected" || openOnTheWay ? "unresolved" : null;
}

/** Sections to read before an upgrade, from the notes of the target release, for the selected family or all. */
function upgradeNotices(notices, versions, documents, to, family = -1) {
  const seen = new Set();
  return versions[to].docs
    .filter((doc) => family < 0 || documents[doc].families.includes(family))
    .flatMap((doc) => (notices[doc] || []).map(([title, url]) => ({ doc, title, url })))
    .filter(({ doc, title }) => {
      const key = `${doc} ${title.toLowerCase()}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

/** Per model: the bugs whose headline names it, and the first and last releases where they appear. */
function modelSummaries(models, bugs, versions) {
  const summaries = new Map(models.map(([model, family]) => [model, { model, family, count: 0, first: Infinity, last: -1 }]));
  for (const bug of bugs) {
    for (const model of bug.models) {
      const summary = summaries.get(model);
      if (!summary) continue;
      summary.count += 1;
      for (const [version] of bug.events) {
        summary.first = Math.min(summary.first, version);
        summary.last = Math.max(summary.last, version);
      }
    }
  }
  return [...summaries.values()].filter((summary) => summary.count && summary.last >= 0).map((summary) => ({
    ...summary, first: nameOf(versions[summary.first]), last: nameOf(versions[summary.last]),
  }));
}

/**
 * Link to the page of a note holding a fact. With a bug ID, a text fragment
 * scrolls to its row and highlights it in the browsers that support it.
 */
function officialUrl(document, page = 0, bug = null) {
  const url = document.pages[page] || document.url;
  return bug ? `${url}#:~:text=${bug}` : url;
}

/** Tab-separated text, which spreadsheets and mail clients paste as a table. */
function tableText(rows) {
  return rows.map((row) => row.map((cell) => String(cell ?? "").replace(/\s+/g, " ").trim()).join("\t")).join("\n");
}

if (typeof module !== "undefined") {
  module.exports = {
    nameOf, covers, firstFixes, statusAt, branchSupport, supportedBranches, hardwareMatch, selectedFamily, searchTerms, isBugTerm,
    matchesTerms, upgradeGroup, upgradeNotices, modelSummaries, officialUrl, tableText,
  };
}
