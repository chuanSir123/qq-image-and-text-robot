import json
import threading
import time
import asyncio

from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image, Voice
from graia.ariadne.message.element import Plain
from loguru import logger
from quart import Quart, request,Response
import tomlkit
from constants import config, BotPlatform
from universal import handle_message
from curl_cffi import requests as curlRequests
import os
import re
import uuid
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
app = Quart(__name__)

lock = threading.Lock()

request_dic = {}

RESPONSE_SUCCESS = "SUCCESS"
RESPONSE_FAILED = "FAILED"
RESPONSE_DONE = "DONE"


class BotRequest:
    def __init__(self, session_id, username, message, request_time):
        self.session_id: str = session_id
        self.username: str = username
        self.message: str = message
        self.result: ResponseResult = ResponseResult()
        self.request_time = request_time
        self.done: bool = False
        """请求是否处理完毕"""

    def set_result_status(self, result_status):
        if not self.result:
            self.result = ResponseResult()
        self.result.result_status = result_status

    def append_result(self, result_type, result):
        with lock:
            if result_type == "message":
                self.result.message.append(result)
            elif result_type == "voice":
                self.result.voice.append(result)
            elif result_type == "image":
                self.result.image.append(result)


class ResponseResult:
    def __init__(self, message=None, voice=None, image=None, result_status=RESPONSE_SUCCESS):
        self.result_status = result_status
        self.message = self._ensure_list(message)
        self.voice = self._ensure_list(voice)
        self.image = self._ensure_list(image)

    def _ensure_list(self, value):
        if value is None:
            return []
        elif isinstance(value, list):
            return value
        else:
            return [value]

    def is_empty(self):
        return not self.message and not self.voice and not self.image

    def pop_all(self):
        with lock:
            self.message = []
            self.voice = []
            self.image = []

    def to_json(self):
        return json.dumps({
            'result': self.result_status,
            'message': self.message,
            'voice': self.voice,
            'image': self.image
        })


async def process_request(bot_request: BotRequest):
    async def response(msg):
        logger.info(f"Got response msg -> {type(msg)} -> {msg}")
        _resp = msg
        if not isinstance(msg, MessageChain):
            _resp = MessageChain(msg)
        for ele in _resp:
            if isinstance(ele, Plain) and str(ele):
                bot_request.append_result("message", str(ele))
            elif isinstance(ele, Image):
                bot_request.append_result("image", f"data:image/png;base64,{ele.base64}")
            elif isinstance(ele, Voice):
                # mp3
                bot_request.append_result("voice", f"data:audio/mpeg;base64,{ele.base64}")
            else:
                logger.warning(f"Unsupported message -> {type(ele)} -> {str(ele)}")
                bot_request.append_result("message", str(ele))
    logger.debug(f"Start to process bot request {bot_request.request_time}.")
    if bot_request.message is None or not str(bot_request.message).strip():
        await response("message 不能为空!")
        bot_request.set_result_status(RESPONSE_FAILED)
    else:
        await handle_message(
            response,
            bot_request.session_id,
            bot_request.message,
            nickname=bot_request.username,
            request_from=BotPlatform.HttpService
        )
        bot_request.set_result_status(RESPONSE_DONE)
    bot_request.done = True
    logger.debug(f"Bot request {bot_request.request_time} done.")


@app.route('/v1/chat', methods=['POST'])
async def v1_chat():
    """同步请求，等待处理完毕返回结果"""
    data = await request.get_json()
    bot_request = construct_bot_request(data)
    await process_request(bot_request)
    # Return the result as JSON
    return bot_request.result.to_json()


@app.route('/v2/chat', methods=['POST'])
async def v2_chat():
    """异步请求，立即返回，通过/v2/chat/response获取内容"""
    data = await request.get_json()
    bot_request = construct_bot_request(data)
    asyncio.create_task(process_request(bot_request))
    request_dic[bot_request.request_time] = bot_request
    # Return the result time as request_id
    return bot_request.request_time


@app.route('/v2/chat/response', methods=['GET'])
async def v2_chat_response():
    """异步请求时，配合/v2/chat获取内容"""
    request_id = request.args.get("request_id")
    bot_request: BotRequest = request_dic.get(request_id, None)
    if bot_request is None:
        return ResponseResult(message="没有更多了！", result_status=RESPONSE_FAILED).to_json()
    response = bot_request.result.to_json()
    if bot_request.done:
        request_dic.pop(request_id)
    else:
        bot_request.result.pop_all()
    logger.debug(f"Bot request {request_id} response -> \n{response[:100]}")
    return response

@app.route('/v1/complete', methods=['POST'])
async def streaming_api():
    rdata = await request.get_json()
    message = rdata.get('prompt')
    logger.debug(message.split('.切换账号')[-1].replace("\n",""))
    if(".切换账号" in message and  not message.split('.切换账号')[-1].replace("\n","").startswith("Human:") and not message.split('.切换账号')[-1].replace("\n","").startswith("Assistant:")):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
        # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        code=""
        # 现在你可以访问解析后的Toml数据，比如：
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        chrome_driver_path = os.path.dirname(parent_dir)
        chrome_driver_path = chrome_driver_path+"\chromedriver.exe"
        chrome_options=Options()
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.54 Safari/537.36")
        """最终的效果：不会弹出浏览器窗口"""
        # 添加 ChromeDriver 所在目录到 PATH 环境变量
        os.environ["PATH"] += os.pathsep + os.path.dirname(chrome_driver_path)
        emailDriver = webdriver.Chrome(executable_path=chrome_driver_path, chrome_options=chrome_options)
        emailDriver.get("https://www.emailnator.com/")
        # 等待"email"输入框出现并输入email地址
        try:
            try:
                connected_values = WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Email Address"][readonly]'))).get_attribute('value')
                goBtn = WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.NAME, "goBtn")))
                logger.debug(connected_values)
            except:
                logger.debug("no accept")

        except Exception as e:
            logger.debug(e)
        code=""
        try:
            data={
                "email_address":f"{connected_values}",
                "recaptcha_token":"03ADUVZwCqKIVpGMy-zn0tuMIgCLC6vXtLXYpMVhxwdoAXF-3S3KApTb3Gl00jWldJ_prVrs2OWhNaW2SX4QxH_xCazjeXMNzxJbrFulG4hLA7URadPbRJmp9ME_c_Dxvnssd01A851TtTYV6hIPOaMXGEJyWEzkId__LkW4sIzlDE69oX-oNVTPd5z9fqOP2VxQqYJblZg17RyOCyl7yUF474nVrJOEFOa-f9-cd7nq7Z6GSCy6vv5SVDDQUq0PTJBzstoI9Zj_vralXSiDz4Z-nP4JJ24AolQHOOEysk09vQfOPO2UDYduSsRXGhS0dRAobRgJbyH50dMHae4GJu17BCGLeKKdyGgOsWI4dkzHMVIzEGb3xiB7nEN9Z41Ftr3UfjscG2Y6AvgSYKpaZEIspqqSje39R-LATTgz7qoixSq1udkB1wvF5-vp34kQaFa94s63zPGjEXB36UOUa_LeOkbonjvAHHTyLHzc3fGjtjX8rTXwr_C7MNjd41kX_UG7lMrOy0KFEzVubvy1nLvOORDlfjDVBwxXPt6A2KocwXfnhLM_mgHxC8V4knwYiHJx8mx83pzVeLmbbTMvGY2nd2f2mjsmPpXzh1yTCa4-Z517t_YVoUhI8t7xYVy0n6TGCXJ9CjrgqIgIOfggnBR0KiVO7Gt42tRtcudcn4js7qoC0GVHTxoCr9pBTatrw7Bmfo_WNBToFiYHLObo-_htu_pQi1rEVz4HlW1nJzwaukNyGVpS5YltAC3APwsvWVvxnBEpYSMblPzw8w7x6d6iv6bPtgZ1OVFzdJxW7-I5jdgAl0aV007GSB0mbdCihapADxLRZwRb0NOOat0IwR6FJqbK6QdduSYB7fb1qbyDsbsCmpiQ3Iw50uJGDgKRg1Z2PW71yrBeZUkuydz4ZrnszThpLFuDyw1O3OJcZhv5lo65pv4gcLHmrPvIjMrL8e8aBc2W4rENz6QhIgDiRRkbcl5ZXFbQbb8ZBQAoZhWHdNAdPYHgmyYzHH8Eyp_r1BVefonr_qxu819Wrz3wkMgKj6r6mQjO8XwenCPtGN6IO3nbClquOL76dLNPBUEAIlwwRLYoqhB7BWMkwEBNnYmxnvBduZCatB9Fx15y7ULt3uMBVQ3PWMr2IfffUOXr4frz43NOrWK6flPE-oZ8pjB8ho9mZHujioy6aiXfO24otcuo3TVjPuVSJRbBWf2vMaOu95k9sdbwlmslduut8MRSTynPkmzVIN-Tiq8By8qDYHRFU_vLGqZfRcf8A0b2nAZflZY8PXd7gqtZa313trRJhlbczsCwkfJK86cn6USnjZlTztHBMD-c_qO1KKW8rtBUNeldFXtdzbkd3YSxkIn9zTpeT1TZ4jvazxj81thg5LZ5zcWFM6seGqgLVvLgsZuuAN92nXma4ufGZFsICVrZ69cNgkkpIBaxrtBOdMROeJDEk-pjBBVvVtE-VNUdMszDHe3Y6gWn9esiBZLI13kBmalsbetlMQQbpXXiNAuCLDGCJ3Z7EmIKCKrk6mOc_KCfGdzUrj9DQmvhrX2zcRmvnU3e79t_0BmcD9EOu3sRIz3YlzcScBMkq74HMX--G5pyE-2KMJllBAOXc9khvJ1ZlNBRA0LxSAtsT2hGxDxaDu7fZhBc6A4V_jMZ-Lgrpf4R1cLBktZwXHLQ-PXsBa7fP2hLO_skBiLi7HjxXDRWpI6HUu6BdUtjDEVSptmaLiqpbWcotTIKGlgyUspRlKIDdnTqZ66cSE-g",
                "recaptcha_site_key":"6LcdsFgmAAAAAMfrnC1hEdmeRQRXCjpy8qT_kvfy"
            }
            try:
                proxies = {
                    'https': f"{config.slack.accounts[0].proxy}",
                    'http': f"{config.slack.accounts[0].proxy}"
                }
                res=curlRequests.post(f"https://claude.ai/api/auth/send_code",proxies=proxies, impersonate="chrome101", json=data)
                res.raise_for_status()
            except Exception as e:
                res=curlRequests.post(f"https://email.claudeai.ai/claude_api/send_code", impersonate="chrome101", json=data)
            time.sleep(5)
            goBtn.click()
            count = 0
            while count<10:
                count += 1
                time.sleep(2)
                try:
                    text = WebDriverWait(emailDriver, 20).until(EC.presence_of_element_located((By.XPATH, "//tr[contains(., 'Your verification code is')]"))).text
                    logger.debug(text)
                    match = re.search(r'Your verification code is (\d{6})', text)
                    if match:
                        code = match.group(1)
                        break
                except Exception as e:
                    WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.NAME, "reload"))).click()
                    time.sleep(2)
                    continue

        except Exception as e:
            logger.error(e)
        logger.debug(code)
        if code == "":
            # driver.get("https://"+"claudeai.ai")
            emailDriver.get("https://yopmail.com/zh/email-generator")
            # 等待"email"输入框出现并输入email地址
            try:
                try:
                    WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.ID, "accept"))).click()
                except:
                    logger.debug("no accept")
                pre = WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "genytxt"))).text

                with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
                    toml_data = file.read()
                    # 解析Toml数据并保留注释
                configDict = tomlkit.parse(toml_data)
                # 现在你可以访问解析后的Toml数据，比如：
                suffix=""
                if not 'email_suffix' in configDict or not configDict['email_suffix']:
                    emailDriver.switch_to.frame(emailDriver.find_element_by_id("ifdoms"))
                    optgroup_element = WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.XPATH, "//optgroup[@label='-- 新的 --']")))
                    suffix = optgroup_element.find_element(By.TAG_NAME, "option").text
                    emailDriver.switch_to.default_content()
                else:
                    suffix="@"+configDict['email_suffix']
                connected_values = pre+suffix
                logger.debug(connected_values)
                checkEmail = WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.XPATH, "//*[text()='查看邮箱']")))
            except Exception as e:
                logger.debug(e)
            code=""
            try:
                proxies = {
                    'https': f"{config.slack.accounts[0].proxy}",
                    'http': f"{config.slack.accounts[0].proxy}"
                }
                data={
                    "email_address":f"{connected_values}",
                    "recaptcha_token":"03ADUVZwCqKIVpGMy-zn0tuMIgCLC6vXtLXYpMVhxwdoAXF-3S3KApTb3Gl00jWldJ_prVrs2OWhNaW2SX4QxH_xCazjeXMNzxJbrFulG4hLA7URadPbRJmp9ME_c_Dxvnssd01A851TtTYV6hIPOaMXGEJyWEzkId__LkW4sIzlDE69oX-oNVTPd5z9fqOP2VxQqYJblZg17RyOCyl7yUF474nVrJOEFOa-f9-cd7nq7Z6GSCy6vv5SVDDQUq0PTJBzstoI9Zj_vralXSiDz4Z-nP4JJ24AolQHOOEysk09vQfOPO2UDYduSsRXGhS0dRAobRgJbyH50dMHae4GJu17BCGLeKKdyGgOsWI4dkzHMVIzEGb3xiB7nEN9Z41Ftr3UfjscG2Y6AvgSYKpaZEIspqqSje39R-LATTgz7qoixSq1udkB1wvF5-vp34kQaFa94s63zPGjEXB36UOUa_LeOkbonjvAHHTyLHzc3fGjtjX8rTXwr_C7MNjd41kX_UG7lMrOy0KFEzVubvy1nLvOORDlfjDVBwxXPt6A2KocwXfnhLM_mgHxC8V4knwYiHJx8mx83pzVeLmbbTMvGY2nd2f2mjsmPpXzh1yTCa4-Z517t_YVoUhI8t7xYVy0n6TGCXJ9CjrgqIgIOfggnBR0KiVO7Gt42tRtcudcn4js7qoC0GVHTxoCr9pBTatrw7Bmfo_WNBToFiYHLObo-_htu_pQi1rEVz4HlW1nJzwaukNyGVpS5YltAC3APwsvWVvxnBEpYSMblPzw8w7x6d6iv6bPtgZ1OVFzdJxW7-I5jdgAl0aV007GSB0mbdCihapADxLRZwRb0NOOat0IwR6FJqbK6QdduSYB7fb1qbyDsbsCmpiQ3Iw50uJGDgKRg1Z2PW71yrBeZUkuydz4ZrnszThpLFuDyw1O3OJcZhv5lo65pv4gcLHmrPvIjMrL8e8aBc2W4rENz6QhIgDiRRkbcl5ZXFbQbb8ZBQAoZhWHdNAdPYHgmyYzHH8Eyp_r1BVefonr_qxu819Wrz3wkMgKj6r6mQjO8XwenCPtGN6IO3nbClquOL76dLNPBUEAIlwwRLYoqhB7BWMkwEBNnYmxnvBduZCatB9Fx15y7ULt3uMBVQ3PWMr2IfffUOXr4frz43NOrWK6flPE-oZ8pjB8ho9mZHujioy6aiXfO24otcuo3TVjPuVSJRbBWf2vMaOu95k9sdbwlmslduut8MRSTynPkmzVIN-Tiq8By8qDYHRFU_vLGqZfRcf8A0b2nAZflZY8PXd7gqtZa313trRJhlbczsCwkfJK86cn6USnjZlTztHBMD-c_qO1KKW8rtBUNeldFXtdzbkd3YSxkIn9zTpeT1TZ4jvazxj81thg5LZ5zcWFM6seGqgLVvLgsZuuAN92nXma4ufGZFsICVrZ69cNgkkpIBaxrtBOdMROeJDEk-pjBBVvVtE-VNUdMszDHe3Y6gWn9esiBZLI13kBmalsbetlMQQbpXXiNAuCLDGCJ3Z7EmIKCKrk6mOc_KCfGdzUrj9DQmvhrX2zcRmvnU3e79t_0BmcD9EOu3sRIz3YlzcScBMkq74HMX--G5pyE-2KMJllBAOXc9khvJ1ZlNBRA0LxSAtsT2hGxDxaDu7fZhBc6A4V_jMZ-Lgrpf4R1cLBktZwXHLQ-PXsBa7fP2hLO_skBiLi7HjxXDRWpI6HUu6BdUtjDEVSptmaLiqpbWcotTIKGlgyUspRlKIDdnTqZ66cSE-g",
                    "recaptcha_site_key":"6LcdsFgmAAAAAMfrnC1hEdmeRQRXCjpy8qT_kvfy"
                }
                res=curlRequests.post(f"https://claude.ai/api/auth/send_code",proxies=proxies, impersonate="chrome101", json=data)
                logger.debug(res.text)
                checkEmail.click()
                count = 0
                while count<10:
                    count += 1
                    time.sleep(2)
                    try:
                        WebDriverWait(emailDriver, 20).until(EC.presence_of_element_located((By.ID, "refresh"))).click()
                        emailDriver.switch_to.frame(emailDriver.find_element_by_id("ifinbox"))
                        e_subject = WebDriverWait(emailDriver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "lms"))).text
                        emailDriver.switch_to.default_content()
                        match = re.search(r'\b\d{6}\b', e_subject)
                        if match:
                            code = match.group()
                            break
                    except Exception as e:
                        continue

            except Exception as e:
                logger.error(e)
        if code == "":
            return
        session_key = None
        organization_id= None
        try:
            verify={
                "email_address":f"{connected_values}",
                "code":code,
                "recaptcha_token":"03ADUVZwCKYPEo6uaLvLSoYvuI7T3fYXtvFYjbOkStl4y5j29PEe3xp0blZRR20u5ga8480mvLZX4JRL9u1m5hGl19oxaxnPWXiqPSd8JOgFPuK8ymNWvOUItA4k9IGZWP5CIp1A7tCXbgWhiAxL7gwwkjGlAkUswL14RbdskbU05cQnnBc3d5Ll8BiOEtg5ITeLU9Fy4vjo5OQ3BIUUtrNCJQKw163_dnkiwMtBChHRfok0Qsa1dXXppRwKOpebhniRdWqwOGYNosI6hRz03p48NNtTKBVjrJ-Q1uh7gcQXKDggMPA-1rUMJHmD0E01CDRWIvgM8cn8Ffb3tT1bzw7wQlwmgmO-c1R7GkHGVzuScoAGQvd1HwnMKBiFvoju72OF51S8vCJJv5P7WZBnyRvAEzVeAqQZF7EC7NA-qIJwoPdqdIkCA2nhwxuGgx5uSbhlEH69jZdXzCvbX_1im8WwqpdykvMK_YPh9_OF1L1F1knkVwZxHkYpPhkO1V2YcOugJXEwyfDUCW8bs1YstUxfCuhZWOblfHaYp6x0Ii7IJHEKSdVumWQdI6R2TZBZEwdij07gpMZNpeOmeP7Jv1EZewvDKU_icZpiB2Xat-AkbwohpBZrQVOXRAftXg2BXCJKNvhYE6vKxGsPD6SgxkaSJXrR68NBf2TQKS5XLfYsxo0oE5fXqE60SBR604NB7hid71-uF2RyiCI5ocxLmaSxMSX1qdUvg5yhgBHyw3tGHGquts23bF4XMrv7gSrgT0vtnLG_zZ4fBjhgD95nP3mmfFgm0t-IoNbEedrUvKTE9pHpVkEdcExltCCpBKfuw-Ai7FdpXvFvvA6qWOR7R5862NWyoQJYqCjdwMI9NVX-ieE7b4VWefbC5mlgnWuFDa3u-T0pblXFhFmdODkpGdsspSx7NKRkO-909n57qrWLASoe2Z6rm19-9RlvYrtcYrsljh-XB3cLi5ngdkvZMFt5WjO3ceRiqdQvS5X_heVVSvLhRYm4lFREAAABbSFkLyidbTb6jsZoKT75RfzTqy2GwAv0MmKQ3YD6bwTMsrsT_PiQVEQo7n3DXnm3kti2t6ybS_nkU9ZJcA8eVKQFWM12qa074ZOuBMZ6WB_FIqyrrHt9o6_NRm3g56Gr-qPGAwxvek1C9o-O7gkvVJUp4yP683S_RFoHzebqAoTOUx1fTBIMbJtnhKlWQ62z6r9vcChIgcANSsH16od2zkAmV6GCwXpIUYo1E1GZhtX9mcXVIDQRbjfiaUbH2k6N7SQluP7QixM_Zz0_RcowYgui6uzUpcsvSe2UTD62V0o_VUxmLPu6fuF7zGzEeA8nzrlq7795xZt1BSmk76WjhTISXl9AKWXIKFi_Z0fMRE2F1Rw0IdkZ8dkswQ2Gxs-8FPYcMKFHZZ2_JsDlPk8O3oL5YAWvV9Lfi2m9oZe0M1TVfsM84UQvl4GX14Ymwh2PfWJpoKUoef2FPjr16aXJ4LnSQjseEqiFZ__8tKhfVGs2iSQmEW3fl7M72_X3S2sxEyOQ6zw5IihxmopKRdOtjrq7hOLnXP_ZwS7BSxn-t7ugBZ4ZkB1F28XRPu-U_bgBFBKEJJg4KVEuSG6YdNJ6rmlwhiuQ1SPvQaP2d6QJqEibEVgCv0lyWEiNin_AOYZexCmqq25sLO_oR2n19d3E3MhJmmji_joxFI9ppDOccKDS6FUmBrztD9d2XJHj4SJLtYhqxzRBvUUKmNgz4rQ_T8GICZ4OtM7oGxhjIfQA",
                "recaptcha_site_key":"6LcdsFgmAAAAAMfrnC1hEdmeRQRXCjpy8qT_kvfy"
            }
            try:
                res= curlRequests.post(f"https://claude.ai/api/auth/verify_code",proxies=proxies, impersonate="chrome101", json=verify)
                logger.debug(res.text)
                logger.debug(res.headers)
                session_key = res.headers["Set-Cookie"].split("sessionKey=")[1].split(";")[0]
                res= curlRequests.get(f"https://claude.ai/api/auth/current_account",headers={"Cookie":f"sessionKey={session_key}"},proxies=proxies, impersonate="chrome101")
                res.raise_for_status()
                data = res.json()
                organization_id = data["account"]["memberships"][0]["organization"]["uuid"]
            except Exception as e:
                verify["verify_code"]=code
                res= curlRequests.post(f"https://email.claudeai.ai/claude_api/verify_code", impersonate="chrome101", json=verify)
                logger.debug(res.text)
                logger.debug(res.headers)
                session_key = res.headers["Set-Cookie"].split("sessionKey=")[1].split(";")[0]
                res= curlRequests.get(f"https://chat.claudeai.ai/api/auth/current_account",headers={"Cookie":f"sessionKey={session_key}"}, impersonate="chrome101")
                data = res.json()
                organization_id = data["account"]["memberships"][0]["organization"]["uuid"]
        except Exception as e:
            logger.error(e)
        config.slack.accounts[0].cookie = f"sessionKey={session_key}"
        config.slack.accounts[0].organization_id = organization_id
        with open('config.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        configDict['slack']['accounts'][0]['cookie'] = f"sessionKey={session_key}"
        configDict['slack']['accounts'][0]['organization_id'] = organization_id
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        logger.debug(rdata)
        if rdata.get('stream') or str(rdata.get('stream'))=="true":
            text = 'data: {"completion":"切换账号成功","stop_reason":null,"model":"claude-2.0","stop":null,"log_id":"970183a4b0c265d06ea3fdbf624c54d2cd86a8fa1049120b72da6a16f0d0a7fe","messageLimit":{"type":"within_limit"}}\n\n'
            return Response(text, content_type='text/event-stream')
        else:
            return Response(json.dumps({"completion":"切换账号成功"}) , content_type='application/json')
        return


    async def generate(message,q):
        # 这里可以替换为你实际的数据生成逻辑
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
        # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：

        if  "claude2_url" in  configDict:
            claude2_url=configDict['claude2_url']
        else:
            claude2_url="claude.ai"
        logger.debug(claude2_url+"-"+config.slack.accounts[0].cookie+"-"+config.slack.accounts[0].organization_id)
        proxies = {
            'https': f"{config.slack.accounts[0].proxy}",
            'http': f"{config.slack.accounts[0].proxy}"
        }
        Cookie = f"{config.slack.accounts[0].cookie}"
        async with curlRequests.AsyncSession() as s:
            try:
                if config.slack.accounts[0].proxy:
                    response = await s.post(f"https://{claude2_url}/api/organizations/{config.slack.accounts[0].organization_id}/chat_conversations",proxies=proxies, impersonate="chrome101",headers={"Cookie":f"{Cookie}"}, json={"uuid":str(uuid.uuid4()),"name":""})
                else:
                    response = await s.post(f"https://{claude2_url}/api/organizations/{config.slack.accounts[0].organization_id}/chat_conversations", impersonate="chrome101",headers={"Cookie":f"{Cookie}"}, json={"uuid":str(uuid.uuid4()),"name":""})

            except:
                response = await s.post(f"https://chat.claudeai.ai/api/organizations/{config.slack.accounts[0].organization_id}/chat_conversations", impersonate="chrome101",headers={"Cookie":f"{Cookie}"}, json={"uuid":str(uuid.uuid4()),"name":""})
        line = response.json()
        conversation_uuid = line["uuid"]

        payload = {
            "completion":{
                "prompt":"",
                "timezone":"Asia/Shanghai",
                "model":"claude-2",
                "incremental":True
            },
            "organization_uuid":config.slack.accounts[0].organization_id,
            "conversation_uuid":conversation_uuid,
            "text":"",
            "attachments":[
                {
                    "file_name":"chatRecord.txt",
                    "file_size":"71429",
                    "file_type":"txt",
                    "extracted_content":message
                }
            ]
        }
        res = "";
        logger.debug(conversation_uuid)
        t1 = time.time()
        async def chunk_callback(chunk,q, *args, **kwargs):
            njsondata = chunk.decode("utf-8")
            await q.put(njsondata)
        async with curlRequests.AsyncSession() as s:

            try:
                try:
                    if config.slack.accounts[0].proxy:
                        await s.post(f"https://{claude2_url}/api/append_message",headers={"Cookie":f"{config.slack.accounts[0].cookie}"},proxies=proxies, impersonate="chrome101",content_callback=lambda chunk: asyncio.ensure_future(chunk_callback(chunk, q)), data=json.dumps(payload),timeout=180)
                    else:
                        await s.post(f"https://{claude2_url}/api/append_message",headers={"Cookie":f"{config.slack.accounts[0].cookie}"}, impersonate="chrome101",content_callback=lambda chunk: asyncio.ensure_future(chunk_callback(chunk, q)), data=json.dumps(payload),timeout=180)

                except:
                    logger.debug("尝试镜像")
                    await s.post(f"https://chat.claudeai.ai/api/append_message",headers={"Cookie":f"{config.slack.accounts[0].cookie}"}, impersonate="chrome101",content_callback=lambda chunk: asyncio.ensure_future(chunk_callback(chunk, q)), data=json.dumps(payload),timeout=180)
            except Exception as e:
                logger.debug(e)
    async def consumer(queue):
        content_str = ""
        while True:
            item = await queue.get()
            content_str +=item
            yield item.replace("H:","").replace("Human:","").replace("A:","")
            if "H:" in content_str or "Human:" in content_str:
                break;
    queue = asyncio.Queue()

    # 创建生产者和消费者任务

    if rdata.get('stream') or str(rdata.get('stream'))=="true":
        asyncio.create_task(generate(message,queue))
        # 打印消费者任务的输出
        return Response(consumer(queue), content_type='text/event-stream')
    else:
        async def consumerCompletion(queue,preStr):
            content_str = ""
            jixu = True
            while jixu:
                item = await queue.get()
                if "H:" in content_str or "Human:" in item:
                    logger.debug("stop :"+item)
                    break;
                for itemData in item.replace("data: ","").split("\n\n"):
                    itemData = "".join(preStr) +itemData
                    line = {}
                    if itemData:
                        try:
                            line = json.loads(itemData)
                            res =  line["completion"]
                            content_str += res
                            preStr = []
                        except:
                            if itemData.startswith("{"):
                                preStr.append(itemData)
                            logger.debug(item)
                            logger.debug("fail to json :"+itemData)
                            if "error" in line:
                                jixu = False;
                                yield json.dumps(line)
            yield json.dumps({"completion":content_str.replace("H:","").replace("Human:","").replace("A:","")})

        asyncio.create_task(generate(message,queue))
        # 打印消费者任务的输出
        preStr = []
        async for line in consumerCompletion(queue,preStr):
            if "error" in json.loads(line):
                return Response(line, content_type='application/json',status=429)
            else:
                return Response(line, content_type='application/json')


def clear_request_dict():
    logger.debug("Watch and clean request_dic.")
    while True:
        now = time.time()
        keys_to_delete = []
        for key, bot_request in request_dic.items():
            if now - int(key)/1000 > 600:
                logger.debug(f"Remove time out request -> {key}|{bot_request.session_id}|{bot_request.username}"
                             f"|{bot_request.message}")
                keys_to_delete.append(key)
        for key in keys_to_delete:
            request_dic.pop(key)
        time.sleep(60)


def construct_bot_request(data):
    session_id = data.get('session_id') or "friend-default_session"
    username = data.get('username') or "某人"
    message = data.get('message')
    logger.info(f"Get message from {session_id}[{username}]:\n{message}")
    with lock:
        bot_request = BotRequest(session_id, username, message, str(int(time.time() * 1000)))
    return bot_request


async def start_task():
    """|coro|
    以异步方式启动
    """
    threading.Thread(target=clear_request_dict).start()
    return await app.run_task(host="127.0.0.1", port="8448")
