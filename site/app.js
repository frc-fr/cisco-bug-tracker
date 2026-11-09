"use strict";

const PAGE_SIZE = 100;
const SYSTEMS = { iosxe: "IOS XE", ios: "IOS", iosxr: "IOS XR", nxos: "NX-OS", asa: "ASA", ftd: "FTD" };
const DEFAULT_SYSTEM = "iosxe";
const KNOWN_LABELS = { k: t("known.k"), l: t("known.l"), r: t("status.fixed") };
const STATUSES = {
  affected: t("status.affected"),
  potential: t("status.potential"),
  fixed: t("status.fixed"),
  unknown: t("status.unknown"),
};
const SCOPES = {
  all: { label: t("scope.all"), tone: "all" },
  supported: { label: t("scope.supported"), tone: "fixed" },
  ended: { label: t("scope.ended"), tone: "unknown" },
};
const SCOPES_DATED = {
  all: { label: t("scope.all"), tone: "all" },
  supported: { label: t("scope.supportedDated"), tone: "fixed" },
  ended: { label: t("scope.endedDated"), tone: "unknown" },
};
// Riskiest first: what an upgrade brings or leaves matters more than what it fixes.
const UPGRADE_GROUPS = {
  all: { label: t("group.all"), tone: "all" },
  introduced: { label: t("group.introduced"), tone: "affected" },
  remaining: { label: t("group.remaining"), tone: "potential" },
  unresolved: { label: t("group.unresolved"), tone: "potential" },
  gained: { label: t("group.gained"), tone: "fixed" },
};

const $ = (id) => document.getElementById(id);
const defaultFilters = () => ({
  query: "", version: "", from: "", model: "",
  hidden: new Set(["unknown"]), group: "all", scope: "all",
});
const system = (() => {
  const wanted = new URLSearchParams(location.hash.slice(1)).get("system");
  return wanted in SYSTEMS ? wanted : DEFAULT_SYSTEM;
})();
const systemName = SYSTEMS[system];
const state = { view: "bugs", shown: PAGE_SIZE, reading: false, ...defaultFilters() };
let versions = [];
let families = [];
let models = [];
let modelFamilies = new Map();
let documents = [];
let bugs = [];
let changes = [];
let summaries = [];
let branches = {};
let lifecycle = null;
let knownIds = {};
// Whether the site can tell anything about the support of the branches: dates, or notes dated.
let supportKnown = false;
let notices = {};
let copiedTable = () => [];
let updated = "";
let schedule = null;
let searchTimer;
const combos = {};

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const formatNumber = (n) => n.toLocaleString(locale);
const formatDate = (iso) => iso.split("-").reverse().join("/");

/** Text field that filters a list of options as you type. */
class Combobox {
  constructor(root, onChange) {
    this.onChange = onChange;
    this.options = [];
    this.current = "";
    this.visible = [];
    this.active = -1;
    this.input = document.createElement("input");
    this.input.id = `${root.id}-input`;
    this.input.type = "text";
    this.input.autocomplete = "off";
    this.input.spellcheck = false;
    this.input.setAttribute("role", "combobox");
    this.input.setAttribute("aria-autocomplete", "list");
    this.input.setAttribute("aria-expanded", "false");
    this.input.setAttribute("aria-controls", `${root.id}-list`);
    this.list = document.createElement("ul");
    this.list.id = `${root.id}-list`;
    this.list.className = "combo-list";
    this.list.setAttribute("role", "listbox");
    this.list.hidden = true;
    root.append(this.input, this.list);

    this.input.addEventListener("focus", () => { this.open(""); this.input.select(); });
    this.input.addEventListener("click", () => {
      if (this.list.hidden) this.open("");
      // Deferred: a click on selected text collapses the selection after this event.
      setTimeout(() => {
        if (this.input.value === this.label()) this.input.select();
      });
    });
    this.input.addEventListener("input", () => this.open(this.input.value));
    this.input.addEventListener("blur", () => this.close());
    this.input.addEventListener("keydown", (event) => this.onKey(event));
    // mousedown, not click: the field must not lose focus before the choice is made.
    this.list.addEventListener("mousedown", (event) => {
      event.preventDefault();
      const option = event.target.closest("[data-index]");
      if (option) this.choose(this.visible[Number(option.dataset.index)]);
    });
  }

  setOptions(options) {
    this.options = options;
    this.value = this.current;
  }

  get value() {
    return this.current;
  }

  set value(value) {
    this.current = value;
    this.input.value = this.label();
  }

  label() {
    const option = this.options.find((entry) => entry.value === this.current);
    return option ? option.label : "";
  }

  open(text) {
    const terms = text.toLowerCase().split(/\s+/).filter(Boolean);
    this.visible = this.options.filter((option) => {
      const label = `${option.label} ${option.group || ""}`.toLowerCase();
      return terms.every((term) => label.includes(term));
    });
    const selected = this.visible.findIndex((option) => option.value === this.current);
    this.active = terms.length ? 0 : Math.max(selected, 0);
    this.renderList();
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
    this.scrollToActive();
  }

  close() {
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.value = this.current;
    // Still focused after Escape or a choice: typing must replace the label.
    if (document.activeElement === this.input) this.input.select();
  }

  choose(option) {
    const changed = option.value !== this.current;
    this.current = option.value;
    this.close();
    if (changed) this.onChange(option.value);
  }

  onKey(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (this.list.hidden) {
        this.open("");
      } else if (this.visible.length) {
        const step = event.key === "ArrowDown" ? 1 : -1;
        this.active = (this.active + step + this.visible.length) % this.visible.length;
        this.renderList();
        this.scrollToActive();
      }
    } else if (event.key === "Enter" && !this.list.hidden) {
      event.preventDefault();
      if (this.visible[this.active]) this.choose(this.visible[this.active]);
    } else if (event.key === "Escape") {
      this.close();
    }
  }

  renderList() {
    let group = null;
    const items = [];
    this.visible.forEach((option, index) => {
      const tone = option.tone ? ` ${option.tone}` : "";
      if (option.group && option.group !== group) {
        group = option.group;
        items.push(`<li class="combo-group${tone}" role="presentation">${escapeHtml(group)}</li>`);
      }
      const classes = `combo-option${tone}${index === this.active ? " active" : ""}`;
      items.push(`<li id="${this.list.id}-${index}" class="${classes}" role="option" data-index="${index}" aria-selected="${option.value === this.current}">${escapeHtml(option.label)}</li>`);
    });
    this.list.innerHTML = items.join("") || `<li class="combo-empty">${t("filter.noResult")}</li>`;
  }

  scrollToActive() {
    const option = this.list.querySelector(".active");
    if (!option) return;
    option.scrollIntoView({ block: "nearest" });
    this.input.setAttribute("aria-activedescendant", option.id);
  }
}

function hydrate(row) {
  const [id, description, cited, familyList, events, elsewhere = []] = row;
  const fixes = firstFixes(events, versions);
  const text = `${id} ${description} ${cited.join(" ")}`.toLowerCase();
  const supported = supportedBranches(events, versions);
  return { id, key: id.toLowerCase(), description, models: cited, families: familyList, events, fixes, text, supported, elsewhere };
}

/** The branch filter only makes sense on a search across all the releases. */
function scopeApplies() {
  return state.view === "bugs" && !state.version && supportKnown;
}

function versionIndex(value) {
  return value === "" ? -1 : versions.findIndex((entry) => entry.v === value);
}

function compute() {
  const terms = searchTerms(state.query);
  const version = versionIndex(state.version);
  const from = versionIndex(state.from);
  const upgrade = state.view === "upgrade" && version >= 0 && from >= 0;
  const scoped = scopeApplies();
  const counts = {};
  const rows = [];

  if (state.view === "upgrade" && !upgrade) return { rows, counts };
  for (const bug of bugs) {
    if (!matchesTerms(bug, terms)) continue;
    const hardware = hardwareMatch(bug, state.model, families, modelFamilies);
    if (!hardware) continue;

    if (scoped) {
      const scope = bug.supported.length ? "supported" : "ended";
      counts[scope] = (counts[scope] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.scope !== "all" && scope !== state.scope) continue;
    }
    const status = version >= 0 ? statusAt(bug, version, versions) : null;
    if (upgrade) {
      const group = upgradeGroup(bug, from, version, versions);
      if (!group) continue;
      counts[group] = (counts[group] || 0) + 1;
      counts.all = (counts.all || 0) + 1;
      if (state.group !== "all" && group !== state.group) continue;
      rows.push({ bug, status, hardware, group });
      continue;
    } else if (status) {
      counts[status.key] = (counts[status.key] || 0) + 1;
      // A bug searched by its ID stays listed, whatever its status: hiding it would look like "not found".
      if (state.hidden.has(status.key) && !terms.some(isBugTerm)) continue;
    }
    rows.push({ bug, status, hardware });
  }
  const risk = Object.keys(UPGRADE_GROUPS);
  const cited = (row) => (row.hardware === "cited" ? 0 : 1);
  const ended = (row) => (scoped && !row.bug.supported.length ? 1 : 0);
  rows.sort((a, b) => risk.indexOf(a.group) - risk.indexOf(b.group)
    || (state.model ? cited(a) - cited(b) : 0) || ended(a) - ended(b));
  return { rows, counts };
}

function officialLink(doc, page, label, bug = null) {
  const url = officialUrl(documents[doc], page, bug);
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${label}</a>`;
}

/** The notes of a release, named by their families. */
function noteName(doc) {
  return documents[doc].families.map((position) => families[position]).join(", ");
}

function highlight(text, terms) {
  const words = terms.filter((term) => !isBugTerm(term)).map(escapeRegExp);
  const safe = escapeHtml(text);
  if (!words.length) return safe;
  return safe.replace(new RegExp(`(${words.map((w) => escapeHtml(w)).join("|")})`, "gi"), "<mark>$1</mark>");
}

function releaseLabel(entry) {
  return nameOf(entry);
}

function fixesLabel(bug) {
  const labels = bug.fixes.map((version) => releaseLabel(versions[version]));
  if (labels.length) return t("bug.fixedIn", { versions: labels.join(", ") });
  const other = bug.elsewhere.filter(([, , status]) => status === "r").map(([key, version]) => `${SYSTEMS[key]} ${version}`);
  return other.length ? t("bug.fixedElsewhere", { system: systemName, versions: other.slice(0, 4).join(", ") + (other.length > 4 ? "…" : "") }) : t("bug.noFix");
}

/** What the notes of the other systems say of the bug, linked to its search there. */
function renderElsewhere(bug) {
  if (!bug.elsewhere.length) return "";
  const bySystem = new Map();
  for (const [key, version, status] of bug.elsewhere) {
    if (!bySystem.has(key)) bySystem.set(key, []);
    bySystem.get(key).push(`${escapeHtml(version)} : ${KNOWN_LABELS[status].toLowerCase()}`);
  }
  const lines = [...bySystem].map(([key, facts]) => {
    const link = new URLSearchParams({ system: key, query: bug.id });
    if (language === "en") link.set("lang", "en");
    return `<dt><a href="#${escapeHtml(link.toString())}">${escapeHtml(SYSTEMS[key])}</a></dt><dd>${facts.join(", ")}</dd>`;
  });
  return `<h3>${t("bug.elsewhere")}</h3><dl class="history">${lines.join("")}</dl><p class="note">${t("bug.elsewhereNote")}</p>`;
}

function hardwareTags(bug, hardware) {
  const tags = bug.models.map((name) => `<span class="tag hw">${escapeHtml(name)}</span>`);
  tags.push(...bug.families.map((position) => `<span class="tag">${escapeHtml(families[position])}</span>`));
  if (hardware === "family") tags.push(`<span class="tag">${t("bug.familyOnly")}</span>`);
  return tags.join("");
}

/** First mention per branch: Cisco does not publish the release that introduced a bug. */
function renderAppearance(bug) {
  const first = new Map();
  for (const [version, status] of bug.events) {
    const branch = versions[version].branch;
    if (status !== "r" && !first.has(branch)) first.set(branch, [version, status]);
  }
  if (!first.size) return `<p>${t("bug.neverKnown")}</p>`;
  const lines = [...first].reverse().map(([branch, [version, status]]) => {
    const text = t(status === "l" ? "bug.firstLimitation" : "bug.firstKnown", { version: nameOf(versions[version]) });
    return `<dt>${escapeHtml(branch)}</dt><dd>${escapeHtml(text)}</dd>`;
  });
  return `<dl class="history">${lines.join("")}</dl><p class="note">${t("bug.appearanceNote")}</p>`;
}

function renderHistory(bug) {
  const lines = [...bug.events].reverse().map(([version, status, wheres]) => {
    const entry = versions[version];
    // One link per note listing the fact: notes of different series may say it each.
    const links = wheres.map(([doc, page]) => officialLink(doc, page, escapeHtml(t("bug.officialNote", { families: noteName(doc) })), bug.id));
    return `<dt>${escapeHtml(releaseLabel(entry))}</dt><dd>${KNOWN_LABELS[status]}, ${links.join(", ")}</dd>`;
  });
  return `<dl class="history">${lines.join("")}</dl>`;
}

function statusDetail(detail) {
  return detail ? `<span>${escapeHtml(t(`detail.${detail.id}`, detail))}</span>` : "";
}

function supportTag(bug) {
  if (!scopeApplies()) return "";
  return bug.supported.length
    ? `<span class="tag supported">${t(lifecycle ? "bug.supportedDated" : "bug.supported", { branches: escapeHtml(bug.supported.slice(0, 4).join(", ")) + (bug.supported.length > 4 ? "…" : "") })}</span>`
    : `<span class="tag">${t("scope.ended")}</span>`;
}

function renderBug({ bug, status, hardware, group }, terms) {
  const badge = group
    ? `<span class="badge ${UPGRADE_GROUPS[group].tone}">${UPGRADE_GROUPS[group].label}</span>`
    : status
      ? `<span class="badge ${status.key}">${STATUSES[status.key]}</span>${statusDetail(status.detail)}`
      : "";
  const description = bug.description ? highlight(bug.description, terms) : `<em>${t("bug.noDescription")}</em>`;
  return `<details class="bug" data-id="${bug.id}">
    <summary>
      <span class="bug-id">${bug.id}</span>
      <span class="bug-text">${description}</span>
      <span class="bug-meta">${badge}<span>${escapeHtml(fixesLabel(bug))}</span>${supportTag(bug)}${hardwareTags(bug, hardware)}</span>
    </summary>
    <div class="bug-detail"><h3>${t("bug.appearance")}</h3>${renderAppearance(bug)}<h3>${t("bug.history")}</h3>${renderHistory(bug)}${renderElsewhere(bug)}
      <p class="note"><a href="https://bst.cloudapps.cisco.com/bugsearch/bug/${bug.id}" target="_blank" rel="noopener">${t("bug.bst", { id: bug.id })}</a> ${t("bug.bstNote")}</p></div>
  </details>`;
}

function tile(data, key, label, tone, count, pressed) {
  return `<button type="button" class="summary-card ${tone}" data-${data}="${key}" aria-pressed="${pressed}"><strong>${formatNumber(count || 0)}</strong><span>${label}</span></button>`;
}

function renderChips(counts) {
  const version = versionIndex(state.version);
  if (state.view === "upgrade") {
    const compared = version >= 0 && versionIndex(state.from) >= 0;
    $("chips").innerHTML = compared
      ? Object.entries(UPGRADE_GROUPS)
        // The order of the tiles helps finding one; the list keeps the riskiest first.
        .sort(([a, { label: first }], [b, { label: second }]) => (b === "all") - (a === "all") || first.localeCompare(second, locale))
        .map(([key, { label, tone }]) => tile("group", key, label, tone, counts[key], state.group === key)).join("")
      : "";
  } else if (scopeApplies()) {
    $("chips").innerHTML = Object.entries(lifecycle ? SCOPES_DATED : SCOPES).map(([key, { label, tone }]) => tile("scope", key, label, tone, counts[key], state.scope === key)).join("");
  } else if (version >= 0) {
    $("chips").innerHTML = Object.entries(STATUSES).map(([key, label]) => tile("status", key, label, key, counts[key], !state.hidden.has(key))).join("");
  } else {
    $("chips").innerHTML = "";
  }
}

function renderNotices() {
  const messages = [];
  const selected = [versionIndex(state.version), state.view === "upgrade" ? versionIndex(state.from) : -1];
  for (const index of selected) {
    const family = selectedFamily(state.model, families, modelFamilies);
    if (index >= 0 && family >= 0 && !versions[index].families.includes(family)) {
      messages.push(t("notice.notListed", { family: families[family], version: nameOf(versions[index]) }));
    }
  }
  const version = selected[0];
  if (state.view === "upgrade" && versionIndex(state.from) >= 0 && version >= 0 && versionIndex(state.from) >= version) {
    messages.push(t("notice.order"));
  }
  if (state.view === "upgrade" && versionIndex(state.from) >= 0 && version >= 0 && versions[versionIndex(state.from)].branch !== versions[version].branch) {
    messages.push(t("notice.branches"));
  }
  $("notices").innerHTML = messages.map((text) => `<p class="notice">${escapeHtml(text)}</p>`).join("") + elsewhereNotice();
}

/** A bug ID absent from this system: the systems whose notes list it. */
function elsewhereNotice() {
  const wanted = searchTerms(state.query).filter(isBugTerm);
  const links = [];
  for (const term of wanted) {
    if (bugs.some((bug) => bug.key === term)) continue;
    const found = Object.entries(knownIds).find(([key]) => key.toLowerCase() === term);
    if (!found) {
      // Cisco writes its IDs CSC, two lowercase letters, five digits: CSCwu11498.
      links.push(t("notice.unknownId", { id: escapeHtml(`CSC${term.slice(3)}`) }));
      continue;
    }
    const [name, systems] = found;
    const targets = systems.filter((key) => key !== system).map((key) => {
      const params = new URLSearchParams({ system: key, query: name });
      if (language === "en") params.set("lang", "en");
      return `<a href="#${escapeHtml(params.toString())}">${escapeHtml(SYSTEMS[key])}</a>`;
    });
    links.push(t("notice.otherSystem", { id: escapeHtml(name), system: escapeHtml(systemName), systems: targets.join(", ") }));
  }
  return links.map((text) => `<p class="notice">${text}</p>`).join("");
}

function supportBadge(support) {
  if (!supportKnown) return "";
  if (support.dated) {
    const lts = support.lts ? ` ${t("support.lts")}` : "";
    const [tone, text] = !support.support
      ? (support.supported ? ["fixed", t("support.undated")] : ["unknown", t("support.ended")])
      : support.supported
        ? ["fixed", t(support.maintained ? "support.until" : "support.securityOnly", { date: formatDate(support.support), maintenance: support.maintenance && formatDate(support.maintenance) })]
        : ["unknown", t("support.endedOn", { date: formatDate(support.support) })];
    return `<a class="badge ${tone}" href="${escapeHtml(lifecycle.source)}" target="_blank" rel="noopener">${text}${lts}</a>`;
  }
  const date = support.activity && formatDate(support.activity);
  return support.supported
    ? `<span class="badge fixed">${t("support.active", { date })}</span>`
    : `<span class="badge unknown">${date ? t("support.inactiveSince", { date }) : t("support.inactive")}</span>`;
}

/** Shortcuts to the latest release of each active branch, newest branch first. */
function renderSupport() {
  const latest = new Map(versions.map((entry) => [entry.branch, entry]));
  const active = [...latest.values()].filter((entry) => entry.support.supported)
    .sort((a, b) => (lifecycle ? 0 : (b.support.activity || "").localeCompare(a.support.activity || "")) || b.i - a.i);
  const shown = ["bugs", "upgrade"].includes(state.view) && active.length > 0 && supportKnown;
  $("support").hidden = !shown;
  if (!shown) return;
  const links = active.map((entry) => {
    const params = stateParams();
    params.set("version", entry.v);
    const label = lifecycle
      ? (entry.support.support ? t("support.dateUntil", { date: formatDate(entry.support.support) }) : t("support.undated"))
        + (entry.support.lts ? ` ${t("support.lts")}` : "")
      : entry.support.activity && t("support.date", { date: formatDate(entry.support.activity) });
    const date = label ? `<small>${label}</small>` : "";
    const current = entry.v === state.version ? ' aria-current="true"' : "";
    return `<a class="support-branch" href="#${escapeHtml(params.toString())}"${current}><strong>${escapeHtml(nameOf(entry))}</strong>${date}</a>`;
  });
  const note = lifecycle
    ? t("support.noteDated", { url: escapeHtml(lifecycle.source), policy: escapeHtml(lifecycle.policy || lifecycle.source) })
    : t("support.note");
  $("support").innerHTML = `<h2>${t(lifecycle ? "support.titleDated" : "support.title")}</h2><div class="support-list">${links.join("")}</div><p class="muted">${note}</p>`;
}

function renderVersionInfo() {
  const entry = versions[versionIndex(state.version)];
  const parts = [];
  if (entry) {
    parts.push(`${systemName} ${escapeHtml(nameOf(entry))}`);
    if (entry.released) parts.push(t("version.released", { date: formatDate(entry.released) }));
    parts.push(supportBadge(entry.support));
    const family = selectedFamily(state.model, families, modelFamilies);
    const docs = entry.docs.filter((doc) => family < 0 || documents[doc].families.includes(family));
    for (const doc of docs) parts.push(officialLink(doc, 0, escapeHtml(t("version.note", { families: noteName(doc) }))));
  }
  $("version-info").innerHTML = parts.map((part) => `<span>${part}</span>`).join("");
}

function renderUpgradeNotices() {
  const from = versionIndex(state.from);
  const to = versionIndex(state.version);
  const family = selectedFamily(state.model, families, modelFamilies);
  const items = state.view === "upgrade" && from >= 0 && to > from ? upgradeNotices(notices, versions, documents, to, family) : [];
  if (!items.length) {
    $("upgrade-notices").innerHTML = "";
    return;
  }
  const entry = versions[to];
  const list = items.map((item) => `<li><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a> <span class="muted">${escapeHtml(noteName(item.doc))}</span></li>`).join("");
  $("upgrade-notices").innerHTML = `<details class="reading"${state.reading ? " open" : ""}><summary>${t("reading.title", { count: items.length })}</summary>
    <p class="muted">${t("reading.help", { version: escapeHtml(nameOf(entry)) })}</p><ul>${list}</ul></details>`;
}

/** Releases holding the most recent value of a date field, newest release first. */
function latestBy(field) {
  const dated = versions.filter((entry) => entry[field]);
  const date = dated.reduce((latest, entry) => (entry[field] > latest ? entry[field] : latest), "");
  return { date, entries: dated.filter((entry) => entry[field] === date).reverse() };
}

function newsCard(title, date, entries) {
  const links = entries.map((entry) => `<a href="#${escapeHtml(new URLSearchParams({ system, version: entry.v }).toString())}">${escapeHtml(nameOf(entry))}</a>`);
  return `<section class="news-card"><h2>${title}</h2><strong>${date}</strong><p>${systemName} ${links.join(", ")}</p></section>`;
}

function latestCard(title, field) {
  const { date, entries } = latestBy(field);
  return date ? newsCard(title, formatDate(date), entries) : "";
}

function noteLine(version) {
  const entry = versions.find((candidate) => candidate.v === version);
  if (!entry || !entry.revised) return "";
  const links = entry.docs.map((doc) => officialLink(doc, 0, escapeHtml(t("version.note", { families: noteName(doc) }))));
  return `<p class="news-pdf version-info"><span>${t("news.revised", { date: formatDate(entry.revised) })}</span> ${links.join(" ")}</p>`;
}

function bugTable(rows) {
  const header = ["copy.bug", "copy.status", "copy.families", "copy.description", "copy.fix"].map((key) => t(key));
  return [header, ...rows.map(({ bug, status, group }) => [
    bug.id,
    group ? UPGRADE_GROUPS[group].label : status ? STATUSES[status.key] : "",
    bug.families.map((position) => families[position]).join(", "),
    bug.description,
    fixesLabel(bug),
  ])];
}

/** The Clipboard API needs HTTPS: a local preview over HTTP falls back on the old command. */
async function copyText(text) {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const field = document.createElement("textarea");
  field.value = text;
  document.body.append(field);
  field.select();
  document.execCommand("copy");
  field.remove();
}

function clearPanels() {
  $("notices").innerHTML = "";
  $("version-info").innerHTML = "";
  $("upgrade-notices").innerHTML = "";
  $("more").hidden = true;
}

function renderHardware() {
  const terms = searchTerms($("hardware-query").value);
  const listed = summaries
    .map((entry) => ({ ...entry, family: families[entry.family] }))
    .filter(({ model, family }) => terms.every((term) => `${model} ${family}`.toLowerCase().includes(term)))
    .sort((a, b) => a.model.localeCompare(b.model, "fr", { numeric: true }));
  const columns = ["model", "family", "count", "first", "last"];
  copiedTable = () => [columns.map((key) => t(`hardware.${key}`)), ...listed.map((entry) => [entry.model, entry.family, entry.count, entry.first, entry.last])];
  $("copy").hidden = !listed.length;
  $("copy").textContent = t("list.copy");
  $("chips").innerHTML = "";
  const rows = listed.map((entry) => {
    const filter = new URLSearchParams({ system, model: `m:${entry.model}` });
    const family = new URLSearchParams({ system, model: `f:${entry.family}` });
    return `<tr><th scope="row"><a href="#${escapeHtml(filter.toString())}">${escapeHtml(entry.model)}</a></th>
      <td><a href="#${escapeHtml(family.toString())}">${escapeHtml(entry.family)}</a></td><td>${formatNumber(entry.count)}</td>
      <td>${escapeHtml(entry.first)}</td><td>${escapeHtml(entry.last)}</td></tr>`;
  });
  $("results").innerHTML = rows.length
    ? `<table class="hardware-table"><thead><tr>${columns.map((key) => `<th scope="col">${t(`hardware.${key}`)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`
    : "";
  $("count").textContent = rows.length ? t("hardware.listed", { count: formatNumber(rows.length) }) : t("hardware.none");
  clearPanels();
  $("news-summary").innerHTML = "";
  writeHash();
}

function renderNews() {
  $("news-summary").innerHTML = latestCard(t("news.latestRelease"), "released") + latestCard(t("news.latestNote"), "revised");
  const byId = new Map(bugs.map((bug) => [bug.id, bug]));
  const entries = changes.map((change) => {
    const items = change.bugs.slice(0, 20).map((id) => {
      const bug = byId.get(id);
      const link = new URLSearchParams({ system, query: id });
      return `<li><a href="#${escapeHtml(link.toString())}">${id}</a> ${bug ? escapeHtml(bug.description) : ""}</li>`;
    });
    const hidden = change.bugs.length - items.length;
    if (hidden > 0) items.push(`<li class="muted">${t("news.more", { count: formatNumber(hidden) })}</li>`);
    const link = new URLSearchParams({ system, version: change.version });
    return `<article class="news">
      <time datetime="${change.date}">${formatDate(change.date)}</time>
      <h2><a href="#${escapeHtml(link.toString())}">${escapeHtml(change.titles[language])}</a></h2>
      ${noteLine(change.version)}
      ${items.length ? `<ul>${items.join("")}</ul>` : ""}
    </article>`;
  });
  $("results").innerHTML = entries.join("");
  $("count").textContent = "";
  $("copy").hidden = true;
  $("chips").innerHTML = "";
  clearPanels();
  writeHash();
}

function render() {
  renderSupport();
  if (state.view === "news") {
    renderNews();
    return;
  }
  if (state.view === "hardware") {
    renderHardware();
    return;
  }
  $("news-summary").innerHTML = "";
  const { rows, counts } = compute();
  const terms = searchTerms(state.query);
  renderChips(counts);
  renderNotices();
  renderVersionInfo();
  renderUpgradeNotices();

  const waiting = state.view === "upgrade" && (!state.from || !state.version);
  $("count").textContent = waiting
    ? t("count.choose")
    : rows.length > state.shown ? t("count.partial", { count: formatNumber(rows.length), shown: formatNumber(state.shown) })
      : rows.length > 1 ? t("count.many", { count: formatNumber(rows.length) }) : t(rows.length ? "count.one" : "count.none");
  $("results").innerHTML = rows.slice(0, state.shown).map((row) => renderBug(row, terms)).join("");
  $("more").hidden = rows.length <= state.shown;
  $("more").textContent = t("list.more", { count: formatNumber(rows.length - state.shown) });
  copiedTable = () => bugTable(rows);
  $("copy").hidden = !rows.length;
  $("copy").textContent = t("list.copy");
  writeHash();
}

function stateParams(shown = language) {
  const params = new URLSearchParams();
  if (shown === "en") params.set("lang", "en");
  if (system !== DEFAULT_SYSTEM) params.set("system", system);
  if (state.view !== "bugs") params.set("view", state.view);
  for (const key of ["query", "version", "from", "model"]) {
    if (state[key]) params.set(key, state[key]);
  }
  if (state.scope !== "all") params.set("scope", state.scope);
  return params;
}

function writeHash() {
  history.replaceState(null, "", `#${stateParams()}`);
}

function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  state.view = ["upgrade", "news", "hardware"].includes(params.get("view")) ? params.get("view") : "bugs";
  for (const key of ["query", "version", "from", "model"]) {
    state[key] = params.get(key) || "";
  }
  state.scope = ["supported", "ended"].includes(params.get("scope")) ? params.get("scope") : "all";
}

function syncControls() {
  const upgrade = state.view === "upgrade";
  const news = state.view === "news";
  const hardware = state.view === "hardware";
  $("tab-bugs").setAttribute("aria-pressed", String(state.view === "bugs"));
  $("tab-upgrade").setAttribute("aria-pressed", String(upgrade));
  $("tab-news").setAttribute("aria-pressed", String(news));
  $("tab-hardware").setAttribute("aria-pressed", String(hardware));
  $("filters").hidden = news || hardware;
  $("legend").hidden = news || hardware;
  $("hardware-tools").hidden = !hardware;
  $("subscribe").hidden = !news;
  $("field-from").hidden = !upgrade;
  $("version-label").textContent = t(upgrade ? "filter.target" : "filter.version", { system: systemName });
  $("view-help").textContent = t(`help.${state.view}`, { system: systemName });
  for (const key of ["version", "from", "model"]) combos[key].value = state[key];
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme").textContent = t(theme === "dark" ? "theme.light" : "theme.dark");
}

function branchLabel({ branch, support }) {
  if (!supportKnown) return `${systemName} ${branch}`;
  if (support.dated) {
    if (!support.supported) return t("option.branchEnded", { system: systemName, branch });
    return support.support ? t("option.branchUntil", { system: systemName, branch, date: formatDate(support.support) }) : `${systemName} ${branch}`;
  }
  return t(support.supported ? "option.branchActive" : "option.branchInactive", { system: systemName, branch });
}

function versionOptions(placeholder) {
  const options = [...versions].reverse().map((entry) => ({
    value: entry.v,
    label: releaseLabel(entry),
    group: branchLabel(entry),
    tone: entry.support.supported || !supportKnown ? "" : "ended",
  }));
  return [{ value: "", label: placeholder }, ...options];
}

/** A family first, for its bugs without model, then the models its bugs name. */
function modelOptions() {
  const options = families.flatMap((family, position) => [
    { value: `f:${family}`, label: t("option.family", { family }), group: family },
    ...models.filter(([, modelFamily]) => modelFamily === position)
      .map(([model]) => ({ value: `m:${model}`, label: model, group: family })),
  ]);
  return [{ value: "", label: t("filter.allModels") }, ...options];
}

function update(next) {
  clearTimeout(searchTimer);
  // The field is the reference: a filter can change while a search is debounced.
  Object.assign(state, { query: $("query").value }, next, { shown: PAGE_SIZE });
  syncControls();
  render();
}

function switchTo(next) {
  if (next === system) return;
  const params = new URLSearchParams({ system: next });
  if (state.view !== "bugs") params.set("view", state.view);
  if (state.query) params.set("query", state.query);
  if (language === "en") params.set("lang", "en");
  history.replaceState(null, "", `#${params}`);
  location.reload();
}

function bindEvents() {
  $("query").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => update({}), 150);
  });
  $("theme").addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", theme);
    applyTheme(theme);
  });
  $("reset").addEventListener("click", () => {
    $("query").value = "";
    update(defaultFilters());
  });
  $("language").addEventListener("click", () => {
    const next = language === "fr" ? "en" : "fr";
    localStorage.setItem("language", next);
    history.replaceState(null, "", `#${stateParams(next)}`);
    location.reload();
  });
  for (const key of Object.keys(SYSTEMS)) $(`system-${key}`).addEventListener("click", () => switchTo(key));
  $("tab-bugs").addEventListener("click", () => update({ view: "bugs" }));
  $("tab-upgrade").addEventListener("click", () => update({ view: "upgrade" }));
  $("tab-news").addEventListener("click", () => update({ view: "news" }));
  $("tab-hardware").addEventListener("click", () => update({ view: "hardware" }));
  $("hardware-query").addEventListener("input", () => render());
  $("more").addEventListener("click", () => {
    state.shown = Infinity;
    render();
  });
  $("chips").addEventListener("click", (event) => {
    const chip = event.target.closest("button");
    if (!chip) return;
    if (chip.dataset.scope) {
      update({ scope: chip.dataset.scope });
    } else if (chip.dataset.group) {
      update({ group: chip.dataset.group });
    } else {
      const key = chip.dataset.status;
      if (state.hidden.has(key)) state.hidden.delete(key); else state.hidden.add(key);
      update({});
    }
  });
  // toggle does not bubble, and a new render must not fold what the reader opened.
  $("upgrade-notices").addEventListener("toggle", (event) => {
    if (event.target.classList.contains("reading")) state.reading = event.target.open;
  }, true);
  $("copy").addEventListener("click", async () => {
    const table = copiedTable();
    await copyText(tableText(table));
    $("copy").textContent = t("list.copied", { count: formatNumber(table.length - 1) });
  });
  $("to-top").addEventListener("click", () => window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }));
  window.addEventListener("scroll", () => {
    $("to-top").hidden = window.scrollY < 500;
  }, { passive: true });
  // Selecting text in a bug must not fold or unfold it.
  $("results").addEventListener("click", (event) => {
    if (event.target.closest("summary") && !getSelection().isCollapsed) event.preventDefault();
  });
  window.addEventListener("hashchange", () => {
    const wanted = new URLSearchParams(location.hash.slice(1)).get("system") || DEFAULT_SYSTEM;
    if (wanted !== system && wanted in SYSTEMS) {
      location.reload();
      return;
    }
    readHash();
    $("query").value = state.query;
    update({});
  });
}

/** A system whose notes are not collected yet: say so, and keep the other systems reachable. */
function showEmpty() {
  $("stats").textContent = t("page.empty", { system: systemName });
  $("scope").textContent = t("page.scope");
  for (const id of ["filters", "legend", "support", "chips", "more", "copy"]) $(id).hidden = true;
  for (const key of ["tab-bugs", "tab-upgrade", "tab-hardware", "tab-news"]) $(key).disabled = true;
  $("count").textContent = t("page.empty", { system: systemName });
  for (const key of Object.keys(SYSTEMS)) $(`system-${key}`).addEventListener("click", () => switchTo(key));
  $("language").addEventListener("click", () => {
    const next = language === "fr" ? "en" : "fr";
    localStorage.setItem("language", next);
    location.reload();
  });
  $("theme").addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", theme);
    applyTheme(theme);
  });
}

/** The IDs of every system; optional, the page works without them. */
async function loadIds() {
  try {
    const response = await fetch("data/ids.json");
    if (response.ok) knownIds = await response.json();
  } catch (error) {
    knownIds = {};
  }
}

async function start() {
  await loadIds();
  const [index, data, news, chapters] = await Promise.all(
    ["index.json", "bugs.json", "changes.json", "notices.json"].map((name) => fetch(`data/${system}/${name}`).then((response) => {
      if (!response.ok) throw new Error(`${name}: ${response.status}`);
      return response.json();
    })),
  );
  branches = index.branches;
  lifecycle = index.lifecycle;
  supportKnown = Boolean(lifecycle) || Object.values(branches).some((entry) => entry.activity);
  const today = new Date().toISOString().slice(0, 10);
  versions = index.versions.map((entry, i) => ({ ...entry, i, support: branchSupport(entry.branch, branches, Boolean(lifecycle), today) }));
  documents = index.documents;
  families = index.families;
  models = index.models;
  modelFamilies = new Map(models);
  changes = news;
  notices = chapters;
  updated = index.updated;
  schedule = index.schedule;
  bugs = data.map(hydrate);
  if (!versions.length) {
    showEmpty();
    return;
  }
  summaries = modelSummaries(models, bugs, versions);

  for (const key of ["version", "from", "model"]) {
    combos[key] = new Combobox($(key), (value) => update({ [key]: value }));
  }
  combos.version.setOptions(versionOptions(t("filter.allVersions")));
  combos.from.setOptions(versionOptions(t("filter.choose")));
  combos.model.setOptions(modelOptions());

  const latest = versions[versions.length - 1];
  $("scope").textContent = t("page.scopeRange", { system: systemName, first: nameOf(versions[0]), last: nameOf(latest) });
  $("stats").textContent = t("page.stats", { bugs: formatNumber(bugs.length), versions: formatNumber(versions.length), notes: formatNumber(documents.length), latest: nameOf(latest) });
  const moment = new Date(updated);
  $("updated").textContent = t("page.updated", {
    date: moment.toLocaleDateString(locale),
    time: moment.toLocaleTimeString(locale, { timeStyle: "short" }),
  });
  if (schedule) $("schedule").textContent = t("page.schedule", { crons: schedule.crons.join(t("page.and")), zone: schedule.timezone });
  readHash();
  $("query").value = state.query;
  bindEvents();
  update({});
}

$(`system-${system}`).setAttribute("aria-pressed", "true");
applyTheme(document.documentElement.dataset.theme);
start().catch((error) => {
  $("stats").textContent = t("page.failed");
  console.error(error);
});
