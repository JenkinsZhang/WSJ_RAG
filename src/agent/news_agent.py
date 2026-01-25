"""
LlamaIndex-based News Agent for WSJ RAG system.

Provides an intelligent agent that can answer questions about news
using the news_query tool backed by OpenSearch vector search.
"""

from __future__ import annotations

import logging
from typing import Optional

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.bedrock_converse import BedrockConverse

from src.agent.tools import create_news_query_function_tool
from src.config import get_settings

logger = logging.getLogger(__name__)

# System prompt for the news agent
NEWS_AGENT_SYSTEM_PROMPT = """You are a helpful news analyst assistant with access to WSJ (Wall Street Journal) news articles.

Your role is to:
1. Help users find relevant news articles based on their queries
2. Summarize and explain news content
3. Answer questions about current events and business news
4. Provide context and analysis when appropriate

When answering questions:
- Always use the news_query tool to search for relevant articles first
- Cite the article titles and provide URLs when referencing specific news
- If the query is about recent events, use mode="recent" with appropriate hours_ago
- For specific topics, use mode="hybrid" for best results
- For conceptual questions, use mode="semantic"

Available news categories: home, world, china, tech, finance, business, politics, economy

Be concise but informative. If no relevant articles are found, let the user know and suggest
alternative search terms or categories.
"""


class NewsAgent:
    """
    LlamaIndex-based agent for news Q&A.

    Uses AWS Bedrock Claude as the LLM and a custom news_query tool
    for retrieving relevant news articles from OpenSearch.

    Example:
        >>> agent = NewsAgent()
        >>> response = await agent.chat("What's the latest on AI regulations?")
        >>> print(response)
    """

    def __init__(
            self,
            model_id: Optional[str] = None,
            verbose: bool = False,
    ) -> None:
        """
        Initialize the news agent.

        Args:
            model_id: Bedrock model ID (defaults to config)
            verbose: Whether to show agent reasoning steps
        """
        settings = get_settings()
        self.model_id = model_id or settings.llm.model_id
        self.verbose = verbose
        self._agent: Optional[FunctionAgent] = None

    def _create_llm(self) -> BedrockConverse:
        """Create the Bedrock LLM instance."""
        settings = get_settings()

        return BedrockConverse(
            model=self.model_id,
            region_name=settings.llm.region_name,
            # AWS credentials from environment/profile
        )

    def _create_agent(self) -> FunctionAgent:
        """Create the LlamaIndex function agent."""
        llm = self._create_llm()
        news_tool = create_news_query_function_tool()

        agent = FunctionAgent(
            tools=[news_tool],
            llm=llm,
            system_prompt=NEWS_AGENT_SYSTEM_PROMPT,
            verbose=self.verbose,
        )

        return agent

    @property
    def agent(self) -> FunctionAgent:
        """Lazy initialization of the agent."""
        if self._agent is None:
            logger.info(f"Initializing NewsAgent with model: {self.model_id}")
            self._agent = self._create_agent()
        return self._agent

    async def chat(self, message: str) -> str:
        """
        Send a message to the agent and get a response.

        Args:
            message: User's question or request

        Returns:
            Agent's response as a string
        """
        logger.debug(f"User message: {message}")

        try:
            response = await self.agent.run(input=message)

            # Extract the response text
            if hasattr(response, 'response'):
                return str(response.response)
            return str(response)

        except Exception as e:
            logger.error(f"Agent chat failed: {e}")
            raise

    def chat_sync(self, message: str) -> str:
        """
        Synchronous version of chat.

        Args:
            message: User's question or request

        Returns:
            Agent's response as a string
        """
        import asyncio

        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # We're in an async context, create a new loop in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.chat(message))
                return future.result()
        else:
            # No running loop, safe to use asyncio.run
            return asyncio.run(self.chat(message))


# Singleton instance
_news_agent: Optional[NewsAgent] = None


def get_news_agent(verbose: bool = False) -> NewsAgent:
    """
    Get singleton news agent instance.

    Args:
        verbose: Whether to show agent reasoning

    Returns:
        NewsAgent instance
    """
    global _news_agent
    if _news_agent is None:
        _news_agent = NewsAgent(verbose=verbose)
    return _news_agent
