# -*- coding: utf-8 -*-
"""main.py

读取 config.json → 启动 MoreLogin → 附加浏览器 → 遍历 Excel 里的账号进行自动登录演示。
"""

import json
import time

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
        if acc["seq"] < 3:
            continue
        print("\n=== 处理账号 #%s %s ===" % (acc["seq"], acc["email"]))
        # 启动 MoreLogin 环境
        debug_port = start_env(acc["seq"], cfg)
        bz = 附加浏览器(debug_port, cfg.get("CHROMEDRIVER_PATH"))
        bz.关闭其他页签()
        bz.打开网页("https://accounts.google.com/signin/v2/identifier")
        bz.点击("#identifierNext")
        # 1. 等待 reCAPTCHA 的 iframe 可用，并切入
        bz.wait.until(EC.frame_to_be_available_and_switch_to_it(
            (By.CSS_SELECTOR, "iframe[src*='recaptcha/enterprise'],"  # 企业版
                              "iframe[src*='recaptcha/api2/anchor'],"  # V2 复选框主 iframe
                              "iframe[src*='recaptcha/api2/bframe']")  # V2 挑格子 iframe
        ))

        # 2. 定位并点击复选框边框
        bz.点击("css=div.recaptcha-checkbox-border")

        # 3. 切回主文档
        bz.driver.switch_to.default_content()

        # 4. 等待“格子挑战”iframe 出现并切入（如果是 V2 图像格子）
        bz.wait.until(EC.frame_to_be_available_and_switch_to_it(
            (By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/bframe']"))
        )

        # 5. 等待格子加载完毕（比如目标文本出现）
        bz.wait.until(EC.presence_of_element_located(
            (By.XPATH, "//div[contains(text(),'Select all images with')]")
        ))

        # 6. 切回主文档，为 solve_recaptcha 取 site_key
        bz.driver.switch_to.default_content()
        site_key = bz.driver.find_element(
            By.CSS_SELECTOR, "iframe[src*='recaptcha']").get_attribute("data-sitekey")
        page_url = bz.获取当前URL()

        # 7. 调用 API 拿 token，注入并提交
        token = solve_recaptcha(site_key, page_url, "a367032b09384ff898161b334dde8b0a653959", "ReCaptchaV2TaskProxyless")
        print(token)
        bz.driver.execute_script(
            "document.getElementById('g-recaptcha-response').value = arguments[0];", token
        )
        # 触发回调（如果必要）
        bz.driver.execute_script("___grecaptcha_cfg.clients[0].T.T.callback(arguments[0]);", token)
        # 最后点击“Verify”按钮
        bz.点击("css=button[jsname='LgbsSe']", force=True)


        return
        g = google.Google(bz)
        # 通过url 判断是否已经登录成功
        url = bz.获取当前URL()
        if "myaccount.google.com" in url:
            continue

        # 判断是否需要 申诉 接码 #identifierNext > div > button > span
        if bz.元素存在("#headingText"):
            print("需要申诉")
            g.receive_code()
            break

        g.login(acc["email"], acc["password"], acc["recovery"])

    bz.driver.quit()


if __name__ == "__main__":
    main()
