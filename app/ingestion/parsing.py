from typing import List, Optional, Union
from langchain_core.documents import Document
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field




class MetaDataParser:
    def __init__(self, llm: LLMManager):
        self.llm = llm
    
        class MetaDataSchema(BaseModel):
            title: str = Field(description="Title of the document")
            summary: str = Field(description="Summary of the document")
            keywords: List[str] = Field(description="Keywords of the document")

        self.parser = PydanticOutputParser(pydantic_object=MetaDataSchema)

    def add_metadata(self, documents: List[Document]) -> List[Document]:
        """Add Metadata to the documents using the LLM"""




class Document:
    def __init__(
            self,
            input_files: Union[List[str], str],
            llm: LLMManager | None = None,
            add_metadata: Optional[bool] = False,
        ):

        if isinstance(input_files, List):
            self.files = input_files
        else:
            self.files = None
            self.input_dir = input_files

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
        )

        self.add_metadata = add_metadata
        if self.add_metadata:
            if llm is None:
                raise ValueError("LLM is Requirerd to add metadata")
            self.metadata_parser = MetaDataParser(llm)
        
    def loadd(self) -> List[Document]:
        """Load documents form the directory or from the list of files"""
        if self.files is not None:
            document = []
            for file in self.files:
                loader = TextLoader(file)
                document.extend(loader.load())
            return document
        
        else:
            loader = DirectoryLoader(
                self.input_dir,
                glob=self.input_dir + '/**/*.md',
                show_progress=True
            )

            return loader.load()
        
    def split(self) -> List[Document]:
        docs = self.loadd()
        return self.text_splitter.split_documents(docs)
    
    def create_nodes(self) -> List[Document]:
        """Create nodes form the documents"""
        split_docs = self.split()
        if self.add_metadata:
            split_docs = self.metadata_parser.add_metadata(split_docs)
        return split_docs
        
            
    

    









    

    


