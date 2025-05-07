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
reasoning_agent_logger = logging.getLogger("reasoning-agent")
        
class FrontAgent(BaseAgent):
    """
    An agent responsible for validating queries.
    """
    def handle_task(self, task_data: str):
        formatted_ontology = get_ontology_for_query(self.agent_system.ontology)
        system_prompt = PROMPT["QUERY_VALIDATION"].format(ontology=formatted_ontology)
        
        # front_agent_logger.debug(f"System prompt: {system_prompt}")

        try:
            front_agent_logger.debug(f"Input received: {task_data}")
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

class ReasoningAgent(BaseAgent):
    """
    An agent responsible for delivering the final answer.
    """
    async def handle_task(self, task_data: str):
        max_step = 6
        current_step = 0
        formatted_ontology = get_ontology_for_text2cypher(self.agent_system.ontology)
        system_prompt = PROMPT["REASONING"].format(step=max_step, ontology=formatted_ontology)
        previous_response_id = None
        
        # reasoning_agent_logger.debug(f"System prompt: {system_prompt}")
        
        try:
            # Initial call
            reasoning_agent_logger.debug(f"Received input in reasoning agent: {task_data}")
            response = self.openai_client.responses.create(
                model="o4-mini",
                input=[
                    {"role": "developer", "content": system_prompt},
                    {"role": "user", "content": task_data},
                ],
                text={"format": {"type": "text"}},
                reasoning={"effort": "medium"},
                tools=self.get_tools(),
                store=True,
            )
            previous_response_id = response.id
            
            tool_calls = self.get_tool_calls(response)
            
            reasoning_agent_logger.debug(f"Initial calling: {get_formatted_openai_response(response)}")
        
            # Process tool call
            while tool_calls and current_step < max_step:
                tool_call = tool_calls[0]
                name = tool_call.name
                args = json.loads(tool_call.arguments)

                if name == "get_nearest_entity_name":
                    tool_content = await self.get_nearest_entity_name(**args)
                elif name == "run_cypher_from_text":
                    tool_content = await self.run_cypher_from_text(**args)
                else:
                    reasoning_agent_logger.error(f"Unknown tool: {name}")
                    raise ValueError(f"Unknown tool: {name}")
                
                # Send the tool call result back to the reasoning agent
                response = self.openai_client.responses.create(
                    model="o4-mini",
                    input=[
                      {                               
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": str(tool_content)
                     }
                    ],
                    text={"format": {"type": "text"}},
                    reasoning={"effort": "medium"},
                    tools=self.get_tools(),
                    store=True,
                    previous_response_id=previous_response_id
                )
                reasoning_agent_logger.debug(get_formatted_openai_response(response))
                previous_response_id = response.id

                current_step += 1
                tool_calls = self.get_tool_calls(response)
                
            # If no more tool calls, return final answer
            return response.output_text
        except Exception as e:
            reasoning_agent_logger.error(f"Error: {str(e)}")
            return f"Error: {str(e)}"   
    
    def get_tools(self):
        return [
            {
                "type": "function",
                "name": "get_nearest_entity_name",
                "description": "Retrieve the most likely entity names for the graph database using similarity search on the vector database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query_strings": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "A list of strings representing potential entity names to search for."
                        }
                    },
                    "required": ["query_strings"],
                    "additionalProperties": False
                },
                "strict": True
            },
            {
                "type": "function",
                "name": "run_cypher_from_text",
                "description": "Execute a read-only Cypher query on the graph database based on a natural language instruction.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_query": {
                            "type": "string",
                            "description": "A concise and specific instruction written in natural language to retrieve information from the graph."
                        }
                    },
                    "required": ["user_query"],
                    "additionalProperties": False
                },
                "strict": True
            }
        ]

    
    async def get_nearest_entity_name(self, query_strings: list[str]):
        return await self.call_agent(agent_to_call="VectorSearchAgent", task_data=query_strings)
    
    async def run_cypher_from_text(self, user_query: str):
        return await self.call_agent(agent_to_call="Text2CypherAgent", task_data=user_query)
    
    def get_tool_calls(self, response): 
        return [item for item in response.output if item.type == "function_call"]

class GraphQuerySystem(BaseMultiAgentSystem):
    def __init__(self, ontology: dict):
        super().__init__(
            {
                "FrontAgent": FrontAgent("FrontAgent"),
                "VectorSearchAgent": VectorSearchAgent("VectorSearchAgent"),
                "Text2CypherAgent": Text2CypherAgent("Text2CypherAgent"),
                "ReasoningAgent": ReasoningAgent("ReasoningAgent")
            }
        )
        self.ontology = ontology
    
    async def handle_request(self, request_data: str):
        # Start with the first agent (FrontAgent)
        evaluation_result = self.agents["FrontAgent"].handle_task(request_data)
        # TODO: Change to better condition
        if "Yes, it may be answered." in evaluation_result:
            input_for_reasoning_agent = f"User Query: {request_data}\nPotential Solution: {evaluation_result}"
            return await self.agents["ReasoningAgent"].handle_task(input_for_reasoning_agent)
        else:
            return evaluation_result




        