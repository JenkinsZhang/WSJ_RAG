# WSJ 网站结构分析报告

> 分析日期：2026-01-25
> 用途：为 WSJ RAG 爬虫开发提供参考

---

## 1. 网站概览

### 1.1 页面类型

| 类型 | URL 格式 | 示例 |
|-----|---------|------|
| 首页 | `https://www.wsj.com/` | 主页，包含多个分类区块 |
| 分类页 | `https://www.wsj.com/{category}` | `/world`, `/business`, `/politics` |
| 文章页 | `https://www.wsj.com/{category}/{slug}` | `/world/china/xxx-article-id` |

### 1.2 分类导航

顶部导航栏包含以下分类链接（class: `css-72mltu-SectionLink e15d4pvj3`）：

| 分类 | URL |
|-----|-----|
| World | `https://www.wsj.com/world` |
| Business | `https://www.wsj.com/business` |
| U.S. | `https://www.wsj.com/us-news` |
| Politics | `https://www.wsj.com/politics` |
| Economy | `https://www.wsj.com/economy` |
| Tech | `https://www.wsj.com/tech` |
| Markets & Finance | `https://www.wsj.com/finance` |
| Opinion | `https://www.wsj.com/opinion` |
| Free Expression | `https://www.wsj.com/opinion/free-expression` |
| Arts | `https://www.wsj.com/arts-culture` |
| Lifestyle | `https://www.wsj.com/lifestyle` |
| Real Estate | `https://www.wsj.com/real-estate` |
| Personal Finance | `https://www.wsj.com/personal-finance` |
| Health | `https://www.wsj.com/health` |
| Style | `https://www.wsj.com/style` |
| Sports | `https://www.wsj.com/sports` |

### 1.3 导航栏动态行为 ⚠️ 重要

**当鼠标 hover 到导航分类元素时：**
- 会触发新的 CSS 和 DOM 元素出现
- 子菜单被包裹在 `div[data-testid="column-wrapper"]` 内
- class: `css-iptmaq-ColumnWrapper e15d4pvj11`
- **静态 dump 无法捕获这些动态内容**
- **爬虫中需要使用 `element.hover()` 触发**

```python
# 示例：触发导航菜单展开
nav_item = page.locator('导航元素选择器')
nav_item.hover()
page.wait_for_selector('[data-testid="column-wrapper"]')
# 然后才能获取子分类链接
```

---

## 2. 首页结构分析

### 2.1 基本信息

- **URL**: `https://www.wsj.com/`
- **Title**: "The Wall Street Journal - Breaking News, Business, Financial & Economic News, World News and Video"

### 2.2 标签统计

| 标签 | 数量 | 说明 |
|-----|------|------|
| h1 | 2 | "The Wall Street Journal" (logo) |
| h2 | 16 | 分类区块标题 |
| h3 | 63 | 文章标题 |
| p | 130 | 段落（含摘要、时间等） |
| a | 232 | 链接 |
| div | 1250 | 容器 |

### 2.3 首页分类区块 (h2)

首页包含以下分类区块（class: `e1ohym382 css-*-SectionLabel`）：

- Top Stories
- Columnists
- Travel
- Entertainment
- Business & Finance
- Fashion
- Sports
- World
- Arts & Culture
- WSJ | Buy Side
- Videos
- Opinion
- Most Popular News
- Most Popular
- Journal Reports

### 2.4 首页布局类型 (data-layout-type)

首页使用多种布局，通过 `data-layout-type` 属性区分：

| 布局类型 | 说明 |
|---------|------|
| `medium-topper` | 顶部主打区域 |
| `visual-eleven` | 11篇文章视觉布局 |
| `feature-strip` | 特色横条 |
| `feature-split-a/b/c` | 特色分栏布局 |
| `feature-below-a` | 特色下方区域 |
| `buyside-main` | 买方主区域 |
| `buyside-right-rail` | 买方右侧栏 |
| `weekend-reads` | 周末阅读 |
| `most-popular-news` | 热门新闻 |
| `most-popular-opinion` | 热门观点 |
| `journal-reports` | 期刊报道 |
| `realtor` | 房产 |

---

## 3. 分类页结构分析

WSJ 分类页分为两种类型：
- **顶级分类页** (Section): 如 `/tech`, `/business` - 有特殊布局和 data-testid
- **子分类页** (Subsection): 如 `/world/china` - 更简单的列表布局

### 3.1 分类页对比总览

| 属性 | China (子分类) | Tech (顶级) | Business (顶级) |
|-----|---------------|------------|----------------|
| URL | `/world/china?mod=nav_top_subsection` | `/tech?mod=nav_top_section` | `/business?mod=nav_top_section` |
| Title | "China - Latest News..." | "Technology - WSJ.com" | "Business - WSJ.com" |
| h3 文章数 | **45** | 26 | 26 |
| h2 区块数 | 7 | 4 | 4 |
| nav 导航元素 | 3 | **12** | **11** |
| breadcrumb | **有** | 有 | 有 |

### 3.2 data-testid 对比

| data-testid | China | Tech | Business | 说明 |
|-------------|-------|------|----------|------|
| `flexcard-headline` | 45 | 26 | 26 | 文章标题 |
| `flexcard-text` | 25 | 11 | 10 | 文章摘要 |
| `byline` | 27 | 15 | 15 | 作者容器 |
| `author-link` | 24 | 17 | 16 | 作者链接 |
| `timestamp-text` | 11 | 9 | 9 | 时间戳 |
| `flexcard-readtime` | 30 | 21 | 21 | 阅读时间 |
| `flashline` | **0** | **10** | **9** | 分类标签 ⚠️ |
| `{section}-front-lead-article` | 无 | **1** | **1** | 头条文章 |
| `{section}-front-article` | 无 | **5** | **5** | 重点文章 |
| `content-feed` | 3 | 1 | 1 | 内容流 |
| `tag` | 18 | 8 | 24 | 标签 |

### 3.3 关键发现

#### 3.3.1 顶级分类页特有元素

顶级分类页 (Tech, Business 等) 有特殊的 data-testid：

```python
# 顶级分类页特有选择器
SECTION_SELECTORS = {
    # 头条文章 - 页面最大的文章
    "lead_article": "[data-testid$='-front-lead-article']",

    # 重点文章 - 编辑推荐
    "featured_articles": "[data-testid$='-front-article']",

    # 分类标签 - 如 "TECH", "BUSINESS", "KEYWORDS"
    "flashline": "[data-testid='flashline']",
}
```

#### 3.3.2 子分类页特点

子分类页 (如 China) 特点：
- 没有 `flashline` (因为整页都是同一分类)
- 文章数量更多 (45 vs 26)
- 有面包屑导航 (`breadcrumb-link`)
- 更简单的列表式布局

#### 3.3.3 flashline 分类标签

`[data-testid='flashline']` 显示文章所属分类：

| 示例 | 说明 |
|-----|------|
| `TECH` | 科技文章 |
| `BUSINESS` | 商业文章 |
| `NEWS QUIZ` | 新闻问答 |
| `KEYWORDS` | 关键词专题 |

**注意**: 子分类页 (如 China) 没有 flashline，因为页面本身就是分类筛选结果。

### 3.4 时间戳格式

`[data-testid='timestamp-text']` 显示格式：

| 时间差 | 显示格式 |
|-------|---------|
| < 24小时 | `7 hours ago` |
| 1-7天 | `January 24, 2026` |
| > 7天 | 完整日期 |

### 3.5 URL 参数说明

| 参数 | 含义 |
|-----|------|
| `mod=nav_top_section` | 从顶级导航进入 |
| `mod=nav_top_subsection` | 从子导航进入 |

---

## 4. 关键选择器 (data-testid)

### 4.1 文章卡片选择器

| data-testid | 用途 | 首页数量 | 分类页数量 |
|-------------|------|---------|-----------|
| `flexcard-headline` | 文章标题 | 59 | 26 |
| `flexcard-text` | 文章摘要 | 31 | 11 |
| `flexcard-readtime` | 阅读时间 | 34 | 21 |
| `byline` | 作者容器 | 12 | 15 |
| `author-link` | 作者链接 | 5 | 19 |
| `timestamp-text` | 时间戳 | 1 | 9 |
| `flashline` | 分类标签 (SPORTS/CHINA等) | 2 | 11 |
| `divider` | 分隔线 | 36 | 9 |

### 4.2 其他选择器

| data-testid | 用途 |
|-------------|------|
| `content-tag` | 内容标签 |
| `tag` | 标签 |
| `link-wrapper` | 链接包装器 |
| `buttonLink` | 按钮链接 |
| `follow-button` | 关注按钮 |
| `ad-container` | 广告容器 |
| `video-player` | 视频播放器 |

---

## 5. 文章卡片 DOM 结构

### 5.1 典型文章卡片结构

```html
<div class="...CardLayoutItem">
  <!-- 图片区域 -->
  <div class="...MediaWrapper">
    <a href="文章链接">
      <picture>
        <img src="图片" />
      </picture>
    </a>
  </div>

  <!-- 内容区域 -->
  <div class="...StyledStack">
    <!-- 分类标签 (可选) -->
    <p data-testid="flashline" class="...withBrowserDarkMode">CHINA</p>

    <!-- 标题 -->
    <h3 class="css-fsvegl">
      <a data-testid="flexcard-headline" class="...CardLink" href="文章链接">
        文章标题
      </a>
    </h3>

    <!-- 摘要 -->
    <p data-testid="flexcard-text" class="css-webmz9">
      文章摘要...
    </p>

    <!-- 作者信息 -->
    <div data-testid="byline" class="...BylineContainer">
      <p class="...AuthorPlaintext">By</p>
      <a data-testid="author-link" href="/news/author/xxx">作者名</a>
    </div>

    <!-- 元信息 -->
    <div class="...SupportingMenuBlock">
      <!-- 评论数 -->
      <a class="...CommentsLink" href="...#comments_sector">
        <p class="css-1hro8ak">74</p>
      </a>
      <!-- 时间 -->
      <p data-testid="timestamp-text" class="...TimeTag">7 hours ago</p>
      <!-- 阅读时间 -->
      <p data-testid="flexcard-readtime" class="css-1hro8ak">6 min read</p>
    </div>
  </div>
</div>
```

### 5.2 关键 class 名称

| class 片段 | 用途 |
|-----------|------|
| `css-fsvegl` | h3 标题容器 |
| `css-webmz9` | 摘要文本 |
| `CardLink` | 卡片链接 (如 `css-1rznr30-CardLink`) |
| `BylineContainer` | 作者容器 |
| `AuthorLink` | 作者链接 |
| `AuthorPlaintext` | "By" 等纯文本 |
| `TimeTag` | 时间标签 |
| `SupportingMenuBlock` | 元信息块 |
| `CommentsLink` | 评论链接 |

---

## 6. 文章链接 URL 模式

### 6.1 URL 结构

```
https://www.wsj.com/{category}/{subcategory?}/{slug}-{article_id}?mod={source}
```

### 6.2 示例

| 文章类型 | URL 示例 |
|---------|---------|
| 体育 | `https://www.wsj.com/sports/aonishiki-ukraine-japan-sumo-star-4e845df8` |
| 世界/中国 | `https://www.wsj.com/world/china/chinas-xi-places-his-top-general...-d07f9c7d` |
| 世界/美洲 | `https://www.wsj.com/world/americas/china-venezuela-oil-trump-65ce1da2` |
| 政治 | `https://www.wsj.com/politics/trump-threatens-new-tariffs...` |
| 文章 | `https://www.wsj.com/articles/with-the-fate-of-greenland...-b7b7f552` |

### 6.3 过滤规则

获取文章链接时应排除：
- `/video/` - 视频页面
- `/livecoverage/` - 直播页面
- `/podcasts/` - 播客页面

---

## 7. 爬虫注意事项

### 7.1 EXCLUSIVE 文章优先级 ⭐

**EXCLUSIVE 文章是最高优先级**，需要优先爬取。

#### 识别方式

EXCLUSIVE 文章在标题中有特殊标记：

| 格式 | 示例 |
|-----|------|
| `EXCLUSIVE\n标题` | `"EXCLUSIVE\nThe Best and Worst Airlines of 2025"` |
| `EXCL: 标题` | `"EXCL: Billionaire Ron Burkle Lists..."` |

#### 提取 EXCLUSIVE 文章

```python
import re

def extract_articles_with_priority(page):
    """提取文章列表，EXCLUSIVE 文章排在前面"""
    articles = []
    headlines = page.locator("h3.css-fsvegl a").all()

    for h in headlines:
        text = h.inner_text().strip()
        href = h.get_attribute("href")

        # 检测 EXCLUSIVE 标记
        is_exclusive = False
        title = text

        if text.startswith("EXCLUSIVE\n"):
            is_exclusive = True
            title = text.replace("EXCLUSIVE\n", "")
        elif text.startswith("EXCL:"):
            is_exclusive = True
            title = re.sub(r"^EXCL:\s*", "", text)

        articles.append({
            "title": title,
            "url": href,
            "is_exclusive": is_exclusive,
            "priority": 0 if is_exclusive else 1  # 0 = 最高优先级
        })

    # 按优先级排序，EXCLUSIVE 在前
    return sorted(articles, key=lambda x: x["priority"])
```

### 7.2 页面加载等待策略

#### 列表页 (首页/分类页)

```python
# 1. 导航到页面，等待 DOM 加载
page.goto(url, wait_until="domcontentloaded", timeout=90000)

# 2. 等待网络空闲
page.wait_for_load_state("networkidle", timeout=30000)

# 3. 等待文章标题出现
page.wait_for_selector("h3.css-fsvegl", timeout=20000)

# 4. 额外等待 DOM 渲染
page.wait_for_timeout(1500)
```

#### 文章详情页

```python
# 1. 导航到文章页
page.goto(article_url, wait_until="domcontentloaded", timeout=90000)

# 2. 等待网络空闲
page.wait_for_load_state("networkidle", timeout=30000)

# 3. 等待文章主体元素加载
page.wait_for_selector("article", timeout=20000)

# 4. 等待标题加载 (兼容两种布局)
try:
    page.wait_for_selector("[data-testid='headline'], h1", timeout=10000)
except:
    pass

# 5. 等待正文段落加载
try:
    page.wait_for_selector("[data-testid='paragraph'], p[data-type='paragraph']", timeout=10000)
except:
    pass
```

### 7.3 人类化滚动加载 ⚠️ 重要

**滚动速度必须模拟人类阅读行为**，否则可能触发反爬机制。

#### 关键原则

1. **随机等待时间**: 每次滚动后等待 1~3 秒（模拟阅读）
2. **等待网络空闲**: 确保懒加载内容加载完成
3. **滚动到底部**: 确保正文全部加载
4. **平滑滚动**: 使用 `behavior: 'smooth'` 更自然

```python
import random

def human_like_scroll(page):
    """
    人类化滚动页面，确保正文全部加载
    - 随机等待 1~3 秒模拟阅读
    - 等待网络空闲确保内容加载
    """
    # 先等待初始网络空闲
    page.wait_for_load_state("networkidle", timeout=30000)

    scroll_height = page.evaluate("document.body.scrollHeight")
    viewport_height = page.evaluate("window.innerHeight")
    current_position = 0
    scroll_count = 0
    max_scrolls = 20  # 长文章可能需要更多滚动

    while current_position < scroll_height and scroll_count < max_scrolls:
        # 滚动一屏 (使用平滑滚动)
        current_position += viewport_height * 0.8  # 留 20% 重叠，更自然
        page.evaluate(f"""
            window.scrollTo({{
                top: {current_position},
                behavior: 'smooth'
            }})
        """)
        scroll_count += 1

        # ⭐ 随机等待 1~3 秒，模拟人类阅读
        wait_time = random.uniform(1.0, 3.0)
        page.wait_for_timeout(wait_time * 1000)

        # 等待网络空闲 (懒加载内容)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except:
            pass  # 超时继续

        # 检查页面高度是否变化 (懒加载可能增加高度)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height > scroll_height:
            scroll_height = new_height

    # 最后确保滚动到底部
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(random.uniform(1.0, 2.0) * 1000)

    # 滚动回顶部 (可选)
    # page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
```

#### 文章详情页完整爬取流程

```python
def scrape_article(page, url):
    """爬取单篇文章，包含人类化滚动"""
    # 1. 导航到文章页
    page.goto(url, wait_until="domcontentloaded", timeout=90000)

    # 2. 等待文章框架加载
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_selector("article", timeout=20000)

    # 3. ⭐ 人类化滚动，确保正文全部加载
    human_like_scroll(page)

    # 4. 提取内容 (此时正文已完全加载)
    title = page.locator("[data-testid='headline'], h1").first.inner_text()

    paragraphs = page.locator("[data-testid='paragraph'], p[data-type='paragraph']").all()
    content = "\n\n".join([p.inner_text().strip() for p in paragraphs if p.inner_text().strip()])

    # 5. 提取其他元信息
    author = extract_author(page)
    timestamp = extract_timestamp(page)

    return {
        "title": title,
        "content": content,
        "author": author,
        "timestamp": timestamp,
        "url": url
    }
```

### 7.4 必须使用已登录页面

- WSJ 是付费内容，需要登录才能查看完整文章
- 使用 Chrome 调试模式 (CDP) 连接到已登录的浏览器
- **不能创建新页面** (`context.new_page()`)，会触发验证
- 必须使用已有的 WSJ 页面进行导航

```python
# 连接到 Chrome 调试模式
browser = playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
context = browser.contexts[0]

# 找到已有的 WSJ 页面
page = next((p for p in context.pages if "wsj.com" in p.url), None)

# 在同一页面内导航
page.goto("https://www.wsj.com/some-article")
```

### 7.5 Chrome 调试模式启动

```bash
# Windows
chrome.exe --remote-debugging-port=9222 --user-data-dir="E:\chrome-debug-profile"

# 或使用项目中的脚本
python -m src.crawler.browser  # 调用 start_chrome_debugging()
```

---

## 8. 推荐的选择器配置

### 8.1 获取文章列表 (首页/分类页)

```python
SELECTORS = {
    # 文章链接 - 从 h3 内获取
    "article_links": "h3.css-fsvegl a",

    # 或使用 data-testid
    "article_headlines": "[data-testid='flexcard-headline']",

    # 文章摘要
    "article_summary": "[data-testid='flexcard-text']",

    # 分类标签
    "category_tag": "[data-testid='flashline']",

    # 作者
    "byline": "[data-testid='byline']",
    "author_link": "[data-testid='author-link']",

    # 时间
    "timestamp": "[data-testid='timestamp-text']",

    # 阅读时间
    "read_time": "[data-testid='flexcard-readtime']",
}
```

### 8.2 文章详情页选择器 (已验证 ✅)

WSJ 文章详情页存在**两种布局类型**，选择器需要兼容两者：

#### 布局类型对比

| 特征 | 类型A: 简单布局 | 类型B: Big-Top 布局 |
|-----|----------------|-------------------|
| 示例 | Tech 文章 | US News, China 文章 |
| h1 标题 | 无 data-testid | `data-testid="headline"` |
| h2 副标题 | 无 data-testid | `data-testid="dek-block"` |
| 正文段落 | `data-type="paragraph"` | `data-testid="paragraph"` |
| 特殊元素 | `<time>` 标签 | `data-block="big-top-wrapper"` |

#### 兼容两种布局的选择器

```python
ARTICLE_SELECTORS = {
    # 标题 - 优先 data-testid，fallback 到 h1
    "title": "[data-testid='headline'], h1",

    # 副标题/摘要
    "dek": "[data-testid='dek-block']",

    # 正文段落 - 兼容两种布局
    "paragraphs": "[data-testid='paragraph'], p[data-type='paragraph']",

    # 作者容器
    "byline": "[data-testid='byline']",

    # 作者链接 (可能多个)
    "author_links": "[data-testid='author-link']",

    # 关注按钮
    "follow_button": "[data-testid='follow-button']",

    # 时间戳
    "timestamp": "[data-testid='timestamp-text']",

    # 工具栏 (分享、保存等)
    "utility_bar": "[data-testid='utility-bar']",
    "share_button": "[data-testid='share-button']",
    "save_button": "[data-testid='save-button']",

    # 评论区
    "comments": "[data-testid='comment-container']",

    # 推荐文章 (What to Read Next)
    "related_articles": "[data-testid='flexcard-headline']",

    # 文章容器
    "article": "article",
}
```

#### 文章详情页 data-testid 统计

| data-testid | 简单布局 | Big-Top 布局 | 说明 |
|-------------|---------|-------------|------|
| `headline` | 0 | **1** | 文章主标题 (h1) |
| `dek-block` | 0 | **1** | 副标题 (h2) |
| `paragraph` | 0 | **26-58** | 正文段落 |
| `byline` | 1 | 1 | 作者容器 |
| `author-link` | 3 | 1-4 | 作者链接 |
| `timestamp-text` | 1 | 6-9 | 时间戳 |
| `utility-bar` | 1 | 2 | 工具栏 |
| `video-player` | 0 | 0-1 | 视频播放器 |
| `comment-container` | 0 | 1 | 评论区 |
| `flexcard-headline` | 12 | 14 | 推荐文章 |

#### 正文提取代码示例

```python
def extract_article_content(page):
    """提取文章正文，兼容两种布局"""
    # 方法1: 优先使用 data-testid
    paragraphs = page.locator("[data-testid='paragraph']").all()

    # 方法2: fallback 到 data-type
    if not paragraphs:
        paragraphs = page.locator("p[data-type='paragraph']").all()

    # 方法3: 最后 fallback 到 article p
    if not paragraphs:
        paragraphs = page.locator("article p").all()

    content = []
    for p in paragraphs:
        text = p.inner_text().strip()
        # 过滤广告和版权声明
        if text and len(text) > 20 and "Advertisement" not in text:
            content.append(text)

    return "\n\n".join(content)
```

#### 时间戳格式

| 格式 | 示例 |
|-----|------|
| 标准 | `Jan. 24, 2026 9:00 pm ET` |
| 更新 | `Updated Jan. 24, 2026 7:36 pm ET` |

---

## 9. 文章详情页结构分析

### 9.1 三个示例文章对比

| 属性 | example_1 (Tech) | example2 (US News) | example3 (China) |
|-----|-----------------|-------------------|-----------------|
| URL | `/tech/europe-...` | `/us-news/federal-...` | `/world/china/china-ai-...` |
| 布局类型 | **简单布局** | Big-Top | Big-Top |
| p 标签数 | 52 | 131 | 165 |
| paragraph | 0 | **26** | **58** |
| h3 (推荐) | 6 | 14 | 17 |
| video | 0 | 3 | 2 |
| figure | 2 | 6 | 8 |

### 9.2 详情页 DOM 结构

```html
<article class="css-1sku87d e1pk9eoe4">
  <!-- 标题区 -->
  <h1 data-testid="headline" class="...HeadlineBlock">
    文章标题
  </h1>

  <!-- 副标题 -->
  <h2 data-testid="dek-block" class="...DekBlock">
    副标题/摘要
  </h2>

  <!-- 作者信息 -->
  <div data-testid="byline" class="...BylineContainer">
    <p class="...AuthorPlaintext">By</p>
    <a data-testid="author-link" href="/news/author/xxx">作者名</a>
    <button data-testid="follow-button">Follow</button>
  </div>

  <!-- 时间戳 -->
  <p data-testid="timestamp-text" class="...TimeTag">
    Jan. 24, 2026 9:00 pm ET
  </p>

  <!-- 正文段落 -->
  <p data-testid="paragraph" data-type="paragraph" class="...Paragraph">
    段落内容...
  </p>
  <p data-testid="paragraph" data-type="paragraph" class="...Paragraph">
    段落内容...
  </p>

  <!-- 文章内小标题 (可选) -->
  <h3 class="...Subhed" data-type="hed">小标题</h3>

  <!-- 图片/图表 -->
  <figure>
    <picture><img src="..." /></picture>
    <figcaption>图片说明</figcaption>
  </figure>
</article>

<!-- 推荐文章 -->
<section>
  <h2>What to Read Next</h2>
  <div>
    <h3 class="css-fsvegl">
      <a data-testid="flexcard-headline">推荐文章标题</a>
    </h3>
  </div>
</section>
```

### 9.3 文章内特殊元素

| 元素 | data-type | 说明 |
|-----|-----------|------|
| 段落 | `paragraph` | 正文段落 |
| 小标题 | `hed` | 文章内 h3 小标题 |
| 图表 | `dynamic-inset` | 交互式图表 |

---

## 10. 已创建的工具脚本

### 10.1 页面检查器

**路径**: `src/crawler/page_inspector.py`

交互式命令行工具，用于检查页面元素：

```bash
python -m src.crawler.page_inspector
```

**命令列表**:
| 命令 | 说明 |
|-----|------|
| `info` | 显示当前页面信息 |
| `goto <url>` | 跳转到 URL |
| `scroll down/up/top/bottom` | 滚动页面 |
| `wait <秒>` | 等待 |
| `elements <selector>` | 查找元素 |
| `attrs <selector>` | 获取属性 |
| `text <selector>` | 获取文本 |
| `dump <name>` | **导出页面所有元素到 JSON** |
| `screenshot <name>` | 截图 |

### 10.2 页面分析脚本

**路径**: `src/crawler/analyze_wsj.py`

自动分析多个页面，寻找最佳选择器：

```bash
python -m src.crawler.analyze_wsj
```

### 10.3 基础爬虫

**路径**: `src/crawler/wsj_crawler.py`

基础爬虫类，需要根据分析结果更新：

```python
from src.crawler import WSJCrawler

crawler = WSJCrawler()
crawler.connect()
links = crawler.get_article_links()
article = crawler.scrape_article(links[0])
```

---

## 10. 待完成事项

1. **文章详情页分析** - 需要 dump 几个文章页面，验证详情页选择器
2. **更新 wsj_crawler.py** - 根据分析结果更新选择器和等待逻辑
3. **测试不同类型文章** - 普通文章、视频文章、图片文章等
4. **增量爬取逻辑** - 避免重复爬取已有文章
5. **错误处理** - 验证页面、超时、内容缺失等情况

---

## 11. 数据文件

| 文件 | 说明 | 采集时间 |
|-----|------|---------|
| `data/page_dump.json` | 首页元素导出 | 2026-01-24 |
| `data/homepage.json` | World 分类页元素导出 | 2026-01-24 |
| `data/homepage.png` | World 分类页截图 | 2026-01-24 |
| `data/china.json` | China 子分类页导出 | 2026-01-24 16:17 |
| `data/tech.json` | Tech 顶级分类页导出 | 2026-01-24 16:18 |
| `data/business.json` | Business 顶级分类页导出 | 2026-01-25 03:14 |
| `data/page_example_1.json` | **文章详情页** (Tech, 简单布局) | 2026-01-24 16:19 |
| `data/page_example2.json` | **文章详情页** (US News, Big-Top) | 2026-01-25 03:34 |
| `data/page_example3.json` | **文章详情页** (China, Big-Top) | 2026-01-25 03:34 |

---

## 附录A：首页 vs 分类页对比

| 项目 | 首页 | World | China | Tech | Business |
|-----|------|-------|-------|------|----------|
| 类型 | 主页 | 分类页 | **子分类** | 顶级分类 | 顶级分类 |
| URL | `/` | `/world` | `/world/china` | `/tech` | `/business` |
| h1 | 2 | 1 | 1 | 1 | 1 |
| h2 | 16 | 4 | 7 | 4 | 4 |
| **h3** | **63** | 26 | **45** | 26 | 26 |
| a | 232 | 157 | 216 | 143 | 153 |
| div | 1250 | 783 | 1151 | 756 | 789 |

## 附录B：data-testid 全页面对比

| data-testid | 首页 | World | China | Tech | Business |
|-------------|------|-------|-------|------|----------|
| `flexcard-headline` | 59 | 26 | **45** | 26 | 26 |
| `flexcard-text` | 31 | 11 | 25 | 11 | 10 |
| `byline` | 12 | 15 | 27 | 15 | 15 |
| `author-link` | 5 | 19 | 24 | 17 | 16 |
| `timestamp-text` | 1 | 9 | 11 | 9 | 9 |
| `flexcard-readtime` | 34 | 21 | 30 | 21 | 21 |
| `flashline` | 2 | 11 | **0** | **10** | **9** |
| `*-front-lead-article` | - | - | - | **1** | **1** |
| `*-front-article` | - | - | - | **5** | **5** |
| `content-feed` | 5 | 1 | 3 | 1 | 1 |
| `tag` | 55 | 3 | 18 | 8 | 24 |
| `divider` | 36 | 9 | 11 | 9 | 9 |

## 附录C：h3 文章标题样例

### China 子分类页 (45篇)
- "China's Xi Places His Top General Under Investigation as Military Purges Heat Up"
- "Pentagon's New Defense Strategy Strikes Conciliatory Tone on China"
- "China Built a Vast Oil Stake in Venezuela. Now It Risks Getting Muscled Out."

### Tech 顶级分类页 (26篇)
- "Europe Prepares for a Nightmare Scenario: The U.S. Blocking Access to Tech"
- "Our Gadgets Finally Speak Human, and Tech Will Never Be the Same"
- "How Intel Came Crashing Back to Earth After Its Trump Bump"

### Business 顶级分类页 (26篇)
- "News Quiz for Jan. 24, 2026"
- "This NFL Season's Fiercest Rivalry Is Sports Betting vs. Prediction Markets"
- "What Trump Was Really Like at Davos"

---

> 文档版本: v4
> 最后更新: 2026-01-25
> 更新历史:
> - v1: 首页 + World 分类页分析
> - v2: 新增 China/Tech/Business 分类页分析
> - v3: 新增文章详情页分析 (两种布局类型、选择器、DOM 结构)
> - v4: **新增爬虫策略** (EXCLUSIVE 优先级、人类化滚动 1~3s、页面加载等待)
