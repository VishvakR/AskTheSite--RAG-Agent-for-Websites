import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl

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

_agent: Optional[RAGAgent] = None


def get_agent(
    namespace: str = "askthesite",
    input_folder: str = "output/",
    query_engine: str = QueryEngineType.AUTO.value,
    top_k: int = 5,
    llm_model_type: str = "opensource",
    llm_model_name: str = "llama3.1:8b",
    llm_temperature: float = 0.7,
) -> RAGAgent:
    """Return the cached RAGAgent, creating it if necessary."""
    global _agent
    if _agent is None:
        logger.info("Initialising RAGAgent …")
        storage = StoreManager.get_or_create(
            store_type="chromadb",
            namespace=namespace,
        )
        llm = LLMManager.create(
            model_type=llm_model_type,
            model_name=llm_model_name,
            temperature=llm_temperature,
        )
        document = Documents(input_files=input_folder)
        index = ChromaIndex(
            storage=storage,
            document=document,
            namespace=namespace,
            query_engine=query_engine,
            top_k=top_k,
        )
        _agent = RAGAgent(llm=llm, storage=storage, index=index, document=document)
        logger.info("RAGAgent ready.")
    return _agent

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AskTheSite API starting up …")
    yield
    logger.info("AskTheSite API shut down.")


app = FastAPI(
    title="AskTheSite API",
    description=(
        "RESTful API for the AskTheSite RAG pipeline. "
        "Crawl a website, ingest the content, and query it with natural language."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class CrawlRequest(BaseModel):
    url: HttpUrl = Field(..., description="Target URL to crawl.")
    output_folder: str = Field("output", description="Local folder to save crawled markdown.")
    filename: str = Field("extracted_data", description="Base filename for output files.")
    append: bool = Field(False, description="Append to existing files instead of overwriting.")


class CrawlResponse(BaseModel):
    message: str
    output_folder: str


class IngestRequest(BaseModel):
    input_folder: str = Field("output/", description="Folder containing crawled markdown files.")
    namespace: str = Field("askthesite", description="ChromaDB collection namespace.")
    query_engine: str = Field(QueryEngineType.AUTO.value, description="Retrieval strategy.")
    top_k: int = Field(5, ge=1, le=50, description="Max chunks to retrieve per query.")
    llm_model_type: str = Field("opensource", description="'opensource' (Ollama) or 'openai'.")
    llm_model_name: str = Field("llama3.1:8b", description="Model identifier.")
    llm_temperature: float = Field(0.7, ge=0.0, le=2.0, description="Sampling temperature.")


class IngestResponse(BaseModel):
    message: str
    namespace: str


class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Natural-language question to answer.")
    input_folder: str = Field("output/", description="Folder used when initialising the agent.")
    namespace: str = Field("askthesite", description="ChromaDB collection namespace.")
    query_engine: str = Field(QueryEngineType.AUTO.value, description="Retrieval strategy.")
    top_k: int = Field(5, ge=1, le=50, description="Max chunks to retrieve.")
    llm_model_type: str = Field("opensource", description="'opensource' (Ollama) or 'openai'.")
    llm_model_name: str = Field("llama3.1:8b", description="Model identifier.")
    llm_temperature: float = Field(0.7, ge=0.0, le=2.0, description="Sampling temperature.")


class QueryResponse(BaseModel):
    prompt: str
    answer: str


class PipelineRequest(BaseModel):
    url: HttpUrl = Field(..., description="Target URL to crawl.")
    output_folder: str = Field("output", description="Folder for crawled markdown.")
    namespace: str = Field("askthesite", description="ChromaDB collection namespace.")
    query: str = Field(..., min_length=1, description="Question to answer after ingestion.")
    query_engine: str = Field(QueryEngineType.AUTO.value, description="Retrieval strategy.")
    top_k: int = Field(5, ge=1, le=50)
    llm_model_type: str = Field("opensource")
    llm_model_name: str = Field("llama3.1:8b")
    llm_temperature: float = Field(0.7, ge=0.0, le=2.0)


class PipelineResponse(BaseModel):
    url: str
    namespace: str
    prompt: str
    answer: str



@app.get("/health", tags=["Utility"])
async def health_check():
    return {"status": "ok", "service": "AskTheSite API"}


@app.post("/crawl", response_model=CrawlResponse, tags=["Pipeline"])
async def crawl_endpoint(request: CrawlRequest):
    try:
        logger.info(f"[/crawl] url={request.url}  folder={request.output_folder}")
        crawler = WebCrawler()
        await crawler.get_page_data(
            url=str(request.url),
            folder=request.output_folder,
            filename=request.filename,
            append=request.append,
        )
        return CrawlResponse(
            message="Crawl completed successfully.",
            output_folder=request.output_folder,
        )
    except Exception as exc:
        logger.exception("[/crawl] Unexpected error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/ingest", response_model=IngestResponse, tags=["Pipeline"])
def ingest_endpoint(request: IngestRequest):
    global _agent
    try:
        logger.info(f"[/ingest] folder={request.input_folder}  ns={request.namespace}")
        _agent = None  # force re-creation with new params
        agent = get_agent(
            namespace=request.namespace,
            input_folder=request.input_folder,
            query_engine=request.query_engine,
            top_k=request.top_k,
            llm_model_type=request.llm_model_type,
            llm_model_name=request.llm_model_name,
            llm_temperature=request.llm_temperature,
        )
        agent.create_index()
        return IngestResponse(
            message="Ingestion completed. Vector index is ready.",
            namespace=request.namespace,
        )
    except Exception as exc:
        logger.exception("[/ingest] Unexpected error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/query", response_model=QueryResponse, tags=["Pipeline"])
def query_endpoint(request: QueryRequest):
    try:
        logger.info(f"[/query] prompt={request.prompt!r}")
        agent = get_agent(
            namespace=request.namespace,
            input_folder=request.input_folder,
            query_engine=request.query_engine,
            top_k=request.top_k,
            llm_model_type=request.llm_model_type,
            llm_model_name=request.llm_model_name,
            llm_temperature=request.llm_temperature,
        )
        answer = agent.run(request.prompt)
        return QueryResponse(prompt=request.prompt, answer=answer)
    except Exception as exc:
        logger.exception("[/query] Unexpected error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/pipeline", response_model=PipelineResponse, tags=["Pipeline"])
async def pipeline_endpoint(request: PipelineRequest):

    global _agent
    try:
        logger.info(f"[/pipeline] url={request.url}  query={request.query!r}")
        crawler = WebCrawler()
        await crawler.get_page_data(
            url=str(request.url),
            folder=request.output_folder,
            filename="extracted_data",
            append=False,
        )
        _agent = None
        agent = get_agent(
            namespace=request.namespace,
            input_folder=f"{request.output_folder}/",
            query_engine=request.query_engine,
            top_k=request.top_k,
            llm_model_type=request.llm_model_type,
            llm_model_name=request.llm_model_name,
            llm_temperature=request.llm_temperature,
        )
        agent.create_index()
        answer = agent.run(request.query)
        return PipelineResponse(
            url=str(request.url),
            namespace=request.namespace,
            prompt=request.query,
            answer=answer,
        )
    except Exception as exc:
        logger.exception("[/pipeline] Unexpected error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
