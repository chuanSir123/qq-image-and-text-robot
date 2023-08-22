from typing import List
import base64
import httpx
from graia.ariadne.message.element import Image
import json
from constants import config
from .base import DrawingAPI
import translators as ts
from loguru import logger
import re
import random
import io
import requests
import http.client
from PIL import Image as ImagePIL
from io import BytesIO
import tomlkit
import time

def basic_auth_encode(authorization: str) -> str:
    authorization_bytes = authorization.encode('utf-8')
    encoded_authorization = base64.b64encode(authorization_bytes).decode('utf-8')
    return f"Basic {encoded_authorization}"


def init_authorization():
    if config.sdwebui.authorization != '':
        return basic_auth_encode(config.sdwebui.authorization)
    else:
        return ''


class SDWebUI(DrawingAPI):

    def __init__(self):
        self.headers = {
            "Authorization": f"{init_authorization()}"
        }

    async def text_to_img(self, prompt):
        width = 512
        height = 512
        width1 = 512
        height1 = 512
        controlnet = {}

        if '--controlnet' in prompt:

            controlnet = {
                "args": [
                ]
            }
            matchV = re.search(r'(?<=--controlnetV:).*?(?=,)', prompt)
            if matchV:
                logger.debug(f"[OneBot] 尝试发送消息：{matchV.group(0)[:100] if len(str(matchV.group(0))) >= 100 else matchV.group(0)}")
                controlnet['args'].append({
                    "input_image": matchV.group(0),
                    "module": "reference_only",
                })
                prompt = prompt.replace(f'--controlnetV:{matchV.group(0)}','')
                prompt = re.sub(r'--controlnetV:[^,]+','',prompt)
                image = ImagePIL.open(BytesIO(base64.b64decode(matchV.group(0))))
                width1, height1 = image.size
                height=width * height1/width1

            matchT = re.search(r'(?<=--controlnetT:).*?(?=,)', prompt)
            if matchT:
                logger.debug(f"[OneBot] 尝试发送消息：{matchT.group(0)[:100] if len(str(matchT.group(0))) >= 100 else matchT.group(0)}")
                controlnet['args'].append({
                    "input_image": matchT.group(0),
                    # "module": "tile_resample",
                    "model": "control_v11f1e_sd15_tile_fp16 [3b860298]",
                })
                prompt = prompt.replace(f'--controlnetT:{matchT.group(0)}','')
                prompt = re.sub(r'--controlnetT:[^,]+','',prompt)
                image = ImagePIL.open(BytesIO(base64.b64decode(matchT.group(0))))
                width1, height1 = image.size
                height=width * height1/width1
        pattern = r"--(\d+)\*(\d+)"
        match = re.search(pattern, prompt)
        if match:
            width = match.group(1)
            height = match.group(2)
        prompt = prompt.replace('--'+str(width)+"*"+str(height),'').replace('-'+str(width)+"*"+str(height),'')
        prompt = re.sub(',+',',',prompt)
        prompt = re.sub('，+','，',prompt)
        logger.debug(f"before trans -> {prompt}")
        try:
            if 'cum' in prompt:
                text=ts.translate_text(prompt,'alibaba','cn').replace('&lt;','<').replace('&gt;','>').replace('<lora: ','<lora:').replace(': ',':').replace('< ','<').replace(' >','>')
            else:
                text=ts.translate_text(prompt,config.sdwebui.default_trans).replace('&lt;','<').replace('&gt;','>').replace('<lora: ','<lora:').replace(': ',':').replace('< ','<').replace(' >','>')
        except Exception as e:
            try:
                text=ts.translate_text(prompt,'alibaba','cn').replace('&lt;','<').replace('&gt;','>').replace('<lora: ','<lora:').replace(': ',':').replace('< ','<').replace(' >','>')
            except Exception as e:
                text=prompt.replace('&lt;','<').replace('&gt;','>').replace('<lora: ','<lora:').replace(': ',':').replace('< ','<').replace(' >','>')
                logger.exception(e)
        logger.debug(f"trans -> {text}")
        # model = 'Anything-v5.safetensors'
        model = config.sdwebui.default_sd_model
        vae=config.sdwebui.default_sd_vae
        if vae=="" and config.sdwebui.default_sd_model in ['fiamixHNSFW_v3.safetensors']:
            vae='kl-f8-anime2.vae.pt'
        num1 = 0
        num2 = 0
        num3 = 0
        num4 = 0
        restore_faces = 'false'

        if '机甲' in prompt or 'mecha' in prompt or 'mecha' in text:
            text=f'{text},<lora:aki:0.8>,'
        if '脱光' in prompt or '不着一物' in prompt or '一丝不挂' in prompt:
            text=f'{text},(nude:1.2),pov,'
        if '(nude' in text or '(naked' in text or ', nude' in text or ', nude' in text or ', naked' in text or ', nudity' in text or 'semi-nude' in text or 'semi-naked' in text or '全裸' in prompt:
            text =f'{text},nipples,pov,'
        if 'doggy-style' in text or 'doggy style' in text or 'doggystyle' in text or '后入' in prompt or 'penetration from behind' in text:
            text =f'{text},(sex from behind:1.4),pov,'
        if 'blowjob' in text or 'fellatio' in text or '口交' in prompt or '口活' in prompt or 'oral sex' in text:
            text =f'{text},(fellatio:1.4),pov,'
        if '精液' in prompt or 'semen,' in prompt or 'orgasm' in text:
            text =f'{text},(cum:1.4),pov,'
        if '插入' in prompt or '交欢' in prompt or '抽插' in prompt or '交媾' in prompt or '交配' in prompt or 'lovemaking' in text or 'love making' in text:
            text =f'{text},(sex:1.4),pov,'
        if '手交' in prompt or 'handjob' in text:
            text =f'{text},(handjob:1.4),pov,'
        if "女上位" in prompt or "骑乘" in prompt or 'female on top' in text or 'woman on top' in text or 'girl on top' in text or 'female upper' in text or 'rear entry' in text or 'ride on male' in text:
            text=f"{text},(cowgirl_position,sex:1.4),pov,"
        if "男上位" in prompt or "传教士" in prompt  or 'missionary' in text or ('male on top' in text and not 'female on top' in text) or 'female lying on back' in text:
            text=f"{text}, <lora:POVMissionary:1>,(missionary,sex:1.4),pov,"
        if '--real' in prompt:
            text = text.replace('--real','').replace('-real','')
            num1 = random.uniform(0, 0.6)
            # num2 = random.uniform(0, 0.6 - num1)
            # num3 = random.uniform(0, 0.6 - num1 - num2)
            num4 = 0.6 - num1
            model = config.sdwebui.default_real_sd_model
            restore_faces = 'true'
            text = text+f',realistic,<lora:JapaneseDollLikeness_v15:{num1}>, <lora:koreanDollLikeness_v20:{num4}>,bright light,VSCO,16K,HDR, highres,(grainy textures),IS0 200,'
        enable_hr = config.sdwebui.enable_hr
        if '-hr' in prompt:
            enable_hr = True
        payload = {
            "enable_hr": enable_hr,
            "denoising_strength": 0.45,
            "hr_scale": 1.5,
            # "hr_resize_x": 1024,
            # "hr_resize_y": 1536,
            "hr_upscaler": "R-ESRGAN 4x+ Anime6B",
            "hr_second_pass_steps": 0,
            "prompt": f"{config.sdwebui.prompt_prefix}, {text}",
            "steps": 20,
            "seed": -1,
            "batch_size": 1,
            "width": width,
            "height": height,
            "n_iter": 1,
            "cfg_scale": 7,
            "filter_nsfw": False,
            "restore_faces": False,
            "override_settings": {
                "sd_model_checkpoint" :model,
                "sd_vae":vae
            },
            "tiling": "false",
            "negative_prompt": config.sdwebui.negative_prompt,
            "eta": 0,
            "sampler_index": config.sdwebui.sampler_index
        }
        if controlnet:
            payload["alwayson_scripts"] = {
                "controlnet": controlnet
            }
        # for key, value in config.sdwebui.dict(exclude_none=True).items():
        #     if isinstance(value, bool):
        #         payload[key] = 'true' if value else 'false'
        #     else:
        #         payload[key] = value
        logger.debug("prompt-"+text)
        try:
            return await self.textToImage(payload)
        except Exception as e:
            logger.debug(f'画图失败{e}')
            return []
    async def textToImage(self,payload):
        try:
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).post(f"{config.sdwebui.api_url}sdapi/v1/txt2img",data=json.dumps(payload), headers=self.headers)
            resp.raise_for_status()
            r = resp.json()
            return [Image(base64=i) for i in r.get('images', [])];
        except Exception as e:
            logger.debug(f"直连接口失败{e}")
            # async for result in self.textToImageFree(payload):
            resp = await self.textToImageFree(payload)
            return [Image(base64=resp)]
    async def textToImageFree(self,payload):
        try:
            with open('config/newConfig.cfg', 'r', encoding='utf-8-sig') as file:
                toml_data = file.read()
                # 解析Toml数据并保留注释
            configDict = tomlkit.parse(toml_data)
            if "haiyi_quick" in configDict:
                speed_type = configDict["haiyi_quick"]
            else:
                speed_type = 1
            if "haiyi_all_model" in configDict:
                haiyi_all_model = configDict["haiyi_all_model"]
            else:
                haiyi_all_model = {"GhostMix2":"05b3523ba5cb7175db74a031cf964e2c|867bf63b9ee7c3c44acda975b4cabca3","ChilloutMix":"81c9105d394d27d8731d3375b8618fa6","Counter3":"038254337d59ef522fdb64268bc28e47|2e40f949adc219bfc0c76cf6868a5001"}
            if "haiyi_current_model" in configDict:
                currentModel = configDict["haiyi_current_model"]
            else:
                currentModel = "GhostMix2"
            modelAndVer = haiyi_all_model[currentModel]
            width = int(int(payload["width"])*1.5)
            height = int(int(payload["height"])*1.5)
            if width>height and width>1024:
                height = int(1024*height/width)
                width = 1024
            elif height>width and height>1024:
                width = int(1024*width/height)
                height = 1024
            newJson={
                "action":1,
                "art_work_no":"3e44f9e472974115dc38ea3596246e52",
                "art_model_no": modelAndVer.split("|")[0],
                "category":1,
                "speed_type":speed_type,
                "meta":{
                    "prompt":payload["prompt"],
                    "negative_prompt":payload["negative_prompt"],
                    "restore_faces":False,
                    "seed":-1,
                    "sampler_name":"DPM++ 2M Karras",
                    "width":width,
                    "height":height,
                    "steps":20,
                    "cfg_scale":7,
                    "vae":"automatic",
                    "clip_skip":2,
                    "n_iter":1
                }
            }
            if len(modelAndVer.split("|"))>1:
                ver = modelAndVer.split("|")[1]
                newJson["art_model_ver_no"] = ver
            # 现在你可以访问解析后的Toml数据，比如：
            haiyiHeader = {"token":configDict['haiyi_token']}
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).post(f"https://www.haiyiai.com/api/v1/task/create",json=newJson, headers=haiyiHeader)
            logger.debug(resp.text)
            r = resp.json()
            task_ids= [r["data"]["id"]]
            time.sleep(10)
            count =1
            while count<60:
                count+=1
                getImage = await httpx.AsyncClient(timeout=config.sdwebui.timeout).post(f"https://www.haiyiai.com/api/v1/task/batch-progress",json={"task_ids":task_ids}, headers=haiyiHeader)
                imageJson = getImage.json()
                if imageJson["data"]["items"][0]["status_desc"] == "finish":
                    url = imageJson["data"]["items"][0]["img_uris"][0]["url"]
                    response = await httpx.AsyncClient(timeout=config.sdwebui.timeout).get(url)
                    imageBase64 = response.content
                    return base64.b64encode(imageBase64).decode("utf-8")
                time.sleep(5)
        except Exception as e:
            logger.debug(f"海艺接口失败{e}")
            resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).post(f"{config.sdwebui.api_url_free}sdapi/v1/txt2img",data=json.dumps(payload), headers=self.headers)
            resp.raise_for_status()
            r = resp.json()
            return r.get('images', [])[0];


    async def img_to_img(self, init_images: List[Image], prompt=''):
        payload = {
            'init_images': [x.base64 for x in init_images],
            'enable_hr': 'false',
            'denoising_strength': 0.45,
            'prompt': f'{config.sdwebui.prompt_prefix}, {prompt}',
            'steps': 15,
            'seed': -1,
            'batch_size': 1,
            'n_iter': 1,
            'cfg_scale': 7.5,
            'restore_faces': 'false',
            'tiling': 'false',
            'negative_prompt': config.sdwebui.negative_prompt,
            'eta': 0,
            'sampler_index': config.sdwebui.sampler_index,
            "filter_nsfw": 'true' if config.sdwebui.filter_nsfw else 'false',
        }

        for key, value in config.sdwebui.dict(exclude_none=True).items():
            if isinstance(value, bool):
                payload[key] = 'true' if value else 'false'
            else:
                payload[key] = value

        resp = await httpx.AsyncClient(timeout=config.sdwebui.timeout).post(f"{config.sdwebui.api_url}sdapi/v1/img2img",
                                                                            json=payload, headers=self.headers)
        resp.raise_for_status()
        r = resp.json()
        return [Image(base64=i) for i in r.get('images', [])]
