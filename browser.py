# -*- coding: utf-8 -*-
"""browser.py

Selenium 常用操作中文封装（Python 3.9+）。

定位规则
^^^^^^^^
1. `#id` 前缀 → **id**
2. `css=` 前缀 → **CSS 选择器**
3. `//` 或 `(//` → **XPath**
4. 其它 → **name**

提供的实例方法
---------------
- `打开网页(url)`                     – 打开并等待加载完成
- `点击(locator, force=False)`        – 支持 id / name / css / xpath；自动滚动；`force=True` 时用 JS 点击
- `输入框清除内容并且输入数据(locator, text)`
- `判断元素是否出现(locator, timeout=30)`
- `等待界面加载完成(timeout=30)`
- `点击并等待加载完成(locator, force=False)`
- `关闭其他页签()`
- `延时(ms=1000)` / `随机延时(min_ms, max_ms)`

工厂方法
---------
- `创建浏览器(driver_path=None, timeout=30)`
- `附加浏览器(debug_port, driver_path=None, timeout=30)`
"""

import os
import random
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import ElementNotInteractableException

__all__ = [
    "浏览器",
    "创建浏览器",
    "附加浏览器",
]


# ------------------------------------------------------------------
# 私有工具
# ------------------------------------------------------------------

def _随机暂停(min_ms=1000, max_ms=2000):
    """更轻微的人类化停顿。"""
    time.sleep(random.uniform(min_ms / 1000.0, max_ms / 1000.0))


def _to_by(locator):
    if locator.startswith("#"):
        return By.ID, locator[1:]
    if locator.startswith("css="):
        return By.CSS_SELECTOR, locator[4:]
    if locator.startswith("//") or locator.startswith("(//"):
        return By.XPATH, locator
    return By.NAME, locator


# ------------------------------------------------------------------
# 浏览器封装
# ------------------------------------------------------------------

class 浏览器:
    def __init__(self, driver, timeout=30):
        self.driver = driver  # type: WebDriver
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)

    # ---------------- 延时 ----------------
    def 延时(self, ms=1000):
        time.sleep(ms / 1000.0)

    def 随机延时(self, min_ms=1000, max_ms=2000):
        _随机暂停(min_ms, max_ms)

    # ---------------- 页面 ----------------
    def 打开网页(self, url):
        self.driver.get(url)
        self.等待界面加载完成()
        _随机暂停(1200, 1600)

    def 获取当前URL(self):
        """返回当前页面的完整 URL"""
        return self.driver.current_url

    def 切换到包含URL关键词的标签(self, keyword):
        """切换到当前所有标签中第一个包含指定关键词的标签页"""
        for handle in self.driver.window_handles:
            self.driver.switch_to.window(handle)
            current_url = self.driver.current_url
            if keyword in current_url:
                print("✅ 已切换到匹配的标签页：", current_url)
                return True
        print("❌ 没有找到包含关键词 [%s] 的标签页" % keyword)
        return False


    # ---------------- 基础动作 ----------------
    def 点击(self, locator, force=False):
        """点击元素；如元素不可交互则自动滚动并可选 JS 点击。"""
        by, value = _to_by(locator)
        element = self.wait.until(EC.presence_of_element_located((by, value)))

        # 滚动到元素可见中心
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
            element,
        )
        _随机暂停(1000, 2000)

        try:
            self.wait.until(EC.element_to_be_clickable((by, value))).click()
        except ElementNotInteractableException:
            if force:
                # 直接用 JS 触发 click
                self.driver.execute_script("arguments[0].click();", element)
            else:
                raise
        _随机暂停()

    def 输入框清除内容并且输入数据(self, locator, text):
        by, value = _to_by(locator)
        element = self.wait.until(EC.presence_of_element_located((by, value)))
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.clear()
        element.send_keys(text)
        _随机暂停()

    def 关闭其他页签(self):
        original = self.driver.current_window_handle
        for handle in list(self.driver.window_handles):
            if handle != original:
                self.driver.switch_to.window(handle)
                self.driver.close()
        self.driver.switch_to.window(original)
        _随机暂停()

    # ---------------- 等待与判断 ----------------
    def 判断元素是否出现(self, locator, timeout=None):
        by, value = _to_by(locator)
        try:
            WebDriverWait(self.driver, timeout or self.timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return True
        except Exception:
            return False

    def 等待界面加载完成(self, timeout=None):
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            if self.driver.execute_script("return document.readyState") == "complete":
                return True
            time.sleep(1)
        return False
    
    def 元素存在(self, locator, timeout=None):
        return self.判断元素是否出现(locator, timeout)


    # ---------------- 复合动作 ----------------
    def 点击并等待加载完成(self, locator, force=False):
        self.点击(locator, force=force)
        self.等待界面加载完成()


# ------------------------------------------------------------------
# 工厂方法
# ------------------------------------------------------------------

def _默认驱动路径():
    return "chromedriver.exe" if os.name == "nt" else "chromedriver"


def 创建浏览器(driver_path=None, timeout=30):
    print(driver_path or _默认驱动路径())
    service = Service(executable_path=driver_path or _默认驱动路径())
    driver = webdriver.Chrome(service=service)
    return 浏览器(driver, timeout)


def 附加浏览器(debug_port, driver_path=None, timeout=30):
    chrome_options = Options()
    chrome_options.debugger_address = f"127.0.0.1:{debug_port}"
    service = Service(executable_path=driver_path or _默认驱动路径())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return 浏览器(driver, timeout)
