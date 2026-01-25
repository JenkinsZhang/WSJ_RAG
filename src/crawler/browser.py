"""
Playwright 浏览器管理模块

支持持久化模式，保存登录状态。
使用本地 Chrome 浏览器而非 Playwright 的 Chromium。
"""

import subprocess
import socket
from pathlib import Path
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 配置
CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
USER_DATA_DIR = Path(r"E:\chrome-debug-profile")


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


class BrowserManager:
    """
    浏览器管理器 - 持久化模式

    使用本地 Chrome + 持久化 context，保存 cookies 和登录状态。

    Usage:
        with BrowserManager() as browser:
            page = browser.get_page()
            page.goto("https://wsj.com")
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[Path] = None,
        chrome_path: Optional[Path] = None,
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir or USER_DATA_DIR
        self.chrome_path = chrome_path or CHROME_PATH

        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def start(self) -> None:
        """启动浏览器"""
        logger.info(f"启动浏览器 (headless={self.headless})")
        logger.info(f"Chrome: {self.chrome_path}")
        logger.info(f"Profile: {self.user_data_dir}")

        self._playwright = sync_playwright().start()

        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            executable_path=str(self.chrome_path),
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )

        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()

        logger.info("浏览器启动成功")

    def close(self) -> None:
        """关闭浏览器"""
        if self._context:
            self._context.close()
            self._context = None
            self._page = None

        if self._playwright:
            self._playwright.stop()
            self._playwright = None

        logger.info("浏览器已关闭")

    def get_page(self) -> Page:
        """获取当前页面"""
        if not self._page:
            raise RuntimeError("浏览器未启动")
        return self._page

    def new_page(self) -> Page:
        """创建新页面"""
        if not self._context:
            raise RuntimeError("浏览器未启动")
        return self._context.new_page()

    def get_all_pages(self) -> list[Page]:
        """获取所有页面"""
        if self._context:
            return self._context.pages
        return []
