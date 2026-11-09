"""Keep sources/manifest.json up to date and download the Release Notes pages.

New notes are found on the cisco.com "Release Notes" page of each product series
listed in sources/catalog.json; robots.txt allows these pages and the notes. A note
is an HTML page, sometimes a "book" whose bugs are in chapter pages.

The HTML pages carry no ETag nor Last-Modified, but the PDF Cisco generates from
each note does: a HEAD on that PDF tells whether the note changed, and only then is
the note downloaded again. Notes whose PDF has not changed for a long time are
checked once a week. Two seconds separate two requests.
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

import requests

from .parser import chapter_links, parse_page

log = logging.getLogger(__name__)

USER_AGENT = "cisco-bug-tracker/0.1 (+https://github.com/frc-fr/cisco-bug-tracker)"
CRAWL_DELAY = 2.0
SITE = "https://www.cisco.com"
STALE_DAYS = 540


class Client:
    """HTTP client that spaces out requests and retries transient failures."""

    def __init__(self, delay: float = CRAWL_DELAY, retries: int = 4):
        self.delay = delay
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def request(self, method: str, url: str) -> requests.Response:
        for attempt in range(self.retries):
            wait = self._last + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=90)
            except requests.RequestException as error:
                log.warning("%s %s failed: %s", method, url, error)
            else:
                if response.status_code not in (429, 500, 502, 503, 504):
                    return response
                log.warning("%s %s returned %s", method, url, response.status_code)
            time.sleep(self.delay * 2 ** (attempt + 1))
        raise RuntimeError(f"{method} {url}: giving up after {self.retries} attempts")


def load_catalog(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def classify(url: str, catalog: dict) -> Optional[Tuple[str, List[str]]]:
    """(system, families) of a note address, or None when the site does not follow it."""
    if re.search(catalog["exclude"], url):
        return None
    for document in catalog["documents"]:
        if re.search(document["pattern"], url):
            return document["system"], document["families"]
    return None


def normalize_link(link: str, base: str) -> Optional[str]:
    absolute = urljoin(base, link)
    parts = urlsplit(absolute)
    if parts.netloc not in ("www.cisco.com", "cisco.com") or not parts.path.endswith(".html"):
        return None
    path = parts.path.replace("/content/en/us/td/docs/", "/c/en/us/td/docs/")
    if not path.startswith("/c/en/us/td/docs/"):
        return None
    return SITE + path


def document_key(url: str) -> str:
    """A readable file name for a note: its page name, made unique by its folder when needed."""
    path = urlsplit(url).path
    stem = path.rsplit("/", 1)[-1][:-len(".html")]
    digest = hashlib.sha1(path.encode()).hexdigest()[:6]
    return f"{stem}-{digest}"


def pdf_of(url: str) -> str:
    return url[:-len(".html")] + ".pdf"


def etag_date(etag: str) -> Optional[str]:
    """Apache writes the modification time of a file, in microseconds, in its ETag: "size-mtime"."""
    match = re.fullmatch(r'"?(?:[0-9a-f]+-)?([0-9a-f]{12,14})"?', etag or "")
    if not match:
        return None
    seconds = int(match.group(1), 16) / 1e6
    if not 1e9 < seconds < 4e9:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d")


def sort_key(entry: dict):
    return entry["system"], entry["url"]


def load_manifest(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    return {document_key(e["url"]): e for e in json.loads(path.read_text(encoding="utf-8"))["documents"]}


def save_manifest(path: Path, manifest: Dict[str, dict]) -> None:
    entries = sorted(manifest.values(), key=sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"documents": entries}, indent=2) + "\n", encoding="utf-8")


def discover(catalog: dict, client: Client) -> Dict[str, Tuple[str, List[str]]]:
    """Notes linked from the listing pages, and the seeds: {url: (system, families)}."""
    found: Dict[str, Tuple[str, List[str]]] = {}
    for listing in catalog["listings"]:
        try:
            response = client.request("GET", listing)
        except RuntimeError as error:
            log.error("%s", error)
            continue
        if response.status_code != 200:
            log.error("%s returned %s", listing, response.status_code)
            continue
        for link in re.findall(r'href="([^"]+)"', response.text):
            url = normalize_link(link, response.url)
            target = url and classify(url, catalog)
            if target:
                found.setdefault(url, target)
    for url in catalog.get("seeds", []):
        target = classify(url, catalog)
        if target:
            found.setdefault(url, target)
    return found


def pdf_state(client: Client, url: str) -> Optional[str]:
    response = client.request("HEAD", pdf_of(url))
    if response.status_code != 200:
        return None
    return response.headers.get("ETag", "").strip('"') or None


def weekly(entry: dict, today: datetime) -> bool:
    """One day of the week per note, spread over the notes."""
    return int(hashlib.sha1(entry["url"].encode()).hexdigest(), 16) % 7 == today.weekday()


def due(entry: dict, today: datetime) -> bool:
    """Notes revised recently are checked at every run, the others once a week."""
    revised = entry.get("revised")
    if not revised or datetime.strptime(revised, "%Y-%m-%d").replace(tzinfo=timezone.utc) > today - timedelta(days=STALE_DAYS):
        return True
    return weekly(entry, today)


def fetch_html(client: Client, url: str) -> Optional[str]:
    response = client.request("GET", url)
    if response.status_code != 200:
        log.error("%s returned %s", url, response.status_code)
        return None
    if "/td/docs/" not in urlsplit(response.url).path:
        # A withdrawn note redirects to a support landing page.
        log.error("%s redirects to %s", url, response.url)
        return None
    response.encoding = response.encoding or "utf-8"
    return response.text


def download_document(client: Client, entry: dict, folder: Path) -> bool:
    """The note and the chapters holding its bugs, into <cache>/<key>/; False if unreachable."""
    html = fetch_html(client, entry["url"])
    if html is None:
        return False
    page = parse_page(html, entry["url"], entry["system"])
    chapters = page.chapters
    pages = [("index.html", html)]
    fetched = [entry["url"]]
    for url in chapters:
        chapter = fetch_html(client, url)
        if chapter is not None:
            pages.append((url.rsplit("/", 1)[-1], chapter))
            fetched.append(url)
    if folder.exists():
        for old in folder.glob("*.html"):
            old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in pages:
        (folder / name).write_text(content, encoding="utf-8")
    (folder / "pages.json").write_text(json.dumps(fetched), encoding="utf-8")
    entry["chapters"] = chapters
    return True


def update(manifest_path: Path, catalog_path: Path, cache: Path, client: Client, today: Optional[datetime] = None) -> List[str]:
    """Add the new notes, check the known ones, download what changed; return the keys downloaded."""
    today = today or datetime.now(timezone.utc)
    catalog = load_catalog(catalog_path)
    manifest = load_manifest(manifest_path)
    for url, (system, families) in discover(catalog, client).items():
        key = document_key(url)
        if key not in manifest:
            log.info("%s: new note %s", key, url)
            manifest[key] = {"url": url, "system": system, "families": families}
        else:
            manifest[key].update(system=system, families=families)
    downloaded = []
    for key, entry in sorted(manifest.items(), key=lambda item: sort_key(item[1])):
        folder = cache / key
        # A note read before is in data/: the cache only spares downloading it again.
        known = "chapters" in entry
        if known and not due(entry, today):
            continue
        etag = pdf_state(client, entry["url"])
        if etag:
            entry["revised"] = etag_date(etag) or entry.get("revised")
        # Without a PDF, nothing tells a change: the note is read again once a week.
        if known and (etag == entry.get("etag") if etag else not weekly(entry, today)):
            continue
        if download_document(client, entry, folder):
            entry["etag"] = etag
            entry.pop("unavailable", None)
            downloaded.append(key)
            log.info("%s: downloaded (%d chapters)", key, len(entry.get("chapters", [])))
            if len(downloaded) % 25 == 0:
                # A long first collection keeps what it got if it is stopped.
                save_manifest(manifest_path, manifest)
        else:
            entry["unavailable"] = True
    save_manifest(manifest_path, manifest)
    return downloaded


def cached_pages(folder: Path) -> List[Tuple[str, str]]:
    """(url, html) of a cached note, main page first."""
    urls = json.loads((folder / "pages.json").read_text(encoding="utf-8"))
    names = ["index.html"] + [url.rsplit("/", 1)[-1] for url in urls[1:]]
    return [(url, (folder / name).read_text(encoding="utf-8")) for url, name in zip(urls, names) if (folder / name).exists()]
