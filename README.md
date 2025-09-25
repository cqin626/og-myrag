# 🕸️ og-myrag

**Ontology-Grounded Graph-Based RAG with Text-to-Cypher Retrieval**

![Python](https://img.shields.io/badge/python-3.9%2B-green.svg)  
![Neo4j](https://img.shields.io/badge/graphdb-neo4j-orange.svg)  
![MongoDB](https://img.shields.io/badge/db-mongodb-green.svg)  
![Pinecone](https://img.shields.io/badge/vector-pinecone-blueviolet.svg)  

---

## 📖 Overview
`og-myrag` is a modular framework for building **ontology-grounded, graph-based Retrieval-Augmented Generation (RAG)** systems with **Text-to-Cypher** capabilities.  

- 🏢 Current implementation focuses on **Malaysian listed companies**.  
- 🌐 Extensible to become **domain-agnostic**.  
- 📓 Includes Jupyter notebooks as usage guides for each module.  

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
