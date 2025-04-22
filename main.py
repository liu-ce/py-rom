# -*- coding: utf-8 -*-
"""main.py

读取 config.json → 启动 MoreLogin → 附加浏览器 → 遍历 Excel 里的账号进行自动登录演示。
"""
import re
import json
import time
import requests
from morelogin import start_env
from browser import 附加浏览器
from load_accounts import load_accounts
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from ezcaptcha import solve_recaptcha
import google

CONFIG_PATH = "config.json"

# ------------------------------------------------------------------
# 配置加载
# ------------------------------------------------------------------

def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def main():
    cfg = load_config()
    accounts = load_accounts(cfg["EXCEL_PATH"])
    if not accounts:
        raise ValueError("账号列表为空！")

    for acc in accounts:
        if acc["seq"] != 3:
            continue
        print("\n=== 处理账号 #%s %s ===" % (acc["seq"], acc["email"]))

        # 启动 MoreLogin 环境
        debug_port = start_env(acc["seq"], cfg)
        bz = 附加浏览器(debug_port, cfg.get("CHROMEDRIVER_PATH"))
        bz.关闭其他页签()
        bz.打开网页("https://accounts.google.com/signin/v2/identifier")

        # 点击 "下一步" 进入验证码阶段
        bz.点击("#identifierNext")

        # 等待验证码 iframe，切入并点击复选框
        bz.wait.until(EC.frame_to_be_available_and_switch_to_it(
            (By.CSS_SELECTOR, "iframe[src*='recaptcha/enterprise'],"
                              "iframe[src*='recaptcha/api2/anchor'],"
                              "iframe[src*='recaptcha/api2/bframe']"))
        )
        bz.点击("css=div.recaptcha-checkbox-border")
        bz.driver.switch_to.default_content()

        # 2. 再用 JS 提取它的值（注意是 data-site-key）
        site_key = bz.driver.execute_script("""
            const el = document.querySelector('div[data-site-key]');
            return el ? el.getAttribute('data-site-key') : null;
        """)

        # 获取干净页面 URL
        page_url = bz.driver.execute_script("return window.location.origin + window.location.pathname;")

        print("✅ 提取到 sitekey:", site_key)
        print("🌐 页面 URL:", page_url)

        # 写入 token 到 textarea
        bz.driver.execute_script("""
            document.getElementById("g-recaptcha-response").value = arguments[0];
        """, token)




if __name__ == "__main__":
    main()
