# WSJ RAG 项目状态

> 最后更新：2026-03-05

## 项目概述

基于 RAG 的华尔街日报新闻热点总结系统。

## 技术栈

| 组件 | 技术选型 | 状态 |
|------|---------|------|
| 爬虫 | Playwright | ✅ 完成 |
| 向量化 | qwen3-embedding-8b (LM Studio, 4096维) | ✅ 完成 |
| 存储 | OpenSearch (localhost:9200) | ✅ 完成 |
| 索引器 | IndexPipeline | ✅ 完成 |
| RAG | LlamaIndex | ✅ 完成 |
| Agent | LlamaIndex FunctionAgent | ✅ 完成 |
| LLM | AWS Bedrock Claude | ✅ 完成 |
| API | FastAPI | ✅ 完成 |
| Chat UI | HTML + SSE 流式输出 | ✅ 完成 |
| 定时任务 | Windows Task Scheduler | ✅ 完成 |

## 项目结构

```
WSJRAG/
├── run_pipeline.py              # 完整流程入口 (爬虫+索引)
├── main.py                      # FastAPI 应用入口
├── requirements.txt             # Python 依赖
├── src/
│   ├── config/
│   │   └── settings.py          # 集中配置管理，支持环境变量
│   ├── models/
│   │   └── document.py          # NewsArticle, ProcessedDocument, SearchResult
│   ├── clients/                 # 外部服务客户端
│   │   ├── opensearch.py        # OpenSearch 客户端封装
│   │   ├── embedding.py         # Embedding API 客户端 + 文档处理
│   │   └── llm.py               # Bedrock Claude 客户端
│   ├── storage/                 # 数据访问层
│   │   ├── schema.py            # OpenSearch index schema (HNSW, cosine)
│   │   └── repository.py        # 数据访问层 (CRUD + 搜索)
│   ├── crawler/
│   │   ├── browser.py           # Playwright 持久化浏览器管理
│   │   ├── wsj_crawler.py       # WSJ 爬虫 (8个分类 + 单URL)
│   │   └── page_inspector.py    # 页面检查工具
│   ├── indexer/                 # 文章索引管道
│   │   ├── loader.py            # Article JSON → NewsArticle
│   │   ├── date_parser.py       # WSJ 时间格式解析
│   │   ├── state.py             # indexed_files.json 管理
│   │   └── pipeline.py          # 索引主流程
│   ├── agent/                   # LlamaIndex Agent 模块
│   │   ├── tools.py             # NewsQueryTool + QueryAnalyzer + 自我评估
│   │   ├── tools_trend.py       # 趋势分析工具
│   │   ├── tools_compare.py     # 对比分析工具
│   │   ├── tools_research.py    # 深度研究工具
│   │   ├── news_agent.py        # FunctionAgent 封装 (多轮对话+流式输出)
│   │   ├── session.py           # 内存会话管理 (多轮对话)
│   │   ├── progress.py          # 工具进度跟踪模块
│   │   └── cli.py               # 命令行交互界面 (支持多轮对话)
│   └── utils/
│       ├── text.py              # 文本分块器
│       └── url.py               # URL 标准化
├── scripts/
│   ├── schedule_pipeline.ps1    # Windows 定时任务脚本
│   ├── run_pipeline.bat         # 定时任务批处理 (自动生成)
│   └── clean_article_urls.py    # 清理已有文章URL
├── examples/
│   ├── demo_pipeline.py         # 完整流程演示
│   └── run_indexer.py           # 索引脚本 (支持单文件)
├── static/
│   └── chat.html                # Chat UI 前端页面
├── articles/                    # 爬取的文章 (按分类/日期组织)
├── data/
│   ├── crawled_urls.json        # 爬虫URL去重
│   └── indexed_files.json       # 索引状态追踪
└── logs/                        # 日志文件
```

---

## 核心模块详解

### 1. 爬虫模块 (`src/crawler/`)

**功能:**
- Playwright 持久化浏览器 (保存登录状态到 `E:\chrome-debug-profile`)
- 8个分类爬取: home, world, china, tech, finance, business, politics, economy
- 单 URL 爬取 (自动推断分类)
- URL去重 (`crawled_urls.json`)
- 文章内容提取: 标题、副标题、作者、发布时间、正文
- EXCLUSIVE 文章优先级排序
- 自动滚动加载更多内容

**爬取数量限制:**
- 首页 (home): 最多 **50** 篇文章
- 其他分类: 最多 **20** 篇文章

**用法:**
```bash
python -m src.crawler.wsj_crawler              # 显示帮助
python -m src.crawler.wsj_crawler tech         # 爬取分类
python -m src.crawler.wsj_crawler all          # 爬取所有
python -m src.crawler.wsj_crawler --url <url>  # 爬取单个 URL
python -m src.crawler.wsj_crawler --url <url> --category-for-url tech
```

**爬取数据格式:**
```json
{
  "title": "...",
  "url": "...",
  "content": "...",
  "author": "...",
  "published_at": "Updated Jan. 23, 2026 4:39 pm ET",
  "subtitle": "...",
  "category": "tech",
  "source": "WSJ",
  "is_exclusive": false,
  "scraped_at": "2026-01-25T12:32:27.521414"
}
```

---

### 2. 索引器模块 (`src/indexer/`)

将 `articles/` 目录下爬取的 JSON 文件索引到 OpenSearch。

**组件:**
- `date_parser.py`: 解析WSJ多种时间格式 ("Updated Jan. 23, 2026 4:39 pm ET")
- `state.py`: 使用 `indexed_files.json` 追踪已索引文件
- `loader.py`: 加载JSON文件，转换为NewsArticle
- `pipeline.py`: 完整索引流程 (load → embed → summarize → index)

**用法:**
```bash
python -m examples.run_indexer                    # 索引所有待处理
python -m examples.run_indexer --file <path>      # 索引单个文件
python -m examples.run_indexer --file <path> --force  # 强制重新索引
python -m examples.run_indexer --category tech    # 索引特定分类
python -m examples.run_indexer --retry-failed     # 重试失败
python -m examples.run_indexer --stats            # 查看统计
python -m examples.run_indexer --dry-run          # 预览待处理
python -m examples.run_indexer --clear-failed     # 清除失败记录
python -m examples.run_indexer --skip-check       # 跳过服务检查
```

**indexed_files.json 格式:**
```json
{
  "version": 1,
  "indexed": {
    "articles/tech/2026-01-25/intel-xxx.json": {
      "article_id": "9271b096...",
      "chunks": 3,
      "indexed_at": "2026-01-25T15:30:00Z"
    }
  },
  "failed": {
    "articles/tech/2026-01-25/bad-file.json": {
      "error": "Empty content",
      "failed_at": "2026-01-25T15:31:00Z"
    }
  }
}
```

---

### 3. OpenSearch Schema (`src/storage/schema.py`)

- Index: `wsj_news`
- 向量维度: 4096
- 算法: HNSW (Lucene引擎, cosine相似度)
- 字段:
  - 标识: article_id, chunk_id, chunk_index
  - 元数据: title, subtitle, url, source, category, author, is_exclusive
  - 时间: published_at, crawled_at
  - 内容: content, article_summary, chunk_summary
  - 向量: content_vector (4096维)

**Schema 自动同步:**
- 启动时自动检查索引是否存在
- 索引不存在 → 创建完整索引
- 索引存在 → 检测并添加缺失字段 (不丢失数据)

**Document ID 生成:**
- `article_id` = MD5(normalize_url(url))
- `chunk_id` = `{article_id}_{chunk_index}`
- URL 标准化: 移除查询参数(?mod=nav)、片段(#section)、末尾斜杠

---

### 4. Agent 模块 (`src/agent/`)

基于 LlamaIndex FunctionAgent 的智能新闻问答 Agent，支持多轮对话、多工具协作、自我评估和用户反馈。

**组件:**
- `session.py`: 内存会话管理 (ChatSession + ChatSessionManager)
- `tools.py`: NewsQueryTool + QueryAnalyzer + 自我评估 (SearchEvaluation)
- `tools_trend.py`: TrendAnalysisTool (趋势分析)
- `tools_compare.py`: CompareArticlesTool (对比分析)
- `tools_research.py`: DeepResearchTool (深度研究)
- `news_agent.py`: NewsAgent - FunctionAgent 封装 (多轮对话 + 流式输出)
- `progress.py`: 工具进度跟踪模块
- `cli.py`: 命令行交互界面

#### 4.1 多轮对话 (`session.py`)

基于内存的会话管理，支持上下文记忆和用户反馈。

**架构:**
```
ChatSessionManager (单例, 线程安全)
├── sessions: dict[session_id, ChatSession]
├── create_session() → ChatSession
├── get_or_create(session_id) → ChatSession
├── cleanup_expired() → 清理过期 session
└── TTL: 30 分钟

ChatSession
├── messages: list[ChatMessage]     # 对话历史 (最多50条)
├── feedback: list[FeedbackEntry]   # 用户反馈
├── add_message(role, content) → ChatMessage (含 message_id)
├── get_history_for_prompt(max_turns=10) → [{"role": ..., "content": ...}]
└── get_recent_feedback_summary() → str | None
```

**工作流程:**
```
用户请求 (带 session_id)
    ↓
SessionManager.get_or_create(session_id) → ChatSession
    ↓
NewsAgent._create_agent(session)
    ├── 基础 system prompt (含当前日期/时间)
    ├── + 对话历史 (最近10轮, 每条截断200字)
    └── + 用户反馈上下文 (如果有最近30分钟的反馈)
    ↓
FunctionAgent 执行 → 回复
    ↓
session.add_message("user", ...) + session.add_message("assistant", ...)
```

**特点:**
- 每次 chat 重建 Agent，注入最新历史（无状态 Agent + 有状态 Session）
- 会话 30 分钟无活动自动过期，后台每 5 分钟清理
- 前端通过 localStorage 保存 session_id，页面刷新后自动恢复会话

#### 4.2 Agent 工具集

Agent 配备 4 个工具，根据用户意图自动选择：

| 工具 | 触发场景 | 功能 |
|------|---------|------|
| `news_query` | 具体新闻搜索 | 意图分析 → 向量/混合/时间搜索 → 自我评估 → 可选总结 |
| `trend_analysis` | "热点"/"趋势" | 批量获取近期新闻 → 分类统计 → LLM 识别热门话题 |
| `compare_articles` | "对比"/"vs" | 多话题分别搜索 → LLM 结构化对比分析 |
| `deep_research` | "深入分析"/"研究" | LLM 生成多角度搜索 → 合并去重 → 综合研究报告 |

**工具选择策略 (System Prompt 引导):**
```
用户问具体新闻/事件 → news_query
用户问"最近什么热门/趋势/热点" → trend_analysis
用户提到对比、区别、vs → compare_articles
用户要求深入分析、全面了解 → deep_research
复杂问题 → 可以组合多个工具
```

#### 4.3 news_query 工具 (`tools.py`)

核心搜索工具，包含两层 LLM 调用：意图分析 + 结果评估。

**QueryAnalyzer 工作流程:**
```
用户输入 (中文/英文)
    ↓
LLM 分析意图 → QueryIntent {
    search_query: "英文查询",
    mode: "hybrid/semantic/recent",
    exclusive_only: true/false,
    needs_summary: true/false,
    category: "tech/finance/...",
    hours_ago: 24/72/...
}
    ↓
英文查询 → Embedding → OpenSearch (带过滤条件)
    ↓
自我评估 (LLM 打分 1-5)
    ├── score >= 3 → 返回结果
    └── score < 3  → 切换搜索模式 retry → 取更优结果
    ↓
[如果 needs_summary] LLM 生成中文总结
```

**自我评估机制 (Self-Reflection):**
- 搜索完成后，用 LLM 评估结果标题与原始查询的相关性 (1-5分)
- 分数 < 3 时自动切换搜索模式重试 (hybrid ↔ semantic)
- 比较两次结果质量，保留更好的
- 评估结果显示在进度步骤中，输出中包含 `(quality: X/5)`

**搜索去重:**
- `_deduplicate(results, limit)`: 按 article_id 去重，保留最高分
- `_to_query_results(results)`: SearchResult → NewsQueryResult 批量转换
- 三种搜索模式共享这两个方法，消除重复代码

**自动识别的意图关键词:**
| 关键词 | 效果 |
|--------|------|
| 独家/exclusive | `exclusive_only=True` |
| 总结/summarize | `needs_summary=True` → 生成中文摘要 |
| 今天/today | `hours_ago=24` |
| 最近/recent | `mode="recent"` |
| 科技/tech | `category="tech"` |

#### 4.4 trend_analysis 工具 (`tools_trend.py`)

分析新闻趋势和热门话题。

```
获取最近 N 小时新闻 (最多200篇)
    ↓
按 article_id 去重 + 按 category 统计
    ↓
提取标题列表 → LLM 识别 Top N 热门话题
    ↓
输出: 分类分布 + 热门话题列表 + 总体趋势
```

**参数:**
| 参数 | 说明 |
|------|------|
| `category` | 可选分类过滤 (home/world/china/tech/finance/business/politics/economy) |
| `hours` | 时间范围 (1-720小时, 默认72=3天) |
| `top_n` | 热门话题数量 (1-10, 默认5) |

#### 4.5 compare_articles 工具 (`tools_compare.py`)

多话题横向对比分析。

```
解析逗号分隔的话题 (2-4个)
    ↓
对每个话题: embed → hybrid_search → 去重
    ↓
收集各话题文章标题和摘要
    ↓
LLM 生成结构化对比:
├── 各话题概述
├── 共同点
├── 关键区别
└── 趋势分析
```

**参数:**
| 参数 | 说明 |
|------|------|
| `topics` | 逗号分隔的话题, 如 "Tesla,BYD" 或 "美国经济,中国经济" |
| `max_per_topic` | 每个话题最大文章数 (1-5, 默认3) |

#### 4.6 deep_research 工具 (`tools_research.py`)

对单一话题进行多角度深度研究。

```
用户话题
    ↓
LLM 生成 4 个搜索角度 (如: 经济影响/政策反应/行业观点/技术发展)
    ↓
对每个角度: embed → hybrid_search → 去重
    ↓
跨角度合并去重 (按 article_id)
    ↓
LLM 生成综合研究报告:
├── 概述 (2-3句)
├── 关键发现 (要点列表)
├── 多角度分析
├── 影响与展望
└── 参考文章列表 (含URL)
```

**参数:**
| 参数 | 说明 |
|------|------|
| `topic` | 研究话题 (任意语言) |
| `max_results` | 总文章上限 (3-20, 默认10) |

#### 4.7 反馈机制

**用户反馈:**
- 前端每条 assistant 消息底部显示 👍/👎 按钮
- 点击后通过 `/chat/feedback` API 发送到 session
- 反馈注入下一轮 Agent 的 system prompt，影响后续回答策略

**Agent 自我评估:**
- 搜索完成后自动评分 (1-5)
- 低分自动 retry 换搜索模式
- 进度 UI 中实时显示评估状态

**用法:**
```bash
python -m src.agent.cli                          # 交互模式 (支持多轮对话)
python -m src.agent.cli --verbose                # 显示推理过程
python -m src.agent.cli --query "帮我总结科技新闻"  # 单次查询
```

**CLI 命令:**
| 命令 | 说明 |
|------|------|
| `exit`/`quit`/`q` | 退出 |
| `clear`/`cls` | 清屏并重置对话 |
| `history` | 查看对话历史 |
| `help`/`?` | 显示帮助 |

---

### 5. 完整流程脚本 (`run_pipeline.py`)

端到端流程: 爬虫 → 数据处理 → OpenSearch

**用法:**
```bash
python run_pipeline.py                           # 完整流程
python run_pipeline.py --category tech finance   # 指定分类
python run_pipeline.py --max-articles 5          # 限制数量
python run_pipeline.py --crawl-only              # 只爬取
python run_pipeline.py --index-only              # 只索引
python run_pipeline.py --retry-failed            # 重试失败
python run_pipeline.py --skip-service-check      # 跳过检查
python run_pipeline.py -v                        # 详细日志
```

**日志:**
- 控制台: 带颜色的实时日志
- 文件: `logs/pipeline_YYYYMMDD_HHMMSS.log`

---

### 6. API 端点 (`main.py`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/index/setup` | POST | 创建/重建索引 |
| `/articles` | POST | 索引单篇文章 |
| `/search` | POST | 语义/混合搜索 |
| `/news/recent` | GET | 获取最近新闻 |
| `/stats` | GET | 索引统计 |
| `/session` | POST | 创建新会话 |
| `/session/{id}` | DELETE | 删除会话 |
| `/chat` | POST | Agent 问答 (非流式, 支持 session_id) |
| `/chat/stream` | POST | Agent 问答 (SSE 流式, 支持 session_id) |
| `/chat/feedback` | POST | 提交用户反馈 (session_id + message_id + rating) |
| `/chat-ui` | GET | 聊天界面 HTML 页面 |

**Chat 请求格式:**
```json
{
  "message": "最近有什么热点?",
  "session_id": "abc123..."    // 可选，不传则自动创建新 session
}
```

**Chat 响应格式:**
```json
{
  "response": "...",
  "session_id": "abc123...",   // 始终返回，前端需保存
  "message_id": "f8a2b3..."   // 用于反馈
}
```

**Feedback 请求格式:**
```json
{
  "session_id": "abc123...",
  "message_id": "f8a2b3...",
  "rating": 5,                // 1-5
  "comment": "回答很准确"       // 可选
}
```

---

### 7. Chat UI (`static/chat.html`)

基于 SSE 的流式聊天界面，支持多轮对话和用户反馈。

**功能特性:**
- 流式输出回复 (逐字显示)
- 多轮对话 (session 自动管理，localStorage 持久化 session_id)
- 「新对话」按钮 (重置 session，清空聊天)
- 实时进度步骤 (可折叠，只显示最新步骤，历史可展开)
- 用户反馈按钮 (每条回复底部 👍/👎，反馈影响后续回答)
- 支持流式/非流式模式切换
- Markdown 渲染
- 预设问题建议 (总结科技新闻 / 热点趋势 / 对比分析 / 深度研究)

**访问方式:**
```bash
# 启动服务
python -m uvicorn main:app --reload

# 浏览器访问
http://localhost:8000/chat-ui
```

**SSE 事件类型:**
| 类型 | 说明 |
|------|------|
| `session` | 会话 ID (首个事件，前端保存到 localStorage) |
| `step` | Agent 步骤 (thinking, tool_call, tool_result) |
| `tool_progress` | 工具内部步骤 (analyzing, embedding, searching, summarizing, evaluating) |
| `delta` | 流式文本片段 |
| `done` | 完成，包含最终回复和 message_id |
| `error` | 错误信息 |

**进度步骤折叠:**
- 只显示最新一条进度步骤
- 历史步骤自动折叠到「展开处理步骤 (N)」中
- 点击可展开/收起查看完整处理流程
- 完成后所有步骤收到「查看处理步骤 (N)」中

---

### 8. 定时任务 (`scripts/schedule_pipeline.ps1`)

Windows 任务计划程序脚本。

**用法:**
```powershell
# 在项目目录下，以管理员身份运行
.\scripts\schedule_pipeline.ps1                  # 默认每天8点
.\scripts\schedule_pipeline.ps1 -Hour 9 -Minute 30
.\scripts\schedule_pipeline.ps1 -Categories "tech,finance"
.\scripts\schedule_pipeline.ps1 -MaxArticles 10
.\scripts\schedule_pipeline.ps1 -Status          # 查看状态
.\scripts\schedule_pipeline.ps1 -Remove          # 删除任务

# 手动触发
schtasks /run /tn "WSJ-RAG-Pipeline"
```

---

## 数据处理流水线

```
articles/**/*.json (爬取的文章)
       ↓
   IndexPipeline
       ├── 加载 JSON → NewsArticle
       ├── 解析 published_at (多种WSJ格式)
       ├── 去重检查 (indexed_files.json)
       ↓
   EmbeddingService.process_document()
       ├── 分块 (512 tokens, 50 overlap)
       ├── embed_batch() → 4096维向量
       ├── summarize_article() → 文章摘要
       └── summarize_chunks_batch() → 块摘要 (并行)
       ↓
   NewsRepository.index_document()
       └── 写入 OpenSearch (每chunk一条文档)
```

---

## 开发进度

### 已完成
- [x] Playwright 爬虫 (8个分类)
- [x] 单 URL 爬取功能
- [x] 首页50篇/其他20篇的差异化限制
- [x] OpenSearch 向量索引
- [x] Schema 自动同步
- [x] LlamaIndex FunctionAgent 集成
- [x] 智能查询分析 (QueryAnalyzer)
- [x] 多语言支持 (中英文自动翻译)
- [x] 独家新闻过滤
- [x] 自动总结功能
- [x] 时间感知 (Agent 知道当前日期)
- [x] 单文件索引 (`--file` 参数)
- [x] 强制重新索引 (`--force` 参数)
- [x] Windows 定时任务脚本
- [x] Chat UI 前端页面
- [x] SSE 流式输出
- [x] 工具内部进度跟踪
- [x] Agent 多轮对话记忆 (内存 Session)
- [x] 用户反馈机制 (👍/👎 + 反馈注入 prompt)
- [x] Agent 自我评估 (搜索质量打分 + 自动 retry)
- [x] 趋势分析工具 (热门话题识别)
- [x] 对比分析工具 (多话题横向对比)
- [x] 深度研究工具 (多角度综合报告)
- [x] 搜索去重重构 (消除重复代码)
- [x] 进度步骤折叠 UI
- [x] 新对话/会话管理 UI

### TODO
- [ ] 批量处理优化 (batch_size参数)
- [ ] 本地LLM支持 (LLMService接口抽象)
- [ ] 持久化对话存储 (当前为内存，重启丢失)
- [ ] Agent 多轮工具调用链 (当前每轮独立)

---

## 环境配置

### 环境要求
- Python 3.10+
- LM Studio (加载 qwen3-embedding-8b)
- OpenSearch (Docker, localhost:9200)
- AWS credentials (Bedrock 访问)
- Google Chrome (爬虫使用)

### 环境变量
```bash
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_INDEX=wsj_news
EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1
EMBEDDING_MODEL=text-embedding-qwen3-embedding-8b
VECTOR_DIMENSION=4096
CHUNK_SIZE=512
CHUNK_OVERLAP=50
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
LLM_MAX_TOKENS=1024
LLM_TEMPERATURE=0.3
LLM_MAX_WORKERS=5
DEBUG=false
```

### 快速启动
```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium

# 启动 OpenSearch
docker run -d -p 9200:9200 -e "discovery.type=single-node" opensearchproject/opensearch:latest

# 启动 LM Studio Server (端口 1234)

# 运行完整流程
python run_pipeline.py

# 或启动 API
uvicorn main:app --reload
```
