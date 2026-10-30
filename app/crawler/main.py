import asyncio
import os
import json
import hashlib
from collections import deque
from pathlib import Path
from typing import Callable, List, Optional, Set
import logging

from crawl4ai import (
    AsyncWebCrawler,
)

from app.crawler.config import CrawlConfig
from app.crawler.pages import PageRecord, WorkspaceStore
from app.crawler.sitemeta import SitemapCrawler, RobotsHandler
from app.crawler.url_utils import URLConfig

logger = logging.getLogger(__name__)


class WebCrawler:
    def __init__(self, crawl_config=None, politeness=2, max_concurrency=10):
        self.crawl_config = crawl_config or CrawlConfig()
        self.politeness = politeness
        self.max_concurrency = max_concurrency
        self.sitemap_crawler = SitemapCrawler()
        self.robots_handler = RobotsHandler(user_agent="MyCrawlerBot")
        self.url_config = URLConfig()

    async def get_page_urls(self, url: str, filename: str) -> Set[str]:
        """Fetch URLs from the given page URL."""
        logger.info(f"Extracting URLs from page: {url}")
        os.makedirs("./data", exist_ok=True)

        # Load and check robots
        self.robots_handler.load(url)

        if not self.robots_handler.is_allowed(url):
            logger.warning(f"Blocked by robots.txt: {url}")
            return set()

        # Respect crawl delay
        crawl_delay = self.robots_handler.get_crawl_delay(url)
        if crawl_delay:
            logger.info(f"Respecting crawl-delay: {crawl_delay}s")
            await asyncio.sleep(crawl_delay)

        try:
            async with AsyncWebCrawler(
                config=self.crawl_config.browser_config,
            ) as crawler:

                result = await crawler.arun(
                    url=url,
                    config=self.crawl_config.crawl_config,
                )

                if not result.success:
                    logger.error(f"Failed to crawl {url}: {result.error}")
                    return set()

                file_path = f"./data/{filename}.jsonl"

                internal_links = result.links.get("internal", [])

                filtered_links = [
                    link["href"]
                    for link in internal_links
                    if self.crawl_config.filter_links(link.get("href", ""))
                ]

                with open(file_path, "a", encoding="utf-8") as f:
                    for link in filtered_links:
                        json_line = json.dumps({"url": link})
                        f.write(json_line + "\n")

                logger.info(f"Filtered links: {filtered_links}")

                return set(filtered_links)

        except Exception:
            logger.exception(f"Unexpected error while crawling {url}")
            return set()

    async def get_website_urls(
        self,
        url: str,
        same_origin: bool = True,
        max_depth: int = 5,
        max_urls: int = 1000,
    ) -> Set[str]:
        """Crawl a website using BFS and return discovered URLs."""

        site_urls = set()
        seen_urls = set()
        orig_domain = self.url_config.extract_domain(url)

        queue = deque([(url, 0)])

        async with AsyncWebCrawler(
            config=self.crawl_config.browser_config
        ) as crawler:

            while queue and len(site_urls) < max_urls:

                curr_url, depth = queue.popleft()

                # Depth & duplicate check
                if depth > max_depth:
                    continue

                normalized_curr = self.url_config.normalize_url(curr_url)

                if normalized_curr in seen_urls:
                    continue

                seen_urls.add(normalized_curr)

                # Robots check
                self.robots_handler.load(normalized_curr)

                if not self.robots_handler.is_allowed(normalized_curr):
                    logger.warning(f"Blocked by robots.txt: {normalized_curr}")
                    continue

                # Respect crawl-delay
                delay = self.robots_handler.get_crawl_delay(normalized_curr)
                if delay:
                    await asyncio.sleep(delay)

                logger.info(f"Crawling depth={depth}: {normalized_curr}")

                try:
                    result = await crawler.arun(
                        url=normalized_curr,
                        config=self.crawl_config.crawl_config,
                    )

                    if not result.success:
                        logger.error(
                            f"Failed to crawl {normalized_curr}: {result.error}"
                        )
                        continue

                    internal_links = result.links.get("internal", [])

                    for link in internal_links:

                        href = link.get("href")
                        if not href:
                            continue

                        normalized = self.url_config.normalize_url(href)

                        if not self.url_config.is_valid_url(normalized):
                            continue

                        if normalized in site_urls:
                            continue

                        site_urls.add(normalized)

                        # Same-origin restriction
                        if (
                            not same_origin
                            or self.url_config.extract_domain(normalized)
                            == orig_domain
                        ):
                            queue.append((normalized, depth + 1))

                        if len(site_urls) >= max_urls:
                            break

                except Exception:
                    logger.exception(
                        f"Exception while crawling {normalized_curr}"
                    )

        logger.info(f"Discovered {len(site_urls)} URLs from {url}")

        return site_urls
    

    @staticmethod
    def _page_title(result) -> str:
        """Best-effort page title from the crawl result's metadata."""
        meta = getattr(result, "metadata", None) or {}
        title = meta.get("title") if isinstance(meta, dict) else None
        return (title or "").strip()

    def _internal_links(self, result, origin: str) -> List[str]:
        """Normalised same-origin outlinks, used to build the knowledge graph."""
        links = []
        seen = set()
        for link in (result.links or {}).get("internal", []) or []:
            href = link.get("href") if isinstance(link, dict) else None
            if not href:
                continue
            normalized = self.url_config.normalize_url(href)
            if not self.url_config.is_valid_url(normalized):
                continue
            if self.url_config.extract_domain(normalized) != origin:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            links.append(normalized)
        return links

    async def crawl_to_workspace(
        self,
        urls: List[str],
        workspace_dir,
        seed_url: str,
        mode: str = "page",
        depths: Optional[dict] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[PageRecord]:
        """
        Crawl *urls* and write one markdown file per page, with front-matter.

        The previous implementation passed a single ``filename`` for the whole
        batch and opened it in ``"w"`` mode, so a multi-page crawl overwrote
        itself and kept only the last page. Every page now gets its own file
        keyed by a hash of its URL, and the returned records make failures
        visible instead of silently reporting success.
        """
        store = WorkspaceStore(Path(workspace_dir))
        store.ensure()
        depths = depths or {}

        normalized = []
        seen = set()
        for u in urls:
            n = self.url_config.normalize_url(u)
            if n not in seen:
                seen.add(n)
                normalized.append(n)

        allowed = []
        for url in normalized:
            self.robots_handler.load(url)
            if self.robots_handler.is_allowed(url):
                allowed.append(url)
            else:
                logger.warning("Blocked by robots.txt: %s", url)

        if not allowed:
            logger.warning("No URLs allowed after robots filtering.")
            store.write_manifest(seed_url, [], mode=mode)
            return []

        origin = self.url_config.extract_domain(seed_url)
        records: List[PageRecord] = []
        total = len(allowed)
        done = 0

        if on_progress:
            on_progress(0, total, f"Crawling {total} page(s)")

        async with AsyncWebCrawler(config=self.crawl_config.browser_config) as crawler:
            logger.info("Starting parallel crawl of %d URLs", total)
            results = await crawler.arun_many(
                urls=allowed,
                config=self.crawl_config.crawl_config,
            )

            for result in results:
                url = getattr(result, "url", "") or ""
                done += 1
                try:
                    if not result.success:
                        logger.error("Failed to crawl %s: %s", url, result.error_message)
                        records.append(
                            PageRecord(
                                url=url,
                                depth=depths.get(url, 0),
                                error=str(result.error_message or "crawl failed"),
                            )
                        )
                        continue

                    markdown = str(result.markdown or "")
                    markdown = self.crawl_config.filter_text(markdown)
                    if not markdown.strip():
                        logger.warning("No content extracted from %s", url)
                        records.append(
                            PageRecord(
                                url=url,
                                depth=depths.get(url, 0),
                                error="no content extracted",
                            )
                        )
                        continue

                    record = PageRecord(
                        url=url,
                        title=self._page_title(result),
                        depth=depths.get(url, 0),
                        outlinks=self._internal_links(result, origin),
                    )
                    store.write_page(record, markdown)
                    records.append(record)
                    logger.info("Crawled %s (%d chars)", url, record.char_count)

                except Exception as exc:
                    logger.exception("Error processing crawl result for %s", url)
                    records.append(
                        PageRecord(url=url, depth=depths.get(url, 0), error=str(exc))
                    )
                finally:
                    if on_progress:
                        on_progress(done, total, f"Crawled {done}/{total}")

        store.write_manifest(seed_url, records, mode=mode)
        ok = sum(1 for r in records if r.ok)
        logger.info("Crawl complete: %d/%d pages succeeded", ok, total)
        return records

    async def discover_urls(
        self,
        url: str,
        max_pages: int = 100,
        max_depth: int = 3,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[str]:
        """Sitemap first, BFS fallback. Returns at most *max_pages* URLs."""
        if on_progress:
            on_progress(0, 0, "Checking sitemap")

        urls = []
        try:
            urls = list(self.sitemap_crawler.crawl_sitemap(url) or [])
        except Exception:
            logger.exception("Sitemap lookup failed for %s", url)

        if urls:
            logger.info("Sitemap yielded %d URLs", len(urls))
        else:
            logger.info("No sitemap found. Falling back to BFS crawl.")
            if on_progress:
                on_progress(0, 0, "No sitemap - discovering links")
            urls = list(
                await self.get_website_urls(
                    url, max_depth=max_depth, max_urls=max_pages
                )
            )

        seed = self.url_config.normalize_url(url)
        normalized = [seed]
        seen = {seed}
        for u in urls:
            n = self.url_config.normalize_url(u)
            if n not in seen:
                seen.add(n)
                normalized.append(n)

        return normalized[:max_pages]

    async def crawl_site(
        self,
        url: str,
        workspace_dir,
        max_pages: int = 100,
        max_depth: int = 3,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[PageRecord]:
        """Discover a whole site (sitemap, else BFS) and crawl every page."""
        urls = await self.discover_urls(
            url, max_pages=max_pages, max_depth=max_depth, on_progress=on_progress
        )
        if not urls:
            logger.warning("No URLs discovered for %s", url)
            return []
        return await self.crawl_to_workspace(
            urls=urls,
            workspace_dir=workspace_dir,
            seed_url=url,
            mode="site",
            on_progress=on_progress,
        )

    async def crawl_page(
        self,
        url: str,
        workspace_dir,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[PageRecord]:
        """Crawl exactly one page into a workspace."""
        return await self.crawl_to_workspace(
            urls=[url],
            workspace_dir=workspace_dir,
            seed_url=url,
            mode="page",
            on_progress=on_progress,
        )
