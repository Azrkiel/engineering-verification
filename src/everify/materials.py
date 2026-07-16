"""Material library loading.

Bundled records are EXAMPLE values compiled from public references and are
flagged requires_verification — the engine warns on every result derived from
them until the user marks them verified. Point --materials at your own
directory of YAML records (same schema) to use your licensed data.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Iterable

import yaml

from everify.models.material import Material


def _load_record(text: str, origin: str) -> Material:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{origin}: expected a YAML mapping describing a material")
    return Material.model_validate(data)


def load_material_library(extra_dirs: Iterable[str | Path] = ()) -> dict[str, Material]:
    library: dict[str, Material] = {}
    root = resources.files("everify") / "data" / "materials"
    for entry in root.iterdir():
        if entry.name.endswith(".yaml"):
            mat = _load_record(entry.read_text(), origin=entry.name)
            library[mat.id] = mat
    for d in extra_dirs:
        for path in sorted(Path(d).glob("*.yaml")):
            mat = _load_record(path.read_text(), origin=str(path))
            library[mat.id] = mat  # user data shadows bundled records
    return library
