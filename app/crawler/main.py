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

                logger.info(f"Extracted {len(filtered_links)} links from {url}")

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

        logger = logging.getLogger(__name__)

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
