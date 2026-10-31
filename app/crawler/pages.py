"""
On-disk representation of a crawled page.

Chunks used to carry only ``TextLoader``'s file path as metadata, which made
citations and the link graph impossible.  Each page is now written as its own
markdown file with YAML front-matter, so it is self-describing:

    workspaces/<workspace_id>/
        pages/<page_id>.md      # front-matter: url, title, depth, crawled_at, ...
        manifest.json           # seed url + page->page link edges for /graph

Front-matter keeps a page self-describing (no manifest drift); the manifest
holds the *edges*, which are not per-chunk data and are what the knowledge
graph needs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
PAGES_DIRNAME = "pages"


def page_id_for(url: str) -> str:
    """Stable filename-safe id for a URL."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


@dataclass
class PageRecord:
    url: str
    title: str = ""
    depth: int = 0
    outlinks: List[str] = field(default_factory=list)
    content_hash: str = ""
    char_count: int = 0
    crawled_at: str = ""
    page_id: str = ""
    file: str = ""
    error: Optional[str] = None

    def __post_init__(self):
        if not self.page_id:
            self.page_id = page_id_for(self.url)
        if not self.file:
            self.file = f"{PAGES_DIRNAME}/{self.page_id}.md"
        if not self.crawled_at:
            self.crawled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @property
    def ok(self) -> bool:
        return self.error is None and self.char_count > 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WorkspaceStore:
    """Reads and writes one workspace's crawled pages and manifest."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.pages_dir = self.root / PAGES_DIRNAME
        self.manifest_path = self.root / MANIFEST_NAME

    def ensure(self) -> None:
        self.pages_dir.mkdir(parents=True, exist_ok=True)

    # ── pages ─────────────────────────────────────────────────────────────

    def write_page(self, record: PageRecord, markdown: str) -> PageRecord:
        self.ensure()
        record.char_count = len(markdown)
        record.content_hash = content_hash(markdown)
        post = frontmatter.Post(
            markdown,
            url=record.url,
            title=record.title,
            depth=record.depth,
            page_id=record.page_id,
            content_hash=record.content_hash,
            crawled_at=record.crawled_at,
            outlinks=record.outlinks,
        )
        target = self.root / record.file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(frontmatter.dumps(post), encoding="utf-8")
        return record

    def read_page(self, path: Path) -> tuple[Dict[str, Any], str]:
        post = frontmatter.load(str(path))
        return dict(post.metadata), post.content

    def iter_page_files(self):
        if not self.pages_dir.exists():
            return
        yield from sorted(self.pages_dir.glob("*.md"))

    def existing_hashes(self) -> Dict[str, str]:
        """``page_id -> content_hash`` for pages already on disk."""
        out: Dict[str, str] = {}
        for path in self.iter_page_files():
            try:
                meta, _ = self.read_page(path)
                if meta.get("page_id"):
                    out[str(meta["page_id"])] = str(meta.get("content_hash", ""))
            except Exception:
                logger.warning("Unreadable page file %s", path, exc_info=True)
        return out

    # ── manifest ──────────────────────────────────────────────────────────

    def write_manifest(
        self, seed_url: str, records: List[PageRecord], mode: str = "page"
    ) -> Dict[str, Any]:
        self.ensure()
        manifest = {
            "seed_url": seed_url,
            "mode": mode,
            "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "page_count": sum(1 for r in records if r.ok),
            "pages": [r.to_dict() for r in records],
        }
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return manifest

    def read_manifest(self) -> Optional[Dict[str, Any]]:
        if not self.manifest_path.exists():
            return None
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Corrupt manifest at %s", self.manifest_path)
            return None

    def graph(self) -> Dict[str, Any]:
        """
        Build ``{nodes, edges}`` for the knowledge-graph view.

        Only edges whose target was actually crawled are kept, so the graph
        never points at nodes that do not exist.
        """
        manifest = self.read_manifest()
        if not manifest:
            return {"nodes": [], "edges": []}

        pages = [p for p in manifest.get("pages", []) if not p.get("error")]
        if not pages:
            return {"nodes": [], "edges": []}

        by_url = {p["url"]: p for p in pages}

        edges = []
        seen = set()
        adjacency: Dict[str, List[str]] = {p["page_id"]: [] for p in pages}
        for p in pages:
            for link in p.get("outlinks", []):
                target = by_url.get(link)
                if not target or target["page_id"] == p["page_id"]:
                    continue
                key = (p["page_id"], target["page_id"])
                if key in seen:
                    continue
                seen.add(key)
                edges.append({"source": p["page_id"], "target": target["page_id"]})
                adjacency[p["page_id"]].append(target["page_id"])

        depths = self._link_depths(manifest.get("seed_url", ""), pages, by_url, adjacency)

        nodes = [
            {
                "id": p["page_id"],
                "url": p["url"],
                "title": p.get("title") or p["url"],
                "depth": depths.get(p["page_id"], p.get("depth", 0)),
                "char_count": p.get("char_count", 0),
            }
            for p in pages
        ]
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _link_depths(
        seed_url: str,
        pages: List[Dict[str, Any]],
        by_url: Dict[str, Dict[str, Any]],
        adjacency: Dict[str, List[str]],
    ) -> Dict[str, int]:
        """
        Link distance from the seed page, by BFS over the crawled link graph.

        Pages discovered via a sitemap all arrive with ``depth`` 0 because they
        were never reached by following links, which made the depth legend
        meaningless. Measuring distance in the graph itself gives a real answer
        regardless of how the URLs were discovered.
        """
        from collections import deque

        seed = by_url.get(seed_url) or by_url.get(seed_url.rstrip("/"))
        if seed is None:
            seed = min(pages, key=lambda p: len(p["url"]))

        depths = {seed["page_id"]: 0}
        queue = deque([seed["page_id"]])
        while queue:
            current = queue.popleft()
            for neighbour in adjacency.get(current, []):
                if neighbour not in depths:
                    depths[neighbour] = depths[current] + 1
                    queue.append(neighbour)

        # Pages with no inbound path from the seed sit one level past the deepest.
        if depths:
            orphan_depth = max(depths.values()) + 1
            for p in pages:
                depths.setdefault(p["page_id"], orphan_depth)
        return depths
