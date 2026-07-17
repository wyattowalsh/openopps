from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openopps.coverage import AUDIT_PROVIDER_TARGETS
from openopps.models import ExportFormat
from openopps.providers.base import ProviderDefinition
from openopps.providers.boards import board_provider_definitions
from openopps.providers.sources import BOARD_SOURCE_RECORDS, source_provider_definitions


def build_docs_data() -> dict[str, Any]:
    """Build deterministic package-derived metadata for the docs site."""

    source_definitions = source_provider_definitions()
    job_definitions = board_provider_definitions()
    source_records = sorted(BOARD_SOURCE_RECORDS, key=lambda source: source.key)
    return {
        "stats": {
            "sourceRecordCount": len(source_records),
            "sourceAdapterCount": len(source_definitions),
            "jobProviderCount": len(job_definitions),
            "exportFormatCount": len(ExportFormat),
        },
        "sourceAdapters": [
            _provider_definition_data(item) for item in source_definitions
        ],
        "jobProviders": [_provider_definition_data(item) for item in job_definitions],
        "sourceCatalog": [
            {
                "key": source.key,
                "providerId": source.provider_id,
                "url": source.url,
                "taxonomy": _source_taxonomy_data(source.raw_metadata),
            }
            for source in source_records
        ],
        "auditProviderTargets": list(AUDIT_PROVIDER_TARGETS),
        "exportFormats": [item.value for item in ExportFormat],
    }


def _provider_definition_data(definition: ProviderDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "label": definition.label,
        "kind": definition.kind.value,
        "supportLevel": definition.support_level.value,
        "description": definition.description,
        "detectsRoutes": definition.route_detector is not None,
    }


def _source_taxonomy_data(raw_metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "providerType",
        "coverageMode",
        "accessType",
        "licenseStatus",
        "refreshCadence",
        "sourceYear",
        "sourceCategory",
        "sourceAttribution",
        "inclusionReason",
    )
    return {key: raw_metadata[key] for key in keys if key in raw_metadata}


def main() -> None:
    output_path = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "lib"
        / "generated"
        / "openopps-data.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_docs_data(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
