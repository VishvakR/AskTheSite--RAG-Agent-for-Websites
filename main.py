import os
import asyncio
import nest_asyncio

from app.crawler.main import WebCrawler
from app.storage import StoreManager
from app.llm.manager import LLMManager
from app.ingestion.parsing import Documents

nest_asyncio.apply()

async def main():
    crawler = WebCrawler()

    # Example 1: Crawl single page
    await crawler.get_page_data(
        url="https://docs.crawl4ai.com",
        folder="output",
        filename="extracted_data",
        append=False,
    )

    # Example 2: Crawl entire website
    # await crawler.get_data(
    #     url="https://www.york.ac.uk/teaching/cws/wws/webpage1.html",
    #     folder="output",
    # )

    # Example 3: Just links from a page
    # await crawler.get_page_urls(
    #     url="https://docs.crawl4ai.com", 
    #     filename="sample"
    # )

    storage = StoreManager.get_or_create(
        store_type="mongodb",
        namespace="askthesite",
    )

    llm = LLMManager.create(
        model_type="opensource",
        model_name="llama3.1:8b",
        temperature=0.7
    )

    input_files = "output/"

    document = Documents(input_files=input_files)
    docs = document.create_nodes()
    storage.get_vector_store().add_documents(docs)



if __name__ == "__main__":
    asyncio.run(main())