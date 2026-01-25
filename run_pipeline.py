#!/usr/bin/env python
"""
WSJ RAG 完整数据流程脚本

流程: 爬虫 → 数据处理 → 写入OpenSearch

使用方法:
    # 爬取所有分类并索引
    python run_pipeline.py

    # 只爬取特定分类
    python run_pipeline.py --category tech

    # 只爬取不索引
    python run_pipeline.py --crawl-only

    # 只索引不爬取 (处理已有的articles目录)
    python run_pipeline.py --index-only

    # 限制每个分类爬取的文章数
    python run_pipeline.py --max-articles 5

    # 详细日志
    python run_pipeline.py -v
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.crawler.wsj_crawler import WSJCrawler, PAGES_TO_CRAWL, Article
from src.indexer import IndexPipeline, IndexState
from src.storage.client import get_opensearch_client


# ============== 日志配置 ==============

class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""

    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> logging.Logger:
    """配置日志系统"""

    # 根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # 清除现有handlers
    root_logger.handlers.clear()

    # 控制台handler (带颜色)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_format = ColoredFormatter(
        fmt="%(asctime)s │ %(levelname)-17s │ %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # 文件handler (如果指定)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        root_logger.addHandler(file_handler)

    # 静默第三方库
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("opensearch").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)

    return logging.getLogger("pipeline")


# ============== 服务检查 ==============

def check_services(logger: logging.Logger) -> dict:
    """检查所有服务状态"""

    logger.info("=" * 60)
    logger.info("服务状态检查")
    logger.info("=" * 60)

    status = {
        "opensearch": False,
        "embedding": False,
        "llm": False,
    }

    # 检查 OpenSearch 并确保 schema 最新
    try:
        client = get_opensearch_client()
        health = client.health_check()
        if health.get("status") != "healthy":
            logger.error(f"✗ OpenSearch: 异常 - {health}")
            return status

        # 确保索引存在且 schema 最新
        schema_result = client.ensure_schema_current()
        if schema_result["status"] == "created":
            logger.info(f"✓ OpenSearch: 已创建索引 {schema_result['index']}")
        elif schema_result["status"] == "updated":
            logger.info(f"✓ OpenSearch: 已更新 schema，新增字段: {schema_result['fields_added']}")
        elif schema_result["status"] == "current":
            logger.info(f"✓ OpenSearch: 正常 (schema 已是最新)")
        elif schema_result["status"] == "error":
            logger.error(f"✗ OpenSearch: schema 更新失败 - {schema_result.get('error')}")
            return status

        status["opensearch"] = True
    except Exception as e:
        logger.error(f"✗ OpenSearch: 连接失败 - {e}")

    # 检查 Embedding 服务
    try:
        from src.services.embedding import get_embedding_service
        embed_svc = get_embedding_service()
        health = embed_svc.health_check()
        if health.get("status") == "healthy":
            status["embedding"] = True
            logger.info(f"✓ Embedding: 正常 ({embed_svc.model})")
        else:
            logger.error(f"✗ Embedding: 异常 - {health}")
    except Exception as e:
        logger.error(f"✗ Embedding: 连接失败 - {e}")

    # 检查 LLM 服务
    try:
        from src.services.llm import get_llm_service
        llm_svc = get_llm_service()
        health = llm_svc.health_check()
        if health.get("status") == "healthy":
            status["llm"] = True
            logger.info(f"✓ LLM: 正常 (Bedrock Claude)")
        else:
            logger.error(f"✗ LLM: 异常 - {health}")
    except Exception as e:
        logger.error(f"✗ LLM: 连接失败 - {e}")

    logger.info("-" * 60)

    return status


# ============== 爬虫阶段 ==============

def run_crawler(
    logger: logging.Logger,
    categories: Optional[list[str]] = None,
    max_articles: int = 20,
) -> dict[str, list[Article]]:
    """
    运行爬虫阶段

    Args:
        logger: 日志记录器
        categories: 要爬取的分类列表 (None=全部)
        max_articles: 每个分类最大文章数

    Returns:
        dict: {category: [Article, ...]}
    """

    logger.info("")
    logger.info("=" * 60)
    logger.info("阶段 1: 爬虫")
    logger.info("=" * 60)

    # 确定要爬取的分类
    if categories:
        targets = {k: v for k, v in PAGES_TO_CRAWL.items() if k in categories}
        if not targets:
            logger.error(f"无效的分类: {categories}")
            logger.info(f"可用分类: {list(PAGES_TO_CRAWL.keys())}")
            return {}
    else:
        targets = PAGES_TO_CRAWL

    logger.info(f"目标分类: {list(targets.keys())}")
    logger.info(f"每分类最大文章数: {max_articles}")

    # 初始化爬虫
    crawler = WSJCrawler()

    # 修改最大文章数
    import src.crawler.wsj_crawler as crawler_module
    original_max = crawler_module.MAX_ARTICLES_PER_PAGE
    crawler_module.MAX_ARTICLES_PER_PAGE = max_articles

    results = {}
    total_articles = 0

    try:
        if not crawler.connect():
            logger.error("无法连接浏览器")
            return {}

        for category, url in targets.items():
            logger.info("")
            logger.info(f">>> 爬取分类: {category.upper()}")

            try:
                articles = crawler.crawl_page(category, url)
                results[category] = articles
                total_articles += len(articles)

                logger.info(f"<<< {category}: 爬取了 {len(articles)} 篇文章")

            except Exception as e:
                logger.error(f"爬取 {category} 失败: {e}")
                results[category] = []

            # 分类间休息
            if category != list(targets.keys())[-1]:
                wait_time = 3
                logger.debug(f"等待 {wait_time} 秒...")
                time.sleep(wait_time)

    finally:
        crawler.disconnect()
        # 恢复原始设置
        crawler_module.MAX_ARTICLES_PER_PAGE = original_max

    logger.info("")
    logger.info("-" * 60)
    logger.info(f"爬虫完成: 共 {total_articles} 篇文章")

    return results


# ============== 索引阶段 ==============

def run_indexer(
    logger: logging.Logger,
    articles_dir: str = "articles",
    categories: Optional[list[str]] = None,
    retry_failed: bool = False,
) -> dict:
    """
    运行索引阶段

    Args:
        logger: 日志记录器
        articles_dir: 文章目录
        categories: 要索引的分类列表 (None=全部)
        retry_failed: 是否重试失败的文件

    Returns:
        dict: 索引结果统计
    """

    logger.info("")
    logger.info("=" * 60)
    logger.info("阶段 2: 索引")
    logger.info("=" * 60)

    # 确定要索引的目录
    base_dir = Path(articles_dir)
    if categories:
        dirs_to_index = [base_dir / cat for cat in categories if (base_dir / cat).exists()]
    else:
        dirs_to_index = [base_dir]

    if not dirs_to_index:
        logger.warning("没有找到要索引的目录")
        return {"indexed": 0, "failed": 0, "total_chunks": 0}

    # 确保OpenSearch索引存在
    client = get_opensearch_client()
    if not client.index_exists():
        logger.info("创建 OpenSearch 索引...")
        client.ensure_index_exists(recreate=False)

    # 初始化索引管道
    pipeline = IndexPipeline(state_file="data/indexed_files.json")

    total_indexed = 0
    total_failed = 0
    total_chunks = 0

    for dir_path in dirs_to_index:
        logger.info(f">>> 索引目录: {dir_path}")

        result = pipeline.index_all(
            articles_dir=dir_path,
            include_failed=retry_failed,
            save_interval=3,
        )

        total_indexed += result.indexed
        total_failed += result.failed
        total_chunks += result.total_chunks

        logger.info(f"<<< {dir_path.name}: {result.indexed} 成功, {result.failed} 失败")

    logger.info("")
    logger.info("-" * 60)
    logger.info(f"索引完成: {total_indexed} 篇文章, {total_chunks} 个块")

    if total_failed > 0:
        logger.warning(f"失败: {total_failed} 篇文章")

    return {
        "indexed": total_indexed,
        "failed": total_failed,
        "total_chunks": total_chunks,
    }


# ============== 主流程 ==============

def run_full_pipeline(
    logger: logging.Logger,
    categories: Optional[list[str]] = None,
    max_articles: int = 20,
    crawl_only: bool = False,
    index_only: bool = False,
    retry_failed: bool = False,
    skip_service_check: bool = False,
) -> dict:
    """
    运行完整的数据流程

    Args:
        logger: 日志记录器
        categories: 要处理的分类列表
        max_articles: 每分类最大爬取数
        crawl_only: 只爬取不索引
        index_only: 只索引不爬取
        retry_failed: 重试失败的文件
        skip_service_check: 跳过服务检查

    Returns:
        dict: 流程执行结果
    """

    start_time = time.time()

    logger.info("")
    logger.info("╔" + "═" * 58 + "╗")
    logger.info("║" + " WSJ RAG 数据流程 ".center(58) + "║")
    logger.info("║" + f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ".center(58) + "║")
    logger.info("╚" + "═" * 58 + "╝")

    result = {
        "crawl": {"articles": 0, "categories": []},
        "index": {"indexed": 0, "failed": 0, "total_chunks": 0},
        "elapsed_seconds": 0,
        "success": True,
    }

    # 服务检查 (索引阶段需要)
    if not crawl_only and not skip_service_check:
        service_status = check_services(logger)

        if not all(service_status.values()):
            logger.error("服务检查未通过，使用 --skip-service-check 跳过")
            result["success"] = False
            return result

    # 阶段 1: 爬虫
    if not index_only:
        crawl_results = run_crawler(
            logger=logger,
            categories=categories,
            max_articles=max_articles,
        )

        total_articles = sum(len(articles) for articles in crawl_results.values())
        result["crawl"] = {
            "articles": total_articles,
            "categories": list(crawl_results.keys()),
        }

        if total_articles == 0:
            logger.warning("没有爬取到新文章")
            if crawl_only:
                result["elapsed_seconds"] = time.time() - start_time
                return result

    # 阶段 2: 索引
    if not crawl_only:
        index_result = run_indexer(
            logger=logger,
            articles_dir="articles",
            categories=categories,
            retry_failed=retry_failed,
        )

        result["index"] = index_result

        if index_result["failed"] > 0:
            result["success"] = False

    # 完成
    elapsed = time.time() - start_time
    result["elapsed_seconds"] = elapsed

    logger.info("")
    logger.info("╔" + "═" * 58 + "╗")
    logger.info("║" + " 流程完成 ".center(58) + "║")
    logger.info("╚" + "═" * 58 + "╝")
    logger.info("")
    logger.info(f"  爬取文章: {result['crawl']['articles']}")
    logger.info(f"  索引文章: {result['index']['indexed']}")
    logger.info(f"  索引块数: {result['index']['total_chunks']}")
    logger.info(f"  失败数量: {result['index']['failed']}")
    logger.info(f"  总耗时:   {elapsed:.1f} 秒")
    logger.info("")

    return result


# ============== 入口 ==============

def main():
    parser = argparse.ArgumentParser(
        description="WSJ RAG 完整数据流程: 爬虫 → 数据处理 → OpenSearch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_pipeline.py                     # 完整流程
  python run_pipeline.py --category tech     # 只处理tech分类
  python run_pipeline.py --crawl-only        # 只爬取
  python run_pipeline.py --index-only        # 只索引
  python run_pipeline.py --max-articles 5    # 限制爬取数量
        """,
    )

    parser.add_argument(
        "--category", "-c",
        nargs="+",
        choices=list(PAGES_TO_CRAWL.keys()),
        help="指定要处理的分类 (可多选)",
    )

    parser.add_argument(
        "--max-articles", "-m",
        type=int,
        default=20,
        help="每个分类最大爬取文章数 (默认: 20)",
    )

    parser.add_argument(
        "--crawl-only",
        action="store_true",
        help="只运行爬虫，不索引",
    )

    parser.add_argument(
        "--index-only",
        action="store_true",
        help="只运行索引，不爬取",
    )

    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="重试之前失败的文件",
    )

    parser.add_argument(
        "--skip-service-check",
        action="store_true",
        help="跳过服务状态检查",
    )

    parser.add_argument(
        "--log-file",
        help="日志文件路径 (默认只输出到控制台)",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细日志输出",
    )

    args = parser.parse_args()

    # 互斥检查
    if args.crawl_only and args.index_only:
        parser.error("--crawl-only 和 --index-only 不能同时使用")

    # 配置日志
    log_file = args.log_file
    if not log_file:
        # 默认日志文件
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = setup_logging(verbose=args.verbose, log_file=str(log_file))
    logger.info(f"日志文件: {log_file}")

    # 运行流程
    try:
        result = run_full_pipeline(
            logger=logger,
            categories=args.category,
            max_articles=args.max_articles,
            crawl_only=args.crawl_only,
            index_only=args.index_only,
            retry_failed=args.retry_failed,
            skip_service_check=args.skip_service_check,
        )

        sys.exit(0 if result["success"] else 1)

    except KeyboardInterrupt:
        logger.warning("\n用户中断")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"流程异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
