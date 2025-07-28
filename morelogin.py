# -*- coding: utf-8 -*-
"""morelogin.py — 启动环境并返回 debugPort"""

import requests

__all__ = ["start_env", "create_env", "delete_env", "close_env"]

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
    payload = {"envId": unique_id}

    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()

    if data.get("code") != 0:
        raise Exception("启动环境失败: %s" % data.get("msg", ""))

    print("✅ 启动成功:", data)
    return data["data"]["debugPort"]


def create_env(config):
    """
    创建环境
    :param config: dict，需含 BASE_URL / API_ID / API_KEY / OPERATOR_SYSTEM
    :return: 创建结果
    """
    url = config["BASE_URL"].rstrip("/") + "/api/env/create/quick"
    headers = {
        "api-id":  config["API_ID"],
        "api-key": config["API_KEY"],
        "Content-Type": "application/json",
    }
    
    # 根据配置文件中的操作系统类型设置operatorSystemId
    operator_system = config.get("OPERATOR_SYSTEM", "mac").lower()
    if operator_system == "windows" or operator_system == "window":
        operator_system_id = 1
        os_name = "Windows"
    elif operator_system == "mac" or operator_system == "macos":
        operator_system_id = 2
        os_name = "macOS"
    else:
        raise ValueError(f"不支持的操作系统类型: {operator_system}，请在配置文件中设置为 'windows' 或 'mac'")
    
    payload = {
        "browserTypeId": 1,           # Chrome浏览器，写死为1
        "operatorSystemId": operator_system_id,  # 根据配置文件设置
        "quantity": 1                 # 创建1个环境
    }
    
    print(f"正在创建环境: 浏览器=Chrome, 操作系统={os_name}, 数量=1")
    
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()
    
    if data.get("code") != 0:
        raise Exception("创建环境失败: %s" % data.get("msg", ""))
    
    # 获取data数组的第一个值
    env_id = data.get("data", [])[0] if data.get("data") else None
    if not env_id:
        raise Exception("创建环境成功但未返回环境ID")
    
    print("✅ 创建环境成功，环境ID:", env_id)
    return env_id


def delete_env(env_ids, config):
    """
    删除环境到回收站
    :param env_ids: list 或 str，环境ID列表或单个环境ID
    :param config: dict，需含 BASE_URL / API_ID / API_KEY
    :return: 删除结果
    """
    url = config["BASE_URL"].rstrip("/") + "/api/env/removeToRecycleBin/batch"
    headers = {
        "api-id":  config["API_ID"],
        "api-key": config["API_KEY"],
        "Content-Type": "application/json",
    }
    
    # 确保env_ids是列表格式
    if isinstance(env_ids, str):
        env_ids = [env_ids]
    
    payload = {
        "envIds": env_ids,
        "removeEnvData": False
    }
    
    print(f"正在删除环境: {env_ids}")
    
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()
    
    if data.get("code") != 0:
        raise Exception("删除环境失败: %s" % data.get("msg", ""))
    
    print("✅ 删除环境成功，已移至回收站")
    return data.get("data", True)


def close_env(env_id, config):
    """
    关闭浏览器环境
    :param env_id: str，环境ID
    :param config: dict，需含 BASE_URL / API_ID / API_KEY
    :return: 关闭结果
    """
    url = config["BASE_URL"].rstrip("/") + "/api/env/close"
    headers = {
        "api-id":  config["API_ID"],
        "api-key": config["API_KEY"],
        "Content-Type": "application/json",
    }
    
    payload = {
        "envId": env_id
    }
    
    print(f"正在关闭环境: {env_id}")
    
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    data = res.json()
    
    if data.get("code") != 0:
        raise Exception("关闭环境失败: %s" % data.get("msg", ""))
    
    print("✅ 关闭环境成功")
    return data.get("data", True)
