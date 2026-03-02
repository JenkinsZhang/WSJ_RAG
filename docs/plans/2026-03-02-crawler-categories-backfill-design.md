# 爬虫扩展：新增分类 + Archive 补全

> 日期：2026-03-02

## 背景

当前爬虫覆盖 8 个分类，WSJ 导航栏有 17 个。同时数据有断层（如 tech 从 01-31 到 03-01 缺失约 28 天）。需要：
1. 扩展分类覆盖
2. 利用 WSJ Archive 页面回溯补全缺失数据

## 设计

### 1. 新增分类

`PAGES_TO_CRAWL` 从 8 → 17：

```python
# 新增 9 个分类
"opinion":          "https://www.wsj.com/opinion",
"arts":             "https://www.wsj.com/arts-culture",
"lifestyle":        "https://www.wsj.com/lifestyle",
"real-estate":      "https://www.wsj.com/real-estate",
"personal-finance": "https://www.wsj.com/personal-finance",
"health":           "https://www.wsj.com/health",
"style":            "https://www.wsj.com/style",
"sports":           "https://www.wsj.com/sports",
"us-news":          "https://www.wsj.com/us-news",
```

### 2. Archive 补全

#### 2.1 Archive 页面结构

- URL: `https://www.wsj.com/news/archive/YYYY/MM/DD`
- 每天约 30-40 篇文章
- 全部以 `h3 a` 标签呈现，无需滚动
- 文章混合所有分类（通过 URL 推断分类）

#### 2.2 缺失日期计算

```
扫描 articles/*/ 下所有日期文件夹
→ 找到全局最早日期和最晚日期
→ 计算期间缺失的天数
→ 限制最大回溯天数 (默认 30)
→ 按日期从新到旧排序 (优先补近期)
```

#### 2.3 新增方法

```python
class WSJCrawler:
    def crawl_archive_day(self, date: date) -> list[Article]:
        """爬取指定日期的 Archive 页面"""
        # 1. 导航到 /news/archive/YYYY/MM/DD
        # 2. 提取 h3 a 链接 (复用 _is_article_url 过滤)
        # 3. 过滤已爬取的 URL
        # 4. 逐一爬取文章详情 (复用 _scrape_article)
        # 5. 保存文章

    def backfill(self, max_days: int = 30) -> dict:
        """智能补全缺失日期"""
        # 1. 扫描 articles/ 获取已有日期集合
        # 2. 计算缺失日期
        # 3. 对每个缺失日期调用 crawl_archive_day
        # 4. 返回统计信息
```

#### 2.4 CLI 接口

```bash
# 智能补全
python -m src.crawler.wsj_crawler backfill
python -m src.crawler.wsj_crawler backfill --max-days 60

# 爬取指定日期的 Archive
python -m src.crawler.wsj_crawler --archive-date 2026-02-15

# run_pipeline.py 集成
python run_pipeline.py --backfill
```

### 3. 不做的事

- 不改变现有的分类页爬取逻辑
- 不改变文章内容提取逻辑
- 不改变索引流程
- Archive 补全不按分类过滤（一天的页面包含所有分类）

## 验证

1. `backfill` 正确识别缺失日期
2. Archive 页面链接提取正常
3. 已爬取的 URL 不会重复爬取
4. CAPTCHA 检测在 Archive 页面也能工作
