import logging
import os
import json

from ..prompts import PROMPT

from ..util import (
    get_formatted_openai_response, 
    get_ontology_for_query, 
    get_ontology_with_only_entities,
    get_ontology_for_text2cypher
    )

from ..base import BaseAgent, BaseMultiAgentSystem

from ..storage import PineconeStorage, Neo4jStorage

front_agent_logger = logging.getLogger("front-agent")
vector_search_agent_logger = logging.getLogger("vector-search-agent")
text2cypher_agent_logger = logging.getLogger("text2cypher-agent")
        
class FrontAgent(BaseAgent):
    """
    An agent responsible for validating queries.
    """
    def handle_task(self, task_data: str):
        formatted_ontology = get_ontology_for_query(self.agent_system.ontology)
        system_prompt = PROMPT["QUERY_VALIDATION"].format(ontology=formatted_ontology)
        
        # front_agent_logger.debug(f"System prompt: {system_prompt}")

        try:
            response = self.openai_client.responses.create(
                model="o4-mini",
                input=[
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": task_data},
                ],
                text={
                    "format": {
                        "type": "text"
                    }
                },
                reasoning={
                    "effort": "medium"
                },
                tools=[],
                store=True
            )
            
            front_agent_logger.debug(get_formatted_openai_response(response))
            return response.output_text
                    
        except Exception as e:
            return f"Error: {str(e)}"
        
class VectorSearchAgent(BaseAgent):
    """
    An agent responsible for quering vector database.
    """
    def __init__(self, agent_name: str):
        super().__init__(agent_name)
        try:
            self.pinecone = PineconeStorage(
                index_name="ogmyrag",
                pinecone_api_key=os.getenv("PINECONE_API_KEY", ""),
                pinecone_environment=os.getenv("PINECONE_ENVIRONMENT", ""),
                pinecone_cloud=os.getenv("PINECONE_CLOUD", ""),
                pinecone_metric=os.getenv("PINECONE_METRIC", ""),
                pinecone_dimensions=os.getenv("PINECONE_DIMENSIONS",""),
                openai_api_key=os.getenv("OPENAI_API_KEY", "")
            )
        except Exception as e:
            vector_search_agent_logger.error(f"Could not connect to Pinecone: {str(e)}")
    
    async def handle_task(self, task_data: str):
        formatted_ontology = get_ontology_with_only_entities(self.agent_system.ontology)
        system_prompt = PROMPT["ENTITY_CLASSIFICATION_FOR_VECTOR_SEARCH"].format(ontology=formatted_ontology)
        
        # vector_search_agent_logger.debug(f"System prompt: {system_prompt}")
        
        try:
            response = self.openai_client.responses.create(
                model="gpt-4.1-mini",
                input=[
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": task_data},
                ],
                text={
                    "format": {
                        "type": "text"
                    }
                },
                temperature=0.0
            )
            
            vector_search_agent_logger.debug(get_formatted_openai_response(response))
            
            vector_search_input=json.loads(response.output_text)
    
            return await self.pinecone.get_similar_results_with_namespace(batch_queries=vector_search_input, top_k=3)     
        except Exception as e:
            vector_search_agent_logger.error(f"Error: {str(e)}")
            return f"Error: {str(e)}"
        
class Text2CypherAgent(BaseAgent):
    """
    An agent responsible for quering graph database.
    """
    def __init__(self, agent_name: str):
        super().__init__(agent_name)
        try:
            self.neo4j = Neo4jStorage(
                os.getenv("NEO4J_URI",""), 
                os.getenv("NEO4J_USERNAME",""), 
                os.getenv("NEO4J_PASSWORD","")
                )
        except Exception as e:
            text2cypher_agent_logger.error(f"Could not connect to Neo4j: {str(e)}")
    
    def handle_task(self, task_data: str):
        formatted_ontology = get_ontology_for_text2cypher(self.agent_system.ontology)
        system_prompt = PROMPT["TEXT_TO_CYPHER"].format(ontology=formatted_ontology)
        
        # text2cypher_agent_logger.debug(f"System prompt: {system_prompt}")
        
        try:
            response = self.openai_client.responses.create(
                model="o4-mini",
                input=[
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": task_data},
                ],
                text={
                    "format": {
                        "type": "text"
                    }
                },
                reasoning={
                    "effort": "medium"
                },
                tools=[],
                store=True
            )
            
            text2cypher_agent_logger.debug(get_formatted_openai_response(response))
            
            cypher_query_with_params=json.loads(response.output_text)
    
            return self.neo4j.run_query_for_text2cypher_agent(query_data=cypher_query_with_params)     
        except Exception as e:
            text2cypher_agent_logger.error(f"Error: {str(e)}")
            return f"Error: {str(e)}"        

class GraphQuerySystem(BaseMultiAgentSystem):
    def __init__(self, ontology: dict):
        super().__init__(
            {
                "FrontAgent": FrontAgent("FrontAgent"),
                "VectorSearchAgent": VectorSearchAgent("VectorSearchAgent"),
                "Text2CypherAgent": Text2CypherAgent("Text2CypherAgent")
            }
        )
        self.ontology = ontology
    
    def handle_request(self, request_data: str):
        # Start with the first agent (FrontAgent)
        # return self.agents["FrontAgent"].handle_task(request_data)
        # return await self.agents["VectorSearchAgent"].handle_task(request_data)
        return self.agents["Text2CypherAgent"].handle_task(request_data)



        