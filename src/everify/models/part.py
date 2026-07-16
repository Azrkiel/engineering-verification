"""The Part: the unit of verification."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml
from pydantic import Field

from everify.models.base import EverifyModel
from everify.models.geometry import Geometry
from everify.models.loads import DesignConditions, LoadCase
from everify.models.material import Material


class UnknownMaterialError(KeyError):
    pass


class Part(EverifyModel):
    id: str
    name: str
    description: str | None = None
    revision: str = "A"
    material: Material | str = Field(
        description="A material library id (e.g. 'SA-516-70') or an inline material definition"
    )
    geometry: Geometry | None = None
    design_conditions: DesignConditions | None = None
    load_cases: list[LoadCase] = Field(default_factory=list)
    standards: list[str] = Field(
        min_length=1, description="Standard module ids to verify against, e.g. ['asme-viii-div1']"
    )
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Part":
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a YAML mapping describing a part")
        return cls.model_validate(data)

    def resolved(self, library: Mapping[str, Material]) -> "Part":
        """Return a copy with the material reference replaced by the full material record."""
        if isinstance(self.material, Material):
            return self
        mat = library.get(self.material)
        if mat is None:
            raise UnknownMaterialError(
                f"material {self.material!r} not found in library "
                f"(available: {', '.join(sorted(library)) or 'none'})"
            )
        return self.model_copy(update={"material": mat})
