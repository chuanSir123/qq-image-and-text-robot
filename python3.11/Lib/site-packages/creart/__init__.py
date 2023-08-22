from __future__ import annotations

import functools
import importlib.util
import os
import sys
import types
from typing import Any, TypeVar

from importlib_metadata import entry_points

from creart.creator import AbstractCreator as AbstractCreator
from creart.creator import CreateTargetInfo as CreateTargetInfo

_created: dict[str, Any] = {}
_creators: list[type[AbstractCreator]] = []

_mapping: dict[str, type[AbstractCreator]] = {}

T = TypeVar("T")


def _env_scan():
    for entry in entry_points().select(group="creart.creators"):
        creator = entry.load()
        if creator.available():
            add_creator(creator)


def add_creator(creator: type[AbstractCreator]):
    intersection = {f"{i.module}:{i.identify}" for i in creator.targets}.intersection(_mapping.keys())
    if intersection:
        raise ValueError(f"conflict target for {', '.join(intersection)}")
    _creators.append(creator)
    _mapping.update({f"{i.module}:{i.identify}": creator for i in creator.targets})


def _signature(target: type) -> str:
    return f"{target.__module__}:{target.__name__}"


def supported(target: type):
    return _signature(target) in _mapping


def _assert_supported(target: type):
    if not supported(target):
        raise TypeError(f"current environment does not contain support for {_signature(target)}")


def _get_creator(target: type) -> type[AbstractCreator]:
    _assert_supported(target)
    return _mapping[_signature(target)]


def create(target_type: type[T], *, cache: bool = True) -> T:
    sig = _signature(target_type)
    if cache and sig in _created:
        return _created[sig]
    _assert_supported(target_type)
    creator = _get_creator(target_type)
    result = creator.create(target_type)
    if cache:
        _created[sig] = result
    return result


def exists_module(package: str) -> bool:
    return package in sys.modules or importlib.util.find_spec(package) is not None


def mixin(*creators: type[AbstractCreator]):
    def wrapper(target: Any):
        if isinstance(target, staticmethod):
            target = target.__func__
        if isinstance(target, types.FunctionType):
            if target.__name__ == "available":

                @functools.wraps(target)
                def inner():
                    return all([target(), *[i.available() for i in creators]])

                return inner
            else:
                raise ValueError(f"no supported mixin for {target.__name__}")
        elif isinstance(target, type) and issubclass(target, AbstractCreator):
            origin = target.available

            @functools.wraps(origin)
            def inner():
                return all([origin(), *[i.available() for i in creators]])

            return inner
        else:
            raise TypeError(f"no supported mixin for {type(target)}")

    return wrapper


it = create

if os.getenv("CREART_AUTO_SCAN") not in {"false", "False", "0", "no", "off"}:
    _env_scan()
