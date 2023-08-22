from __future__ import annotations

import asyncio
from asyncio import AbstractEventLoop
from typing import TYPE_CHECKING

from creart import AbstractCreator, CreateTargetInfo, exists_module, it, mixin

if TYPE_CHECKING:
    from graia.broadcast import Broadcast
    from graia.broadcast.interrupt import InterruptControl
    from graia.saya.builtins.broadcast.behaviour import BroadcastBehaviour


class EventLoopCreator(AbstractCreator):
    targets = (CreateTargetInfo("asyncio.events", "AbstractEventLoop"),)

    @staticmethod
    def create(_: type[AbstractEventLoop]) -> AbstractEventLoop:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


class BroadcastCreator(AbstractCreator):
    targets = (
        CreateTargetInfo(
            module="graia.broadcast",
            identify="Broadcast",
            humanized_name="Broadcast Control",
            description="<common,graia,broadcast> a high performance, highly customizable, elegantly designed event system based on asyncio",
            author=["GraiaProject@github"],
        ),
        CreateTargetInfo(
            module="graia.broadcast.interrupt",
            identify="InterruptControl",
            humanized_name="Interrupt",
            description="<common,graia,broadcast,interrupt> Interrupt feature for broadcast control.",
            author=["GraiaProject@github"],
        ),
    )

    @staticmethod
    def available() -> bool:
        return exists_module("graia.broadcast")

    @staticmethod
    def create(
        create_type: type[Broadcast | InterruptControl],
    ) -> Broadcast | InterruptControl:
        from graia.broadcast import Broadcast
        from graia.broadcast.interrupt import InterruptControl

        if issubclass(create_type, Broadcast):
            return create_type(loop=it(AbstractEventLoop))
        elif issubclass(create_type, InterruptControl):
            return create_type(it(Broadcast))


class BroadcastBehaviourCreator(AbstractCreator):
    targets = (
        CreateTargetInfo(
            "graia.saya.builtins.broadcast.behaviour", "BroadcastBehaviour"
        ),
    )

    @staticmethod
    @mixin(BroadcastCreator)
    def available() -> bool:
        return exists_module("graia.saya")

    @staticmethod
    def create(create_type: type[BroadcastBehaviour]) -> BroadcastBehaviour:
        from graia.broadcast import Broadcast

        broadcast = it(Broadcast)
        return create_type(broadcast)
