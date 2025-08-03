import re
import argparse
import asyncio
import io
import os
import tempfile
import logging
from typing import List, Optional
from threading import Thread

import google.generativeai as genai
from openai import OpenAI

from .retrieval_storage   import RetrievalAsyncStorageManager
from .retrieval_embedder  import RetrievalEmbedder
from .retrieval_extractor import RetrievalExtractor
from ..report_scraper.models import ReportType
from ..report_retrieval.report_retrieval_util import chunk_markdown, clean_markdown_response
from ..prompts import PROMPT

# Background event loop for async storage
_background_loop = asyncio.new_event_loop()

def _start_background_loop():
    asyncio.set_event_loop(_background_loop)
    _background_loop.run_forever()

_thread = Thread(target=_start_background_loop, daemon=True)
_thread.start()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _background_loop)
    return future.result()

retrieval_logger = logging.getLogger("retrieval")

class ReportRetrievalManager:
    def __init__(
        self,
        storage: RetrievalAsyncStorageManager,
        embedder: RetrievalEmbedder,
        extractor: RetrievalExtractor,
        genai_model: str,
        genai_api_key: str,
        openai_api_key: str,
        dry_run: bool = True
    ):
        self.storage   = storage
        self.embedder  = embedder
        self.extractor = extractor
        self.genai_model   = genai_model
        self.genai_api_key = genai_api_key
        self.openai_key    = openai_api_key
        self.dry_run       = dry_run

    def parse_store(
        self,
        company: str,
        report_type: ReportType,
        year: int,
        prompt: str = PROMPT["REPORTS PARSING"],
        download_local: bool = True,
        forced_process: bool = False
    ) -> Optional[str]:
        """
        Synchronous wrapper around the async parse_and_store.
        """
        return run_async(self.parse_and_store(company, report_type, year, prompt, download_local, forced_process))

    async def parse_and_store(
            self,
            company: str,
            report_type: ReportType,
            year: int,
            prompt: str = PROMPT["REPORTS PARSING"],
            download_local: bool = True,
            forced_process: bool = False
    ) -> None:
        """
        1) Fetch raw PDFs for company/year
        2) Upload to GenAI + run summarization prompt
        3) Save the Markdown summary to GridFS and metadata
        4) Mark raw PDF docs processed=True + summary_path/file_id
        5) Chunk & embed the summary into Pinecone
        Returns the Markdown text.
        """
        company = company.replace(" ", "_").upper().strip()

        # Step 1: Fetch raw PDFs
        report_collection = report_type.collection
        process_collection = f"{report_type.name}_processed"

        # Check processed collection first
        self.storage.use_collection(process_collection)
        summary_fn = f"{company}_{report_type.name}_{year}_summary.md"
        processed_md = await self.storage.get_processed_summary(summary_fn)

        # Fetch raw pdfs
        self.storage.use_collection(report_collection)
        raw_docs = await self.storage.get_raw_reports(company, year)
        if not raw_docs:
            raise ValueError(f"No raw reports found for {company} {report_type.keyword} {year}")
        
        amended_docs = [d for d in raw_docs if d.get("is_amended")]

        # if processed summary is existed
        if processed_md and not forced_process:
            # if no amendments, mark all raw as processed and return existing summary
            if not amended_docs:
                await self.storage.collection.update_many(
                    {"company": company, "year": str(year)},
                    {
                        "$set": {
                            "processed": True,
                            "summary_path": summary_fn,
                        }
                    }
                )
                
                # download to local
                if download_local:
                    self.download_to_local(company, summary_fn, processed_md)

                return
            
            # re-process only the amended PDFs
            else:
                retrieval_logger.info("Performing Amend Branch...")
                base_md = await self.storage.get_processed_summary(summary_fn)
                to_upload = amended_docs
                mode = "amend"

        else:
            # no processed summary yet, fresh process of all raw PDFs
            retrieval_logger.info("Performing Fresh Branch...")
            to_upload = raw_docs
            mode = "fresh"

        # upload PDFs and process with genai
        genai.configure(api_key=self.genai_api_key)
        uploaded_pdfs = []

        for doc in to_upload:
            fid = doc["file_id"]
            fn = doc["filename"]
            retrieval_logger.info("     Uploading %s ...", fn)
            grid_out = await self.storage.fs_bucket.open_download_stream(fid)
            data = await grid_out.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(data)
            tmp.close()
            uploaded_pdfs.append(genai.upload_file(path=tmp.name, display_name=fn))
            os.unlink(tmp.name)

        retrieval_logger.info("Uploaded %d PDFs", len(uploaded_pdfs))

        model = genai.GenerativeModel(self.genai_model)
        if mode == "amend":
            full_prompt = (
                "Here is the existing summary:\n\n"
                    + base_md
                    + "\n\nNow update it to incorporate these amendments:\n\n"
                    + prompt
            )
        else:
            full_prompt = prompt

        retrieval_logger.info("Generating...")
        response = model.generate_content([*uploaded_pdfs, full_prompt])
        md = clean_markdown_response(response.text)

        retrieval_logger.info("Finished processing.")

        # Extract token usage
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count
        output_tokens = usage.candidates_token_count
        total_tokens = usage.total_token_count

        retrieval_logger.info(f"     Prompt Tokens: {input_tokens}")
        retrieval_logger.info(f"     Output Tokens: {output_tokens}")
        retrieval_logger.info(f"     Total Tokens: {total_tokens}")


        # save summary into processed collection and mark raw docs
        await self.storage.save_processed_report(
            company, year, report_type, summary_fn, md
        )

        # chunk and replce old vectors in Pinecone
        chunks = chunk_markdown(md)
        if not self.dry_run:
            self.embedder.upsert_chunks(chunks, company, year)

        else:
            retrieval_logger.info("Dry run enabled, skipping chunk upsert.")

        # download to local
        if download_local:
            self.download_to_local(company, summary_fn, md)




    
    def answer_query(
            self,
            company: str,
            query: str,
            top_k: 5,
            chat_model: str
    ) -> str:
        """
        Answer a query about a company's reports using the retrieval system.
        1) Retrieve relevant chunks from Pinecone
        2) Format them into a prompt
        3) Use OpenAI to answer the query
        """
        top_k_chunks = self.extractor.retrieve_chunks(query, namespace=company, top_k=top_k)

        if not top_k_chunks:
            return "No relevant information found for this query."
        
        context = "\n\n---\n\n".join(top_k_chunks)

        openai = OpenAI(api_key=self.openai_key)
        messages = [
            {"role": "system", "content": f"Use the following context:\n\n{context}"},
            {"role": "user",   "content": query}
        ]
        resp = openai.chat.completions.create(model=chat_model, messages=messages)

        retrieval_logger.info("Response generated: %s (TOKEN: %d)", resp.choices[0].message.content, resp.usage.total_tokens)
        
        return resp.choices[0].message.content
    

    def download_to_local(self, company: str, filename: str, content: str) -> None:
        company_directory = os.path.join("./processed_report", company)
        os.makedirs(company_directory, exist_ok=True)

        # Create full file path
        file_path = os.path.join(company_directory, filename)

        with open(file_path, "w") as f:
            f.write(content)
        retrieval_logger.info(f"Saved processed report to {file_path}")