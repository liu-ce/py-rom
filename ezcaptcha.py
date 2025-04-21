import requests
import time
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def solve_recaptcha(site_key, page_url, client_key, task_type):
    url = "https://api.yescaptcha.com/createTask"
    data = {
        "clientKey": client_key,
        "task": {
            "websiteURL": page_url,
            "websiteKey": site_key,
            "type": task_type
        }
    }
    result = requests.post(url, json=data, verify=False).json()
    task_id = result.get("taskId")
    if not task_id:
        raise RuntimeError("创建任务失败: %s" % result)

    print("创建任务成功:", task_id)
    # 循环获取结果
    for i in range(60):
        time.sleep(3)
        check_url = "https://api.yescaptcha.com/getTaskResult"
        check_data = {"clientKey": client_key, "taskId": task_id}
        check_result = requests.post(check_url, json=check_data, verify=False).json()
        if check_result.get("status") == "ready":
            return check_result["solution"]["gRecaptchaResponse"]
        print("等待验证码识别中... (%d/60)" % (i + 1))
    raise RuntimeError("验证码识别超时")
