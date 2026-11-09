"""Extract the bugs of a Cisco Release Notes page.

The notes come in many layouts, but every bug list is a table with one bug per row,
a Cisco bug ID (CSCwu11498) in one cell and its headline in another. The section
title before the table says whether the bugs are open or resolved, and in which
release; a table caption may say it again, sometimes more precisely, sometimes
wrongly (a copied caption). The title of the section wins for the release, the
caption for the status.

A note can be one page or a "book" whose table of contents links one page per
chapter: the chapters that hold bugs are read in turn. Security advisories are
left out, and CVE references are removed. Anything that does not fit is reported
in `warnings` rather than guessed.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from .versions import find_branch, find_versions, in_scope, only_out_of_scope, parts, sort_versions, version_key

BUG = re.compile(r"\bCSC[a-z]{2}\d{5}\b")
VULNERABILITY = re.compile(r"vulnerabilit|\bCVE-\d{4}-\d+|\bPSIRT\b|security advisory", re.I)
CVE_REFERENCE = re.compile(r"[\s(,;]*\bCVE-\d{4}-\d{4,}\b[)]?", re.I)
HEADLINE_PREFIX = re.compile(r"^(?:Headline|Symptom)\s*:\s*", re.I)
BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "caption", "div", "dt", "dd", "pre", "title"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
HEADING_CLASS = re.compile(r"head|title|subhead", re.I)
CAPTION_CLASS = re.compile(r"tablecap", re.I)
NOTICE = re.compile(
    r"upgrad|downgrad|migrat|limitation|restriction|important note|caution|behaviou?r change|deprecat|"
    r"unsupported|no longer supported|compatib", re.I)
CHAPTER = re.compile(r"bug|caveat|issue|open|resolved|known|upgrad|limitation|restriction|important|behavio", re.I)
MAX_HEADING = 160
SUBTITLE = re.compile(r"^(resolved|open|fixed|outstanding|known)\b.{0,20}\b(bugs?|issues?|caveats?)\b", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = re.compile(rf"\b(?:({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})|(\d{{4}})-(\d{{2}})-(\d{{2}})|(\d{{1,2}})\s+({MONTHS}),?\s+(\d{{4}}))\b", re.I)
RELEASED = re.compile(r"available|released|first release|initial|publish|created", re.I)


@dataclass
class Block:
    tag: str
    cls: str
    text: str


@dataclass
class Table:
    rows: List[List[str]]


class Flattener(HTMLParser):
    """The page as a flat list of text blocks and tables, in reading order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items: List[object] = []
        self.links: List[str] = []
        self.text: List[str] = []
        self.tag, self.cls = "", ""
        self.tables: List[List[List[str]]] = []
        self.captions: List[str] = []
        self.cell: Optional[List[str]] = None
        self.skip = 0

    def flush(self):
        text = " ".join("".join(self.text).replace("\xa0", " ").split())
        self.text = []
        if not text:
            return
        if self.cell is not None:
            self.cell.append(text)
        elif self.tables and self.tag == "caption":
            # A caption is written inside its table: it comes out just before it.
            self.captions[-1] = f"{self.captions[-1]} {text}".strip()
        elif not self.tables:
            self.items.append(Block(self.tag, self.cls, text))

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "nav", "footer"):
            self.skip += 1
            return
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if self.skip:
            return
        if tag == "table":
            self.flush()
            self.tables.append([])
            self.captions.append("")
        elif tag == "tr" and self.tables:
            self.tables[-1].append([])
        elif tag in ("td", "th") and self.tables:
            self.flush()
            self.cell = []
        elif tag in BLOCKS or tag == "br":
            self.flush()
            if tag != "br":
                self.tag, self.cls = tag, attributes.get("class") or ""

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "nav", "footer"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.tables and self.cell is not None:
            self.flush()
            if self.tables[-1]:
                self.tables[-1][-1].append(" ".join(self.cell))
            self.cell = None
        elif tag == "table" and self.tables:
            self.flush()
            rows = self.tables.pop()
            caption = self.captions.pop()
            if self.tables:
                # A table nested in a cell: its rows join the outer table.
                self.tables[-1].extend(rows)
            else:
                if caption:
                    self.items.append(Block("caption", "", caption))
                self.items.append(Table(rows))
        elif tag in BLOCKS:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


def flatten(html: str) -> Tuple[List[object], List[str]]:
    parser = Flattener()
    parser.feed(html)
    parser.flush()
    return parser.items, parser.links


@dataclass
class Page:
    url: str
    title: str
    observations: List[dict]
    notices: List[list]
    released: Dict[str, str]
    warnings: List[str]
    skipped: int
    has_bugs: bool
    chapters: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)
    left_out: List[str] = field(default_factory=list)


def is_heading(block: Block) -> bool:
    if len(block.text) > MAX_HEADING or "minitoc" in block.cls.lower():
        return False
    return block.tag in HEADING_TAGS or bool(HEADING_CLASS.search(block.cls)) and block.tag in ("p", "div", "span")


def is_subtitle(block: Block) -> bool:
    """A plain block can title a table too: "Resolved Bugs in Cisco IOS XE 17.9.10" in a div."""
    return (block.tag in ("p", "div") and not is_heading(block) and len(block.text) <= MAX_HEADING
            and bool(SUBTITLE.match(block.text)))


def is_caption(block: Block) -> bool:
    return len(block.text) <= MAX_HEADING and (block.tag == "caption" or bool(CAPTION_CLASS.search(block.cls)))


def section_status(text: str) -> Optional[str]:
    """"resolved", "open", "limitation", "security", or None when the text does not tell."""
    name = text.lower()
    if re.search(r"\bsecurity\b|vulnerab|psirt", name):
        return "security"
    resolved = re.search(r"\b(resolved|fixed|closed)\b", name)
    opened = re.search(r"\b(open|outstanding)\b", name)
    if resolved and not opened:
        return "resolved"
    if opened and not resolved:
        return "open"
    if resolved and opened:
        return None
    if re.search(r"\bknown (issues?|behaviou?rs?|limitations?|caveats?)\b|general/known|\blimitations?\b", name):
        return "limitation"
    # IOS XR lists the open bugs of a release as its "caveats".
    if re.search(r"\bcaveats\b|specific bugs|^bugs$", name):
        return "open"
    return None


def clean_description(text: str) -> str:
    text = HEADLINE_PREFIX.sub("", " ".join(text.split()))
    return CVE_REFERENCE.sub("", text).strip()


def parse_date(text: str) -> Optional[str]:
    match = DATE.search(text)
    if not match:
        return None
    g = match.groups()
    try:
        if g[0]:
            return datetime.strptime(f"{g[0]} {g[1]} {g[2]}", "%B %d %Y").strftime("%Y-%m-%d")
        if g[3]:
            return datetime(int(g[3]), int(g[4]), int(g[5])).strftime("%Y-%m-%d")
        return datetime.strptime(f"{g[7]} {g[6]} {g[8]}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def chapter_links(html_links: List[str], url: str) -> List[str]:
    """Chapters of a book that may hold bugs: pages under <note>/ whose name says so."""
    base = url[:-len(".html")] + "/" if url.endswith(".html") else url.rstrip("/") + "/"
    base_path = urlsplit(base).path
    found = []
    for link in html_links:
        absolute = urljoin(url, link).split("#")[0]
        path = urlsplit(absolute).path
        if path.startswith(base_path) and path.endswith(".html") and CHAPTER.search(path[len(base_path):]):
            target = "https://www.cisco.com" + path
            if target not in found:
                found.append(target)
    return found


def page_title(items: List[object]) -> str:
    for kind in ("h1", "title"):
        for item in items:
            if isinstance(item, Block) and item.tag == kind:
                return item.text
    return ""


def revision_dates(rows: List[List[str]], system: str, found: Dict[str, str]) -> None:
    """The date of each release: from a table of releases ("Version | Build | Date"), or
    from a revision history, the date a row says a release became available."""
    header = [cell.strip().lower() for cell in rows[0]] if rows else []
    version_column = next((i for i, cell in enumerate(header) if cell in ("version", "release")), None)
    date_column = next((i for i, cell in enumerate(header) if cell in ("date", "release date")), None)
    if version_column is not None and date_column is not None:
        for row in rows[1:]:
            if len(row) <= max(version_column, date_column):
                continue
            date = parse_date(row[date_column])
            for version in find_versions(system, row[version_column])[:1]:
                if date and (version not in found or date < found[version]):
                    found[version] = date
        return
    for row in rows:
        dates = [parse_date(cell) for cell in row]
        date = next((d for d in dates if d), None)
        if not date:
            continue
        text = " ".join(cell for cell, d in zip(row, dates) if not d)
        if not RELEASED.search(text):
            continue
        for version in find_versions(system, text):
            if version not in found or date < found[version]:
                found[version] = date


def parse_page(html: str, url: str, system: str, doc_title: Optional[str] = None) -> Page:
    """Bugs of one page. `doc_title` is the title of the note when the page is one of its chapters."""
    items, links = flatten(html)
    title = page_title(items)
    context_title = doc_title or title
    title_versions = find_versions(system, context_title)
    title_branch = find_branch(system, context_title)
    if not title_versions and not title_branch:
        bare = re.search(r"(?<![\d.])(\d+\.\d+)\s*$", context_title)
        title_branch = bare.group(1) if bare else None
    observations: List[dict] = []
    notices: List[list] = []
    released: Dict[str, str] = {}
    warnings: List[str] = []
    # Known layouts the site does not read, on purpose: recorded with the note, not blocking.
    left_out: List[str] = []
    skipped = 0
    heading, caption = "", ""
    has_bugs = False
    sections: List[str] = []

    for item in items:
        if isinstance(item, Block):
            if is_caption(item) or is_subtitle(item):
                caption = item.text
            elif is_heading(item):
                heading, caption = item.text, ""
                # A release with a bug section of its own, even an empty one, is documented.
                if section_status(item.text) in ("open", "resolved"):
                    sections += [v for v in find_versions(system, item.text) if v not in sections]
                if NOTICE.search(item.text) and item.text not in [n[0] for n in notices]:
                    notices.append([item.text, url])
            continue
        rows = [row for row in item.rows if any(BUG.fullmatch(cell.strip()) for cell in row)]
        header = " ".join(item.rows[0]).lower() if item.rows else ""
        if "date" in header and not rows:
            revision_dates(item.rows, system, released)
            continue
        if not rows:
            continue
        has_bugs = True
        status = section_status(caption) if caption else None
        status = status or section_status(heading)
        # A note, or a section, of releases older than the scope of the site.
        if only_out_of_scope(system, heading) or (not title_versions and only_out_of_scope(system, context_title)):
            continue
        if status is None and not title_versions and title_branch and not in_scope(system, title_branch):
            continue
        if status is None and not caption and re.search(r"\bresolved\b.*\bopen\b|\bopen\b.*\bresolved\b", heading, re.I):
            left_out.append(f"{url}: {len(rows)} bugs under {heading!r}, a table without caption: open or resolved, the note does not say")
            continue
        if status is None and re.search(r"behaviou?r change", heading, re.I):
            left_out.append(f"{url}: {len(rows)} bugs cited in {heading!r}: a change of behavior, not a bug list")
            continue
        if status is None:
            warnings.append(f"{url}: {len(rows)} bugs under {heading!r} / {caption!r}: status unknown, left out")
            continue
        if status == "security":
            skipped += len(rows)
            continue
        versions = find_versions(system, heading) or find_versions(system, caption)
        branch = None
        if not versions:
            branch = find_branch(system, heading) or find_branch(system, caption)
            if not branch:
                if len(title_versions) == 1:
                    versions = title_versions
                else:
                    branch = title_branch
        if not versions and not branch:
            if title_branch and not in_scope(system, title_branch):
                continue  # A note of a release older than the scope of the site.
            warnings.append(f"{url}: {len(rows)} bugs under {heading!r}: release unknown, left out")
            continue
        if branch and not in_scope(system, branch):
            continue
        for row in rows:
            bug_cell = next(cell for cell in row if BUG.fullmatch(cell.strip()))
            others = [cell for cell in row if cell is not bug_cell and cell.strip()]
            description = clean_description(max(others, key=len)) if others else ""
            if VULNERABILITY.search(description):
                skipped += 1
                continue
            for version in versions or [None]:
                observations.append({
                    "bug_id": bug_cell.strip(),
                    "status": status,
                    "version": version,
                    "branch": branch if version is None else None,
                    "description": description,
                    "url": url,
                })
    page = Page(url, title, observations, notices, released, warnings, skipped, has_bugs, sections=sections, left_out=left_out)
    if not has_bugs and not doc_title:
        page.chapters = chapter_links(links, url)
    return page


@dataclass
class Document:
    title: str
    versions: List[str]
    released: Dict[str, str]
    observations: List[dict]
    notices: List[list]
    warnings: List[str]
    skipped: int
    pages: List[str]
    left_out: List[str] = field(default_factory=list)


def parse_document(pages: List[Tuple[str, str]], system: str) -> Document:
    """A note from its main page and its chapters, as (url, html), main page first.

    Bugs listed for a whole branch ("Open Bugs in Version 9.22(x)") are open in the
    latest release the note documents on that branch, when it was published.
    """
    main_url, main_html = pages[0]
    first = parse_page(main_html, main_url, system)
    parsed = [first] + [parse_page(html, url, system, first.title) for url, html in pages[1:]]
    observations = [o for page in parsed for o in page.observations]
    warnings = [w for page in parsed for w in page.warnings]
    left_out = [w for page in parsed for w in page.left_out]
    released: Dict[str, str] = {}
    for page in parsed:
        for version, date in page.released.items():
            if version not in released or date < released[version]:
                released[version] = date
    known = {o["version"] for o in observations if o["version"]} | {v for page in parsed for v in page.sections}
    known |= {v for v in find_versions(system, first.title)}
    resolved = []
    unplaced: Dict[Tuple[str, str], int] = {}
    for o in observations:
        if o["version"]:
            resolved.append(o)
            continue
        on_branch = [v for v in known if parts(system, v)[0] == o["branch"]]
        if not on_branch:
            unplaced[(o["url"], o["branch"])] = unplaced.get((o["url"], o["branch"]), 0) + 1
            continue
        resolved.append({**o, "version": sort_versions(system, on_branch)[-1]})
    for (url, branch), count in unplaced.items():
        left_out.append(f"{url}: {count} bugs listed for branch {branch}, which names none of its releases")
    for o in resolved:
        o.pop("branch", None)
    # One fact per bug, release and status: a table repeated in two chapters says it once.
    unique = {}
    for o in resolved:
        unique.setdefault((o["bug_id"], o["version"], o["status"]), o)
    observations = sorted(unique.values(), key=lambda o: (version_key(system, o["version"]), o["status"], o["bug_id"]))
    notices = []
    for page in parsed:
        for title, url in page.notices:
            if title not in [n[0] for n in notices]:
                notices.append([title, url])
    versions = sort_versions(system, known)
    return Document(first.title, versions, released, observations, notices, warnings,
                    sum(page.skipped for page in parsed), [url for url, _ in pages], left_out)
