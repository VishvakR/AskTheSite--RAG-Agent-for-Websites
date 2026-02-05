import asyncio
from typing import List, Set
import os
from collections import deque
import json
import hashlib

from crawl4ai import AsyncWebCrawler
from app.crawler.config import CrawlerConfig
from app.crawler import URLManager

class Crawler:
        def __init__(self, crawl_config = None, politeness = 2, max_concurrent = 10):
                self.crawl_config = CrawlerConfig()
                self.politeness = politeness
                self.max_concurrent = max_concurrent

                if crawl_config:
                        self.crawl_config = crawl_config

        async def get_page_urls(self, url: str, filename: str, same_dir = True) -> List[str]:
                """Crawl a URL and extract all page URLs.

                Args:
                    url (str): The starting URL to crawl.
                    filename (str): The file to save the extracted URLs.
                    same_dir (bool): Whether to restrict URLs to the same directory.
                Returns:
                    List[str]: A list of extracted page URLs.
                """
                async with AsyncWebCrawler(
                        config = self.crawl_config.browser_config
                ) as crawler:
                        
                        result = await crawler.arun(
                                url = url,
                                config = self.crawl_config.crawl_run_config
                        )

                        if result.success:
                                filename = f"""./data/{filename}.jsonl"""
                        
                        