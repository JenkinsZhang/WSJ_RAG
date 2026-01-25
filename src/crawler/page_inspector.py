"""
页面检查器 - 交互式工具，用于分析 WSJ 页面结构

功能：
- 连接到已登录的 Chrome 浏览器
- 导出页面元素到 JSON 供分析
- 交互式命令检查页面

使用方法：
    python -m src.crawler.page_inspector
"""

import json
import re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# 配置
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
USER_DATA_DIR = Path(r"E:\chrome-debug-profile")
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data"


class PageInspector:
    """页面检查器"""

    def __init__(self):
        self._playwright = None
        self._context = None
        self._page: Page = None

    def connect(self) -> bool:
        """连接浏览器"""
        print("连接浏览器...")
        try:
            self._playwright = sync_playwright().start()
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(USER_DATA_DIR),
                headless=False,
                executable_path=str(CHROME_PATH),
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )

            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()

            print(f"连接成功，当前页面: {self._page.url}")
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()
        print("已断开连接")

    def goto(self, url: str):
        """跳转到 URL"""
        print(f"跳转到: {url}")
        self._page.goto(url, wait_until="load", timeout=90000)
        try:
            self._page.wait_for_load_state("networkidle", timeout=30000)
        except:
            pass
        self._page.wait_for_timeout(3000)
        print(f"当前页面: {self._page.url}")

    def scroll(self, direction: str = "bottom"):
        """滚动页面"""
        if direction == "bottom":
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            self._page.evaluate("window.scrollTo(0, 0)")
        elif direction == "down":
            self._page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
        elif direction == "up":
            self._page.evaluate("window.scrollBy(0, -window.innerHeight * 0.8)")
        self._page.wait_for_timeout(1000)
        print(f"滚动: {direction}")

    def scroll_full(self):
        """滚动到底部，等待所有内容加载"""
        print("开始滚动加载...")
        last_height = 0
        stable_count = 0

        while stable_count < 2:
            self._page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
            self._page.wait_for_timeout(3000)

            current_height = self._page.evaluate("document.body.scrollHeight")
            if current_height == last_height:
                stable_count += 1
            else:
                stable_count = 0
                last_height = current_height
            print(f"  高度: {current_height}, 稳定次数: {stable_count}")

        print("滚动完成")

    def info(self):
        """显示当前页面信息"""
        url = self._page.url
        title = self._page.title()
        print(f"URL: {url}")
        print(f"Title: {title}")

        # 统计标签
        tags = ['h1', 'h2', 'h3', 'h4', 'p', 'a', 'div', 'article', 'section']
        print("\n标签统计:")
        for tag in tags:
            count = len(self._page.locator(tag).all())
            if count > 0:
                print(f"  {tag}: {count}")

    def elements(self, selector: str, limit: int = 10):
        """查找元素"""
        els = self._page.locator(selector).all()
        print(f"找到 {len(els)} 个元素 (显示前 {limit} 个):\n")

        for i, el in enumerate(els[:limit]):
            try:
                text = el.inner_text()[:80].replace('\n', ' ')
                print(f"{i+1}. {text}")
            except:
                print(f"{i+1}. [无法获取文本]")

    def attrs(self, selector: str, limit: int = 5):
        """获取元素属性"""
        els = self._page.locator(selector).all()
        print(f"找到 {len(els)} 个元素:\n")

        for i, el in enumerate(els[:limit]):
            try:
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                attrs = el.evaluate("""el => {
                    const result = {};
                    for (const attr of el.attributes) {
                        result[attr.name] = attr.value;
                    }
                    return result;
                }""")
                print(f"{i+1}. <{tag}>")
                for k, v in attrs.items():
                    v_short = v[:60] + "..." if len(v) > 60 else v
                    print(f"     {k}=\"{v_short}\"")
                print()
            except:
                print(f"{i+1}. [无法获取属性]")

    def dump(self, name: str):
        """导出页面元素到 JSON"""
        print(f"导出页面元素...")

        data = self._page.evaluate("""
            () => {
                const result = {
                    url: window.location.href,
                    title: document.title,
                    timestamp: new Date().toISOString(),
                    tags: {},
                    data_testid: {},
                    data_type: {},
                    classes: {}
                };

                // 统计标签
                const tags = ['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'a', 'div', 'span', 'article', 'section', 'nav', 'header', 'footer', 'ul', 'li', 'figure', 'img', 'time', 'button'];
                for (const tag of tags) {
                    const els = document.querySelectorAll(tag);
                    if (els.length > 0) {
                        result.tags[tag] = {
                            count: els.length,
                            samples: []
                        };
                        // 采样前 10 个
                        for (let i = 0; i < Math.min(els.length, 10); i++) {
                            const el = els[i];
                            result.tags[tag].samples.push({
                                text: el.innerText?.slice(0, 200) || '',
                                class: el.className?.slice(0, 100) || '',
                                href: el.href || null,
                                'data-testid': el.getAttribute('data-testid') || null
                            });
                        }
                    }
                }

                // 统计 data-testid
                const testids = document.querySelectorAll('[data-testid]');
                const testidMap = {};
                testids.forEach(el => {
                    const id = el.getAttribute('data-testid');
                    if (!testidMap[id]) testidMap[id] = [];
                    if (testidMap[id].length < 5) {
                        testidMap[id].push({
                            tag: el.tagName.toLowerCase(),
                            text: el.innerText?.slice(0, 150) || '',
                            class: el.className?.slice(0, 80) || ''
                        });
                    }
                });
                for (const [id, samples] of Object.entries(testidMap)) {
                    result.data_testid[id] = {
                        count: document.querySelectorAll(`[data-testid="${id}"]`).length,
                        samples: samples
                    };
                }

                // 统计 data-type
                const datatypes = document.querySelectorAll('[data-type]');
                const datatypeMap = {};
                datatypes.forEach(el => {
                    const dt = el.getAttribute('data-type');
                    if (!datatypeMap[dt]) datatypeMap[dt] = [];
                    if (datatypeMap[dt].length < 3) {
                        datatypeMap[dt].push({
                            tag: el.tagName.toLowerCase(),
                            text: el.innerText?.slice(0, 100) || ''
                        });
                    }
                });
                for (const [dt, samples] of Object.entries(datatypeMap)) {
                    result.data_type[dt] = {
                        count: document.querySelectorAll(`[data-type="${dt}"]`).length,
                        samples: samples
                    };
                }

                return result;
            }
        """)

        # 保存
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{name}.json"
        filepath = OUTPUT_DIR / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"已保存到: {filepath}")
        print(f"  URL: {data['url']}")
        print(f"  标签类型: {len(data['tags'])}")
        print(f"  data-testid 类型: {len(data['data_testid'])}")

    def screenshot(self, name: str):
        """截图"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / f"{name}.png"
        self._page.screenshot(path=str(filepath), full_page=True)
        print(f"截图保存到: {filepath}")


def main():
    """交互式命令行"""
    print("\n" + "=" * 60)
    print("  WSJ 页面检查器")
    print("=" * 60)

    inspector = PageInspector()
    if not inspector.connect():
        return

    print("\n命令:")
    print("  info              - 显示页面信息")
    print("  goto <url>        - 跳转到 URL")
    print("  scroll [方向]     - 滚动 (bottom/top/down/up)")
    print("  scroll_full       - 滚动到底部并等待加载")
    print("  elements <选择器> - 查找元素")
    print("  attrs <选择器>    - 获取元素属性")
    print("  dump <名称>       - 导出页面元素到 JSON")
    print("  screenshot <名称> - 截图")
    print("  quit              - 退出")
    print()

    try:
        while True:
            try:
                cmd = input("> ").strip()
                if not cmd:
                    continue

                parts = cmd.split(maxsplit=1)
                action = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if action == "quit" or action == "exit" or action == "q":
                    break
                elif action == "info":
                    inspector.info()
                elif action == "goto" and arg:
                    inspector.goto(arg)
                elif action == "scroll":
                    inspector.scroll(arg or "bottom")
                elif action == "scroll_full":
                    inspector.scroll_full()
                elif action == "elements" and arg:
                    inspector.elements(arg)
                elif action == "attrs" and arg:
                    inspector.attrs(arg)
                elif action == "dump" and arg:
                    inspector.dump(arg)
                elif action == "screenshot" and arg:
                    inspector.screenshot(arg)
                else:
                    print("未知命令或缺少参数")

            except KeyboardInterrupt:
                print("\n")
                continue
            except Exception as e:
                print(f"错误: {e}")

    finally:
        inspector.disconnect()


if __name__ == "__main__":
    main()
