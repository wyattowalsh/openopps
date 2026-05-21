from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    ConsiderCompaniesResponse,
    ConsiderCompany,
    SourceRecord,
    utc_now,
)
from openopps.providers.registry import default_registry
from openopps.settings import OpenOppsSettings
from openopps.url_validation import validate_public_https_url
from openopps.utils import slugify, source_board_key, stable_id


DEFAULT_A16Z_SOURCE = SourceRecord(
    key="a16z",
    url="https://jobs.a16z.com/companies",
    provider_id="consider_a16z",
    enabled=True,
    raw_metadata={"board": "andreessen-horowitz"},
)

DEFAULT_CONSIDER_SOURCES = {
    "a16z": DEFAULT_A16Z_SOURCE,
    "anthemis": SourceRecord(
        key="anthemis",
        url="https://jobs.anthemis.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "anthemis-group"},
    ),
    "aixventures": SourceRecord(
        key="aixventures",
        url="https://careers.aixventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "aix-ventures"},
    ),
    "alter": SourceRecord(
        key="alter",
        url="https://careers.alter.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "alter-global"},
    ),
    "abstractvc": SourceRecord(
        key="abstractvc",
        url="https://jobs.abstractvc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "abstract-ventures"},
    ),
    "adverb": SourceRecord(
        key="adverb",
        url="https://jobs.adverb.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "adverb-ventures"},
    ),
    "age1": SourceRecord(
        key="age1",
        url="https://careers.age1.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "age1"},
    ),
    "atlasventure": SourceRecord(
        key="atlasventure",
        url="https://careers.atlasventure.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "atlas-venture"},
    ),
    "atoneventures": SourceRecord(
        key="atoneventures",
        url="https://jobs.atoneventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "at-one-ventures"},
    ),
    "bakarlabs": SourceRecord(
        key="bakarlabs",
        url="https://jobs.bakarlabs.org/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "bakar-bio-labs"},
    ),
    "lsvp": SourceRecord(
        key="lsvp",
        url="https://jobs.lsvp.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "lightspeed"},
    ),
    "sequoia": SourceRecord(
        key="sequoia",
        url="https://jobs.sequoiacap.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "sequoia-capital"},
    ),
    "bvp": SourceRecord(
        key="bvp",
        url="https://jobs.bvp.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "bessemer-ventures"},
    ),
    "baincapitalventures": SourceRecord(
        key="baincapitalventures",
        url="https://jobs.baincapitalventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "bain-ventures"},
    ),
    "battery": SourceRecord(
        key="battery",
        url="https://jobs.battery.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "battery-ventures"},
    ),
    "balderton": SourceRecord(
        key="balderton",
        url="https://careers.balderton.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "balderton-capital"},
    ),
    "costanoavc": SourceRecord(
        key="costanoavc",
        url="https://jobs.costanoavc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "costanoa-ventures"},
    ),
    "crv": SourceRecord(
        key="crv",
        url="https://jobs.crv.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "crv"},
    ),
    "contrary": SourceRecord(
        key="contrary",
        url="https://jobs.contrary.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "contrary"},
    ),
    "conversioncapital": SourceRecord(
        key="conversioncapital",
        url="https://jobs.conversioncapital.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "conversion-capital"},
    ),
    "creandum": SourceRecord(
        key="creandum",
        url="https://careers.creandum.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "creandum"},
    ),
    "felicis": SourceRecord(
        key="felicis",
        url="https://jobs.felicis.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "felicis"},
    ),
    "fincapital": SourceRecord(
        key="fincapital",
        url="https://jobs.fin.capital/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "fin-capital"},
    ),
    "fiftyyears": SourceRecord(
        key="fiftyyears",
        url="https://jobs.fiftyyears.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "fifty-years"},
    ),
    "f2vc": SourceRecord(
        key="f2vc",
        url="https://jobs.f2vc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "f2-venture-capital"},
    ),
    "fenbushicapital": SourceRecord(
        key="fenbushicapital",
        url="https://careers.fenbushicapital.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "fenbushi-capital"},
    ),
    "forerunnerventures": SourceRecord(
        key="forerunnerventures",
        url="https://jobs.forerunnerventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "forerunner-ventures"},
    ),
    "hardyaka": SourceRecord(
        key="hardyaka",
        url="https://jobs.hardyaka.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "hard-yaka"},
    ),
    "amplifypartners": SourceRecord(
        key="amplifypartners",
        url="https://talent.amplifypartners.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "amplify-partners"},
    ),
    "greylock": SourceRecord(
        key="greylock",
        url="https://jobs.greylock.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "greylock-partners"},
    ),
    "goldenventures": SourceRecord(
        key="goldenventures",
        url="https://jobs.golden.ventures/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "golden-ventures"},
    ),
    "gaingels": SourceRecord(
        key="gaingels",
        url="https://jobs.gaingels.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "gaingels"},
    ),
    "gv": SourceRecord(
        key="gv",
        url="https://jobs.gv.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "gv"},
    ),
    "ivp": SourceRecord(
        key="ivp",
        url="https://careers.ivp.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "ivp"},
    ),
    "initialized": SourceRecord(
        key="initialized",
        url="https://jobs.initialized.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "initialized"},
    ),
    "iconventures": SourceRecord(
        key="iconventures",
        url="https://jobs.iconventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "icon-ventures"},
    ),
    "hitachiventures": SourceRecord(
        key="hitachiventures",
        url="https://jobs.hitachi-ventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "hitachi-ventures"},
    ),
    "e14": SourceRecord(
        key="e14",
        url="https://jobs.e14.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "e14-fund"},
    ),
    "expa": SourceRecord(
        key="expa",
        url="https://jobs.expa.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "expa"},
    ),
    "extantia": SourceRecord(
        key="extantia",
        url="https://careers.extantia.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "extantia"},
    ),
    "illuminatefinancial": SourceRecord(
        key="illuminatefinancial",
        url="https://jobs.illuminatefinancial.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "illuminate-financial"},
    ),
    "kleinerperkins": SourceRecord(
        key="kleinerperkins",
        url="https://jobs.kleinerperkins.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "kleiner-perkins"},
    ),
    "linkventures": SourceRecord(
        key="linkventures",
        url="https://jobs.linkventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "link-ventures"},
    ),
    "nea": SourceRecord(
        key="nea",
        url="https://careers.nea.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "nea"},
    ),
    "nextview": SourceRecord(
        key="nextview",
        url="https://jobs.nextview.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "nextview-ventures"},
    ),
    "necessary": SourceRecord(
        key="necessary",
        url="https://jobs.necessary.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "necessary-ventures"},
    ),
    "panteracapital": SourceRecord(
        key="panteracapital",
        url="https://jobs.panteracapital.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "pantera-capital"},
    ),
    "playground": SourceRecord(
        key="playground",
        url="https://careers.playground.global/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "playground-global"},
    ),
    "nvp": SourceRecord(
        key="nvp",
        url="https://careers.nvp.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "norwest-venture-partners"},
    ),
    "nexusvp": SourceRecord(
        key="nexusvp",
        url="https://jobs.nexusvp.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "nexus-venture-partners"},
    ),
    "mvp": SourceRecord(
        key="mvp",
        url="https://talent.mvp-vc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "mvp-ventures"},
    ),
    "mantisvc": SourceRecord(
        key="mantisvc",
        url="https://careers.mantisvc.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "mantis"},
    ),
    "notation": SourceRecord(
        key="notation",
        url="https://consider.com/boards/vc/notation-capital/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "notation-capital"},
    ),
    "notion": SourceRecord(
        key="notion",
        url="https://jobs.notion.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "notion-capital"},
    ),
    "offline": SourceRecord(
        key="offline",
        url="https://jobs.offline.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "offline-ventures"},
    ),
    "oneragtime": SourceRecord(
        key="oneragtime",
        url="https://careers.oneragtime.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "oneragtime"},
    ),
    "qedinvestors": SourceRecord(
        key="qedinvestors",
        url="https://careers.qedinvestors.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "qed-investors"},
    ),
    "usv": SourceRecord(
        key="usv",
        url="https://jobs.usv.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "union-square-ventures"},
    ),
    "vuventurepartners": SourceRecord(
        key="vuventurepartners",
        url="https://jobs.vuventurepartners.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "vu-venture-partners"},
    ),
    "transition": SourceRecord(
        key="transition",
        url="https://jobs.transition.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "transition-ventures"},
    ),
    "threshold": SourceRecord(
        key="threshold",
        url="https://jobs.threshold.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "threshold-ventures"},
    ),
    "urbaninnovationfund": SourceRecord(
        key="urbaninnovationfund",
        url="https://jobs.urbaninnovationfund.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "urban-innovation-fund"},
    ),
    "woven": SourceRecord(
        key="woven",
        url="https://portfoliojobs.woven.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "woven-capital"},
    ),
    "sosv": SourceRecord(
        key="sosv",
        url="https://techjobs.sosv.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "sosv"},
    ),
    "startx": SourceRecord(
        key="startx",
        url="https://jobs.startx.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "startx"},
    ),
    "qplusequality": SourceRecord(
        key="qplusequality",
        url="https://jobs.qplusequality.org/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "q-plus-equality"},
    ),
    "hoxtonventures": SourceRecord(
        key="hoxtonventures",
        url="https://jobs.hoxtonventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "hoxton-ventures"},
    ),
    "xange": SourceRecord(
        key="xange",
        url="https://jobs.xange.vc/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "xange"},
    ),
    "zettavp": SourceRecord(
        key="zettavp",
        url="https://careers.zettavp.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "zetta-venture-partners"},
    ),
    "5amventures": SourceRecord(
        key="5amventures",
        url="https://jobs.5amventures.com/companies",
        provider_id="consider",
        enabled=True,
        raw_metadata={"board": "5am-ventures"},
    ),
}


class ConsiderSourceAdapter:
    provider_id = "consider"

    def __init__(self, settings: OpenOppsSettings, board: str | None = None):
        self.settings = settings
        self.board = board
        self.registry = default_registry()
        self._request_json = retrying_json_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        board = str(source.raw_metadata.get("board") or self.board or source.key)
        parsed = urlparse(source.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        endpoint = f"{origin}/api-boards/search-companies"
        sequence: str | None = None
        while True:
            meta: dict[str, Any] = {"size": page_size}
            if sequence:
                meta["sequence"] = sequence
            payload = {
                "query": {"parent": board},
                "meta": meta,
                "board": {"id": board, "isParent": True},
            }
            response = await self._request_json(
                client,
                "POST",
                endpoint,
                json=payload,
                headers={
                    "content-type": "application/json",
                    "referer": source.url,
                    "origin": origin,
                },
            )
            if not isinstance(response, dict):
                raise ValueError(
                    "Consider companies endpoint returned a non-object JSON payload"
                )
            payload = ConsiderCompaniesResponse.model_validate(response)
            boards, providers = self._normalize_companies(source.key, payload.companies)
            yield (
                boards,
                providers,
                {
                    "version": payload.version,
                    "meta": payload.meta,
                    "total": payload.total,
                },
            )
            next_sequence = payload.meta.get("sequence")
            if not payload.companies or not next_sequence or next_sequence == sequence:
                break
            sequence = str(next_sequence)

    def _normalize_companies(
        self,
        source_key: str,
        companies: list[ConsiderCompany],
    ) -> tuple[list[BoardRecord], list[BoardProviderRecord]]:
        boards: list[BoardRecord] = []
        providers: list[BoardProviderRecord] = []
        now = utc_now()
        for company in companies:
            remote_id = str(company.id or company.slug or company.name)
            remote_slug = company.slug or slugify(remote_id)
            board_key = source_board_key(source_key, remote_slug)
            website_url = company.website.url if company.website else None
            board = BoardRecord(
                key=board_key,
                source_key=source_key,
                remote_id=remote_id,
                remote_slug=str(remote_slug),
                name=company.name or remote_id,
                domain=company.domain,
                website_url=website_url,
                description=company.description,
                markets=company.markets,
                locations=company.office_locations,
                staff_count=company.staff_count,
                num_jobs_hint=company.num_jobs,
                raw_payload=company.as_raw_payload(),
                synced_at=now,
            )
            boards.append(board)
            for job_source in company.job_sources:
                provider_id = str(job_source.id or job_source.value or "").strip()
                if not provider_id:
                    continue
                providers.append(
                    BoardProviderRecord(
                        id=stable_id(source_key, board_key, provider_id),
                        source_key=source_key,
                        board_key=board_key,
                        provider_id=provider_id,
                        label=job_source.label,
                        support_level=self.registry.support_level(provider_id),
                        count_hint=job_source.count,
                        raw_payload=job_source.as_raw_payload(),
                        detected_at=now,
                    )
                )
        return boards, providers


class ConsiderA16zSourceAdapter(ConsiderSourceAdapter):
    provider_id = "consider_a16z"
