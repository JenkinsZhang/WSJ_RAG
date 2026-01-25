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
NEWS_AGENT_SYSTEM_PROMPT = """你是一个专业的新闻分析助手，可以访问华尔街日报(WSJ)的新闻文章。

## 你的职责
1. 帮助用户查找相关的新闻文章
2. 总结和解释新闻内容
3. 回答关于时事和商业新闻的问题
4. 在适当时候提供背景分析

## 重要规则
- **所有回答必须使用中文**，即使用户用英文提问
- 引用文章时，提供文章标题和URL
- 如果没有找到相关文章，告知用户并建议其他搜索词或分类

## 使用news_query工具
- 查询最近的新闻: mode="recent", 配合 hours_ago 参数
- 查询特定主题: mode="hybrid" (推荐，结合语义和关键词)
- 概念性问题: mode="semantic"

## 可用的新闻分类
home, world, china, tech, finance, business, politics, economy

## 回答格式
- 简洁但信息丰富
- 引用来源时格式: 「文章标题」(URL)
- 如有多篇相关文章，综合分析后给出答案
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
        """Create the Bedrock LLM instance with increased token limit."""
        settings = get_settings()

        return BedrockConverse(
            model=self.model_id,
            region_name=settings.llm.region_name,
            max_tokens=4096,  # Increased from default for detailed Chinese responses
            temperature=0.7,
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
            response = await self.agent.run(user_msg=message)

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
