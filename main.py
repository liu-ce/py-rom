# -*- coding: utf-8 -*-
"""main.py

读取 config.json → 启动 MoreLogin → 附加浏览器 → 遍历 Excel 里的账号进行自动登录演示。
"""
import os
import re
import json
import time
import requests
from morelogin import start_env, create_env, delete_env, close_env
from browser import 附加浏览器
from load_accounts import load_accounts, update_account_status
from google_login import handle_google_login, switch_back_to_main_window
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
import google
import threading
import queue

CONFIG_PATH = "config.json"
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))



# ------------------------------------------------------------------
# 配置加载
# ------------------------------------------------------------------

def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

cfg = load_config()


def main():
    accounts = load_accounts(cfg["EXCEL_PATH"])
    if not accounts:
        raise ValueError("账号列表为空！")

    account_queue = queue.Queue()
    failed_accounts = []  # 失败账号优先队列
    failed_lock = threading.Lock()  # 保护失败账号列表的锁
    
    for acc in accounts:
        account_queue.put(acc)

    threads = []
    for _ in range(cfg["THREAD_NUM"]):  # 启动5个线程，也可以配置
        t = threading.Thread(target=worker, args=(account_queue, cfg, failed_accounts, failed_lock))
        t.start()
        threads.append(t)

    # 等待所有账号处理完成（包括失败重试的账号）
    while True:
        # 检查普通队列是否为空
        normal_queue_empty = account_queue.empty()
        
        # 检查失败账号列表是否为空
        with failed_lock:
            failed_queue_empty = len(failed_accounts) == 0
        
        # 如果两个队列都为空，且所有线程都空闲，说明处理完成
        if normal_queue_empty and failed_queue_empty:
            print("✅ 所有账号处理完成（包括重试）")
            break
        
        # 等待一段时间再检查
        time.sleep(1)
    
    # 等待所有线程结束
    for t in threads:
        t.join()



def worker(account_queue, cfg, failed_accounts, failed_lock):
    while True:
        acc = None
        from_queue = False  # 标记账号是否来自普通队列
        
        # 优先处理失败的账号
        with failed_lock:
            if failed_accounts:
                acc = failed_accounts.pop(0)  # 从头部取出失败的账号
                print(f"🔄 优先重试失败账号: {acc['email']} (剩余失败账号: {len(failed_accounts)})")
                from_queue = False
        
        # 如果没有失败账号，从普通队列获取
        if acc is None:
            try:
                acc = account_queue.get_nowait()  # 非阻塞取出
                from_queue = True
            except queue.Empty:
                break

        # 真正处理逻辑
        env_id = None
        try:
            account_type = "🔄 重试账号" if not from_queue else "🆕 新账号"
            print(f"{account_type} 开始处理账号: {acc['email']}")
            # 1.创建浏览器环境
            env_id = create_env(cfg)
            # 2.打开浏览器
            full_path = os.path.join(PROJECT_ROOT, cfg.get("CHROMEDRIVER_PATH"))
            print(full_path)
            debug_port = start_env(env_id, cfg)
            bz = 附加浏览器(debug_port, cfg.get("CHROMEDRIVER_PATH"))
            # 新流程：先进行WEMIX PLAY预登录
            print("🌐 开始WEMIX PLAY预登录流程...")
            if perform_wemix_prelogin(bz, acc):
                print("✅ WEMIX PLAY预登录完成")
            else:
                print("⚠️ WEMIX PLAY预登录失败，继续后续流程")
            
            # 打开pre-registration页面
            print("🌐 打开pre-registration页面...")
            bz.打开网页("https://romgoldenage.com/pre-registration")
            bz.关闭其他页签()
            time.sleep(3)
            
            # 勾选所有同意条款的checkbox
            if check_agreement_boxes(bz):
                print("✅ 已勾选所有同意条款")
                
                # 执行Google登录流程
                if click_google_button(bz):
                    # 处理Google登录
                    handle_google_login(bz.driver, acc)
                    # 切换回主窗口
                    switch_back_to_main_window(bz.driver)
                    
                    print("✅ 第一次Google登录流程完成")
                    
                    # 等待5秒
                    print("⏳ 等待1秒...")
                    time.sleep(1)
                    
                    # 点击Apply Pre-Registration按钮
                    if click_apply_preregistration_button(bz):
                        print("✅ Apply Pre-Registration按钮点击成功")
                        
                        # 再次处理Google登录 (直接检测账号选择) - 带重试机制
                        max_login_retries = 5  # 最多重试5次
                        coupon_code_success = False
                        
                        for retry_count in range(max_login_retries):
                            print(f"🔄 第{retry_count + 1}次尝试Google登录...")
                            
                            if click_google_button_no_wait(bz):
                                handle_google_login(bz.driver, acc)
                                switch_back_to_main_window(bz.driver)
                                print(f"✅ 第{retry_count + 1}次Google登录流程完成")
                                
                                # 检测Coupon code元素
                                print("⏳ 开始等待Coupon code元素...")
                                if wait_for_coupon_code(bz):
                                    print("✅ 检测到Coupon code，登录成功！")
                                    coupon_code_success = True
                                    break
                                else:
                                    print(f"❌ 第{retry_count + 1}次尝试未检测到Coupon code")

                            else:
                                print(f"❌ 第{retry_count + 1}次Google登录按钮点击失败")
                        
                        if coupon_code_success:
                            # 进行签到任务
                            if perform_checkin_tasks(bz, acc):
                                print("✅ 签到任务全部完成！")
                            else:
                                print("❌ 签到任务未完成，需要重新开始")
                        else:
                            print("❌ 所有重试后仍未检测到Coupon code，登录流程失败")
                            raise Exception("多次重试后Coupon code元素仍未出现，登录失败")
                    else:
                        print("❌ Apply Pre-Registration按钮点击失败")
                        
                else:
                    print("❌ Google登录按钮点击失败")
            else:
                print("❌ 勾选同意条款失败")
            

            # 处理完成，更新Excel状态
            update_account_status(cfg["EXCEL_PATH"], acc["row_index"], "完成")
            print(f"✅ 账号 {acc['email']} 处理完成")

        except Exception as e:
            # 不能让账号浪费了
            account_type = "重试账号" if not from_queue else "新账号"
            print(f"❌ {account_type}处理失败，加入优先重试队列: {acc['email']}")
            print(f"❌ 错误详情: {e}")
            with failed_lock:
                failed_accounts.insert(0, acc)  # 插入到头部，优先重试
                print(f"📋 当前失败账号队列长度: {len(failed_accounts)}，将优先重试")
        finally:
            # 无论是否异常删除环境
            if env_id:
                close_env(env_id, cfg)
                time.sleep(2)
                delete_env(env_id, cfg)
            
            # 只有从普通队列获取的账号才调用task_done()
            if from_queue:
                account_queue.task_done()


def perform_wemix_prelogin(bz, account):
    """执行WEMIX PLAY预登录流程"""
    try:
        print("🌐 打开WEMIX PLAY页面...")
        bz.打开网页("https://event.wemixplay.com/rom-wp")
        bz.关闭其他页签()
        time.sleep(2)
        
        # 步骤1: 重试点击Log In按钮，直到找到Google登录按钮
        max_login_retries = 5  # 最多重试5次
        login_success = False
        
        for retry in range(max_login_retries):
            print(f"🔄 尝试点击Log In按钮 (第{retry + 1}次)")
            
            if click_wemix_login_button(bz):
                print("✅ 已点击Log In按钮")
                time.sleep(2)  # 等待2秒后检查Google登录按钮
                
                # 步骤2: 检查Google登录按钮是否出现
                if click_wemix_google_button(bz):
                    print("✅ 已点击Google登录按钮")
                    login_success = True
                    break
                else:
                    print(f"⚠️ 第{retry + 1}次点击后未找到Google登录按钮，{2}秒后重试...")
                    if retry < max_login_retries - 1:  # 不是最后一次重试
                        time.sleep(2)  # 等待2秒再重试
            else:
                print(f"❌ 第{retry + 1}次点击Log In按钮失败")
                if retry < max_login_retries - 1:
                    time.sleep(2)
        
        if not login_success:
            print("❌ 多次重试后仍无法找到Google登录按钮")
            return False
        
        # 步骤3: 进行Google登录
        from google_login import handle_google_login, switch_back_to_main_window
        handle_google_login(bz.driver, account)
        switch_back_to_main_window(bz.driver)
        
        print("✅ WEMIX PLAY Google登录完成")
        
        # 步骤4: 处理注册确认弹框
        print("🔄 开始处理WEMIX PLAY注册确认弹框...")
        if handle_signup_modal(bz):
            print("✅ WEMIX PLAY注册确认弹框处理完成")
        else:
            print("⚠️ WEMIX PLAY注册确认弹框处理失败，继续后续流程")
        
        # 保持页面打开，不关闭
        print("✅ WEMIX PLAY预登录流程完成，保持页面打开")
        return True
        
    except Exception as e:
        print(f"❌ WEMIX PLAY预登录失败: {e}")
        return False

def click_wemix_login_button(bz):
    """点击WEMIX PLAY的Log In按钮"""
    try:
        print("🔍 查找Log In按钮...")
        selectors = [
            '//button[contains(@class, "btn-login") and contains(@class, "DesktopMenuSection_btn-login")]',
            '//button[contains(@class, "btn-login")]//span[text()="Log In"]/parent::button',
            '//span[contains(@class, "btn-login-text") and contains(@class, "DesktopMenuSection_btn-login-text") and text()="Log In"]/parent::button',
            '//span[text()="Log In"]/parent::button',
            '//button[contains(@class, "btn-login")]'
        ]
        
        for selector in selectors:
            try:
                button_element = bz.driver.find_element(By.XPATH, selector)
                if button_element.is_displayed() and button_element.is_enabled():
                    print(f"🎯 找到Log In按钮: {button_element.tag_name}, 类名: {button_element.get_attribute('class')}")
                    
                    # 滚动到按钮位置
                    bz.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button_element)
                    time.sleep(1)
                    
                    # 尝试多种点击方法
                    click_methods = [
                        # 方法1: 普通点击
                        lambda: button_element.click(),
                        # 方法2: JavaScript点击
                        lambda: bz.driver.execute_script("arguments[0].click();", button_element),
                        # 方法3: 聚焦后点击
                        lambda: (button_element.click() if bz.driver.execute_script("arguments[0].focus(); return true;", button_element) else None),
                        # 方法4: 模拟鼠标点击
                        lambda: bz.driver.execute_script("""
                            var element = arguments[0];
                            var event = new MouseEvent('click', {
                                view: window,
                                bubbles: true,
                                cancelable: true,
                                clientX: element.getBoundingClientRect().left + element.offsetWidth/2,
                                clientY: element.getBoundingClientRect().top + element.offsetHeight/2
                            });
                            element.dispatchEvent(event);
                        """, button_element),
                        # 方法5: 直接触发点击事件
                        lambda: bz.driver.execute_script("""
                            arguments[0].dispatchEvent(new Event('click', {bubbles: true}));
                        """, button_element)
                    ]
                    
                    for i, click_method in enumerate(click_methods, 1):
                        try:
                            print(f"🔄 尝试点击方法{i}...")
                            click_method()
                            print(f"✅ 找到并点击Log In按钮(方法{i})")
                            time.sleep(1)  # 等待响应
                            return True
                        except Exception as click_error:
                            print(f"⚠️ 点击方法{i}失败: {click_error}")
                            continue
                    
                    print("❌ 所有点击方法都失败了")
                    continue
            except Exception as find_error:
                print(f"⚠️ 选择器失败: {find_error}")
                continue
        
        print("❌ 未找到Log In按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击Log In按钮失败: {e}")
        return False

def click_wemix_google_button(bz):
    """点击WEMIX PLAY的Google登录按钮"""
    try:
        print("🔍 查找Google登录按钮...")
        selectors = [
            '//button[contains(@class, "btn-sns-login") and contains(@class, "btn-google") and contains(@class, "SigninModal_btn-sns-login")]',
            '//button[contains(@class, "btn-google") and contains(., "Continue with Google")]',
            '//button[contains(., "Continue with Google")]',
            '//button[contains(@class, "btn-google")]'
        ]
        
        for selector in selectors:
            try:
                google_element = bz.driver.find_element(By.XPATH, selector)
                if google_element.is_displayed():
                    bz.driver.execute_script("arguments[0].scrollIntoView(true);", google_element)
                    time.sleep(0.5)
                    bz.driver.execute_script("arguments[0].click();", google_element)
                    print("✅ 找到并点击Google登录按钮")
                    return True
            except:
                continue
        
        print("❌ 未找到Google登录按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击Google登录按钮失败: {e}")
        return False

def check_agreement_boxes(bz):
    """勾选所有同意条款的checkbox"""
    try:
        print("🔍 查找同意条款的checkbox...")
        
        # 查找所有包含同意文本的checkbox
        checkboxes = bz.driver.find_elements(By.XPATH, 
            "//label[contains(@class, 'form-check-box')]//em[contains(text(), \"I've read and agree to all of below.\")]/../preceding-sibling::input[@type='checkbox']")
        
        if not checkboxes:
            print("❌ 未找到同意条款的checkbox")
            return False
        
        print(f"🔍 找到 {len(checkboxes)} 个同意条款checkbox")
        
        success_count = 0
        for i, checkbox in enumerate(checkboxes):
            try:
                if not checkbox.is_selected():
                    # 滚动到checkbox位置
                    bz.driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
                    time.sleep(0.5)
                    
                    # 方法1: 尝试点击包含该checkbox的label
                    try:
                        label = checkbox.find_element(By.XPATH, "./parent::label")
                        label.click()
                        print(f"✅ 已勾选第 {i+1} 个checkbox (点击label)")
                        success_count += 1
                    except:
                        # 方法2: 使用JavaScript直接设置checkbox状态
                        try:
                            bz.driver.execute_script("arguments[0].click();", checkbox)
                            print(f"✅ 已勾选第 {i+1} 个checkbox (JS点击)")
                            success_count += 1
                        except:
                            # 方法3: 直接设置checked属性
                            bz.driver.execute_script("arguments[0].checked = true; arguments[0].dispatchEvent(new Event('change'));", checkbox)
                            print(f"✅ 已勾选第 {i+1} 个checkbox (JS设置)")
                            success_count += 1
                else:
                    print(f"ℹ️ 第 {i+1} 个checkbox已经被勾选")
                    success_count += 1
                    
                time.sleep(0.5)  # 短暂等待
                
            except Exception as e:
                print(f"❌ 勾选第 {i+1} 个checkbox失败: {e}")
                # 尝试最后的备用方案
                try:
                    bz.driver.execute_script("arguments[0].checked = true;", checkbox)
                    print(f"⚠️ 第 {i+1} 个checkbox使用备用方案勾选")
                    success_count += 1
                except:
                    print(f"❌ 第 {i+1} 个checkbox所有方案都失败")
        
        if success_count == len(checkboxes):
            print(f"✅ 成功勾选所有 {success_count} 个同意条款")
            return True
        else:
            print(f"⚠️ 只成功勾选了 {success_count}/{len(checkboxes)} 个checkbox")
            return success_count > 0  # 至少勾选了一个就算部分成功
            
    except Exception as e:
        print(f"❌ 查找同意条款checkbox失败: {e}")
        return False

def click_google_button(bz):
    """点击Google登录按钮"""
    max_wait_time = 30  # 最大等待30秒
    check_interval = 1  # 每秒检测一次
    
    for attempt in range(max_wait_time):
        try:
            # 方案1: 切换到iframe内部点击真正的按钮
            google_iframe = bz.driver.find_element(By.CLASS_NAME, "L5Fo6c-PQbLGe")
            print(f"✅ 找到Google iframe (等待了{attempt}秒)")
            
            # 切换到iframe内部
            bz.driver.switch_to.frame(google_iframe)
            print("✅ 已切换到Google iframe内部")
            
            # 在iframe内部查找并点击按钮
            try:
                # 等待iframe内容加载
                time.sleep(1)
                # 查找iframe内的按钮 (通常是div或button)
                inner_button = bz.driver.find_element(By.CSS_SELECTOR, "[role='button']")
                inner_button.click()
                print("✅ 成功点击iframe内部按钮")
                # 切换回主页面
                bz.driver.switch_to.default_content()
                # 等待弹窗出现
                return wait_for_popup(bz)
            except:
                try:
                    # 尝试其他可能的选择器
                    inner_button = bz.driver.find_element(By.TAG_NAME, "div")
                    bz.driver.execute_script("arguments[0].click();", inner_button)
                    print("✅ 成功点击iframe内部div")
                    # 切换回主页面
                    bz.driver.switch_to.default_content()
                    # 等待弹窗出现
                    return wait_for_popup(bz)
                except:
                    # 切换回主页面
                    bz.driver.switch_to.default_content()
                    print("❌ iframe内部点击失败，切换回主页面")
                
        except:
            # 方案2: 查找title包含Google的iframe
            try:
                google_iframe = bz.driver.find_element(By.XPATH, "//iframe[contains(@title, 'Google')]")
                print(f"✅ 通过title找到Google iframe (等待了{attempt}秒)")
                google_iframe.click()
                print("✅ 成功点击Google iframe(通过title)")
                time.sleep(5)
                return True
            except:
                pass
            
            # 方案3: 回退到原来的class查找
            try:
                google_btn = bz.driver.find_element(By.CLASS_NAME, "nsm7Bb-HzV7m-LgbsSe-BPrWId")
                print(f"✅ 找到原始Google按钮 (等待了{attempt}秒)")
                bz.driver.execute_script("arguments[0].click();", google_btn)
                print("✅ 成功点击原始Google按钮")
                return True
            except:
                pass
            
            # 没找到元素，等待1秒后重试
            if attempt < max_wait_time - 1:  # 不是最后一次尝试
                print(f"Google按钮未加载，等待中... ({attempt + 1}/{max_wait_time})")
                time.sleep(check_interval)
            else:
                print("❌ Google按钮等待超时，尝试最后的回退方案")
                break
    
    # 最后的回退方案：点击google-login容器
    try:
        google_btn = bz.driver.find_element(By.CLASS_NAME, "google-login")
        bz.driver.execute_script("arguments[0].click();", google_btn)
        print("✅ 回退点击google-login容器")
        return True
    except Exception as e:
        print(f"❌ 所有方案都失败: {e}")
        return False

def wait_for_popup(bz):
    """等待Google登录弹窗出现"""
    max_wait_time = 15  # 最大等待15秒
    initial_windows = len(bz.driver.window_handles)
    
    print(f"等待Google登录弹窗出现... (当前窗口数: {initial_windows})")
    
    for attempt in range(max_wait_time):
        # 方法1: 检测新窗口
        current_windows = len(bz.driver.window_handles)
        if current_windows > initial_windows:
            print(f"✅ 检测到新窗口弹窗! 窗口数从 {initial_windows} 增加到 {current_windows} (等待了{attempt + 1}秒)")
            return True
        
        # 方法2: 检测当前页面是否出现Google登录元素
        try:
            # 检测邮箱输入框
            if bz.driver.find_element(By.ID, "identifierId"):
                print(f"✅ 检测到Google登录页面! (等待了{attempt + 1}秒)")
                return True
        except:
            pass
        
        # 方法3: 检测账户选择界面
        try:
            # 检测账户选择相关元素
            account_selectors = [
                '//*[contains(text(), "選擇帳戶")]',  # 繁体中文
                '//*[contains(text(), "选择账户")]',  # 简体中文
                '//*[contains(text(), "Choose an account")]',  # 英文
                '//div[contains(@data-email, "@")]',  # 账户邮箱
                '//*[contains(@class, "BHzsHc")]'  # Google账户选择容器
            ]
            
            for selector in account_selectors:
                if bz.driver.find_element(By.XPATH, selector):
                    print(f"✅ 检测到Google账户选择界面! (等待了{attempt + 1}秒)")
                    return True
        except:
            pass
        
        # 方法4: 检测所有窗口中的Google登录内容
        try:
            current_handle = bz.driver.current_window_handle
            for handle in bz.driver.window_handles:
                try:
                    bz.driver.switch_to.window(handle)
                    current_url = bz.driver.current_url
                    if "accounts.google.com" in current_url:
                        print(f"✅ 在窗口中检测到Google登录页面! URL: {current_url} (等待了{attempt + 1}秒)")
                        return True
                except:
                    continue
            # 切换回原窗口
            bz.driver.switch_to.window(current_handle)
        except:
            pass
        
        # 方法5: 检测是否有Google登录相关文字
        try:
            if "accounts.google.com" in bz.driver.current_url or "登入" in bz.driver.page_source:
                print(f"✅ 检测到Google登录内容! (等待了{attempt + 1}秒)")
                return True
        except:
            pass
        
        if attempt < max_wait_time - 1:
            print(f"等待弹窗中... ({attempt + 1}/{max_wait_time})")
            time.sleep(1)
        else:
            print("❌ 等待弹窗超时，但可能已经在当前页面")
            break

    # 即使超时也检查一下是否已经有登录元素
    try:
        # 检查邮箱输入框
        if bz.driver.find_element(By.ID, "identifierId"):
            print("✅ 超时检查发现Google登录页面已存在")
            return True
    except:
        pass
    
    # 检查账户选择界面
    try:
        account_selectors = [
            '//*[contains(text(), "選擇帳戶")]',
            '//*[contains(text(), "选择账户")]', 
            '//*[contains(text(), "Choose an account")]',
            '//div[contains(@data-email, "@")]'
        ]
        for selector in account_selectors:
            if bz.driver.find_element(By.XPATH, selector):
                print("✅ 超时检查发现Google账户选择界面已存在")
                return True
    except:
        pass
    
    # 检查所有窗口中的Google内容
    try:
        current_handle = bz.driver.current_window_handle
        for handle in bz.driver.window_handles:
            try:
                bz.driver.switch_to.window(handle)
                if "accounts.google.com" in bz.driver.current_url:
                    print("✅ 超时检查在窗口中发现Google登录页面")
                    return True
            except:
                continue
        bz.driver.switch_to.window(current_handle)
    except:
        pass
    
    return False

def click_apply_preregistration_button(bz):
    """点击Apply Pre-Registration按钮"""
    try:
        print("🔍 查找Apply Pre-Registration按钮...")
        
        # 方法1: 通过文本内容查找按钮
        try:
            apply_btn = bz.driver.find_element(By.XPATH, "//button[contains(text(), 'Apply Pre-Registration') or contains(text(), 'Apply Pre-registration') or contains(text(), 'APPLY PRE-REGISTRATION')]")
            print("✅ 找到Apply Pre-Registration按钮(通过button文本)")
        except:
            # 方法2: 通过input按钮查找
            try:
                apply_btn = bz.driver.find_element(By.XPATH, "//input[@type='submit' and (contains(@value, 'Apply Pre-Registration') or contains(@value, 'Apply Pre-registration') or contains(@value, 'APPLY PRE-REGISTRATION'))]")
                print("✅ 找到Apply Pre-Registration按钮(通过input)")
            except:
                # 方法3: 通过任何包含该文本的可点击元素
                apply_btn = bz.driver.find_element(By.XPATH, "//*[contains(text(), 'Apply Pre-Registration') or contains(text(), 'Apply Pre-registration') or contains(text(), 'APPLY PRE-REGISTRATION')]")
                print("✅ 找到Apply Pre-Registration按钮(通过通用元素)")
        
        # 滚动到按钮位置
        bz.driver.execute_script("arguments[0].scrollIntoView(true);", apply_btn)
        time.sleep(0.5)
        
        # 尝试点击按钮
        try:
            apply_btn.click()
            print("✅ Apply Pre-Registration按钮点击成功(普通点击)")
            return True
        except:
            # 使用JavaScript点击
            bz.driver.execute_script("arguments[0].click();", apply_btn)
            print("✅ Apply Pre-Registration按钮点击成功(JS点击)")
            return True
            
    except Exception as e:
        print(f"❌ 查找或点击Apply Pre-Registration按钮失败: {e}")
        return False

def wait_for_coupon_code(bz):
    """等待Coupon code元素出现"""
    max_wait_time = 30  # 最大等待30秒
    
    print("🔍 开始检测Coupon code元素...")
    print(f"⏳ 最大等待时间: {max_wait_time}秒")
    
    for second in range(max_wait_time):
        try:
            # 查找 <dt>Coupon code</dt> 元素
            coupon_element = bz.driver.find_element(By.XPATH, "//dt[text()='Coupon code']")
            print(f"✅ 找到Coupon code元素! (等待了{second + 1}秒)")
            
            # 可以添加额外验证，确保元素可见
            if coupon_element.is_displayed():
                print("✅ Coupon code元素已显示，登录成功")
                return True
            else:
                print(f"⚠️ Coupon code元素存在但不可见，继续等待... ({second + 1}/{max_wait_time})")
                
        except Exception as e:
            # 元素不存在，继续等待
            if second < max_wait_time - 1:
                print(f"🔍 等待Coupon code出现... ({second + 1}/{max_wait_time})")
            else:
                print(f"❌ 等待Coupon code超时，元素未出现")
                
        time.sleep(1)
    
    print("❌ 30秒内未检测到Coupon code元素")
    return False

def perform_checkin_tasks(bz, account):
    """执行签到任务"""
    try:
        # 打开event02页面
        print("🌐 打开event02页面进行签到任务...")
        bz.打开网页("https://romgoldenage.com/event02")
        time.sleep(3)
        
        # 等待账号加载完成（btn-loading不再是active）
        if not wait_for_loading_complete(bz):
            print("❌ 账号加载超时")
            return False
        
        print("✅ 账号加载完成，开始签到任务")
        
        # 执行签到任务
        max_attempts = 3  # 最多尝试3次
        for attempt in range(max_attempts):
            print(f"🔄 第{attempt + 1}次尝试签到任务...")
            
            result = click_uncompleted_tasks(bz, account)
            if result == "task4_completed":
                # 第4个任务完成，直接返回成功
                print("✅ 第4个任务完成，签到流程结束！")
                time.sleep(2)
                return True
            elif result is True:
                # 其他任务正常完成，继续原有逻辑
                # 等5秒检查是否全部完成
                time.sleep(5)
                if check_all_tasks_completed(bz):
                    print("✅ 所有签到任务已完成！")
                    return True
                else:
                    print(f"⚠️ 第{attempt + 1}次尝试后仍有未完成任务")
            else:
                print(f"❌ 第{attempt + 1}次点击任务失败")
            
            if attempt < max_attempts - 1:
                print("🔄 刷新页面重新开始...")
                bz.driver.refresh()
                time.sleep(3)
                if not wait_for_loading_complete(bz):
                    print("❌ 重新加载超时")
                    return False
        
        print("❌ 达到最大尝试次数，签到任务未完成")
        return False
        
    except Exception as e:
        print(f"❌ 执行签到任务时出错: {e}")
        return False

def wait_for_loading_complete(bz):
    """等待账号加载完成（btn-loading不再是active）"""
    max_wait_time = 30
    print("⏳ 等待账号加载完成...")
    
    for second in range(max_wait_time):
        try:
            # 查找btn-loading元素
            loading_element = bz.driver.find_element(By.CSS_SELECTOR, "span.btn-loading")
            
            # 检查是否还有active class
            if "active" in loading_element.get_attribute("class"):
                if second < max_wait_time - 1:
                    print(f"🔄 账号加载中... ({second + 1}/{max_wait_time})")
                else:
                    print("❌ 账号加载超时")
                    return False
            else:
                print(f"✅ 账号加载完成 (用时{second + 1}秒)")
                return True
                
        except Exception as e:
            # 如果找不到loading元素，可能已经加载完成
            print(f"✅ 未找到loading元素，可能已加载完成 (用时{second + 1}秒)")
            return True
            
        time.sleep(1)
    
    return False

def click_uncompleted_tasks(bz, account):
    """点击未完成的签到任务"""
    try:
        # 查找所有process-cell元素
        task_cells = bz.driver.find_elements(By.CSS_SELECTOR, "ol.process-list li.process-cell")
        print(f"🔍 找到 {len(task_cells)} 个签到任务")
        
        # 显示当前所有任务的状态
        print("📋 当前任务状态:")
        for i, cell in enumerate(task_cells):
            if i == 4:  # 第5个任务跳过
                print(f"   任务 {i+1}: 跳过（无需处理）")
                continue
            cell_class = cell.get_attribute("class")
            status = "已完成" if "active" in cell_class else "未完成"
            print(f"   任务 {i+1}: {status}")
        
        uncompleted_count = 0
        completed_count = 0
        task4_completed = False  # 第4个任务完成标志
        
        for i, cell in enumerate(task_cells):
            try:
                # 第5个li无需点击，直接跳过
                if i == 4:  # 索引4代表第5个元素
                    print(f"ℹ️ 任务 {i+1} 无需点击，跳过")
                    continue
                
                cell_class = cell.get_attribute("class")
                
                # 第4个任务，无论是否完成都要点击
                if i == 3:  # 索引3代表第4个元素
                    print(f"🔘 第4个任务 - 无论状态如何都需要点击执行预注册")
                # 其他任务如果已完成就跳过
                elif "active" in cell_class:  
                    print(f"✅ 任务 {i+1} 已完成，跳过")
                    completed_count += 1
                    continue
                else:
                    print(f"🔘 点击任务 {i+1}...")
                
                # 滚动到元素位置
                bz.driver.execute_script("arguments[0].scrollIntoView(true);", cell)
                time.sleep(0.5)
                
                # 使用JavaScript点击避免被遮挡
                bz.driver.execute_script("arguments[0].click();", cell)
                uncompleted_count += 1
                
                # 等待页面/弹窗加载
                print("⏳ 等待页面加载并检测新窗口...")
                time.sleep(5)
                
                # 检测是否有新窗口并切换上下文
                initial_window_count = 1
                current_window_count = len(bz.driver.window_handles)
                
                if current_window_count > initial_window_count:
                    print(f"🔄 检测到新窗口，当前窗口数: {current_window_count}")
                    # 切换到新窗口
                    bz.driver.switch_to.window(bz.driver.window_handles[-1])
                    print(f"🌐 新窗口URL: {bz.driver.current_url}")
                    
                    # 第4个任务执行特殊操作
                    if i == 3:  # 索引3代表第4个元素
                        print("ℹ️ 第4个任务开始执行预注册操作")
                        # 执行第4个任务的特殊操作（已经在新窗口中）
                        try:
                            if handle_task4_simple_operations(bz, account):
                                print("✅ 第4个任务预注册操作完成")
                                print("🎉 第4个任务完成！签到流程结束，保持在当前窗口")
                                completed_count += 1
                                # 设置第4个任务完成标志，结束循环
                                task4_completed = True
                                break  # 跳出任务循环
                            else:
                                print("❌ 第4个任务预注册操作失败")
                                print("⚠️ 第4个任务失败，但仍然结束流程，保持在当前窗口")
                                task4_completed = True  # 即使失败也设置标志
                                break  # 跳出任务循环
                        except Exception as e:
                            print(f"❌ 第4个任务执行出错: {e}")
                            print("⚠️ 第4个任务出错，但仍然结束流程，保持在当前窗口")
                            task4_completed = True  # 即使出错也设置标志
                            break  # 跳出任务循环
                    else:
                        print(f"ℹ️ 任务 {i+1} 在新窗口中，即将关闭")
                        # 其他任务关闭新窗口
                        time.sleep(2)
                        bz.driver.close()
                        # 切换回主窗口
                        bz.driver.switch_to.window(bz.driver.window_handles[0])
                        print(f"✅ 任务 {i+1} 新窗口已关闭")
                        
                        # 重新获取主窗口中的任务元素进行状态检查（非第4个任务）
                        if i != 3:  # 第4个任务状态由自己的函数处理
                            try:
                                time.sleep(1)
                                updated_cells = bz.driver.find_elements(By.CSS_SELECTOR, "ol.process-list li.process-cell")
                                if i < len(updated_cells):
                                    updated_class = updated_cells[i].get_attribute("class")
                                    if "active" in updated_class:
                                        print(f"✅ 任务 {i+1} 点击后已完成")
                                        completed_count += 1
                                    else:
                                        print(f"⚠️ 任务 {i+1} 点击后状态未变化")
                                else:
                                    print(f"⚠️ 无法重新检查任务 {i+1} 状态")
                            except Exception as e:
                                print(f"⚠️ 重新检查任务 {i+1} 状态失败: {e}")
                else:
                    print(f"ℹ️ 任务 {i+1} 未打开新窗口")
                    # 如果没有新窗口，在当前页面检查状态（非第4个任务）
                    if i != 3:  # 第4个任务不需要在这里检查状态
                        time.sleep(1)
                        try:
                            # 重新获取元素状态
                            updated_cells = bz.driver.find_elements(By.CSS_SELECTOR, "ol.process-list li.process-cell")
                            if i < len(updated_cells):
                                updated_class = updated_cells[i].get_attribute("class")
                                if "active" in updated_class:
                                    print(f"✅ 任务 {i+1} 点击后已完成")
                                    completed_count += 1
                                else:
                                    print(f"⚠️ 任务 {i+1} 点击后状态未变化")
                            else:
                                print(f"⚠️ 无法重新检查任务 {i+1} 状态")
                        except Exception as e:
                            print(f"⚠️ 重新检查任务 {i+1} 状态失败: {e}")
                    else:
                        print("ℹ️ 第4个任务状态检查由专门函数处理")
                    
            except Exception as e:
                print(f"❌ 处理任务 {i+1} 时出错: {e}")
        
        # 如果第4个任务完成，不返回主窗口
        if task4_completed:
            print("🎉 第4个任务完成，保持在当前窗口，不返回主窗口")
            print(f"📊 已完成: {completed_count}, 已点击: {uncompleted_count}")
            return "task4_completed"  # 返回特殊值表示第4个任务完成
        
        # 其他情况确保最后在主窗口
        if len(bz.driver.window_handles) > 1:
            print("🔄 确保返回主窗口...")
            print(f"当前窗口数: {len(bz.driver.window_handles)}")
            bz.driver.switch_to.window(bz.driver.window_handles[0])
            print(f"🌐 主窗口URL: {bz.driver.current_url}")
        
        print(f"📊 已完成: {completed_count}, 已点击: {uncompleted_count}")
        return True
        
    except Exception as e:
        print(f"❌ 查找或点击任务时出错: {e}")
        return False

def close_popup_if_exists(bz):
    """关闭弹出的页面"""
    try:
        initial_window_count = 1  # 假设开始只有一个主窗口
        max_wait_time = 10  # 最多等待10秒检测新窗口
        
        # 等待新窗口出现
        for second in range(max_wait_time):
            current_windows = len(bz.driver.window_handles)
            
            if current_windows > initial_window_count:
                print(f"🔄 检测到新窗口，关闭弹窗... (等待了{second + 1}秒)")
                # 切换到新窗口
                bz.driver.switch_to.window(bz.driver.window_handles[-1])
                # 关闭新窗口
                bz.driver.close()
                # 切换回主窗口
                bz.driver.switch_to.window(bz.driver.window_handles[0])
                print("✅ 弹窗已关闭")
                return
            
            time.sleep(1)
        
        print("ℹ️ 10秒内未检测到新窗口，可能无需弹窗")
            
    except Exception as e:
        print(f"⚠️ 关闭弹窗时出错: {e}")

def check_all_tasks_completed(bz):
    """检查是否所有任务都已完成"""
    try:
        # 确保在主窗口检查
        if len(bz.driver.window_handles) > 1:
            print(f"🔄 切换到主窗口检查任务状态... (当前窗口数: {len(bz.driver.window_handles)})")
            bz.driver.switch_to.window(bz.driver.window_handles[0])
            time.sleep(2)  # 等待主窗口加载
            print(f"🌐 主窗口URL: {bz.driver.current_url}")
        
        task_cells = bz.driver.find_elements(By.CSS_SELECTOR, "ol.process-list li.process-cell")
        completed_count = 0
        required_count = len(task_cells) - 1  # 第5个li无需完成，所以减1
        
        for i, cell in enumerate(task_cells):
            # 第5个li(索引4)无需检查
            if i == 4:
                continue
                
            cell_class = cell.get_attribute("class")
            if "active" in cell_class:
                completed_count += 1
                print(f"✅ 最终检查 - 任务 {i+1}: 已完成")
            else:
                print(f"⚠️ 最终检查 - 任务 {i+1}: 未完成")
        
        print(f"📊 最终检查: {completed_count}/{required_count} 个任务已完成 (第5个任务无需完成)")
        return completed_count == required_count
        
    except Exception as e:
        print(f"❌ 检查任务完成状态时出错: {e}")
        return False

def handle_task4_operations(bz, account):
    """处理第4个任务的特殊操作：勾选checkbox → 预注册 → Google登录"""
    try:
        # 检查是否有新窗口打开
        if len(bz.driver.window_handles) > 1:
            print("🔄 切换到第4个任务的新窗口")
            bz.driver.switch_to.window(bz.driver.window_handles[-1])
            time.sleep(3)
        
        # 步骤1: 勾选checkbox
        if click_checkbox_task4(bz):
            print("✅ 已勾选checkbox")
            time.sleep(2)  # 等待checkbox状态更新
            
            # 步骤2: 点击预注册按钮
            if click_preregister_button(bz):
                print("✅ 已点击预注册按钮")
                time.sleep(3)  # 等待弹窗出现
                
                # 步骤3: 点击确认OK按钮
                if click_preregister_ok_button(bz):
                    print("✅ 已点击预注册确认OK按钮")
                    time.sleep(2)  # 等待确认完成
                else:
                    print("⚠️ 点击预注册确认OK按钮失败，继续流程")
            else:
                print("❌ 点击预注册按钮失败")
        else:
            print("❌ 勾选checkbox失败")
            
        return False
        
    except Exception as e:
        print(f"❌ 处理第4个任务操作时出错: {e}")
        return False

def handle_task4_simple_operations(bz, account):
    """简化的第4个任务处理：勾选checkbox → 预注册 → 简单Google登录"""
    try:
        print("🌐 已在第4个任务的新窗口中，开始执行简化操作...")
        print(f"🌐 当前URL: {bz.driver.current_url}")
        time.sleep(3)  # 等待页面完全加载
        # 步骤1: 勾选checkbox
        if click_checkbox_task4(bz):
            print("✅ 已勾选checkbox")
            time.sleep(2)  # 等待checkbox状态更新

            # 步骤2: 点击预注册按钮
            if click_preregister_button(bz):
                print("✅ 已点击预注册按钮")
                time.sleep(3)  # 等待弹窗出现
                
                # 步骤3: 点击确认OK按钮
                if click_preregister_ok_button(bz):
                    print("✅ 已点击预注册确认OK按钮")
                    time.sleep(2)  # 等待确认完成
                    
                    # 步骤4: 开始抽奖流程
                    if handle_lottery_process(bz):
                        print("✅ 抽奖流程完成")
                        return True
                    else:
                        print("⚠️ 抽奖流程失败，但注册已成功")
                        return True  # 注册成功就算完成
                else:
                    print("❌ 点击预注册确认OK按钮失败，无法继续抽奖流程")
                    return False
            else:
                print("❌ 点击预注册按钮失败")
                return False
        else:
            print("❌ 勾选checkbox失败")
            return False

    except Exception as e:
        print(f"❌ 处理第4个任务操作时出错: {e}")
        import traceback
        print(f"详细错误信息: {traceback.format_exc()}")
        return False

def simple_google_login_task4(bz, account):
    """第4个任务的简单Google登录：点击账号 → 同意 → 下一步"""
    try:
        print("🔄 开始简单Google登录流程...")
        time.sleep(5)  # 增加等待时间让登录界面完全加载
        
        # 检查并切换到正确的窗口/iframe
        if switch_to_google_login_context(bz):
            print("✅ 已切换到Google登录上下文")
        else:
            print("⚠️ 未找到Google登录窗口，在当前窗口继续")
        
        # 打印当前页面信息用于调试
        print(f"🌐 当前页面URL: {bz.driver.current_url}")
        print(f"🌐 当前页面标题: {bz.driver.title}")
        
        # 步骤1: 点击已有账号
        email = account['email']
        if click_existing_account_simple(bz, email):
            print(f"✅ 已点击账号: {email}")
            time.sleep(3)
            
            # 步骤2: 点击同意/继续按钮
            if click_agree_continue_button(bz):
                print("✅ 已点击同意/继续")
                time.sleep(2)
                
                # 步骤3: 如果还有下一步按钮，点击
                if click_next_step_if_exists(bz):
                    print("✅ 已点击下一步")
                    
                time.sleep(3)
                
                print("✅ 第4个任务Google登录流程完成")
                return True  # Google登录成功就算成功
            else:
                print("❌ 点击同意/继续失败")
        else:
            print("❌ 点击账号失败")
            
        return False
        
    except Exception as e:
        print(f"❌ 简单Google登录失败: {e}")
        import traceback
        print(f"详细错误信息: {traceback.format_exc()}")
        return False

def switch_to_google_login_context(bz):
    """切换到Google登录的正确上下文（窗口或iframe）"""
    try:
        # 方法1: 检查是否有新窗口
        if len(bz.driver.window_handles) > 1:
            print(f"🔄 检测到多个窗口({len(bz.driver.window_handles)}个)，切换到最新窗口")
            bz.driver.switch_to.window(bz.driver.window_handles[-1])
            time.sleep(2)
            print(f"🌐 切换后URL: {bz.driver.current_url}")
            
            # 检查是否是Google域名
            if "accounts.google.com" in bz.driver.current_url or "google.com" in bz.driver.current_url:
                print("✅ 成功切换到Google登录窗口")
                return True
        
        # 方法2: 检查是否有iframe
        try:
            iframes = bz.driver.find_elements(By.TAG_NAME, "iframe")
            print(f"🔍 找到 {len(iframes)} 个iframe")
            
            for i, iframe in enumerate(iframes):
                try:
                    bz.driver.switch_to.frame(iframe)
                    current_url = bz.driver.current_url
                    page_source = bz.driver.page_source[:200]  # 获取前200个字符
                    print(f"🌐 iframe {i+1} URL: {current_url}")
                    
                    # 检查是否包含Google登录相关内容
                    if ("google" in current_url.lower() or 
                        "選擇帳戶" in page_source or 
                        "选择账户" in page_source or
                        "Choose an account" in page_source):
                        print(f"✅ 找到Google登录iframe {i+1}")
                        return True
                    else:
                        # 切换回主内容
                        bz.driver.switch_to.default_content()
                except:
                    try:
                        bz.driver.switch_to.default_content()
                    except:
                        pass
                    continue
        except Exception as e:
            print(f"⚠️ 检查iframe时出错: {e}")
        
        print("ℹ️ 未找到Google登录特定上下文，使用当前页面")
        return False
        
    except Exception as e:
        print(f"❌ 切换Google登录上下文失败: {e}")
        return False

def handle_signup_modal(bz):
    """处理注册确认弹框流程"""
    try:
        print("🔄 开始处理注册确认弹框...")
        time.sleep(3)  # 等待弹框加载
        # 先确保切换到正确的窗口上下文
        if switch_back_to_main_context(bz):
            print("✅ 已切换回主页面上下文")
        else:
            print("⚠️ 切换上下文失败，在当前窗口继续")
        
        # 打印当前页面信息用于调试
        print(f"🌐 当前页面URL: {bz.driver.current_url}")
        print(f"🌐 当前页面标题: {bz.driver.title}")
        
        # 步骤1: 直接勾选两个checkbox
        if check_marketing_checkboxes(bz):
            print("✅ 已勾选营销同意选项")
            
            # 步骤2: 点击Next按钮
            if click_next_button(bz):
                print("✅ 已点击Next按钮")
                time.sleep(2)
                
                # 步骤3: 填写昵称和生日
                if fill_registration_form(bz):
                    print("✅ 注册表单填写完成")
                    return True
                else:
                    pass
            else:
                print("❌ 点击Next按钮失败")
        else:
            print("ℹ️ 未找到营销选项checkbox，可能不需要额外注册步骤")
            return True  # 没有弹框也算成功
            
        return False
        
    except Exception as e:
        print(f"❌ 处理注册确认弹框失败: {e}")
        return False

def switch_back_to_main_context(bz):
    """切换回主应用上下文（优先第4个任务窗口）"""
    try:
        print("🔄 尝试切换回主应用上下文...")
        
        # 如果有多个窗口，需要找到正确的应用窗口
        if len(bz.driver.window_handles) > 1:
            print(f"🔍 检测到多个窗口({len(bz.driver.window_handles)}个)")
            
            # 首先优先查找第4个任务窗口 (wemixplay.com)
            wemix_window = None
            rom_window = None
            
            for i, handle in enumerate(bz.driver.window_handles):
                try:
                    bz.driver.switch_to.window(handle)
                    current_url = bz.driver.current_url
                    print(f"🌐 窗口{i+1} URL: {current_url}")
                    
                    # 优先级1: 第4个任务窗口 (wemixplay.com)
                    if "wemixplay.com" in current_url:
                        wemix_window = (i+1, handle)
                        print(f"🎯 找到第4个任务窗口{i+1} (wemixplay)")
                    
                    # 优先级2: 主页面窗口 (romgoldenage.com)
                    elif "romgoldenage.com" in current_url:
                        rom_window = (i+1, handle)
                        print(f"🏠 找到主页面窗口{i+1} (romgoldenage)")
                        
                except Exception as e:
                    print(f"⚠️ 检查窗口{i+1}时出错: {e}")
                    continue
            
            # 优先选择第4个任务窗口
            if wemix_window:
                bz.driver.switch_to.window(wemix_window[1])
                print(f"✅ 切换到第4个任务窗口{wemix_window[0]} (wemixplay)")
                time.sleep(2)
                return True
            elif rom_window:
                bz.driver.switch_to.window(rom_window[1])
                print(f"✅ 切换到主页面窗口{rom_window[0]} (romgoldenage)")
                time.sleep(2)
                return True
            else:
                # 如果都没找到，默认切换到最后一个窗口（通常是任务窗口）
                print("⚠️ 未找到明确的应用窗口，切换到最后一个窗口")
                bz.driver.switch_to.window(bz.driver.window_handles[-1])
                time.sleep(2)
                return True
        else:
            # 只有一个窗口，检查是否在iframe中
            try:
                bz.driver.switch_to.default_content()
                print("✅ 已切换到默认内容")
                time.sleep(1)
                return True
            except:
                print("⚠️ 切换到默认内容失败")
                return False
        
    except Exception as e:
        print(f"❌ 切换回主页面上下文失败: {e}")
        return False

def click_signup_button(bz):
    """点击Sign Up按钮"""
    try:
        print("⏳ 等待Sign Up按钮出现...")
        max_wait = 20  # 最多等待20秒
        
        # 查找Sign Up按钮的选择器
        selectors = [
            '//span[contains(@class, "btn-label") and contains(@class, "RomPreRegisterationConfirmModal_btn-label") and text()="Sign Up"]',
            '//span[text()="Sign Up"]',
            '//button[contains(., "Sign Up")]',
            'span.RomPreRegisterationConfirmModal_btn-label__CrKhl',
            '//span[contains(@class, "btn-label") and contains(text(), "Sign Up")]',
            '//*[contains(text(), "Sign Up") and (name()="button" or name()="span")]',
            '//button[contains(@class, "btn") and contains(., "Sign Up")]',
            '//*[contains(text(), "Sign Up")]'
        ]
        
        # 每秒检测一次，最多等待20秒
        for wait_time in range(max_wait):
            try:
                # 先打印页面中所有可能的Sign Up相关元素（只在第一次和每5秒打印一次）
                if wait_time == 0 or wait_time % 5 == 0:
                    try:
                        signup_elements = bz.driver.find_elements(By.XPATH, "//*[contains(text(), 'Sign Up') or contains(text(), 'signup') or contains(@class, 'signup')]")
                        print(f"🔍 找到 {len(signup_elements)} 个包含Sign Up的元素")
                        for i, elem in enumerate(signup_elements[:3]):  # 只显示前3个
                            try:
                                text = elem.text[:30] if elem.text else "无文本"
                                tag = elem.tag_name
                                classes = elem.get_attribute("class") or "无class"
                                print(f"   元素{i+1}: <{tag}> text='{text}' class='{classes[:50]}'")
                            except:
                                pass
                    except Exception as e:
                        print(f"⚠️ 调试信息获取失败: {e}")
                
                # 尝试每个选择器
                for selector in selectors:
                    try:
                        if selector.startswith('//'):
                            btn = bz.driver.find_element(By.XPATH, selector)
                        else:
                            btn = bz.driver.find_element(By.CSS_SELECTOR, selector)
                        
                        # 检查元素是否可见
                        if btn.is_displayed():
                            # 如果是span元素，查找父button
                            click_target = btn
                            if btn.tag_name == 'span':
                                try:
                                    click_target = btn.find_element(By.XPATH, "./ancestor::button[1]")
                                except:
                                    click_target = btn  # 如果找不到父button就直接点span
                            
                            # 尝试点击
                            try:
                                click_target.click()
                            except:
                                bz.driver.execute_script("arguments[0].click();", click_target)
                            
                            print(f"✅ 找到并点击了Sign Up按钮 (等待了{wait_time}秒)")
                            return True
                    except:
                        continue
                
                # 如果没找到，等待1秒后继续
                if wait_time < max_wait - 1:
                    print(f"🔍 等待Sign Up按钮... ({wait_time+1}/{max_wait})")
                    time.sleep(1)
                else:
                    print("❌ 等待Sign Up按钮超时")
                    break
                    
            except Exception as e:
                print(f"⚠️ 第{wait_time+1}次检测时出错: {e}")
                if wait_time < max_wait - 1:
                    time.sleep(1)
                continue
                
        print("ℹ️ 未找到Sign Up按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击Sign Up按钮失败: {e}")
        return False

def check_marketing_checkboxes(bz):
    """勾选营销同意选项"""
    try:
        # 查找两个checkbox
        checkbox_selectors = [
            'input[name=":r1:"]',  # 营销邮件
            'input[name=":r2:"]'   # 推送消息
        ]
        
        success_count = 0
        for i, selector in enumerate(checkbox_selectors):
            try:
                checkbox = bz.driver.find_element(By.CSS_SELECTOR, selector)
                
                # 检查是否已经选中
                if not checkbox.is_selected():
                    # 尝试点击checkbox本身
                    try:
                        bz.driver.execute_script("arguments[0].click();", checkbox)
                        print(f"✅ 已勾选checkbox {i+1} (直接点击)")
                        success_count += 1
                    except:
                        # 尝试点击父label
                        try:
                            label = checkbox.find_element(By.XPATH, "./ancestor::label[1]")
                            bz.driver.execute_script("arguments[0].click();", label)
                            print(f"✅ 已勾选checkbox {i+1} (点击label)")
                            success_count += 1
                        except:
                            # 使用JavaScript设置
                            bz.driver.execute_script("arguments[0].checked = true; arguments[0].dispatchEvent(new Event('change'));", checkbox)
                            print(f"✅ 已勾选checkbox {i+1} (JS设置)")
                            success_count += 1
                else:
                    print(f"ℹ️ checkbox {i+1} 已经选中")
                    success_count += 1
                    
            except Exception as e:
                print(f"❌ 处理checkbox {i+1} 失败: {e}")
        
        return success_count == 2
        
    except Exception as e:
        print(f"❌ 勾选营销选项失败: {e}")
        return False

def click_next_button(bz):
    """点击Next按钮"""
    try:
        # 查找Next按钮
        selectors = [
            '//button[contains(@class, "btn-solid-cap") and contains(., "Next")]',
            '//button[text()="Next"]',
            'button.Button_btn-solid-cap__72atT',
            'button.btn-solid-cap'
        ]
        
        for selector in selectors:
            try:
                if selector.startswith('//'):
                    btn = bz.driver.find_element(By.XPATH, selector)
                else:
                    btn = bz.driver.find_element(By.CSS_SELECTOR, selector)
                
                bz.driver.execute_script("arguments[0].click();", btn)
                print("✅ 找到并点击了Next按钮")
                return True
            except:
                continue
                
        print("❌ 未找到Next按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击Next按钮失败: {e}")
        return False

def fill_registration_form(bz):
    """填写注册表单"""
    try:
        import random
        import string
        
        # 生成随机昵称 (10-12个字符，开头必须英文，全小写)
        nickname_length = random.randint(10, 12)
        first_char = random.choice(string.ascii_letters)
        remaining_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=nickname_length-1))
        nickname = (first_char + remaining_chars).lower()
        
        # 生成随机生日
        month = random.randint(1, 9)
        day = random.randint(10, 20)
        year = random.randint(1990, 1998)
        
        max_attempts = 3
        for attempt in range(max_attempts):
            print(f"🔄 第{attempt + 1}次尝试填写表单...")
            
            # 填写昵称
            if fill_nickname(bz, nickname):
                print(f"✅ 已填写昵称: {nickname}")
                
                # 填写生日
                if fill_birthday(bz, month, day, year):
                    print(f"✅ 已填写生日: {month}/{day}/{year}")
                    
                    # 点击Agree & Sign Up按钮
                    if click_agree_signup_button(bz):
                        print("✅ 已点击Agree & Sign Up按钮")
                        
                        # 等待2秒检查Sign Up是否消失
                        time.sleep(2)
                        if check_signup_success(bz):
                            print("✅ 注册成功，Sign Up按钮已消失")

                        else:
                            if attempt < max_attempts - 1:
                                print(f"⚠️ Sign Up按钮仍存在，尝试使用新昵称 (第{attempt + 1}次)")
                                # 重新生成昵称
                                nickname_length = random.randint(10, 12)
                                first_char = random.choice(string.ascii_letters)
                                remaining_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=nickname_length-1))
                                nickname = (first_char + remaining_chars).lower()
                                continue
                            else:
                                print("❌ 达到最大尝试次数，注册可能失败")
                                return False
                    else:
                        print("❌ 点击Agree & Sign Up按钮失败")
                else:
                    pass
            else:
                pass
            
            if attempt < max_attempts - 1:
                print("🔄 等待后重试...")
                time.sleep(2)
        
        return False
        
    except Exception as e:
        print(f"❌ 填写注册表单失败: {e}")
        return False

def fill_nickname(bz, nickname):
    """填写昵称"""
    try:
        nickname_input = bz.driver.find_element(By.CSS_SELECTOR, 'input[name="nickname"]')
        nickname_input.clear()
        nickname_input.send_keys(nickname)
        print(f"✅ 已输入昵称: {nickname}")
        return True
    except Exception as e:
        pass
        return False

def fill_birthday(bz, month, day, year):
    """填写生日 - 点击下拉框选择"""
    try:
        # 填写月份
        print(f"🔄 选择月份: {month}")
        if select_dropdown_option(bz, 'input[name="month"]', str(month)):
            print(f"✅ 已选择月份: {month}")
        else:
            return False
        
        time.sleep(0.5)
        
        # 填写日期
        print(f"🔄 选择日期: {day}")
        if select_dropdown_option(bz, 'input[name="day"]', str(day)):
            print(f"✅ 已选择日期: {day}")
        else:
            print(f"❌ 选择日期失败: {day}")
            return False
        
        time.sleep(0.5)
        
        # 填写年份
        print(f"🔄 选择年份: {year}")
        if select_dropdown_option(bz, 'input[name="year"]', str(year)):
            print(f"✅ 已选择年份: {year}")
        else:
            print(f"❌ 选择年份失败: {year}")
            return False
        
        print(f"✅ 已填写完整生日: {month}/{day}/{year}")
        return True
    except Exception as e:
        print(f"❌ 填写生日失败: {e}")
        return False

def select_dropdown_option(bz, input_selector, target_value):
    """通用下拉框选择函数"""
    try:
        # 月份数字到英文缩写的映射
        month_mapping = {
            "1": "JAN", "2": "FEB", "3": "MAR", "4": "APR",
            "5": "MAY", "6": "JUN", "7": "JUL", "8": "AUG", 
            "9": "SEP", "10": "OCT", "11": "NOV", "12": "DEC"
        }
        
        # 找到input元素
        input_element = bz.driver.find_element(By.CSS_SELECTOR, input_selector)
        
        # 多种方式尝试打开下拉框
        dropdown_opened = False
        
        # 方法1: 点击整个select-box容器
        try:
            select_box = input_element.find_element(By.XPATH, "./ancestor::div[contains(@class, 'select-box')][1]")
            bz.driver.execute_script("arguments[0].click();", select_box)
            time.sleep(1)
            # 检查下拉框是否出现
            try:
                bz.driver.find_element(By.CSS_SELECTOR, '.scroll-area')
                dropdown_opened = True
                print("✅ 下拉框已打开 (方法1)")
            except:
                pass
        except Exception as e:
            print(f"⚠️ 方法1打开下拉框失败: {e}")
        
        # 方法2: 点击label
        if not dropdown_opened:
            try:
                parent_label = input_element.find_element(By.XPATH, "./ancestor::label[1]")
                bz.driver.execute_script("arguments[0].click();", parent_label)
                time.sleep(1)
                try:
                    bz.driver.find_element(By.CSS_SELECTOR, '.scroll-area')
                    dropdown_opened = True
                    print("✅ 下拉框已打开 (方法2)")
                except:
                    pass
            except Exception as e:
                print(f"⚠️ 方法2打开下拉框失败: {e}")
        
        # 方法3: 点击value div
        if not dropdown_opened:
            try:
                value_div = input_element.find_element(By.XPATH, "./preceding-sibling::div[contains(@class, 'value')]")
                bz.driver.execute_script("arguments[0].click();", value_div)
                time.sleep(1)
                try:
                    bz.driver.find_element(By.CSS_SELECTOR, '.scroll-area')
                    dropdown_opened = True
                    print("✅ 下拉框已打开 (方法3)")
                except:
                    pass
            except Exception as e:
                print(f"⚠️ 方法3打开下拉框失败: {e}")
        
        if not dropdown_opened:
            return False
        
        # 确定要查找的目标文本
        search_text = target_value
        if "month" in input_selector:
            # 月份：转换为英文缩写
            search_text = month_mapping.get(target_value, target_value)
            print(f"🔄 月份转换: {target_value} -> {search_text}")
        elif "day" in input_selector:
            # 日期：直接使用数字
            search_text = target_value
            print(f"🔄 日期查找: {search_text}")
        elif "year" in input_selector:
            # 年份：直接使用数字
            search_text = target_value
            print(f"🔄 年份查找: {search_text}")
        
        # 等待下拉框完全加载
        time.sleep(1)
        
        # 先打印当前页面上所有的option元素用于调试
        try:
            # 查找所有可能的容器
            containers = bz.driver.find_elements(By.CSS_SELECTOR, '.scroll-area, .drawer, .SelectDropBox_contents__efL8X')
            print(f"🔍 找到 {len(containers)} 个下拉容器")
            
            for container in containers:
                options = container.find_elements(By.XPATH, './/div[contains(@class, "option")]')
                if options:
                    print(f"📋 容器中找到 {len(options)} 个选项")
                    for i, opt in enumerate(options[:15]):
                        try:
                            opt_text = opt.text.strip()
                            z3print(f"   选项{i+1}: '{opt_text}'")
                        except:
                            pass
                    break
        except Exception as debug_e:
            print(f"⚠️ 获取调试信息失败: {debug_e}")
        
        # 等待并查找目标选项
        max_wait = 5
        option_found = False
        
        for wait in range(max_wait):
            try:
                # 多种查找策略
                selectors = [
                    f'//div[@class="option Option_option__S__7w" and text()="{search_text}"]',
                    f'//div[contains(@class, "option") and contains(@class, "Option_option__S__7w") and text()="{search_text}"]',
                    f'//div[@role="button" and text()="{search_text}"]',
                    f'//*[text()="{search_text}" and contains(@class, "option")]'
                ]
                
                for selector in selectors:
                    try:
                        options = bz.driver.find_elements(By.XPATH, selector)
                        print(f"🔍 选择器 {selector} 找到 {len(options)} 个匹配")
                        
                        for option in options:
                            if option.is_displayed() and option.is_enabled():
                                print(f"✅ 找到可点击的选项: {search_text}")
                                
                                # 滚动到选项位置
                                bz.driver.execute_script("arguments[0].scrollIntoView(true);", option)
                                time.sleep(0.3)
                                
                                # 多种点击方式
                                click_success = False
                                
                                # 方法1: 普通点击
                                try:
                                    option.click()
                                    print("✅ 选项点击成功 (方法1)")
                                    click_success = True
                                except Exception as e1:
                                    print(f"⚠️ 方法1点击失败: {e1}")
                                    
                                    # 方法2: JavaScript点击
                                    try:
                                        bz.driver.execute_script("arguments[0].click();", option)
                                        print("✅ 选项点击成功 (方法2-JS)")
                                        click_success = True
                                    except Exception as e2:
                                        print(f"⚠️ 方法2点击失败: {e2}")
                                        
                                        # 方法3: 触发事件
                                        try:
                                            bz.driver.execute_script("""
                                                arguments[0].dispatchEvent(new MouseEvent('click', {
                                                    view: window,
                                                    bubbles: true,
                                                    cancelable: true
                                                }));
                                            """, option)
                                            print("✅ 选项点击成功 (方法3-事件)")
                                            click_success = True
                                        except Exception as e3:
                                            print(f"⚠️ 方法3点击失败: {e3}")
                                
                                if click_success:
                                    time.sleep(1)  # 等待下拉框关闭
                                    option_found = True
                                    return True
                                    
                    except Exception as selector_e:
                        print(f"⚠️ 选择器失败: {selector_e}")
                        continue
                
                if option_found:
                    break
                    
                if wait < max_wait - 1:
                    print(f"🔄 等待选项出现... ({wait+1}/{max_wait})")
                    time.sleep(1)
                    
            except Exception as wait_e:
                print(f"⚠️ 等待过程出错: {wait_e}")
                continue
        
        if not option_found:
            print(f"❌ 未找到或无法点击选项: {search_text}")
        
        return False
        
    except Exception as e:
        print(f"❌ 下拉框选择失败: {e}")
        return False

def click_agree_signup_button(bz):
    """点击Agree & Sign Up按钮"""
    try:
        selectors = [
            '//button[contains(., "Agree") and contains(., "Sign Up")]',
            '//button[contains(@class, "btn-solid-cap") and contains(., "Agree")]',
            'button.btn-solid-cap'
        ]
        
        for selector in selectors:
            try:
                if selector.startswith('//'):
                    btn = bz.driver.find_element(By.XPATH, selector)
                else:
                    btn = bz.driver.find_element(By.CSS_SELECTOR, selector)
                
                bz.driver.execute_script("arguments[0].click();", btn)
                print("✅ 找到并点击了Agree & Sign Up按钮")
                return True
            except:
                continue
                
        print("❌ 未找到Agree & Sign Up按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击Agree & Sign Up按钮失败: {e}")
        return False

def check_signup_success(bz):
    """检查注册是否成功（Sign Up按钮是否消失）"""
    try:
        # 尝试查找Sign Up相关按钮
        signup_elements = bz.driver.find_elements(By.XPATH, '//button[contains(., "Sign Up") or contains(., "Agree")]')
        if len(signup_elements) == 0:
            print("✅ Sign Up按钮已消失，注册成功")
            return True
        else:
            print(f"⚠️ 仍有 {len(signup_elements)} 个Sign Up相关按钮存在")
            return False
    except Exception as e:
        print(f"⚠️ 检查注册状态时出错: {e}")
        return True  # 出错时假设成功

def click_existing_account_simple(bz, target_email):
    """简单点击现有账户"""
    try:
        print(f"🔍 查找账号: {target_email}")
        
        # 先打印页面信息用于调试
        try:
            print(f"🌐 当前页面标题: {bz.driver.title}")
            print(f"🌐 当前页面URL: {bz.driver.current_url}")
            
            # 查找页面中所有可能的账户元素并打印
            all_possible_accounts = bz.driver.find_elements(By.XPATH, "//*[contains(@data-email, '@') or contains(text(), '@')]")
            print(f"🔍 找到 {len(all_possible_accounts)} 个包含邮箱的元素")
            for i, elem in enumerate(all_possible_accounts[:5]):  # 只显示前5个
                try:
                    text = elem.text[:50] if elem.text else "无文本"
                    data_email = elem.get_attribute("data-email") or "无data-email"
                    print(f"   元素{i+1}: text='{text}', data-email='{data_email}'")
                except:
                    pass
        except Exception as e:
            print(f"⚠️ 调试信息获取失败: {e}")
        
        # 等待账号加载出现
        max_wait_time = 10
        for second in range(max_wait_time):
            try:
                # 方法1: 通过data-email属性查找
                try:
                    account_element = bz.driver.find_element(By.CSS_SELECTOR, f'[data-email="{target_email}"]')
                    # 尝试点击元素本身或父容器
                    try:
                        bz.driver.execute_script("arguments[0].click();", account_element)
                        print(f"✅ 通过data-email直接点击账户: {target_email}")
                        return True
                    except:
                        # 尝试点击父容器
                        account_container = account_element.find_element(By.XPATH, "./ancestor::*[@role='button' or contains(@class, 'BHzsHc') or contains(@class, 'RP2QDe')][1]")
                        bz.driver.execute_script("arguments[0].click();", account_container)
                        print(f"✅ 通过data-email找到并点击了账户容器: {target_email}")
                        return True
                except:
                    pass
                
                # 方法2: 通过yAlK0b class查找（用户提供的具体class）
                try:
                    email_element = bz.driver.find_element(By.CSS_SELECTOR, f'div.yAlK0b[data-email="{target_email}"]')
                    # 点击父容器
                    account_container = email_element.find_element(By.XPATH, "./ancestor::*[@role='button' or contains(@class, 'BHzsHc') or contains(@class, 'RP2QDe')][1]")
                    bz.driver.execute_script("arguments[0].click();", account_container)
                    print(f"✅ 通过yAlK0b class找到并点击了账户: {target_email}")
                    return True
                except:
                    pass
                
                # 方法3: 通过邮箱文本查找
                try:
                    email_element = bz.driver.find_element(By.XPATH, f"//*[text()='{target_email}']")
                    # 点击元素本身或父容器
                    try:
                        bz.driver.execute_script("arguments[0].click();", email_element)
                        print(f"✅ 通过文本直接点击账户: {target_email}")
                        return True
                    except:
                        account_container = email_element.find_element(By.XPATH, "./ancestor::*[@role='button' or @data-identifier][1]")
                        bz.driver.execute_script("arguments[0].click();", account_container)
                        print(f"✅ 通过文本找到并点击了账户容器: {target_email}")
                        return True
                except:
                    pass
                
                # 方法4: 查找包含该邮箱的任何元素
                try:
                    email_element = bz.driver.find_element(By.XPATH, f"//*[contains(text(), '{target_email}')]")
                    # 点击元素本身或父容器
                    try:
                        bz.driver.execute_script("arguments[0].click();", email_element)
                        print(f"✅ 通过包含文本直接点击账户: {target_email}")
                        return True
                    except:
                        account_container = email_element.find_element(By.XPATH, "./ancestor::*[@role='button' or @data-identifier or contains(@onclick, '') or contains(@class, 'click')][1]")
                        bz.driver.execute_script("arguments[0].click();", account_container)
                        print(f"✅ 通过包含文本找到并点击了账户容器: {target_email}")
                        return True
                except:
                    pass
                
                # 方法5: 根据截图，尝试查找账户行（可能包含用户名和邮箱）
                try:
                    # 查找包含目标邮箱的div，然后向上查找可点击的父元素
                    xpath_queries = [
                        f"//div[contains(text(), '{target_email}')]/ancestor::div[@role='button']",
                        f"//div[contains(text(), '{target_email}')]/ancestor::div[contains(@class, 'account') or contains(@class, 'user')]",
                        f"//div[contains(text(), '{target_email}')]/parent::div",
                        f"//*[contains(text(), '{target_email}')]/ancestor::*[contains(@onclick, '') or @role='button'][1]"
                    ]
                    
                    for xpath in xpath_queries:
                        try:
                            account_container = bz.driver.find_element(By.XPATH, xpath)
                            bz.driver.execute_script("arguments[0].click();", account_container)
                            print(f"✅ 通过xpath找到并点击了账户: {target_email}")
                            return True
                        except:
                            continue
                except:
                    pass
                
                # 如果没找到，等待1秒后重试
                if second < max_wait_time - 1:
                    print(f"⏳ 等待账号加载... ({second + 1}/{max_wait_time})")
                    time.sleep(1)
                else:
                    print("❌ 等待超时，尝试点击第一个可用账户")
                    break
                    
            except Exception as e:
                if second < max_wait_time - 1:
                    print(f"⏳ 查找账号时出错，继续等待... ({second + 1}/{max_wait_time})")
                    time.sleep(1)
                else:
                    break
        
        # 最后尝试点击第一个可用账户
        try:
            account_containers = bz.driver.find_elements(By.CSS_SELECTOR, "[data-identifier], .BHzsHc, .RP2QDe, [role='button']")
            if account_containers:
                bz.driver.execute_script("arguments[0].click();", account_containers[0])
                print("✅ 点击了第一个可用账户")
                return True
            else:
                print("❌ 未找到任何可点击的账户容器")
        except Exception as e:
            print(f"❌ 点击第一个可用账户失败: {e}")
            
        print("❌ 所有方法都未找到可点击的账户")
        return False
        
    except Exception as e:
        print(f"❌ 点击账户失败: {e}")
        return False

def click_agree_continue_button(bz):
    """点击同意/继续按钮"""
    try:
        # 方法1: 查找"Continue"按钮
        try:
            btn = bz.driver.find_element(By.XPATH, "//span[text()='Continue']/parent::button")
            bz.driver.execute_script("arguments[0].click();", btn)
            print("✅ 点击Continue按钮")
            return True
        except:
            pass
        
        # 方法2: 查找"允许"按钮
        try:
            btn = bz.driver.find_element(By.XPATH, "//span[text()='Allow']/parent::button")
            bz.driver.execute_script("arguments[0].click();", btn)
            print("✅ 点击Allow按钮")
            return True
        except:
            pass
        
        # 方法3: 查找"同意"按钮
        try:
            btn = bz.driver.find_element(By.XPATH, "//span[contains(text(), '同意')]/parent::button")
            bz.driver.execute_script("arguments[0].click();", btn)
            print("✅ 点击同意按钮")
            return True
        except:
            pass
        
        # 方法4: 通过jsname查找按钮
        try:
            btn = bz.driver.find_element(By.CSS_SELECTOR, "[jsname='LgbsSe']")
            bz.driver.execute_script("arguments[0].click();", btn)
            print("✅ 点击jsname按钮")
            return True
        except:
            pass
            
        print("ℹ️ 未找到同意/继续按钮")
        return True  # 可能不需要额外点击
        
    except Exception as e:
        print(f"❌ 点击同意/继续按钮失败: {e}")
        return False

def click_next_step_if_exists(bz):
    """如果存在下一步按钮则点击"""
    try:
        # 查找各种可能的下一步按钮
        next_buttons = [
            "//span[text()='Next']/parent::button",
            "//span[text()='下一步']/parent::button", 
            "//span[text()='Continue']/parent::button",
            "//button[contains(text(), 'Next')]",
            "//button[contains(text(), '下一步')]"
        ]
        
        for xpath in next_buttons:
            try:
                btn = bz.driver.find_element(By.XPATH, xpath)
                bz.driver.execute_script("arguments[0].click();", btn)
                print("✅ 点击了下一步按钮")
                return True
            except:
                continue
                
        print("ℹ️ 没有找到下一步按钮")
        return True  # 不是必须的步骤
        
    except Exception as e:
        print(f"❌ 点击下一步按钮失败: {e}")
        return True  # 不影响主流程

def handle_task4_operations_in_window(bz, account):
    """处理第4个任务的特殊操作（已经在新窗口中）：勾选checkbox → 预注册"""
    try:
        print("🌐 已在第4个任务的新窗口中，开始执行操作...")
        print(f"🌐 当前URL: {bz.driver.current_url}")
        time.sleep(3)  # 等待页面完全加载
        
        # 步骤1: 勾选checkbox
        if not click_checkbox_task4(bz):
            print("❌ 勾选checkbox失败")
            return False
            
        print("✅ 已勾选checkbox")
        time.sleep(2)  # 等待checkbox状态更新
        
        # 步骤2: 点击预注册按钮
        if not click_preregister_button(bz):
            print("❌ 点击预注册按钮失败")
            return False
            
        print("✅ 已点击预注册按钮")
        time.sleep(3)  # 等待状态更新
        
        # 由于之前已经在WEMIX PLAY完成了Google登录，这里不需要再次登录
        print("ℹ️ 跳过Google登录步骤（已在WEMIX PLAY完成登录）")
        print(f"🌐 当前URL: {bz.driver.current_url}")
        return True
        
    except Exception as e:
        print(f"❌ 第4个任务操作失败: {e}")
        return False

def click_checkbox_task4(bz):
    """勾选第4个任务页面的checkbox"""
    try:
        # 方法1: 直接点击checkbox input
        checkbox = bz.driver.find_element(By.CSS_SELECTOR, 'input[type="checkbox"][name=":r0:"]')
        bz.driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
        time.sleep(0.5)
        bz.driver.execute_script("arguments[0].click();", checkbox)
        print("✅ 已勾选checkbox(方法1)")
        return True
    except:
        try:
            # 方法2: 点击包含checkbox的label
            label = bz.driver.find_element(By.XPATH, '//label[.//input[@type="checkbox" and @name=":r0:"]]')
            bz.driver.execute_script("arguments[0].scrollIntoView(true);", label)
            time.sleep(0.5)
            bz.driver.execute_script("arguments[0].click();", label)
            print("✅ 已勾选checkbox(方法2)")
            return True
        except:
            try:
                # 方法3: 通过span点击
                span_check = bz.driver.find_element(By.CSS_SELECTOR, 'span.ico-check.CheckBox_ico-check__mc8_N')
                bz.driver.execute_script("arguments[0].scrollIntoView(true);", span_check)
                time.sleep(0.5)
                bz.driver.execute_script("arguments[0].click();", span_check)
                print("✅ 已勾选checkbox(方法3)")
                return True
            except Exception as e:
                print(f"❌ 勾选checkbox失败: {e}")
                return False

def click_preregister_ok_button(bz):
    """点击预注册成功后的确认OK按钮"""
    try:
        print("🔍 查找预注册确认OK按钮...")
        
        # 等待弹窗完全出现
        time.sleep(1)
        
        # 多种OK按钮选择器
        ok_selectors = [
            '//button[contains(@class, "btn-confirm") and contains(@class, "RomPreRegisterationSuceessModal_btn-confirm")]//span[text()="OK"]',
            '//span[contains(@class, "btn-label") and contains(@class, "RomPreRegisterationSuceessModal_btn-label") and text()="OK"]/parent::button',
            '//button[contains(@class, "btn-confirm")]//span[text()="OK"]',
            '//span[text()="OK"]/parent::button[contains(@class, "btn-confirm")]',
            '//button[contains(@class, "RomPreRegisterationSuceessModal_btn-confirm")]',
            '//span[text()="OK"]'
        ]
        
        for i, selector in enumerate(ok_selectors, 1):
            try:
                ok_element = bz.driver.find_element(By.XPATH, selector)
                if ok_element.is_displayed() and ok_element.is_enabled():
                    print(f"🎯 找到预注册确认OK按钮(方法{i}): {ok_element.tag_name}")
                    
                    # 滚动到按钮位置
                    bz.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", ok_element)
                    time.sleep(0.5)
                    
                    # 尝试多种点击方法
                    click_methods = [
                        # 方法1: 普通点击
                        lambda: ok_element.click(),
                        # 方法2: JavaScript点击
                        lambda: bz.driver.execute_script("arguments[0].click();", ok_element),
                        # 方法3: 如果是span，找父button
                        lambda: (lambda button: bz.driver.execute_script("arguments[0].click();", button))(
                            ok_element.find_element(By.XPATH, "./ancestor::button[1]") if ok_element.tag_name == 'span' else ok_element
                        )
                    ]
                    
                    for j, click_method in enumerate(click_methods, 1):
                        try:
                            print(f"🔄 尝试点击OK按钮(方法{j})...")
                            click_method()
                            print(f"✅ 预注册确认OK按钮点击成功(方法{j})")
                            return True
                        except Exception as click_error:
                            print(f"⚠️ 点击方法{j}失败: {click_error}")
                            continue
                    
                    print("❌ 所有点击方法都失败了")
                    continue
                    
            except Exception as find_error:
                continue  # 尝试下一个选择器
        
        print("❌ 未找到预注册确认OK按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击预注册确认OK按钮失败: {e}")
        return False

def click_preregister_button(bz):
    """点击预注册按钮"""
    try:
        # 方法1: 通过class查找
        btn = bz.driver.find_element(By.CSS_SELECTOR, 'button.btn-pre-now.DesktopPreRegistrationSection_btn-pre-now__rBkUY')
        bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        time.sleep(0.5)
        bz.driver.execute_script("arguments[0].click();", btn)
        print("✅ 已点击预注册按钮(方法1)")
        return True
    except:
        try:
            # 方法2: 通过文本查找
            btn = bz.driver.find_element(By.XPATH, '//button[.//span[text()="PRE-REGISTER NOW"]]')
            bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.5)
            bz.driver.execute_script("arguments[0].click();", btn)
            print("✅ 已点击预注册按钮(方法2)")
            return True
        except:
            try:
                # 方法3: 通过部分class查找
                btn = bz.driver.find_element(By.CSS_SELECTOR, 'button.btn-pre-now')
                bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.5)
                bz.driver.execute_script("arguments[0].click();", btn)
                print("✅ 已点击预注册按钮(方法3)")
                return True
            except Exception as e:
                print(f"❌ 点击预注册按钮失败: {e}")
                return False

def click_google_login_button_task4(bz):
    """点击Google登录按钮"""
    try:
        # 方法1: 通过class查找
        btn = bz.driver.find_element(By.CSS_SELECTOR, 'button.btn-login-google')
        bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        time.sleep(0.5)
        bz.driver.execute_script("arguments[0].click();", btn)
        print("✅ 已点击Google登录按钮(方法1)")
        return True
    except:
        try:
            # 方法2: 通过文本查找
            btn = bz.driver.find_element(By.XPATH, '//button[.//span[text()="Continue with Google"]]')
            bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(0.5)
            bz.driver.execute_script("arguments[0].click();", btn)
            print("✅ 已点击Google登录按钮(方法2)")
            return True
        except:
            try:
                # 方法3: 通过包含Google的按钮查找
                btn = bz.driver.find_element(By.XPATH, '//button[contains(., "Google")]')
                bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.5)
                bz.driver.execute_script("arguments[0].click();", btn)
                print("✅ 已点击Google登录按钮(方法3)")
                return True
            except:
                try:
                    # 方法4: 通过span文本的父元素查找
                    btn = bz.driver.find_element(By.XPATH, '//span[contains(text(), "Continue with Google")]/parent::button')
                    bz.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(0.5)
                    bz.driver.execute_script("arguments[0].click();", btn)
                    print("✅ 已点击Google登录按钮(方法4)")
                    return True
                except Exception as e:
                    print(f"❌ 点击Google登录按钮失败: {e}")
                    return False

def handle_lottery_process(bz):
    """处理抽奖流程 - 循环抽奖直到券数归零"""
    try:
        print("🎰 开始抽奖流程...")
        max_lottery_rounds = 10  # 最多抽奖10轮，避免无限循环
        
        for round_num in range(max_lottery_rounds):
            print(f"🔄 开始第 {round_num + 1} 轮抽奖...")
            
            # 步骤1: 检测抽奖券数量
            lottery_count = get_lottery_count(bz)
            print(f"🎫 当前抽奖券数量: {lottery_count}")
            
            if lottery_count == 0:
                print("🎉 抽奖券已全部用完，抽奖流程完成！")
                return True
            elif lottery_count > 0:
                print(f"📝 开始抽取第 {round_num + 1} 张抽奖券...")
                
                # 步骤2: 点击开始抽奖Submit按钮
                if not click_lottery_submit_button(bz):
                    print("❌ 点击开始抽奖按钮失败")
                    break
                print("✅ 已点击开始抽奖按钮")
                time.sleep(2)  # 等待2秒
                
                # 步骤3: 点击Auto-Pick摇号按钮
                if not click_auto_pick_button(bz):
                    print("❌ 点击Auto-Pick按钮失败")
                    break
                print("✅ 已点击Auto-Pick按钮")
                time.sleep(1)  # 等待1秒
                
                # 步骤4: 点击提交Submit按钮
                if not click_final_submit_button(bz):
                    print("❌ 点击最终提交按钮失败")
                    break
                print("✅ 已点击最终提交按钮")
                
                # 步骤5: 点击确认OK按钮
                if not click_confirm_ok_button(bz):
                    print("❌ 点击确认OK按钮失败")
                    break
                print("✅ 已点击确认OK按钮")
                
                print(f"✅ 第 {round_num + 1} 轮抽奖完成")
                
                # 等待页面更新后继续下一轮
                time.sleep(2)
                
            else:
                print("⚠️ 无法检测抽奖券数量，可能出现异常")
                break
        
        # 最终检查抽奖券数量
        final_count = get_lottery_count(bz)
        if final_count == 0:
            print("🎉 所有抽奖券已用完，抽奖流程全部完成！")
            return True
        else:
            print(f"⚠️ 抽奖结束，剩余 {final_count} 张抽奖券未使用")
            print("⚠️ 可能已达到最大抽奖轮数限制或遇到其他问题")
            return True  # 仍然返回成功，避免卡住整个流程
        
    except Exception as e:
        print(f"❌ 抽奖流程失败: {e}")
        return False

def click_ok_button(bz):
    """点击OK按钮"""
    try:
        print("⏳ 等待OK按钮出现...")
        max_wait = 10  # 最多等待10秒
        
        for wait_time in range(max_wait):
            try:
                selectors = [
                    '//button[contains(@class, "btn-confirm") and contains(@class, "RomPreRegisterationSuceessModal_btn-confirm")]//span[text()="OK"]',
                    '//span[contains(@class, "btn-label") and contains(@class, "RomPreRegisterationSuceessModal_btn-label") and text()="OK"]',
                    '//button[contains(@class, "btn-confirm")]//span[text()="OK"]',
                    '//span[text()="OK"]'
                ]
                
                for selector in selectors:
                    try:
                        ok_element = bz.driver.find_element(By.XPATH, selector)
                        if ok_element.is_displayed():
                            # 如果是span，找父button
                            if ok_element.tag_name == 'span':
                                try:
                                    button = ok_element.find_element(By.XPATH, "./ancestor::button[1]")
                                    bz.driver.execute_script("arguments[0].click();", button)
                                except:
                                    bz.driver.execute_script("arguments[0].click();", ok_element)
                            else:
                                bz.driver.execute_script("arguments[0].click();", ok_element)
                            
                            print(f"✅ 找到并点击OK按钮 (等待了{wait_time}秒)")
                            return True
                    except:
                        continue
                
                if wait_time < max_wait - 1:
                    print(f"🔍 等待OK按钮... ({wait_time+1}/{max_wait})")
                    time.sleep(1)
                
            except Exception as e:
                if wait_time < max_wait - 1:
                    time.sleep(1)
                continue
        
        print("❌ 等待OK按钮超时")
        return False
        
    except Exception as e:
        print(f"❌ 点击OK按钮失败: {e}")
        return False

def get_lottery_count(bz):
    """获取抽奖券数量"""
    try:
        print("🔍 检测抽奖券数量...")
        selectors = [
            '//div[contains(@class, "count") and contains(@class, "DesktopReferralShare_count")]',
            '//div[contains(@class, "count")]'
        ]
        
        for selector in selectors:
            try:
                count_element = bz.driver.find_element(By.XPATH, selector)
                count_text = count_element.text.strip()
                if count_text.isdigit():
                    count = int(count_text)
                    print(f"✅ 检测到抽奖券数量: {count}")
                    return count
            except:
                continue
        
        print("⚠️ 无法检测抽奖券数量")
        return 0
        
    except Exception as e:
        print(f"❌ 检测抽奖券数量失败: {e}")
        return 0

def click_lottery_submit_button(bz):
    """点击开始抽奖Submit按钮"""
    try:
        print("🔍 查找开始抽奖Submit按钮...")
        selectors = [
            '//span[contains(@class, "btn-label") and contains(@class, "DesktopReferralShare_btn-label") and text()="Submit"]',
            '//span[contains(@class, "btn-label") and text()="Submit"]',
            '//button[contains(., "Submit")]//span[text()="Submit"]'
        ]
        
        for selector in selectors:
            try:
                submit_element = bz.driver.find_element(By.XPATH, selector)
                if submit_element.is_displayed():
                    # 如果是span，找父button
                    if submit_element.tag_name == 'span':
                        try:
                            button = submit_element.find_element(By.XPATH, "./ancestor::button[1]")
                            bz.driver.execute_script("arguments[0].click();", button)
                        except:
                            bz.driver.execute_script("arguments[0].click();", submit_element)
                    else:
                        bz.driver.execute_script("arguments[0].click();", submit_element)
                    
                    print("✅ 找到并点击开始抽奖Submit按钮")
                    return True
            except:
                continue
        
        print("❌ 未找到开始抽奖Submit按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击开始抽奖Submit按钮失败: {e}")
        return False

def click_auto_pick_button(bz):
    """点击Auto-Pick摇号按钮"""
    try:
        print("🔍 查找Auto-Pick按钮...")
        selectors = [
            '//button[contains(@class, "btn-auto") and contains(@class, "DesktopLottoEntryModal_btn-auto")]//span[contains(@class, "text") and text()="Auto-Pick"]',
            '//span[contains(@class, "text") and contains(@class, "DesktopLottoEntryModal_text") and text()="Auto-Pick"]',
            '//span[text()="Auto-Pick"]',
            '//button[contains(@class, "btn-auto")]'
        ]
        
        for selector in selectors:
            try:
                auto_pick_element = bz.driver.find_element(By.XPATH, selector)
                if auto_pick_element.is_displayed():
                    # 如果是span，找父button
                    if auto_pick_element.tag_name == 'span':
                        try:
                            button = auto_pick_element.find_element(By.XPATH, "./ancestor::button[1]")
                            bz.driver.execute_script("arguments[0].click();", button)
                        except:
                            bz.driver.execute_script("arguments[0].click();", auto_pick_element)
                    else:
                        bz.driver.execute_script("arguments[0].click();", auto_pick_element)
                    
                    print("✅ 找到并点击Auto-Pick按钮")
                    return True
            except:
                continue
        
        print("❌ 未找到Auto-Pick按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击Auto-Pick按钮失败: {e}")
        return False

def click_final_submit_button(bz):
    """点击最终提交Submit按钮"""
    try:
        print("🔍 查找最终提交Submit按钮...")
        selectors = [
            '//span[contains(@class, "text") and contains(@class, "DesktopLottoEntryModal_text") and text()="Submit"]',
            '//span[contains(@class, "text") and text()="Submit"]',
            '//button[contains(., "Submit")]//span[text()="Submit"]',
            '//span[text()="Submit"]'
        ]
        
        for selector in selectors:
            try:
                submit_element = bz.driver.find_element(By.XPATH, selector)
                if submit_element.is_displayed():
                    # 如果是span，找父button
                    if submit_element.tag_name == 'span':
                        try:
                            button = submit_element.find_element(By.XPATH, "./ancestor::button[1]")
                            bz.driver.execute_script("arguments[0].click();", button)
                        except:
                            bz.driver.execute_script("arguments[0].click();", submit_element)
                    else:
                        bz.driver.execute_script("arguments[0].click();", submit_element)
                    
                    print("✅ 找到并点击最终提交Submit按钮")
                    return True
            except:
                continue
        
        print("❌ 未找到最终提交Submit按钮")
        return False
        
    except Exception as e:
        print(f"❌ 点击最终提交Submit按钮失败: {e}")
        return False

def click_confirm_ok_button(bz):
    """点击确认OK按钮 (RomConfirmModal)"""
    try:
        print("⏳ 等待确认OK按钮出现...")
        max_wait = 10  # 最多等待10秒
        
        for wait_time in range(max_wait):
            try:
                selectors = [
                    '//span[contains(@class, "btn-label") and contains(@class, "RomConfirmModal_btn-label") and text()="OK"]',
                    '//span[contains(@class, "RomConfirmModal_btn-label") and text()="OK"]',
                    '//button[contains(@class, "RomConfirmModal")]//span[text()="OK"]',
                    '//span[text()="OK"]'
                ]
                
                for selector in selectors:
                    try:
                        ok_element = bz.driver.find_element(By.XPATH, selector)
                        if ok_element.is_displayed():
                            # 如果是span，找父button
                            if ok_element.tag_name == 'span':
                                try:
                                    button = ok_element.find_element(By.XPATH, "./ancestor::button[1]")
                                    bz.driver.execute_script("arguments[0].click();", button)
                                except:
                                    bz.driver.execute_script("arguments[0].click();", ok_element)
                            else:
                                bz.driver.execute_script("arguments[0].click();", ok_element)
                            
                            print(f"✅ 找到并点击确认OK按钮 (等待了{wait_time}秒)")
                            return True
                    except:
                        continue
                
                if wait_time < max_wait - 1:
                    print(f"🔍 等待确认OK按钮... ({wait_time+1}/{max_wait})")
                    time.sleep(1)
                
            except Exception as e:
                if wait_time < max_wait - 1:
                    time.sleep(1)
                continue
        
        print("❌ 等待确认OK按钮超时")
        return False
        
    except Exception as e:
        print(f"❌ 点击确认OK按钮失败: {e}")
        return False

def check_lottery_completion(bz):
    """检查抽奖是否完成（抽奖券数量为0）"""
    try:
        print("🔍 检查抽奖完成状态...")
        time.sleep(2)  # 等待页面更新
        
        # 获取当前抽奖券数量
        final_count = get_lottery_count(bz)
        
        if final_count == 0:
            print("✅ 抽奖券数量已归零，抽奖完成")
            return True
        else:
            print(f"⚠️ 抽奖券数量仍为 {final_count}，可能需要继续抽奖")
            return False
        
    except Exception as e:
        print(f"❌ 检查抽奖完成状态失败: {e}")
        return False

def click_google_button_no_wait(bz):
    """点击Google登录按钮 (第二次登录 - 不等待弹窗)"""
    max_wait_time = 10  # 减少等待时间
    check_interval = 1  # 每秒检测一次
    
    for attempt in range(max_wait_time):
        try:
            # 方案1: 切换到iframe内部点击真正的按钮
            google_iframe = bz.driver.find_element(By.CLASS_NAME, "L5Fo6c-PQbLGe")
            print(f"✅ 找到Google iframe (等待了{attempt}秒)")
            
            # 切换到iframe内部
            bz.driver.switch_to.frame(google_iframe)
            print("✅ 已切换到Google iframe内部")
            
            # 在iframe内部查找并点击按钮
            try:
                # 等待iframe内容加载
                time.sleep(1)
                # 查找iframe内的按钮 (通常是div或button)
                inner_button = bz.driver.find_element(By.CSS_SELECTOR, "[role='button']")
                inner_button.click()
                print("✅ 成功点击iframe内部按钮")
                # 切换回主页面
                bz.driver.switch_to.default_content()
                # 直接返回成功，不等待弹窗
                print("✅ 第二次登录：跳过弹窗等待，直接进行账号选择")
                return True
            except:
                try:
                    # 尝试其他可能的选择器
                    inner_button = bz.driver.find_element(By.TAG_NAME, "div")
                    bz.driver.execute_script("arguments[0].click();", inner_button)
                    print("✅ 成功点击iframe内部div")
                    # 切换回主页面
                    bz.driver.switch_to.default_content()
                    # 直接返回成功，不等待弹窗
                    print("✅ 第二次登录：跳过弹窗等待，直接进行账号选择")
                    return True
                except:
                    # 切换回主页面
                    bz.driver.switch_to.default_content()
                    print("❌ iframe内部点击失败，切换回主页面")
                
        except:
            # 方案2: 查找title包含Google的iframe
            try:
                all_iframes = bz.driver.find_elements(By.TAG_NAME, "iframe")
                for iframe in all_iframes:
                    iframe_title = iframe.get_attribute("title")
                    if iframe_title and "google" in iframe_title.lower():
                        print(f"✅ 找到Google iframe (通过title: {iframe_title})")
                        bz.driver.switch_to.frame(iframe)
                        
                        try:
                            inner_button = bz.driver.find_element(By.CSS_SELECTOR, "[role='button']")
                            inner_button.click()
                            print("✅ 成功点击iframe内部按钮")
                            bz.driver.switch_to.default_content()
                            print("✅ 第二次登录：跳过弹窗等待，直接进行账号选择")
                            return True
                        except:
                            bz.driver.switch_to.default_content()
                            continue
            except:
                pass
            
            # 方案3: 查找具体class的Google按钮
            try:
                google_btn = bz.driver.find_element(By.CLASS_NAME, "nsm7Bb-HzV7m-LgbsSe-BPrWId")
                bz.driver.execute_script("arguments[0].scrollIntoView(true);", google_btn)
                time.sleep(0.5)
                bz.driver.execute_script("arguments[0].click();", google_btn)
                print("✅ 第二次登录：成功点击Google按钮(特定class)")
                return True
            except:
                pass
        
        # 等待后重试
        if attempt < max_wait_time - 1:
            print(f"🔍 等待Google按钮... ({attempt + 1}/{max_wait_time})")
            time.sleep(check_interval)
        else:
            print("❌ Google按钮等待超时")
            break
    
    # 最后的回退方案：点击google-login容器
    try:
        google_btn = bz.driver.find_element(By.CLASS_NAME, "google-login")
        bz.driver.execute_script("arguments[0].click();", google_btn)
        print("✅ 第二次登录：回退点击google-login容器")
        return True
    except Exception as e:
        print(f"❌ 第二次登录所有方案都失败: {e}")
        return False

if __name__ == "__main__":
    main()
