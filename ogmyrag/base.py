from __future__ import annotations
import os
import inspect
import openai
from typing import Any, TypedDict


class MongoStorageConfig(TypedDict):
    database_name: str
    collection_name: str | None


class PineconeStorageConfig(TypedDict):
    index_name: str
    pinecone_api_key: str
    pinecone_environment: str
    pinecone_cloud: str
    pinecone_metric: str
    pinecone_dimensions: str
    openai_api_key: str


class Neo4jStorageConfig(TypedDict):
    uri: str
    user: str
    password: str


class BaseLLMClient:
    async def fetch_response(
        self, model: str, system_prompt: str | None, user_prompt: str, **kwargs
    ) -> Any:
        raise NotImplementedError


class BaseAgent:
    def __init__(self, agent_name: str, agent_config: dict[str, dict] | None= None):
        # agent_config should not be optional. However, it is optional at current stage to cater code that is not yet refactored
        self.agent_name = agent_name
        self.agent_config = agent_config
        self.agent_system: BaseMultiAgentSystem = None

        try:
            self.openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        except Exception as e:
            raise ValueError(f"Error initializing OpenAI client: {str(e)}")

    def handle_task(self, **kwargs):
        raise NotImplementedError("Agent musk implement handle_task")

    async def call_agent(self, agent_to_call: str, task_data: Any):
        agent = self.agent_system.get_agent(agent_to_call)
        handler = agent.handle_task

        if inspect.iscoroutinefunction(handler):
            return await handler(task_data)
        else:
            return handler(task_data)


class BaseMultiAgentSystem:
    def __init__(
        self,
        agents: dict[str, BaseAgent],
        llm_client: BaseLLMClient,
    ):
        self.agents = agents
        self.llm_client = llm_client

        for agent in self.agents.values():
            agent.agent_system = self

    def get_agent(self, agent_name: str) -> BaseAgent:
        return self.agents.get(agent_name)

    def handle_request(self, **kwargs):
        raise NotImplementedError("Agent system musk implement handle_request")
