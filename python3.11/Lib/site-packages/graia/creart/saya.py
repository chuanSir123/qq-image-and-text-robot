from __future__ import annotations

from typing import TYPE_CHECKING

from creart import AbstractCreator, CreateTargetInfo, exists_module, it

from .broadcast import BroadcastCreator
from .scheduler import SchedulerCreator

if TYPE_CHECKING:
    from graia.saya import Saya


class SayaCreator(AbstractCreator):
    targets = (
        CreateTargetInfo(
            module="graia.saya",
            identify="Saya",
            humanized_name="Saya",
            description="<common,graia,saya> a modular implementation with modern design and injection",
            author=["GraiaProject@github"],
        ),
    )

    @staticmethod
    def available() -> bool:
        return exists_module("graia.saya")

    @staticmethod
    def create(create_type: type[Saya]) -> Saya:
        if BroadcastCreator.available():
            from graia.broadcast import Broadcast
            from graia.saya.builtins.broadcast.behaviour import BroadcastBehaviour

            broadcast = it(Broadcast)
            saya = create_type(broadcast)
            saya.install_behaviours(it(BroadcastBehaviour))
        else:
            saya = create_type()
        if SchedulerCreator.available():
            from graia.scheduler.saya.behaviour import GraiaSchedulerBehaviour

            saya.install_behaviours(it(GraiaSchedulerBehaviour))
        return saya
