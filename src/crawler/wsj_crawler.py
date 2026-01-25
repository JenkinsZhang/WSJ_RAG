"""
WSJ 爬虫 MVP 版本

功能：
1. 爬取 WSJ 多个分类页面的文章
2. EXCLUSIVE 文章优先爬取
3. 人类化滚动加载（1~3秒随机等待）
4. 输出 JSON 格式，按 category/date/article.json 组织
5. 避免重复爬取

使用方法：
    python -m src.crawler.wsj_crawler
"""

import json
import logging
import random
import re
import hashlib
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext

from src.utils.url import normalize_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============== 配置 ==============

# Chrome 路径和 profile
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
USER_DATA_DIR = Path(r"E:\chrome-debug-profile")

# 输出目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
ARTICLES_DIR = PROJECT_ROOT / "articles"
CRAWLED_URLS_FILE = PROJECT_ROOT / "data" / "crawled_urls.json"

# 要爬取的页面
PAGES_TO_CRAWL = {
    "home": "https://www.wsj.com/",
    "world": "https://www.wsj.com/world?mod=nav_top_section",
    "china": "https://www.wsj.com/world/china?mod=nav_top_subsection",
    "tech": "https://www.wsj.com/tech?mod=nav_top_section",
    "finance": "https://www.wsj.com/finance?mod=nav_top_section",
    "business": "https://www.wsj.com/business?mod=nav_top_section",
    "politics": "https://www.wsj.com/politics?mod=nav_top_section",
    "economy": "https://www.wsj.com/economy?mod=nav_top_section",
}

# 每页最大文章数
MAX_ARTICLES_PER_PAGE = 20
MAX_ARTICLES_HOME = 50  # 首页允许更多文章


# ============== 数据结构 ==============

@dataclass
class ArticleLink:
    """文章链接信息"""
    title: str
    url: str
    is_exclusive: bool = False
    priority: int = 1  # 0=最高 (EXCLUSIVE), 1=普通


@dataclass
class Article:
    """文章完整数据"""
    title: str
    url: str
    content: str
    author: Optional[str] = None
    published_at: Optional[str] = None
    subtitle: Optional[str] = None
    category: Optional[str] = None
    source: str = "WSJ"
    is_exclusive: bool = False
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def generate_id(self) -> str:
        """生成文章唯一ID（基于清理后的URL）"""
        clean_url = normalize_url(self.url)
        return hashlib.md5(clean_url.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        """转为字典"""
        return asdict(self)

    def generate_filename(self) -> str:
        """生成文件名 (从URL提取slug)"""
        # 从URL提取slug: /tech/article-title-abc123 -> article-title-abc123
        path = urlparse(self.url).path
        slug = path.rstrip('/').split('/')[-1]
        # 清理特殊字符
        slug = re.sub(r'[^\w\-]', '', slug)
        if len(slug) > 80:
            slug = slug[:80]
        return f"{slug}.json"


# ============== 爬虫核心 ==============

class WSJCrawler:
    """WSJ 爬虫"""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._crawled_urls: set[str] = set()

        # 加载已爬取的URL
        self._load_crawled_urls()

    def _normalize_url(self, url: str) -> str:
        """标准化URL用于去重（去掉参数部分）"""
        return normalize_url(url)

    def _load_crawled_urls(self):
        """加载已爬取的URL列表"""
        if CRAWLED_URLS_FILE.exists():
            try:
                with open(CRAWLED_URLS_FILE, 'r', encoding='utf-8') as f:
                    # 加载时也标准化
                    urls = json.load(f)
                    self._crawled_urls = set(self._normalize_url(u) for u in urls)
                logger.info(f"已加载 {len(self._crawled_urls)} 个已爬取URL")
            except Exception as e:
                logger.warning(f"加载已爬取URL失败: {e}")

    def _save_crawled_urls(self):
        """保存已爬取的URL列表"""
        CRAWLED_URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CRAWLED_URLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(self._crawled_urls), f, ensure_ascii=False, indent=2)

    def connect(self) -> bool:
        """启动浏览器（持久化模式）"""
        logger.info("启动浏览器...")

        try:
            self._playwright = sync_playwright().start()

            # 使用持久化 context
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=False,
                executable_path=str(CHROME_PATH),
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )

            # 获取或创建页面
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()

            logger.info("浏览器启动成功")
            return True

        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            return False

    def disconnect(self):
        """关闭浏览器"""
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("浏览器已关闭")

    def _scroll_to_bottom(self, for_list_page: bool = True):
        """
        滚动到页面底部，确保懒加载内容全部加载

        Args:
            for_list_page: True=列表页(监控h3), False=详情页(监控高度)
        """
        last_value = 0
        stable_count = 0
        scroll_count = 0
        max_scrolls = 15

        if for_list_page:
            last_value = len(self._page.locator("h3").all())
            logger.info(f"  开始滚动，当前 h3: {last_value}")
        else:
            last_value = self._page.evaluate("document.body.scrollHeight")

        while stable_count < 2 and scroll_count < max_scrolls:
            # 直接滚到当前底部
            self._page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
            scroll_count += 1

            # 等待 3 秒让内容加载
            self._page.wait_for_timeout(3000)

            # 检查是否有新内容
            if for_list_page:
                current_value = len(self._page.locator("h3").all())
            else:
                current_value = self._page.evaluate("document.body.scrollHeight")

            if current_value > last_value:
                stable_count = 0
                last_value = current_value
            else:
                stable_count += 1

        if for_list_page:
            logger.info(f"  滚动完成: {scroll_count}次, h3: {last_value}")

    def _extract_article_links(self, category: str) -> list[ArticleLink]:
        """
        从列表页提取文章链接
        注: EXCLUSIVE 标记在详情页判断，列表页只提取链接
        """
        articles = []
        seen_urls = set()

        # 等待文章标题加载
        try:
            self._page.wait_for_selector("h3", timeout=15000)
        except:
            logger.warning("等待 h3 超时")
            return []

        # 滚动加载更多内容
        self._scroll_to_bottom(for_list_page=True)

        # 提取所有 h3 内的链接
        headlines = self._page.locator("h3 a").all()

        for h in headlines:
            try:
                text = h.inner_text().strip()
                href = h.get_attribute("href")

                if not href or not text or len(text) < 10:
                    continue

                # 补全URL
                if href.startswith('/'):
                    href = f"https://www.wsj.com{href}"

                # 去重
                if href in seen_urls:
                    continue

                # 过滤非文章链接
                if not self._is_article_url(href):
                    continue

                seen_urls.add(href)

                # 清理标题中的 EXCLUSIVE 前缀（如有）
                title = text
                if text.upper().startswith("EXCLUSIVE"):
                    title = re.sub(r'^EXCLUSIVE\s*\n?\s*', '', text, flags=re.IGNORECASE)
                elif text.upper().startswith("EXCL:"):
                    title = re.sub(r'^EXCL:\s*', '', text, flags=re.IGNORECASE)

                articles.append(ArticleLink(
                    title=title.strip(),
                    url=href,
                    is_exclusive=False,  # 详情页判断
                    priority=1
                ))

            except Exception as e:
                continue

        logger.info(f"找到 {len(articles)} 篇文章")

        return articles

    def _is_article_url(self, url: str) -> bool:
        """检查是否是文章URL"""
        # 必须是 WSJ 域名
        parsed = urlparse(url)
        if parsed.netloc and not parsed.netloc.endswith('wsj.com'):
            return False

        # 排除非文章页面
        exclude_patterns = ['/video/', '/livecoverage/', '/podcasts/', '/buyside/', '/coupons/']
        for pattern in exclude_patterns:
            if pattern in url.lower():
                return False

        # 必须包含文章路径特征
        article_patterns = [
            '/articles/', '/politics/', '/finance/', '/tech/',
            '/business/', '/world/', '/economy/', '/markets/',
            '/us-news/', '/opinion/', '/lifestyle/', '/arts-culture/'
        ]
        return any(p in url.lower() for p in article_patterns)

    def _scrape_article(self, link: ArticleLink, category: str) -> Optional[Article]:
        """爬取单篇文章"""
        logger.info(f"  爬取: {link.title[:50]}...")

        try:
            # 导航到文章页
            self._page.goto(link.url, wait_until="domcontentloaded", timeout=60000)

            # 等待网络空闲
            try:
                self._page.wait_for_load_state("networkidle", timeout=30000)
            except:
                pass

            # 等待文章元素
            try:
                self._page.wait_for_selector("article", timeout=15000)
            except:
                logger.warning("    未找到 article 元素")

            # 滚动加载完整正文
            self._scroll_to_bottom(for_list_page=False)

            # 提取内容
            data = self._page.evaluate("""
                () => {
                    const result = {
                        title: '',
                        subtitle: '',
                        author: '',
                        published_at: '',
                        content: '',
                        is_exclusive: false
                    };

                    // 检测 EXCLUSIVE 标记 (详情页)
                    // 方法1: 检查页面文本中是否有 EXCLUSIVE 标签
                    const exclusiveEl = document.querySelector('[class*="exclusive" i], [class*="Exclusive" i], [data-type="exclusive"]');
                    if (exclusiveEl) {
                        result.is_exclusive = true;
                    }
                    // 方法2: 检查标题前是否有 EXCLUSIVE 文字
                    const headlineContainer = document.querySelector('[data-testid="headline-container"]') || document.querySelector('header');
                    if (headlineContainer) {
                        const text = headlineContainer.innerText.toUpperCase();
                        if (text.includes('EXCLUSIVE') || text.includes('EXCL:')) {
                            result.is_exclusive = true;
                        }
                    }

                    // 标题 - 兼容两种布局
                    const headline = document.querySelector('[data-testid="headline"]') || document.querySelector('h1');
                    if (headline) result.title = headline.innerText.trim();

                    // 副标题
                    const dek = document.querySelector('[data-testid="dek-block"]');
                    if (dek) result.subtitle = dek.innerText.trim();

                    // 作者
                    const byline = document.querySelector('[data-testid="byline"]');
                    if (byline) {
                        result.author = byline.innerText.replace(/^By\\s+/i, '').trim();
                    }

                    // 时间
                    const timeEl = document.querySelector('[data-testid="timestamp-text"]') || document.querySelector('time');
                    if (timeEl) {
                        result.published_at = timeEl.innerText.trim();
                    }

                    // 正文提取 - 兼容三种布局
                    let texts = [];

                    // 方法1: data-testid="paragraph"
                    let paragraphs = document.querySelectorAll('[data-testid="paragraph"]');
                    paragraphs.forEach(p => {
                        const text = p.innerText.trim();
                        if (text.length > 20 && !text.includes('Advertisement')) {
                            texts.push(text);
                        }
                    });

                    // 方法2: 如果太少，尝试 data-type="paragraph"
                    if (texts.length <= 2) {
                        texts = [];
                        paragraphs = document.querySelectorAll('p[data-type="paragraph"]');
                        paragraphs.forEach(p => {
                            const text = p.innerText.trim();
                            if (text.length > 20 && !text.includes('Advertisement')) {
                                texts.push(text);
                            }
                        });
                    }

                    // 方法3: fallback 到 article.wsj-article p 或 article p (交互式文章)
                    if (texts.length <= 2) {
                        texts = [];
                        // 优先 wsj-article，否则用第一个 article
                        const article = document.querySelector('article.wsj-article') || document.querySelector('article');
                        if (article) {
                            article.querySelectorAll('p').forEach(p => {
                                const text = p.innerText.trim();
                                // 过滤：长度>30，不含广告/版权/邮箱提示
                                if (text.length > 30 &&
                                    !text.includes('Advertisement') &&
                                    !text.includes('copyright') &&
                                    !text.includes('Subscriber Agreement') &&
                                    !text.startsWith('Write to ')) {
                                    texts.push(text);
                                }
                            });
                        }
                    }

                    result.content = texts.join('\\n\\n');

                    return result;
                }
            """)

            # 验证内容
            if not data['content'] or len(data['content']) < 100:
                logger.warning(f"    内容过短或为空: {len(data.get('content', ''))}")
                return None

            # 使用链接中的标题（如果页面标题为空）
            title = data['title'] or link.title

            # EXCLUSIVE 从详情页判断
            is_exclusive = data.get('is_exclusive', False)
            if is_exclusive:
                logger.info("    [EXCLUSIVE] 独家报道")

            return Article(
                title=title,
                url=normalize_url(link.url),  # 清理URL参数
                content=data['content'],
                author=data['author'] or None,
                published_at=data['published_at'] or None,
                subtitle=data['subtitle'] or None,
                category=category,
                is_exclusive=is_exclusive,
            )

        except Exception as e:
            logger.error(f"    爬取失败: {e}")
            return None

    def _save_article(self, article: Article) -> Path:
        """保存文章到 JSON 文件"""
        # 目录结构: articles/category/date/article.json
        date_str = datetime.now().strftime("%Y-%m-%d")
        category_dir = ARTICLES_DIR / (article.category or "uncategorized") / date_str
        category_dir.mkdir(parents=True, exist_ok=True)

        filename = article.generate_filename()
        filepath = category_dir / filename

        # 避免文件名冲突
        if filepath.exists():
            base = filepath.stem
            for i in range(1, 100):
                filepath = category_dir / f"{base}_{i}.json"
                if not filepath.exists():
                    break

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(article.to_dict(), f, ensure_ascii=False, indent=2)

        return filepath

    def crawl_page(self, category: str, url: str) -> list[Article]:
        """爬取单个分类页面"""
        logger.info(f"\n{'='*60}")
        logger.info(f"爬取分类: {category.upper()}")
        logger.info(f"URL: {url}")
        logger.info(f"{'='*60}")

        # 导航到列表页，等待完全加载
        logger.info("  等待页面加载...")
        self._page.goto(url, wait_until="load", timeout=90000)

        # 等待网络空闲
        try:
            self._page.wait_for_load_state("networkidle", timeout=30000)
        except:
            logger.warning("  networkidle 超时，继续...")

        # 等待文章标题出现
        try:
            self._page.wait_for_selector("h3", timeout=15000)
        except:
            logger.warning("  等待 h3 超时")

        # 额外等待确保页面渲染完成
        self._page.wait_for_timeout(3000)
        logger.info("  页面加载完成")

        # 提取文章链接
        links = self._extract_article_links(category)

        # 过滤已爬取的（基于URL去重，去掉参数比对）
        new_links = [l for l in links if self._normalize_url(l.url) not in self._crawled_urls]
        logger.info(f"新文章: {len(new_links)}/{len(links)}")

        # 限制数量 (首页允许更多)
        max_articles = MAX_ARTICLES_HOME if category == "home" else MAX_ARTICLES_PER_PAGE
        links_to_crawl = new_links[:max_articles]

        # 爬取每篇文章
        articles = []
        for i, link in enumerate(links_to_crawl, 1):
            logger.info(f"\n[{i}/{len(links_to_crawl)}] {link.title[:40]}...")

            article = self._scrape_article(link, category)

            if article and article.content:
                articles.append(article)

                # 保存文章
                filepath = self._save_article(article)
                logger.info(f"    保存: {filepath.name}")

                # 记录已爬取并立即保存（避免中断时丢失进度）
                self._crawled_urls.add(self._normalize_url(link.url))
                self._save_crawled_urls()

            # 随机间隔
            if i < len(links_to_crawl):
                wait = random.uniform(2.0, 4.0)
                self._page.wait_for_timeout(int(wait * 1000))

        logger.info(f"\n{category} 完成: {len(articles)}/{len(links_to_crawl)} 篇成功")
        return articles

    def crawl_all(self) -> dict[str, list[Article]]:
        """爬取所有配置的页面"""
        if not self.connect():
            return {}

        results = {}

        try:
            for category, url in PAGES_TO_CRAWL.items():
                articles = self.crawl_page(category, url)
                results[category] = articles

                # 保存已爬取URL
                self._save_crawled_urls()

                # 分类间隔
                if category != list(PAGES_TO_CRAWL.keys())[-1]:
                    wait = random.uniform(3.0, 5.0)
                    logger.info(f"\n等待 {wait:.1f} 秒后继续...")
                    self._page.wait_for_timeout(int(wait * 1000))

            return results

        finally:
            self._save_crawled_urls()
            self.disconnect()

    def crawl_single(self, category: str) -> list[Article]:
        """爬取单个分类"""
        if category not in PAGES_TO_CRAWL:
            logger.error(f"未知分类: {category}")
            logger.info(f"可用分类: {list(PAGES_TO_CRAWL.keys())}")
            return []

        if not self.connect():
            return []

        try:
            articles = self.crawl_page(category, PAGES_TO_CRAWL[category])
            return articles
        finally:
            self._save_crawled_urls()
            self.disconnect()

    def crawl_url(self, url: str, category: Optional[str] = None) -> Optional[Article]:
        """
        爬取单个 URL

        Args:
            url: 文章 URL
            category: 文章分类 (可选，会尝试从 URL 自动推断)

        Returns:
            Article: 爬取的文章，失败返回 None
        """
        # 标准化 URL
        normalized_url = self._normalize_url(url)

        # 检查是否已爬取
        if normalized_url in self._crawled_urls:
            logger.warning(f"URL 已爬取过: {url}")
            # 仍然继续爬取，但会提示

        # 自动推断分类
        if not category:
            category = self._infer_category_from_url(url)
            logger.info(f"自动推断分类: {category}")

        if not self.connect():
            return None

        try:
            # 创建 ArticleLink
            link = ArticleLink(
                title="",  # 会从页面获取
                url=url,
                is_exclusive=False,
                priority=1,
            )

            # 爬取文章
            article = self._scrape_article(link, category)

            if article and article.content:
                # 保存文章
                filepath = self._save_article(article)
                logger.info(f"保存: {filepath}")

                # 记录已爬取
                self._crawled_urls.add(normalized_url)
                self._save_crawled_urls()

                return article
            else:
                logger.error(f"爬取失败或内容为空: {url}")
                return None

        finally:
            self.disconnect()

    def _infer_category_from_url(self, url: str) -> str:
        """从 URL 推断文章分类"""
        url_lower = url.lower()

        category_patterns = {
            "tech": ["/tech/", "/technology/"],
            "finance": ["/finance/", "/markets/"],
            "business": ["/business/"],
            "politics": ["/politics/"],
            "economy": ["/economy/"],
            "world": ["/world/"],
            "china": ["/china/"],
        }

        for category, patterns in category_patterns.items():
            for pattern in patterns:
                if pattern in url_lower:
                    return category

        return "uncategorized"


# ============== 主函数 ==============

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(
        description="WSJ 爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.crawler.wsj_crawler tech          # 爬取 tech 分类
  python -m src.crawler.wsj_crawler all           # 爬取所有分类
  python -m src.crawler.wsj_crawler --url <url>   # 爬取单个 URL
  python -m src.crawler.wsj_crawler --url <url> --category tech
        """,
    )

    parser.add_argument(
        "category",
        nargs="?",
        choices=list(PAGES_TO_CRAWL.keys()) + ["all"],
        help="要爬取的分类 (或 'all' 爬取全部)",
    )

    parser.add_argument(
        "--url", "-u",
        type=str,
        help="爬取单个文章 URL",
    )

    parser.add_argument(
        "--category-for-url", "-c",
        type=str,
        choices=list(PAGES_TO_CRAWL.keys()) + ["uncategorized"],
        help="为 URL 指定分类 (默认自动推断)",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  WSJ 爬虫")
    print("=" * 60)
    print(f"\n输出目录: {ARTICLES_DIR}")
    print(f"浏览器 Profile: {USER_DATA_DIR}")

    # 模式1: 爬取单个 URL
    if args.url:
        print(f"\n[模式] 爬取单个 URL")
        print(f"URL: {args.url}")
        if args.category_for_url:
            print(f"分类: {args.category_for_url}")

        crawler = WSJCrawler()
        article = crawler.crawl_url(args.url, category=args.category_for_url)

        if article:
            print(f"\n{'='*60}")
            print(f"爬取成功!")
            print(f"  标题: {article.title}")
            print(f"  分类: {article.category}")
            print(f"  内容长度: {len(article.content)} 字符")
        else:
            print(f"\n爬取失败")

    # 模式2: 爬取分类
    elif args.category:
        if args.category == "all":
            print(f"\n可用分类: {', '.join(PAGES_TO_CRAWL.keys())}")
            print("\n[模式] 爬取所有分类")
            crawler = WSJCrawler()
            results = crawler.crawl_all()

            # 统计
            total = sum(len(articles) for articles in results.values())
            print(f"\n{'='*60}")
            print(f"爬取完成: 共 {total} 篇文章")
            for cat, articles in results.items():
                print(f"  {cat}: {len(articles)} 篇")
        else:
            print(f"\n[模式] 爬取单个分类: {args.category}")
            crawler = WSJCrawler()
            articles = crawler.crawl_single(args.category)
            print(f"\n完成: {len(articles)} 篇文章")

    # 无参数: 显示帮助
    else:
        print(f"\n可用分类: {', '.join(PAGES_TO_CRAWL.keys())}")
        parser.print_help()


if __name__ == "__main__":
    main()
