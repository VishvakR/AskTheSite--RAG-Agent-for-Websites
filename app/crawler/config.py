from crawl4ai import (
    BrowserConfig, 
    CrawlerRunConfig, 
    CacheMode, 
    DefaultMarkdownGenerator
)
from crawl4ai.content_filter_strategy import PruningContentFilter

class CrawlerConfig:
    def __init__(
            self,
            filter_text: bool = None,
            filter_link: bool = None,
            browser_config = None,
            md_generator = None,
            crawl_run_config = None,
            content_filter = None
        ) :

        # Set up Markdown Generator
        if md_generator is None:
            self.md_generator = DefaultMarkdownGenerator(
                options={
                    "ignore_links" : False,
                    "protect_links" : False,
                },
                content_filter= (PruningContentFilter(threshold=0.6) 
                                 if content_filter is None else content_filter)
            )
        else:
            self.md_generator = md_generator

        # Set up Browser Configuration
        if browser_config is None:
            self.browser_config = BrowserConfig(
                headless=True,
                verbose=False
            )
        else:
            self.browser_config = browser_config

        # Set up Crawl Run Configuration
        if crawl_run_config is None:
            self.crawl_run_config = CrawlerRunConfig(
                markdown_generator=self.md_generator,
                cache_mode=CacheMode.BYPASS,
            )
        else:
            self.crawl_run_config = crawl_run_config
            
        # Set up content filtering options
        self.filter_text = filter_text
        self.filter_link = filter_link

