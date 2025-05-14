from __future__ import annotations

import json
import logging

from typing import TypedDict

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import get_formatted_ontology, get_formatted_openai_response, get_clean_json
from ..storage import MongoDBStorage
from ..base import BaseAgent, BaseMultiAgentSystem
from .ontology_construction_util import (
   get_new_version,
   get_formatted_cq_for_db,
   get_formatted_ontology_for_db,
   get_formatted_feedback_for_db,
   get_formatted_cq_for_display,
   get_formatted_feedback_for_display
)

ontology_construction_logger = logging.getLogger("ontology_construction")

class StorageConfig(TypedDict):
    connection_uri: str
    database_name: str
    collection_name: str
    
class CQGenerationAgent(BaseAgent):
    """
    An agent responsible for generating competency questions to evaluate the robustness of the given ontology.
    """
    async def handle_task(self, **kwargs) -> str:
        """
         Parameters:
            personality_num (int): Number of personalities to generate.
            task_num (int): Number of tasks to generate.
            question_num (int): Number of questions to generate.
        """
        system_prompt = PROMPT["ONTOLOGY_CQ_GENERATION"].format(
           ontology_purpose=self.agent_system.ontology_purpose,
           personality_num=kwargs.get("personality_num", 1) or 1,
           task_num=kwargs.get("task_num", 1) or 1,
           question_num=kwargs.get("question_num", 4) or 4,
         )
        user_prompt = "You now understand the guidelines. Please generate the competency questions accordingly."
        
      #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")
        ontology_construction_logger.info(f"CQGenerationAgent is called")
        try:
            response = await fetch_responses_openai(
                model="gpt-4.1-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0,
                max_output_tokens=32768
            )
            ontology_construction_logger.info(f"CQGenerationAgent:\nCompetency questions generation response details:\n{get_formatted_openai_response(response)}")
            
            return response.output_text   
        except Exception as e:
            ontology_construction_logger.error(f"CQGenerationAgent:\nCQ generation failed: {str(e)}")
            return ""
   
class OntologyConstructionAgent(BaseAgent):
    """
    An agent responsible for constructing ontology based on source text and feedback.
    """
    async def handle_task(self, **kwargs) -> str:
        """
         Parameters:
            source_text (str): The source text to parse.
            document_desc (str): A description of the source text.
            ontology (dict): The existing ontology.
            requires_reconstruct (bool): Whether to parse twice
        """
        formatted_ontology = get_formatted_ontology(data=kwargs.get("ontology",{}) or {})
        
        system_prompt = PROMPT["ONTOLOGY_CONSTRUCTION"].format(
           ontology=formatted_ontology,
           ontology_purpose=self.agent_system.ontology_purpose,
           document_desc=kwargs.get("document_desc", "NA") or "NA",
        )
        
        user_prompt=kwargs.get("source_text", "NA") or "NA"
        
        ontology_construction_logger.info(f"OntologyConstructionAgent is called")
        
      #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        try:
            response = await fetch_responses_openai(
            model="o4-mini",
               system_prompt=system_prompt,
               user_prompt=user_prompt,
               text={
                  "format": {"type": "text"}
               },
               reasoning={
                  "effort": "medium"
               },
               max_output_tokens=100000,
               tools=[],
            )
            ontology_construction_logger.info(f"OntologyConstructionAgent\nOntology construction response details:\n{get_formatted_openai_response(response)}")
            ontology_construction_logger.info(f"OntologyConstructionAgent\nOntology construction output text:\n{get_formatted_ontology(get_clean_json(response.output_text))}")
            
            if(kwargs.get("requires_reconstruct", False) or False):
               new_response = await fetch_responses_openai(
               model="o4-mini",
                  user_prompt=PROMPT["ONTOLOGY_RECONSTRUCTION"],
                  text={
                     "format": {"type": "text"}
                  },
                  reasoning={
                     "effort": "medium"
                  },
                  previous_response_id=response.id,
                  max_output_tokens=100000,
                  tools=[],
               )
               
               
               ontology_construction_logger.info(f"OntologyConstructionAgent\nOntology reconstruction response details:\n{get_formatted_openai_response(new_response)}")
               ontology_construction_logger.info(f"OntologyConstructionAgent\nOntology reconstruction output text:\n{get_formatted_ontology(get_clean_json(new_response.output_text))}")
               
               return new_response.output_text
            else:
               return response.output_text
        except Exception as e:
            ontology_construction_logger.error(f"OntologyConstructionAgent\nOntology construction failed: {str(e)}")
            return ""

class OntologyComplexityReductionAgent(BaseAgent):
    """
    An agent responsible for reducing the complexity of the ontology.
    """
    async def handle_task(self, **kwargs) -> str:
        """ 
        Parameters:
          ontology (dict): The existing ontology.
        """
        formatted_ontology = get_formatted_ontology(data=kwargs.get("ontology",{}) or {})
        
        system_prompt = PROMPT["ONTOLOGY_COMPLEXITY_REDUCTION"].format(ontology_purpose=self.agent_system.ontology_purpose)
        
        user_prompt=formatted_ontology
        
        ontology_construction_logger.info(f"OntologyComplexityReductionAgent is called")
        
      #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                text={
                  "format": {"type": "text"}
                },
                reasoning={
                  "effort": "medium"
                },
                max_output_tokens=50000,
                tools=[],
            )
            ontology_construction_logger.info(f"OntologyComplexityReductionAgent\nOntology complexity reduction response details:\n{get_formatted_openai_response(response)}")
            
            return response.output_text
        except Exception as e:
            ontology_construction_logger.error(f"OntologyComplexityReductionAgent\nOntology complexity reduction failed: {str(e)}")
            return ""
         
class OntologyClarityEnhancementAgent(BaseAgent):
    """
    An agent responsible for enhancing the clarity of the ontology.
    """
    async def handle_task(self, **kwargs) -> str:
        """ 
        Parameters:
          ontology (dict): The existing ontology.
        """
        formatted_ontology = get_formatted_ontology(data=kwargs.get("ontology",{}) or {})
        
        system_prompt = PROMPT["ONTOLOGY_CLARITY_ENHANCEMENT"].format(ontology_purpose=self.agent_system.ontology_purpose)
        
        user_prompt=formatted_ontology
        
        ontology_construction_logger.info(f"OntologyClarityEnhancementAgent is called")
        
      #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        try:
            response = await fetch_responses_openai(
               model="o4-mini",
               system_prompt=system_prompt,
               user_prompt=user_prompt,
               text={
                  "format": {"type": "text"}
               },
               reasoning={
                  "effort": "medium"
               },
               max_output_tokens=50000,
               tools=[],
            )
            
            ontology_construction_logger.info(f"OntologyClarityEnhancementAgent\nOntology clarity enhancement response details:\n{get_formatted_openai_response(response)}")
            
            return response.output_text
        except Exception as e:
            ontology_construction_logger.error(f"OntologyClarityEnhancementAgent\nOntology clarity enhancement failed: {str(e)}")
            return ""

class OntologyEvaluationAgent(BaseAgent):
    """
    An agent responsible for evaluating ontology based on task-driven competency questions.
    """
    async def handle_task(self, **kwargs) -> str:
        """
         Parameters:
            ontology (dict): The ontology.
            competency_questions (str): The competency questions to evaluate the ontology.
        """
        system_prompt = PROMPT["ONTOLOGY_COMPETENCY_EVALUATION"].format(
           ontology_purpose=self.agent_system.ontology_purpose,
           competency_questions=kwargs.get("competency_questions", "NA") or "NA",
        )
        
        user_prompt= get_formatted_ontology(
           data=kwargs.get("ontology",{}) or {},
           exclude_entity_fields=["llm-guidance", "is_stable"],
           exclude_relationship_fields=["llm-guidance", "is_stable"]
         )
        
      #   ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")

        ontology_construction_logger.info(f"OntologyEvaluationAgent is called")

        try:
            response = await fetch_responses_openai(
                model="o4-mini",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                text={
                  "format": {"type": "text"}
                },
                reasoning={
                  "effort": "medium"
                },
                max_output_tokens=50000,
                tools=[],
            )
            ontology_construction_logger.info(f"OntologyEvaluationAgent\nOntology evaluation response details:\n{get_formatted_openai_response(response)}")
            
            return response.output_text
        except Exception as e:
            ontology_construction_logger.error(f"OntologyEvaluationAgent\nOntology evaluation failed: {str(e)}")
            return ""

class OntologyConstructionSystem(BaseMultiAgentSystem):
    def __init__(
       self, 
       ontology_purpose: str,
       ontology_config: StorageConfig, 
       cq_config: StorageConfig,
       feedback_config: StorageConfig
       ):
        super().__init__(
            {
               "CQGenerationAgent": CQGenerationAgent("CQGenerationAgent"),
               "OntologyConstructionAgent": OntologyConstructionAgent("OntologyConstructionAgent"),
               "OntologyEvaluationAgent": OntologyEvaluationAgent("OntologyEvaluationAgent"),
               "OntologyComplexityReductionAgent": OntologyComplexityReductionAgent("OntologyComplexityReductionAgent"),
               "OntologyClarityEnhancementAgent": OntologyClarityEnhancementAgent("OntologyClarityEnhancementAgent")
            }
        )
        try:
         self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
         self.onto_storage.use_database(ontology_config["database_name"])
         self.onto_storage.use_collection(ontology_config["collection_name"])
         
         self.cq_storage = MongoDBStorage(cq_config["connection_uri"])
         self.cq_storage.use_database(cq_config["database_name"])
         self.cq_storage.use_collection(cq_config["collection_name"])
         
         self.feedback_storage = MongoDBStorage(feedback_config["connection_uri"])
         self.feedback_storage.use_database(feedback_config["database_name"])
         self.feedback_storage.use_collection(feedback_config["collection_name"])
         
         self.ontology_purpose = ontology_purpose
        except Exception as e:
           ontology_construction_logger.error(f"OntologyConstructionSystem: {e}")
           raise ValueError(f"Failed to connect to MongoDB: {e}")
    
    async def handle_request(self, **kwargs) -> None:
      """
       Parameters:
         source_text (str): Source text to parse.
         document_desc (str): Description of source text.
         requires_reconstruct (bool): Whether to reconstruct the ontology
      """
      source_text = kwargs.get("source_text","NA") or "NA"
      document_desc = kwargs.get("document_desc","NA") or "NA"
      requires_reconstruct = kwargs.get("requires_reconstruct",False) or False
      
      await self.update_ontology(source_text=source_text,document_desc=document_desc, requires_reconstruct=requires_reconstruct)
      ontology_construction_logger.info(f"OntologyConstructionSystem\nOntology is updated, current version: {self.get_current_onto_version()}")
      
    async def update_ontology(
       self,
       source_text: str,
       document_desc: str,
       requires_reconstruct: bool
       ):
         current_onto = self.get_current_onto()
         current_onto_version = self.get_current_onto_version()
         current_cq_version = self.get_current_cq_version()
         
         # Step 1: Call construction agent
         try:
            raw_response = await self.agents["OntologyConstructionAgent"].handle_task(
               source_text=source_text,
               ontology=current_onto,
               document_desc=document_desc,
               requires_reconstruct=requires_reconstruct
            )
            if not raw_response:
               raise ValueError("Ontology construction returned no output.")
         except Exception as e:
            raise ValueError(f"Error while constructing ontology: {e}")
         
         # Step 2: Format response into json
         try:
            response = get_clean_json(raw_response)
            entities = response.pop("entities", {})
            relationships = response.pop("relationships", {})
            note = response.pop("note","")
            
         except Exception as e:
            raise ValueError(f"Error while converting ontology to json: {e}")

         # Step 3: Upload constructed ontology to db
         try:
            self.onto_storage.update_document({"is_latest": True}, {"is_latest": False})
            self.onto_storage.create_document(
               get_formatted_ontology_for_db(
                  ontology= {
                     "entities": entities,
                     "relationships": relationships
                  },
                  model="o4-mini",
                  modification_note=note,
                  purpose=self.ontology_purpose,
                  version=get_new_version(current_version=current_onto_version, update_type="PATCH"),
                  cq_version=current_cq_version
               )
            )
         except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")
   
    async def minimize_ontology(self) -> None:
         current_onto = self.get_current_onto()
         current_onto_version = self.get_current_onto_version()
         current_cq_version = self.get_current_cq_version()
         
         # Step 1: Call complexity reduction agent
         try:
            raw_response = await self.agents["OntologyComplexityReductionAgent"].handle_task(ontology=current_onto)
            if not raw_response:
               raise ValueError("Ontology minimization returned no output.")
         except Exception as e:
            raise ValueError(f"Error while minimizing ontology: {e}")
         
         # Step 2: Format response into json
         try:
            response = get_clean_json(raw_response)
            
            updated_ontology = response.get("updated_ontology", {})
            entities = updated_ontology.pop("entities", {})
            relationships = updated_ontology.pop("relationships", {})
            
            removed_entities = response.pop("removed_entities", [])
            removed_relationships = response.pop("removed_relationships", [])
            note = response.pop("note", "")
         except Exception as e:
            raise ValueError(f"Error while converting ontology to json: {e}")

         # Step 3: Upload minimized ontology to db
         try:
            self.onto_storage.update_document({"is_latest": True}, {"is_latest": False})
            self.onto_storage.create_document(
               get_formatted_ontology_for_db(
                  ontology = {
                     "entities": entities,
                     "relationships": relationships
                  },
                  modification_note=note,
                  modification_justification= {
                     "removed_entities": removed_entities, 
                     "removed_relationships": removed_relationships
                  },
                  model="o4-mini",
                  purpose=self.ontology_purpose,
                  version=get_new_version(current_version=current_onto_version, update_type="PATCH"),
                  cq_version=current_cq_version
               )
            )
            ontology_construction_logger.info(f"OntologyConstructionSystem\nOntology is updated, current version: {self.get_current_onto_version()}")
         except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")
         
    async def enhance_ontology_clarity(self) -> None:
         current_onto = self.get_current_onto()
         current_onto_version = self.get_current_onto_version()
         current_cq_version = self.get_current_cq_version()
         
         # Step 1: Call clarity enhancement agent
         try:
            raw_response = await self.agents["OntologyClarityEnhancementAgent"].handle_task(ontology=current_onto)
            if not raw_response:
               raise ValueError("Ontology clarity enhancement returned no output.")
         except Exception as e:
            raise ValueError(f"Error while enhancing ontology: {e}")
         
         # Step 2: Format response into json
         try:
            response = get_clean_json(raw_response)
            
            updated_ontology = response.get("updated_ontology", {})
            entities = updated_ontology.pop("entities", {})
            relationships = updated_ontology.pop("relationships", {})
            
            modified_entities = response.pop("modified_entities", [])
            modified_relationships = response.pop("modified_relationships", [])
            note = response.pop("note", "")
         except Exception as e:
            raise ValueError(f"Error while converting ontology to json: {e}")

         # Step 3: Upload enhanced ontology to db
         try:
            self.onto_storage.update_document({"is_latest": True}, {"is_latest": False})
            self.onto_storage.create_document(
               get_formatted_ontology_for_db(
                  ontology= {
                     "entities": entities,
                     "relationships": relationships
                  },
                  modification_justification={
                     "modified_entities": modified_entities, 
                     "modified_relationships": modified_relationships
                  },
                  modification_note=note,
                  model="o4-mini",
                  purpose=self.ontology_purpose,
                  version=get_new_version(current_version=current_onto_version, update_type="PATCH"),
                  cq_version=current_cq_version
               )
            )
            ontology_construction_logger.info(f"OntologyConstructionSystem\nOntology is updated, current version: {self.get_current_onto_version()}")
         except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")
         
    async def create_onto_manually(self, new_onto: dict):
         current_onto_version = self.get_current_onto_version()
         current_cq_version = self.get_current_cq_version()
         
         try:
            entities = new_onto.pop("entities", {})
            relationships = new_onto.pop("relationships", {})
            note = new_onto.pop("note","")
            
         except Exception as e:
            raise ValueError(f"Error parsing relevant information: {e}")

         try:
            self.onto_storage.update_document({"is_latest": True}, {"is_latest": False})
            self.onto_storage.create_document(
               get_formatted_ontology_for_db(
                  ontology= {
                     "entities": entities,
                     "relationships": relationships
                  },
                  model="NA",
                  modification_note=note,
                  purpose="NA",
                  version=get_new_version(current_version=current_onto_version, update_type="PATCH"),
                  cq_version=current_cq_version
               )
            )
         except Exception as e:
            raise ValueError(f"Error while uploading ontology: {e}")
         
    async def evaluate_ontology(self):
       current_onto = self.get_current_onto()
       current_cq = self.get_current_cq()
       current_onto_version = self.get_current_onto_version()
       current_cq_version = self.get_current_cq_version()
       
       # Step 1: Call evaluation agent
       ontology_construction_logger.info("OntologyConstructionSystem\nEvaluating ontology...")
       try:
         evaluation_result = await self.agents["OntologyEvaluationAgent"].handle_task(
            ontology=current_onto,
            competency_questions=get_formatted_cq_for_display(current_cq),
         )
         if not evaluation_result:
            raise ValueError("Ontology evaluation returned no output.")
       except Exception as e:
         raise ValueError(f"Error while evaluating ontology: {e}")
         
       # Step 2: Format response into json
       try:
         evaluation_result = get_clean_json(evaluation_result)
       except Exception as e:
         raise ValueError(f"Error while converting evaluation result to json: {e}")
         
       # Step 3: Upload feedback to db
       try:
         self.feedback_storage.create_document(
            get_formatted_feedback_for_db(
               feedback=evaluation_result,
               model="o4-mini",
               purpose=self.ontology_purpose,
               is_handled=evaluation_result.get("require_resolution", "") == "TRUE",
               cq_version=current_cq_version,
               onto_version=current_onto_version
            )
         )
       except Exception as e:
         raise ValueError(f"Error while uploading feedback: {e}")
   
    async def generate_competency_questions(
       self,
       personality_num: int,
       task_num: int,
       question_num: int,
       update_type: str = "PATCH"
    ):
      current_version = self.get_current_cq_version()
      
      try:
         new_cq = await self.agents["CQGenerationAgent"].handle_task(
            personality_num=personality_num,
            task_num=task_num,
            question_num=question_num,
         )
         if not new_cq:
            raise ValueError("CQGenerationAgent returned no output.")
      except Exception as e:
         raise ValueError(f"Error while generating competency questions: {e}")
            
      formatted_cq_record = get_formatted_cq_for_db(
         cq=get_clean_json(new_cq),
         model="gpt-4.1-mini",
         purpose=self.ontology_purpose,
         version=get_new_version(current_version=current_version, update_type=update_type)
      )
      
      try:
         self.cq_storage.update_document({"is_latest": True}, {"is_latest": False})
         self.cq_storage.create_document(formatted_cq_record)
      except Exception as e:
         raise ValueError(f"Error while uploading competency questions: {e}")
      
    def get_current_onto(self) -> dict:
      try: 
        current_latest_onto = self.onto_storage.read_documents({"is_latest": True})
        return current_latest_onto[0].get("ontology", "") if current_latest_onto else {}
      except Exception as e:
         ontology_construction_logger.error(f"OntologyConstructionSystem\nError getting ontology: {e}")
         return {}
   
    def get_current_cq(self) -> str:
      try: 
        current_latest_cq = self.cq_storage.read_documents({"is_latest": True})
        return current_latest_cq[0].get("competency_questions", "") if current_latest_cq else {}
      except Exception as e:
         ontology_construction_logger.error(f"OntologyConstructionSystem\nError getting cq: {e}")
         return {}
      
    def get_unhandled_feedback(self, onto_version: str) -> dict:
       try:
         feedback_entry = self.feedback_storage.read_documents(
            {"is_handled": False, "feedback_for_onto_version": onto_version}
         )
         return feedback_entry[0].get("feedback") if feedback_entry else {}
       except Exception as e:
         ontology_construction_logger.error(f"OntologyConstructionSystem\nError getting unhandled feedback: {e}")
         return {}
   
    def get_current_onto_version(self) -> str:
      try: 
        current_latest_onto = self.onto_storage.read_documents({"is_latest": True})
        return current_latest_onto[0].get("version", "1.0.0") if current_latest_onto else "1.0.0"
      except Exception as e:
         ontology_construction_logger.error(f"OntologyConstructionSystem\nError getting ontology version: {e}")
         return "1.0.0"
      
    def get_current_cq_version(self) -> str:
      try:
        current_latest_cq = self.cq_storage.read_documents({"is_latest": True})
        return current_latest_cq[0].get("version", "1.0.0") if current_latest_cq else "1.0.0"
      except Exception as e:
         ontology_construction_logger.error(f"OntologyConstructionSystem\nError getting cq version: {e}")
         return "1.0.0"

