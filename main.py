# # def main():
# #     print("Hello from rag-agent-for-websites-data!")


# # if __name__ == "__main__":
# #     main()

# import asyncio
# from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# async def main():
#     # 1. Define the Browser Configuration
#     # This controls the "physical" browser (window visibility, logging)
#     browser_conf = BrowserConfig(
#         verbose=True,      # Log steps to the terminal
#         headless=False,    # Open a visible browser window
#     )

#     # 2. Define the Run Configuration
#     # This controls the scraping logic (caching, scrolling, javascript)
#     run_conf = CrawlerRunConfig(
#         cache_mode=CacheMode.BYPASS  # Force a fresh scrape (don't use cache)
#     )

#     # 3. Initialize the Crawler with your Browser Config
#     async with AsyncWebCrawler(config=browser_conf) as crawler:
        
#         # 4. Run the crawl
#         result = await crawler.arun(
#             url="https://www.geeksforgeeks.org/machine-learning/self-supervised-learning-ssl/",
#             config=run_conf
#         )

#         # 5. Print the result
#         print("\n--- Scraped Content (Markdown) ---")
#         print(result.markdown) # Print first 500 chars to avoid clutter
#         print("...")

# if __name__ == "__main__":
#     asyncio.run(main())


from app.crawler.url_manager import URLManager

def test_extract_domain():
    url = "https://www.example.com/path/to/page?query=123#section"
    domain = URLManager.extract_domain(url)
    assert domain == "https://www.example.com"

def test_normalize_url():
    url = "https://www.example.com/path/to/page?query=123#section"
    normalized = URLManager.normalize_url(url)
    assert normalized == "https://www.example.com/path/to/page"

def test_is_valid_url():
    valid_url = "https://www.example.com/path/to/page"
    invalid_url_1 = "ftp://www.example.com/resource"
    invalid_url_2 = "https://www.example.com/image.jpg"
    invalid_url_3 = "www.example.com/no-scheme"

    assert URLManager.is_valid_url(valid_url) == True
    assert URLManager.is_valid_url(invalid_url_1) == False
    assert URLManager.is_valid_url(invalid_url_2) == False
    assert URLManager.is_valid_url(invalid_url_3) == False




def main():
    test_extract_domain()
    test_normalize_url()
    test_is_valid_url()
    print("All tests passed!")

if __name__ == "__main__":
    main()