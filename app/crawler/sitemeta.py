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

class RobotsTextCrawler:
    def __init__(self):
        pass
    
    # Fetch and parse the robots.txt file, returning a list of disallowed paths.
    def parse_robots_txt(self, url: str) -> List[str]:
        """
        Fetches the robots.txt file from the given URL and extracts all disallowed paths.
        Args:
            url (str): The URL of the website to fetch the robots.txt from.
        Returns:
            List[str]: A list of disallowed paths extracted from the robots.txt file.
        """
        domain = URLConfig.extract_domain(url)
        disallowed_paths = []
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            for line in response.text.splitlines():
                line = line.split("#", 1)[0].strip()  # Remove comments and whitespace
                if line.lower().startswith("disallow:"):
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        path = parts[1].strip()
                        if path:
                            disallowed_paths.append(f"{domain}{path}")
        except requests.RequestException as e:
            print(f"Error fetching robots.txt: {e}")
        return disallowed_paths
    
    # Crawl the robots.txt for disallowed links.
    def robot_crawl(self, url: str) -> Set[str]:
        """
        Crawl the robots.txt file starting from the given URL and return a set of all disallowed URLs.
        Args:
            url (str): The URL of the website to crawl the robots.txt from.
        Returns:
            Set[str]: A set of disallowed URLs found in the robots.txt file.
        """

        domain = URLConfig.extract_domain(url)
        robot_url = f"{domain}/robots.txt"
        return set(self.parse_robots_txt(robot_url))

