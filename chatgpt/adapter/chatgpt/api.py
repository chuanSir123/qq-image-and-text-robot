import ctypes
import os
from typing import Generator
import openai
from loguru import logger
from revChatGPT.V3 import Chatbot as OpenAIChatbot

from adapter.botservice import BotAdapter
from config import OpenAIAPIKey
from constants import botManager, config
import re
import time
import datetime
import pickle
import os
import copy

hashu = lambda word: ctypes.c_uint64(hash(word)).value



class ChatGPTAPIAdapter(BotAdapter):
    api_info: OpenAIAPIKey = None
    """API Key"""

    bot: OpenAIChatbot = None
    """实例"""

    hashed_user_id: str

    def __init__(self, session_id: str = "unknown",isSilly=False):
        self.__conversation_keep_from = 0
        self.session_id = session_id
        self.isSilly = isSilly
        self.hashed_user_id = "user-" + hashu("session_id").to_bytes(8, "big").hex()
        self.api_info = botManager.pick('openai-api')
        self.bot = OpenAIChatbot(
            api_key=self.api_info.api_key,
            proxy=self.api_info.proxy,
            presence_penalty=config.openai.gpt3_params.presence_penalty,
            frequency_penalty=config.openai.gpt3_params.frequency_penalty,
            top_p=config.openai.gpt3_params.top_p,
            temperature=config.openai.gpt3_params.temperature,
            max_tokens=config.openai.gpt3_params.max_tokens,
        )
        self.conversation_id = None
        self.parent_id = None
        super().__init__()
        self.bot.conversation[self.session_id] = []
        self.current_model = self.api_info.model or "gpt-3.5-turbo"
        self.supported_models = [
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-0301",
            "gpt-4",
            "gpt-4-0314",
            "gpt-4-32k",
            "gpt-4-32k-0314",
        ]
        self.sillyMessage = {}
        self.role_name: str = config.onebot.qq_nick_name
        self.groupMember = []
        self.isSilly = isSilly
        self.role_desc=''

    async def switch_model(self, model_name):
        self.current_model = model_name
        self.bot.engine = self.current_model

    async def rollback(self):
        if len(self.bot.conversation[self.session_id]) <= 0:
            return False
        self.bot.rollback(convo_id=self.session_id, n=2)
        return True

    async def on_reset(self):
        self.api_info = botManager.pick('openai-api')
        self.bot.api_key = self.api_info.api_key
        self.bot.proxy = self.api_info.proxy
        self.bot.conversation[self.session_id] = []
        self.__conversation_keep_from = 0
    async def ask(self, prompt,repeat:bool=False,count:int=1) -> Generator[str, None, None]:
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
        self.api_info = botManager.pick('openai-api')
        self.bot.api_key = self.api_info.api_key
        self.bot.proxy = self.api_info.proxy
        self.bot.session.proxies.update(
            {
                "http": self.bot.proxy,
                "https": self.bot.proxy,
            },
        )

        os.environ['API_URL'] = f'{openai.api_base}/chat/completions'
        try:
            line = ''
            async for resp in self.bot.ask_stream_async1(messages=sillyMessage["messages"]):
                line += resp
            logger.debug(line)
            message: str = line
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
        self.api_info = botManager.pick('openai-api')
        self.bot.api_key = self.api_info.api_key
        self.bot.proxy = self.api_info.proxy
        self.bot.session.proxies.update(
            {
                "http": self.bot.proxy,
                "https": self.bot.proxy,
            },
        )

        if self.session_id not in self.bot.conversation:
            self.bot.conversation[self.session_id] = [
                {"role": "system", "content": self.bot.system_prompt}
            ]
            self.__conversation_keep_from = 1

        while self.bot.max_tokens - self.bot.get_token_count(self.session_id) < config.openai.gpt3_params.min_tokens and \
                len(self.bot.conversation[self.session_id]) > self.__conversation_keep_from:
            self.bot.conversation[self.session_id].pop(self.__conversation_keep_from)
            logger.debug(
                f"清理 token，历史记录遗忘后使用 token 数：{str(self.bot.get_token_count(self.session_id))}"
            )

        os.environ['API_URL'] = f'{openai.api_base}/chat/completions'
        full_response = ''
        async for resp in self.bot.ask_stream_async(prompt=prompt, role=self.hashed_user_id, convo_id=self.session_id):
            full_response += resp
            yield full_response
        logger.debug(f"[ChatGPT-API:{self.bot.engine}] 响应：{full_response}")
        logger.debug(f"使用 token 数：{str(self.bot.get_token_count(self.session_id))}")

    async def preset_ask(self, role: str, text: str):
        if role.endswith('bot') or role in {'assistant', 'chatgpt'}:
            logger.debug(f"[预设] 响应：{text}")
            yield text
            role = 'assistant'

        if self.session_id not in self.bot.conversation:
            self.bot.conversation[self.session_id] = []
            self.__conversation_keep_from = 0
        self.bot.conversation[self.session_id].append({"role": role, "content": text})
        self.__conversation_keep_from = len(self.bot.conversation[self.session_id])
