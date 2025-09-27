# 🕸️ og-myrag

**Ontology-Grounded Vector & Graph RAG: Report Scraping, Preprocessing & Text-to-Cypher Retrieval**

![Python](https://img.shields.io/badge/python-3.9%2B-green.svg)  
![Neo4j](https://img.shields.io/badge/graphdb-neo4j-orange.svg)  
![MongoDB](https://img.shields.io/badge/db-mongodb-green.svg)  
![Pinecone](https://img.shields.io/badge/vector-pinecone-blueviolet.svg)  

---

## 📖 Overview

`og-myrag` is a modular framework for building **ontology-grounded, graph-based Retrieval-Augmented Generation (RAG)** systems with **Text-to-Cypher** capabilities.

* 🏢 Focused on **Malaysian listed companies**; designed to become **domain-agnostic**.
* 🧺 **Report Scraper:** collects Bursa Malaysia company PDFs + metadata.
* 🧹 **Report Preprocessing:** cleans, segments, and enriches PDFs into searchable chunks.
* 🧠 **Vector RAG Module:** embeds chunks and retrieves top-K context for grounded answers.
* 🏗️ **Ontology Construction:** infers entity/relationship types and evolves the schema.
* 🌐 **Graph Construction:** builds a compact Neo4j property graph with Pinecone entity vectors.
* 🔍 **Graph Retrieval:** Text-to-Cypher + multi-agent querying over the ontology and graph.
* 📓 Jupyter notebooks included as usage guides for each module.


---

## ⚙️ Modules

### 1. 🏗️ Ontology Construction Module
Builds an **ontology** from source documents with minimal human intervention.  
- **Output**: Ontology stored in **MongoDB**.  
- **Sub-processes**:
  1. Extraction of entity and relationship types  
  2. Iterative ontology enhancement loop  

---

### 2. 🌐 Graph Construction Module
Constructs a **compact knowledge graph** based on the ontology and source documents.  
- **Model**: Property Graph Model  
- **Output**: Knowledge graph stored in **Neo4j** + **MongoDB**, with entities also stored in **Pinecone** for Cypher retrieval.  
- **Sub-processes**:
  1. Extraction of entity and relationship instances  
  2. Deduplication of entity/relationship instances (cache-based, LLM-oriented)  

---

### 3. 🔍 Graph Retrieval Module
Enables retrieval through collaboration between the **Graph RAG Agent** and the **Vector RAG Agent**.  
- **Output**: Responses to user queries.  
- **Graph RAG Agent** includes:  
  1. **Request Decomposition Agent** – Splits queries into smaller, independent parts  
  2. **Query Agent** – Formulates ontology-aware Cypher queries, evaluates results, and generates responses  
  3. **Text2Cypher Agent** – Converts natural language queries into Cypher  
  4. **Retrieval Result Compilation Agent** – Aggregates Cypher query results  

---

### 4. 🧺 Report Scraper (Web Scraping Agent)

Continuously ingests company reports from **Bursa Malaysia** “Company Announcements” (e.g., annual reports, prospectuses), capturing both the **PDFs** and rich **metadata** (company name/code, report title, period, publication date). 

* **Fast path:** `requests` + **BeautifulSoup** for static HTML pages.
* Stores raw artifacts & metadata for downstream processing.

This agent periodically (or on-demand) crawls listing pages → follows each announcement link → collects the attachment URLs → downloads PDFs → hands them off to preprocessing.  

---

### 5. 🧹 Report Preprocessing

Converts raw Bursa Malaysia PDFs into clean, searchable chunks with rich metadata for Vector RAG and Graph modules.

* **Ingest & normalize:** fetch PDF, extract basic metadata, optional OCR for scanned files.
* **Parse structure:** remove headers/footers, detect headings/TOC, fix hyphenation/encoding.
* **Segment smartly:** section-aware chunking (~1200 chars, small overlap) with light deduplication.
* **Enrich metadata:** company, stock code, report type, period, publish date, section path, page range, provenance IDs.
* **Index & handoff:** embed chunks, upsert to Pinecone, and export JSONL for KG/entity extraction.

---

### 6. 🧠 Vector RAG Module

A chat-style **retrieval-augmented generation** pipeline over the vectorized report corpus:

1. **Query Agent** – Parses user intent, extracts companies/years, optionally decomposes multi-part questions, and **normalizes** phrasing into retrieval-friendly text. 
2. **Embedding & Retrieval** – Builds the query embedding and runs **Pinecone** similarity search with metadata filters to fetch the most relevant chunks. 
3. **Chat Agent (Generator)** – Prompts an LLM using only the retrieved snippets as **grounding** to synthesize a coherent, source-backed answer; avoids hallucinations by enforcing “use-context-only” instructions. 

> The module acts as a “virtual analyst” that answers natural-language queries by stitching together semantically retrieved report fragments with strict provenance. 

---
