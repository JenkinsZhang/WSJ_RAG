# WSJ RAG

基于 RAG (Retrieval-Augmented Generation) 的华尔街日报新闻热点总结系统。

## 功能特性

- **智能爬虫**: Playwright 自动化爬取 WSJ 8个分类的新闻，支持单 URL 爬取
- **语义搜索**: 基于向量的语义搜索 + BM25 混合搜索
- **智能摘要**: LLM 自动生成文章和段落摘要
- **增量处理**: 自动跳过已处理的文章，支持断点续传
- **智能 Agent**: 基于 LlamaIndex 的多工具新闻问答，多轮对话，自我评估
- **Chat UI**: SSE 流式聊天界面，实时进度，反馈机制
- **定时任务**: Windows 任务计划程序自动运行

## 技术栈

| 组件 | 技术 |
|------|------|
| 爬虫 | Playwright |
| 向量化 | LM Studio + qwen3-embedding-8b (4096维) |
| 存储 | OpenSearch (HNSW 向量索引) |
| LLM | AWS Bedrock Claude |
| Agent | LlamaIndex FunctionAgent |
| API | FastAPI + SSE |
| Chat UI | HTML + Markdown + 流式输出 |

## 环境要求

- Python 3.10+
- [LM Studio](https://lmstudio.ai/) - 运行本地 embedding 模型
- [OpenSearch](https://opensearch.org/) - Docker 运行
- AWS 账号 - Bedrock Claude 访问权限
- Google Chrome - 爬虫使用

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 启动服务

```bash
# OpenSearch (Docker)
docker run -d -p 9200:9200 -e "discovery.type=single-node" opensearchproject/opensearch:latest

# LM Studio
# 启动 LM Studio，加载 qwen3-embedding-8b 模型，开启 Server 模式 (端口 1234)
```

### 3. 配置环境变量 (可选)

```bash
# OpenSearch
export OPENSEARCH_HOST=localhost
export OPENSEARCH_PORT=9200

# Embedding
export EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1
export EMBEDDING_MODEL=text-embedding-qwen3-embedding-8b

# AWS Bedrock
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

---

## 脚本使用

### 完整流程 (推荐)

`run_pipeline.py` - 一键完成爬取和索引

```bash
# 完整流程：爬取所有分类 → 索引到 OpenSearch
python run_pipeline.py

# 只处理特定分类
python run_pipeline.py --category tech finance

# 限制每分类爬取数量 (测试用)
python run_pipeline.py --max-articles 5

# 只爬取，不索引
python run_pipeline.py --crawl-only

# 只索引已有文章，不爬取
python run_pipeline.py --index-only

# 重试之前失败的文件
python run_pipeline.py --retry-failed

# 详细日志
python run_pipeline.py -v
```

**参数说明:**

| 参数 | 说明 |
|------|------|
| `--category, -c` | 指定分类: home, world, china, tech, finance, business, politics, economy |
| `--max-articles, -m` | 每分类最大爬取数 (默认: home=50, 其他=20) |
| `--crawl-only` | 只运行爬虫 |
| `--index-only` | 只运行索引 |
| `--retry-failed` | 重试失败的文件 |
| `--skip-service-check` | 跳过服务检查 |
| `--log-file` | 指定日志文件路径 |
| `-v, --verbose` | 详细日志 |

---

### 单独运行爬虫

```bash
# 显示帮助和可用分类
python -m src.crawler.wsj_crawler

# 爬取所有分类
python -m src.crawler.wsj_crawler all

# 爬取单个分类
python -m src.crawler.wsj_crawler tech
python -m src.crawler.wsj_crawler china

# 爬取单个 URL (自动推断分类)
python -m src.crawler.wsj_crawler --url "https://www.wsj.com/tech/ai/article-slug"

# 爬取单个 URL (指定分类)
python -m src.crawler.wsj_crawler --url "https://www.wsj.com/..." --category-for-url tech
```

**爬取数量限制:**
- 首页 (home): 最多 50 篇文章
- 其他分类: 最多 20 篇文章

**注意**: 首次运行需要手动登录 WSJ 账号，登录状态会保存在 Chrome profile 中。

**输出目录结构:**
```
articles/
├── home/
│   └── 2026-01-25/
│       └── ...
├── tech/
│   └── 2026-01-25/
│       ├── intel-shares-slide-9271b096.json
│       └── google-gmail-ai-74c5eaf7.json
├── finance/
│   └── 2026-01-25/
│       └── ...
└── ...
```

---

### 单独运行索引

```bash
# 索引所有待处理文章
python -m scripts.run_indexer

# 索引单个 JSON 文件
python -m scripts.run_indexer --file articles/tech/2026-01-25/article.json

# 强制重新索引 (即使已索引)
python -m scripts.run_indexer --file articles/tech/2026-01-25/article.json --force

# 只索引特定分类
python -m scripts.run_indexer --category tech

# 预览待处理文件 (不实际索引)
python -m scripts.run_indexer --dry-run

# 查看索引统计
python -m scripts.run_indexer --stats

# 重试失败的文件
python -m scripts.run_indexer --retry-failed

# 清除失败记录
python -m scripts.run_indexer --clear-failed

# 跳过服务检查
python -m scripts.run_indexer --skip-check
```

**索引状态文件:** `data/indexed_files.json`

---

### 启动 API 服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**API 端点:**

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/index/setup` | POST | 创建/重建索引 |
| `/articles` | POST | 索引单篇文章 |
| `/search` | POST | 语义/混合搜索 |
| `/news/recent` | GET | 获取最近新闻 |
| `/stats` | GET | 索引统计 |
| `/session` | POST | 创建会话 |
| `/session/{id}` | DELETE | 删除会话 |
| `/chat` | POST | Agent 问答 (支持 session_id) |
| `/chat/stream` | POST | Agent 问答 (SSE 流式) |
| `/chat/feedback` | POST | 提交反馈 (👍/👎) |
| `/chat-ui` | GET | 聊天界面 |

**Chat UI:** 浏览器访问 `http://localhost:8000/chat-ui`

---

### 新闻问答 Agent (CLI)

基于 LlamaIndex 的多工具新闻问答 Agent，支持多轮对话、自我评估、中英文查询。

```bash
# 交互模式 (多轮对话)
python -m src.agent.cli

# 显示 agent 推理过程
python -m src.agent.cli --verbose

# 单次查询
python -m src.agent.cli --query "帮我总结一下最近的独家科技新闻"
```

**Agent 工具集 (6 个):**

| 工具 | 触发场景 | 功能 |
|------|---------|------|
| `news_query` | 具体新闻搜索 | 意图分析 → 搜索 → 自我评估 → 可选总结 |
| `trend_analysis` | "热点"/"趋势" | 近期新闻统计 → LLM 识别热门话题 |
| `compare_articles` | "对比"/"vs" | 多话题搜索 → 结构化对比 |
| `deep_research` | "深入分析" | 多角度搜索 → 综合研究报告 |
| `database_info` | "有多少文章" | 数据库统计/最新文章/分类分布 |
| *(Free Chat)* | 日常对话/通用知识 | 直接回答，不调用工具 |

**核心能力:**
- **多轮对话**: 基于内存 Session，支持上下文记忆
- **自我评估**: 搜索后 LLM 评分 (1-5)，低分自动切换搜索模式重试
- **用户反馈**: 👍/👎 反馈注入下一轮 prompt
- **Free Chat**: 日常对话、通用知识问题直接回答，不调工具
- **多语言**: 中文/英文自动翻译检索，所有回答使用中文
- **时间感知**: Agent 知道当前日期，说明新闻时效性

**CLI 命令:**
| 命令 | 说明 |
|------|------|
| `exit`/`quit`/`q` | 退出 |
| `clear`/`cls` | 清屏并重置对话 |
| `history` | 查看对话历史 |
| `help`/`?` | 显示帮助 |

**示例问题:**
- "你好" → 直接回答 (Free Chat)
- "什么是量化宽松" → 直接回答 (通用知识)
- "帮我总结最近的科技新闻" → news_query
- "最近有什么热点？" → trend_analysis
- "对比一下 Tesla 和 BYD" → compare_articles
- "深入研究 AI 对就业的影响" → deep_research
- "数据库最新文章是几号的？" → database_info

---

## 项目结构

```
WSJRAG/
├── run_pipeline.py              # 完整流程入口 (爬虫+索引)
├── main.py                      # FastAPI 应用
├── requirements.txt             # Python 依赖
├── src/
│   ├── config/settings.py       # 配置管理
│   ├── models/document.py       # 数据模型 (NewsArticle, SearchResult)
│   ├── clients/                 # 外部服务客户端
│   │   ├── opensearch.py        # OpenSearch 客户端
│   │   ├── embedding.py         # Embedding 服务
│   │   └── llm.py               # LLM 服务 (Bedrock)
│   ├── storage/
│   │   ├── schema.py            # OpenSearch 索引设计
│   │   └── repository.py        # 数据访问层
│   ├── crawler/
│   │   ├── browser.py           # Playwright 浏览器管理
│   │   ├── wsj_crawler.py       # WSJ 爬虫
│   │   └── page_inspector.py    # 页面检查工具
│   ├── indexer/
│   │   ├── loader.py            # 文章加载器
│   │   ├── date_parser.py       # 日期解析器
│   │   ├── state.py             # 索引状态管理
│   │   └── pipeline.py          # 索引流水线
│   ├── agent/                   # LlamaIndex Agent
│   │   ├── models.py            # 共享数据类 (QueryIntent, NewsQueryResult 等)
│   │   ├── query_analyzer.py    # 查询意图分析 + 结果总结
│   │   ├── tools_query.py       # 新闻搜索工具 (NewsQueryTool)
│   │   ├── tools_trend.py       # 趋势分析工具
│   │   ├── tools_compare.py     # 对比分析工具
│   │   ├── tools_research.py    # 深度研究工具
│   │   ├── tools_database.py    # 数据库信息工具
│   │   ├── news_agent.py        # FunctionAgent 封装 (多轮+异步进度)
│   │   ├── session.py           # 内存会话管理
│   │   ├── progress.py          # 异步进度跟踪
│   │   └── cli.py               # 命令行交互 (多轮对话)
│   └── utils/
│       ├── text.py              # 文本分块
│       └── url.py               # URL 标准化
├── scripts/
│   ├── run_indexer.py           # 索引 CLI 工具
│   ├── clean_article_urls.py    # URL 清理脚本
│   ├── schedule_pipeline.ps1    # Windows 定时任务脚本
│   └── run_pipeline.bat         # 定时任务批处理 (自动生成)
├── examples/
│   └── demo_pipeline.py         # 完整流程演示
├── articles/                    # 爬取的文章 (gitignore)
├── data/                        # 状态文件 (gitignore)
│   ├── crawled_urls.json        # 爬虫 URL 去重
│   └── indexed_files.json       # 索引状态
└── logs/                        # 日志文件 (gitignore)
```

---

## 数据流程

```
                    ┌─────────────────┐
                    │   WSJ 网站       │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Playwright    │
                    │   爬虫          │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  articles/*.json │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   ┌──────▼──────┐   ┌───────▼───────┐   ┌──────▼──────┐
   │  分块        │   │  Embedding    │   │  LLM 摘要   │
   │  512 tokens  │   │  4096 维      │   │  Bedrock    │
   └──────┬──────┘   └───────┬───────┘   └──────┬──────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                    ┌────────▼────────┐
                    │   OpenSearch    │
                    │   wsj_news      │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   ┌──────▼──────┐   ┌───────▼───────┐   ┌──────▼──────┐
   │  FastAPI    │   │  Agent CLI    │   │  定时任务   │
   │  搜索 API   │   │  问答交互     │   │  自动爬取   │
   └─────────────┘   └───────────────┘   └─────────────┘
```

---

## 定时任务 (Windows)

使用 PowerShell 脚本设置 Windows 任务计划程序自动运行 pipeline：

```powershell
# 在项目目录下，以管理员身份运行 PowerShell

# 设置每天早上8点运行 (默认)
.\scripts\schedule_pipeline.ps1

# 自定义时间和分类
.\scripts\schedule_pipeline.ps1 -Hour 9 -Minute 30 -Categories "tech,finance"

# 自定义每分类文章数
.\scripts\schedule_pipeline.ps1 -MaxArticles 10

# 查看任务状态
.\scripts\schedule_pipeline.ps1 -Status

# 删除任务
.\scripts\schedule_pipeline.ps1 -Remove

# 手动触发运行
schtasks /run /tn "WSJ-RAG-Pipeline"

# 打开任务计划程序 GUI
taskschd.msc
```

**参数说明:**
| 参数 | 说明 |
|------|------|
| `-Hour` | 运行小时 (0-23, 默认 8) |
| `-Minute` | 运行分钟 (0-59, 默认 0) |
| `-Categories` | 分类列表，逗号分隔 |
| `-MaxArticles` | 每分类最大文章数 (默认 20) |
| `-Status` | 查看任务状态 |
| `-Remove` | 删除任务 |

---

## 常见问题

### Q: 爬虫无法登录 WSJ？

首次运行爬虫时，会打开 Chrome 浏览器，需要手动登录 WSJ 账号。登录状态会保存在 `E:\chrome-debug-profile` 目录。

### Q: Embedding 服务连接失败？

确保 LM Studio 已启动并加载了 embedding 模型，Server 模式监听 `http://127.0.0.1:1234`。

### Q: OpenSearch 连接失败？

```bash
# 检查 OpenSearch 是否运行
curl http://localhost:9200

# Docker 启动
docker run -d -p 9200:9200 -e "discovery.type=single-node" opensearchproject/opensearch:latest
```

### Q: 同一篇文章会被重复索引吗？

不会。系统使用 URL 生成唯一 ID，并且会自动标准化 URL（移除查询参数如 `?mod=nav`），确保同一篇文章无论从哪个入口访问都会生成相同的 ID。

```
https://wsj.com/tech/article?mod=nav     → ID: abc123
https://wsj.com/tech/article?mod=search  → ID: abc123 (相同)
```

### Q: 如何清理已爬取文章的 URL？

如果已有文章包含查询参数，可以使用清理脚本：

```bash
# 预览需要更新的文件
python scripts/clean_article_urls.py

# 应用更改
python scripts/clean_article_urls.py --apply
```

### Q: 如何重新索引所有文章？

```bash
# 方法1: 清除索引状态，重新索引
del data\indexed_files.json
python -m scripts.run_indexer

# 方法2: 删除 OpenSearch 索引，重建
curl -X DELETE http://localhost:9200/wsj_news
python run_pipeline.py --index-only
```

### Q: 定时任务脚本报错？

确保在项目根目录下运行，并以管理员身份运行 PowerShell：

```powershell
cd E:\Programming\Pycharm\WSJRAG
.\scripts\schedule_pipeline.ps1
```

---

## 开发计划

- [x] Playwright 爬虫 (8个分类 + 单URL)
- [x] OpenSearch 向量索引 + Schema 自动同步
- [x] LlamaIndex RAG 集成
- [x] 智能 Agent (FunctionAgent + 6 个工具)
- [x] 多语言支持 (中英文自动翻译)
- [x] Agent 多轮对话记忆 (内存 Session)
- [x] Agent 自我评估 + 自动 retry
- [x] 用户反馈机制 (👍/👎 → prompt 注入)
- [x] 趋势分析 / 对比分析 / 深度研究工具
- [x] 数据库信息查询工具
- [x] Free Chat (不调工具直接回答)
- [x] Chat UI (SSE 流式 + 折叠进度 + 反馈)
- [x] 异步进度推送 (双 task unified queue)
- [x] Windows 定时任务
- [ ] 本地 LLM 支持 (LLMService 接口抽象)
- [ ] 持久化对话存储 (当前为内存)

---

## License

MIT
