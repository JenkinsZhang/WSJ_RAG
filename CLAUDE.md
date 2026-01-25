# WSJ RAG 项目状态

> 最后更新：2026-01-25

## 项目概述

基于 RAG 的华尔街日报新闻热点总结系统。

## 技术栈

| 组件 | 技术选型 | 状态 |
|------|---------|------|
| 爬虫 | Playwright | ✅ 完成 |
| 向量化 | qwen3-embedding-8b (LM Studio, 4096维) | ✅ 完成 |
| 存储 | OpenSearch (localhost:9200) | ✅ 完成 |
| 索引器 | ArticleIndexer | ✅ 完成 |
| RAG | LlamaIndex | ✅ 完成 |
| Agent | LlamaIndex FunctionAgent | ✅ 完成 |
| LLM | AWS Bedrock Claude (可切换本地模型) | ✅ 完成 |
| API | FastAPI | ✅ 完成 |

## 已完成模块

### 1. 项目结构 (企业级模块化)

```
WSJRAG/
├── src/
│   ├── config/settings.py      # 集中配置管理，支持环境变量
│   ├── models/document.py      # NewsArticle, ProcessedDocument, SearchResult
│   ├── clients/                # 外部服务客户端
│   │   ├── opensearch.py       # OpenSearch 客户端封装
│   │   ├── embedding.py        # Embedding API 客户端 + 文档处理
│   │   └── llm.py              # Bedrock Claude 客户端
│   ├── storage/                # 数据访问层
│   │   ├── schema.py           # OpenSearch index schema (HNSW, cosine)
│   │   └── repository.py       # 数据访问层 (CRUD + 搜索)
│   ├── crawler/
│   │   ├── browser.py          # Playwright 持久化浏览器管理
│   │   ├── wsj_crawler.py      # WSJ 爬虫 (8个分类)
│   │   └── page_inspector.py   # 页面检查工具
│   ├── indexer/                # 文章索引管道
│   │   ├── loader.py           # Article JSON → NewsArticle
│   │   ├── date_parser.py      # WSJ 时间格式解析
│   │   ├── state.py            # indexed_files.json 管理
│   │   └── pipeline.py         # 索引主流程
│   ├── agent/                  # LlamaIndex Agent 模块
│   │   ├── tools.py            # NewsQueryTool + QueryAnalyzer
│   │   ├── news_agent.py       # FunctionAgent 封装
│   │   └── cli.py              # 命令行交互界面
│   └── utils/
│       ├── text.py             # 文本分块器
│       └── url.py              # URL 标准化
├── scripts/
│   └── clean_article_urls.py   # 清理已有文章URL
├── articles/                   # 爬取的文章 (按分类/日期组织)
├── data/
│   ├── crawled_urls.json       # 爬虫URL去重
│   └── indexed_files.json      # 索引状态追踪
├── examples/
│   ├── demo_pipeline.py        # 完整流程演示
│   └── run_indexer.py          # 索引脚本
├── main.py                     # FastAPI 入口
├── run_pipeline.py             # 完整数据流程脚本
└── requirements.txt
```

### 2. OpenSearch Index Schema

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

### 3. 数据处理流水线

```
articles/**/*.json (爬取的文章)
       ↓
   ArticleIndexer
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

### 4. 爬虫模块

**已实现功能:**
- Playwright 持久化浏览器 (保存登录状态)
- 8个分类爬取: home, world, china, tech, finance, business, politics, economy
- URL去重 (crawled_urls.json)
- 文章内容提取: 标题、副标题、作者、发布时间、正文
- EXCLUSIVE 文章优先级排序
- 自动滚动加载更多内容

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

### 5. API 端点

- `GET /health` - 健康检查
- `POST /index/setup` - 创建/重建索引
- `POST /articles` - 索引文章
- `POST /search` - 语义/混合搜索
- `GET /news/recent` - 获取最近新闻
- `GET /stats` - 索引统计

### 6. 索引器模块

将 `articles/` 目录下爬取的 JSON 文件索引到 OpenSearch。

**组件:**
- `date_parser.py`: 解析WSJ多种时间格式 ("Updated Jan. 23, 2026 4:39 pm ET")
- `state.py`: 使用 `indexed_files.json` 追踪已索引文件
- `loader.py`: 加载JSON文件，转换为NewsArticle
- `pipeline.py`: 完整索引流程 (load → embed → summarize → index)

**使用方法:**
```bash
# 索引所有待处理文章
python -m examples.run_indexer

# 只索引特定分类
python -m examples.run_indexer --category tech

# 重试失败的文件
python -m examples.run_indexer --retry-failed

# 查看统计信息
python -m examples.run_indexer --stats

# 预览待处理文件
python -m examples.run_indexer --dry-run
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

**预估处理时间 (单篇文章, 约3个chunks):** 10-17秒

### 7. 完整数据流程脚本

`run_pipeline.py` - 端到端流程: 爬虫 → 数据处理 → OpenSearch

**使用方法:**
```bash
# 完整流程 (爬取所有分类并索引)
python run_pipeline.py

# 只处理特定分类
python run_pipeline.py --category tech finance

# 限制每分类爬取数量
python run_pipeline.py --max-articles 5

# 只爬取不索引
python run_pipeline.py --crawl-only

# 只索引不爬取
python run_pipeline.py --index-only

# 详细日志
python run_pipeline.py -v
```

**日志:**
- 控制台: 带颜色的实时日志
- 文件: `logs/pipeline_YYYYMMDD_HHMMSS.log`

### 8. Agent 模块 (LlamaIndex)

基于 LlamaIndex FunctionAgent 的新闻问答 Agent。

**组件:**
- `tools.py`: NewsQueryTool + QueryAnalyzer (智能意图分析)
- `news_agent.py`: NewsAgent - LlamaIndex FunctionAgent 封装
- `cli.py`: 命令行交互界面

**核心功能:**
- 🌐 **多语言支持**: 用户可用中文或英文提问，查询自动翻译为英文进行检索
- 🕐 **时间感知**: 查询自动添加当前时间上下文
- 🇨🇳 **中文回答**: 无论输入语言，始终用中文回答
- 📝 **高token限制**: max_tokens=4096，支持详细回答
- ⭐ **独家新闻过滤**: 自动识别"独家"/"exclusive"关键词
- 📊 **智能总结**: 自动识别"总结"/"summarize"关键词，生成综合摘要

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
[如果 needs_summary] LLM 生成中文总结
```

**使用方法:**
```bash
# 交互模式
python -m src.agent.cli

# 详细模式 (显示 agent 推理过程)
python -m src.agent.cli --verbose

# 单次查询模式 (支持中文)
python -m src.agent.cli --query "帮我总结一下最近的独家科技新闻"
```

**NewsQueryTool 参数 (简化):**
| 参数 | 说明 |
|------|------|
| `query` | 自然语言查询 (任意语言，自动解析意图) |
| `max_results` | 最大结果数 (1-20, 默认5) |

**自动识别的意图关键词:**
| 关键词 | 效果 |
|--------|------|
| 独家/exclusive | `exclusive_only=True` |
| 总结/summarize | `needs_summary=True` → 生成中文摘要 |
| 今天/today | `hours_ago=24` |
| 最近/recent | `mode="recent"` |
| 科技/tech | `category="tech"` |

**Agent 特性:**
- 智能意图识别 (无需手动指定mode)
- 默认使用混合搜索 (hybrid)
- 引用文章标题和 URL
- **所有回答使用中文**

## 下一步开发

### 已完成
- [x] LlamaIndex FunctionAgent 集成
- [x] 智能查询分析 (QueryAnalyzer)
- [x] 多语言支持 (中英文自动翻译)
- [x] 独家新闻过滤
- [x] 自动总结功能
- [x] 时间感知 (Agent 知道当前日期)

### TODO
- [ ] 批量处理优化 (batch_size参数)
- [ ] 本地LLM支持 (LLMService接口抽象)
- [ ] Agent 多轮对话记忆
- [ ] 更多 Agent 工具 (趋势分析、对比分析)

## 环境要求

- Python 3.10+
- LM Studio (加载 qwen3-embedding-8b)
- OpenSearch (Docker, localhost:9200)
- AWS credentials (Bedrock 访问)

## 快速启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 API
uvicorn main:app --reload

# 运行 demo
python -m examples.demo_pipeline
```

## 配置 (环境变量)

```bash
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
EMBEDDING_BASE_URL=http://127.0.0.1:1234/v1
EMBEDDING_MODEL=text-embedding-qwen3-embedding-8b
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```
