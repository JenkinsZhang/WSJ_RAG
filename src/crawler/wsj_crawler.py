"""
WSJ 爬虫

功能：
1. 爬取 WSJ 多个分类页面的文章
2. EXCLUSIVE 文章优先爬取
3. 人类化滚动加载（随机等待）
4. 输出 JSON 格式，按 category/date/article.json 组织
5. 避免重复爬取
6. CAPTCHA 检测 + 暂停等待手动验证

使用方法：
    python -m src.crawler.wsj_crawler
"""

import hashlib
import json
import logging
import random
import re
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import Page

from src.crawler.browser import BrowserManager
from src.utils.url import normalize_url

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============== 配置 ==============

PROJECT_ROOT = Path(__file__).parent.parent.parent
ARTICLES_DIR = PROJECT_ROOT / "articles"
CRAWLED_URLS_FILE = PROJECT_ROOT / "data" / "crawled_urls.json"

PAGES_TO_CRAWL = {
    "home": "https://www.wsj.com/",
    "world": "https://www.wsj.com/world",
    "china": "https://www.wsj.com/world/china",
    "tech": "https://www.wsj.com/tech",
    "finance": "https://www.wsj.com/finance",
    "business": "https://www.wsj.com/business",
    "politics": "https://www.wsj.com/politics",
    "economy": "https://www.wsj.com/economy",
    "opinion": "https://www.wsj.com/opinion",
    "arts": "https://www.wsj.com/arts-culture",
    "lifestyle": "https://www.wsj.com/lifestyle",
    "real-estate": "https://www.wsj.com/real-estate",
    "personal-finance": "https://www.wsj.com/personal-finance",
    "health": "https://www.wsj.com/health",
    "style": "https://www.wsj.com/style",
    "sports": "https://www.wsj.com/sports",
    "us-news": "https://www.wsj.com/us-news",
}

ARCHIVE_URL_TEMPLATE = "https://www.wsj.com/news/archive/{year}/{month:02d}/{day:02d}"
BACKFILL_MAX_DAYS = 30

MAX_ARTICLES_PER_PAGE = 50
MAX_ARTICLES_HOME = 100

# CAPTCHA 等待配置
CAPTCHA_AUTO_WAIT = 15  # 自动解决型等待秒数
CAPTCHA_POLL_INTERVAL = 5  # 手动验证轮询间隔秒数
CAPTCHA_MAX_WAIT = 300  # 最长等待秒数 (5分钟)

# 非文章 URL 路径黑名单
_EXCLUDE_URL_PATTERNS = [
    "/video/",
    "/livecoverage/",
    "/podcasts/",
    "/buyside/",
    "/coupons/",
    "/news/types/",
    "/news/author/",
    "/puzzles/",
    "/audio/",
    "/print-edition/",
    "/digital-print-edition",
    "/client/",
    "/market-data/",
]

# 文章内容提取 JS
_EXTRACT_ARTICLE_JS = """() => {
    const result = {
        title: '', subtitle: '', author: '', published_at: '',
        content: '', is_exclusive: false
    };

    // EXCLUSIVE 检测
    const exNav = document.querySelector('[aria-label*="exclusive" i]');
    if (exNav) result.is_exclusive = true;
    if (!result.is_exclusive) {
        document.querySelectorAll(
            '[data-testid="content-tag"], [data-testid="content-tag-flashline"]'
        ).forEach(tag => {
            if (tag.innerText.toLowerCase().includes('exclusive'))
                result.is_exclusive = true;
        });
    }
    if (!result.is_exclusive) {
        const bc = document.querySelector('nav.breadcrumb, [class*="breadcrumb"]');
        if (bc && bc.innerText.toLowerCase().includes('exclusive'))
            result.is_exclusive = true;
    }

    // 元数据
    const headline = document.querySelector('[data-testid="headline"]')
                  || document.querySelector('h1');
    if (headline) result.title = headline.innerText.trim();

    const dek = document.querySelector('[data-testid="dek-block"]');
    if (dek) result.subtitle = dek.innerText.trim();

    const byline = document.querySelector('[data-testid="byline"]');
    if (byline) result.author = byline.innerText.replace(/^By\\s+/i, '').trim();

    const timeEl = document.querySelector('[data-testid="timestamp-text"]')
                || document.querySelector('time');
    if (timeEl) result.published_at = timeEl.innerText.trim();

    // 正文提取 (三种布局 fallback)
    const isGoodParagraph = (text, minLen) =>
        text.length > minLen && !text.includes('Advertisement');

    let texts = [];

    // 方法1: data-testid="paragraph" (新版布局)
    document.querySelectorAll('[data-testid="paragraph"]').forEach(p => {
        const t = p.innerText.trim();
        if (isGoodParagraph(t, 20)) texts.push(t);
    });

    // 方法2: data-type="paragraph" (主流布局)
    if (texts.length <= 2) {
        texts = [];
        document.querySelectorAll('p[data-type="paragraph"]').forEach(p => {
            const t = p.innerText.trim();
            if (isGoodParagraph(t, 20)) texts.push(t);
        });
    }

    // 方法3: article p (兜底)
    if (texts.length <= 2) {
        texts = [];
        const article = document.querySelector('article.wsj-article')
                     || document.querySelector('article');
        if (article) {
            article.querySelectorAll('p').forEach(p => {
                const t = p.innerText.trim();
                if (t.length > 30
                    && !t.includes('Advertisement')
                    && !t.includes('copyright')
                    && !t.includes('Subscriber Agreement')
                    && !t.startsWith('Write to ')) {
                    texts.push(t);
                }
            });
        }
    }

    result.content = texts.join('\\n\\n');
    return result;
}"""

# URL 路径 → 分类映射 (顺序重要：子路径在前)
_URL_CATEGORY_RULES = [
    ("/world/china", "china"),
    ("/china/", "china"),
    ("/world/asia", "asia"),
    ("/asia/", "asia"),
    ("/tech/", "tech"),
    ("/technology/", "tech"),
    ("/world/", "world"),
    ("/finance/", "finance"),
    ("/markets/", "finance"),
    ("/business/", "business"),
    ("/politics/", "politics"),
    ("/economy/", "economy"),
    ("/arts-culture/", "arts"),
    ("/arts/", "arts"),
    ("/culture/", "arts"),
    ("/lifestyle/", "lifestyle"),
    ("/opinion/", "opinion"),
    ("/us-news/", "us"),
    ("/personal-finance/", "personal-finance"),
    ("/sports/", "sports"),
    ("/real-estate/", "real-estate"),
    ("/health/", "health"),
    ("/style/", "style"),
    ("/free-expression/", "free-expression"),
    ("/articles/", "miscellaneous"),
]


# ============== 数据结构 ==============


@dataclass
class ArticleLink:
    """文章链接信息"""

    title: str
    url: str
    is_exclusive: bool = False
    priority: int = 1  # 0=EXCLUSIVE, 1=普通


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
        clean_url = normalize_url(self.url)
        return hashlib.md5(clean_url.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)

    def generate_filename(self) -> str:
        path = urlparse(self.url).path
        slug = path.rstrip("/").split("/")[-1]
        slug = re.sub(r"[^\w\-]", "", slug)
        if len(slug) > 80:
            slug = slug[:80]
        return f"{slug}.json"


# ============== 爬虫核心 ==============


class WSJCrawler:
    """WSJ 爬虫"""

    def __init__(self):
        self._browser = BrowserManager()
        self._page: Optional[Page] = None
        self._crawled_urls: set[str] = set()
        self._load_crawled_urls()

    # ---------- 浏览器生命周期 ----------

    def connect(self) -> bool:
        try:
            self._browser.start()
            self._page = self._browser.get_page()
            return True
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            return False

    def disconnect(self):
        self._browser.close()
        self._page = None

    # ---------- CAPTCHA 检测 ----------

    def _is_captcha_page(self) -> bool:
        """检测当前页面是否为 CAPTCHA 验证页"""
        try:
            title = self._page.title()
            return title.strip().lower() == "wsj.com"
        except Exception:
            return False

    def _wait_for_captcha(self, context: str = "") -> bool:
        """
        等待 CAPTCHA 验证通过。

        Returns:
            True: 验证通过或无 CAPTCHA
            False: 等待超时
        """
        if not self._is_captcha_page():
            return True

        # 先等待自动解决型 CAPTCHA
        logger.warning(f"  [CAPTCHA] 检测到验证页面{f' ({context})' if context else ''}")
        logger.info(f"  [CAPTCHA] 等待 {CAPTCHA_AUTO_WAIT}s（可能自动通过）...")
        self._page.wait_for_timeout(CAPTCHA_AUTO_WAIT * 1000)

        if not self._is_captcha_page():
            logger.info("  [CAPTCHA] 自动验证通过!")
            return True

        # 需要手动验证
        print("\n" + "!" * 60)
        print("  [CAPTCHA] 需要手动验证！请在浏览器中完成滑块验证")
        print("  等待中... (最长等待 5 分钟)")
        print("!" * 60 + "\n")

        waited = CAPTCHA_AUTO_WAIT
        while waited < CAPTCHA_MAX_WAIT:
            self._page.wait_for_timeout(CAPTCHA_POLL_INTERVAL * 1000)
            waited += CAPTCHA_POLL_INTERVAL

            if not self._is_captcha_page():
                logger.info(f"  [CAPTCHA] 验证通过! (等待了 {waited}s)")
                # 额外等待页面渲染
                self._page.wait_for_timeout(3000)
                return True

        logger.error(f"  [CAPTCHA] 等待超时 ({CAPTCHA_MAX_WAIT}s)，跳过")
        return False

    # ---------- URL 管理 ----------

    def _load_crawled_urls(self):
        if CRAWLED_URLS_FILE.exists():
            try:
                with open(CRAWLED_URLS_FILE, "r", encoding="utf-8") as f:
                    urls = json.load(f)
                    self._crawled_urls = {normalize_url(u) for u in urls}
                logger.info(f"已加载 {len(self._crawled_urls)} 个已爬取URL")
            except Exception as e:
                logger.warning(f"加载已爬取URL失败: {e}")

    def _save_crawled_urls(self):
        CRAWLED_URLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CRAWLED_URLS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(self._crawled_urls), f, ensure_ascii=False, indent=2)

    # ---------- 页面操作 ----------

    def _scroll_to_bottom(self, for_list_page: bool = True, max_scrolls: int = 15):
        """滚动到页面底部，加载懒加载内容"""
        if for_list_page:
            last_value = len(self._page.locator("h3").all())
            logger.info(f"  开始滚动，当前 h3: {last_value}")
        else:
            last_value = self._page.evaluate("document.body.scrollHeight")

        stable_count = 0
        scroll_count = 0

        while stable_count < 2 and scroll_count < max_scrolls:
            self._page.evaluate(
                "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})"
            )
            scroll_count += 1
            self._page.wait_for_timeout(3000)

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

    # ---------- URL 过滤 ----------

    @staticmethod
    def _is_article_url(url: str) -> bool:
        """检查是否是文章 URL（黑名单模式）"""
        parsed = urlparse(url)

        # 必须是 WSJ 域名
        if parsed.netloc and not parsed.netloc.endswith("wsj.com"):
            return False

        url_lower = url.lower()

        # 排除已知非文章路径
        for pattern in _EXCLUDE_URL_PATTERNS:
            if pattern in url_lower:
                return False

        # URL path 至少有 2 段（排除纯分类首页如 /tech）
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(path_parts) < 2:
            return False

        return True

    @staticmethod
    def _infer_category_from_url(url: str) -> str:
        """从 URL 推断文章分类"""
        url_lower = url.lower()
        for pattern, category in _URL_CATEGORY_RULES:
            if pattern in url_lower:
                return category
        return "uncategorized"

    # ---------- 链接提取 ----------

    def _extract_article_links(self, category: str) -> list[ArticleLink]:
        """从列表页提取文章链接"""
        articles = []
        seen_urls = set()

        try:
            self._page.wait_for_selector("h3", timeout=15000)
        except Exception:
            logger.warning("等待 h3 超时")
            return []

        self._scroll_to_bottom(for_list_page=True)

        for h in self._page.locator("h3 a").all():
            try:
                text = h.inner_text().strip()
                href = h.get_attribute("href")

                if not href or not text or len(text) < 10:
                    continue

                if href.startswith("/"):
                    href = f"https://www.wsj.com{href}"

                # 用标准化 URL 去重
                normalized = normalize_url(href)
                if normalized in seen_urls:
                    continue

                if not self._is_article_url(href):
                    continue

                seen_urls.add(normalized)

                # 检测 EXCLUSIVE 前缀
                is_exclusive = False
                title = text
                if text.upper().startswith("EXCLUSIVE"):
                    is_exclusive = True
                    title = re.sub(
                        r"^EXCLUSIVE\s*\n?\s*", "", text, flags=re.IGNORECASE
                    )
                elif text.upper().startswith("EXCL:"):
                    is_exclusive = True
                    title = re.sub(r"^EXCL:\s*", "", text, flags=re.IGNORECASE)

                articles.append(
                    ArticleLink(
                        title=title.strip(),
                        url=href,
                        is_exclusive=is_exclusive,
                        priority=0 if is_exclusive else 1,
                    )
                )
            except Exception:
                continue

        articles.sort(key=lambda x: x.priority)

        exclusive_count = sum(1 for a in articles if a.is_exclusive)
        logger.info(f"找到 {len(articles)} 篇文章 (列表页EXCLUSIVE: {exclusive_count})")

        return articles

    # ---------- 文章爬取 ----------

    def _scrape_article(self, link: ArticleLink, category: str) -> Optional[Article]:
        """爬取单篇文章"""
        logger.info(f"  爬取: {link.title[:50]}...")

        try:
            self._page.goto(link.url, wait_until="domcontentloaded", timeout=20000)

            try:
                self._page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            # CAPTCHA 检测
            if not self._wait_for_captcha(context=link.title[:30]):
                return None

            try:
                self._page.wait_for_selector("article", timeout=10000)
            except Exception:
                logger.warning("    未找到 article 元素")

            self._scroll_to_bottom(for_list_page=False)

            data = self._page.evaluate(_EXTRACT_ARTICLE_JS)

            if not data["content"] or len(data["content"]) < 100:
                logger.warning(f"    内容过短或为空: {len(data.get('content', ''))}")
                return None

            title = data["title"] or link.title

            is_exclusive = link.is_exclusive or data.get("is_exclusive", False)
            if is_exclusive and not link.is_exclusive:
                logger.info("    [EXCLUSIVE] 详情页检测到独家报道")
            elif is_exclusive:
                logger.info("    [EXCLUSIVE] 独家报道")

            article_url = normalize_url(link.url)
            inferred_category = self._infer_category_from_url(article_url)
            logger.info(f"    分类: {inferred_category}")

            return Article(
                title=title,
                url=article_url,
                content=data["content"],
                author=data["author"] or None,
                published_at=data["published_at"] or None,
                subtitle=data["subtitle"] or None,
                category=inferred_category,
                is_exclusive=is_exclusive,
            )

        except Exception as e:
            logger.error(f"    爬取失败: {e}")
            return None

    # ---------- 文章保存 ----------

    @staticmethod
    def _save_article(article: Article) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        category_dir = ARTICLES_DIR / (article.category or "uncategorized") / date_str
        category_dir.mkdir(parents=True, exist_ok=True)

        filename = article.generate_filename()
        filepath = category_dir / filename

        if filepath.exists():
            base = filepath.stem
            for i in range(1, 100):
                filepath = category_dir / f"{base}_{i}.json"
                if not filepath.exists():
                    break

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article.to_dict(), f, ensure_ascii=False, indent=2)

        return filepath

    # ---------- 爬取入口 ----------

    def crawl_page(self, category: str, url: str) -> list[Article]:
        """爬取单个分类页面"""
        logger.info(f"\n{'='*60}")
        logger.info(f"爬取分类: {category.upper()}")
        logger.info(f"URL: {url}")
        logger.info(f"{'='*60}")

        logger.info("  等待页面加载...")
        self._page.goto(url, wait_until="load", timeout=90000)

        try:
            self._page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            logger.warning("  networkidle 超时，继续...")

        # CAPTCHA 检测
        if not self._wait_for_captcha(context=category):
            logger.error(f"  {category} 页面 CAPTCHA 超时，跳过该分类")
            return []

        try:
            self._page.wait_for_selector("h3", timeout=15000)
        except Exception:
            logger.warning("  等待 h3 超时")

        self._page.wait_for_timeout(3000)
        logger.info("  页面加载完成")

        links = self._extract_article_links(category)

        new_links = [
            l for l in links if normalize_url(l.url) not in self._crawled_urls
        ]
        logger.info(f"新文章: {len(new_links)}/{len(links)}")

        max_articles = (
            MAX_ARTICLES_HOME if category == "home" else MAX_ARTICLES_PER_PAGE
        )
        links_to_crawl = new_links[:max_articles]

        articles = []
        for i, link in enumerate(links_to_crawl, 1):
            exclusive_tag = "[EXCLUSIVE] " if link.is_exclusive else ""
            logger.info(
                f"\n[{i}/{len(links_to_crawl)}] {exclusive_tag}{link.title[:40]}..."
            )

            article = self._scrape_article(link, category)

            if article and article.content:
                articles.append(article)

                filepath = self._save_article(article)
                logger.info(f"    保存: {filepath.name}")

                self._crawled_urls.add(normalize_url(link.url))
                self._save_crawled_urls()

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
        categories = list(PAGES_TO_CRAWL.items())

        try:
            for i, (category, url) in enumerate(categories):
                articles = self.crawl_page(category, url)
                results[category] = articles
                self._save_crawled_urls()

                if i < len(categories) - 1:
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
            return self.crawl_page(category, PAGES_TO_CRAWL[category])
        finally:
            self._save_crawled_urls()
            self.disconnect()

    # ---------- Archive 补全 ----------

    @staticmethod
    def _save_article_for_date(article: Article, target_date: date) -> Path:
        """保存文章到指定日期的目录（用于 Archive 补全）"""
        date_str = target_date.isoformat()
        category_dir = ARTICLES_DIR / (article.category or "uncategorized") / date_str
        category_dir.mkdir(parents=True, exist_ok=True)

        filename = article.generate_filename()
        filepath = category_dir / filename

        if filepath.exists():
            base = filepath.stem
            for i in range(1, 100):
                filepath = category_dir / f"{base}_{i}.json"
                if not filepath.exists():
                    break

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article.to_dict(), f, ensure_ascii=False, indent=2)

        return filepath

    def crawl_archive_day(self, target_date: date) -> list[Article]:
        """爬取指定日期的 Archive 页面"""
        url = ARCHIVE_URL_TEMPLATE.format(
            year=target_date.year, month=target_date.month, day=target_date.day
        )

        logger.info(f"\n{'='*60}")
        logger.info(f"Archive 补全: {target_date.isoformat()}")
        logger.info(f"URL: {url}")
        logger.info(f"{'='*60}")

        self._page.goto(url, wait_until="load", timeout=90000)

        try:
            self._page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            logger.warning("  networkidle 超时，继续...")

        if not self._wait_for_captcha(context=f"archive {target_date}"):
            logger.error(f"  Archive {target_date} CAPTCHA 超时，跳过")
            return []

        # Archive 页面无需滚动，直接提取 h3 a
        try:
            self._page.wait_for_selector("h3", timeout=15000)
        except Exception:
            logger.warning(f"  {target_date} 无文章")
            return []

        self._page.wait_for_timeout(2000)

        # 提取链接
        links = []
        seen_urls = set()
        for h in self._page.locator("h3 a").all():
            try:
                text = h.inner_text().strip()
                href = h.get_attribute("href")
                if not href or not text or len(text) < 10:
                    continue
                if href.startswith("/"):
                    href = f"https://www.wsj.com{href}"

                normalized = normalize_url(href)
                if normalized in seen_urls or normalized in self._crawled_urls:
                    continue
                if not self._is_article_url(href):
                    continue

                seen_urls.add(normalized)
                links.append(ArticleLink(title=text.strip(), url=href))
            except Exception:
                continue

        logger.info(f"  找到 {len(links)} 篇新文章")

        # 逐一爬取
        articles = []
        for i, link in enumerate(links, 1):
            logger.info(f"\n  [{i}/{len(links)}] {link.title[:50]}...")

            article = self._scrape_article(link, "archive")
            if article and article.content:
                articles.append(article)
                filepath = self._save_article_for_date(article, target_date)
                logger.info(f"    保存: {filepath.name}")

                self._crawled_urls.add(normalize_url(link.url))
                self._save_crawled_urls()

            if i < len(links):
                wait = random.uniform(2.0, 4.0)
                self._page.wait_for_timeout(int(wait * 1000))

        logger.info(f"\n  {target_date} 完成: {len(articles)}/{len(links)} 篇")
        return articles

    @staticmethod
    def _find_missing_dates(max_days: int = BACKFILL_MAX_DAYS) -> list[date]:
        """扫描 articles/ 目录，找出缺失的日期"""
        existing_dates: set[date] = set()

        if ARTICLES_DIR.exists():
            for category_dir in ARTICLES_DIR.iterdir():
                if not category_dir.is_dir():
                    continue
                for date_dir in category_dir.iterdir():
                    if not date_dir.is_dir():
                        continue
                    try:
                        existing_dates.add(date.fromisoformat(date_dir.name))
                    except ValueError:
                        continue

        if not existing_dates:
            logger.info("没有已有数据，无法计算缺失日期")
            return []

        earliest = max(min(existing_dates), date.today() - timedelta(days=max_days))
        latest = date.today()

        all_dates = set()
        current = earliest
        while current <= latest:
            all_dates.add(current)
            current += timedelta(days=1)

        missing = sorted(all_dates - existing_dates, reverse=True)
        return missing

    def backfill(self, max_days: int = BACKFILL_MAX_DAYS) -> dict:
        """智能补全缺失日期的文章"""
        missing = self._find_missing_dates(max_days)

        if not missing:
            logger.info("没有缺失日期，数据已完整!")
            return {"missing_days": 0, "total_articles": 0}

        logger.info(f"发现 {len(missing)} 个缺失日期 (最远回溯 {max_days} 天)")
        for d in missing[:10]:
            logger.info(f"  - {d.isoformat()}")
        if len(missing) > 10:
            logger.info(f"  ... 还有 {len(missing) - 10} 天")

        if not self.connect():
            return {"missing_days": len(missing), "total_articles": 0}

        total_articles = 0
        results_by_date = {}

        try:
            for i, target_date in enumerate(missing):
                articles = self.crawl_archive_day(target_date)
                results_by_date[target_date.isoformat()] = len(articles)
                total_articles += len(articles)

                if i < len(missing) - 1:
                    wait = random.uniform(3.0, 5.0)
                    logger.info(f"\n等待 {wait:.1f}s...")
                    self._page.wait_for_timeout(int(wait * 1000))

            return {
                "missing_days": len(missing),
                "total_articles": total_articles,
                "by_date": results_by_date,
            }
        finally:
            self._save_crawled_urls()
            self.disconnect()

    def crawl_archive_date(self, target_date: date) -> list[Article]:
        """爬取单个指定日期的 Archive"""
        if not self.connect():
            return []
        try:
            return self.crawl_archive_day(target_date)
        finally:
            self._save_crawled_urls()
            self.disconnect()

    def crawl_url(self, url: str, category: Optional[str] = None) -> Optional[Article]:
        """爬取单个 URL"""
        normalized_url = normalize_url(url)

        if normalized_url in self._crawled_urls:
            logger.warning(f"URL 已爬取过: {url}")

        if not category:
            category = self._infer_category_from_url(url)
            logger.info(f"自动推断分类: {category}")

        if not self.connect():
            return None

        try:
            link = ArticleLink(title="", url=url)
            article = self._scrape_article(link, category)

            if article and article.content:
                filepath = self._save_article(article)
                logger.info(f"保存: {filepath}")

                self._crawled_urls.add(normalized_url)
                self._save_crawled_urls()
                return article

            logger.error(f"爬取失败或内容为空: {url}")
            return None
        finally:
            self.disconnect()


# ============== 主函数 ==============


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="WSJ 爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.crawler.wsj_crawler tech              # 爬取 tech 分类
  python -m src.crawler.wsj_crawler all               # 爬取所有分类
  python -m src.crawler.wsj_crawler --url <url>       # 爬取单个 URL
  python -m src.crawler.wsj_crawler backfill          # 智能补全缺失日期
  python -m src.crawler.wsj_crawler backfill --max-days 60
  python -m src.crawler.wsj_crawler --archive-date 2026-02-15
        """,
    )

    parser.add_argument(
        "category",
        nargs="?",
        choices=list(PAGES_TO_CRAWL.keys()) + ["all", "backfill"],
        help="分类 / 'all' / 'backfill'",
    )

    parser.add_argument("--url", "-u", type=str, help="爬取单个文章 URL")

    parser.add_argument(
        "--category-for-url", "-c", type=str,
        help="为 URL 指定分类 (默认自动推断)",
    )

    parser.add_argument(
        "--archive-date", type=str,
        help="爬取指定日期的 Archive (格式: YYYY-MM-DD)",
    )

    parser.add_argument(
        "--max-days", type=int, default=BACKFILL_MAX_DAYS,
        help=f"backfill 最大回溯天数 (默认 {BACKFILL_MAX_DAYS})",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  WSJ 爬虫")
    print("=" * 60)
    print(f"\n输出目录: {ARTICLES_DIR}")

    # 模式1: Archive 指定日期
    if args.archive_date:
        try:
            target = date.fromisoformat(args.archive_date)
        except ValueError:
            print(f"日期格式错误: {args.archive_date} (应为 YYYY-MM-DD)")
            return

        print(f"\n[模式] 爬取 Archive: {target}")
        crawler = WSJCrawler()
        articles = crawler.crawl_archive_date(target)
        print(f"\n完成: {len(articles)} 篇文章")

    # 模式2: 单个 URL
    elif args.url:
        print(f"\n[模式] 爬取单个 URL")
        print(f"URL: {args.url}")

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

    # 模式3: backfill / 分类
    elif args.category:
        if args.category == "backfill":
            print(f"\n[模式] 智能补全 (最远 {args.max_days} 天)")
            crawler = WSJCrawler()
            stats = crawler.backfill(max_days=args.max_days)
            print(f"\n{'='*60}")
            print(f"补全完成!")
            print(f"  缺失天数: {stats['missing_days']}")
            print(f"  爬取文章: {stats['total_articles']}")

        elif args.category == "all":
            print(f"\n可用分类: {', '.join(PAGES_TO_CRAWL.keys())}")
            print("\n[模式] 爬取所有分类")
            crawler = WSJCrawler()
            results = crawler.crawl_all()

            total = sum(len(articles) for articles in results.values())
            print(f"\n{'='*60}")
            print(f"爬取完成: 共 {total} 篇文章")
            for cat, articles in results.items():
                if articles:
                    print(f"  {cat}: {len(articles)} 篇")
        else:
            print(f"\n[模式] 爬取单个分类: {args.category}")
            crawler = WSJCrawler()
            articles = crawler.crawl_single(args.category)
            print(f"\n完成: {len(articles)} 篇文章")

    else:
        print(f"\n可用分类: {', '.join(PAGES_TO_CRAWL.keys())}")
        parser.print_help()


if __name__ == "__main__":
    main()
