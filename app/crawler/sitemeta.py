import requests
from collections import deque
from typing import List, Set
from xml.etree import ElementTree

from app.crawler import URLConfig

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
            current_url = url = queue.pop()
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

