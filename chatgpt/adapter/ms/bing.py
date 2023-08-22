import json
from io import BytesIO
from typing import Generator, Union, List

import aiohttp
import asyncio
from PIL import Image

from constants import config
from adapter.botservice import BotAdapter
from EdgeGPT import Chatbot as EdgeChatbot, ConversationStyle, NotAllowedToAccess
from contextlib import suppress

from constants import botManager
from drawing import DrawingAPI
from exceptions import BotOperationNotSupportedException
from loguru import logger
import re
from ImageGen import ImageGenAsync
from graia.ariadne.message.element import Image as GraiaImage
import time
import datetime
import pickle
import os

image_pattern = r"!\[.*\]\((.*)\)"


class BingAdapter(BotAdapter, DrawingAPI):
    cookieData = None
    count: int = 0

    conversation_style: ConversationStyle = None

    bot: EdgeChatbot
    """实例"""

    def __init__(self, session_id: str = "unknown",isSilly=False, conversation_style: ConversationStyle = ConversationStyle.creative):
        super().__init__(session_id)
        self.session_id = session_id
        self.conversation_style = conversation_style
        self.sillyMessage = {}
        self.role_name: str = config.onebot.qq_nick_name
        self.groupMember = []
        self.isSilly = isSilly
        self.supported_models = [
            "claude"
        ]
        self.role_desc=''

        account = botManager.pick('bing-cookie')
        self.cookieData = []
        if account.cookie_content.strip().startswith('['):
            self.cookieData = json.loads(account.cookie_content)
        else:
            for line in account.cookie_content.split("; "):
                name, value = line.split("=", 1)
                self.cookieData.append({"name": name, "value": value})
        try:
            self.bot = EdgeChatbot(cookies=self.cookieData, proxy=account.proxy)
        except NotAllowedToAccess as e:
            raise Exception("Bing 账号 Cookie 已过期，请联系管理员更新！") from e

    async def rollback(self):
        raise BotOperationNotSupportedException()

    async def on_reset(self):
        self.count = 0
        await self.bot.reset()
    async def ask_stream_single(self,prompt,conversation_style,wss_link,count):
        if count>3:
            return ["ask bing 失败"]
        return self.bot.ask_stream(prompt=prompt,
                                           conversation_style=conversation_style,
                                           wss_link=wss_link)
    async def ask(self, prompt) -> Generator[str, None, None]:
        if not self.isSilly:
            async for content1 in self.ask1(self,prompt):
                yield content1
            return
        sillyMessage = self.sillyMessage
        totalSillyMessage = {}
        if os.path.exists(f'{self.session_id}.pickle'):
            with open(f'{self.session_id}.pickle', "rb") as file:
                sillyMessage = pickle.load(file)
        if os.path.exists(f'total-{self.session_id}.pickle'):
            with open(f'total-{self.session_id}.pickle', "rb") as file:
                totalSillyMessage = pickle.load(file)
        NSFW = config.presets.third_NSFW if self.third_reply_mode else config.presets.NSFW
        main = config.presets.third_main if self.third_reply_mode else config.presets.main
        Jailbreak = config.presets.third_Jailbreak if self.third_reply_mode else config.presets.Jailbreak
        slack_ping_message = config.slack.third_slack_ping_message if self.third_reply_mode else config.slack.slack_ping_message
        personRule = ', and reply to the object in the third person' if self.third_reply_mode else ', and reply to the object in the first person'
        initMessages = [{
            "role":"system",
            "content": (NSFW+main+"\n\n"+self.role_desc+"\n").replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)
        },{
            "role":"system",
            "content":"[This is a group chat, please lock the last speaker as the conversation object"+personRule+"]\n[Start a new group chat. Group members: "+','.join(self.groupMember)+"]\n"
        },{
            "role":"system",
            "content":"\n\n[current date time:'"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+"',The current event must be chosen reasonably based on the current date time(24-hour clock)]\n[last speaker:"+self.nickname+",According to the current date time and the last conversation('"+prompt+"'),make a reasonable reply directly as "+self.role_name+", and it is forbidden to repeat the content in the dialogue record]"
        },{
            "role":"system",
            "content":"[last chat time:"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+f",previous scenario:<desc>{self.init_scene}</desc>]"
        },{
            "role":"system",
            "content":Jailbreak.replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)
        }]
        if sillyMessage == {}:
            stream = False
            sillyMessage["messages"] = initMessages
        if totalSillyMessage == {}:
            totalSillyMessage["messages"] = copy.deepcopy(initMessages)
        if self.nickname not in self.groupMember:
            self.groupMember.append(self.nickname)
            sillyMessage["messages"][1] = {
                "role":"system",
                "content":"[This is a group chat, please lock the last speaker as the conversation object"+personRule+"]\n[Start a new group chat. Group members: "+','.join(self.groupMember)+"]"
            }

        sillyMessage["stream"] = False
        sillyMessage["pingConfig"] = {"MAINPROMPT_LAST":config.slack.slack_main_last,"PING_MESSAGE":slack_ping_message.replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)}
        sillyMessage["config"] = {"TOKEN":config.slack.slack_token,"COOKIE":config.slack.slack_cookie,"TEAM_ID":config.slack.slack_team_id,"CHANNEL":config.slack.slack_channel,"CLAUDE_USER":config.slack.slack_claude_user}
        newChat = {"role":"user","content":'('+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+')'+self.nickname+': "'+prompt+'"'}

        match = re.match(r'^删除上(\d+)条对话$', prompt.strip())
        if match:
            # 获取匹配到的数字n
            n = int(match.group(1))
            messages = sillyMessage["messages"]
            totalMessages = totalSillyMessage["messages"]
            # 删除数组中的倒数第四至倒数第(n+3)条记录
            if len(messages) >= n + 5:
                del messages[-4:-4-n:-1]
                del totalMessages[-4:-4-n:-1]
                yield f"已删除上{n}条对话"
                with open(f'{self.session_id}.pickle', "wb") as file:
                    pickle.dump(sillyMessage, file)
                with open(f'total-{self.session_id}.pickle', "wb") as file:
                    pickle.dump(totalSillyMessage, file)
                return
            else:
                yield f'无法删除 {n} 条对话，当前对话记录长度:{len(messages)-5}。'
                return
        if( "重新回复" in  prompt):
            if not repeat:
                sillyMessage["messages"].pop(-4)
                totalSillyMessage["messages"].pop(-4)
        else:
            sillyMessage["messages"].insert(-3, newChat)
            totalSillyMessage["messages"].insert(-3, newChat)

        sillyMessage["messages"][-1] = {
            "role":"system",
            "content":Jailbreak.replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)
        }
        totalSillyMessage["messages"][-1] = {
            "role":"system",
            "content":Jailbreak.replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)
        }
        match = re.search("上一次的聊天总结：\n(.*)", sillyMessage["messages"][0]["content"], flags=re.DOTALL)
        first = ""
        if match:
            first = "上一次的聊天总结：\n"+match.group(1)
        else:
            pattern = r"上一次的聊天总结：(.+)"  # 这里的r表示原始字符串，.*表示匹配任意字符（除了换行符）零次或多次
            match = re.search(pattern, sillyMessage["messages"][0]["content"], flags=re.DOTALL)
            if match:
                first = "上一次的聊天总结：\n"+match.group(1)

        sillyMessage["messages"][0] = {
            "role":"system",
            "content": (NSFW+main+"\n\n"+self.role_desc+"\n").replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)+first
        }
        totalSillyMessage["messages"][0] = {
            "role":"system",
            "content": (NSFW+main+"\n\n"+self.role_desc+"\n").replace("{{char}}",self.role_name).replace("{{user}}",self.nickname)
        }
        lastContent = sillyMessage["messages"][-4]["content"]
        logger.debug(sillyMessage["messages"][-2]["content"])
        lastTime = sillyMessage["messages"][-2]["content"].split("last chat time:")[1].split(",previous scenario")[0]
        time1 = datetime.datetime.strptime(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "%Y-%m-%d %H:%M:%S")
        time2 = datetime.datetime.strptime(lastTime, "%Y-%m-%d %H:%M:%S")
        time_difference = abs(time1 - time2)  # 计算时间差（绝对值）
        hours_difference = time_difference.total_seconds() / 3600  # 将时间差转换为小时
        content1 = ',Please ignore previous topics and situations,according to the current date time and the last conversation(' if hours_difference > 2 else ',according to the current date time and the last conversation('
        sillyMessage["messages"][-3] = {
            "role":"system",
            "content":"\n\n[current date time:'"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+"',The current event must be chosen reasonably based on the current date time(24-hour clock)]\n[last speaker:"+lastContent.split(": ")[0].split(")")[1]+""+content1+""+lastContent.split(": ")[1]+"),make a reasonable reply directly as "+self.role_name+", and it is forbidden to repeat the content in the dialogue record and chat record]"
        }
        totalSillyMessage["messages"][-3] = {
            "role":"system",
            "content":"\n\n[current date time:'"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+"',The current event must be chosen reasonably based on the current date time(24-hour clock)]\n[last speaker:"+lastContent.split(": ")[0].split(")")[1]+""+content1+""+lastContent.split(": ")[1]+"),make a reasonable reply directly as "+self.role_name+", and it is forbidden to repeat the content in the dialogue record and chat record]"
        }
        if hours_difference > 2:
            updateLastContent = re.sub(r'<desc>.*?</desc>', f'previous scenario:<desc>{self.init_scene}</desc>', sillyMessage["messages"][-2]["content"])
            sillyMessage["messages"][-2] = {
                "role":"system",
                "content":updateLastContent
            }
            totalSillyMessage["messages"][-2] = {
                "role":"system",
                "content":updateLastContent
            }

        try:
            parsed_content = ''
            prompt= '\n'.join(item['content'] for item in sillyMessage["messages"])
            await self.on_reset()
            count = 0;
            try:
                responseList = await self.ask_stream_single(prompt,self.conversation_style,config.bing.wss_link,count)
            except Exception as e:
                logger.debug(f'ask bing 失败{e}')
                responseList = await self.ask_stream_single(prompt,self.conversation_style,config.bing.wss_link,count)
            async for final, response in responseList:
                if not response:
                    continue

                if final:
                    # 最后一条消息
                    max_messages = config.bing.max_messages
                    with suppress(KeyError):
                        max_messages = response["item"]["throttling"]["maxNumUserMessagesInConversation"]

                    with suppress(KeyError):
                        raw_text = response["item"]["messages"][1]["adaptiveCards"][0]["body"][0]["text"]
                        image_urls = re.findall(image_pattern, raw_text)

                    remaining_conversations = f'\n剩余回复数：{self.count} / {max_messages} ' \
                        if config.bing.show_remaining_count else ''

                    if len(response["item"].get('messages', [])) > 1 and config.bing.show_suggestions:
                        suggestions = response["item"]["messages"][-1].get("suggestedResponses", [])
                        if len(suggestions) > 0:
                            parsed_content = parsed_content + '\n猜你想问：  \n'
                            for suggestion in suggestions:
                                parsed_content = f"{parsed_content}* {suggestion.get('text')}  \n"

                    parsed_content = parsed_content + remaining_conversations

                else:
                    # 生成中的消息
                    parsed_content = re.sub(r"\[\^\d+\^\]", "", response)
                    if config.bing.show_references:
                        parsed_content = re.sub(r"\[(\d+)\]: ", r"\1: ", parsed_content)
                    else:
                        parsed_content = re.sub(r"(\[\d+\]\: .+)+", "", parsed_content)
                    parts = re.split(image_pattern, parsed_content)
                    # 图片单独保存
                    parsed_content = parts[0]

                    if len(parts) > 2:
                        parsed_content = parsed_content + parts[-1]
            logger.debug(parsed_content)
            message: str = parsed_content
            message = message.replace("&lt;","<").replace("&gt;",">").replace("第一段","").replace('发言人',self.nickname).replace("<第一段>","").replace("<第二段>","").replace(f"{self.role_name}：","").replace(f"{self.role_name}:","").replace(f"{self.role_name}的回复","").replace(f"({self.role_name})","").replace(f"</{self.role_name}>","").replace(f"<{self.role_name}>","").replace("<第一段回复>","").replace("(第一段回复)","").replace("(第二段回复)","").replace("<第二段回复>","").replace("(1段回复)","").replace("<两段回复>","").replace(f"<{self.role_name}的回复>","").replace("Claude","").replace("<p>","").replace("</p>","").replace("<article>","").replace("</article>","").replace("A: ","").replace("♪","").replace("A:","").replace("Assistant:","").lstrip()
            lines = message.splitlines()
            clean_lines = [line.strip() for line in lines if line.strip()]
            message = '\n'.join(clean_lines)
            message = re.sub(r'\[.*?\]', '', message).replace(f"<{self.role_name}>","")
            if not message.startswith(' <desc>') and not message.startswith('<desc>') and '</desc>' in message:
                message=message.split('</desc>')[0]+'</desc>'
            message = re.sub(r'\(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\)', '', message).replace(f"{self.role_name}：","").replace(f"{self.role_name}:","")
            message = re.sub(r"<desc>(.*?)<\/desc>", lambda match: match.group(0).replace(self.role_name, "female"), message, flags=re.DOTALL)
            message = re.sub(r"<desc>(.*?)<\/desc>", lambda match: match.group(0).replace(self.nickname, "male"), message, flags=re.DOTALL)
            message=message.lstrip()
            filterMessage = message
            filterMessage = filterMessage.replace("&lt;",'<').replace('&gt;','>')
            filterMessage = re.sub(r"<desc>(.*?)</desc>", "", filterMessage, flags=re.DOTALL)
            filterMessage = re.sub(r"desc(.*?)/desc", "", filterMessage, flags=re.DOTALL)
            filterMessage = filterMessage.replace('amp;','').replace("()","").replace("Claude :","").replace("\n","")
            if 'previous scenario:' in filterMessage:
                filterMessage = filterMessage.split("previous scenario:")[1]
            newReply = {"role":"assistant","content":'('+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+')'+f'{self.role_name}: "'+filterMessage+'"'}

            match = re.findall(r"<desc>(.*?)</desc>", message, flags=re.DOTALL)
            desc=None
            if match:
                desc = "，".join(match)
            else:
                match = re.findall(r"desc(.*?)/desc", message, flags=re.DOTALL)
                if match:
                    desc="，".join(match)
            if (not match or filterMessage=="") and count < 5:
                logger.debug(message)
                if not "重新回复" in prompt:
                    sillyMessage["messages"].pop(-4)
                    totalSillyMessage["messages"].pop(-4)
                with open(f'{self.session_id}.pickle', "wb") as file:
                    pickle.dump(sillyMessage, file)
                with open(f'total-{self.session_id}.pickle', "wb") as file:
                    pickle.dump(totalSillyMessage, file)
                count += 1
                async for content1 in self.ask(prompt,True,count):
                    yield content1
                return
            sillyMessage["messages"].insert(-3, newReply)
            totalSillyMessage["messages"].insert(-3, newReply)
            if desc:
                sillyMessage["messages"][-2] = {
                    "role":"system",
                    "content":"[last chat time:"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+",previous scenario:<desc>"+desc+"</desc>]"
                }
                totalSillyMessage["messages"][-2] = {
                    "role":"system",
                    "content":"[last chat time:"+datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")+",previous scenario:<desc>"+desc+"</desc>]"
                }
            self.sillyMessage = sillyMessage
            yield message
            # 将map对象持久化到本地文件
            with open(f'{self.session_id}.pickle', "wb") as file:
                pickle.dump(self.sillyMessage, file)
            with open(f'total-{self.session_id}.pickle', "wb") as file:
                pickle.dump(totalSillyMessage, file)
        except Exception as e:
            logger.exception(e)
            sillyMessage["messages"].pop(-4)
            yield "网络故障，请重新回复"

    async def ask1(self, prompt: str) -> Generator[str, None, None]:
        self.count = self.count + 1
        parsed_content = ''
        image_urls = []
        try:
            async for final, response in self.bot.ask_stream(prompt=prompt,
                                                             conversation_style=self.conversation_style,
                                                             wss_link=config.bing.wss_link):
                if not response:
                    continue

                if final:
                    # 最后一条消息
                    max_messages = config.bing.max_messages
                    with suppress(KeyError):
                        max_messages = response["item"]["throttling"]["maxNumUserMessagesInConversation"]

                    with suppress(KeyError):
                        raw_text = response["item"]["messages"][1]["adaptiveCards"][0]["body"][0]["text"]
                        image_urls = re.findall(image_pattern, raw_text)

                    remaining_conversations = f'\n剩余回复数：{self.count} / {max_messages} ' \
                        if config.bing.show_remaining_count else ''

                    if len(response["item"].get('messages', [])) > 1 and config.bing.show_suggestions:
                        suggestions = response["item"]["messages"][-1].get("suggestedResponses", [])
                        if len(suggestions) > 0:
                            parsed_content = parsed_content + '\n猜你想问：  \n'
                            for suggestion in suggestions:
                                parsed_content = f"{parsed_content}* {suggestion.get('text')}  \n"

                    parsed_content = parsed_content + remaining_conversations

                    if parsed_content == remaining_conversations:  # No content
                        yield "Bing 已结束本次会话。继续发送消息将重新开启一个新会话。"
                        await self.on_reset()
                        return
                else:
                    # 生成中的消息
                    parsed_content = re.sub(r"\[\^\d+\^\]", "", response)
                    if config.bing.show_references:
                        parsed_content = re.sub(r"\[(\d+)\]: ", r"\1: ", parsed_content)
                    else:
                        parsed_content = re.sub(r"(\[\d+\]\: .+)+", "", parsed_content)
                    parts = re.split(image_pattern, parsed_content)
                    # 图片单独保存
                    parsed_content = parts[0]

                    if len(parts) > 2:
                        parsed_content = parsed_content + parts[-1]

                yield parsed_content
            logger.debug(f"[Bing AI 响应] {parsed_content}")
            image_tasks = [
                asyncio.create_task(self.__download_image(url))
                for url in image_urls
            ]
            for image in await asyncio.gather(*image_tasks):
                yield image
        except (asyncio.exceptions.TimeoutError, asyncio.exceptions.CancelledError) as e:
            raise e
        except NotAllowedToAccess:
            yield "出现错误：机器人的 Bing Cookie 可能已过期，或者机器人当前使用的 IP 无法使用 Bing AI。"
            return
        except Exception as e:
            if str(e) == 'Redirect failed':
                yield '画图失败：Redirect failed'
                return
            raise e

    async def text_to_img(self, prompt: str):
        logger.debug(f"[Bing Image] Prompt: {prompt}")
        try:
            async with ImageGenAsync(
                    next((cookie['value'] for cookie in self.bot.cookies if cookie['name'] == '_U'), None),
                    False
            ) as image_generator:
                images = await image_generator.get_images(prompt)

                logger.debug(f"[Bing Image] Response: {images}")
                tasks = [asyncio.create_task(self.__download_image(image)) for image in images]
                return await asyncio.gather(*tasks)
        except Exception as e:
            if str(e) == 'Redirect failed':
                raise Exception('画图失败：Redirect failed') from e
            raise e


    async def img_to_img(self, init_images: List[GraiaImage], prompt=''):
        return await self.text_to_img(prompt)

    async def __download_image(self, url) -> GraiaImage:
        logger.debug(f"[Bing AI] 下载图片：{url}")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, proxy=self.bot.proxy) as resp:
                resp.raise_for_status()
                logger.debug(f"[Bing AI] 下载完成：{resp.content_type} {url}")
                return GraiaImage(data_bytes=await resp.read())

    async def preset_ask(self, role: str, text: str):
        yield None  # Bing 不使用预设功能
