"""Standard module protocol and registry.

A standard module owns: its identity (id, title, edition), an applicability
predicate, and a `run()` that returns clause-cited CheckResults. Modules
register at import time; `everify.standards` imports all bundled modules.
"""

from __future__ import annotations

import abc
from typing import ClassVar

from everify.engine.results import CheckResult, ClauseRef, StandardInfo
from everify.models.part import Part


class UnknownStandardError(KeyError):
    pass


class StandardModule(abc.ABC):
    id: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]] = ()
    title: ClassVar[str]
    edition: ClassVar[str]
    note: ClassVar[str] = ""

    @abc.abstractmethod
    def applicable(self, part: Part) -> bool: ...

    @abc.abstractmethod
    def run(self, part: Part) -> list[CheckResult]: ...

    def clause(
        self, clause: str, title: str, quote: str | None = None, note: str | None = None
    ) -> ClauseRef:
        return ClauseRef(
            standard=self.title, edition=self.edition, clause=clause, title=title,
            quote=quote, note=note,
        )

    def info(self) -> StandardInfo:
        return StandardInfo(id=self.id, title=self.title, edition=self.edition,
                            note=self.note or None)


_REGISTRY: dict[str, StandardModule] = {}


def _normalize(key: str) -> str:
    return key.strip().lower().replace(" ", "-").replace("_", "-")


def register(module: StandardModule) -> StandardModule:
    for key in (module.id, *module.aliases):
        _REGISTRY[_normalize(key)] = module
    return module


def resolve(standard_id: str) -> StandardModule:
    try:
        return _REGISTRY[_normalize(standard_id)]
    except KeyError:
        available = ", ".join(sorted({m.id for m in _REGISTRY.values()}))
        raise UnknownStandardError(
            f"unknown standard {standard_id!r}; available modules: {available}"
        ) from None


def list_modules() -> list[StandardModule]:
    seen: dict[str, StandardModule] = {}
    for module in _REGISTRY.values():
        seen.setdefault(module.id, module)
    return sorted(seen.values(), key=lambda m: m.id)
