import asyncio
import logging
from dotenv import load_dotenv

from app.logger import Logger
from app.crawler.main import WebCrawler
from app.storage import StoreManager
from app.llm import LLMManager
from app.ingestion.parsing import Documents
from app.index.providers.chroma import ChromaIndex
from app.index.providers.type import QueryEngineType
from app.main import RAGAgent

load_dotenv()

Logger.setup()
logger = logging.getLogger(__name__)

TARGET_URL      = "https://docs.crawl4ai.com"
OUTPUT_FOLDER   = "output"
NAMESPACE       = "askthesite"
QUERY_ENGINE    = QueryEngineType.AUTO.value
TOP_K           = 5
LLM_MODEL_TYPE  = "opensource"
LLM_MODEL_NAME  = "llama3.1:8b"
LLM_TEMPERATURE = 0.7
DEMO_QUERY      = "What is crawl4ai and how does it work?"



async def crawl(url: str, folder: str) -> None:
    logger.info(f"[Crawl] Starting crawl of: {url}")
    crawler = WebCrawler()
    await crawler.get_page_data(
        url=url,
        folder=folder,
        filename="extracted_data",
        append=False,
    )
    logger.info(f"[Crawl] Finished. Output saved to '{folder}/'")

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


def build_agent(input_folder: str) -> RAGAgent:
    storage = StoreManager.get_or_create(
        store_type="chromadb",
        namespace=NAMESPACE,
    )

    llm = LLMManager.create(
        model_type=LLM_MODEL_TYPE,
        model_name=LLM_MODEL_NAME,
        temperature=LLM_TEMPERATURE,
    )

    document = Documents(input_files=input_folder)

    index = ChromaIndex(
        storage=storage,
        document=document,
        namespace=NAMESPACE,
        query_engine=QUERY_ENGINE,
        top_k=TOP_K,
    )

    return RAGAgent(
        llm=llm,
        storage=storage,
        index=index,
        document=document,
    )


def ingest(agent: RAGAgent) -> None:

    logger.info("[Ingest] Creating vector index from documents …")
    agent.create_index()
    logger.info("[Ingest] Index created successfully.")


def query(agent: RAGAgent, prompt: str) -> str:

    logger.info(f"[Query] Prompt: {prompt!r}")
    answer = agent.run(prompt)
    logger.info(f"[Query] Answer: {answer}")
    return answer



async def main() -> None:
    
    await crawl(url=TARGET_URL, folder=OUTPUT_FOLDER)
    agent = build_agent(input_folder=f"{OUTPUT_FOLDER}/")
    ingest(agent)

    answer = query(agent, prompt=DEMO_QUERY)
    print(f"\n{'='*60}\nAnswer:\n{answer}\n{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())