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
from app.crawler import URLUtils


class WebCrawler:

    def __init__(self, crawl_config=None, politeness=2, max_concurrency=10):
        self.crawl_config = crawl_config or CrawlConfig()
        self.politeness = politeness
        self.max_concurrency = max_concurrency
        self.sitemap_crawler = SitemapCrawler()
        self.robots_handler = RobotsHandler()
        self.url_utils = URLUtils()

    async def get_page_urls(self, url: str, filename: str) -> Set[str]:
        """Fetch URLs from the given page URL."""

        logger = logging.getLogger(__name__)

        # Ensure data directory exists
        os.makedirs("./data", exist_ok=True)

        # Load robots (if required by your implementation)
        self.robots_handler.load(url)

        if not self.robots_handler.is_allowed(url):
            logger.warning(f"Blocked by robots.txt: {url}")
            return set()

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

                return set(filtered_links)

        except Exception:
            logger.exception(f"Error crawling {url}")
            return set()
