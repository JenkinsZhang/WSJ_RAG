# WSJ RAG

基于 RAG (Retrieval-Augmented Generation) 的华尔街日报新闻热点总结系统。

## 功能特性

- **智能爬虫**: Playwright 自动化爬取 WSJ 8个分类的新闻
- **语义搜索**: 基于向量的语义搜索 + BM25 混合搜索
- **智能摘要**: LLM 自动生成文章和段落摘要
- **增量处理**: 自动跳过已处理的文章，支持断点续传

## 技术栈

| 组件 | 技术 |
|------|------|
| 爬虫 | Playwright |
| 向量化 | LM Studio + qwen3-embedding-8b (4096维) |
| 存储 | OpenSearch (HNSW 向量索引) |
| LLM | AWS Bedrock Claude |
| API | FastAPI |

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
| `--category` | 指定分类: home, world, china, tech, finance, business, politics, economy |
| `--max-articles` | 每分类最大爬取数 (默认 20) |
| `--crawl-only` | 只运行爬虫 |
| `--index-only` | 只运行索引 |
| `--retry-failed` | 重试失败的文件 |
| `--skip-service-check` | 跳过服务检查 |
| `-v, --verbose` | 详细日志 |

---

### 单独运行爬虫

```bash
# 爬取所有分类
python -m src.crawler.wsj_crawler

# 爬取单个分类
python -m src.crawler.wsj_crawler --category tech
```

**注意**: 首次运行需要手动登录 WSJ 账号，登录状态会保存在 Chrome profile 中。

**输出目录结构:**
```
articles/
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
python -m examples.run_indexer

# 只索引特定分类
python -m examples.run_indexer --category tech

# 预览待处理文件 (不实际索引)
python -m examples.run_indexer --dry-run

# 查看索引统计
python -m examples.run_indexer --stats

# 重试失败的文件
python -m examples.run_indexer --retry-failed

# 清除失败记录
python -m examples.run_indexer --clear-failed
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

**搜索示例:**
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Federal Reserve interest rates", "k": 5}'
```

---

### 新闻问答 Agent (CLI)

基于 LlamaIndex 的交互式新闻问答 Agent，支持中英文查询，自动分析用户意图。

```bash
# 交互模式
python -m src.agent.cli

# 显示 agent 推理过程
python -m src.agent.cli --verbose

# 单次查询 (支持中英文)
python -m src.agent.cli --query "帮我总结一下最近的独家科技新闻"
python -m src.agent.cli --query "What's happening with Tesla?"
```

**核心功能:**
- 🌐 **多语言查询**: 中文/英文自动翻译为英文检索
- 🤖 **智能意图识别**: 自动检测搜索模式、时间范围、独家筛选、总结需求
- 🇨🇳 **中文回答**: 所有回答都使用中文
- ⏰ **时间感知**: Agent 知道当前日期，会说明新闻的时效性

**自动识别的关键词:**
| 关键词 | 效果 |
|--------|------|
| 独家/exclusive | 只搜索独家新闻 |
| 总结/summarize | 自动生成综合摘要 |
| 今天/最近/recent | 按时间筛选新闻 |
| 科技/tech/finance | 按分类筛选 |

**示例问题:**
- "帮我总结一下最近的独家科技新闻"
- "特斯拉最近有什么新闻？"
- "What's happening with Federal Reserve interest rates?"
- "今天有什么重要的商业新闻？"

---

## 项目结构

```
WSJRAG/
├── run_pipeline.py              # 完整流程入口
├── main.py                      # FastAPI 应用
├── src/
│   ├── config/settings.py       # 配置管理
│   ├── models/document.py       # 数据模型
│   ├── clients/                 # 外部服务客户端
│   │   ├── opensearch.py        # OpenSearch 客户端
│   │   ├── embedding.py         # Embedding 服务
│   │   └── llm.py               # LLM 服务 (Bedrock)
│   ├── storage/
│   │   ├── schema.py            # OpenSearch 索引设计
│   │   └── repository.py        # 数据访问层
│   ├── crawler/
│   │   ├── browser.py           # Playwright 浏览器
│   │   └── wsj_crawler.py       # WSJ 爬虫
│   ├── indexer/
│   │   ├── loader.py            # 文章加载器
│   │   ├── state.py             # 索引状态管理
│   │   └── pipeline.py          # 索引流水线
│   ├── agent/                   # LlamaIndex Agent
│   │   ├── tools.py             # NewsQueryTool
│   │   ├── news_agent.py        # FunctionAgent 封装
│   │   └── cli.py               # 命令行交互
│   └── utils/
│       ├── text.py              # 文本分块
│       └── url.py               # URL 标准化
├── scripts/
│   └── clean_article_urls.py    # URL 清理脚本
├── examples/
│   ├── run_indexer.py           # 索引脚本
│   └── demo_pipeline.py         # 演示脚本
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
                    ┌────────▼────────┐
                    │   FastAPI       │
                    │   搜索 API      │
                    └─────────────────┘
```

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
rm data/indexed_files.json
python -m examples.run_indexer

# 方法2: 删除 OpenSearch 索引，重建
curl -X DELETE http://localhost:9200/wsj_news
python run_pipeline.py --index-only
```

---

## 开发计划

- [x] LlamaIndex RAG 集成
- [x] 智能 Agent (FunctionAgent + QueryAnalyzer)
- [ ] 本地 LLM 支持
- [ ] 批量处理优化
- [ ] 定时爬取调度
- [ ] Agent 多轮对话记忆

---

## License

MIT
