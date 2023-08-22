import requests
import websocket
import json
import importlib.util
import time
import re
import threading
import websockets
from loguru import logger
import ssl
import asyncio


rename_roles = {
    'user': 'Human',
    'assistant': 'Assistant',
    'example_user': 'H',
    'example_assistant': 'A'
}

typingString = "\n\n_Typing…_"

maxMessageLength = 6000

lastMessage = ''

streamQueue = None

config = {}
cfg = {}

async def chat_completions(req, res, next):
    global cfg
    global config
    cfg = req["pingConfig"]
    cfg["MAINPROMPT_AS_PING"] = False;
    cfg["USE_BLOCKS"] = True;
    cfg["STREAMING_TIMEOUT"] = 240000;
    config = req["config"]
    if 'messages' not in req:
        raise Exception('Completion request not in expected format, make sure SillyTavern is set to use OpenAI.')

    try:
        stream = req['stream']
        promptMessages = buildSlackPromptMessages(req['messages'])

        tsThread = await createSlackThread(promptMessages[0])

        if tsThread is None or tsThread is None:
            raise Exception("First message did not return a thread timestamp. Make sure that CHANNEL is set to a channel ID that both your Slack user and Claude have access to.")

        print(f"Created thread with ts {tsThread}")

        pingMessage = cfg['PING_MESSAGE']
        if cfg['MAINPROMPT_AS_PING']:
            pingMessage = promptMessages.pop()

        if len(promptMessages) > 1:
            for i in range(1, len(promptMessages)):
                await createSlackReply(promptMessages[i], tsThread)
                print(f"Created {i}. reply on thread {tsThread}")
        await createClaudePing(pingMessage, tsThread)
        print(f"Created Claude ping on thread {tsThread}")
        ws = await openWebSocketConnection()
        if stream:
            print("Opened stream for Claude's response.")
            await listen_websocket(ws, res, tsThread)
        else:
            print("Awaiting Claude's response.")
            await listen_websocket(ws, res, tsThread)

        ws.close()
        print(f"Created Claude ping on thread {tsThread}")
    except Exception as error:
        print(error)
        next(error)

async def listen_websocket(ws, res, tsThread):
    ready=False
    t1=time.time()
    try:
        while True:
            # 设置超时时间，单位为秒（例如，10秒）
            message = await asyncio.wait_for(ws.recv(), timeout=15)
            data = json.loads(message)
            if 'subtype' in data and data['subtype'] == 'message_changed':
                ready=True
            if t1-time.time()>30 and not ready:
                res['choices'] = [{
                    'message': {
                        'content': "slack回复超时，请重试"
                    }
                }]
                break
            getClaudeResponse(tsThread, message, res)

            if res:
                break
    except asyncio.TimeoutError:
        res['choices'] = [{
            'message': {
                'content': "slack回复超时，请重试"
            }
        }]

def assign_stream_queue(message, res, tsThread):
    global streamQueue
    streamQueue = streamQueue.then(lambda: streamNextClaudeResponseChunk(message, res, tsThread))

def finishStream(res):
    global lastMessage
    lastMessage = ''
    res.write('\ndata: [DONE]')
    res.end()

async def openWebSocketConnection():
    ssl_context = ssl.SSLContext()
    ssl_context.verify_mode = ssl.CERT_NONE
    ws = await websockets.connect(f"wss://wss-primary.slack.com/?token={config['TOKEN']}",ssl=ssl_context,
                                  extra_headers={
                                      'Cookie': f"d={config['COOKIE']};",
                                      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0'
                                  })
    return ws


def streamNextClaudeResponseChunk(message, res, tsThread):
    try:
        data = json.loads(message)
        if data['subtype'] == 'message_changed':
            if tsThread == data['message']['thread_ts'] and config['CLAUDE_USER'] == data['message']['user']:
                text = data['message']['text']
                stillTyping = text.endswith(typingString)
                text = stripTyping(text) if stillTyping else text
                chunk = getNextChunk(text)
                if len(chunk) == 0:
                    return
                streamData = {
                    'choices': [{
                        'delta': {
                            'content': chunk
                        }
                    }]
                }
                res.write(f'data: {json.dumps(streamData)}\n\n')
                if not stillTyping:
                    finishStream(res)
    except Exception as error:
        logger.debug(error)
        print('Error parsing Slack WebSocket message')
        print(error)

def getNextChunk(text):
    global lastMessage
    if text == lastMessage:
        return ''
    if not text.includes(lastMessage):
        print('text check error,restore history')
    chunk = text[len(lastMessage):]
    lastMessage = text
    return chunk

def stripTyping(text):
    return text[:-len(typingString)]

def getClaudeResponse(tsThread, message, res):
    try:
        data = json.loads(message)
        if 'subtype' in data and data['subtype'] == 'message_changed':
            if tsThread == data['message']['thread_ts'] and config['CLAUDE_USER'] == data['message']['user']:
                content = data['message']['text'].replace("&lt;","<").replace("&gt;",">").lstrip()

                if '</desc>' in content and not content.startswith("<desc>"):
                    res['choices'] = [{
                        'message': {
                            'content': content.split("</desc>")[0]+"</desc>"
                        }
                    }]
                elif not content.endswith(typingString):
                    res['choices'] = [{
                        'message': {
                            'content': content
                        }
                    }]
                else:
                    print(f"received {len(data['message']['text'])} characters...")
    except Exception as error:
        logger.debug(error)
        print('Error parsing Slack WebSocket message:')
        print(error)

def buildSlackPromptMessages(messages):
    prompts = []
    currentPrompt = ''
    mainPrompt = ''

    if cfg['MAINPROMPT_LAST'] or cfg['MAINPROMPT_AS_PING']:
        firstMessage = convertToPrompt(messages[0])
        index = firstMessage.find('\n\n')
        if index > 0:
            mainPrompt = firstMessage[:index]
            currentPrompt = firstMessage[index:]
            if len(currentPrompt) > maxMessageLength:
                currentPrompt = splitPrompt(currentPrompt, prompts)
            messages.pop(0)
        else:
            print("Unable to determine cutoff point for main prompt, reverting to default behavior.")
            cfg['MAINPROMPT_LAST'] = False
            cfg['MAINPROMPT_AS_PING'] = False

    for msg in messages:
        promptPart = convertToPrompt(msg)
        if len(currentPrompt) + len(promptPart) < maxMessageLength:
            currentPrompt += promptPart
        else:
            prompts.append(currentPrompt)
            currentPrompt = promptPart
            if len(currentPrompt) > maxMessageLength:
                currentPrompt = splitPrompt(currentPrompt, prompts)
    prompts.append(currentPrompt)

    if cfg['MAINPROMPT_LAST'] or cfg['MAINPROMPT_AS_PING']:
        prompts.append(mainPrompt)

    return prompts

def splitPrompt(text, prompts):
    whiteSpaceMatch = re.search(r'\s(?=[^\s]*$)', text[:maxMessageLength])
    splitIndex = whiteSpaceMatch.start() + 1 if whiteSpaceMatch else maxMessageLength
    prompts.append(text[:splitIndex])
    secondHalf = text[splitIndex:]
    if len(secondHalf) > maxMessageLength:
        return splitPrompt(secondHalf, prompts)
    return secondHalf

def convertToPrompt(msg):
    if msg['role'] == 'system':
        if 'name' in msg:
            return f"{rename_roles[msg['name']]}: {msg['content']}\n\n"
        else:
            return f"{msg['content']}\n\n"
    else:
        return f"{msg['content']}\n\n"

def preparePingMessage(msg):
    claudePing = f"<@{config['CLAUDE_USER']}>"
    claudePingMatch = re.search(r'@Claude', msg, re.IGNORECASE)
    if claudePingMatch:
        return msg.replace(claudePingMatch.group(), claudePing)
    return f"{claudePing} {msg}"

async def postSlackMessage(msg, thread_ts, pingClaude):
    url = f"https://{config['TEAM_ID']}.slack.com/api/chat.postMessage"
    headers = {
        'Cookie': f"d={config['COOKIE']};",
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0',
    }
    data = {
        'token': config['TOKEN'],
        'channel': config['CHANNEL'],
        '_x_mode': 'online',
        '_x_sonic': 'true',
        'type': 'message',
        'xArgs': '{}',
        'unfurl': '[]',
        'include_channel_perm_error': 'true',
        '_x_reason': 'webapp_message_send',
    }

    if thread_ts is not None:
        data['thread_ts'] = thread_ts

    if pingClaude:
        msg = preparePingMessage(msg)

    if cfg['USE_BLOCKS']:
        blocks = [{
            'type': 'rich_text',
            'elements': [{
                'type': 'rich_text_section',
                'elements': [{
                    'type': 'text',
                    'text': msg
                }]
            }]
        }]
        data['blocks'] = json.dumps(blocks)
    else:
        data['text'] = msg

    response = requests.post(url, data=data, headers=headers)

    if 'ok' in response.json() and not response.json()['ok']:
        if 'error' in response.json():
            if response.json()['error'] == 'invalid_auth' or response.json()['error'] == 'not_authed':
                raise Exception("Failed posting message to Slack. Your TOKEN and/or COOKIE might be incorrect or expired.")
            else:
                raise Exception(response.json()['error'])
        else:
            raise Exception(response.json())

    return response.json()['ts']


async def createSlackThread(promptMsg):
    return await postSlackMessage(promptMsg, None, False)

async def createSlackReply(promptMsg, ts):
    return await postSlackMessage(promptMsg, ts, False)

async def createClaudePing(promptMsg, ts):
    return await postSlackMessage(promptMsg, ts, True)
