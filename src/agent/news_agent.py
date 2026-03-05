"""
LlamaIndex-based News Agent for WSJ RAG system.

Provides an intelligent agent that can answer questions about news
using the news_query tool backed by OpenSearch vector search.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional, AsyncGenerator

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.bedrock_converse import BedrockConverse
from workflows.handler import WorkflowHandler

from src.agent.progress import ProgressTracker, set_progress_tracker
from src.agent.session import ChatSession
from src.agent.tools import create_news_query_function_tool
from src.agent.tools_trend import create_trend_analysis_tool
from src.agent.tools_compare import create_compare_articles_tool
from src.agent.tools_research import create_deep_research_tool
from src.agent.tools_database import create_database_info_tool
from src.config import get_settings

logger = logging.getLogger(__name__)

# System prompt template for the news agent
NEWS_AGENT_SYSTEM_PROMPT_TEMPLATE = """你是一个专业的新闻分析助手，可以访问华尔街日报(WSJ)的新闻文章。

## 当前时间
**今天是 {current_date}（{current_weekday}），当前时间 {current_time}**

请根据这个时间来判断新闻的时效性：
- 如果新闻发布时间是今天，说明是"今天的新闻"
- 如果是昨天发布的，说明是"昨天的新闻"
- 超过一周的新闻可以标注为"较早的新闻"

## 你的职责
1. 与用户自然对话，回答各类问题
2. 帮助用户查找相关的新闻文章
3. 总结和解释新闻内容
4. 回答关于时事和商业新闻的问题
5. 在适当时候提供背景分析，说明新闻的时效性
6. 分析新闻趋势和话题热度变化
7. 对比不同文章的观点和立场
8. 对复杂话题进行深度研究，综合多篇文章

## 重要规则
- **所有回答必须使用中文**，即使用户用英文提问
- **不要对每条消息都调用工具** —— 日常对话、通用知识问题、对之前回答的追问应该直接回答，不需要搜索新闻
- 引用文章时，提供文章标题和URL
- **说明新闻发布时间与今天的关系**（如"这是今天发布的新闻"或"这篇文章发布于3天前"）
- 如果没有找到相关文章，告知用户并建议其他搜索词或分类
- 如果用户对之前的回答不满意，尝试不同的搜索策略或工具

## 可用工具

### 1. news_query — 新闻查询
基础查询工具，搜索新闻文章。支持语义搜索、时间过滤、分类过滤、独家新闻过滤和自动总结。
工具会自动分析用户意图，你只需要传入用户的原始问题即可。
工具会自动处理：
- 翻译（中文→英文搜索）
- 时间范围（"最近"→ recent mode）
- 独家新闻（"独家"→ exclusive filter）
- 自动总结（"总结"→ 生成摘要）

### 2. trend_analysis — 趋势分析
分析某个话题在一段时间内的新闻报道趋势，包括报道频率、情感倾向和关键事件时间线。

### 3. compare_articles — 文章对比
对比多篇文章的观点、立场和重点差异，适用于有争议的话题或多角度分析。

### 4. deep_research — 深度研究
对复杂话题进行深度研究，综合多轮搜索和多篇文章，生成详细的研究报告。

### 5. database_info — 数据库信息
查询数据库元数据：文章总数、最新/最早文章日期、分类分布、最新入库的文章列表。

## 工具选择策略

### 不需要工具，直接回答：
- **日常对话**（"你好"、"谢谢"、"你是谁"、"你能做什么"）→ 直接用中文回答，不调用任何工具
- **通用知识问题**（"什么是GDP"、"解释一下量化宽松"、"什么是市盈率"）→ 用你自己的知识直接回答，不需要搜索新闻
- **对之前回答的追问**（"再详细说说"、"能举个例子吗"、"为什么"）→ 根据对话历史直接回答
- **闲聊或意见类问题**（"你觉得呢"、"有什么建议"）→ 直接回答

### 需要使用工具：
- **新闻查询**（"最近有什么科技新闻"、"特斯拉最新消息"）→ 使用 `news_query`
- **趋势分析**（"AI监管最近的趋势如何"、"最近什么热门"）→ 使用 `trend_analysis`
- **观点对比**（"对比 Tesla 和 BYD"、"各方对关税政策的看法"）→ 使用 `compare_articles`
- **深度研究**（"详细分析中美贸易战的影响"、"深入研究AI就业"）→ 使用 `deep_research`
- **数据库信息**（"最新文章是几号的"、"有多少篇文章"、"各分类有多少"）→ 使用 `database_info`

### 判断原则
**只有当用户需要查找、检索或分析具体的近期新闻时才使用工具。** 如果你可以凭借自身知识或对话上下文回答问题，就直接回答，不要调用工具。

## 可用的新闻分类
home, world, china, tech, finance, business, politics, economy

## 回答格式
- 简洁但信息丰富
- 引用来源时格式: 「文章标题」(URL) - 发布于 [时间]
- 如有多篇相关文章，综合分析后给出答案
- 明确告知用户新闻的新鲜程度
"""

CONVERSATION_HISTORY_TEMPLATE = """
## 对话历史
以下是本次会话的历史对话，请参考上下文回答用户的最新问题：

{history}
"""

FEEDBACK_CONTEXT_TEMPLATE = """
## 用户反馈
用户对近期回答的反馈：
{feedback}
请根据反馈调整你的回答策略。
"""

# Weekday names in Chinese
WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _generate_system_prompt() -> str:
    """Generate system prompt with current date/time."""
    now = datetime.now()
    return NEWS_AGENT_SYSTEM_PROMPT_TEMPLATE.format(
        current_date=now.strftime("%Y年%m月%d日"),
        current_weekday=WEEKDAY_NAMES[now.weekday()],
        current_time=now.strftime("%H:%M"),
    )


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
        self._tools = None

    def _create_llm(self) -> BedrockConverse:
        """Create the Bedrock LLM instance with increased token limit."""
        settings = get_settings()

        return BedrockConverse(
            model=self.model_id,
            region_name=settings.llm.region_name,
            max_tokens=4096,  # Increased from default for detailed Chinese responses
            temperature=0.7,
        )

    def _get_tools(self) -> list:
        """Lazily create and cache all agent tools."""
        if self._tools is None:
            logger.info("Creating agent tools...")
            self._tools = [
                create_news_query_function_tool(),
                create_trend_analysis_tool(),
                create_compare_articles_tool(),
                create_deep_research_tool(),
                create_database_info_tool(),
            ]
            logger.info(f"Created {len(self._tools)} tools")
        return self._tools

    def _create_agent(self, session: Optional[ChatSession] = None) -> FunctionAgent:
        """Create the LlamaIndex function agent with current datetime context.

        Args:
            session: Optional chat session for multi-turn conversation context.
        """
        llm = self._create_llm()
        tools = self._get_tools()

        # Generate system prompt with current date/time
        system_prompt = _generate_system_prompt()

        # Append conversation history if session has messages
        if session and session.messages:
            history_entries = session.get_history_for_prompt(max_turns=10)
            if history_entries:
                history_lines = []
                for entry in history_entries:
                    role_label = "用户" if entry["role"] == "user" else "助手"
                    content = entry["content"]
                    if len(content) > 200:
                        content = content[:200] + "..."
                    history_lines.append(f"{role_label}: {content}")
                history_text = "\n".join(history_lines)
                system_prompt += CONVERSATION_HISTORY_TEMPLATE.format(history=history_text)

        # Append feedback context if session has recent feedback
        if session:
            feedback_summary = session.get_recent_feedback_summary()
            if feedback_summary:
                system_prompt += FEEDBACK_CONTEXT_TEMPLATE.format(feedback=feedback_summary)

        agent = FunctionAgent(
            tools=tools,
            llm=llm,
            system_prompt=system_prompt,
            verbose=self.verbose,
        )

        return agent

    async def chat(self, message: str, session: Optional[ChatSession] = None) -> str:
        """
        Send a message to the agent and get a response.

        Args:
            message: User's question or request
            session: Optional chat session for multi-turn conversation

        Returns:
            Agent's response as a string
        """
        logger.debug(f"User message: {message}")

        try:
            agent = self._create_agent(session)
            response = await agent.run(user_msg=message)

            # Extract the response text
            if hasattr(response, "response"):
                response_text = str(response.response)
            else:
                response_text = str(response)

            # Record messages in session
            if session:
                session.add_message("user", message)
                session.add_message("assistant", response_text)

            return response_text

        except Exception as e:
            logger.error(f"Agent chat failed: {e}")
            raise

    def chat_sync(self, message: str, session: Optional[ChatSession] = None) -> str:
        """
        Synchronous version of chat.

        Args:
            message: User's question or request
            session: Optional chat session for multi-turn conversation

        Returns:
            Agent's response as a string
        """
        return asyncio.run(self.chat(message, session))

    async def chat_stream(
        self, message: str, session: Optional[ChatSession] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Stream chat with real-time tool progress events.

        Architecture: two concurrent async tasks feed a unified output queue.

            Task 1 (_agent_stream_producer):
                Reads Agent workflow events (ToolCall, AgentStream, etc.)
                and writes to unified_queue.

            Task 2 (_progress_forwarder):
                Continuously reads from progress_queue (fed by sync emit_xxx)
                and writes to unified_queue with 100ms polling.

            chat_stream:
                Reads from unified_queue and yields to the SSE response.

        This ensures tool progress events are delivered in real-time,
        not batched until the next Agent workflow event.
        """
        logger.debug(f"User message (stream): {message}")

        # Progress queue: tools write here via sync emit_xxx() → put_nowait()
        progress_queue: asyncio.Queue = asyncio.Queue()
        tracker = ProgressTracker()
        tracker.set_queue(progress_queue)
        set_progress_tracker(tracker)

        # Unified output queue: single consumer (this method), two producers
        unified_queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        async def _agent_stream_producer(handler: WorkflowHandler):
            """Read Agent workflow events → unified queue."""
            try:
                current_tool_call = None
                async for event in handler.stream_events():
                    event_type = type(event).__name__

                    if event_type == "AgentInput":
                        await unified_queue.put({
                            "type": "step", "step": "processing",
                            "content": "开始处理请求...",
                        })
                    elif event_type == "AgentSetup":
                        pass
                    elif event_type == "AgentStream":
                        if hasattr(event, "delta") and event.delta:
                            await unified_queue.put({"type": "delta", "content": event.delta})
                    elif event_type == "ToolCall":
                        tool_name = getattr(event, "tool_name", "unknown")
                        tool_args = getattr(event, "tool_kwargs", {})
                        current_tool_call = tool_name
                        await unified_queue.put({
                            "type": "step", "step": "tool_call",
                            "tool": tool_name,
                            "content": f"调用工具: {tool_name}",
                            "args": tool_args,
                        })
                    elif event_type == "ToolCallResult":
                        tool_name = getattr(event, "tool_name", current_tool_call or "unknown")
                        raw_output = str(getattr(event, "tool_output", ""))
                        await unified_queue.put({
                            "type": "step", "step": "tool_result",
                            "tool": tool_name,
                            "content": f"工具 {tool_name} 返回结果",
                            "result_preview": raw_output[:500] + ("..." if len(raw_output) > 500 else ""),
                        })
                    elif event_type == "AgentOutput":
                        if hasattr(event, "response"):
                            await unified_queue.put({"type": "_agent_output", "response": str(event.response)})
                    else:
                        logger.debug(f"Unknown event type: {event_type}")
            except Exception as e:
                await unified_queue.put({"type": "error", "content": str(e)})
            finally:
                await unified_queue.put(_SENTINEL)

        async def _progress_forwarder():
            """Forward tool progress events → unified queue in real-time."""
            while True:
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.1)
                    await unified_queue.put(event)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    # Drain remaining before exit
                    while not progress_queue.empty():
                        try:
                            await unified_queue.put(progress_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    return

        try:
            yield {"type": "step", "step": "thinking", "content": "正在分析您的问题..."}

            agent = self._create_agent(session)
            handler: WorkflowHandler = agent.run(user_msg=message)

            # Launch two concurrent producers
            agent_task = asyncio.create_task(_agent_stream_producer(handler))
            progress_task = asyncio.create_task(_progress_forwarder())

            final_response = ""

            # Single consumer loop
            while True:
                event = await unified_queue.get()

                if event is _SENTINEL:
                    break

                event_type = event.get("type")
                if event_type == "delta":
                    final_response += event["content"]
                    yield event
                elif event_type == "_agent_output":
                    final_response = event["response"]
                    # Internal event, don't yield to client
                elif event_type == "error":
                    yield event
                    break
                else:
                    yield event

            # Shut down progress forwarder
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass

            # Ensure agent task completes and get final result
            await agent_task
            result = await handler
            if hasattr(result, "response") and not final_response:
                final_response = str(result.response)

            # Record in session
            if session:
                session.add_message("user", message)
                msg = session.add_message("assistant", final_response)
                yield {"type": "done", "content": final_response, "message_id": msg.message_id}
            else:
                yield {"type": "done", "content": final_response}

        except Exception as e:
            logger.error(f"Agent stream failed: {e}")
            yield {"type": "error", "content": str(e)}
        finally:
            set_progress_tracker(None)


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
