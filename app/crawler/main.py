import asyncio
import os
import json
import hashlib
from collections import deque
from typing import List, Set
import logging

from crawl4ai import (
    AsyncWebCrawler,
)

from app.crawler.config import CrawlConfig
from app.crawler.sitemeta import SitemapCrawler, RobotsHandler
from app.crawler import URLConfig

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
    

    async def crawl_parallel(
        self,
        urls: List[str],
        folder: str = None,
        filename: str = None,
        append: bool = False,
    ):
        """Efficient parallel crawl using Crawl4AI arun_many."""

        if folder:
            os.makedirs(folder, exist_ok=True)

        # Normalize URLs first
        normalized_urls = [
            self.url_config.normalize_url(u) for u in urls
        ]

        # Filter robots BEFORE sending to arun_many
        allowed_urls = []
        for url in normalized_urls:
            self.robots_handler.load(url)
            if self.robots_handler.is_allowed(url):
                allowed_urls.append(url)
            else:
                logger.warning(f"Blocked by robots.txt: {url}")

        if not allowed_urls:
            logger.warning("No URLs allowed after robots filtering.")
            return

        async with AsyncWebCrawler(
            config=self.crawl_config.browser_config
        ) as crawler:

            logger.info(
                f"Starting parallel crawl of {len(allowed_urls)} URLs"
            )

            results = await crawler.arun_many(
                urls=allowed_urls,
                config=self.crawl_config.crawl_config,
            )

            for result in results:

                try:
                    url = result.url

                    if not result.success:
                        logger.error(
                            f"Failed to crawl {url}: {result.error}"
                        )
                        continue

                    logger.info(f"Successfully crawled: {url}")

                    # Determine filename
                    if append:
                        if not filename:
                            raise ValueError(
                                "Filename required when append=True"
                            )
                        file_name = filename
                    else:
                        file_name = (
                            hashlib.sha256(url.encode()).hexdigest()[:8]
                            if not filename
                            else filename
                        )

                    if folder:
                        file_name = os.path.join(folder, file_name)

                    file_path = f"{file_name}.md"

                    content = result.markdown

                    if not content:
                        logger.warning(f"No content extracted from {url}")
                        continue

                    with open(
                        file_path,
                        "a" if append else "w",
                        encoding="utf-8",
                    ) as f:
                        f.write(self.crawl_config.filter_text(content))

                except Exception:
                    logger.exception("Error processing crawl result")

        logger.info("Parallel crawl completed.")


    async def get_data(
        self,
        url: str,
        folder: str = None,
        filename: str = None,
        append: bool = False,
    ):
        """
        Crawl entire website:
        - Try sitemap first
        - Fallback to BFS crawl
        - Then crawl pages in parallel
        """

        # Step 1: Try sitemap
        logger.info(f"Checking sitemap for {url}")

        all_urls = self.sitemap_crawler.crawl_sitemap(url)

        # Step 2: If no sitemap → BFS crawl
        if not all_urls:
            logger.info("No sitemap found. Falling back to BFS crawl.")
            all_urls = await self.get_website_urls(url)

        if not all_urls:
            logger.warning("No URLs discovered.")
            return

        logger.info(f"Discovered {len(all_urls)} URLs. Starting parallel crawl.")

        # Step 3: Crawl discovered URLs
        await self.crawl_parallel(
            urls=list(all_urls),
            folder=folder,
            filename=filename,
            append=append,
        )

    async def get_page_data(
        self,
        url: str,
        folder: str = None,
        filename: str = None,
        append: bool = False,
    ):
        """
        Crawl a single page and save its content.
        """

        await self.crawl_parallel(
            urls=[url],
            folder=folder,
            filename=filename,
            append=append,
        )