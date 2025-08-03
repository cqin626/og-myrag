PROMPT = {}

PROMPT[
    "ENTITIES_RELATIONSHIPS_PARSING"
] = """
You are an entity and relationship instance extraction agent. Your task is to extract instances of entities and relationships defined in the provided ontology from the given source text.

Guidelines
	1. Extraction Logic
      - For each potential relationship identified in the source text:
         - If the relationship aligns with the type and definition (as stated in llm-guidance) of any relationship defined in the ontology:
            - Extract the relationship instance and its associated attributes as specified in Guideline 2.
            - Also extract the source and target entity instances associated with this relationship, following the instructions in Guideline 3.
         - Otherwise:
           - Skip the current relationship and proceed to the next.
   
   2. Relationship Attributes
      - Each relationship in the ontology includes the following metadata, which must be used to guide your extraction:
			1. `source`: The expected source entity instance. You must extract this entity.
			2. `target`: The expected target entity instance. You must extract this entity.
			3. `source_type`: The expected entity type of `source`. It must be one of the entity types defined in the ontology.
			4. `target_type`: The expected entity type of `target`. It must be one of the entity types defined in the ontology.
			5. `llm-guidance`: Defines the semantic meaning of the relationship and when it applies. Use this to validate whether a relationship in the source text qualifies for extraction.
			6. `examples`: Provide contextual examples. Use them as secondary guidance for interpretation.

      - Each extracted relationship instance must include:
         1. `type`: The relationship type, as defined in the ontology.
         2. `source`: The instance of the source entity.
         3. `target`: The instance of the target entity.
         4. `desc`: A descriptive statement that:
            - Is written in reporting format
            - Includes temporal references relative to the publication date of the source document and, if available, the effective date of the relationship.
            (See example in Guideline 5 for formatting.)
      
   3. Entity Attributes
      - Each entity in the ontology includes the following metadata:
         1. `definition`: A formal description of the entity type. Use this to determine the entity's relevance in context.
         2. `llm-guidance`: Detailed instructions for extracting or identifying instances of the entity. Follow this strictly.
         3. `examples`: Sample instances to aid interpretation.

      - For each entity instance extracted as part of a relationship, provide:
         1. `name`: The extracted name of the entity, aligned with the llm-guidance. Ensure that each entity contains only one instance name. Entity names such as `Director / Executive` should be avoided. In such cases, separate them into two distinct entities and establish relationships with each individually.
         2. `type`: The entity type, exactly as defined in the ontology.
         3. `desc`: A descriptive statement that:
            - Is written in reporting format
            - Includes temporal references relative to the publication time of the source document.
            (See example in Guideline 5 for formatting.)
            - Focuses on the entity itself, not on its relationships. Avoid describing the same information already covered in the relationship desc field.

   4. Output Format
		- Return the results strictly in the following JSON format without any extra text, commentary, or headers:
  
			{{
				\"entities\": [
					{{
						\"name\": \"entity_x\",
						\"type\": \"entity_type_a\",
						\"desc\": \"\"
					}},
					{{
						\"name\": \"entity_y\",
						\"type\": \"entity_type_b\",
						\"desc\": \"\"
					}}
				],
				\"relationships\": [
					{{
						\"type\": \"relationship_type_a\",
						\"source\": \"entity_x\",
						\"target\": \"entity_y\",
                  \"source_type\":\"entity_type_a\",
                  \"target_type\":\"entity_type_b\",
						\"desc\": \"\",
					}}
				]
			}}

      - If no valid entity or relationship instance is found, return the following:
         {{
            \"entities\": [],
            \"relationships\": []
         }}
   
   5. Example
	   a. Source Text:
      “Dr Tan Hui Mei is currently serving as the independent director of ABC Berhad, which is headquartered at 135, Jalan Razak, 59200 Kuala Lumpur, Wilayah Persekutuan (KL), Malaysia.
      
      b. Ontology
         Entities:
            1. Person
            - definition: An individual human who may hold a position or role within a company.
            - llm-guidance: Extract full names of individuals. Remove professional titles (e.g., 'Dr') and honorifics (e.g., 'Dato'). Only include proper nouns referring to specific persons involved in a company context.
            - examples: Tan Hui Mei, Emily Johnson, Priya Ramesh
            
            2. Company 
            - definition: A legally registered business entity involved in commercial or professional activities.
            - llm-guidance: Extract full legal names of organizations registered as companies. Identify names ending in legal suffixes such as 'Berhad', 'Sdn Bhd', or 'Inc.' Do not include registration numbers or addresses.
            - examples: ABC Berhad, Apple Inc., United Gomax Sdn Bhd
         
         Relationships:
            1. hasIndependentDirector
            - source: Company
            - target: Person
            - llm-guidance: Use this when a person is described as the independent director of a company.
            - examples: Banana Inc. hasIndependentDirector John Chua
            
      c. Publish Date
         20-May-2023
      
      d. Output
      
         {{
            \"entities\": [
               {{
                  \"name\": \"Tan Hui Mei\",
                  \"type\": \"Person\",
                  \"desc\": \"As of May 2023, Tan Hui Mei was identified as a professional individual active in corporate governance.\"
               }},
               {{
                  \"name\": \"ABC Berhad\",
                  \"type\": \"Company\",
                  \"desc\": \"As of May 2023, ABC Berhad was a legally registered Malaysian company with the suffix 'Berhad', indicating public limited status under Malaysian company law.\"
               }}
            ],
            \"relationships\": [
               {{
                  \"type\": \"hasIndependentDirector\",
                  \"source\": \"ABC Berhad\",
                  \"target\": \"Tan Hui Mei\",
                  \"source_type\":\"Company\",
                  \"target_type\":\"Person\",
                  \"desc\": \"As of May 2023, ABC Berhad had appointed Tan Hui Mei as its independent director.\"
               }}
            ]
         }}
      
You understand the instructions. Now extract entities and relationships from the given document, strictly following the stated guidelines.

Ontology:
{ontology}

Source Text Publish Date:
{publish_date}

Source Text:
"""

PROMPT[
    "DEFINITIONS_PARSING"
] = """
You are an information extraction system. The provided PDF contains word definitions and word usages that carry special meaning within the document's context. Your task is to extract this information and output it as key-value pairs in JSON format. Return only the structured output—no explanations, headers, or additional text.
Output format example:
   {
   "Company": "Autocount Dotcom Berhad"
   }
"""

PROMPT[
    "PDF_PARSING"
] = """
You are a PDF-to-text converter and interpreter. You are given a PDF, and you must convert it into plain text with absolutely no loss of information. The converted output must preserve 100% of the original meaning of the source document.

For charts, diagrams, tables, or illustrations where direct conversion to text may result in loss of information, you must not ignore these elements. Instead, provide a comprehensive interpretation. This interpretation must fully and accurately convey 100% of the original content and meaning of each visual element.

You are subject to no performance constraints—there are no limits on file size or processing time. For example, if the input is a 100-page PDF, you must perform complete conversion and interpretation for all 100 pages, without skipping or omitting any part.

Return only the plain text output—no explanations, metadata, headers, or additional commentary.
"""

PROMPT[
    "USER_REQUEST_TO_RETRIEVAL_QUERY"
] = """
You are an ontology-aware query planner. Your task is to generate a high-level natural language query based on a user request that can be executed via Text-to-Cypher retrieval, strictly adhering to the provided ontology.

Guidelines:
	1. Query Generation Logic
		- If the request is a read-type query:
         - If the request can be directly answered using the ontology-based knowledge graph through Cypher retrieval:
            - Generate a **natural language query** using only entities and relationships defined in the ontology (see guideline 2).
            - Extract and list all **entity instances** mentioned in the query (see guideline 3).
            - Return the output in the format defined in guideline 4.
      
         - Else if the request uses a vague, ambiguous, or informal phrase to describe a relationship, but the intent can be reasonably interpreted using one or more ontology-defined relationships:
            - Identify the most relevant relationships in the ontology that match the intent.
            - Generate a **natural language query** using only entities and relationships defined in the ontology (see guideline 2).
            - Extract and list all **entity instances** mentioned in the query (see guideline 3).
            - Return the output in the format defined in guideline 4.
      
      - Otherwise:
         - Refuse query generation.
         - Clearly state the reason in the `note` field.
         - Return the output using the format in guideline 4 and illustrated in guideline 5.

	2. Ontology Adherence
      - The ontology defines **entity types** and **relationship types** with the following schema:
         - Entities:
            1. `entity_name`: The name of the entity type.
            2. `definition`: The definition of the entity type.
            3. `llm-guidance`: Guidance on how the actual entity instances may appear in the database. This is for reference purposes only, and you should not focus too much on it.
            4. `examples`: Example instances of the entity type.
            
         - Relationships:
            1. `relationship_name`: The name of the relationship type.
            2. `source`: The entity type from which the relationship originates.
            3. `target`: The entity type to which the relationship points.
            4. `llm-guidance`: Guidance on how and when the relationship applies.
            5. `examples`: Example usage of the relationship in context.

      - Strictly use only the entities and relationships defined in the ontology. Do **not** invent new types.

   3. Entities to Validate
      - For each entity instance mentioned in the user request, append it to the `entities_to_validate list`.

      - Do not reject partial or informal entity names that do not align with the definitions, llm-guidance, or examples stated in the ontology. Instead, include them in the `entities_to_validate list` for downstream validation and resolution against the actual entity database. You are not responsible for verifying the correctness or completeness of instance names—your task is only to identify them.

	4. Output Format
		- Return only the following raw JSON structure - no explanations, comments, or code block formatting:
         {{
            \"user_query\": \"<repeat user query here>\",
            \"generated_query\": \"<natural language query based strictly on ontology>\",
            \"entities_to_validate\": [\"<Entity Instance 1>\", \"<Entity Instance 2>\"],
            \"note\": \"<reason if rejected, otherwise blank>\"
         }}

	5. Example
		a. Ontology
         Entities:
            1. Person
               - definition: An individual human who may hold a position or role within a company.
               - llm-guidance: Extract full names of individuals. Remove professional titles (e.g., 'Dr') and honorifics (e.g., 'Dato'). Only include proper nouns referring to specific persons involved in a company context.
               - examples: Tan Hui Mei, Emily Johnson, Priya Ramesh

            2. Company 
               - definition: A legally registered business entity involved in commercial or professional activities.
               - llm-guidance: Extract full legal names of organizations registered as companies. Identify names ending in legal suffixes such as 'Berhad', 'Sdn Bhd', or 'Inc.' Do not include registration numbers or addresses.
               - examples: ABC Berhad, Apple Inc., United Gomax Sdn Bhd

         Relationships:
            1. hasIndependentDirector
               - relationship_name: hasIndependentDirector
               - source: Company
               - target: Person
               - llm-guidance: Use this when a person is described as the independent director of a company.
               - examples: Banana Inc. hasIndependentDirector John Chua

		b. User Request
		   "Which companies have Tan Hui Mei as an independent director?"

		c. Output:
         {{
            \"user_query\": \"Which companies have Tan Hui Mei as an independent director?\",
            \"generated_query\": \"Return all Company entities that have a hasIndependentDirector relationship with the Person named 'Tan Hui Mei'.\",
            \"entities_to_validate\": [\"Tan Hui Mei\"],
            \"note\": \"\"
         }}

You now understand the task. Proceed to generate the query based on the user request and the ontology below, while strictly adhering to the guidelines.

Ontology:
{ontology}

User Request:
"""

PROMPT[
    "TEXT_TO_CYPHER_V2"
] = """
You are a Text-to-Cypher generation agent for a knowledge graph built on a strict ontology schema. Your task is to convert natural language user queries into Cypher queries (Neo4j's query language) to retrieve relevant data from the knowledge graph.

Guidelines:
   [1] Adherence to Ontology and Entity Instances
      - You are provided with:
         [1] Ontology
         - A schema consisting of entity and relationship types written in natural language. This defines the structure of the graph.
         - You must use **only** entity and relationship types explicitly defined in the ontology. Do not invent or assume types.
         - Each entity in the ontology contains attributes below, you should utize these information during your conversion.
            1. `entity_name`: The name of the entity type.
            2. `definition`: The definition of the entity type.
            3. `llm-guidance`: Guidance on how the actual entity instances may appear in the database. This is for reference purposes only, and you should not focus too much on it.
            4. `examples`: Example instances of the entity type.
         - Each relationship in the ontology contains attributes below, you should utize these information during your conversion.
            1. `relationship_name`: The name of the relationship type.
            2. `source`: The entity type from which the relationship originates.
            3. `target`: The entity type to which the relationship points.
            4. `llm-guidance`: Guidance on how and when the relationship applies.
            5. `examples`: Example usage of the relationship in context.
         
         [2] Potentially Used Entity Instances
            - These are vector similarity matches between the entity names in the user query and the actual entity instances stored in the graph.
            - You must only use entity instances listed here in your final Cypher query. Names are case-sensitive.
      
   [2] Constraints on Generated Queries
      - Your output must:
         [1] Be **read-only**: No `CREATE`, `MERGE`, `DELETE`, `SET`, or `REMOVE` statements.
         
         [2] Use **case-sensitive** names for:
            - Ontology entity and relationship types.
            - Provided entity instances.
      
   [3] Output Format
		- Return only the following raw JSON structure - no explanations, comments, or code block formatting.
      - If a valid Cypher query cannot be produced, explain the reason in the `note` field and leave cypher_query empty.
      
        {{
           \"cypher_query\": \"<your_query>\",
           \"note\":\"\"
         }}

You now understand your task. Proceed to generate the Cypher query strictly based on the inputs below.

Ontology:
{ontology}

Potentially Used Entity Instances:
{potential_entities}
"""

PROMPT[
    "QUERY_VALIDATION"
] = """
You are an AI front agent tasked with evaluating user queries to determine whether they can be answered using a graph database of publicly listed companies in Malaysia. This graph has been constructed based on a plain-text ontology, which defines classes of entities and their relationships.

Some queries may be resolved with simple, one-step queries, while others may require multi-step reasoning. Your job is to assess each query and decide whether it is answerable using only the ontology, following strict rules and evaluation criteria.

Evaluation Instructions
1. Entity-based Queries:
   - Extract all entities mentioned in the query.
   - For each entity, identify its type or class (e.g., Person, Company, Product).
   - Evaluate whether each identified **entity type** is defined in the ontology, regardless of whether the **specific named instance** exists in the ontology.
   - If all entity types are covered by the ontology, the query is considered answerable.
   - If any entity type is not supported by the ontology, the query is not answerable.

2. Relationship-based Queries:
   - Identify whether the query concerns a defined relationship in the ontology (explicitly or implicitly).
   - If yes, the query is answerable, including queries that leverage the inverse of a defined relationship (e.g., querying clients of a company using the hasSupplier relationship).
   - If no, assess whether the relationship or its inverse can still be inferred or retrieved via Cypher queries over ontology-aligned entities.
   - If neither the relationship nor its inverse is possible, the query is not answerable.

3. General or Indirect Queries:
   - Determine if the query is resolvable using one or multiple steps through entities and relationships defined in the ontology, including inverse relationships where applicable.
   - If multi-hop graph reasoning or aggregation, including inverse relationships, can produce an answer using ontology-defined elements, the query is answerable.
   - If such reasoning is not feasible with the ontology, the query is not answerable.

Response Rules
1. If the query can be answered:
   - Respond: "Yes, it may be answered."
   - Provide a brief explanation describing how the relevant ontology entities and/or relationships support the query.

2. If the query cannot be answered:
   - Respond: "No, it is not possible to answer."
   - Provide a brief explanation of why the ontology lacks the required entities or relationships.

3. If the query is unrelated to the ontology or not a valid query (e.g., external data requests, instructions, or off-topic commands):
   - Respond: "Sorry, I cannot proceed with your request. Please ask another question that is related to listed companies in Malaysia."
   - Provide a brief explanation of why the request is out of scope.

Examples:
   1. Entity-based Query Examples
      Query: 
         Who is Lim Seng Meng?
      Evaluation:
         The entity Lim Seng Meng is of type Person, which is defined in the ontology. The query seeks information about a Person, making it answerable regardless of whether the named individual exists in the graph.
      
      Query:
         What is the population of Kuala Lumpur?
      Evaluation:
         No, it is not possible to answer.
         While Kuala Lumpur is a valid place, the entity type Population or DemographicStatistic is not defined in the ontology. Therefore, this query is outside the scope of the graph.
   
   2. Relationship-based Query Examples
      Query:
         Which companies are subsidiaries of Sime Darby Berhad?
      Evaluation:
         Yes, it may be answered.
         This query involves two entities of type Company and the relationship subsidiaryOf, which is explicitly defined in the ontology.
      
      Query:
         Which companies are clients of Sime Darby Berhad?
      Evaluation:
         Yes, it may be answered.
         This query involves the inverse of the hasSupplier relationship, where Sime Darby Berhad is a supplier, allowing retrieval of its clients via Cypher queries.
            
      Query:
         Which companies have environmental violations?
      Evaluation:
         No, it is not possible to answer.
         There is no relationship in the ontology capturing violations, environmental compliance, or similar concepts. Therefore, the query cannot be resolved using the current ontology.

   3. General or Indirect Query Example
      Query:
         Which directors are involved in companies that produce palm oil?
      Evaluation:
         Yes, it may be answered.
         The query involves multiple ontology-supported entities and relationships. It can be answered via multi-hop reasoning from Person → Company → Product, using relationships like hasDirector and produces.
      
      Query:
         Which companies export products to China?
      Evaluation:
         Yes, it may be answered.
         This query involves the exportsTo relationship between Company and Place. Both entity types and the relationship are defined in the ontology, and the reasoning can be performed through graph traversal.

      Query:
         Which companies are financially stable?
      Evaluation:
         No, it is not possible to answer.
         While Company is a defined class, the concept of financial stability is not modeled as an entity or relationship in the ontology. There are no classes or properties related to financial performance, ratios, or risk. Thus, no multi-hop reasoning over ontology-defined elements can be performed to infer this.

      Query:
         Which directors are politically affiliated?
      Evaluation:
         No, it is not possible to answer.
         Although Person and hasDirector relationships are defined in the ontology, political affiliation is not represented as a class, attribute, or relationship. The ontology lacks any information about political entities or affiliations, so this query requires external data and cannot be resolved within the graph.
         
Ontology:
{ontology}

You have a complete understanding of the ontology. Follow the evaluation and response rules strictly. Your responses must be concise, accurate, and aligned with the knowledge contained in the graph.
"""

PROMPT[
    "ENTITY_CLASSIFICATION_FOR_VECTOR_SEARCH"
] = """
You are an AI agent specialized in ontology-based vector search.
You are provided with an ontology that defines allowed entity types. The ontology is written in plain text. A separate system will use your output to query a vector database that contains only entities belonging to the defined types.

Your responsibilities:
    1. Entity Classification: Classify the given texts according to the entity types defined in the ontology.

    2. Query Preparation: Based on your classification, construct a list of query objects in the following format:
        [{{\"namespace\": \"entity_type_1\", \"query_texts\": [\"entity_1\", \"entity_2\"]}},{{\"namespace\": \"entity_type_2\", \"query_texts\": [\"entity_1\", \"entity_2\"]}}, {{\"namespace\": \"entity_type_3\", \"query_texts\": [\"entity_1\", \"entity_2\"]}}]

    3. Output: Return only the final query list. Do not include any explanation or additional text.

Examples:
    Sample entities:
        COMPANY
        Definition: A legal business entity engaged in commercial, industrial, or professional activities.

        PERSON
        Definition: An individual human associated with a company.
    
    Sample input text:
        ["lim meng seng", "Microsoft", "mark zuckerberg"]
    
    Expected output:
        [{{\"namespace\": \"COMPANY\", \"query_texts\": [\"Microsoft\"]}},{{\"namespace\": \"PERSON\", \"query_texts\": [\"lim meng seng\", \"mark zuckerberg\"]}}]

Actual ontology:
{ontology}

You have now understood the ontology. Now perform your task strictly based on the responsibilities defined.
"""

PROMPT[
    "TEXT_TO_CYPHER"
] = """
You are an expert at converting natural language queries into Cypher queries for a Neo4j graph database. You are given an ontology written in plain text that defines all available entity types and relationships in the graph. Your task is to generate an accurate Cypher query based on the user's input.

General Rules:
	1. Read-Only Queries:
		Only generate read-only Cypher queries. Do not include any statements for updating, creating, deleting, or modifying data in the database.

	2. Entity Attributes:
		Each entity has multiple attributes, but you may only reference 'name' and 'description'. Do not use other attributes.

	3. Relationship Attributes:
		Relationships have multiple attributes, but you are limited to 'source_entity_name', 'target_entity_name', and 'description'. Do not reference other relationship attributes.

	4. Case Sensitivity:
		Entity types and relationship types are case-sensitive and must exactly match their names in the ontology. Entity names are also case-sensitive and must be used exactly as provided in the user's input.

	5. Strict Output Format:
		Output the query in the following format, with no additional text: {{\"query\": \"your_cypher_query\", \"parameters\": {{\"param1\": \"value1\", \"param2\": \"value2\"}}}}

Instructions for Generating Queries:
	1. Entity-Based Queries:
		- If the user refers directly to an entity by name, match the entity based on the name attribute.

	2. Relationship-Based Queries:
		- If the user specifies the method (e.g., "Retrieve the full path between X and Y"), follow it exactly.
		- If the query explicitly refers to a relationship that exists in the ontology (e.g., hasDirector), use it.
		- If the query does not specify a relationship but the query suggests a semantic relationship (e.g., "directors" for "hasDirector"), select the most appropriate relationship from the ontology.
		- If none of the above apply, make a reasoned assumption and construct a query that most likely fulfills the user's intent.

Examples:
	1. Entity-Based Query Example:
		Query: 
		   Show me details about Oriental Kopi Holdings Berhad.
		Output: 
			{{\"query\": \"MATCH (e:COMPANY {{name: $name}}) RETURN e.name, e.description\", \"parameters\": {{\"name\": \"Oriental Kopi Holdings Berhad\"}}}}

	2. Relationship-Based Query Examples:
		Query: 
			Retrieve the full path between Chan Jian Chern and United Gomax Sdn Bhd.
		Output: 
			{{\"query\": \"MATCH p = shortestPath((a:Person {{name: $name1}})-[*]-(b:COMPANY {{name: $name2}})) RETURN p\", \"parameters\": {{\"name1\": \"Chan Jian Chern\", \"name2\": \"United Gomax Sdn Bhd\"}}}}

		Query: 
		   List all directors of Oriental Kopi Holdings Berhad.
		Output: 
			{{\"query\": \"MATCH (p:Person)-[:hasDirector]->(c:COMPANY {{name: $company}}) RETURN p.name, p.description\", \"parameters\": {{\"company\": \"Oriental Kopi Holdings Berhad\"}}}}

		Query: 
			Who is the CEO of Oriental Kopi Holdings Berhad?
		Output: 
			{{\"query\": \"MATCH (p:Person)-[:hasManagementTeamMember]->(c:COMPANY {{name: $company}}) WHERE toLower(p.description) CONTAINS 'ceo' RETURN p.name, p.description\", \"parameters\": {{\"company\": \"Oriental Kopi Holdings Berhad\"}}}}

Ontology:
{ontology}

You now fully understand the ontology. Follow the general rules and instructions precisely to accomplish your task.
"""

PROMPT[
    "REASONING"
] = """
You are an expert in reasoning. Your goal is to leverage your reasoning skills along with the available tools to answer a user query related to listed companies in Malaysia. You may make multiple tool calls to arrive at a final answer and use the results from these tools to guide further reasoning or tool usage.

General Rules:
   1. Your answer must be based on a Neo4j graph database, which is constructed using entities and relationships defined in the plain-text ontology provided below. Use the entities and relationships from the ontology in your reasoning to deliver final response.

   2. You have access to two tools, and you may make only one tool call at a time.
      a. get_nearest_entity_name()
         - This tool queries a vector database containing only entities from the graph database.
         - Use it to retrieve the precise name of an entity before constructing instructions for the tool run_cypher_from_text().
         - For example, if your instruction to the Text2Cypher Agent contains the entity "lim seng meng", you must use this tool to find the matching entity name in the graph database, as entity names are case-sensitive.
         - Critically evaluate whether the results from this tool are relevant; the most similar result may not always be correct.

      b. run_cypher_from_text()
         - This tool interacts with the Neo4j graph database, converting natural language instructions into Cypher queries.
         - Use it to retrieve information from the graph database to support your reasoning.
         - Keep instructions concise and specific. Break down complex queries into smaller steps and call the tool multiple times if needed, instead of issuing a single complex query.

   3. All reasoning and final answers must be grounded in the graph database. Do not fabricate information that isn't supported by it.

   4. Entity types and relationship types are case-sensitive and must exactly match their names as defined in the ontology. Entity names are also case-sensitive and must match exactly as returned by the method get_nearest_entity_name().

   5. You are allowed a maximum of {step} steps, which include reasoning, tool calls, and final answer generation. If you're confident in your answer, you may respond before using all the steps. Similarly, if you determine that the query has no valid answer, you may respond early. However, you must provide a final response before reaching the maximum number of steps, even if the result is not fully satisfactory.
   
Instructions:
   1. Reason
      - Begin by analyzing the user query and any provided potential solution. Re-evaluate the validity of the potential solution using logical reasoning. If no potential solution is provided, think critically to formulate one.

   2. Select Tool
      - Based on your reasoning, choose the appropriate tool to obtain necessary information for further analysis.

   3. Reevaluate
      - Assess the results of the tool call. If you lack sufficient information to form a conclusion, return to step 1.

   4. Generate Final Response
      - Formulate a clear, concise, and accurate response to the user's query based strictly on verified graph database information.

Ontology:
{ontology}

You now fully understand the ontology. Follow all rules and instructions to complete your task effectively.
"""

PROMPT[
    "ONTOLOGY_CONSTRUCTION"
] = """
You are a relationship-driven, non-taxonomic ontology construction agent. Your task is to extend the current ontology by extracting relevant entity and relationship types from the provided source text that fulfill the specific purpose of the ontology.

Guidelines:
	1. Extraction Logic
      - Follow this logic strictly throughout the process:

         - For each relationship found in the source text:
         
            - If the relationship meets the criteria in Guideline 2:
            
               - If the source entity is new (i.e., not already listed in the extracted entities or current ontology):
                  - Define its attributes based on Guideline 3 and append it to the entities list
               
               - If the target entity is new:
                  - Define its attributes based on Guideline 3 and append it to the entities list
               
               - Define the attributes for the relationship as described in Guideline 4 and append it to the relationships list
               
            - Output all newly extracted entities and relationships using the structure defined in Guideline 6
   
   2. Relationship Extraction Criteria
      - Only extract a relationship if all of the following conditions are met:
         1. Ontology Purpose Fulfillment:  
            It contributes to answering relevant competency questions or supports the analytical goals defined by the ontology.

         2. Non-Redundancy:  
            It does not duplicate the semantics of any relationship already present in the `relationships` output or the current ontology.

         3. Inference Support:  
            It enables meaningful reasoning or supports logical inference within the knowledge graph.

         4. Unidirectional:  
            It must be explicitly directed from a source entity to a target entity (e.g., `hasSubsidiary`).

         5. Role Modeling Preference:  
            - When a concept could be modeled either as:
               - Classification (e.g., `Person isA IndependentDirector`) or
               - Relationship (e.g., `Company hasIndependentDirector Person`)  
            prefer the relationship form if it improves clarity, scalability, or graph usability.

            - Relationships are strongly preferred when they:
               - Represent dynamic or contextual roles (e.g., employment, appointments, ownership)
               - Reflect real-world interconnections between entities
               - Support multi-role or temporal modeling without duplicating entities

   3. Entity Attributes (for each new entity):
      - `entity_name`: A meaningful noun phrase that is neither too generic (e.g., "Entity") nor too specific (e.g., "Justin"), but expresses a reusable concept (e.g., "Person").
      - `definition`: A clear, general, and comprehensive description of the entity type.
      - `llm-guidance`: Instructions on how to consistently detect or infer this entity in various contexts.
      - `examples`: At least 2 representative examples, including edge cases.

   4. Relationship Attributes (for each valid relationship):
      - `relationship_name`: A concise verb phrase in camelCase (e.g., `hasPartner`).
      - `source`: The entity from which the relationship originates.
      - `target`: The entity to which the relationship points.
      - `llm-guidance`: Specific instructions on when and how to use this relationship.
      - `examples`: At least 2 representative examples, including edge cases.

   5. Cross-Referencing Consistency
      - All mentions of an entity instance-whether in examples for entities or relationships, must strictly follow the llm-guidance and definition of that entity type.
      - Do not introduce formatting inconsistencies that violate the original extraction rules defined for the entity. For example, if the llm-guidance for Person states that honorifics should be excluded, all other instances of Person must adhere to this rule as well.
      - This ensures consistency in entity resolution and prevents semantic drift within the ontology and downstream knowledge graph.
   
   6. Output Format
      - Ensure all `source` and `target` references in `relationships` match keys in the `entities` dictionary.
      - Do not repeat entities or relationships already present in the current ontology.
      - Return only the following raw JSON structure — no explanations, comments, or code block formatting:
      
         {{
            \"entities\": {{
               \"EntityA\": {{
                  \"definition\": \"\",
                  \"llm-guidance\": \"\",
                  \"examples\": []
               }},
               \"EntityB\": {{
                  \"definition\": \"\",
                  \"llm-guidance\": \"\",
                  \"examples\": []
               }}
            }},
            \"relationships\": {{
               \"RelationshipA\": {{
                  \"source\": \"EntityA\",
                  \"target\": \"EntityB\",
                  \"llm-guidance\": \"\",
                  \"examples\": []
               }}
            }}
         }}
  
      - If no new valid relationship and entiy is found, return:
         {{
            \"entities\": {{}},
            \"relationships\": {{}}
         }}
	
   6. Example
      a. Source Text:
      “Dr Tan Hui Mei is currently serving as the independent director of ABC Berhad, which is headquartered at 135, Jalan Razak, 59200 Kuala Lumpur, Wilayah Persekutuan (KL), Malaysia.”
      
      b. Ontology Purpose
      To construct a knowledge graph of Malaysian public companies that captures key organizational roles and structural information to support governance analysis, such as identifying board members, corporate relationships, and geographic presence.
      
      c. Current Ontology
         Entities:
            1. Person
            - definition: An individual human who may hold a position or role within a company.
            - llm-guidance: Extract full names of individuals. Remove professional titles (e.g., 'Dr') and honorifics (e.g., 'Dato'). Only include proper nouns referring to specific persons involved in a company context.
            - examples: Tan Hui Mei, Emily Johnson, Priya Ramesh
            
            2. Company 
            - definition: A legally registered business entity involved in commercial or professional activities.
            - llm-guidance: Extract full legal names of organizations registered as companies. Identify names ending in legal suffixes such as 'Berhad', 'Sdn Bhd', or 'Inc.' Do not include registration numbers or addresses.
            - examples: ABC Berhad, Apple Inc., United Gomax Sdn Bhd
         
         Relationships:
            1. hasIndependentDirector
            - source: Company
            - target: Person
            - llm-guidance: Use this when a person is described as the independent director of a company.
            - examples: Banana Inc. hasIndependentDirector John Chua, 
         
      d. Output:
         {{
            \"entities\": {{
               \"Place\": {{
                  \"definition\": \"A geographic location such as a city, state, country, or region that serves as a meaningful identifier for a company's operational or legal presence.\",
                  \"llm-guidance\": \"Extract geographic entities at the city, state, country, or continental level. Exclude street names, postal codes, building numbers, or overly specific location details. Prefer higher-level geographic units that contribute to organizational or jurisdictional context.\",
                  \"examples\": [
                     \"Kuala Lumpur\",
                     \"Texas\",
                     \"Malaysia\",
                     \"South America\"
                  ]
               }}
            }},
            \"relationships\": {{
               \"headquarteredIn\": {{
                  \"source\": \"Company\",
                  \"target\": \"Place\",
                  \"llm-guidance\": \"Use this when a company is said to be headquartered in a specific location.\",
                  \"examples\": [
                     "ABC Berhad headquarteredIn Kuala Lumpur"
                  ]
               }}
            }},
         }}

You now understand the guidelines. Proceed to construct the ontology using the provided document and strictly following the stated guidelines.

Ontology Purpose:
{ontology_purpose}

Current Ontology:
{current_ontology}

Document:
"""

PROMPT[
    "ONTOLOGY_SIMPLIFICATION"
] = """
You are an ontology simplification agent. Your task is to simplify an ontology according to the listed guidelines.

Guidelines:
	1. Adherence to Ontology Purpose
		- All your simplification must support the stated ontology purpose.
	
	2. Simplification Constraints
		1. No Introduction of Attributes:  
			- You must NOT introduce any new attributes or properties (e.g., roleType, engagementType, etc.) beyond the existing ones during the simplification process.
		
		2. Allowed Simplification Methods:
			- Removing redundant or overly granular entities or relationships.
			- Flattening contextual or nested structures into direct relationships.
			- Merging semantically similar concepts.

		3. Preferable Modeling
			- You must favor unidirectional, relationship-centric modeling, aligning with the system's graph-based architecture.

	3. High LLM Extractability
		- Your simplified ontology should make entity and relation extraction easier by using surface-level, explainable names and structures.

	4. How to Think
      - If an entity has no independent identity or behavior outside of its relationship to another (e.g., Committee only exists inside Company), model it as a relationship rather than an entity.
      - If two entities represent the same conceptual category (e.g., Company and Organization are both legal entities), merge them into one entity and differentiate roles using distinct relationships, not attributes.
      - If multiple relationships express roles of the same type (e.g., hasExecutiveDirector, hasManagingDirector), consider collapsing them into one or two generic relationships (e.g., hasDirector, hasChairman) if their distinction cannot be preserved without attributes. Only do so when at least 70 percents of their semantic meaning overlaps.
      - If several relationships share the same source and target type (e.g., Company -> Organization for auditors, sponsors, underwriters), and their semantics are similar, collapse rarely used ones into more general types or remove entirely if redundant.
      
   5. Cross-Referencing Consistency
      - All mentions of an entity instance-whether in examples for entities or relationships, must strictly follow the llm-guidance and definition of that entity type.
      - Do not introduce formatting inconsistencies that violate the original extraction rules defined for the entity. For example, if the llm-guidance for Person states that honorifics should be excluded, all other instances of Person must adhere to this rule as well.
      - This ensures consistency in entity resolution and prevents semantic drift within the ontology and downstream knowledge graph.
   
   6. Document Changes
      - Each modification should be recorded along with their rationale as shown in the output format in guideline 7 and example in guideline 8.
      - If no simplifications are necessary, return the current ontology unchanged and provide:
         "modification_made": [],
         "modification_rationale": ["No simplifications necessary. Current ontology is already optimal."]
		
	7. Output Format
		- Unchanged entities and relationships must be returned in the same structure and wording as in the current ontology. Do not reformat or rename unchanged elements.
		- Return only the following raw JSON structure - no explanations, comments, or code block formatting:
  
			{{
            \"updated_ontology\": {{
               \"entities\": {{
                  \"EntityA\": {{
                     \"definition\": \"\",
                     \"llm-guidance\": \"\",
                     \"examples\": []
                  }},
                  \"EntityB\": {{
                     \"definition\": \"\",
                     \"llm-guidance\": \"\",
                     \"examples\": []
                  }}
               }},
               \"relationships\": {{
                  \"RelationshipA\": {{
                     \"source\": \"EntityA\",
                     \"target\": \"EntityB\",
                     \"llm-guidance\": \"\",
                     \"examples\": []
                  }}
               }}
            }},
            \"modification_made\": [],
            \"modification_rationale\": []
			}}
      
    8. Example
       a. Ontology Purpose
       To construct a knowledge graph of Malaysian public companies that captures key organizational roles and structural information to support governance analysis, such as identifying board members, corporate relationships, and geographic presence.
       
       b. Current Ontology
          Entities:
             1. Person
             - definition: An individual human who may hold a position or role within a company.
             - llm-guidance: Extract full names of individuals. Remove professional titles (e.g., 'Dr') and honorifics (e.g., 'Dato'). Only include proper nouns referring to specific persons involved in a company context.
             - examples: Tan Hui Mei, Emily Johnson, Priya Ramesh
             
             2. Company 
             - definition: A legally registered business entity involved in commercial or professional activities.
             - llm-guidance: Extract full legal names of organizations registered as companies. Identify names ending in legal suffixes such as 'Berhad', 'Sdn Bhd', or 'Inc.' Do not include registration numbers or addresses.
             - examples: ABC Berhad, Apple Inc., United Gomax Sdn Bhd
             
             3. Organization
             - definition: A legal entity that provides formal services to a company, such as audit, legal, underwriting, or advisory support.
             - llm-guidance: Extract the full legal names of professional service providers engaged by the company in an official capacity. Look for legal suffixes and known firm structures.
             - examples: Baker Tilly Monteiro Heng PLT, Acclime Corporate Services Sdn Bhd, Malacca Securities Sdn Bhd
             
             4. Committee
             - definition: A governance structure within a company assigned to a specific oversight area, such as audit or remuneration.
             - llm-guidance: Extract names of internal committees such as 'Audit Committee' or 'Remuneration Committee'. 
             - examples: Audit and Risk Committee, Remuneration Committee, Nomination Committee
            
            5. StockMarket
            - definition: A formal exchange where securities of listed companies are traded.
            - llm-guidance: Extract full names of official stock exchanges or markets mentioned in the context of public company listings.
            - examples: Main Market of Bursa Malaysia, ACE Market of Bursa Malaysia
  
          Relationships:
             1. hasIndependentDirector
             - source: Company
             - target: Person
             - llm-guidance: Use this when a person is described as the independent director of a company.
             - examples: Banana Inc. hasIndependentDirector John Chua
             
             2. hasExecutiveDirector
             - source: Company
             - target: Person
             - llm-guidance: Use when a person is explicitly labeled an Executive Director of the company.
             - examples: Banana Inc. hasExecutiveDirector John Chua
             
             3. hasManagingDirector
             - source: Company
             - target: Person
             - llm-guidance: Use when a person holds the role of Managing Director in a company.
             - examples: Banana Inc. hasManagingDirector John Chua
             
             4. hasIndependentNonExecutiveDirector
             - source: Company
             - target: Person
             - llm-guidance: Use when a person is referred to as an Independent Non-Executive Director.
             - examples: Banana Inc. hasIndependentNonExecutiveDirector John Chua
             
             5. hasChairman
             - source: Company
             - target: Person
             - llm-guidance: Use when a person is referred to as the Chairman of the company.
             - examples: Banana Inc. hasChairman John Chua
             
             6. hasBoardCommittee
             - source: Company
             - target: Committee
             - llm-guidance: Use when a committee is formally established under the company.
             - examples: Banana Inc. hasBoardCommittee Remuneration Committee
             
             7. hasChairperson
             - source: Committee
             - target: Person
             - llm-guidance: Use when a person is the Chairperson of a specific committee.
             - examples: Remuneration Committee hasChairperson Emily Johnson
             
             8. hasMember
             - source: Committee
             - target: Person
             - llm-guidance: Use when a person is a formal member of the committee.
             - examples: Audit Committee hasMember Tan Hui Mei
             
             9. hasAuditor
             - source: Company
             - target: Organization
             - llm-guidance: Use when an audit firm is appointed to verify the company's financial statements.
             - examples: Banana Inc. hasAuditor Baker Tilly Monteiro Heng PLT
             
             10. hasSponsor
             - source: Company
             - target: Organization
             - llm-guidance: Use when a sponsor organization is appointed to guide a listing or fundraising process.
             - examples: Banana Inc. hasSponsor Malacca Securities Sdn Bhd
             
             11. hasShareRegistrar
             - source: Company
             - target: Organization
             - llm-guidance: Use when an organization serves as the company's registrar for shareholder-related matters.
             - examples: Banana Inc. hasShareRegistrar Boardroom Share Registrars Sdn. Bhd.
             
             12. hasIssuingHouse
             - source: Company
             - target: Organization
             - llm-guidance: Use when an issuing house is engaged to manage the issuance process.
             - examples: Banana Inc. hasIssuingHouse Malaysian Issuing House Sdn Bhd
             
             13. listedOn
             - source: Company
             - target: StockMarket
             - llm-guidance: Use when a company is listed or seeks listing on a recognized stock market.
             - examples: Banana Inc. listedOn ACE Market of Bursa Malaysia
       
       c. Output:
         {{
           \"updated_ontology\": {{
             \"entities\": {{
               \"Person\": {{
                 \"definition\": \"An individual human who may hold a governance or operational role within a legal entity.\",
                 \"llm-guidance\": \"Extract full names of individuals. Remove professional titles and honorifics. Focus only on persons mentioned in the context of corporate roles or functions.\",
                 \"examples\": [\"Tan Hui Mei\", \"Emily Johnson\", \"Priya Ramesh\"]
               }},
               \"LegalEntity\": {{
                 \"definition\": \"A formally registered company or service provider involved in listing, audit, legal, or governance functions.\",
                 \"llm-guidance\": \"Extract legal names of companies and organizations with suffixes such as Sdn Bhd, Berhad, PLT. Include both issuers and third-party service firms.\",
                 \"examples\": [\"ABC Berhad\", \"Malacca Securities Sdn Bhd\", \"Baker Tilly Monteiro Heng PLT\"]
               }},
               \"StockMarket\": {{
                 \"definition\": \"A formal exchange where securities of listed companies are traded.\",
                 \"llm-guidance\": \"Extract full names of official stock exchanges or markets mentioned in the context of public company listings.\",
                 \"examples\": [\"Main Market of Bursa Malaysia\", \"ACE Market of Bursa Malaysia\"]
               }}
             }},
             \"relationships\": {{
               \"hasDirector\": {{
                 \"source\": \"LegalEntity\",
                 \"target\": \"Person\",
                 \"llm-guidance\": \"Use when a person is described as a director, whether executive, non-executive, or managing.\",
                 \"examples\": [\"ABC Berhad hasDirector Tan Hui Mei\"]
               }},
               \"hasChairman\": {{
                 \"source\": \"LegalEntity\",
                 \"target\": \"Person\",
                 \"llm-guidance\": \"Use when a person is described as the Chairman of the entity.\",
                 \"examples\": [\"ABC Berhad hasChairman Emily Johnson\"]
               }},
               \"hasCommitteeMember\": {{
                 \"source\": \"LegalEntity\",
                 \"target\": \"Person\",
                 \"llm-guidance\": \"Use when a person is listed as part of any board-level committee (e.g., Audit, Nomination, Remuneration).\",
                 \"examples\": [\"ABC Berhad hasCommitteeMember Priya Ramesh\"]
               }},
               \"hasAuditor\": {{
                 \"source\": \"LegalEntity\",
                 \"target\": \"LegalEntity\",
                 \"llm-guidance\": \"Use when a legal entity is appointed as an auditor to another legal entity.\",
                 \"examples\": [\"ABC Berhad hasAuditor Baker Tilly Monteiro Heng PLT\"]
               }},
               \"hasSponsor\": {{
                 \"source\": \"LegalEntity\",
                 \"target\": \"LegalEntity\",
                 \"llm-guidance\": \"Use when a sponsor organization assists with listing or corporate transactions.\",
                 \"examples\": [\"ABC Berhad hasSponsor Malacca Securities Sdn Bhd\"]
               }},
               \"listedOn\": {{
                 \"source\": \"LegalEntity\",
                 \"target\": \"StockMarket\",
                 \"llm-guidance\": \"Use when a legal entity is listed or intends to be listed on an exchange.\",
                 \"examples\": [\"ABC Berhad listedOn Main Market of Bursa Malaysia\"]
               }}
             }}
           }},
           \"modification_made\": [
             \"Merged 'Company' and 'Organization' into 'LegalEntity'\",
             \"Removed 'Committee' as an entity and flattened its use into 'hasCommitteeMember'\",
             \"Collapsed 'hasExecutiveDirector', 'hasManagingDirector', and 'hasIndependentNonExecutiveDirector' into 'hasDirector'\",
             \"Removed 'hasBoardCommittee', 'hasChairperson', 'hasMember', 'hasShareRegistrar', and 'hasIssuingHouse'\"
           ],
           \"modification_rationale\": [
             \"Company and Organization both represent legal entities differentiated only by contextual roles. Merging them improves schema simplicity and reduces extraction ambiguity.\",
             \"Committee is only meaningful in the context of the company and its members; it was better modeled through direct relationships.\",
             \"Various director roles were semantically overlapping and extractable from context. A single relationship simplifies structure while maintaining meaning.\",
             \"Low-usage or redundant roles like Share Registrar and Issuing House add complexity with limited analytical value and can be handled in downstream processes if needed.\"
           ]
         }}
         
You now understand the guidelines. Please proceed to simplify the ontology according to them.

Ontology Purpose:
{ontology_purpose}

Current Ontology:
"""

PROMPT[
    "ONTOLOGY_CLARITY_ENHANCEMENT"
] = """
You are an ontology clarity enhancement agent specializing in non-taxonomic, relationship-driven models. Your task is to refine the ontology to ensure all attributes of entities and relationships meet defined criteria and consistently support the ontology's purpose.

Guidelines:
   1. Clarity Enhancement Logic
      - For each entity in the ontology:
         - For each attribute:
            - If it does not meet the criteria in Guideline 2:
               - Update its content.
               - Update any affected relationships (e.g., entity name changes that impact source/target).
               - Log the change and rationale as stated in Guideline 4.
      
      - For each relationship in the ontology:
         -For each attribute:
            - If it does not meet the criteria in Guideline 3:
               - Update its content.
               - Log the change and rationale as stated in Guideline 4.
               
   2. Entity Attributes (for each entity):
      - `entity_name`: A meaningful noun phrase that is neither too generic (e.g., "Entity") nor too specific (e.g., "Justin"), but expresses a reusable concept (e.g., "Person").
      - `definition`: A clear, general, and comprehensive description of the entity type.
      - `llm-guidance`: Instructions on how to consistently detect or infer this entity in various contexts.
      - `examples`: At least 2 representative examples, including edge cases.

   3. Relationship Attributes (for each relationship):
      - `relationship_name`: A concise verb phrase in camelCase (e.g., `hasPartner`).
      - `source`: The entity from which the relationship originates.
      - `target`: The entity to which the relationship points.
      - `llm-guidance`: Specific instructions on when and how to use this relationship.
      - `examples`: At least 2 representative examples, including edge cases.
   
   4. Document Changes
      - Each modification should be recorded along with their rationale as shown in the output format in guideline 7 and example in guideline 8.
      - If no clarity enhancements are necessary, return the current ontology unchanged and provide:
         "modification_made": [],
         "modification_rationale": ["No clarity enhancement necessary. Current ontology is already optimal."]
   
   5. Adherence to Ontology Purpose
		- All your clarity enhancement made must support the stated ontology purpose.
      
   6. Cross-Referencing Consistency
      - All mentions of an entity instance-whether in examples for entities or relationships, must strictly follow the llm-guidance and definition of that entity type.
      - Do not introduce formatting inconsistencies that violate the original extraction rules defined for the entity. For example, if the llm-guidance for Person states that honorifics should be excluded, all other instances of Person must adhere to this rule as well.
      - This ensures consistency in entity resolution and prevents semantic drift within the ontology and downstream knowledge graph.
   
 	7. Output Format
		- Unchanged entities and relationships must be returned in the same structure and wording as in the current ontology. Do not reformat or rename unchanged elements.
		- Return only the following raw JSON structure - no explanations, comments, or code block formatting:
      
         {{
            \"updated_ontology\": {{
               \"entities\": {{
                  \"EntityA\": {{
                     \"definition\": \"\",
                     \"llm-guidance\": \"\",
                     \"examples\": []
                  }},
                  \"EntityB\": {{
                     \"definition\": \"\",
                     \"llm-guidance\": \"\",
                     \"examples\": []
                  }}
               }},
               \"relationships\": {{
                  \"RelationshipA\": {{
                     \"source\": \"EntityA\",
                     \"target\": \"EntityB\",
                     \"llm-guidance\": \"\",
                     \"examples\": []
                  }}
               }}
            }},
            \"modification_made\": [],
            \"modification_rationale\": []
			}}

   8. Example
      a. Ontology Purpose
      To construct a knowledge graph of Malaysian public companies that captures key organizational roles and structural information to support governance analysis, such as identifying board members, corporate relationships, and geographic presence.
      
      b. Current Ontology
        Entities:
         1. Person
         - definition: An individual human who may hold a governance or operational role within a legal entity.
         - llm-guidance: Extract full names of individuals. Remove professional titles and honorifics. 
         - examples: Tan Hui Mei, Emily Johnson, Priya Ramesh

         2. LegalEntity
         - definition: A formally registered company or service provider involved in listing, audit, legal, or governance functions.
         - llm-guidance: Extract legal names of companies and organizations with suffixes such as Sdn Bhd, Berhad, PLT. Include both issuers and third-party service firms.
         - examples: ABC Berhad, Malacca Securities Sdn Bhd, Baker Tilly Monteiro Heng PLT
         
         3. StockMarket
         - definition: A formal exchange where securities of listed companies are traded.
         - llm-guidance: Extract full names of official stock exchanges or markets mentioned in the context of public company listings.
         - examples: Main Market of Bursa Malaysia, ACE Market of Bursa Malaysia

      Relationships:
         1. hasDirector
         - source: LegalEntity
         - target: Person
         - llm-guidance: Use when a person is described as a director, whether executive, non-executive, or managing.
         - examples: ABC Berhad hasDirector Tan Hui Mei

         2. hasChairman
         - source: LegalEntity
         - target: Person
         - llm-guidance: Use when a person is described as the Chairman of the entity.
         - examples: ABC Berhad hasChairman Emily Johnson

         3. hasCommitteeMember
         - source: LegalEntity
         - target: Person
         - llm-guidance: Use when a person is listed as part of any board-level committee (e.g., Audit, Nomination, Remuneration).
         - examples: ABC Berhad hasCommitteeMember Priya Ramesh

         4. hasAuditor
         - source: LegalEntity
         - target: LegalEntity
         - llm-guidance: Use when a legal entity is appointed as an auditor to another legal entity.
         - examples: ABC Berhad hasAuditor Baker Tilly Monteiro Heng PLT

         5. hasSponsor
         - source: LegalEntity
         - target: LegalEntity
         - llm-guidance: Use when a sponsor organization assists with listing or corporate transactions.
         - examples: ABC Berhad hasSponsor Malacca Securities Sdn Bhd

         6. listedOn
         - source: LegalEntity
         - target: StockMarket
         - llm-guidance: Use when a legal entity is listed or intends to be listed on an exchange.
         - examples: ABC Berhad listedOn Main Market of Bursa Malaysia
      
      c. Output:
         {{
            \"updated_ontology\": {{
               \"entities\": {{
                  \"Person\": {{
                     \"definition\": \"An individual who holds or has held a governance, executive, or board-level role within a corporate legal entity.\",
                     \"llm-guidance\": \"Extract full names of individuals. Remove professional titles and honorifics (e.g., Mr., Dato', Dr.). \",
                     \"examples\": [\"Tan Hui Mei\", \"Emily Johnson\", \"Priya Ramesh\"]
                  }},
                  \"LegalEntity\": {{
                     \"definition\": \"A formally registered company or service provider involved in listing, audit, legal, or governance functions.\",
                     \"llm-guidance\": \"Extract legal names of companies and organizations with suffixes such as Sdn Bhd, Berhad, PLT. Include both issuers and third-party service firms.\",
                     \"examples\": [\"ABC Berhad\", \"Malacca Securities Sdn Bhd\", \"Baker Tilly Monteiro Heng PLT\"]
                  }},
                  \"StockMarket\": {{
                     \"definition\": \"A formal exchange where securities of listed companies are traded.\",
                     \"llm-guidance\": \"Extract full names of official stock exchanges or markets mentioned in the context of public company listings.\",
                     \"examples\": [\"Main Market of Bursa Malaysia\", \"ACE Market of Bursa Malaysia\"]
                  }}
               }},
               \"relationships\": {{
                  \"hasDirector\": {{
                     \"source\": \"LegalEntity\",
                     \"target\": \"Person\",
                     \"llm-guidance\": \"Use when a person is described as a director, whether executive, non-executive, or managing.\",
                     \"examples\": [\"ABC Berhad hasDirector Tan Hui Mei\"]
                  }},
                  \"hasChairman\": {{
                     \"source\": \"LegalEntity\",
                     \"target\": \"Person\",
                     \"llm-guidance\": \"Use when a person is described as the Chairman of the entity.\",
                     \"examples\": [\"ABC Berhad hasChairman Emily Johnson\"]
                  }},
                  \"hasCommitteeMember\": {{
                     \"source\": \"LegalEntity\",
                     \"target\": \"Person\",
                     \"llm-guidance\": \"Use when a person is explicitly listed as a serving member of a specific board committee, such as Audit, Nomination, or Remuneration. Avoid using if the committee name or function is ambiguous or missing.\",
                     \"examples\": [\"ABC Berhad hasCommitteeMember Priya Ramesh\", \"XYZ Berhad hasCommitteeMember Emily Johnson\"]
                  }},
                  \"hasAuditor\": {{
                     \"source\": \"LegalEntity\",
                     \"target\": \"LegalEntity\",
                     \"llm-guidance\": \"Use when a legal entity is appointed as an auditor to another legal entity.\",
                     \"examples\": [\"ABC Berhad hasAuditor Baker Tilly Monteiro Heng PLT\"]
                  }},
                  \"hasSponsor\": {{
                     \"source\": \"LegalEntity\",
                     \"target\": \"LegalEntity\",
                     \"llm-guidance\": \"Use when a sponsor organization assists with listing or corporate transactions.\",
                     \"examples\": [\"ABC Berhad hasSponsor Malacca Securities Sdn Bhd\"]
                  }},
                  \"listedOn\": {{
                     \"source\": \"LegalEntity\",
                     \"target\": \"StockMarket\",
                     \"llm-guidance\": \"Use when a legal entity is listed or intends to be listed on an exchange.\",
                     \"examples\": [\"ABC Berhad listedOn Main Market of Bursa Malaysia\"]
                  }}
               }}
            }},
            \"modification_made\": [
               \"Person\",
               \"hasCommitteeMember\"
            ],
            \"modification_rationale\": [
               \"Updated definition and llm-guidance for 'Person' to provide clearer disambiguation criteria and exclusion rules for extraction.\",
               \"Refined llm-guidance for 'hasCommitteeMember' to prevent misuse where board committee membership is not clearly defined, improving precision for edge cases.\"
            ]
         }}

You now understand the guidelines. Please proceed to enhance the clarity of the ontology according to them.

Ontology Purpose:
{ontology_purpose}

Current Ontology:
"""

PROMPT[
    "ONTOLOGY_CQ_GENERATION"
] = """
You are a non-taxonomic, relationship-driven ontology competency question generation agent. Your goal is to generate realistic, answerable, and ontology-grounded competency questions that test whether the ontology can support the types of queries required by its purpose.

Ontology Purpose:
\"{ontology_purpose}\"

Guidelines:
	1. Do not assume access to information beyond what is structurally captured in the ontology and its defined data sources. 
      - Do not infer behavioral outcomes, causality, or abstract effects that are not modeled.
      - Questions must remain within the scope of \"{ontology_purpose}\"

	2. Based on this purpose, generate {personality_num} distinct user personalities.

	3. For each personality, generate {task_num} distinct tasks.

	4. For each task, generate {question_num} distinct competency questions that evaluate the ontology's robustness.

	5. All personalities, tasks, and questions must be meaningfully distinct from one another. Collectively, they should aim to cover as many edge cases as possible to enable a thorough evaluation of the ontology.

	6. Competency questions should be categorized by difficulty level as follows:
 
      - Easy: Lookup queries or queries involving a single entity.
      
      - Moderate: One-hop relationships (e.g., A → B).
      
      - Difficult: Multi-hop relationships, filters, or aggregates.
      
      - Extremely Difficult: Requires multi-part queries, joins, subqueries, or nested logic.

	7. For each task, distribute the questions evenly across the four difficulty levels. That is, generate ({question_num} / 4) question(s) for each difficulty level: Easy, Moderate, Difficult, and Extremely Difficult.
 
   8. Avoid using the word "ontology" in any of the generated questions. Instead, focus on how a user with the generated personality would interrogate the system to retrieve relevant information. Questions should:

      - Reflect real-world use cases.

      - Require increasing levels of reasoning (from factual lookups to complex relational inferences).

      - Be phrased as high-level, domain-relevant inquiries.

      - Not refer explicitly to the ontology's structure.

   9. All questions must be generalized. Do not mention specific entities from any data source or ontology instance. Questions should test the structure and reasoning capability of the ontology, not recall of named examples.
   
	10. Follow the exact output format shown below. Do not include any additional text or explanation.
	
		{{
			\"PersonalityA\": {{
				\"TaskA\": {{
					\"Easy\": [\"QuestionA\"],
					\"Moderate\": [\"QuestionB\"],
					\"Difficult\": [\"QuestionC\"],
					\"Extremely Difficult\": [\"QuestionD\"]
				}}
			}}
		}}

"""

PROMPT[
    "ONTOLOGY_COMPETENCY_EVALUATION"
] = """
You are a non-taxonomic, relationship-driven ontology competency evaluation agent. Your task is to assess the robustness of a given ontology in answering specific competency questions without compromising its intended purpose.

Guidelines
   1. All suggestions must preserve the ontology's ability to fulfill its intended purpose: {ontology_purpose}.
   
	2. For each competency question, evaluate how well the ontology supports it using one of the following categories.

      a. Not Supportive: The ontology lacks necessary entities or relationships, requiring entirely new components.
      
      b. Slightly Supportive: The ontology has some relevant entities or relationships but requires significant additions or modifications.
      
      c. Partially Supportive: The ontology supports the question but requires minor adjustments to existing entities or relationships.
      
      d. Fully Supportive: The ontology fully supports the question with existing entities and relationships.
  
   3. For every competency question, include a brief justification for your chosen support level.
   
   4. Set require_resolution:
      - Set to "TRUE" if any competency question is evaluated as "Slightly Supportive" or "Partially Supportive".
      - Set to "FALSE" otherwise
   
   4. Include a concise structural summary of the ontology in the summary field.

	5. You must produce output strictly in the format below.
	
		{{
         \"competency_evaluation\": {{
            \"PersonalityA\": {{
               \"TaskA\": [
                  {{
                     \"question\": \"questionA\",
                     \"difficulty\": \"Easy\",
                     \"support\": \"Fully Supportive\",
                     \"justification\": \"\"
                  }}
               ]
            }}
         }},
         \"summary\": \"\",
         \"require_resolution\": 
		}}
  
Steps:
   1. Read the ontology structure and its intended use case.

   2. For every question under each task and personality:
      - Determine if the current ontology can answer it based on existing entities and relationships.
      - Assign one of the four support levels.
      - Provide a concise justification.

   3. In the summary field, describe the ontology's general capability, structure, and any observed strengths or limitations.

Competency Questions:
{competency_questions}

You now understand the guidelines and competency questions. Please evaluate the ontology based on the guidelines and provide the output in the required format.

Ontology:
"""

PROMPT[
    "ENTITY_RELATIONSHIP_MERGER"
] = """"
You are an entity-relationship merger agent. Your task is to evaluate whether entity and relationship instances are factually equivalent, and merge them accordingly.

Guidelines:
	1. Each entity has the following attributes:
		- id: Unique identifier
		- name: Entity's name
		- type: Entity's type
		- description: Entity's description

   2. Each relationship has the following attributes:
		- id: Unique identifier
		- type: Relationship's type
		- source: Name of the relationship's source entity
		- target: Name of the relationship's target entity
      - description: Relationship's description
      - valid_date: Date when the relationship becomes valid
      - invalid_date: Date when the relationship becomes invalid 
      - temporal_note: Additional temporal information
      
   3. Relationship Integrity:
      - When merging entities, update all relationships that reference the merged entity—whether as source or target—to reference the remaining entity.
         
	4. Entity Evaluation Logic:
		- Given two entities :
			- If they are the same types and their names are literally the same (e.g., "Lim Chee Meng" and "Lim Chee Meng"):
					- If their descriptions refer to the same thing (focus on meaning, not wording; descriptions may complement each other):
						- They are factually equivalent -> proceed to merge.
					- Else:
						- Not factually equivalent -> skip.

			- If they are the same types and their names are similar (e.g., "Lim Chee Meng" and "Chee Meng Lim"):
					- If their descriptions refer to the same thing:
						- Factually equivalent -> proceed to merge.
					- Else:
						- Not factually equivalent -> skip.

			- If they are the same types and their names are not similar (e.g., "Lim Chee Seng" and "Ong Chee Seng" or "XYZ Berhad" and "XYZ Sdn Bhd"):
				- Not factually equivalent -> skip.

			- If their type is different:
				- Not factually equivalent.

   5. Relationship Evaluation Logic:
      - Given two relationships:
         - If they are the same types and having the same source and target:
            - If their descriptions refer to the same subject 
               - They are factually equivalent -> proceed to merge.
            - Else:
               - Not factually equivalent -> skip.

         - If they are the same types and having different source and target
            - Not factually equivalent -> skip.

         - If their types differ:
            - Not factually equivalent -> skip.
            
	6. Entity Merger Procedure:
		- If two entities are factually equivalent:
			- And their descriptions are complementary:
				- Mark EntityB as "to_be_removed"
				- Merge EntityB's description into EntityA's description (minimally and meaningfully).
            - Update all relationships that reference EntityB to reference EntityA instead.
			- And their descriptions are not complementary:
				- Mark EntityB as "to_be_removed"
				- Keep EntityA's description unchanged.
            - Update all relationships that reference EntityB to reference EntityA instead.
   
   6. Relationship Merger Procedure:
      - If two relationships are factually equivalent:
         - And their descriptions are complementary:
            - Mark RelationshipB as "to_be_removed"
            - Merge RelationshipB's description into RelationshipA's description (minimally and meaningfully).
            - Update the temporal information: for valid_date and invalid_date, set them to earlier dates as needed, and update temporal_note accordingly.
         - And their descriptions are not complementary:
            - Mark RelationshipB as "to_be_removed"
            - Keep RelationshipA's description unchanged.
   
	7. Precision is critical
		- Only declare equivalence when you are strongly confident. Prioritize accuracy over coverage.

	8. Multiple Duplicates:
      - For multiple factually equivalent entities (3+):
         - Keep one.
         - Merge all others into it if needed.
         - Modify the description, valid_date, invalid_date, and temporal_note only if additional info is complementary.
      - For multiple factually equivalent relationships (3+):
         - Keep one.
         - Merge all others into it if needed.
         - Modify the description,valid_date, invalid_date, and temporal_note only if additional info is complementary

	9. Provide your output based on format specified below. No additional explanation, text, or headers are required in the output.
	
		{{
			\"entities_to_be_removed\": [
				\"entityX's id\",
				\"entityY's id\",
				\"entityZ's id\"
			],
         \"relationships_to_be_removed\": [
            \"relationshipX's id\",
            \"relationshipY's id\",
         ],
			\"entities_to_be_modified\": {{
				\"entityA's id\": \"new description for entity A\"
         }},
   	   \"relationships_to_be_modified\": {{
				\"relationshipA's id\": {{
               \"description\": \"new description for relationship A\",
               \"source\": \"updated name of source entity (if updated)\",
               \"target\": \"updated name of target entity (if updated)\"
            }}
			}}
		}}

Example: 
   a. Example Input:
   
      Example Entities:
         1. LIM CHEE MENG
            - id: E001
            - type: Person
            - description: CEO of XYZ BERHAD, based in Kuala Lumpur.

         2. LIM CHEE MENG
            - id: E002
            - type: Person
            - description: Leads XYZ BERHAD as Chief Executive Officer.

         3. CHEE MENG LIM
            - id: E003
            - type: Person
            - description: CEO of XYZ BERHAD, oversees operations in Malaysia.
         
         4. LIM CHEE SENG
            - id: E004
            - type: Person
            - description: CTO of XYZ BERHAD.
         
         5. XYZ BERHAD
            - id: E005
            - type: Company
            - description: A technology company headquartered in Kuala Lumpur.

         6. XYZ SDN BERHAD
            - id: E006
            - type: Company
            - description: A subsidiary of XYZ BERHAD.

         7. LIM CHEE MENG
            - id: E007
            - type: Person
            - description: A software engineer at ABC Corp.

      Example Relationships:
         1. employs
            - id: R001
            - source: XYZ BERHAD
            - target: LIM CHEE MENG
            - description: XYZ BERHAD employs LIM CHEE MENG as CEO.
            - valid_date: NA
            - invalid_date: NA
            - temporal_note: As at 1-Jan-2023.

         2. employs
            - id: R002
            - source: XYZ BERHAD
            - target: LIM CHEE MENG
            - description: LIM CHEE MENG is employed by XYZ BERHAD as Chief Executive Officer.
            - valid_date: 1-Jan-2023
            - invalid_date: NA
            - temporal_note: Current role.

         3. employs
            - id: R003
            - source: XYZ BERHAD
            - target: CHEE MENG LIM
            - description: XYZ BERHAD employs CHEE MENG LIM as CEO.
            - valid_date: NA
            - invalid_date: NA
            - temporal_note: 1-Jan-2023.

         4. employs
            - id: R004
            - source: XYZ BERHAD
            - target: LIM CHEE SENG
            - description: XYZ BERHAD employs LIM CHEE SENG as CTO.
            - valid_date: 1-Jan-2023
            - invalid_date: NA
            - temporal_note: Ongoing.
   
   b. Example Output:
   
      {{
         \"entities_to_be_removed\": [
            \"E002\",
            \"E003\"
         ],
         \"relationships_to_be_removed\": [
            \"R002\",
            \"R003\"
         ],
         \"entities_to_be_modified\": {{
            \"E001\": \"CEO of XYZ BERHAD, oversees operations in Malaysia.\"
         }},
         \"relationships_to_be_modified\": {{
            \"R001\": {{
               \"description\": \"XYZ BERHAD employs LIM CHEE MENG as CEO.\",
               \"source\": \"XYZ BERHAD\",
               \"target\": \"LIM CHEE MENG\",
               \"valid_date\": \"1-Jan-2023\",
               \"invalid_date\": \"NA\",
               \"temporal_note\": \"As at 1-Jan-2023.\"
            }}
         }}
      }}

Steps to Follow:

	1. Identify potentially equivalent entities.

	2. Evaluate equivalence of entities.

	3. Perform merging of entities if applicable.
 
   4. Ensure that all relationships referencing the merged entity are updated to reference the remaining entity.
   
   5. Evaluate equivalence of relationships.

	6. Perform merging of relationships if applicable.

	7. Output result in the specified format.

You now understand the task. Please proceed to perform merging for the following entities and relationships:

Entities & Relationships:
"""


PROMPT[
    "REPORTS PARSING"
] = """
                        You are a professional financial analyst assistant and a PDF-to-text interpreter. Your task is to extract, analyze, and convert the full content of the attached annual report PDF into structured, plain text output with 100% preservation of the original meaning and detail.

                        You must not omit or summarize any portion of the document. The conversion must be complete and exhaustive—even if the document contains 100+ pages.

                        For charts, tables, diagrams, infographics, and illustrations that cannot be converted directly into text, you must not ignore them. Instead, you must interpret them thoroughly and describe their full meaning, trends, values, and structure in context, including any page references. The goal is to preserve the entire informational content of the document.

                        ### Formatting requirements  
                        1. Use Markdown.  
                        2. Insert **one empty line**  
                        - *before and after* every top-level heading (`## …`).  
                        - *before* each sub-topic block (bold label + content) and *after* its final paragraph or bullet list.  
                        3. Present every sub-topic label in **bold**, end it with a colon (`:`), then start the narrative or bullet list on the next line.  
                        4. Within a block, use bullet lists (`*`) where they improve clarity; otherwise use full sentences.  
                        5. Maintain all page-number references exactly as they appear in the source.

                        Follow this exact section order:

                        ## Company Overview
                        - General company background
                        - Business model and operations
                        - Vision & mission statement
                        - *(If any images/infographics appear, describe them with page reference, e.g., 'Company Overview Infographic, pg 5')*

                        ## Financial Statements
                        - Income statement, balance sheet, cash flow highlights
                        - Revenue/profit trends and financial performance
                        - Key ratios (e.g. P/E, ROE, Debt-to-Equity)
                        - *(If tables/charts appear, explain and reference them, e.g., 'Balance Sheet Summary Table, pg 12')*

                        ## Key Messages from Management
                        - CEO/Chairman statements
                        - Business strategy and outlook
                        - *(Summarize speeches or leadership imagery with page reference)*

                        ## Industry Overview
                        - Market conditions and economic context
                        - Competitive positioning
                        - *(Summarize charts with insight and page reference)*

                        ## Leadership & Governance
                        - Board of directors, org charts, governance policies
                        - *(Describe structure charts with interpretation and page reference)*

                        ## Shareholder Information
                        - Shareholding breakdown
                        - Dividends and ownership data
                        - *(Interpret shareholder tables with summary and page reference)*

                        ## ESG & Sustainability
                        - Environmental/social/governance initiatives
                        - CSR programs and commitments
                        - *(Interpret ESG metrics/tables with context and reference)*

                        ## Risk Factors
                        - Strategic, financial, and operational risks
                        - Legal/regulatory uncertainties
                        - *(Interpret risk matrices/visuals and explain meaning with page reference)*

                        ## Other Notable Sections
                        - Any other content not captured above

                        You are to return only the structured plain text Markdown output—no commentary, metadata, or explanation.
                    """