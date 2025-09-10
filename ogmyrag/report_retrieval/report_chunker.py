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
    query: str,
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
) -> Dict[str, Any]:
    """
    End-to-end RAG:
      1) Read company names from Pinecone catalog namespace (1 vector per company).
      2) Use a small LLM to detect/normalize a company mention in the query.
      3) Retrieve top-k chunks from data namespace with exact metadata filter (if detected).
      4) Call a bigger LLM to produce a grounded answer using only retrieved chunks.

    Returns:
      {
        "answer": str,
        "hits": [ {id, score, text, section, company, year, ...}, ... ],
        "company_used": Optional[str],
        "known_companies": List[str],
        "filter_used": Dict[str, Any]
      }
    """
    def _clip(txt: str, n: int = 300) -> str:
        txt = (txt or "").replace("\n", " ").strip()
        return txt if len(txt) <= n else txt[:n] + "…"
    
    query_logger.info("RAG start | query=%r | top_k=%d", query, top_k)
    


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


    # ---------------- (2) Detect/normalize company with a small LLM ----------------
    company_used: Optional[str] = None
    detect_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    search_query = query

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
            • Replace any detected company mentions (and their possessives) with “the company” (or “the company’s” for possessive)
            if removing them would make the sentence ungrammatical or unclear.
            • If removing a trailing prepositional fragment (“of <company>”, “for <company>”, etc.) causes a dangling phrase,
            adjust the wording to keep the sentence fluent (e.g., drop the preposition or reattach it to “the company”).
            • Preserve the rest of the user intent; NEVER add facts. Keep years, section labels (e.g., “Practice 1.1”), numbers, and constraints.
            • Collapse extra whitespace; retain helpful punctuation.
            • If no company is detected, return the original query.

            Examples:
            - "What is the mission of Farm Fresh?" → "What is the mission of the company?"
            - "Who chairs the audit committee for Edelteq?" → "Who chairs the audit committee for the company?"
            - "What effective tax rate did AutoCount report and why?" → "What effective tax rate did the company report, and why?"
            - "Farm Fresh CG Practice 1.1" → "CG Practice 1.1"
            - "Board remuneration in FY2023 for VETECE" → "Board remuneration in FY2023"

            Output EXACT JSON, e.g.:
            {"companies":["ACME_BERHAD"], "normalized_query":"What is the mission of the company?"}"""

        )
        detect_msgs = [
            {"role": "system", "content": detect_system},
            {"role": "user", "content": f"COMPANIES: {companies}\n\nQUERY: {query}"},
        ]
        try:
            det = await pine.openai.chat.completions.create(
                model=small_model,
                messages=detect_msgs,
                response_format={"type": "json_object"},
                #temperature=0,
            )
            # capture usage safely
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
            if llm_norm:
                search_query = llm_norm
            else:
                search_query = query

        except Exception:
            company_used = None  # fall back to no company filter
            search_query = query

    query_logger.info("Detected company: %r", company_used)
    if search_query != query:
        query_logger.info("Search query normalized: %r → %r", query, search_query)
    else:
        query_logger.info("Search query unchanged.")


    # ---------------- (3) Retrieve top-k chunks from data namespace ----------------
    # Build exact-match metadata filter (must match your write-path fields).
    flt: Dict[str, Any] = {}
    if company_used:
        flt["from_company"] = company_used
    if doc_type:
        flt["type"] = doc_type
    if report_type_name:
        flt["report_type_name"] = report_type_name
    if year:
        flt["year"] = year

    query_logger.info("Query filter: %s", flt or "{}")


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
        msg = str(e).lower()
        query_logger.warning("Vector query failed: %s", e)

        if "namespace not found" in msg or ("404" in msg and "namespace" in msg):
            matches = []
        else:
            # be permissive: empty results on unexpected errors
            matches = []

    # normalize hits and optionally filter by score
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


    # build (unbounded) context string
    context = "\n\n".join(
        f"[{i}] id={h.get('id')} · score={h.get('score'):.3f} · section={h.get('section') or ''} · company={h.get('company')}\n{(h.get('text') or '').strip()}"
        for i, h in enumerate(hits, start=1)
    )
    #query_logger.info("Context: %s", context)

    # ---------------- (4) Grounded answer using ONLY the retrieved chunks ----------------
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
        - Do NOT place citations inline in Overview, Details, or Metrics. Citations appear ONLY in the final **Evidence** section.
        - Ensure every material claim in your answer is traceable to at least one item in **Evidence**.
        - In **Evidence**, use brief verbatim quotes (≤35 words) or precise paraphrases with the exact figure/phrase, each followed by a citation like: [src: <chunk-id or title>, p. X] (omit page if unknown).
        - If sources conflict, note the conflict in the answer (without inline citations) and include both conflicting quotes in **Evidence** with their citations.

        Calculations & Derivations:
        - You may compute simple, explicit derivations (e.g., growth rates, sums) ONLY from numbers present in the chunks.
        - Show the formula and inputs in **Metrics & Dates** (no inline citations there). In **Evidence**, include the quoted inputs with citations.

        Handling Gaps:
        - If a needed detail is not stated, write: "Not stated in provided documents." (no speculation).
        - Do not generalize beyond what is explicitly supported.

        Output Format:
        - If answering for one company:
        ## Overview
        <2–4 sentences summarizing the supported answer. No inline citations.>

        ## Details
        - <concise fact or point. No inline citations.>
        - <concise fact or point. No inline citations.>

        ## Metrics & Dates
        - <key figure/date verbatim or near-verbatim. No inline citations.>
        - <derived metric with formula, e.g., "YoY = (2024 – 2023) / 2023 = 12.4%"> 

        ## Evidence
        - "<short quote or exact figure/phrase>" [src: …, p. X]
        - "<short quote or exact figure/phrase>" [src: …, p. X]

        ## Limitations / Unknowns
        - Not stated in provided documents. (as applicable)

        - If answering for multiple companies:
        ### <Company Name>
        (Repeat the same subsections as above for each company, or write exactly "Not found in provided documents." if insufficient evidence.)

        Additional Constraints:
        - Neutral, analytical tone.
        - Do not include external knowledge or assumptions.
        - Preserve original numeric formatting (commas, decimals, signs, currencies).
        - Only include cross-company comparisons if the user EXPLICITLY asks; otherwise, keep companies separate.

        Remember: If nothing can be answered for any company, output exactly: "Not found in provided documents."""
    )
    user_msg = f"Question:\n{search_query}\n\nContext (top-{top_k}):\n{context}"

    answer_usage = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

    try:
        ans = await pine.openai.chat.completions.create(
            model=answer_model,
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": user_msg}],
            #temperature=0.2,
        )
        # capture answer usage safely
        u = getattr(ans, "usage", None)
        if u:
            answer_usage["prompt_tokens"] = getattr(u, "prompt_tokens", None)
            answer_usage["completion_tokens"] = getattr(u, "completion_tokens", None)
            answer_usage["total_tokens"] = getattr(u, "total_tokens", None)

        answer = (ans.choices[0].message.content or "").strip()
    except Exception:
        query_logger.warning("Answer generation failed: %s", e)
        answer = "Failed to generate an answer."

    # compute grand total if both present
    total_tokens_all = (detect_usage["total_tokens"] or 0) + (answer_usage["total_tokens"] or 0)


    query_logger.info("Final answer: \n\n%s\n\n", answer)
    query_logger.info("Token usage | total = %d", total_tokens_all)

    # print out top-k chunks on console
    """query_logger.info("\n\nTop-%d chunks retrieved: %d", top_k, len(hits))
    for i, h in enumerate(hits, start=1):
        query_logger.info(
            "Hit #%d | id=%s | score=%.3f | company=%s | section=%s | text=%s",
            i, h.get("id"), (h.get("score") or 0.0),
            h.get("company"), h.get("section"),
            h.get("text")
        )"""

    return {
        "answer": answer,
        "hits": hits,
        "company_used": company_used,
        "known_companies": companies,
        "filter_used": flt,
        "usage": {
            "detect": detect_usage,
            "answer": answer_usage,
            "total_tokens": total_tokens_all,   # <-- overall total
        },
    }