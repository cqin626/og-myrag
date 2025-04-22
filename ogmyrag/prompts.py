PROMPT = {}

PROMPT["ENTITIES_RELATIONSHIPS_PARSING"] = """
Goal: 
   You are an information extraction system grounded in a specific ontology. You will be provided with a piece of text and an ontology definition consisting of a list of valid entity classes and valid relationships between those classes. Your task is to extract only the entities and relationships that match the ontology exactly.

General Rules:
   1. Extract only entities that participate in at least one defined relationship. Entities that do not participate in any valid relationship defined in the ontology must not be included in the output.

   2. Do not create or infer any entity types or relationship types that are not explicitly defined in the ontology.

   3. Use the exact relationship names and entity classes as specified in the ontology.
   
   4. During actual parsing, you will be provided with key-value pairs that help interpret the source text. You must apply these mappings when extracting and storing entities and relationships to ensure consistency and accuracy.
   
   5. You are subject to no performance constraints—there are no limits on processing time. For example, if the input consists of a 100,000-word text, you must perform complete entity and relationship extraction without skipping or omitting any part. Accuracy and comprehensiveness are the top priorities, even for texts as long as 100,000 words.
   
   6. Return only the structured output in the specified format-exclude all explanations, headers, or additional text.
   
   7. Return an empty output structure {{\"entities\": [], \"relationships\": []}} if the ontology is missing, invalid, or empty; if the source text is empty or irrelevant; or if no matching entities or relationships are found."
   
Output Format:
   {{\"entities\": [\"<entity_type>{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_content>\"], \"relationships\": [\"<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_type>{tuple_delimiter}<relationship_description>\"]}}
   
Explanation on the components of the output format:
   1. Entities
      Each entity must be formatted as: "<entity_type>{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_content>"
      Where:
         - <entity_type>: The class or type of the entity, strictly as defined in the ontology.
         - <entity_name>: The canonical name of the entity, based on the ontology definition and valid extraction rules.
         - <entity_content>: A comprehensive, factual description of the entity, based on the source text.
      
   2. Relationships
      Each relationship must be formatted as: "<source_entity>{tuple_delimiter}<target_entity>{tuple_delimiter}<relationship_type>{tuple_delimiter}<relationship_description>"
      Where:
         - <source_entity>: The <entity_name> of source entity.
         - <target_entity>: The <entity_name> of the target entity.
         - <relationship_type>: One of the relationship types defined in the ontology.
         - <relationship_description>: A comprehensive explanation of the relationship, based on the source text.

Examples: 
   [1] Sample ontology written in plain-text:
   
      Entity Classes:

         - Organization: Any structured group formed to achieve common goals, including clubs, unions, or federations.
         - Individual: A human being involved with any organization, regardless of role.
         - Region: A geographic division such as a county, district, or landmass.
         - Tool: Any mechanical or digital item designed to assist with specific tasks.
         - Program: A scheduled series of coordinated activities or initiatives managed by an organization.

      Relationships:
      
         - Individual leads Program
         - Individual affiliatedWith Organization
         - Organization locatedIn Region
         - Organization develops Tool
         - Organization administers Program
         - Region overlapsWith Region
         
   [2] Sample source text:
   
      The Wild Earth Union operates in Westridge District. It runs the Green Roots Program, which is led by Yasmin Ortega. They also created EcoMap Mobile, a tool for tracking illegal dumping.

   [3] Sample output:
      {{
         \"entities\": [
            \"Organization{tuple_delimiter}Wild Earth Union{tuple_delimiter}Wild Earth Union operates in Westridge District and runs multiple environmental initiatives.\",
            \"Region{tuple_delimiter}Westridge District{tuple_delimiter}Westridge District is a region where Wild Earth Union is active.\",
            \"Program{tuple_delimiter}Green Roots Program{tuple_delimiter}Green Roots Program is an initiative managed by Wild Earth Union.\",
            \"Individual{tuple_delimiter}Yasmin Ortega{tuple_delimiter}Yasmin Ortega is the leader of the Green Roots Program.\",
            \"Tool{tuple_delimiter}EcoMap Mobile{tuple_delimiter}EcoMap Mobile is a tool developed by Wild Earth Union to track illegal dumping.\"
         ],
         \"relationships\": [
            \"Wild Earth Union{tuple_delimiter}Westridge District{tuple_delimiter}locatedIn{tuple_delimiter}Wild Earth Union operates in Westridge District.\",
            \"Wild Earth Union{tuple_delimiter}Green Roots Program{tuple_delimiter}administers{tuple_delimiter}Wild Earth Union runs the Green Roots Program.\",
            \"Yasmin Ortega{tuple_delimiter}Green Roots Program{tuple_delimiter}leads{tuple_delimiter}Yasmin Ortega leads the Green Roots Program.\",
            \"Wild Earth Union{tuple_delimiter}EcoMap Mobile{tuple_delimiter}develops{tuple_delimiter}Wild Earth Union created EcoMap Mobile.\",
            \"Yasmin Ortega{tuple_delimiter}Wild Earth Union{tuple_delimiter}affiliatedWith{tuple_delimiter}Yasmin Ortega is affiliated with Wild Earth Union.\"
         ]
      }}

Below is the actual ontology you must follow for parsing. The examples inside the ontology are only for learning purposes - do not extract entities or relationships from them:

{ontology}

Below are key-value pairs to help you interpret the source text. When storing entities and relationships, always map keys to their corresponding values:

{source_text_definitions}
   
You already know the ontology and the required output format. Now extract entities and relationships from the following text, strictly following these guidelines:

   - Use only the actual ontology, including any notes provided for each entity class and relationship type.
   - Apply the key-value mappings to interpret and normalize text content.
   - Follow the general extraction rules exactly.
   - Return the output only in the specified structured format.

Source text:
"""

PROMPT["DEFINITIONS_PARSING"] ="""
You are an information extraction system. The provided PDF contains word definitions and word usages that carry special meaning within the document's context. Your task is to extract this information and output it as key-value pairs in JSON format. Return only the structured output—no explanations, headers, or additional text.
Output format example:
   {
   "Company": "Autocount Dotcom Berhad"
   }
"""

PROMPT["PDF_PARSING"] = """
You are a PDF-to-text converter and interpreter. You are given a PDF, and you must convert it into plain text with absolutely no loss of information. The converted output must preserve 100% of the original meaning of the source document.

For charts, diagrams, tables, or illustrations where direct conversion to text may result in loss of information, you must not ignore these elements. Instead, provide a comprehensive interpretation. This interpretation must fully and accurately convey 100% of the original content and meaning of each visual element.

You are subject to no performance constraints—there are no limits on file size or processing time. For example, if the input is a 100-page PDF, you must perform complete conversion and interpretation for all 100 pages, without skipping or omitting any part.

Return only the plain text output—no explanations, metadata, headers, or additional commentary.
"""