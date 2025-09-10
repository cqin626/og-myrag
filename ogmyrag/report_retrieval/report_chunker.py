import asyncio
import json
from lxml import html as lxml_html
from markdown import markdown
from typing import Any, List, Dict, Optional
import hashlib
import logging
from ..storage.pinecone_storage import PineconeStorage
from ogmyrag.base import PineconeStorageConfig

query_logger = logging.getLogger("query")
retrieval_logger = logging.getLogger("retrieval")

# ---------- tiny, fast DOM chunker ----------
def _text_of(node) -> str:
    return " ".join(t.strip() for t in node.itertext() if t and t.strip())

def _split_big_block(s: str, max_chars: int) -> List[str]:
    if len(s) <= max_chars:
        return [s]
    out, start = [], 0
    while start < len(s):
        end = min(start + max_chars, len(s))
        cut = end
        for i in range(end, max(start, end - 200), -1):
            if s[i-1] in ".!?;:\n":
                cut = i
                break
        if cut == end and end < len(s):
            sp = s.rfind(" ", start, end)
            if sp > start + 50:
                cut = sp
        out.append(s[start:cut].strip())
        start = cut
    return [p for p in out if p]

def _pack_blocks(blocks: List[str], title: str, h_level: int, max_chars: int,
                 min_chars: int, overlap: int) -> List[Dict]:
    chunks, buf, length = [], [], 0

    def flush(final=False):
        nonlocal buf, length
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        if text:
            chunks.append({"content": text, "section_title": title, "h_level": h_level})
        if not final and overlap > 0 and text:
            tail = text[-overlap:]
            buf, length = [tail], len(tail)
        else:
            buf, length = [], 0

    for b in blocks:
        blen = len(b) + 2
        if length + blen <= max_chars or length < min_chars:
            buf.append(b); length += blen
        else:
            flush()
            buf, length = [b], len(b) + 2
    flush(final=True)
    return chunks

def chunk_html_dom(html_str: str, *, max_chars=1200, min_chars=400, overlap=150, atomic_by_heading: bool = True) -> List[Dict]:
    tree = lxml_html.fromstring(html_str)
    headings = tree.xpath("//h1|//h2|//h3|//h4|//h5|//h6")
    if not headings:
        body = tree.find("body") or tree
        blocks = []
        for node in body.iterchildren():
            if node.tag in {"script", "style", "noscript"}: 
                continue
            txt = _text_of(node)
            if txt:
                blocks.extend(_split_big_block(txt, max_chars))
        return _pack_blocks(blocks, "ROOT", 0, max_chars, min_chars, overlap)

    chunks: List[Dict] = []
    for h in headings:
        level = int(h.tag[1])
        title = _text_of(h) or h.tag.upper()
        blocks: List[str] = []
        for sib in h.itersiblings():
            if sib.tag in {"script", "style", "noscript"}:
                continue
            if sib.tag in {"h1","h2","h3","h4","h5","h6"} and int(sib.tag[1]) <= level:
                break
            txt = _text_of(sib)
            if txt:
                if len(txt) > max_chars:
                    blocks.extend(_split_big_block(txt, max_chars))
                else:
                    blocks.append(txt)

        """# if atomic, emit ONE chunk per heading (join all collected blocks)
        if atomic_by_heading:
            content = "\n\n".join(blocks).strip()
            chunks.append({"content": content, "section_title": title, "h_level": level})
        else:
            # original behavior (size-aware packing with overlap)"""
        chunks.extend(_pack_blocks(blocks, title, level, max_chars, min_chars, overlap))
            
    for i, c in enumerate(chunks): 
        c["seq"] = i
    return chunks

# ---------- builder: Pinecone items from chunks ----------
def build_pinecone_items_from_chunks(
    *,
    company: str,
    report_type,
    year_tag: str,
    doc_type: str,
    index: int,                 # section index (e.g., 1..N)
    section: str,               # section title
    chunks: List[Dict],         # each: {"content": "...", ...}
) -> List[Dict[str, Any]]:
    """
    Shapes chunks into items for PineconeStorage.create_vectors_without_namespace().
    Each item: {'id', 'name', 'metadata'}  (NO 'namespace')
    """

    items: List[Dict[str, Any]] = []
    for k, c in enumerate(chunks, start=1):  # 1-based chunk numbering
        vid = f"{company}_{report_type.name}{year_tag}_SECTION_{index}_CHUNK_{k}"
        items.append({
            "id": vid,                 # Pinecone vector id
            "name": c["content"],      # text to embed
            "metadata": {              # <-- exactly what you asked for   
                "type": doc_type,
                "from_company": company,
                "year": year_tag,
                "section": section,
                "chunk": k,
                "text": c["content"]
            }
        })
    return items

# ---------- end-to-end helper that uses your PineconeStorage ----------
async def index_markdown_with_pinecone(
    pine: PineconeStorage,
    pinecone_config: PineconeStorageConfig,
    md_text: str,
    *,
    company: str,
    report_type,
    year_tag: str,
    doc_type: str,
    index: int,                 # section index (e.g., 1..N)
    section: str,
    max_chars: int = 1500,
    min_chars: int = 400,
    overlap: int = 150,
    embed_batch: int = 16,          # controls concurrency inside create_vectors()
    ensure_catalog: bool = True
) -> int:
    """
    Convert MD -> HTML once, chunk via DOM, then embed+upsert via PineconeStorage.
    Runs embeddings in parallel inside each batch (your class uses tqdm_asyncio.gather).
    Return: number of chunks indexed.
    """
    # Hard-delete previous vectors for this section in the default namespace ("")
    try:
        await asyncio.to_thread(
            pine.pinecone.Index(pinecone_config["index_name"]).delete,
            filter={
                "from_company": company,
                "type": doc_type,
                "year": year_tag,
                "section": section,
            },
            namespace="",                  # default namespace
        )
    except Exception as e:
        # First run: namespace may not exist yet → ignore this specific 404
        if e.status == 404 and "Namespace not found" in str(e):
            retrieval_logger.debug("Default namespace not found yet; skipping delete.")
        else:
            raise

    html_str = markdown(md_text, extensions=["tables", "fenced_code"])
    
    chunks = chunk_html_dom(html_str, max_chars=max_chars, min_chars=min_chars, overlap=overlap)

    items = build_pinecone_items_from_chunks(
        company=company, 
        report_type=report_type, 
        year_tag=year_tag, 
        doc_type=doc_type, 
        index=index, 
        section=section, 
        chunks=chunks
    )

    # Send in batches so you control embedding concurrency (each call spawns parallel tasks)
    total = 0
    for i in range(0, len(items), embed_batch):
        batch = items[i:i+embed_batch]
        await pine.get_index(pinecone_config["index_name"]).upsert_vectors(batch)  # <- uses your class; embeds concurrently + upserts
        total += len(batch)


    # Only after successful chunk upserts, ensure company exists in catalog namespace
    if ensure_catalog and company:
        try:
            comp_vec = await pine._embed_text(company)  # match your index dims
            await asyncio.to_thread(
                pine.pinecone.Index(pinecone_config["index_name"]).upsert,
                vectors=[{
                    "id": f"company::{company}",
                    "values": comp_vec,
                    "metadata": {"from_company": company},
                }],
                namespace="company-catalog",
            )
        except Exception:
            # Non-fatal; catalog sync failure shouldn't break the main indexing flow
            pass
        
    return total


async def rag_answer_with_company_detection(
    pine: PineconeStorage,
    pinecone_config: PineconeStorageConfig,
    *,
    query: Optional[str] = None,
    top_k: int = 10,
    data_namespace: str = "",                 # your chunk namespace (default "")
    catalog_namespace: str = "company-catalog",
    small_model: str = "gpt-5-nano",         # for company detection
    answer_model: str = "gpt-5-nano",             # for final grounded answer
    # optional extra narrowing (must match your stored metadata)
    doc_type: Optional[str] = None,
    report_type_name: Optional[str] = None,
    year: Optional[str] = None,
    # tuning
    max_company_candidates: int = 500,        # cap company list to keep prompt small
    max_context_chars: int = 6000,            # cap context passed to the answer model
    score_threshold: Optional[float] = None,  # drop low scores if desired
    max_concurrency: int = 4,
    # NEW: debug knobs
    return_hits: bool = False,
    hits_per_subquery: int = 5,
    hits_preview_chars: int = 240,
) -> Dict[str, Any]:
    """
        End-to-end multi-step RAG (minimal-changes version):
        0) Receives a single query string (from user_query | query).
        1) Read company names from Pinecone catalog namespace (1 vector per company).
        2) Use a small LLM to (a) decompose the user query into sub-queries (if needed),
            and (b) for each sub-query, detect/normalize a company mention.
        3) For each sub-query, retrieve top-k chunks from data namespace with exact metadata filter (if detected).
        4) For each sub-query, call a bigger LLM to produce a grounded answer using only retrieved chunks.
        5) Synthesize a single final answer from all per-sub-query answers.
        6) Return {"RAG_RESPONSE": <final answer string>}.

        Returns:
        { "RAG_RESPONSE": str }
    """
    def _clip(txt: str, n: int = 300) -> str:
        txt = (txt or "").replace("\n", " ").strip()
        return txt if len(txt) <= n else txt[:n] + "…"
    
    def _fmt_score(s) -> str:
        try:
            return f"{float(s):.3f}"
        except Exception:
            return "n/a"
        
    # helper for compact hit projection (used only if return_hits=True)
    def _project_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        keep = ("id", "score", "company", "section", "chunk_no", "year", "type")
        out = []
        for h in hits:
            item = {k: h.get(k) for k in keep}
            item["snippet"] = h.get("text") or ""
            out.append(item)
        return out
    
    # NEW: unify single input query
    user_query = (query or "").strip()
    query_logger.info("RAG start | query=%r | top_k=%d", user_query, top_k)
    


    # ---------------- (1) List companies from the catalog namespace ----------------
    companies: List[str] = []
    try:
        # pages: generator of lists of IDs
        try:
            pages = await asyncio.to_thread(
                lambda: list(pine.pinecone.Index(pinecone_config["index_name"]).list(namespace=catalog_namespace, prefix="company::", limit=99))
            )
        except Exception as e:
            query_logger.warning("list(namespace=%r) failed: %s; falling back to list() without namespace",
                                    catalog_namespace, e)
            pages = await asyncio.to_thread(
                lambda: list(pine.pinecone.Index(pinecone_config["index_name"]).list(prefix="company::", limit=1000))
            )

        # flatten list-of-lists → ids
        ids = [vid for page in pages for vid in (page or []) if vid]

        seen = set()
        for i in range(0, len(ids), 100):
            batch_ids = ids[i:i+100]
            try:
                fetched = await asyncio.to_thread(
                    pine.pinecone.Index(pinecone_config["index_name"]).fetch, ids=batch_ids, namespace=catalog_namespace
                )
            except Exception as e:
                query_logger.warning(
                    "fetch(namespace=%r) failed: %s; retrying without namespace",
                    catalog_namespace, e
                )
                fetched = await asyncio.to_thread(pine.pinecone.Index(pinecone_config["index_name"]).fetch, ids=batch_ids)

            vecs = (
                fetched.get("vectors") if isinstance(fetched, dict)
                else getattr(fetched, "vectors", None)
            ) or {}

            # normalize to an iterator of (id, record)
            if isinstance(vecs, dict):
                it = vecs.items()                      # {id: {..}} or {id: Vector}
            elif isinstance(vecs, (list, tuple)):
                it = [(getattr(v, "id", None), v) for v in vecs]   # [Vector, ...]
            else:
                it = []

            for vid, rec in it:
                # metadata for dict or Vector object
                meta = (
                    rec.get("metadata") if isinstance(rec, dict)
                    else getattr(rec, "metadata", None)
                ) or {}

                name = (meta.get("from_company") or "").strip()

                # fallback: parse from the id like "company::ACME_INC"
                if not name:
                    rid = vid if isinstance(vid, str) else getattr(rec, "id", None)
                    if isinstance(rid, str) and "::" in rid:
                        name = rid.split("::", 1)[1].strip()

                if name:
                    seen.add(name)

        companies = sorted(seen)

    except Exception as e:
        query_logger.exception("Catalog company extraction failed")  # <- real stacktrace
        companies = []

    query_logger.info("Catalog companies (%d): %s", len(companies), companies)
    
    # ---------------- (2a) Decompose the user query into sub-queries ----------------
    # NEW: ask a small model to break the single query into atomic sub-queries
    
    subqueries: List[str] = [user_query]  # default to single if decomposition fails
    try:
        decompose_system = (
            """You will be given a single user query. Decide if it should be decomposed into multiple
            atomic, answerable sub-queries. Output STRICT JSON with a single key:
            {"subqueries": ["...", "...", "..."]}

            Rules:
            - If the query clearly asks multiple distinct things, split them.
            - Keep each sub-query self-contained and grammatical.
            - Preserve constraints (years, names, sections) inside each sub-query.
            - If no decomposition is needed, return the original query as a one-element list.
            - Do not add facts. Do not mention companies unless the user does.
            """
        )
        dec = await pine.openai.chat.completions.create(
            model=small_model,
            messages=[
                {"role": "system", "content": decompose_system},
                {"role": "user", "content": user_query},
            ],
            response_format={"type": "json_object"},
        )
        raw = dec.choices[0].message.content or "{}"
        obj = json.loads(raw)
        sq = [s.strip() for s in (obj.get("subqueries") or []) if isinstance(s, str) and s.strip()]
        if sq:
            subqueries = sq
    except Exception as e:
        query_logger.warning("Query decomposition failed: %s; proceeding with single query.", e)

    query_logger.info("Sub-queries (%d): %s", len(subqueries), subqueries)
    
    # ---------------- helper: per-subquery RAG ----------------
    async def _run_rag_for_one_subquery(one_query: str) -> Dict[str, Any]:
        company_used: Optional[str] = None
        detect_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
        search_query = one_query

        # ---- (2b) Detect/normalize company with a small LLM (per sub-query) ----
        if companies:
            detect_system = (
                """You will be given a user query and a list of CANONICAL company names.
                Return strict JSON with two keys:
                1) "companies": array of exact canonical names referenced by the query;
                2) "normalized_query": the query rewritten for semantic search with ALL company mentions removed
                   while remaining grammatical and self-contained.

                Company-matching rules (case-insensitive):
                • Match full canonical name OR a meaningful substring/abbreviation.
                • Before matching, normalize both sides by removing punctuation, extra spaces, and common corporate suffixes
                  (Holdings, Berhad, Bhd, Sdn Bhd, Ltd, Limited, PLC, Inc, Co, Corp, Corporation, Company).
                • Substring must be ≥ 4 alphanumeric characters. Do NOT invent names.

                Normalized-query rules:
                • Replace any detected company mentions (and their possessives) with “the company” if needed for grammar.
                • Preserve user intent; never add facts. Keep years, labels, numbers, constraints.
                • If no company is detected, return the original query.

                Output EXACT JSON, e.g.:
                {"companies":["ACME_BERHAD"], "normalized_query":"What is the mission of the company?"}"""
            )
            detect_msgs = [
                {"role": "system", "content": detect_system},
                {"role": "user", "content": f"COMPANIES: {companies}\n\nQUERY: {one_query}"},
            ]
            try:
                det = await pine.openai.chat.completions.create(
                    model=small_model,
                    messages=detect_msgs,
                    response_format={"type": "json_object"},
                )
                u = getattr(det, "usage", None)
                if u:
                    detect_usage["prompt_tokens"] = getattr(u, "prompt_tokens", None)
                    detect_usage["completion_tokens"] = getattr(u, "completion_tokens", None)
                    detect_usage["total_tokens"] = getattr(u, "total_tokens", None)

                raw = det.choices[0].message.content or "{}"
                obj = json.loads(raw)

                found = (obj.get("companies") or [])
                if found:
                    company_used = str(found[0]).strip()

                llm_norm = (obj.get("normalized_query") or "").strip()
                search_query = llm_norm or one_query
            except Exception as e:
                query_logger.warning("Company detection failed for sub-query %r: %s", one_query, e)
                company_used = None
                search_query = one_query

        query_logger.info("Detected company for sub-query %r: %r", one_query, company_used)
        if search_query != one_query:
            query_logger.info("Search query normalized: %r → %r", one_query, search_query)
        else:
            query_logger.info("Search query unchanged for this sub-query.")

        # ---- (3) Retrieve top-k chunks from data namespace ----
        flt: Dict[str, Any] = {}
        if company_used:
            flt["from_company"] = company_used
        if doc_type:
            flt["type"] = doc_type
        if report_type_name:
            flt["report_type_name"] = report_type_name
        if year:
            flt["year"] = year

        query_logger.info("Query filter (sub-query): %s", flt or "{}")

        try:
            q_emb = await pine._embed_text(search_query)
            result = pine.pinecone.Index(pinecone_config["index_name"]).query(
                vector=q_emb,
                top_k=top_k,
                include_metadata=True,
                namespace=data_namespace,
                filter=flt or None,
            )
            matches = (result.get("matches") if isinstance(result, dict)
                       else getattr(result, "matches", [])) or []
        except Exception as e:
            query_logger.warning("Vector query failed: %s", e)
            matches = []

        hits: List[Dict[str, Any]] = []
        for m in matches:
            meta = m.get("metadata") or {}
            hit = {
                "id": m.get("id"),
                "score": m.get("score"),
                "text": meta.get("text") or meta.get("chunk_text") or "",
                "section": meta.get("section"),
                "company": meta.get("from_company"),
                "type": meta.get("type"),
                "chunk_no": meta.get("chunk_no"),
                "year": meta.get("year"),
                "metadata": meta,
            }
            if score_threshold is None or (hit["score"] is not None and hit["score"] >= score_threshold):
                hits.append(hit)
        hits.sort(key=lambda h: (h["score"] is not None, h["score"]), reverse=True)
        hits = hits[:top_k]

        # build (bounded) context string
        context = "\n\n".join(
            f"[{i}] id={h.get('id')} · score={_fmt_score(h.get('score'))} · section={h.get('section') or ''} · company={h.get('company')}\n{(h.get('text') or '').strip()}"
            for i, h in enumerate(hits, start=1)
        )

        # ---- (4) Grounded answer using ONLY the retrieved chunks ----
        sys_prompt = (
            """You are a precise assistant. Use ONLY the provided context chunks. Be comprehensive and richly detailed, but strictly grounded in the sources.

            Rules:
            1) Group all context by company (use each chunk's 'company' metadata in the context header).
            2) NEVER mix facts across companies. If the user names a specific company, answer ONLY for that company and ignore others.
            3) If multiple companies appear AND the question is generic (no single company specified), evaluate each company separately:
            - If you have enough evidence for a company, produce an answer for that company.
            - If not enough evidence for that company, write exactly: "Not found in provided documents."
            4) No invention of facts. Every material claim (numbers, dates, names, products, events) must be supported by the provided chunks. If no company has sufficient evidence, the entire reply must be exactly: "Not found in provided documents."
            5) Be thorough yet economical: short paragraphs and tight bullets. Elaborate where the documents allow; never speculate.

            Sourcing & Evidence Policy:
            - Do NOT include citations or quotes in the output.
            - Ensure every material claim you state is supported by the provided chunks.
            - If sources conflict, briefly note the conflict in the Details section without citations.

            Handling Gaps:
            - If a needed detail is not stated, write: "Not stated in provided documents." (no speculation).
            - Do not generalize beyond what is explicitly supported.

            Output Format:
            - If answering for one company:
            ## Overview
            <2–4 sentences summarizing the supported answer. No citations.>

            ## Details
            - <concise fact or point. No citations.>
            - <concise fact or point. No citations.>

            - If answering for multiple companies:
            ### <Company Name>
            ## Overview
            <2–4 sentences. No citations.>

            ## Details
            - <concise fact or point. No citations.>
            - <concise fact or point. No citations.>

            Additional Constraints:
            - Neutral, analytical tone.
            - Do not include external knowledge or assumptions.
            - Preserve original numeric formatting (commas, decimals, signs, currencies).
            - Only include cross-company comparisons if the user EXPLICITLY asks; otherwise, keep companies separate.

            Remember: If nothing can be answered for any company, output exactly: "Not found in provided documents."
            """
        )
        user_msg = f"Question:\n{search_query}\n\nContext (top-{top_k}):\n{context}"

        answer_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

        try:
            ans = await pine.openai.chat.completions.create(
                model=answer_model,
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": user_msg}],
            )
            u = getattr(ans, "usage", None)
            if u:
                answer_usage["prompt_tokens"] = getattr(u, "prompt_tokens", None)
                answer_usage["completion_tokens"] = getattr(u, "completion_tokens", None)
                answer_usage["total_tokens"] = getattr(u, "total_tokens", None)

            answer = (ans.choices[0].message.content or "").strip()
        except Exception as e:
            query_logger.warning("Answer generation failed: %s", e)
            answer = "Failed to generate an answer."

        return {
            "subquery": one_query,
            "normalized_search_query": search_query,
            "company_used": company_used,
            "hits": hits,
            "answer": answer,
            "usage": {"detect": detect_usage, "answer": answer_usage},
        }

    # ---------------- (3.5) Run per-subquery RAG concurrently (bounded) ----------------
    sem = asyncio.Semaphore(max_concurrency)

    async def _guarded(idx: int, sq: str):
        async with sem:
            try:
                res = await _run_rag_for_one_subquery(sq)
            except Exception as e:
                query_logger.exception("RAG error for sub-query %r: %s", sq, e)
                res = {"subquery": sq, "answer": "Failed to generate an answer.", "error": str(e)}
            return idx, res

    tasks = [asyncio.create_task(_guarded(i, sq)) for i, sq in enumerate(subqueries)]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    # normalize results, preserve original subquery order
    ordered: Dict[int, Dict[str, Any]] = {}
    for item in gathered:
        if isinstance(item, Exception):
            query_logger.exception("Unhandled task exception: %s", item)
            continue
        idx, res = item
        ordered[idx] = res

    per_sub_results: List[Dict[str, Any]] = [ordered[i] for i in range(len(subqueries)) if i in ordered]

    # ---------------- (5) Synthesize a single final answer ----------------
    try:
        synthesis_system = (
            """You are a careful synthesizer. You will be given a list of sub-queries and their grounded answers.
            Produce ONE final answer for the original user query.

            Rules:
            - Do NOT invent facts; rely only on the sub-answers provided.
            - Merge overlapping insights; remove redundancies.
            - Keep a clear structure with short paragraphs and bullets when helpful.
            - If some sub-answers report 'Not found in provided documents.' state clearly which aspects are unknown.
            - Do not add citations; they were already handled upstream.
            """
        )
        synthesis_input = {
            "original_query": user_query,
            "sub_answers": [
                {
                    "subquery": r.get("subquery"),
                    "answer": r.get("answer"),
                    "company_used": r.get("company_used"),
                }
                for r in per_sub_results
            ],
        }
        syn = await pine.openai.chat.completions.create(
            model=answer_model,
            messages=[
                {"role": "system", "content": synthesis_system},
                {"role": "user", "content": json.dumps(synthesis_input, ensure_ascii=False)},
            ],
        )
        final_answer = (syn.choices[0].message.content or "").strip()
    except Exception as e:
        query_logger.warning("Synthesis failed: %s; concatenating sub-answers.", e)
        final_answer = "\n\n".join(
            f"### {r.get('subquery')}\n{r.get('answer')}" for r in per_sub_results
        )
        
    query_logger.info("Final synthesized answer:\n%s", final_answer)

    if not return_hits:
        return {"RAG_RESPONSE": final_answer}

    # Build compact debug payload with per-sub hits
    debug_payload = {
        "subqueries": subqueries,
        "per_sub": [
            {
                "subquery": r.get("subquery"),
                "company_used": r.get("company_used"),
                "normalized_search_query": r.get("normalized_search_query"),
                "hits": _project_hits(r.get("hits", [])),
            }
            for r in per_sub_results
        ],
    }
    return {
        "RAG_RESPONSE": final_answer,
        "RAG_DEBUG": debug_payload,
    }
