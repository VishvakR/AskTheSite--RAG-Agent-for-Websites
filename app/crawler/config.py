from crawl4ai import (
    BrowserConfig,
    CrawlerRunConfig,
    CacheMode,
    DefaultMarkdownGenerator,
)
from crawl4ai.content_filter_strategy import PruningContentFilter


class CrawlConfig:
    def __init__(
            self,
            browser_config=None,
            crawl_config=None,
            filter_links=None,
            md_generator=None,
            content_filter_strategy=None,
            filter_text=None,
            
    ):
        # Configuring the browser is browser config is not provided
        if browser_config is None:
            self.browser_config = BrowserConfig(
                headless=False,
                verbose=True
            )
        else:
            self.browser_config = browser_config

        # Configuring the Markdown generator is md_generator is not provided
        if md_generator is None:
            self.md_generator = DefaultMarkdownGenerator(
                options={
                    "ignore_links": False, 
                    "protect_links": False
                },
                content_filter=PruningContentFilter(threshold=0.6) 
                if content_filter_strategy is None 
                else content_filter_strategy
            )
        else:
            self.md_generator = md_generator
        
        # Configuring the CrawlerRunConfig is crawl_config is not provided
        if crawl_config is None:
            self.crawl_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                markdown_generator=self.md_generator
            )
        else:
            self.crawl_config = crawl_config

        self.filter_text = filter_text or (lambda x: x)
        self.filter_links = filter_links or (lambda x: True)
        
