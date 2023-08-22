from typing import Callable, Optional

from conversation import ConversationContext


class Middleware:
    async def handle_request(self, session_id: str, prompt: str, respond: Callable,
                             conversation_context: Optional[ConversationContext], action: Callable,queue_info):
        await action(session_id, prompt, conversation_context, respond,queue_info)

    async def handle_respond(self, session_id: str, prompt: str, rendered: str, respond: Callable, action: Callable):
        await action(session_id, prompt, rendered, respond)

    async def handle_respond_completed(self, session_id: str, prompt: str, respond: Callable): ...
    async def on_respond(self, session_id: str, prompt: str, rendered: str): ...
