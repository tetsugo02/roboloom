"""Files a configuration names: relative to the naming file, or shipped with roboloom.

`roboloom:robots/rakuda2/model/assembly_2.urdf` names a file inside the installed
package, so a project made by `roboloom init` does not depend on a source checkout.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

PREFIX = "roboloom:"


def is_package_ref(ref: object) -> bool:
    return isinstance(ref, str) and ref.startswith(PREFIX)


def resolve(ref: str | Path, base_dir: str | Path | None = None) -> Path:
    if is_package_ref(ref):
        path = Path(str(resources.files("roboloom").joinpath(str(ref)[len(PREFIX) :])))
        if not path.exists():
            raise FileNotFoundError(f"{ref}: not shipped with this roboloom")
        return path
    path = Path(ref)
    if not path.is_absolute() and base_dir is not None:
        path = Path(base_dir) / path
    return path.resolve()
