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
| RAG | LlamaIndex | ⏳ 待开发 |
| Agent | LangChain | ⏳ 待开发 |
| LLM | AWS Bedrock Claude (可切换本地模型) | ✅ 完成 |
| API | FastAPI | ✅ 完成 |

## 已完成模块

### 1. 项目结构 (企业级模块化)

```
WSJRAG/
├── src/
│   ├── config/settings.py      # 集中配置管理，支持环境变量
│   ├── models/document.py      # NewsArticle, ProcessedDocument, SearchResult
│   ├── storage/
│   │   ├── schema.py           # OpenSearch index schema (HNSW, cosine)
│   │   ├── client.py           # OpenSearch 客户端封装
│   │   └── repository.py       # 数据访问层 (CRUD + 搜索)
│   ├── services/
│   │   ├── embedding.py        # Embedding + 文档处理流水线
│   │   └── llm.py              # Bedrock Claude 集成
│   ├── crawler/
│   │   ├── browser.py          # Playwright 持久化浏览器管理
│   │   ├── wsj_crawler.py      # WSJ 爬虫 (8个分类)
│   │   └── page_inspector.py   # 页面检查工具
│   ├── indexer/                # 文章索引管道
│   │   ├── loader.py           # Article JSON → NewsArticle
│   │   ├── date_parser.py      # WSJ 时间格式解析
│   │   ├── state.py            # indexed_files.json 管理
│   │   └── pipeline.py         # 索引主流程
│   └── utils/text.py           # 文本分块器
├── articles/                   # 爬取的文章 (按分类/日期组织)
├── data/
│   ├── crawled_urls.json       # 爬虫URL去重
│   └── indexed_files.json      # 索引状态追踪
├── examples/demo_pipeline.py   # 完整流程演示
├── main.py                     # FastAPI 入口
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

## 下一步开发

### TODO
- [ ] 批量处理优化 (batch_size参数)
- [ ] 本地LLM支持 (LLMService接口抽象)
- [ ] LlamaIndex RAG集成
- [ ] LangChain Agent

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
BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
```
