# def main():
#     print("Hello from rag-agent-for-websites-data!")


# if __name__ == "__main__":
#     main()

import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

async def main():
    # 1. Define the Browser Configuration
    # This controls the "physical" browser (window visibility, logging)
    browser_conf = BrowserConfig(
        verbose=True,      # Log steps to the terminal
        headless=False,    # Open a visible browser window
    )

    # 2. Define the Run Configuration
    # This controls the scraping logic (caching, scrolling, javascript)
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS  # Force a fresh scrape (don't use cache)
    )

    # 3. Initialize the Crawler with your Browser Config
    async with AsyncWebCrawler(config=browser_conf) as crawler:
        
        # 4. Run the crawl
        result = await crawler.arun(
            url="https://www.geeksforgeeks.org/machine-learning/self-supervised-learning-ssl/",
            config=run_conf
        )

        # 5. Print the result
        print("\n--- Scraped Content (Markdown) ---")
        print(result.markdown) # Print first 500 chars to avoid clutter
        print("...")

if __name__ == "__main__":
    asyncio.run(main())
