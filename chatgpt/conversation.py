import asyncio
import contextlib
from datetime import datetime
from typing import List, Dict, Optional

import httpx
from EdgeGPT import ConversationStyle
from graia.amnesia.message import MessageChain
from graia.ariadne.message.element import Image as GraiaImage, Element
from loguru import logger

import constants
from adapter.baidu.yiyan import YiyanAdapter
from adapter.botservice import BotAdapter
from adapter.chatgpt.api import ChatGPTAPIAdapter
from adapter.chatgpt.web import ChatGPTWebAdapter
from adapter.claude.slack import ClaudeInSlackAdapter
from adapter.google.bard import BardAdapter
from adapter.ms.bing import BingAdapter
from drawing import DrawingAPI, SDWebUI as SDDrawing, OpenAI as OpenAIDrawing
from adapter.quora.poe import PoeBot, PoeAdapter
from adapter.thudm.chatglm_6b import ChatGLM6BAdapter
from constants import config
from exceptions import PresetNotFoundException, BotTypeNotFoundException, NoAvailableBotException, \
    CommandRefusedException, DrawingFailedException
from renderer import Renderer
from renderer.merger import BufferedContentMerger, LengthContentMerger
from renderer.renderer import MixedContentMessageChainRenderer, MarkdownImageRenderer, PlainTextRenderer
from renderer.splitter import MultipleSegmentSplitter
from middlewares.draw_ratelimit import MiddlewareRatelimit
from utils import retry
from constants import LlmName
from utils.text_to_speech import TtsVoice, TtsVoiceManager
import base64
from graia.ariadne.message.element import Image
from graia.ariadne.message.element import Image as GraiaImage, At, Plain, Voice
import requests
from aiocqhttp import CQHttp, Event, MessageSegment
import re
from drawing.my_map import add_to_map, get_from_map
from PIL import Image as ImagePIL
import io
import os

handlers = {}

middlewares = MiddlewareRatelimit()
bot = CQHttp()

class ConversationContext:
    type: str
    adapter: BotAdapter
    """聊天机器人适配器"""

    splitter: Renderer
    """消息分隔器"""
    merger: Renderer
    """消息合并器"""
    renderer: Renderer
    """消息渲染器"""

    drawing_adapter: DrawingAPI = None
    """绘图引擎"""

    preset: str = None

    preset_decoration_format: Optional[str] = "{prompt}"
    """预设装饰文本"""

    preset_role_desc: str = None

    init_scene: str = None

    role_name: str = None

    third_reply_mode: bool = False

    preset_role_neg_desc: str = None

    conversation_voice: TtsVoice = None
    """语音音色"""

    @property
    def current_model(self):
        return self.adapter.current_model

    @property
    def supported_models(self):
        return self.adapter.supported_models

    def __init__(self, _type: str, session_id: str):
        self.session_id = session_id

        self.last_resp = ''

        self.last_pic = ''

        self.last_pic_prompt = ''

        self.isSilly = False

        self.switch_renderer()

        if config.text_to_speech.always:
            tts_engine = config.text_to_speech.engine
            tts_voice = config.text_to_speech.default
            try:
                self.conversation_voice = TtsVoiceManager.parse_tts_voice(tts_engine, tts_voice)
            except KeyError as e:
                logger.error(f"Failed to load {tts_engine} tts voice setting -> {tts_voice}")
        if config.response.sillyClaudeIdList:
            self.isSilly = self.checkSilly()
        if _type == LlmName.ChatGPT_Web.value:
            self.adapter = ChatGPTWebAdapter(self.session_id)
        elif _type == LlmName.ChatGPT_Api.value:
            self.adapter = ChatGPTAPIAdapter(self.session_id,self.isSilly)
        elif PoeBot.parse(_type):
            self.adapter = PoeAdapter(self.session_id, PoeBot.parse(_type))
        elif _type == LlmName.Bing.value:
            self.adapter = BingAdapter(self.session_id,self.isSilly)
        elif _type == LlmName.BingC.value:
            logger.debug("bing-c")
            self.adapter = BingAdapter(self.session_id,self.isSilly, ConversationStyle.creative)
        elif _type == LlmName.BingB.value:
            self.adapter = BingAdapter(self.session_id,self.isSilly, ConversationStyle.balanced)
        elif _type == LlmName.BingP.value:
            self.adapter = BingAdapter(self.session_id,self.isSilly, ConversationStyle.precise)
        elif _type == LlmName.Bard.value:
            self.adapter = BardAdapter(self.session_id)
        elif _type == LlmName.YiYan.value:
            self.adapter = YiyanAdapter(self.session_id)
        elif _type == LlmName.ChatGLM.value:
            self.adapter = ChatGLM6BAdapter(self.session_id)
        elif _type == LlmName.SlackClaude.value:
            self.adapter = ClaudeInSlackAdapter(self.session_id,self.isSilly)
        else:
            raise BotTypeNotFoundException(_type)
        self.type = _type

        # 没有就算了
        if config.sdwebui:
            self.drawing_adapter = SDDrawing()
        elif config.bing.use_drawing:
            with contextlib.suppress(NoAvailableBotException):
                self.drawing_adapter = BingAdapter(self.session_id, ConversationStyle.creative)
        else:
            with contextlib.suppress(NoAvailableBotException):
                self.drawing_adapter = OpenAIDrawing(self.session_id)
    def checkSilly(self):
        for element in config.response.sillyClaudeIdList:
            if element in self.session_id:
                return True
        return False

    def switch_renderer(self, mode: Optional[str] = None):
        # 目前只有这一款
        self.splitter = MultipleSegmentSplitter()

        if config.response.buffer_delay > 0:
            self.merger = BufferedContentMerger(self.splitter)
        else:
            self.merger = LengthContentMerger(self.splitter)

        if not mode:
            mode = "image" if config.text_to_image.default or config.text_to_image.always else config.response.mode

        if mode == "image" or config.text_to_image.always:
            self.renderer = MarkdownImageRenderer(self.merger)
        elif mode == "mixed":
            self.renderer = MixedContentMessageChainRenderer(self.merger)
        elif mode == "text":
            self.renderer = PlainTextRenderer(self.merger)
        else:
            self.renderer = MixedContentMessageChainRenderer(self.merger)
        if mode != "image" and config.text_to_image.always:
            raise CommandRefusedException("不要！由于配置文件设置强制开了图片模式，我不会切换到其他任何模式。")

    async def reset(self):
        await self.adapter.on_reset()
        self.last_resp = ''
        yield config.response.reset

    @retry((httpx.ConnectError, httpx.ConnectTimeout, TimeoutError))
    async def ask1(self, prompt: str, chain: MessageChain = None, name: str = None,queue_info = None):

        reply = None
        image = None
        for elem in chain:
            if isinstance(elem, (Image, GraiaImage)):
                image = elem
            elif isinstance(elem, Plain) and str(elem).startswith('[CQ:reply,'):
                logger.debug(f'reply {str(elem)}')
                matchReply = re.search(r'\[CQ:reply,id=(-?\d+)\]', str(elem))
                reply = matchReply.group(1)
        cacheImageObj = get_from_map(f'pic-{reply}')
        cacheImage = None
        if cacheImageObj:
            matchReply = re.search(r'base64://([^]]+)', str(cacheImageObj))
            if matchReply:
                cacheImage = matchReply.group(1)
        prompt = re.sub(r"\[CQ:reply,id=\d+\]", "", prompt)
        prompt = re.sub(r"\[CQ:reply,id=(-?\d+)\]", "", prompt)
        async with queue_info:
            promptDesc=prompt
            controlnetV = ('-v' in prompt or '-V' in prompt)
            controlnetT = ('-t' in prompt or '-T' in prompt)
            if not controlnetV and not controlnetT and self.is_base64_image(cacheImage):
                controlnetT=True
            if controlnetV or controlnetT:
                prompt = re.sub(r"\[CQ:reply,id=\d+\]", "", prompt)
                prompt = re.sub(r"\[CQ:reply,id=-\d+\]", "", prompt)
                removeprefix = prompt.replace('-v','').replace('-V','').replace('-t','').replace('-T','').replace(f'{self.role_name}，','').replace(f'{self.role_name},','').replace(f'{self.role_name}','').replace(f'@{config.onebot.qq}','')
                promptDesc = f'{self.last_pic}' if not cacheImage else cacheImage
                prompt = f'{self.last_pic_prompt}' if not cacheImage else get_from_map(f'picPrompt-{reply}')
                if removeprefix:
                    prompt=f'{prompt},（{removeprefix}:1.5）,'

                if controlnetV:
                    prompt=f'{prompt}--controlnetV:{promptDesc},'
                if controlnetT:
                    prompt=f'{prompt}--controlnetT:{promptDesc},'
            if image and image.url:
                imageBase64 = requests.get(image.url).content
                prompt = prompt.replace('[图片]','')
                for prefix in config.trigger.prefix_image:
                    prompt=prompt.removeprefix(prefix)
                prompt = f'({prompt}:1.2)--controlnetT:{base64.b64encode(imageBase64).decode("utf-8")},'
                controlnetT = not controlnetV
            # 检查是否为 画图指令
            for prefix in config.trigger.prefix_image or controlnetV or controlnetT:
                if (prompt.startswith(prefix) and not isinstance(self.adapter, YiyanAdapter)) or controlnetV or controlnetT:
                    # TODO(lss233): 此部分可合并至 RateLimitMiddleware
                    respond_str = middlewares.handle_draw_request(self.session_id, prompt)
                    # TODO(lss233): 这什么玩意
                    if respond_str != "1":
                        yield respond_str
                        return
                    if not self.drawing_adapter:
                        yield "未配置画图引擎，无法使用画图功能！"
                        return
                    prompt = prompt.removeprefix(prefix)
                    try:
                        images = await self.drawing_adapter.text_to_img(prompt)
                        for i in images:
                            self.last_pic = i.base64
                            self.last_pic_prompt = promptDesc
                            add_to_map('this_pic_prompt',self.last_pic_prompt)
                            yield i
                    except Exception as e:
                        raise DrawingFailedException from e
                    respond_str = middlewares.handle_draw_respond_completed(self.session_id, prompt)
                    if respond_str != "1":
                        yield respond_str
                    return

            if self.preset_decoration_format:
                prompt = (
                    self.preset_decoration_format.replace("{prompt}", prompt).replace(f'@{config.onebot.qq}','')
                        .replace("{nickname}", name)
                        .replace("{last_resp}", self.last_resp)
                        .replace("{date}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )

            async with self.renderer:
                items =  ''
                async for item in self.adapter.ask1(prompt):
                    self.adapter.nickname = name
                    if isinstance(item, Element):
                        items = item
                        item = re.sub(r"$<desc>(.*?)</desc>", "", item)
                        yield item.replace("()","")
                    else:
                        items = item
                        logger.debug(f"item -> {item}")
                        item = re.sub(r"<desc>(.*?)</desc>", "", item)
                        item = re.sub(r"desc(.*?)/desc", "", item)
                    yield await self.renderer.render(item.replace("()",""))
                    self.last_resp = item or ''
                yield await self.renderer.result()
            if not self.preset_role_desc or self.preset_role_desc == '' or not config.response.generateCurrentImage:
                return
            async for item in self.adapter.ask1(f'本次回复暂停角色扮演，请重点根据最近2条对话，使用逗号分隔的关键词或短语生成当前场景位置和当前的人物表情、动作、状态和服饰的描述(不需要否定、近义、重复、过去和不可见事物的描述)，描述放在<desc></desc>标签内，仅人物服饰加1.5倍比重，且只能等于1.5倍比重，例如：<desc>大海，沙滩，微笑，游泳，(蓝色比基尼，蓝色泳衣:1.5)</desc>，其中大海、沙滩是背景，微笑是人物表情，游泳是人物动作，(蓝色比基尼，蓝色泳衣:1.5)是1.5倍比重的人物服饰'):
                items = item
        match = re.findall(r"<desc>(.*?)</desc>", items)
        desc=''
        if match:
            desc = "，".join(match)
        else:
            match = re.findall(r"desc(.*?)/desc", items)
            if match:
                desc="，".join(match)
            else:
                desc = items
        desc = self.preset_role_desc+""+desc.replace(': 1.5',':1.5')+""
        logger.debug(f"desc -> {desc}")
        images = await self.drawing_adapter.text_to_img(desc)
        for i in images:
            self.last_pic = i.base64
            self.last_pic_prompt = desc
            add_to_map('this_pic_prompt',self.last_pic_prompt)
            yield i
        return
    @retry((httpx.ConnectError, httpx.ConnectTimeout, TimeoutError))
    async def ask(self, prompt: str, chain: MessageChain = None, name: str = None,queue_info = None):

        reply = None
        image = None
        for elem in chain:
            if isinstance(elem, (Image, GraiaImage)):
                image = elem
            elif isinstance(elem, Plain) and str(elem).startswith('[CQ:reply,'):
                logger.debug(f'reply {str(elem)}')
                matchReply = re.search(r'\[CQ:reply,id=(-?\d+)\]', str(elem))
                reply = matchReply.group(1)
        cacheImageObj = get_from_map(f'pic-{reply}')
        cacheImage = None
        if cacheImageObj:
            matchReply = re.search(r'base64://([^]]+)', str(cacheImageObj))
            if matchReply:
                cacheImage = matchReply.group(1)
        if not self.isSilly:
            async for content1 in self.ask1(prompt,chain,name,queue_info):
                yield content1
            return
        prompt = re.sub(r"\[CQ:reply,id=\d+\]", "", prompt)
        prompt = re.sub(r"\[CQ:reply,id=(-?\d+)\]", "", prompt)
        async with queue_info:
            self.adapter.nickname = name
            logger.debug("[Concurrent] 排到了！")
            promptDesc=prompt
            controlnetV = ('-v' in prompt or '-V' in prompt)
            controlnetT = ('-t' in prompt or '-T' in prompt)
            if not controlnetV and not controlnetT and (self.is_base64_image(cacheImage) or (image and image.url)):
                controlnetT=True
            logger.debug(f"[Concurrent] controlnetT {controlnetT}")
            if controlnetV or controlnetT:
                prompt = re.sub(r"\[CQ:reply,id=\d+\]", "", prompt)
                prompt = re.sub(r"\[CQ:reply,id=-\d+\]", "", prompt)
                removeprefix = prompt.replace('-v','').replace('-V','').replace('-t','').replace('-T','').replace(f'{self.role_name}，','').replace(f'{self.role_name},','').replace(f'{self.role_name}','').replace(f'@{config.onebot.qq}','')
                promptDesc = cacheImage
                prompt =get_from_map(f'picPrompt-{reply}')  if get_from_map(f'picPrompt-{reply}') else ''

                if image and image.url:
                    imageBase64 = requests.get(image.url).content

                    for prefix in config.trigger.prefix_image:
                        prompt = prompt.removeprefix(prefix)
                    if controlnetV:
                        prompt = f'{prompt},（{removeprefix}:1.2）--controlnetV:{base64.b64encode(imageBase64).decode("utf-8")},'
                    else:
                        prompt = f'{prompt},（{removeprefix}:1.5）--controlnetT:{base64.b64encode(imageBase64).decode("utf-8")},'
                        controlnetT = True
                else:
                    if controlnetV:
                        prompt=f'{prompt},（{removeprefix}:1.2）--controlnetV:{promptDesc},'
                    if controlnetT:
                        prompt=f'{prompt},（{removeprefix}:1.5）--controlnetT:{promptDesc},'
            logger.debug(f"[OneBot] promptDesc：{promptDesc[:100] if len(str(promptDesc)) >= 100 else promptDesc}")
            prompt = prompt.replace('[图片]','')
            # 检查是否为 画图指令
            for prefix in config.trigger.prefix_image or controlnetV or controlnetT:
                if (prompt.startswith(prefix) and not isinstance(self.adapter, YiyanAdapter)) or controlnetV or controlnetT:
                    # TODO(lss233): 此部分可合并至 RateLimitMiddleware
                    respond_str = middlewares.handle_draw_request(self.session_id, prompt)
                    # TODO(lss233): 这什么玩意
                    if respond_str != "1":
                        yield respond_str
                        return
                    if not self.drawing_adapter:
                        yield "未配置画图引擎，无法使用画图功能！"
                        return
                    prompt = prompt.removeprefix(prefix)
                    try:
                        images = await self.drawing_adapter.text_to_img(prompt)
                        for i in images:
                            self.last_pic = i.base64
                            self.last_pic_prompt = prompt
                            add_to_map('this_pic_prompt',self.last_pic_prompt)
                            yield i
                    except Exception as e:
                        raise DrawingFailedException from e
                    respond_str = middlewares.handle_draw_respond_completed(self.session_id, prompt)
                    if respond_str != "1":
                        yield respond_str
                    return

            if self.preset_decoration_format:
                prompt = (
                    self.preset_decoration_format.replace("{prompt}", prompt).replace(f'@{config.onebot.qq}','')
                        .replace("{nickname}", name)
                        .replace("{last_resp}", self.last_resp)
                        .replace("{date}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )

            async with self.renderer:
                items =  ''
                async for item in self.adapter.ask(prompt):
                    logger.debug(f"item -> {item}")
                    if isinstance(item, Element):
                        items = item
                        item = re.sub(r"<desc>(.*?)</desc>", "", item, flags=re.DOTALL)
                        if not self.third_reply_mode:
                            match = re.search(r'["“](.*?)["”]', item)
                            # if match and len(match.group(1))>5:
                            #     item = match.group(1)
                        yield item.replace("()","").rstrip("\n")
                    else:
                        item = item.replace("&lt;",'').replace('&gt;','')
                        items = item
                        item = re.sub(r"<desc>(.*?)</desc>", "", item, flags=re.DOTALL)
                        item = re.sub(r"desc(.*?)/desc", "", item, flags=re.DOTALL)
                        if not self.third_reply_mode:
                            match = re.search(r'["“](.*?)["”]', item)
                            # if match:
                            #     item = match.group(1)
                        logger.debug(f'self.renderer.render->{item}')
                        yield await self.renderer.render(item.replace("()","").rstrip("\n").lstrip())
                    self.last_resp = item or ''
                yield await self.renderer.result()
            # queue_info.lock.release()
            match = re.match(r'^已删除上(\d+)条对话$', items.strip())
            if not self.preset_role_desc or self.preset_role_desc == '' or '网络故障，请重新回复' in items or match  or '当前对话记录长度' in items or '回复超时' in items or '总结内容如下' in items or '缓存会话成功' in items or '请先总结会话' in items or '回复失败' in items:
                return
        match = re.findall(r"<desc>(.*?)</desc>", items, flags=re.DOTALL)
        desc=''
        if match:
            desc = "，".join(match)
        else:
            match = re.findall(r"desc(.*?)/desc", items, flags=re.DOTALL)
            if match:
                desc="，".join(match)
            else:
                # match = re.findall(r"\[当前情景:(.*?)\]", items)
                # if match:
                #     desc="，".join(match)
                # else:
                #     match = re.findall(r"\[当前情景：(.*?)\]", items)
                #     if match:
                #         desc="，".join(match)
                #     else:
                desc = items
        desc = self.preset_role_desc+""+desc.replace(': 1.5',':1.5').replace('amp;','')+""
        logger.debug(f"desc -> {desc}")
        images = await self.drawing_adapter.text_to_img(desc)
        for i in images:
            self.last_pic = i.base64
            self.last_pic_prompt = desc
            add_to_map('this_pic_prompt',self.last_pic_prompt)
            yield i
        return
    async def rollback(self):
        resp = await self.adapter.rollback()
        if isinstance(resp, bool):
            yield config.response.rollback_success if resp else config.response.rollback_fail.format(
                reset=config.trigger.reset_command)
        else:
            yield resp
    def is_base64_image(self,string):
        try:
            # 尝试解码字符串
            decoded_data = base64.b64decode(string)
            # 将解码后的数据转换为 BytesIO 对象
            image_data = io.BytesIO(decoded_data)
            # 使用 Pillow 打开图片
            image = ImagePIL.open(image_data)
            # 检查图片是否加载成功
            image.verify()
            return True
        except Exception:
            return False
    async def switch_model(self, model_name):
        return await self.adapter.switch_model(model_name)

    async def load_preset(self, keyword: str):
        self.preset_decoration_format = None
        if keyword in config.presets.keywords:
            presets = config.load_preset(keyword)
            for text in presets:
                if not text.strip() or not text.startswith('#'):
                    # 判断格式是否为 role: 文本
                    if ':' in text:
                        role, text = text.split(':', 1)
                    else:
                        raise PresetNotFoundException(text)
                    if role == 'user_send':
                        self.preset_decoration_format = text
                        continue
                    if role == 'role_desc':
                        self.preset_role_desc = text
                        continue
                    if role == 'init_scene':
                        self.adapter.init_scene = text
                        continue
                    if role == 'third_reply_mode':
                        self.third_reply_mode = text.lower().strip() == "true"
                        self.adapter.third_reply_mode = text.lower().strip() == "true"
                        continue
                    if role == 'role_name':
                        self.role_name = text.lower().strip()
                        self.adapter.role_name = text.lower().strip()
                        self.adapter.groupMember = [text.lower().strip()]
                        continue
                    if role == 'role_neg_desc':
                        self.preset_role_neg_desc = text
                        continue
                    if role == 'system':
                        self.adapter.role_desc = text
                    if role == 'assistant':
                        self.adapter.role_first = text


                    if role == 'voice':
                        self.conversation_voice = TtsVoiceManager.parse_tts_voice(config.text_to_speech.engine,
                                                                                  text.strip())
                        logger.debug(f"Set conversation voice to {self.conversation_voice.full_name}")
                        continue
                    logger.debug("预设--------------"+role)
                    if not os.path.exists(f'normal-{self.session_id}.pickle'):
                        async for item in self.adapter.preset_ask(role=role.lower().strip(), text=text.strip()):
                            yield item
        elif keyword != 'default':
            raise PresetNotFoundException(keyword)
        self.preset = keyword

    def delete_message(self, respond_msg):
        # TODO: adapt to all platforms
        pass


class ConversationHandler:
    """
    每个聊天窗口拥有一个 ConversationHandler，
    负责管理多个不同的 ConversationContext
    """
    conversations: Dict[str, ConversationContext]
    """当前聊天窗口下所有的会话"""

    current_conversation: ConversationContext = None

    session_id: str = 'unknown'

    queue_info = None

    def __init__(self, session_id: str):
        self.conversations = {}
        self.session_id = session_id

    def list(self) -> List[ConversationContext]:
        ...

    """
    获取或创建新的上下文
    这里的代码和 create 是一样的
    因为 create 之后会加入多会话功能
    """

    async def first_or_create(self, _type: str):
        if _type in self.conversations:
            return self.conversations[_type]
        conversation = ConversationContext(_type, self.session_id)
        self.conversations[_type] = conversation
        return conversation

    """创建新的上下文"""

    async def create(self, _type: str):
        if _type in self.conversations:
            return self.conversations[_type]
        conversation = ConversationContext(_type, self.session_id)
        self.conversations[_type] = conversation
        return conversation

    """切换对话上下文"""

    def switch(self, index: int) -> bool:
        if len(self.conversations) > index:
            self.current_conversation = self.conversations[index]
            return True
        return False

    @classmethod
    async def get_handler(cls, session_id: str):
        if session_id not in handlers:
            handlers[session_id] = ConversationHandler(session_id)
        return handlers[session_id]
