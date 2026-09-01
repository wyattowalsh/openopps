"""Test and notebook-facing re-exports from the openopps_kaggle package."""

from __future__ import annotations

import openopps_kaggle._core as _core
from openopps_kaggle._core import (
    PUBLIC_EXAMPLE_NOTEBOOKS as PUBLIC_EXAMPLE_NOTEBOOKS,
    STARTER_NB_ID as STARTER_NB_ID,
    kernel_metadata_for_spec as kernel_metadata_for_spec,
    starter_kernel_metadata as starter_kernel_metadata,
    starter_notebook as starter_notebook,
)
from openopps_kaggle.runtime_manifest import (  # noqa: F401
    runtime_generator_script_sha256,
    runtime_package_manifest,
    runtime_package_sha256,
    verify_runtime_package,
)

globals().update(
    {name: value for name, value in vars(_core).items() if not name.startswith("__")}
)
