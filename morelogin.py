# -*- coding: utf-8 -*-
"""morelogin.py — 启动环境并返回 debugPort"""

import requests

__all__ = ["start_env"]

def start_env(unique_id, config):
    """
    :param unique_id: 运行环境唯一 ID
    :param config:    dict，需含 BASE_URL / API_ID / API_KEY
    :return: int      debugPort
    """
    url = config["BASE_URL"].rstrip("/") + "/api/env/start"
    headers = {
        "api-id":  config["API_ID"],
        "api-key": config["API_KEY"],
        "Content-Type": "application/json",
    }
    payload = {"uniqueId": unique_id}

    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()

    if data.get("code") != 0:
        raise Exception("启动环境失败: %s" % data.get("msg", ""))

    print("✅ 启动成功:", data)
    return data["data"]["debugPort"]
