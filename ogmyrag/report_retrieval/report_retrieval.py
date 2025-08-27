from datetime import datetime
import time
import json
import re
import argparse
import asyncio
import io
import os
import tempfile
import logging
from typing import Dict, List, Optional, Mapping, Any, Tuple
from threading import Thread

from google import genai
from google.genai import types
from openai import OpenAI

from .retrieval_storage   import RetrievalAsyncStorageManager
from ..report_scraper.models import ReportType
from ..report_retrieval.report_retrieval_util import clean_markdown_response
from ..prompts import PROMPT
from .report_chunker import index_markdown_with_pinecone
from ..storage.pinecone_storage import PineconeStorage

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
        pine: PineconeStorage,
        genai_model: str,
        genai_api_key: str,
        openai_api_key: str,
        dry_run: bool = True
    ):
        self.storage   = storage
        self.pine = pine
        self.genai_model   = genai_model
        self.genai_api_key = genai_api_key
        self.client = genai.Client(api_key=self.genai_api_key)
        self.openai_key    = openai_api_key
        self.dry_run       = dry_run
        self.rpm_limit = 5
        self.win_start = time.time()
        self.reqs_in_window = 0

    
    async def parse_report(
            self,
            company: str,
            report_type: ReportType,
            year: Optional[int] = None,
            prompt: dict = PROMPT,
            download_local: bool = True,
            forced_process: bool = False
    ) -> None:
        year_tag = f"_{year}" if year and year != "N/A" else ""
        year = str(year) if year is not None else "N/A"
        company = company.replace(" ", "_").upper().strip()

        processed_location = f"{company}_{report_type.name}{year_tag}"
        report_collection = report_type.collection
        disclosure_collection = "company_disclosures"
        
        # Fetch raw pdfs
        self.storage.use_collection(report_collection)
        raw_docs = await self.storage.get_raw_reports(company, year)
        if not raw_docs:
            retrieval_logger.info(f"No raw reports found for {company} {report_type.keyword} {year}")
            raise ValueError(f"No raw reports found for {company} {report_type.keyword} {year}")
        
        mode, docs_to_process = self.determine_mode(raw_docs, company, report_type, year, forced_process)

        if report_type.collection == "ipo_reports":
            final_md = await self.parse_ipo(company, year, report_type, docs_to_process, mode)
        elif report_type.collection == "annual_reports":
            final_md = await self.parse_annual(company, year, report_type, docs_to_process, mode)

        processed_md_name = f"{processed_location}.md"
        await self.mark_processed(company, report_type, year, processed_md_name)

        # download to local
        if download_local:
            self.download_to_local(company, processed_md_name, final_md)

        
        

    
    async def parse_annual(
            self,
            company: str,
            year: int,
            report_type: ReportType,
            docs: List[Mapping[str, Any]],
            mode: str
    ) -> str:
        """
        Annual report parsing with mode-aware behavior:
        - fresh: extract definitions, TOC, and sections from PDFs (year-scoped)
        - amend: update existing sections using amended PDFs; keep existing definitions
        - skip: load previously stored content; no uploads or generations
        """

        if mode == "skip":
            retrieval_logger.info("Skipping processing, using existing content.")
            self.storage.use_collection("company_disclosures")
            return await self.storage.extract_combine_processed_content(company, year, report_type)

        # upload PDFs
        uploaded = await self.upload_pdfs(docs)

        if mode == "fresh":
            retrieval_logger.info("Fresh processing mode, extracting TOC.")

            # TOC extraction
            #await self.extract_definitions(company, report_type, docs, uploaded, year=year)
            sections = await self.extract_table_of_contents(company, report_type, docs, uploaded, year=year)

            # Section extraction
            contents = await self.extract_sections(company, report_type, docs, uploaded, sections, mode, year=year)

            # Combine all sections into a single Markdown string
            md = [f"# {company} {report_type.name} {year}\n"]
            for section, text in contents.items():
                md.append(text + "\n")

            return "\n".join(md)    #, contents
        
        if mode == "amend":
            retrieval_logger.info("Amend processing mode, updating existing sections.")

            sections = await self.extract_table_of_contents(company, report_type, docs, uploaded, year=year)
            contents = await self.extract_sections(company, report_type, docs, uploaded, sections, mode, year=year)

            # Combine all sections into a single Markdown string
            md = [f"# {company} {report_type.name} {year}\n"]
            for section, text in contents.items():
                md.append(text + "\n")

            return "\n".join(md)    #, contents
        
        # If we reach here, it means an unknown mode was provided
        retrieval_logger.error("Unknown processing mode: %s - defaulting to fresh", mode)

        # TOC extraction
        #await self.extract_definitions(company, report_type, docs, uploaded, year=year)
        sections = await self.extract_table_of_contents(company, report_type, docs, uploaded, year=year)

        # Section extraction
        contents = await self.extract_sections(company, report_type, docs, uploaded, sections, mode, year=year)

        # Combine all sections into a single Markdown string
        md = [f"# {company} {report_type.name} {year}\n"]
        for section, text in contents.items():
            md.append(text + "\n")

        return "\n".join(md)    #, contents
    

    
    async def parse_ipo(
            self, 
            company: str, 
            year: int, 
            report_type: ReportType, 
            docs: List[Mapping[str, Any]],
            mode: str,
        ) -> str:
        """
        IPO parsing with different mode handling.
        - fresh: extract definitions, TOC and sections from PDFs
        - amend: update existing sections using amended PDFs, keep existing definitions
        - skip: load previously processed content, no uploads and generations
        """
        if mode == "skip":
            retrieval_logger.info("Skipping processing, using existing content.")
            self.storage.use_collection("company_disclosures")
            return await self.storage.extract_combine_processed_content(company, year, report_type)
        
    
        # upload PDFs
        uploaded = await self.upload_pdfs(docs)

        if mode == "fresh":
            retrieval_logger.info("Fresh processing mode, extracting definitions and TOC.")

            # Definitions & TOC extraction
            await self.extract_definitions(company, report_type, docs, uploaded)
            sections = await self.extract_table_of_contents(company, report_type, docs, uploaded)

            # Section extraction
            contents = await self.extract_sections(company, report_type, docs, uploaded, sections, mode)

            # Combine all sections into a single Markdown string
            md = [f"# {company} {report_type.name}\n"]
            for section, text in contents.items():
                md.append(text + "\n")

            return "\n".join(md)    #, contents
        
        if mode == "amend":
            retrieval_logger.info("Amend processing mode, updating existing sections.")

            sections = await self.extract_table_of_contents(company, report_type, docs, uploaded)
            contents = await self.extract_sections(company, report_type, docs, uploaded, sections, mode)

            # Combine all sections into a single Markdown string
            md = [f"# {company} {report_type.name}\n"]
            for section, text in contents.items():
                md.append(text + "\n")

            return "\n".join(md)    #, contents
        

        # If we reach here, it means an unknown mode was provided
        retrieval_logger.error("Unknown processing mode: %s - defaulting to fresh", mode)

        # Definitions & TOC extraction
        await self.extract_definitions(company, report_type, docs, uploaded)
        sections = await self.extract_table_of_contents(company, report_type, docs, uploaded)

        # Section extraction
        contents = await self.extract_sections(company, report_type, docs, uploaded, sections, mode)

        # Combine all sections into a single Markdown string
        md = [f"# {company} {report_type.name}\n"]
        for section, text in contents.items():
            md.append(text + "\n")

        return "\n".join(md)    #, contents
   

    def determine_mode(
            self,
            raw_docs: List[Mapping[str, Any]],
            company: str,
            report_type: ReportType,
            year: str,
            forced: bool
    ) -> Tuple[str, List[Mapping[str, Any]]]:
        """
        Determine the processing mode based on existing documents.
        Returns a tuple of (mode, documents to upload).
        """
        processed_docs = [d for d in raw_docs if d.get("processed")]
        amended_docs = [d for d in raw_docs if d.get("is_amended")]
        original_docs = [d for d in raw_docs if not d.get("is_amended")]

        # already processed and no force
        if processed_docs and not forced:
            if not amended_docs:
                retrieval_logger.info("Already processed and up to date.")
                return "skip", []
            
            if original_docs and amended_docs:
                retrieval_logger.info("Originals exist; processing amendments branch.")
                return "amend", amended_docs

        retrieval_logger.info("Fresh processing of all docs.")
        return "fresh", raw_docs

    async def mark_processed(
            self,
            company: str,
            report_type: ReportType,
            year: str,
            processed_location: str
    ):
        """
        Mark the raw documents as processed and save the summary path.
        """
        self.storage.use_collection(report_type.collection)
        self.storage.update_many(
            {"company": company, "year": str(year)},
            {"processed": True, "summary_path": processed_location}
        )


    async def upload_pdfs(
            self,
            docs: List[Mapping[str, Any]]
    ) -> List[Any]:
        """
        Upload PDFs to GenAI and return the uploaded file IDs.
        """
        temp_files = []
        for d in docs:
            fid = d["file_id"]
            fn = d["filename"]
            retrieval_logger.info("     Uploading %s ...", fn)
            grid_out = await self.storage.fs_bucket.open_download_stream(fid)
            data = await grid_out.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(data)
            tmp.close()
            temp_files.append(tmp.name)

        uploaded_files = [self.client.files.upload(file=path) for path in temp_files]
        retrieval_logger.info("Uploaded %d PDFs", len(uploaded_files))
        return uploaded_files
    
    

    async def extract_definitions(
            self,
            company: str,
            report_type: ReportType,
            docs: List[Mapping[str, Any]],
            uploaded: List[Any],
            year: Optional[str] = None
    ) -> None:
        year_tag = f"_{year}" if year and year != "N/A" else ""
        key = f"{company}_{report_type.name}{year_tag}_WORD_DEFINITION"
        filter_query = {
            "name": key,
            "type": "CONSTRAINTS",
            "from_company": company
        }
        if year and year != "N/A":
            filter_query["year"] = str(year)

        self.storage.use_collection("constraints")
        if not await self.storage.check_exists(filter_query):
            # --- retry loop (max 3 attempts) + RPM ---
            attempts = 0
            definition_text = None

            while attempts < 3:
                attempts += 1
                # RPM window check
                now = time.time()
                elapsed = now - self.win_start
                if elapsed >= 60:
                    self.win_start = now
                    self.reqs_in_window = 0
                if self.reqs_in_window >= self.rpm_limit:
                    await asyncio.sleep(60 - (time.time() - self.win_start))
                    self.win_start = time.time()
                    self.reqs_in_window = 0

                try:
                    # Extract Definitions
                    definition_resp = self.client.models.generate_content(
                        model=self.genai_model,
                        contents=[*uploaded, PROMPT["DEFINITION PARSING"]]
                    )
                    definition_text = clean_markdown_response(definition_resp.text.strip())

                    # Extract token usage
                    usage = definition_resp.usage_metadata

                    retrieval_logger.info(
                        f"Definition tokens: prompt = {usage.prompt_token_count}, "
                        f"output = {usage.candidates_token_count}, total = {usage.total_token_count}"
                    )
                    break
                except Exception as e:
                    msg = str(e).lower()
                    # If rate-limited, sleep to next minute; else small backoff
                    if "429" in msg or "rate" in msg or "quota" in msg or "limit" in msg:
                        wait_s = max(0.5, 60 - (time.time() - self.win_start))
                    else:
                        wait_s = 1 if attempts == 1 else 2
                    retrieval_logger.warning("Definitions attempt %d failed: %s; sleeping %.1fs",
                                            attempts, e, wait_s)
                    await asyncio.sleep(wait_s)

            
            if definition_text:

                #retrieval_logger.info("Definition extracted: %s", definition_text)

                # store in 'constraints' collection
                update_query = {
                    "created_at": datetime.utcnow(),
                    "content": definition_text,
                    "published_at": docs[0]["announced_date"]
                }
                if year and year != "N/A":
                    update_query["year"] = year
                
                self.storage.update_many(filter_query, update_query)
                retrieval_logger.info("Saved constraints for %s", company)

            else:
                retrieval_logger.error("Definition extraction failed after retries; continuing.")

            
        else:
            retrieval_logger.info("Definitions already exist, skipping extraction.")



    async def extract_table_of_contents(
            self, 
            company: str,
            report_type: ReportType,
            docs: List[Mapping[str, Any]],
            uploaded: List[Any],
            year: Optional[str] = None
    ) -> List[str]:
        year_tag = f"_{year}" if year and year != "N/A" else ""
        key = f"{company}_{report_type.name}{year_tag}_TOC"
        filter_query = {
            "name": key,
            "type": "TOC",
            "from_company": company
        }
        if year and year != "N/A":
            filter_query["year"] = year

        self.storage.use_collection("company_disclosures")

        if not await self.storage.check_exists(filter_query):
            sections = []
            attempts = 0

            while attempts < 3:
                attempts += 1
                # RPM guard
                now = time.time()
                elapsed = now - self.win_start
                if elapsed >= 60:
                    self.win_start = now
                    self.reqs_in_window = 0
                if self.reqs_in_window >= self.rpm_limit:
                    await asyncio.sleep(60 - (time.time() - self.win_start))
                    self.win_start = time.time()
                    self.reqs_in_window = 0

                try:
                    self.reqs_in_window += 1
                    # Extract Table of Contents
                    toc_resp = self.client.models.generate_content(
                        model=self.genai_model,
                        contents=[*uploaded, PROMPT["TABLE OF CONTENT EXTRACTION"]]
                    )
                    cleaned = clean_markdown_response(toc_resp.text.strip())
                    try:
                        sections = json.loads(cleaned)
                    except Exception:
                        # accept fenced JSON
                        cleaned2 = re.sub(r"^```(?:json|markdown)?|```$", "", cleaned, flags=re.M).strip()
                        sections = json.loads(cleaned2)

                    # Extract token usage
                    usage = toc_resp.usage_metadata

                    retrieval_logger.info(
                        f"Definition tokens: prompt = {usage.prompt_token_count}, "
                        f"output = {usage.candidates_token_count}, total = {usage.total_token_count}"
                    )

                    retrieval_logger.info("Table of Contents extracted")
            
                    # store in 'company_disclosures' collection
                    update_query = {
                        "created_at": datetime.utcnow(),
                        "content": clean_markdown_response(toc_resp.text.strip()),
                        "published_at": docs[0]["announced_date"]
                    }
                    if year and year != "N/A":
                        update_query["year"] = year
                    
                    self.storage.update_many(filter_query, update_query)
                    retrieval_logger.info("Saved Table of Contents for %s", company)
                    break

                except Exception as e:
                    msg = str(e).lower()
                    if "429" in msg or "rate" in msg or "quota" in msg or "limit" in msg:
                        wait_s = max(0.5, 60 - (time.time() - self.win_start))
                    else:
                        wait_s = 1 if attempts == 1 else 2
                    retrieval_logger.warning("TOC attempt %d failed: %s; sleeping %.1fs",
                                            attempts, e, wait_s)
                    await asyncio.sleep(wait_s)

            if not sections:
                retrieval_logger.error("TOC extraction failed after retries; returning empty list.")

        else:
            retrieval_logger.info("Table of Contents already exists, skipping extraction.")
            sections = json.loads(await self.storage.retrieve_toc(filter_query))
            retrieval_logger.info("Sections to extract: %s", sections)

        return sections

    async def extract_sections(
            self,
            company: str,
            report_type: ReportType,
            docs: List[Mapping[str, Any]],
            uploaded: List[Any],
            sections: List[str],
            mode: str,
            year: Optional[str] = None,         
            embed_workers: int = 5,           
    ) -> Dict[str, str]:
        results: Dict[str, str] = {}

        year_tag = f"_{year}" if year and year != "N/A" else ""
        doc_type = "PROSPECTUS" if report_type.collection == "ipo_reports" else "ANNUAL_REPORT"

        # --- NEW: track success/failure ---
        success_sections: list[str] = []
        failed_sections: list[tuple[str, str]] = []  # (section, reason)

        # NEW: ensure shared RPM state + lock exist
        if not hasattr(self, "_rpm_lock"):
            self._rpm_lock = asyncio.Lock()
        if not hasattr(self, "win_start"):
            self.win_start = time.time()
        if not hasattr(self, "reqs_in_window"):
            self.reqs_in_window = 0
        if not hasattr(self, "rpm_limit"):
            self.rpm_limit = 5  # default if not set elsewhere

        # NEW: simple async RPM acquire using your existing counters
        async def rpm_acquire():
            while True:
                # compute wait outside of the lock to avoid blocking others
                async with self._rpm_lock:
                    now = time.time()
                    elapsed = now - self.win_start
                    if elapsed >= 60:
                        self.win_start = now
                        self.reqs_in_window = 0

                    if self.reqs_in_window < self.rpm_limit:
                        self.reqs_in_window += 1
                        wait_s = 0.0
                    else:
                        wait_s = max(0.01, 60 - (now - self.win_start))
                if wait_s <= 0:
                    return
                await asyncio.sleep(wait_s)

        # NEW: limit concurrency to 5 (or your rpm_limit)
        sem = asyncio.Semaphore(self.rpm_limit)
        embed_sem = asyncio.Semaphore(embed_workers)

        async def process_one(index: int, section: str):
            try:
                self.storage.use_collection("company_disclosures")
                filter_query = {
                    "name": f"{company}_{report_type.name}{year_tag}_SECTION_{index}",
                    "type": doc_type,
                    "from_company": company,
                    "section": section
                }
                if year and year != "N/A":
                    filter_query["year"] = year

                exists = await self.storage.check_exists(filter_query)

                if mode == "fresh":
                    need_to_extract = True
                elif mode == "amend":
                    need_to_extract = True
                else:
                    need_to_extract = not exists

                if mode == "amend" and exists:
                    base = await self.storage.retrieve_section(filter_query)
                    SECTION_PROMPT_AMEND = PROMPT["IPO SECTION PROMPT AMEND"] if report_type.collection == "ipo_reports" else PROMPT["ANNUAL REPORT SECTION PROMPT AMEND"]
                    prompt_text = SECTION_PROMPT_AMEND.format(base=base, section=section)
                else:
                    SECTION_PROMPT_FRESH = PROMPT["IPO SECTION PROMPT FRESH"] if report_type.collection == "ipo_reports" else PROMPT["ANNUAL REPORT SECTION PROMPT FRESH"]
                    prompt_text = SECTION_PROMPT_FRESH.format(section=section)

                content = None

                async with sem:  # NEW: at most 5 in flight
                    if need_to_extract:
                        attempts = 0
                        while attempts < 5:
                            attempts += 1

                            # NEW: global RPM guard (thread-safe via lock)
                            await rpm_acquire()

                            try:
                                retrieval_logger.info("Extracting section: %s", section)

                                # NEW: offload blocking call so we don't block the event loop
                                response = await asyncio.to_thread(
                                    self.client.models.generate_content,
                                    model=self.genai_model,
                                    contents=[*uploaded, prompt_text]
                                )
                                content = clean_markdown_response(response.text.strip())

                                usage = getattr(response, "usage_metadata", None)
                                if usage:
                                    retrieval_logger.info(
                                        "Definition tokens: prompt = %s, output = %s, total = %s",
                                        getattr(usage, "prompt_token_count", "?"),
                                        getattr(usage, "candidates_token_count", "?"),
                                        getattr(usage, "total_token_count", "?"),
                                    )

                                update_query = {
                                    "created_at": datetime.utcnow(),
                                    "is_parsed": True,
                                    "content": content,
                                    "published_at": docs[0]["announced_date"],
                                    "section": section
                                }
                                if year and year != "N/A":
                                    update_query["year"] = year

                                self.storage.update_many(filter_query, update_query)
                                retrieval_logger.info("Section: %s saved in DB", section)
                                success_sections.append(section)
                                break

                            except Exception as e:
                                msg = str(e).lower()
                                if "429" in msg or "rate" in msg or "quota" in msg or "limit" in msg:
                                    wait_s = max(0.5, 60 - (time.time() - self.win_start))
                                else:
                                    wait_s = 1 if attempts == 1 else 2
                                retrieval_logger.warning(
                                    "Section '%s' attempt %d failed: %s; sleeping %.1fs",
                                    section, attempts, e, wait_s
                                )
                                await asyncio.sleep(wait_s)

                        if content is None:
                            retrieval_logger.error("Section '%s' failed after retries.", section)
                            if exists:
                                content = await self.storage.retrieve_section(filter_query)
                                success_sections.append(section)

                            else:
                                content = f"# {section}\n\n[Extraction failed after retries]"
                                failed_sections.append((section, "extraction failed after retries"))

                    else:
                        retrieval_logger.info("Section %s already exists, updating content", section)
                        content = await self.storage.retrieve_section(filter_query)
                        success_sections.append(section)


                # ---------- NEW: chunk → embed → upsert (NO namespace) ----------
                async with embed_sem:
                    try:
                        retrieval_logger.info("Chunking, Embedding, Upserting: %s", section)
                        total = await index_markdown_with_pinecone(
                            self.pine,
                            content, 
                            company=company, 
                            report_type=report_type, 
                            year_tag=year_tag, 
                            doc_type=doc_type, 
                            index=index, 
                            section=section
                        )
                        retrieval_logger.info("Embedded & upserted %d chunks for section: %s", total, section)
                    except Exception as e:
                        retrieval_logger.warning("Chunk/embed/upsert failed for section '%s': %s", section, e)
                        

                results[section] = content

            except Exception as e:
                retrieval_logger.exception("Unhandled error for section '%s'", section)
                failed_sections.append((section, f"unhandled: {e}"))

        # NEW: fire off tasks instead of serial loop
        tasks = [asyncio.create_task(process_one(i, s)) for i, s in enumerate(sections, start=1)]
        #tasks = [asyncio.create_task(process_one(1, sections[15]))] if sections else []
        await asyncio.gather(*tasks)

        # --- Summary logging ---
        total = len(sections)
        ok = len(success_sections)
        ko = len(failed_sections)
        retrieval_logger.info("Extraction summary: %d/%d sections succeeded, %d failed.", ok, total, ko)

        if failed_sections:
            for s, reason in failed_sections:
                retrieval_logger.info("FAILED section: %s | reason: %s", s, reason)

        retrieval_logger.info("All sections extracted.")
        return results
        


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


    def download_to_local(self, company: str, filename: str, content: str) -> None:
        company_directory = os.path.join("./processed_report", company)
        os.makedirs(company_directory, exist_ok=True)

        # Create full file path
        file_path = os.path.join(company_directory, filename)

        with open(file_path, "w") as f:
            f.write(content)
        retrieval_logger.info(f"Saved processed report to {file_path}")