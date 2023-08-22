import re
import time
from base64 import b64decode, b64encode
from typing import Union, Optional,Callable

import aiohttp
from aiocqhttp import CQHttp, Event, MessageSegment
from charset_normalizer import from_bytes
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Image as GraiaImage, At, Plain, Voice
from graia.ariadne.message.parser.base import DetectPrefix
from graia.broadcast import ExecutionStop
from loguru import logger

import constants
from constants import config, botManager
from manager.bot import BotManager
from middlewares.ratelimit import manager as ratelimit_manager
from universal import handle_message
import os
import json
import time
import aiohttp
from graia.ariadne.message.element import Image
from middlewares.middleware import Middleware
from middlewares.baiducloud import MiddlewareBaiduCloud
import copy
from utils.text_to_img import to_image
from drawing.my_map import add_to_map, get_from_map
import httpx
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
from curl_cffi import requests
import uuid
import toml
import sys
import tomlkit
import pickle
import os
import asyncio
import subprocess

bot = CQHttp()
middlewares = MiddlewareBaiduCloud()


class MentionMe:
    """At 账号或者提到账号群昵称"""

    def __init__(self, name: Union[bool, str] = True) -> None:
        self.name = name

    async def __call__(self, chain: MessageChain, event: Event) -> Optional[MessageChain]:
        for index, element in enumerate(chain):
            if isinstance(element, At) and element.target == config.onebot.qq:
                return MessageChain(chain[:index] + chain[index+1:], inline=True).removeprefix(" ")
            elif isinstance(element, Plain):
                member_info = await bot.get_group_member_info(group_id=event.group_id, user_id=config.onebot.qq)
                if member_info.get("nickname") and chain.startswith(member_info.get("nickname")):
                    return chain.removeprefix(" ")
                if chain.startswith("@"+member_info.get("nickname")):
                    return chain.removeprefix("@"+member_info.get("nickname")).removeprefix(" ")
                if chain.startswith(config.onebot.qq_nick_name):
                    return chain.removeprefix("@"+config.onebot.qq_nick_name).removeprefix(" ")
                if chain.startswith("@"+config.onebot.qq_nick_name):
                    return chain.removeprefix("@"+config.onebot.qq_nick_name).removeprefix(" ")
        raise ExecutionStop


class Image(GraiaImage):
    async def get_bytes(self) -> bytes:
        """尝试获取消息元素的 bytes, 注意, 你无法获取并不包含 url 且不包含 base64 属性的本元素的 bytes.

        Raises:
            ValueError: 你尝试获取并不包含 url 属性的本元素的 bytes.

        Returns:
            bytes: 元素原始数据
        """
        if self.base64:
            return b64decode(self.base64)
        if not self.url:
            raise ValueError("you should offer a url.")
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as response:
                response.raise_for_status()
                data = await response.read()
                self.base64 = b64encode(data).decode("ascii")
                return data


# TODO: use MessageSegment
# https://github.com/nonebot/aiocqhttp/blob/master/docs/common-topics.md
def transform_message_chain(text: str) -> MessageChain:
    pattern = r"\[CQ:(\w+),([^\]]+)\]"
    matches = re.finditer(pattern, text)

    message_classes = {
        "text": Plain,
        "image": Image,
        "at": At,
        # Add more message classes here
    }

    messages = []
    start = 0
    for match in matches:
        cq_type, params_str = match.groups()
        params = dict(re.findall(r"(\w+)=([^,]+)", params_str))
        if message_class := message_classes.get(cq_type):
            text_segment = text[start:match.start()]
            if text_segment:
                messages.append(Plain(text_segment))
            if cq_type == "at":
                if params.get('qq') == 'all':
                    continue
                params["target"] = int(params.pop("qq"))
            elem = message_class(**params)
            messages.append(elem)
            start = match.end()
    if text_segment := text[start:]:
        messages.append(Plain(text_segment))

    return MessageChain(*messages)


def transform_from_message_chain(chain: MessageChain):
    result = ''
    for elem in chain:
        if isinstance(elem, (Image, GraiaImage)):
            result = result + MessageSegment.image(f"base64://{elem.base64}")
        elif isinstance(elem, Plain):
            result = result + MessageSegment.text(str(elem))
        elif isinstance(elem, Voice):
            result = result + MessageSegment.record(f"base64://{elem.base64}")
    return result


def response(event, is_group: bool):
    async def respond(resp):
        repstr = str(resp)
        logger.debug(f"[OneBot] 尝试发送消息：{str(resp)}")
        repImage = resp
        image = ''
        if not isinstance(repImage, MessageChain):
            repImage = MessageChain(repImage)
        for elem in repImage:
            if isinstance(elem, (Image, GraiaImage)):
                image = MessageSegment.image(f"{elem.base64}")
            elif isinstance(elem, Plain):
                image = image + MessageSegment.text(str(elem))
            elif isinstance(elem, Voice):
                image = MessageSegment.image(f"{elem.base64}")
        repImage = image
        if config.response.quote and '[CQ:record,file=' not in str(repImage):  # skip voice
            repImage = '' + repImage
        result = str(repImage).replace('[CQ:image,file=','').replace(']','')
        logger.debug(f"[OneBot] 尝试发送消息：{result[:100] if len(str(result)) >= 100 else result}")
        messageId = None
        try:
            if not isinstance(resp, MessageChain):
                resp = MessageChain(resp)
            resp = transform_from_message_chain(resp)
            if config.response.quote and '[CQ:record,file=' not in str(resp):  # skip voice
                resp = (MessageSegment.reply(event.message_id) if event.message_id else "")  + resp

            # if not middlewares.baidu_cloud.access_token:
            #     middlewares.baidu_cloud.access_token = await middlewares.baidu_cloud.get_access_token()
            check = True
            # logger.success(f"[百度云token] ：{middlewares.baidu_cloud.access_token}")
            # if repstr == '[图片]' and result != '':
            #     response_dict = await middlewares.baidu_cloud.get_conclusion_image(result)
            # else:
            #     response_dict = await middlewares.baidu_cloud.get_conclusion(resp)
            # # 处理百度云审核结果
            # logger.success(f"[百度云审核] 结果：{response_dict}")
            # if response_dict != None:
            #     conclusion = response_dict["conclusion"]
            #     if conclusion == "合规":
            #         logger.success(f"[百度云审核] 判定结果1：{conclusion}")
            #         check = False
            #     else:
            #         logger.error(f"[百度云审核] 判定结果2：{conclusion}")
            #         check = True
            if check==False and is_group:  # skip voice
                messageId =  await bot.call_action(
                    "send_group_forward_msg" if is_group else "send_private_forward_msg",
                    group_id=event.group_id,
                    messages=[
                        MessageSegment.node_custom(event.self_id, "ChatGPT", resp)
                    ]
                )
                add_to_map(f"picPrompt-{messageId['message_id']}", get_from_map('this_pic_prompt'))
                add_to_map(f"pic-{messageId['message_id']}", resp)
                add_to_map(f"lastMessageId-{event.group_id}", messageId['message_id'])
            else:
                messageId = await bot.send(event, resp)
                add_to_map(f"picPrompt-{messageId['message_id']}", get_from_map('this_pic_prompt'))
                add_to_map(f"pic-{messageId['message_id']}", resp)
                add_to_map(f"lastMessageId-{event.group_id}", messageId['message_id'])
        except Exception as e:

            try:
                messageId = await bot.call_action(
                    "send_group_forward_msg" if is_group else "send_private_forward_msg",
                    group_id=event.group_id,
                    messages=[
                        MessageSegment.node_custom(event.self_id, "ChatGPT", resp)
                    ]
                )
                add_to_map(f"picPrompt-{messageId['message_id']}", get_from_map('this_pic_prompt'))
                add_to_map(f"pic-{messageId['message_id']}", resp)
                add_to_map(f"lastMessageId-{event.group_id}", messageId['message_id'])
            except Exception as e:
                try:
                    resp = await to_image(repstr)
                    resp = MessageSegment.image(f"base64://{resp.base64}")
                    if config.response.quote and '[CQ:record,file=' not in str(resp):  # skip voice
                        resp = (MessageSegment.reply(event.message_id) if event.message_id else "") + resp
                    messageId = await bot.send(event, resp)
                    add_to_map(f"picPrompt-{messageId['message_id']}", get_from_map('this_pic_prompt'))
                    add_to_map(f"pic-{messageId['message_id']}", resp)
                    add_to_map(f"lastMessageId-{event.group_id}", messageId['message_id'])
                except Exception as e:
                    logger.debug(e)

                    if repstr != '[图片]':
                        try:
                            resp = "请再说一遍（换个说法，防止被吞）"
                            resp = MessageSegment.text(resp)
                            if config.response.quote and '[CQ:record,file=' not in str(resp):  # skip voice
                                resp = (MessageSegment.reply(event.message_id) if event.message_id else "") + resp

                                messageId = await bot.send(event, resp)
                        except Exception as e:
                            return ''
                        add_to_map(f"picPrompt-{messageId['message_id']}", get_from_map('this_pic_prompt'))
                        add_to_map(f"pic-{messageId['message_id']}", resp)
                        add_to_map(f"lastMessageId-{event.group_id}", messageId['message_id'])
            # logger.exception(e)
            # logger.warning("原始消息发送失败，尝试通过转发发送")
            # return await bot.call_action(
            #     "send_group_forward_msg" if is_group else "send_private_forward_msg",
            #     group_id=event.group_id,
            #     messages=[
            #         MessageSegment.node_custom(event.self_id, "ChatGPT", resp)
            #     ]
            # )

    return respond




FriendTrigger = DetectPrefix('')


@bot.on_message('private')
async def _(event: Event):
    if event.message.startswith('.'):
        return
    chain = transform_message_chain(event.message)
    if str(chain[-1]).startswith('.') or str(chain[-1]).startswith(' .'):
        return
    try:
        msg = await FriendTrigger(chain, None)
    except:
        logger.debug(f"丢弃私聊消息：{event.message}（原因：不符合触发前缀）")
        return
    with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
        toml_data = file.read()
    # 解析Toml数据并保留注释
    configDict = tomlkit.parse(toml_data)
    # 现在你可以访问解析后的Toml数据，比如：
    if str(event.user_id) in configDict['black_qq_list']:
        logger.debug(f"黑名单：{event.sender.get('nickname', '群友')}，发送消息：{event.message}")
        return
    logger.debug(f"私聊消息：{event.message}")
    try:
        await handle_message(
            response(event, False),
            f"friend-{event.user_id}",
            msg.display,
            chain,
            is_manager=event.user_id == config.onebot.manager_qq,
            nickname=event.sender.get("nickname", "好友"),
            request_from=constants.BotPlatform.Onebot
        )
    except Exception as e:
        logger.exception(e)
@bot.on_message()
async def _(event: Event):
    if not (".切换账号" in event.message and (str(config.onebot.qq) in re.findall(r'\[CQ:at,qq=(\d+)\]', event.message) or  not event.group_id)):
        return
    with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
        toml_data = file.read()
    # 解析Toml数据并保留注释
    configDict = tomlkit.parse(toml_data)
    code=""
    # 现在你可以访问解析后的Toml数据，比如：
    if str(event.user_id) in configDict['black_qq_list'] or  ('close_group_list' in configDict and str(event.group_id) in configDict['close_group_list']):
        logger.debug(f"黑名单：{event.sender.get('nickname', '群友')}，发送消息：{event.message}")
        return
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
                'https': f"{config.slack.accounts[0].proxy}"
            }
            res=requests.post(f"https://claude.ai/api/auth/send_code",proxies=proxies, impersonate="chrome101", json=data)
            res.raise_for_status()
        except Exception as e:
            res=requests.post(f"https://email.claudeai.ai/claude_api/send_code", impersonate="chrome101", json=data)
        logger.debug(res.text)
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
                'https': f"{config.slack.accounts[0].proxy}"
            }
            data={
                "email_address":f"{connected_values}",
                "recaptcha_token":"03ADUVZwCqKIVpGMy-zn0tuMIgCLC6vXtLXYpMVhxwdoAXF-3S3KApTb3Gl00jWldJ_prVrs2OWhNaW2SX4QxH_xCazjeXMNzxJbrFulG4hLA7URadPbRJmp9ME_c_Dxvnssd01A851TtTYV6hIPOaMXGEJyWEzkId__LkW4sIzlDE69oX-oNVTPd5z9fqOP2VxQqYJblZg17RyOCyl7yUF474nVrJOEFOa-f9-cd7nq7Z6GSCy6vv5SVDDQUq0PTJBzstoI9Zj_vralXSiDz4Z-nP4JJ24AolQHOOEysk09vQfOPO2UDYduSsRXGhS0dRAobRgJbyH50dMHae4GJu17BCGLeKKdyGgOsWI4dkzHMVIzEGb3xiB7nEN9Z41Ftr3UfjscG2Y6AvgSYKpaZEIspqqSje39R-LATTgz7qoixSq1udkB1wvF5-vp34kQaFa94s63zPGjEXB36UOUa_LeOkbonjvAHHTyLHzc3fGjtjX8rTXwr_C7MNjd41kX_UG7lMrOy0KFEzVubvy1nLvOORDlfjDVBwxXPt6A2KocwXfnhLM_mgHxC8V4knwYiHJx8mx83pzVeLmbbTMvGY2nd2f2mjsmPpXzh1yTCa4-Z517t_YVoUhI8t7xYVy0n6TGCXJ9CjrgqIgIOfggnBR0KiVO7Gt42tRtcudcn4js7qoC0GVHTxoCr9pBTatrw7Bmfo_WNBToFiYHLObo-_htu_pQi1rEVz4HlW1nJzwaukNyGVpS5YltAC3APwsvWVvxnBEpYSMblPzw8w7x6d6iv6bPtgZ1OVFzdJxW7-I5jdgAl0aV007GSB0mbdCihapADxLRZwRb0NOOat0IwR6FJqbK6QdduSYB7fb1qbyDsbsCmpiQ3Iw50uJGDgKRg1Z2PW71yrBeZUkuydz4ZrnszThpLFuDyw1O3OJcZhv5lo65pv4gcLHmrPvIjMrL8e8aBc2W4rENz6QhIgDiRRkbcl5ZXFbQbb8ZBQAoZhWHdNAdPYHgmyYzHH8Eyp_r1BVefonr_qxu819Wrz3wkMgKj6r6mQjO8XwenCPtGN6IO3nbClquOL76dLNPBUEAIlwwRLYoqhB7BWMkwEBNnYmxnvBduZCatB9Fx15y7ULt3uMBVQ3PWMr2IfffUOXr4frz43NOrWK6flPE-oZ8pjB8ho9mZHujioy6aiXfO24otcuo3TVjPuVSJRbBWf2vMaOu95k9sdbwlmslduut8MRSTynPkmzVIN-Tiq8By8qDYHRFU_vLGqZfRcf8A0b2nAZflZY8PXd7gqtZa313trRJhlbczsCwkfJK86cn6USnjZlTztHBMD-c_qO1KKW8rtBUNeldFXtdzbkd3YSxkIn9zTpeT1TZ4jvazxj81thg5LZ5zcWFM6seGqgLVvLgsZuuAN92nXma4ufGZFsICVrZ69cNgkkpIBaxrtBOdMROeJDEk-pjBBVvVtE-VNUdMszDHe3Y6gWn9esiBZLI13kBmalsbetlMQQbpXXiNAuCLDGCJ3Z7EmIKCKrk6mOc_KCfGdzUrj9DQmvhrX2zcRmvnU3e79t_0BmcD9EOu3sRIz3YlzcScBMkq74HMX--G5pyE-2KMJllBAOXc9khvJ1ZlNBRA0LxSAtsT2hGxDxaDu7fZhBc6A4V_jMZ-Lgrpf4R1cLBktZwXHLQ-PXsBa7fP2hLO_skBiLi7HjxXDRWpI6HUu6BdUtjDEVSptmaLiqpbWcotTIKGlgyUspRlKIDdnTqZ66cSE-g",
                "recaptcha_site_key":"6LcdsFgmAAAAAMfrnC1hEdmeRQRXCjpy8qT_kvfy"
            }
            res=requests.post(f"https://claude.ai/api/auth/send_code",proxies=proxies, impersonate="chrome101", json=data)
            logger.debug(res.text)
            checkEmail.click()
            count = 0
            while count<10:
                count += 1
                time.sleep(2)
                try:
                    WebDriverWait(emailDriver, 20).until(EC.presence_of_element_located((By.ID, "refresh"))).click()
                    emailDriver.switch_to.frame(emailDriver.find_element_by_id("ifinbox"))
                    e_subject = WebDriverWait(emailDriver, 2).until(EC.presence_of_element_located((By.CLASS_NAME, "lms"))).text
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
        await bot.send(event, "临时邮箱达到本日次数上限，请更换节点")
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
            res= requests.post(f"https://claude.ai/api/auth/verify_code",proxies=proxies, impersonate="chrome101", json=verify)
            logger.debug(res.text)
            logger.debug(res.headers)
            session_key = res.headers["Set-Cookie"].split("sessionKey=")[1].split(";")[0]
            res= requests.get(f"https://claude.ai/api/auth/current_account",headers={"Cookie":f"sessionKey={session_key}"},proxies=proxies, impersonate="chrome101")
            res.raise_for_status()
            data = res.json()
            organization_id = data["account"]["memberships"][0]["organization"]["uuid"]
        except Exception as e:
            verify["verify_code"]=code
            res= requests.post(f"https://email.claudeai.ai/claude_api/verify_code", impersonate="chrome101", json=verify)
            logger.debug(res.text)
            logger.debug(res.headers)
            session_key = res.headers["Set-Cookie"].split("sessionKey=")[1].split(";")[0]
            res= requests.get(f"https://chat.claudeai.ai/api/auth/current_account",headers={"Cookie":f"sessionKey={session_key}"}, impersonate="chrome101")
            res.raise_for_status()
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
    await bot.send(event, "切换账号成功:"+session_key)

@bot.on_message('private')
async def _(event: Event):
    if not event.message.startswith('.'):
        return
    if event.user_id != config.onebot.manager_qq:
        return
    if event.message.startswith('.help'):
        await bot.send(event, ".加载(获取)海艺模型\r\n.加载海艺token(登陆海艺f12-网络-随便接口token)\r\n.开启海艺普通(快速,无限)队列\r\n.git pull(在线更新，需下载git)\r\n.关闭(开启)\r\n.拉黑(拉白)@\r\n.开启（关闭）定时回复3600\r\n.开启（关闭）sd高清\r\n.加载sd接口\r\n.加载（获取）sd模型\r\n.加载sd真人模型\r\n.加载（获取）sd-vae\r\n.获取lora\r\n.切换sd翻译\r\n重新回复\r\n删除上n条对话\r\n重置会话\r\n.加载(关闭)claude2\r\n\r\n缓存会话（claude2专用）\r\n.加载（当前）镜像地址（claude2专用）\r\n.(手动)切换账号（claude2专用）\r\n.切换（当前）邮箱后缀（claude2专用）\r\n.加载最大token(slack酒馆模式专用)")
    if event.message.startswith('.手动切换账号'):
        result = event.message.replace(".手动切换账号","").lstrip()
        proxies = {
            'https': f"{config.slack.accounts[0].proxy}"
        }
        try:
            res= requests.get(f"https://claude.ai/api/auth/current_account",headers={"Cookie":f"sessionKey={result}"},proxies=proxies, impersonate="chrome101")
            res.raise_for_status()
            data = res.json()
            organization_id = data["account"]["memberships"][0]["organization"]["uuid"]
        except Exception as e:
            try:
                res= requests.get(f"https://chat.claudeai.ai/api/auth/current_account",headers={"Cookie":f"sessionKey={result}"}, impersonate="chrome101")
                res.raise_for_status()
                data = res.json()
                organization_id = data["account"]["memberships"][0]["organization"]["uuid"]
            except Exception as e:
                await bot.send(event, f"切换账号失败，当前key不可用")
                return

        with open('config.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        configDict['slack']['accounts'][0]['cookie'] = f"sessionKey={result}"
        configDict['slack']['accounts'][0]['organization_id'] = organization_id
        config.slack.accounts[0].cookie = f"sessionKey={result}"
        config.slack.accounts[0].organization_id = organization_id

        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, f"手动切换账号成功")
    if event.message.startswith('.获取海艺模型'):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        if not "haiyi_all_model" in configDict:
            configDict['haiyi_all_model'] = {"GhostMix2":"05b3523ba5cb7175db74a031cf964e2c|867bf63b9ee7c3c44acda975b4cabca3","ChilloutMix":"81c9105d394d27d8731d3375b8618fa6","Counter3":"038254337d59ef522fdb64268bc28e47|2e40f949adc219bfc0c76cf6868a5001"}
        if not "haiyi_current_model" in configDict:
            configDict['haiyi_current_model'] = "GhostMix2"
        result = ",".join(configDict['haiyi_all_model'].keys())
        current = configDict['haiyi_current_model']
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, f"当前模型:{current},所有海艺模型:{result}")
    if event.message.startswith('.加载海艺模型'):
        result = event.message.replace(".加载海艺模型","").lstrip()
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        if not "haiyi_all_model" in configDict:
            configDict['haiyi_all_model'] = {"GhostMix2":"05b3523ba5cb7175db74a031cf964e2c|867bf63b9ee7c3c44acda975b4cabca3","ChilloutMix":"81c9105d394d27d8731d3375b8618fa6","Counter3":"038254337d59ef522fdb64268bc28e47|2e40f949adc219bfc0c76cf6868a5001"}
        if result in configDict['haiyi_all_model']:
            configDict['haiyi_current_model'] = result
        else:
            all_model = ",".join(configDict['haiyi_all_model'].keys())
            await bot.send(event, f"加载海艺模型失败,所有海艺模型:{all_model}")
            return
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "加载海艺模型成功")
    if event.message.startswith('.加载海艺token'):
        result = event.message.replace(".加载海艺token","").lstrip()
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        configDict['haiyi_token'] = result
        if not "haiyi_all_model" in configDict:
            configDict['haiyi_all_model'] = {"GhostMix2":"05b3523ba5cb7175db74a031cf964e2c|867bf63b9ee7c3c44acda975b4cabca3","ChilloutMix":"81c9105d394d27d8731d3375b8618fa6","Counter3":"038254337d59ef522fdb64268bc28e47|2e40f949adc219bfc0c76cf6868a5001"}
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "加载海艺token成功")
    if event.message.startswith('.开启海艺快速队列'):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        configDict['haiyi_quick'] = 2
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "开启海艺快速队列成功")
    if event.message.startswith('.开启海艺无限队列'):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        configDict['haiyi_quick'] = 3
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "开启海艺无限队列成功")
    if event.message.startswith('.开启海艺普通队列'):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        configDict['haiyi_quick'] = 1
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "开启海艺普通队列成功")
    if event.message.startswith('.加载sd接口'):
        try:
            title = event.message.replace(".加载sd接口","").lstrip()
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{title}sdapi/v1/sd-models")
            data = resp.json()
            config.sdwebui.api_url = event.message.replace(".加载sd接口","").lstrip()
            await bot.send(event, "加载sd接口成功")
        except Exception as e:
            await bot.send(event, f"加载sd接口失败，请确保url正确，例如:{config.sdwebui.api_url}")
    if event.message.startswith('.加载sd模型'):
        try:
            title = event.message.replace(".加载sd模型","").lstrip()
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{config.sdwebui.api_url}sdapi/v1/sd-models")
            data = resp.json()
            titleList = []
            for dto in data:
                titleList.append(dto["title"].split(" ")[0])
            if title in titleList:
                config.sdwebui.default_sd_model = event.message.replace(".加载sd模型","").lstrip()
                await bot.send(event, "加载sd模型成功")
            else:
                await bot.send(event, f"加载sd模型失败，请确保模型名正确，例如:{config.sdwebui.default_sd_model}")
        except Exception as e:
            await bot.send(event, f"加载sd模型失败，当前接口不可用：{config.sdwebui.api_url}")
    if event.message.startswith('.加载sd真人模型'):
        try:
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{config.sdwebui.api_url}sdapi/v1/sd-models")
            data = resp.json()
            title = event.message.replace(".加载sd真人模型","").lstrip()
            titleList = []
            for dto in data:
                titleList.append(dto["title"].split(" ")[0])
            if title in titleList:
                config.sdwebui.default_real_sd_model = event.message.replace(".加载sd真人模型","").lstrip()
                await bot.send(event, "加载sd真人模型成功")
            else:
                await bot.send(event, f"加载sd真人模型失败，请确保模型名正确，例如:{config.sdwebui.default_real_sd_model}")
        except Exception as e:
            await bot.send(event, f"加载sd模型失败，当前接口不可用：{config.sdwebui.api_url}")
    if event.message.startswith('.加载sd-vae'):
        try:
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{config.sdwebui.api_url}sdapi/v1/sd-vae")
            data = resp.json()
            title = event.message.replace(".加载sd-vae","").lstrip()
            titleList = []
            for dto in data:
                titleList.append(dto["model_name"])
            if title in titleList or title=="":
                config.sdwebui.default_sd_vae = title
                await bot.send(event, "加载sd-vae成功")
            else:
                await bot.send(event, f"加载sd-vae失败，请确保vae名正确，例如:{config.sdwebui.default_sd_vae}")
        except Exception as e:
            await bot.send(event, f"加载sd模型失败，当前接口不可用：{config.sdwebui.api_url}")
    if event.message.startswith('.加载claude2'):
        config.slack.claude2 = True
        await bot.send(event, "加载claude2成功")
    if event.message.startswith('.关闭claude2'):
        config.slack.claude2 = False
        await bot.send(event, "关闭claude2成功")
    if event.message.startswith('.获取sd模型'):
        resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{config.sdwebui.api_url}sdapi/v1/sd-models")
        data = resp.json()
        await bot.send(event, '\r\n'.join([dto["title"].split(" ")[0] for dto in data]))
    if event.message.startswith('.获取sd-vae'):
        resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{config.sdwebui.api_url}sdapi/v1/sd-vae")
        data = resp.json()
        await bot.send(event, '\r\n'.join([dto["model_name"] for dto in data]))
    if event.message.startswith('.切换sd翻译'):
        trans = event.message.replace(".切换sd翻译","").lstrip()
        support = ['alibaba', 'apertium', 'argos', 'baidu', 'bing', 'caiyun', 'cloudYi', 'deepl', 'elia']
        if trans in support:
            config.sdwebui.default_trans = trans
            await bot.send(event, "切换sd翻译成功")
        else:
            await bot.send(event, "切换sd翻译失败，仅支持bing,alibaba,baidu,apertium,argos,caiyun,cloudYi,deepl,elia")
    if event.message.startswith('.获取lora'):
        resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(f"{config.sdwebui.api_url}sdapi/v1/loras")
        data = resp.json()
        await bot.send(event, '\r\n'.join(["<lora:"+dto["name"]+":1>" for dto in data]))
    if event.message.startswith('.开启sd高清'):
        config.sdwebui.enable_hr = True
        await bot.send(event, '开启sd高清成功')
    if event.message.startswith('.关闭sd高清'):
        config.sdwebui.enable_hr = False
        await bot.send(event, '关闭sd高清成功')
    if event.message.startswith('.加载最大token'):
        try:
            config.slack.slack_max_token = int(event.message.replace(".加载最大token","").replace(" ",""))
            await bot.send(event, "加载最大token成功")
        except Exception as e:
            await bot.send(event, f"加载最大token成功,示例：.加载最大token4000")

task_dict = {}

@bot.on_message()
async def _(event: Event):
    message = re.sub(r'\[CQ.*?\]', '', event.message,1).lstrip()
    if not message.startswith('.'):
        return
    # chain = transform_message_chain(event.message)
    # try:
    #     for it in GroupTrigger:
    #         chain = await it(chain, event)
    # except Exceptionas as e:
    #     logger.debug(e)
    #     return
    if message.startswith('.git pull'):
        result = re.findall(r'\[CQ:at,qq=(\d+)\]', event.message)
        if str(config.onebot.qq) in result or not event.group_id:
            current_directory = os.path.dirname(os.path.abspath(__file__))
            git_repo_path = os.path.dirname(os.path.dirname(current_directory))
            start_cmd = "start /D {} 启动ChatGPT.cmd".format(git_repo_path)
            try:
                subprocess.run(["git", "pull"], cwd=git_repo_path, capture_output=True, text=True, check=True)
            except:
                await bot.send(event, "在线更新失败，存在冲突文件，请手动更新")
                return
            subprocess_obj = subprocess.Popen(start_cmd, shell=True, close_fds=True)

            # 等待子进程终止
            subprocess_obj.wait()
            await bot.send(event, "在线更新完成")
            asyncio.get_event_loop().stop()
            os._exit(0)
            return
    if event.user_id == config.onebot.manager_qq and message.startswith('.拉黑'):
        result = re.findall(r'\[CQ:at,qq=(\d+)\]', message)
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        if "black_qq_list" in  configDict:
            configDict['black_qq_list'] = list(set(configDict['black_qq_list']+result))
        else:
            configDict['black_qq_list'] = result
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "拉黑成功")
    if event.user_id == config.onebot.manager_qq and message == '.关闭':
        result = [str(event.group_id)]
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        if "close_group_list" in  configDict:
            configDict['close_group_list'] = list(set(configDict['close_group_list']+result))
        else:
            configDict['close_group_list'] = result
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "关闭成功")
    if event.user_id == config.onebot.manager_qq and message.startswith('.拉白'):
        result = re.findall(r'\[CQ:at,qq=(\d+)\]', message)
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        if  "black_qq_list" in  configDict:
            configDict['black_qq_list'] = [item for item in configDict['black_qq_list'] if item not in result]
        else:
            configDict['black_qq_list'] = []
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "拉白成功")
    if event.user_id == config.onebot.manager_qq and message == '.开启':
        result = [str(event.group_id)]
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：
        if  "close_group_list" in  configDict:
            configDict['close_group_list'] = [item for item in configDict['close_group_list'] if item not in result]
        else:
            configDict['close_group_list'] = []
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "开启成功")
    if event.user_id == config.onebot.manager_qq and message.startswith('.切换邮箱后缀'):
        result = message.replace('.切换邮箱后缀','').lstrip()
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：

        configDict['email_suffix'] = result
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "切换邮箱后缀成功")

    if event.user_id == config.onebot.manager_qq and message.startswith('.当前邮箱后缀'):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：

        if  "email_suffix" in  configDict:
            email=configDict['email_suffix']
        else:
            email=""

        await bot.send(event, "当前邮箱后缀:"+email+"(为空时每日随机,不可用时请前往https://yopmail.com/zh/email-generator获取)")
    if event.user_id == config.onebot.manager_qq and message.startswith('.加载镜像地址'):
        result = message.replace('.加载镜像地址','').lstrip().replace("https://","").replace("http://","").replace("点",".")
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：

        configDict['claude2_url'] = result
        # 将修改后的数据写入Toml文件，并保留原有的注释
        with open('config/newConfig.cfg', 'w', encoding='utf-8-sig') as file:
            file.write(tomlkit.dumps(configDict))
        await bot.send(event, "加载镜像地址成功")

    if event.user_id == config.onebot.manager_qq and message.startswith('.当前镜像地址'):
        with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
            toml_data = file.read()
            # 解析Toml数据并保留注释
        configDict = tomlkit.parse(toml_data)
        # 现在你可以访问解析后的Toml数据，比如：

        if  "claude2_url" in  configDict:
            email=configDict['claude2_url']
        else:
            email="claude.ai"

        await bot.send(event, ("当前镜像地址:"+email+"(测试可用：chat.claudeai.ai)").replace(".","点"))



@bot.on_message('group')
async def _(event: Event):
    message = re.sub(r'\[CQ.*?\]', '', event.message).lstrip()
    if not message.startswith('.'):
        return
    chain = transform_message_chain(event.message)
    try:
        for it in GroupTrigger:
            chain = await it(chain, event)
    except:
        return
    with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
        toml_data = file.read()
    # 解析Toml数据并保留注释
    configDict = tomlkit.parse(toml_data)
    # 现在你可以访问解析后的Toml数据，比如：
    if str(event.user_id) in configDict['black_qq_list'] or ('close_group_list' in configDict and str(event.group_id) in configDict['close_group_list']):
        logger.debug(f"黑名单：{event.sender.get('nickname', '群友')}，发送消息：{event.message}")
        return
    groupId =  event.group_id
    if message.startswith('.开启定时回复'):
        if event.user_id != config.onebot.manager_qq:
            return await bot.send(event, "您没有权限执行这个操作")
        interval = int(message.replace(".开启定时回复","").lstrip())
        if groupId in task_dict:
            old_task = task_dict[groupId]
            old_task.cancel()
        # 创建新的定时任务
        task = asyncio.create_task(task_function(event, interval))
        task_dict[groupId] = task
        await bot.send(event, "开启定时回复成功")
    if message.startswith('.关闭定时回复'):
        if groupId in task_dict:
            old_task = task_dict[groupId]
            old_task.cancel()
        await bot.send(event, "关闭定时回复成功")
async def task_function(event, interval):
    event.message_id = ""
    event.message = "(无人回应，请根据当前情景进行互动，必须推动情节发展，禁止重复聊天记录中的内容，禁止输出system的内容)"
    while True:
        await asyncio.sleep(interval)
        lastTime = time.time()
        if os.path.exists(f'config/定时回复-group-{event.group_id}.pickle'):
            with open(f'config/定时回复-group-{event.group_id}.pickle', "rb") as file:
                data_dict = pickle.load(file)
        if event.group_id in data_dict:
            lastTime = data_dict[event.group_id]
        if time.time()-lastTime > interval:
            chain = transform_message_chain(event.message)
            await handle_message(
                response(event, True),
                f"group-{event.group_id}",
                "(无人回应，请根据当前情景进行互动，必须推动情节发展，禁止重复聊天记录中的内容，禁止输出system的内容)",
                chain,
                is_manager=event.user_id == config.onebot.manager_qq,
                nickname="system",
                request_from=constants.BotPlatform.Onebot
            )

GroupTrigger = [MentionMe(config.trigger.require_mention != "at"), DetectPrefix(
    config.trigger.prefix + config.trigger.prefix_group)] if config.trigger.require_mention != "none" else [
    DetectPrefix(config.trigger.prefix)]


@bot.on_message('group')
async def _(event: Event):
    message = re.sub(r'\[CQ.*?\]', '', event.message,1).lstrip()
    if message.startswith('.'):
        return
    if message.startswith('.') or message.startswith('#撤回'):
        return
    chain = transform_message_chain(event.message)
    if str(chain[-1]).startswith('.') or str(chain[-1]).startswith(' .') or str(chain[-1]).startswith(' #撤回') or str(chain[-1]).startswith('#撤回'):
        return
    try:
        for it in GroupTrigger:
            chain = await it(chain, event)
    except:
        # logger.debug(f"丢弃群聊消息：{event.message}（原因：不符合触发前缀）")
        return

    with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
        toml_data = file.read()
    # 解析Toml数据并保留注释
    configDict = tomlkit.parse(toml_data)
    # 现在你可以访问解析后的Toml数据，比如：
    if str(event.user_id) in configDict['black_qq_list'] or  ('close_group_list' in configDict and str(event.group_id) in configDict['close_group_list']):
        logger.debug(f"黑名单：{event.sender.get('nickname', '群友')}，发送消息：{event.message}")
        return

    logger.debug(f"群聊消息：{event.message}")
    data_dict = {}
    if os.path.exists(f'config/定时回复-group-{event.group_id}.pickle'):
        with open(f'config/定时回复-group-{event.group_id}.pickle', "rb") as file:
            data_dict = pickle.load(file)
    data_dict[event.group_id] = time.time()
    with open(f'config/定时回复-group-{event.group_id}.pickle', "wb") as file:
        pickle.dump(data_dict, file)

    max_timeout =config.response.max_timeout
    if '缓存会话' in chain.display:
        config.response.max_timeout = 3600
    await handle_message(
        response(event, True),
        f"group-{event.group_id}",
        chain.display,
        chain,
        is_manager=event.user_id == config.onebot.manager_qq,
        nickname=event.sender.get("nickname", "群友"),
        request_from=constants.BotPlatform.Onebot
    )
    config.response.max_timeout = max_timeout


@bot.on_message()
async def _(event: Event):
    if event.message != ".reload":
        return
    if event.user_id != config.onebot.manager_qq:
        return await bot.send(event, "您没有权限执行这个操作")
    constants.config = config.load_config()
    config.scan_presets()
    await bot.send(event, "配置文件重新载入完毕！")
    await bot.send(event, "重新登录账号中，详情请看控制台日志……")
    constants.botManager = BotManager(config)
    await botManager.login()
    await bot.send(event, "登录结束")

@bot.on_message()
async def _(event: Event):
    if ".撤回" not in event.message and "#撤回" not in event.message:
        return
    matchReply = re.search(r'\[CQ:reply,id=(-?\d+)\]', event.message)
    if matchReply:
        await bot.call_action(
            "delete_msg",
            message_id=matchReply.group(1),
        )
    else:
        matchReply = re.search(r'\[CQ:at,qq=(\d+)\]', event.message)
        if matchReply and str(matchReply.group(1)) == str(config.onebot.qq):
            try:
                await bot.call_action(
                    "delete_msg",
                    message_id=get_from_map(f"lastMessageId-{event.group_id}"),
                )
            except:
                await bot.send(event, "仅支持撤回最近的消息，请回复消息进行撤回")



# @bot.on_message()
# async def _(event: Event):
#     if event.message != ".help":
#         return
#     await bot.send(event, "帮助：输入.help弹出")


# @bot.on_message()
# async def _(event: Event):
#     pattern = r"\.设置\s+(\w+)\s+(\S+)\s+额度为\s+(\d+)\s+条/小时"
#     match = re.match(pattern, event.message.strip())
#     if not match:
#         return
#     if event.user_id != config.onebot.manager_qq:
#         return await bot.send(event, "您没有权限执行这个操作")
#     msg_type, msg_id, rate = match.groups()
#     rate = int(rate)
#
#     if msg_type not in ["群组", "好友"]:
#         return await bot.send(event, "类型异常，仅支持设定【群组】或【好友】的额度")
#     if msg_id != '默认' and not msg_id.isdecimal():
#         return await bot.send(event, "目标异常，仅支持设定【默认】或【指定 QQ（群）号】的额度")
#     ratelimit_manager.update(msg_type, msg_id, rate)
#     return await bot.send(event, "额度更新成功！")
#
#
# @bot.on_message()
# async def _(event: Event):
#     pattern = r"\.设置\s+(\w+)\s+(\S+)\s+画图额度为\s+(\d+)\s+个/小时"
#     match = re.match(pattern, event.message.strip())
#     if not match:
#         return
#     if event.user_id != config.onebot.manager_qq:
#         return await bot.send(event, "您没有权限执行这个操作")
#     msg_type, msg_id, rate = match.groups()
#     rate = int(rate)
#
#     if msg_type not in ["群组", "好友"]:
#         return await bot.send(event, "类型异常，仅支持设定【群组】或【好友】的额度")
#     if msg_id != '默认' and not msg_id.isdecimal():
#         return await bot.send(event, "目标异常，仅支持设定【默认】或【指定 QQ（群）号】的额度")
#     ratelimit_manager.update_draw(msg_type, msg_id, rate)
#     return await bot.send(event, "额度更新成功！")
#
#
# @bot.on_message()
# async def _(event: Event):
#     pattern = r"\.查看\s+(\w+)\s+(\S+)\s+的使用情况"
#     match = re.match(pattern, event.message.strip())
#     if not match:
#         return
#
#     msg_type, msg_id = match.groups()
#
#     if msg_type not in ["群组", "好友"]:
#         return await bot.send(event, "类型异常，仅支持设定【群组】或【好友】的额度")
#     if msg_id != '默认' and not msg_id.isdecimal():
#         return await bot.send(event, "目标异常，仅支持设定【默认】或【指定 QQ（群）号】的额度")
#     limit = ratelimit_manager.get_limit(msg_type, msg_id)
#     if limit is None:
#         return await bot.send(event, f"{msg_type} {msg_id} 没有额度限制。")
#     usage = ratelimit_manager.get_usage(msg_type, msg_id)
#     current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
#     return await bot.send(event,
#                           f"{msg_type} {msg_id} 的额度使用情况：{limit['rate']}条/小时， 当前已发送：{usage['count']}条消息\n整点重置，当前服务器时间：{current_time}")
#
#
# @bot.on_message()
# async def _(event: Event):
#     pattern = r"\.查看\s+(\w+)\s+(\S+)\s+的画图使用情况"
#     match = re.match(pattern, event.message.strip())
#     if not match:
#         return
#
#     msg_type, msg_id = match.groups()
#
#     if msg_type not in ["群组", "好友"]:
#         return await bot.send(event, "类型异常，仅支持设定【群组】或【好友】的额度")
#     if msg_id != '默认' and not msg_id.isdecimal():
#         return await bot.send(event, "目标异常，仅支持设定【默认】或【指定 QQ（群）号】的额度")
#     limit = ratelimit_manager.get_draw_limit(msg_type, msg_id)
#     if limit is None:
#         return await bot.send(event, f"{msg_type} {msg_id} 没有额度限制。")
#     usage = ratelimit_manager.get_draw_usage(msg_type, msg_id)
#     current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
#     return await bot.send(event,
#                           f"{msg_type} {msg_id} 的额度使用情况：{limit['rate']}个图/小时， 当前已绘制：{usage['count']}个图\n整点重置，当前服务器时间：{current_time}")
#
#
# @bot.on_message()
# async def _(event: Event):
#     pattern = ".预设列表"
#     event.message = str(event.message)
#     if event.message.strip() != pattern:
#         return
#
#     if config.presets.hide and event.user_id != config.onebot.manager_qq:
#         return await bot.send(event, "您没有权限执行这个操作")
#     nodes = []
#     for keyword, path in config.presets.keywords.items():
#         try:
#             with open(path, 'rb') as f:
#                 guessed_str = from_bytes(f.read()).best()
#                 preset_data = str(guessed_str).replace("\n\n", "\n=========\n")
#             answer = f"预设名：{keyword}\n{preset_data}"
#
#             node = MessageSegment.node_custom(event.self_id, "ChatGPT", answer)
#             nodes.append(node)
#         except Exception as e:
#             logger.error(e)
#
#     if not nodes:
#         await bot.send(event, "没有查询到任何预设！")
#         return
#     try:
#         if event.group_id:
#             await bot.call_action("send_group_forward_msg", group_id=event.group_id, messages=nodes)
#         else:
#             await bot.call_action("send_private_forward_msg", user_id=event.user_id, messages=nodes)
#     except Exception as e:
#         logger.exception(e)
#         await bot.send(event, "消息发送失败！请在私聊中查看。")


@bot.on_request
async def _(event: Event):
    if config.system.accept_friend_request:
        await bot.call_action(
            action='.handle_quick_operation_async',
            self_id=event.self_id,
            context=event,
            operation={'approve': True}
        )


@bot.on_request
async def _(event: Event):
    if config.system.accept_group_invite:
        await bot.call_action(
            action='.handle_quick_operation_async',
            self_id=event.self_id,
            context=event,
            operation={'approve': True}
        )


@bot.on_startup
async def startup():
    logger.success("启动完毕，接收消息中……")


async def start_task():
    """|coro|
    以异步方式启动
    """
    return await bot.run_task(host=config.onebot.reverse_ws_host, port=config.onebot.reverse_ws_port)
