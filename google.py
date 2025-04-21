# -*- coding: utf-8 -*-
"""google.py
Google 自动化一站式工具类 `Google`。
"""

import time
from typing import Optional

from browser import 创建浏览器, 浏览器

__all__ = ["Google"]


class Google:
    """Google 账号相关自动化操作封装。"""

    def __init__(
        self,
        browser: Optional[浏览器] = None,
        driver_path: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self._owns_browser = browser is None
        self.bz: 浏览器 = browser or 创建浏览器(driver_path=driver_path, timeout=timeout)

    # ------------------------------------------------------------------
    # 登录流程
    # ------------------------------------------------------------------
    def login(self, email: str, password: str, recovery: str = "") -> str:
        bz = self.bz
        bz.打开网页("https://accounts.google.com/signin/v2/identifier")

        # 输入邮箱
        bz.输入框清除内容并且输入数据("identifier", email)
        bz.点击("#identifierNext")

        # 输入密码
        if bz.判断元素是否出现("Passwd", timeout=10):
            bz.输入框清除内容并且输入数据("Passwd", password)
            bz.点击("#passwordNext")

        # 辅助邮箱（可选）
        if recovery and bz.判断元素是否出现("knowledgePreregisteredEmail", timeout=8):
            bz.输入框清除内容并且输入数据("knowledgePreregisteredEmail", recovery)
            bz.点击("css=button[jsname='LgbsSe']", force=True)

        time.sleep(5)
        return bz.获取当前URL()

    # ------------------------------------------------------------------
    # 接码
    # ------------------------------------------------------------------
    def receive_code(self) -> str:
        """占位：调用第三方接码平台获取验证码。"""
        self.bz.点击("#identifierNext")
        self.bz.等待界面加载完成()


    # ------------------------------------------------------------------
    # 申诉占位实现
    # ------------------------------------------------------------------
    def appeal(self, reason: str = "") -> None:
        """占位：账号申诉流程，需要自动填写谷歌申诉表单。"""
        # TODO: 根据谷歌官方申诉页面 URL + 表单字段自动填写并提交
        print(f"[appeal] 申诉原因: {reason} —— 请在此实现申诉自动化……")

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------
    def quit(self):
        if self._owns_browser:
            self.bz.driver.quit()
