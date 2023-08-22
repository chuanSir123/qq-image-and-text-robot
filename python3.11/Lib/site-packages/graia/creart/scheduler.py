from __future__ import annotations

from typing import TYPE_CHECKING

from creart import AbstractCreator, CreateTargetInfo, exists_module, it, mixin

from .broadcast import BroadcastCreator

if TYPE_CHECKING:
    from graia.scheduler import GraiaScheduler
    from graia.scheduler.saya.behaviour import GraiaSchedulerBehaviour


class SchedulerCreator(AbstractCreator):
    targets = (
        CreateTargetInfo(
            module="graia.scheduler",
            identify="GraiaScheduler",
            humanized_name="Graia Scheduler",
            description="<common,graia,scheduler> a simple but powerful scheduler based on asyncio & broadcast control",
            author=["GraiaProject@github"],
        ),
    )

    @staticmethod
    @mixin(BroadcastCreator)
    def available() -> bool:
        return exists_module("graia.scheduler")

    @staticmethod
    def create(create_type: type[GraiaScheduler]) -> GraiaScheduler:
        from graia.broadcast import Broadcast

        broadcast = it(Broadcast)
        return create_type(loop=broadcast.loop, broadcast=broadcast)


class SchedulerBehaviourCreator(AbstractCreator):
    targets = (
        CreateTargetInfo(
            module="graia.scheduler.saya.behaviour",
            identify="GraiaSchedulerBehaviour",
            humanized_name="Saya for Graia Scheduler",
            description="<common,graia,scheduler,saya,behaviour> saya support for Graia Scheduler",
            author=["GraiaProject@github"],
        ),
    )

    @staticmethod
    @mixin(SchedulerCreator)
    def available() -> bool:
        return exists_module("graia.saya")

    @staticmethod
    def create(create_type: type[GraiaSchedulerBehaviour]) -> GraiaSchedulerBehaviour:
        from graia.scheduler import GraiaScheduler

        scheduler = it(GraiaScheduler)
        return create_type(scheduler)
