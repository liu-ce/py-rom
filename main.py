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

        # 开始最多尝试 100 次打码验证
        for i in range(100):
            print("🔁 第 %d 次尝试验证码识别..." % (i + 1))

            bz.driver.switch_to.default_content()

            # 获取 site_key 和当前页面 URL
            site_key_elem = bz.driver.find_element(By.CSS_SELECTOR, "[data-site-key]")
            site_key = site_key_elem.get_attribute("data-site-key")
            page_url = bz.获取当前URL()

            # 调用打码平台获取 token
            token = solve_recaptcha(
                site_key,
                page_url,
                "7e9d2df45e0c06251cbb6b8a10924f23e44eaadd56355",
                "NoCaptchaTaskProxyless"
            )
            print("识别结果 token:", token)

            # 注入 token
            bz.driver.execute_script("""
                let el = document.getElementById('g-recaptcha-response');
                el.value = arguments[0];
                el.dispatchEvent(new Event('change'));
            """, token)

            # 确保切换到主文档
            bz.driver.switch_to.default_content()

            # 执行 grecaptcha callback（兼容隐式回调）
            clients_structure = bz.driver.execute_script("""
                try {
                    const clients = window.___grecaptcha_cfg.clients;
                    const json = JSON.stringify(clients, function (key, value) {
                        if (typeof value === 'function') return '[Function]';
                        return value;
                    });
                    return json;
                } catch (e) {
                    return "打印失败: " + e.toString();
                }
            """)
            print("打印内容：", clients_structure)

            # 尝试点击 verify / skip 按钮（有些页面需要）
            try:
                bz.wait.until(EC.frame_to_be_available_and_switch_to_it(
                    (By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/bframe']"))
                )
                bz.点击("#recaptcha-verify-button", force=True)
                bz.driver.switch_to.default_content()
            except Exception as e:
                print("⚠️ bframe iframe 不存在，可能已验证成功")

            time.sleep(2)

            # 检查复选框是否已被选中，表示验证通过
            try:
                bz.driver.switch_to.default_content()
                anchor_frame = bz.driver.find_element(By.CSS_SELECTOR, "iframe[src*='recaptcha/api2/anchor']")
                bz.driver.switch_to.frame(anchor_frame)
                checkbox = bz.driver.find_element(By.ID, "recaptcha-anchor")
                status = checkbox.get_attribute("aria-checked")
                if status == "true":
                    print("✅ 验证通过！")
                    bz.driver.switch_to.default_content()
                    break
                else:
                    print("🔁 验证仍未通过，继续下一轮")
            except Exception as e:
                print("🔁 无法判断是否成功，继续下一轮")

        else:
            print("❌ 已尝试 100 次验证码验证仍失败！")
            continue


def test():
    pass
    #     g = google.Google(bz)
    #     # 通过url 判断是否已经登录成功
    #     url = bz.获取当前URL()
    #     if "myaccount.google.com" in url:
    #         continue
    #
    #     # 判断是否需要 申诉 接码 #identifierNext > div > button > span
    #     if bz.元素存在("#headingText"):
    #         print("需要申诉")
    #         g.receive_code()
    #         break
    #
    #     g.login(acc["email"], acc["password"], acc["recovery"])
    #
    # bz.driver.quit()


if __name__ == "__main__":
    main()
