from datetime import datetime
import json
import re
import argparse
import asyncio
import io
import os
import tempfile
import logging
from typing import List, Optional, Mapping, Any
from threading import Thread

from google import genai
from google.genai import types
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
            retrieval_logger.info(f"No raw reports found for {company} {report_type.keyword} {year}")
            raise ValueError(f"No raw reports found for {company} {report_type.keyword} {year}")
        
        amended_docs = [d for d in raw_docs if d.get("is_amended")]
        original_docs = [d for d in raw_docs if not d.get("is_amended")]

        # if processed summary is existed
        if processed_md and not forced_process:
            # if no amendments, mark all raw as processed and return existing summary
            if not amended_docs:
                self.storage.use_collection(report_collection)
                retrieval_logger.info("Processed report found.")
                self.storage.update_many(
                    {"company": company, "year": str(year)},
                    {"processed": True, "summary_path": summary_fn,}
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
            if original_docs and amended_docs:
                # phase 1: process originals
                retrieval_logger.info("Performing Phase 1: Fresh Branch...")
                base_md = await self.generate_response_with_docs(original_docs, prompt)
                retrieval_logger.info("Performing Phase 2: Amend Branch...")
                to_upload = amended_docs
                mode = "amend"
            else:
                # no processed summary yet, fresh process of all raw PDFs
                retrieval_logger.info("Performing Fresh Branch...")
                to_upload = raw_docs
                mode = "fresh"

        
        if mode == "amend":
            full_prompt = (
                "Here is the existing summary:\n\n"
                    + base_md
                    + "\n\nNow update it to incorporate these amendments:\n\n"
                    + prompt
            )
        else:
            full_prompt = prompt

        # upload PDFs and process with genai
        md = await self.generate_response_with_docs(to_upload, full_prompt)
        retrieval_logger.info("Finished processing.")

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



    async def parse_report(
            self,
            company: str,
            report_type: ReportType,
            year: Optional[int] = None,
            prompt: dict = PROMPT,
            download_local: bool = True,
            forced_process: bool = False
    ) -> None:
        year = str(year) if year is not None else "N/A"
        company = company.replace(" ", "_").upper().strip()

        processed_location = f"{company}_{report_type.name}"
        report_collection = report_type.collection
        disclosure_collection = "company_disclosures"
        
        # Fetch raw pdfs
        self.storage.use_collection(report_collection)
        raw_docs = await self.storage.get_raw_reports(company, year)
        if not raw_docs:
            retrieval_logger.info(f"No raw reports found for {company} {report_type.keyword} {year}")
            raise ValueError(f"No raw reports found for {company} {report_type.keyword} {year}")
        
        processed_docs = [d for d in raw_docs if d.get("processed")]
        amended_docs = [d for d in raw_docs if d.get("is_amended")]
        original_docs = [d for d in raw_docs if not d.get("is_amended")]

        

        # if reports already processed
        if processed_docs and not forced_process:
            # and no amendment
            if not amended_docs:
                self.storage.use_collection(report_collection)
                retrieval_logger.info("Processed report found.")
                self.storage.update_many(
                    {"company": company, "year": str(year)},
                    {"processed": True, "summary_path": processed_location}
                )

                # download to local
                if download_local:
                    # extract and combine all from 'company_disclosures' into md
                    self.storage.use_collection(disclosure_collection)
                    processed_md = await self.storage.extract_combine_processed_content(company, year, report_type)
                    self.download_to_local(company, f"{processed_location}.md", processed_md)

                return
            
            # re-process only the amended PDFs
            else:
                retrieval_logger.info("Performing Amend Branch...")
                # extract and combine original content from 'company_disclosures' into base_md
                to_upload = amended_docs
                mode = "amend"

        else:
            if original_docs and amended_docs:
                # phase 1: process originals
                retrieval_logger.info("Performing Phase 1: Fresh Branch...")
                retrieval_logger.info("Performing Phase 2: Amend Branch...")
                to_upload = amended_docs
                mode = "amend"
            else:
                # no processed summary yet, fresh process of all raw PDFs
                retrieval_logger.info("Performing Fresh Branch...")
                to_upload = raw_docs
                mode = "fresh"



        if report_type.collection == "ipo_reports":
            md = await self.parse_ipo(company, year, report_type, to_upload, mode)
        elif report_type.collection == "annual_reports":
            md = await self.parse_annual(company, year, report_type, to_upload, mode)

        # mark the original reports to 'processed'
        self.storage.use_collection(report_collection)
        self.storage.update_many(
            {"company": company, "year": str(year)},
            {"processed": True, "summary_path": processed_location}
        )
        
        # chunk and replce old vectors in Pinecone
        chunks = chunk_markdown(md)
        if not self.dry_run:
            self.embedder.upsert_chunks(chunks, company, year)

        else:
            retrieval_logger.info("Dry run enabled, skipping chunk upsert.")

        # download to local
        if download_local:
            self.download_to_local(company, f"{processed_location}.md", md)
    







    

    
    async def parse_ipo(
            self, 
            company: str, 
            year: int, 
            report_type: ReportType, 
            docs: List[Mapping[str, Any]],
            mode: str = "fresh",
            prompt: dict = PROMPT
        ) -> str:
        
        self.storage.use_collection(report_type.collection)

        client = genai.Client(api_key=self.genai_api_key)


        
        temp_paths = []

        # Upload all PDFs to GenAI
        for doc in docs:
            fid = doc["file_id"]
            fn = doc["filename"]
            retrieval_logger.info("     Uploading %s ...", fn)
            grid_out = await self.storage.fs_bucket.open_download_stream(fid)
            data = await grid_out.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(data)
            tmp.close()
            temp_paths.append(tmp.name)

        uploaded_files = [client.files.upload(file=path) for path in temp_paths]
    

        retrieval_logger.info("Uploaded %d PDFs", len(temp_paths))

        # DEFINITION EXTRACTION
        filter_query = {
            "name": f"{company}_{report_type.name}_WORD_DEFINITION",
            "type": "CONSTRAINTS",
            "from_company": company,
        }
        self.storage.use_collection("constraints")
        existing = await self.storage.check_exists(filter_query)
        if not existing:
            # Extract Definitions
            definition_resp = client.models.generate_content(
                model=self.genai_model,
                contents=[*uploaded_files, PROMPT["DEFINITION PARSING"]]
            )
            definition_text = clean_markdown_response(definition_resp.text.strip())

            retrieval_logger.info("Definition extracted: %s", definition_text)

            # store in 'constraints' collection
            self.storage.use_collection("constraints")
            update_query = {
                "created_at": datetime.utcnow(),
                "content": definition_text,
                "published_at": docs[0]["announced_date"]
            }
            
            self.storage.update_many(filter_query, update_query)
            retrieval_logger.info("Saved constraints for %s", company)

            # Extract token usage
            usage = definition_resp.usage_metadata

            retrieval_logger.info(f"     Prompt Tokens: {usage.prompt_token_count}")
            retrieval_logger.info(f"     Output Tokens: {usage.candidates_token_count}")
            retrieval_logger.info(f"     Total Tokens: {usage.total_token_count}")

        else:
            retrieval_logger.info("Definitions already exist, skipping extraction.")
        
    
        # TABLE OF CONTENTS EXTRACTION
        filter_query = {
            "name": f"{company}_{report_type.name}_TOC",
            "type": "TOC",
            "from_company": company
        }
        self.storage.use_collection("company_disclosures")
        existing = await self.storage.check_exists(filter_query)
        if not existing:
            # Extract Table of Contents
            toc_resp = client.models.generate_content(
                model=self.genai_model,
                contents=[*uploaded_files, PROMPT["TABLE OF CONTENT EXTRACTION"]]
            )
            sections = json.loads(clean_markdown_response(toc_resp.text.strip()))
            retrieval_logger.info("Table of Contents extracted")
            
            
            
            # store in 'company_disclosures' collection
            update_query = {
                "created_at": datetime.utcnow(),
                "content": clean_markdown_response(toc_resp.text.strip()),
                "published_at": docs[0]["announced_date"]
            }
            self.storage.update_many(filter_query, update_query)
            retrieval_logger.info("Saved Table of Contents for %s", company)

            # Extract token usage
            usage = toc_resp.usage_metadata

            retrieval_logger.info(f"     Prompt Tokens: {usage.prompt_token_count}")
            retrieval_logger.info(f"     Output Tokens: {usage.candidates_token_count}")
            retrieval_logger.info(f"     Total Tokens: {usage.total_token_count}")

        else:
            retrieval_logger.info("Table of Contents already exists, skipping extraction.")
            sections = json.loads(await self.storage.retrieve_toc(filter_query))
            retrieval_logger.info("Sections to extract: %s", sections)


        # SECTION EXTRACTION
        # loop over each section and extract content
        results = {}
        index = 1
        for section in sections:
            if mode == "fresh":
                self.storage.use_collection("company_disclosures")
                filter_query = {
                    "name": f"{company}_{report_type.name}_SECTION_{index}",
                    "type": "PROSPECTUS",
                    "from_company": company,
                    "section": section
                }
                
                if not await self.storage.check_exists(filter_query):
                    # if not exists, insert new section
                    retrieval_logger.info("Extracting section: %s", section)
                    section_prompt = f'''
                        Section: "{section}"

                        Extract only the content under this exact heading—preserve 100% of the meaning.
                        For any tables or figures in this section, fully interpret them with page number references.
                        Strip headers, footers, and page numbers.
                        Return only the plain text of this section—no extra commentary.
                        '''
                    response = client.models.generate_content(
                        model=self.genai_model,
                        contents=[*uploaded_files, section_prompt]
                    )
                    content = clean_markdown_response(response.text.strip())
                    results[section] = content

                    usage = response.usage_metadata

                    retrieval_logger.info(f"     Prompt Tokens: {usage.prompt_token_count}")
                    retrieval_logger.info(f"     Output Tokens: {usage.candidates_token_count}")
                    retrieval_logger.info(f"     Total Tokens: {usage.total_token_count}")

                    filter_query = {
                        "name": f"{company}_{report_type.name}_SECTION_{index}",
                        "type": "PROSPECTUS",
                        "from_company": company
                    }
                    update_query = {
                        "created_at": datetime.utcnow(),
                        "is_parsed": True,
                        "content": content,
                        "published_at": docs[0]["announced_date"],
                        "section": section
                    }


                    self.storage.update_many(filter_query, update_query)
                    retrieval_logger.info("Saved section: %s", section)
                else:
                    # if exists, update existing section
                    retrieval_logger.info("Section %s already exists, updating content", section)
            
            elif mode == "amend":
                self.storage.use_collection("company_disclosures")
                filter_query = {
                    "name": f"{company}_{report_type.name}_SECTION_{index}",
                    "type": "PROSPECTUS",
                    "from_company": company,
                    "section": section
                }
                if await self.storage.check_exists(filter_query):
                    # if exists, update existing section
                    retrieval_logger.info("Retrieving existing section: %s", section)
                    base_content = await self.storage.retrieve_section(filter_query)

                    section_prompt = f'''Here is the existing summary:\n\n
                    
                        {base_content}

                        Now update it to incorporate these amendments:\n\n
                        
                        Section: "{section}"

                        Extract only the content under this exact heading—preserve 100% of the meaning.
                        For any tables or figures in this section, fully interpret them with page number references.
                        Strip headers, footers, and page numbers.
                        Return only the plain text of this section—no extra commentary.
                    '''
                    retrieval_logger.info("Updating section: %s", section)

                else:
                    # if not exists, insert new section
                    retrieval_logger.info("Extracting section: %s", section)
                    section_prompt = f'''
                        Section: "{section}"

                        Extract only the content under this exact heading—preserve 100% of the meaning.
                        For any tables or figures in this section, fully interpret them with page number references.
                        Strip headers, footers, and page numbers.
                        Return only the plain text of this section—no extra commentary.
                        '''
                    

                response = client.models.generate_content(
                    model=self.genai_model,
                        ontents=[*uploaded_files, section_prompt]
                )
                content = clean_markdown_response(response.text.strip())
                results[section] = content

                usage = response.usage_metadata

                retrieval_logger.info(f"     Prompt Tokens: {usage.prompt_token_count}")
                retrieval_logger.info(f"     Output Tokens: {usage.candidates_token_count}")
                retrieval_logger.info(f"     Total Tokens: {usage.total_token_count}")

                filter_query = {
                    "name": f"{company}_{report_type.name}_SECTION_{index}",
                    "type": "PROSPECTUS",
                    "from_company": company
                }
                update_query = {
                    "created_at": datetime.utcnow(),
                    "is_parsed": True,
                    "content": content,
                    "published_at": docs[0]["announced_date"],
                    "section": section
                }

                self.storage.update_many(filter_query, update_query)
                retrieval_logger.info("Saved section: %s", section)


            index += 1


        retrieval_logger.info("All sections extracted.")


        # combine all into single md and return
        md = [f"# {company} {report_type.name}\n"]
        for section, text in results.items():
            md.append(f"## {section}\n\n{text}\n")

        return "\n".join(md)






    async def generate_response_with_docs(self, docs: List[Mapping[str, Any]], prompt: str):
        # upload PDFs and process with genai
        genai.configure(api_key=self.genai_api_key)
        uploaded_pdfs = []

        for doc in docs:
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
        retrieval_logger.info("Generating...")
        response = model.generate_content([*uploaded_pdfs, prompt])

        # Extract token usage
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count
        output_tokens = usage.candidates_token_count
        total_tokens = usage.total_token_count

        retrieval_logger.info(f"     Prompt Tokens: {input_tokens}")
        retrieval_logger.info(f"     Output Tokens: {output_tokens}")
        retrieval_logger.info(f"     Total Tokens: {total_tokens}")
        
        return clean_markdown_response(response.text)
    



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