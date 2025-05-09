from __future__ import annotations

import json
import logging

from typing import TypedDict

from ..prompts import PROMPT
from ..llm import fetch_responses_openai
from ..util import get_formatted_ontology, get_formatted_openai_response
from ..storage import MongoDBStorage
from ..base import BaseAgent, BaseMultiAgentSystem
from .ontology_construction_util import (
   get_new_version,
   get_formatted_cq_record
)

ontology_construction_logger = logging.getLogger("ontology_construction")

class OntologyStorageConfig(TypedDict):
   connection_uri: str
   database_name: str
   collection_name: str

class CompetencyQuestionsStorageConfig(TypedDict):
   connection_uri: str
   database_name: str
   collection_name: str
   
class CQGenerationAgent(BaseAgent):
    """
    An agent responsible for generating competency questions to evaluate the robustness of the given ontology.
    
    Parameters:
        task_data (str): The purpose of the ontology.
        personality_num (int): Number of personalities to generate.
        task_num (int): Number of tasks to generate.
        question_num (int): Number of questions to generate.
    """
    async def handle_task(self, task_data: str, **kwargs) -> str:
        system_prompt = PROMPT["ONTOLOGY_CQ_GENERATION"].format(
           ontology_purpose=task_data,
           personality_num=kwargs.get("personality_num", 1),
           task_num=kwargs.get("task_num", 1),
           question_num=kwargs.get("question_num", 1),
         )
        user_prompt = "You now understand the guidelines. Please generate the competency questions accordingly."
        
        ontology_construction_logger.debug(f"System Prompt:\n\n{system_prompt}")
        
        try:
            response = await fetch_responses_openai(
                model=kwargs.get("model", "gpt-4.1-mini"),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0,
                max_output_tokens=32768
            )
            ontology_construction_logger.info(f"Competency questions generation response details:\n{get_formatted_openai_response(response)}")
            
            return response.output_text   
        except Exception as e:
            ontology_construction_logger.error(f"CQ generation failed: {str(e)}")
            return ""
   
# class OntologyConstructionAgent(BaseAgent):
#     """
#     An agent responsible for constructing ontology based on source text and feedback.
#     """
#     def handle_task(self, task_data: str):
#         formatted_ontology = get_ontology_for_query(self.agent_system.ontology)
#         system_prompt = PROMPT["QUERY_VALIDATION"].format(ontology=formatted_ontology)
        
#         # front_agent_logger.debug(f"System prompt: {system_prompt}")

#         try:
#             front_agent_logger.debug(f"Input received: {task_data}")
#             response = self.openai_client.responses.create(
#                 model="o4-mini",
#                 input=[
#                     {"role": "developer", "content": system_prompt},
#                     {"role": "user", "content": task_data},
#                 ],
#                 text={
#                     "format": {
#                         "type": "text"
#                     }
#                 },
#                 reasoning={
#                     "effort": "medium"
#                 },
#                 tools=[],
#                 store=True
#             )
            
#             front_agent_logger.debug(get_formatted_openai_response(response))
#             return response.output_text
                    
#         except Exception as e:
#             return f"Error: {str(e)}"


class OntologyConstructionSystem(BaseMultiAgentSystem):
    def __init__(
       self, 
       ontology_purpose: str,
       ontology_config: OntologyStorageConfig, 
       cq_config: CompetencyQuestionsStorageConfig
       ):
        super().__init__(
            {
               "CQGenerationAgent": CQGenerationAgent("CQGenerationAgent")
            }
        )
        try:
         self.onto_storage = MongoDBStorage(ontology_config["connection_uri"])
         self.onto_storage.use_database(ontology_config["database_name"])
         self.onto_storage.use_collection(ontology_config["collection_name"])
         
         self.cq_storage = MongoDBStorage(cq_config["connection_uri"])
         self.cq_storage.use_database(cq_config["database_name"])
         self.cq_storage.use_collection(cq_config["collection_name"])
         
         self.ontology_purpose = ontology_purpose
        except Exception as e:
           ontology_construction_logger.error(e)
           raise ValueError(f"Failed to connect to MongoDB: {e}")
    
    async def handle_request(self, request_data: str):
      pass
   
    async def generate_competency_questions(
       self,
       personality_num: int,
       task_num: int,
       question_num: int,
       model: str,
       update_type: str = "PATCH"
    ):
      try:
         new_cq = await self.agents["CQGenerationAgent"].handle_task(
            task_data=self.ontology_purpose,
            personality_num=personality_num,
            task_num=task_num,
            question_num=question_num,
            model=model
         )
         if not new_cq:
            raise ValueError("CQGenerationAgent returned no output.")
      except Exception as e:
         raise ValueError(f"Error while generating competency questions: {e}")
      
      try:
        current_latest = self.cq_storage.read_documents({"is_latest": True})
        current_version = current_latest[0].get("version", "1.0.0") if current_latest else "1.0.0"
      except Exception as e:
         current_version = "1.0.0"
         
      formatted_cq_record = get_formatted_cq_record(
         cq=json.loads(new_cq),
         model=model,
         purpose=self.ontology_purpose,
         version=get_new_version(current_version=current_version, update_type=update_type)
      )
      self.cq_storage.update_document({"is_latest": True}, {"is_latest": False})
      self.cq_storage.create_document(formatted_cq_record)

