from __future__ import annotations

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, TypeVar


@dataclass
class CreateTargetInfo:
    """Information of create target."""

    module: str
    """dotted name of target's module"""

    identify: str
    """target's qualified name"""

    # info for cli
    humanized_name: str | None = None
    """humanized name"""

    description: str | None = None
    """description of target"""

    author: list[str] | None = None
    """list of authors"""


T = TypeVar("T")


class AbstractCreator(metaclass=ABCMeta):
    """factory of `targets` class attributes

    add `entry points` in your distribution to support auto discovery.
    """

    targets: ClassVar[tuple[CreateTargetInfo, ...]]
    """Supported targets' creation info, as a tuple."""

    @staticmethod
    def available() -> bool:
        """This function will be called to determine whether the targets could be created."""
        return True

    @staticmethod
    @abstractmethod
    def create(create_type: type[T]) -> T:
        """Actual creation implementation."""
        ...
