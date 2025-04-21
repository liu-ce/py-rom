# -*- coding: utf-8 -*-
"""ezcaptcha.py

使用 EzCaptcha API 自动解决多种验证码任务，包括：
- reCAPTCHA V2/V3/Enterprise（Proxyless）
- 普通图形验证码（ImageToText）

提供函数：
- `solve_recaptcha(site_key, page_url, client_key, task_type, timeout)`
- `solve_image_captcha(image_path=None, image_url=None, client_key, timeout)`

示例::

    from ezcaptcha import solve_recaptcha, solve_image_captcha

    # 解决 reCAPTCHA
    token = solve_recaptcha(
        site_key="6Lc_aCMTAAAAABx56m4PSSfeR5-",
        page_url="https://accounts.google.com/",
        client_key="YOUR_EZCAPTCHA_KEY",
        task_type="ReCaptchaV2TaskProxyless",
    )
    print("reCAPTCHA token:", token)

    # 解决本地图片验证码
    text = solve_image_captcha(
        image_path="/path/to/captcha.png",
        client_key="YOUR_EZCAPTCHA_KEY",
    )
    print("图形验证码识别结果:", text)

    # 或解决网络图片
    text2 = solve_image_captcha(
        image_url="https://example.com/captcha.jpg",
        client_key="YOUR_EZCAPTCHA_KEY",
    )
    print(text2)
"""

import time
import base64
import requests

# EzCaptcha 接口 URL
CREATE_URL = "https://api.ez-captcha.com/createTask"
GET_URL = "https://api.ez-captcha.com/getTaskResult"

__all__ = ["solve_recaptcha", "solve_image_captcha"]


def _create_task(client_key, task_payload):
    """通用创建任务"""
    payload = {"clientKey": client_key, "task": task_payload}
    res = requests.post(CREATE_URL, json=payload, timeout=20).json()
    if res.get("errorId") != 0:
        raise RuntimeError(f"CreateTask Error: {res.get('errorDescription')}")
    return res["taskId"]


def _get_result(client_key, task_id):
    """通用获取任务结果"""
    payload = {"clientKey": client_key, "taskId": task_id}
    res = requests.post(GET_URL, json=payload, timeout=20).json()
    if res.get("errorId") != 0:
        raise RuntimeError(f"GetTask Error: {res.get('errorDescription')}")
    return res.get("status"), res.get("solution", {})


def solve_recaptcha(
    site_key: str,
    page_url: str,
    client_key: str,
    task_type: str = "ReCaptchaV3TaskProxyless",
    timeout: int = 120,
) -> str:
    """
    提交 reCAPTCHA 任务并轮询结果，返回 gRecaptchaResponse token。

    :param site_key:    页面上 <div data-sitekey="..."> 的值
    :param page_url:    触发验证码的网页 URL
    :param client_key:  EzCaptcha 分配的 API Key
    :param task_type:   任务类型，常用 ReCaptchaV2TaskProxyless/ReCaptchaV3TaskProxyless
    :param timeout:     最长等待秒数
    :return:            token 字符串
    """
    task_payload = {
        "type": task_type,
        "websiteURL": page_url,
        "websiteKey": site_key,
    }
    task_id = _create_task(client_key, task_payload)
    start = time.time()
    while True:
        status, solution = _get_result(client_key, task_id)
        if status == "ready":
            return solution.get("gRecaptchaResponse")
        if time.time() - start > timeout:
            raise TimeoutError(f"reCAPTCHA solving timeout after {timeout}s")
        time.sleep(5)


def solve_image_captcha(
    image_path: str = None,
    image_url: str = None,
    client_key: str = None,
    timeout: int = 120,
) -> str:
    """
    提交图形验证码任务并轮询结果，返回识别文本。

    :param image_path:  本地图片文件路径（.png/.jpg）
    :param image_url:   网络图片 URL（二选一提供）
    :param client_key:  EzCaptcha 分配的 API Key
    :param timeout:     最长等待秒数
    :return:            识别后的文本
    """
    if not client_key:
        raise ValueError("client_key is required")
    if not (image_path or image_url):
        raise ValueError("Must provide image_path or image_url")

    # 读取图片并 base64 编码
    if image_url:
        img_data = requests.get(image_url, timeout=10).content
    else:
        with open(image_path, "rb") as f:
            img_data = f.read()
    img_base64 = base64.b64encode(img_data).decode("utf-8")

    task_payload = {
        "type": "ImageToTextTask",
        "body": img_base64,
    }
    task_id = _create_task(client_key, task_payload)
    start = time.time()
    while True:
        status, solution = _get_result(client_key, task_id)
        if status == "ready":
            return solution.get("text")
        if time.time() - start > timeout:
            raise TimeoutError(f"Image captcha timeout after {timeout}s")
        time.sleep(5)
