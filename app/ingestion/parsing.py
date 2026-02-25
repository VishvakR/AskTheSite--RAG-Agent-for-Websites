from typing import List, Optional, Union
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter



# class MetaDataParser:
#     def __init__(self, llm_manager):

#         self.header_text_splitter = MarkdownHeaderTextSplitter(
#             chunk_size=1000,
#             chunk_overlap=200,
#         )


class Document:
    def __init__(
            self,
            input_files: Union[List[str], str],
            llm: LLmManager | None = None,
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
        
        def loadd(self):
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
            
        def split(self):
            docs = self.loadd()
            return self.text_splitter.split_documents(docs)
        
        








        

        


