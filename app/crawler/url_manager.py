from urllib.parse import urlparse, urlunparse

EXCLUDED_EXTENSIONS = [
    ".jpg", ".jpeg", ".png",
    ".gif", ".pdf", ".docx",
    ".xlsx", ".zip", ".rar",
    ".exe", ".svg", ".css",
    ".js",
]

class URLManager:
    @staticmethod
    def extract_domain(url: str) -> str:
        """Extracts the domain from a given URL."""
        paresed_url = urlparse(url)
        return f"{paresed_url.scheme}://{paresed_url.netloc}"
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalizes the URL by removing fragments and query parameters."""
        parsed_url = urlparse(url)
        normalized_url = parsed_url._replace(fragment='', query='')
        return urlunparse(normalized_url)
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Checks if the URL is valid and does not point to excluded file types."""
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        
        path = parsed.path.lower()
        return not any(path.endswith(ext) for ext in EXCLUDED_EXTENSIONS)
    

    