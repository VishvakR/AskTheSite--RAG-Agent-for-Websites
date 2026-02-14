import requests
from collections import deque
from typing import List, Set, Dict
from xml.etree import ElementTree
import urllib.robotparser
from urllib.parse import urlparse
import logging
from app.crawler import URLConfig

logger = logging.getLogger(__name__)

class SitemapCrawler:
    def __init__(self):
        pass
    
    # Fetch and parse the sitemap, returning a list of URLs.
    def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """
        Fetches the sitemap XML from the given URL and extracts all URLs listed in it.
        Args:
            sitemap_url (str): The URL of the sitemap to parse.
        Returns:
            List[str]: A list of URLs extracted from the sitemap.
        """
        try:
            response = requests.get(sitemap_url)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            return [loc.text for loc in root.findall(".//ns:loc", namespace)]
        except Exception as e:
            print(f"Error fetching sitemap: {e}")
            return []
    
    # Crawl the sitemap and return a set of all URLs found.
    def crawl_sitemap(self, url: str) -> Set[str]:
        """
        Crawl the sitemap starting from the given URL and return a set of all URLs found.
        Args:
            url (str): The URL of the sitemap to crawl.
        Returns:
            Set[str]: A set of URLs found in the sitemap.
        """

        visited = set()
        all_url = set()

        queue = deque([URLConfig.extract_domain(url) + '/sitemap.xml'])
        while queue:
            current_url = queue.pop()
            if current_url in visited:
                continue
            visited.add(current_url)
            links = self.parse_sitemap(current_url)
            for link in links:
                if link.endswith('.xml') and link not in visited:
                    queue.append(link)
                else:
                    all_url.add(link)
        return all_url

class RobotsHandler:
    def __init__(self, user_agent: str = "*"):
        self.user_agent = user_agent
        self.parsers: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self.crawl_delays: Dict[str, float] = {}

    def _get_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def load(self, url: str):
        domain = self._get_domain(url)

        if domain in self.parsers:
            return

        robots_url = f"{domain}/robots.txt"

        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)

        try:
            rp.read()
            self.parsers[domain] = rp

            delay = rp.crawl_delay(self.user_agent)
            if delay:
                self.crawl_delays[domain] = delay

            logger.info(f"Loaded robots.txt for {domain}")

        except Exception as e:
            logger.warning(
                f"Failed to load robots.txt for {domain}: {e}. "
                "Failing open (allowing crawl)."
            )

            self.parsers[domain] = None
    def is_allowed(self, url: str) -> bool:
        domain = self._get_domain(url)

        if domain not in self.parsers:
            self.load(url)

        rp = self.parsers.get(domain)

        # If robots failed to load → allow crawl
        if rp is None:
            return True

        return rp.can_fetch(self.user_agent, url)

    def get_crawl_delay(self, url: str) -> float:
        domain = self._get_domain(url)
        return self.crawl_delays.get(domain, 0)

