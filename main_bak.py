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
    # 启动 MoreLogin 环境
    debug_port = start_env(acc["seq"], cfg)
    bz = 附加浏览器(debug_port, cfg.get("CHROMEDRIVER_PATH"))
    bz.关闭其他页签()
    bz.打开网页("https://accounts.google.com/signin/v2/identifier")




if __name__ == "__main__":
    main()
