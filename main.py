
from app.crawler.main import WebCrawler
import asyncio

async def main():
    crawler = WebCrawler()

    # Example 1: Crawl single page
    await crawler.get_page_data(
        url="https://docs.crawl4ai.com",
        folder="output",
        filename="crawl4ai_docs",
        append=False,
    )

    # Example 2: Crawl entire website
    # await crawler.get_data(
    #     url="https://docs.crawl4ai.com",
    #     folder="output",
    # )

    # Example 3: Just links from a page
    # await crawler.get_page_urls(
    #     url="https://docs.crawl4ai.com", 
    #     filename="sample"
    # )


if __name__ == "__main__":
    asyncio.run(main())