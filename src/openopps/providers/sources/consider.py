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
    normalize_public_website_url,
    utc_now,
    validate_public_https_url,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify, source_board_key, stable_id

A16Z_SOURCE = SourceRecord(
    key="a16z",
    url="https://jobs.a16z.com/companies",
    provider_id="consider_a16z",
    raw_metadata={"board": "andreessen-horowitz"},
)

INDIEBIO_SOURCE = SourceRecord(
    key="indiebio",
    url="https://indiebio.board.staging.consider.com/companies",
    provider_id="consider",
    raw_metadata={"board": "indiebio"},
)


VALTRUIS_SOURCE = SourceRecord(
    key="valtruis",
    url="https://careers.valtruis.com/companies",
    provider_id="consider",
    raw_metadata={"board": "valtruis"},
)

SELECTPRIORINVESTMENTS_SOURCE = SourceRecord(
    key="selectpriorinvestments",
    url="https://consider.com/boards/vc/select-prior-investments/companies",
    provider_id="consider",
    raw_metadata={"board": "selectpriorinvestments"},
)

VISTRIA_SOURCE = SourceRecord(
    key="vistria",
    url="https://consider.com/boards/vc/vistria/companies",
    provider_id="consider",
    raw_metadata={"board": "vistria"},
)


CONSIDER_SOURCE_CATALOG = {
    "a16z": A16Z_SOURCE,
    "anthemis": SourceRecord(
        key="anthemis",
        url="https://jobs.anthemis.com/companies",
        provider_id="consider",
        raw_metadata={"board": "anthemis-group"},
    ),
    "aixventures": SourceRecord(
        key="aixventures",
        url="https://careers.aixventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "aix-ventures"},
    ),
    "alter": SourceRecord(
        key="alter",
        url="https://careers.alter.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "alter-global"},
    ),
    "abstractvc": SourceRecord(
        key="abstractvc",
        url="https://jobs.abstractvc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "abstract-ventures"},
    ),
    "adverb": SourceRecord(
        key="adverb",
        url="https://jobs.adverb.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "adverb-ventures"},
    ),
    "age1": SourceRecord(
        key="age1",
        url="https://careers.age1.com/companies",
        provider_id="consider",
        raw_metadata={"board": "age1"},
    ),
    "atlasventure": SourceRecord(
        key="atlasventure",
        url="https://careers.atlasventure.com/companies",
        provider_id="consider",
        raw_metadata={"board": "atlas-venture"},
    ),
    "atoneventures": SourceRecord(
        key="atoneventures",
        url="https://jobs.atoneventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "at-one-ventures"},
    ),
    "bakarlabs": SourceRecord(
        key="bakarlabs",
        url="https://jobs.bakarlabs.org/companies",
        provider_id="consider",
        raw_metadata={"board": "bakar-bio-labs"},
    ),
    "lsvp": SourceRecord(
        key="lsvp",
        url="https://jobs.lsvp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "lightspeed"},
    ),
    "sequoia": SourceRecord(
        key="sequoia",
        url="https://jobs.sequoiacap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "sequoia-capital"},
    ),
    "bvp": SourceRecord(
        key="bvp",
        url="https://jobs.bvp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "bessemer-ventures"},
    ),
    "baincapitalventures": SourceRecord(
        key="baincapitalventures",
        url="https://jobs.baincapitalventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "bain-ventures"},
    ),
    "battery": SourceRecord(
        key="battery",
        url="https://jobs.battery.com/companies",
        provider_id="consider",
        raw_metadata={"board": "battery-ventures"},
    ),
    "balderton": SourceRecord(
        key="balderton",
        url="https://careers.balderton.com/companies",
        provider_id="consider",
        raw_metadata={"board": "balderton-capital"},
    ),
    "costanoavc": SourceRecord(
        key="costanoavc",
        url="https://jobs.costanoavc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "costanoa-ventures"},
    ),
    "crv": SourceRecord(
        key="crv",
        url="https://jobs.crv.com/companies",
        provider_id="consider",
        raw_metadata={"board": "crv"},
    ),
    "contrary": SourceRecord(
        key="contrary",
        url="https://jobs.contrary.com/companies",
        provider_id="consider",
        raw_metadata={"board": "contrary"},
    ),
    "conversioncapital": SourceRecord(
        key="conversioncapital",
        url="https://jobs.conversioncapital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "conversion-capital"},
    ),
    "creandum": SourceRecord(
        key="creandum",
        url="https://careers.creandum.com/companies",
        provider_id="consider",
        raw_metadata={"board": "creandum"},
    ),
    "felicis": SourceRecord(
        key="felicis",
        url="https://jobs.felicis.com/companies",
        provider_id="consider",
        raw_metadata={"board": "felicis"},
    ),
    "fincapital": SourceRecord(
        key="fincapital",
        url="https://jobs.fin.capital/companies",
        provider_id="consider",
        raw_metadata={"board": "fin-capital"},
    ),
    "fiftyyears": SourceRecord(
        key="fiftyyears",
        url="https://jobs.fiftyyears.com/companies",
        provider_id="consider",
        raw_metadata={"board": "fifty-years"},
    ),
    "f2vc": SourceRecord(
        key="f2vc",
        url="https://jobs.f2vc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "f2-venture-capital"},
    ),
    "fenbushicapital": SourceRecord(
        key="fenbushicapital",
        url="https://careers.fenbushicapital.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "fenbushi-capital"},
    ),
    "forerunnerventures": SourceRecord(
        key="forerunnerventures",
        url="https://jobs.forerunnerventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "forerunner-ventures"},
    ),
    "hardyaka": SourceRecord(
        key="hardyaka",
        url="https://jobs.hardyaka.com/companies",
        provider_id="consider",
        raw_metadata={"board": "hard-yaka"},
    ),
    "amplifypartners": SourceRecord(
        key="amplifypartners",
        url="https://talent.amplifypartners.com/companies",
        provider_id="consider",
        raw_metadata={"board": "amplify-partners"},
    ),
    "greylock": SourceRecord(
        key="greylock",
        url="https://jobs.greylock.com/companies",
        provider_id="consider",
        raw_metadata={"board": "greylock-partners"},
    ),
    "goldenventures": SourceRecord(
        key="goldenventures",
        url="https://jobs.golden.ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "golden-ventures"},
    ),
    "gaingels": SourceRecord(
        key="gaingels",
        url="https://jobs.gaingels.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gaingels"},
    ),
    "gv": SourceRecord(
        key="gv",
        url="https://jobs.gv.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gv"},
    ),
    "ivp": SourceRecord(
        key="ivp",
        url="https://careers.ivp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "ivp"},
    ),
    "initialized": SourceRecord(
        key="initialized",
        url="https://jobs.initialized.com/companies",
        provider_id="consider",
        raw_metadata={"board": "initialized"},
    ),
    "iconventures": SourceRecord(
        key="iconventures",
        url="https://jobs.iconventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "icon-ventures"},
    ),
    "hitachiventures": SourceRecord(
        key="hitachiventures",
        url="https://jobs.hitachi-ventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "hitachi-ventures"},
    ),
    "e14": SourceRecord(
        key="e14",
        url="https://jobs.e14.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "e14-fund"},
    ),
    "expa": SourceRecord(
        key="expa",
        url="https://jobs.expa.com/companies",
        provider_id="consider",
        raw_metadata={"board": "expa"},
    ),
    "extantia": SourceRecord(
        key="extantia",
        url="https://careers.extantia.com/companies",
        provider_id="consider",
        raw_metadata={"board": "extantia"},
    ),
    "illuminatefinancial": SourceRecord(
        key="illuminatefinancial",
        url="https://jobs.illuminatefinancial.com/companies",
        provider_id="consider",
        raw_metadata={"board": "illuminate-financial"},
    ),
    "kleinerperkins": SourceRecord(
        key="kleinerperkins",
        url="https://jobs.kleinerperkins.com/companies",
        provider_id="consider",
        raw_metadata={"board": "kleiner-perkins"},
    ),
    "linkventures": SourceRecord(
        key="linkventures",
        url="https://jobs.linkventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "link-ventures"},
    ),
    "nea": SourceRecord(
        key="nea",
        url="https://careers.nea.com/companies",
        provider_id="consider",
        raw_metadata={"board": "nea"},
    ),
    "nextview": SourceRecord(
        key="nextview",
        url="https://jobs.nextview.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "nextview-ventures"},
    ),
    "necessary": SourceRecord(
        key="necessary",
        url="https://jobs.necessary.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "necessary-ventures"},
    ),
    "panteracapital": SourceRecord(
        key="panteracapital",
        url="https://jobs.panteracapital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "pantera-capital"},
    ),
    "playground": SourceRecord(
        key="playground",
        url="https://careers.playground.global/companies",
        provider_id="consider",
        raw_metadata={"board": "playground-global"},
    ),
    "nvp": SourceRecord(
        key="nvp",
        url="https://careers.nvp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "norwest-venture-partners"},
    ),
    "nexusvp": SourceRecord(
        key="nexusvp",
        url="https://jobs.nexusvp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "nexus-venture-partners"},
    ),
    "mvp": SourceRecord(
        key="mvp",
        url="https://talent.mvp-vc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "mvp-ventures"},
    ),
    "mantisvc": SourceRecord(
        key="mantisvc",
        url="https://careers.mantisvc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "mantis"},
    ),
    "notation": SourceRecord(
        key="notation",
        url="https://consider.com/boards/vc/notation-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "notation-capital"},
    ),
    "notion": SourceRecord(
        key="notion",
        url="https://jobs.notion.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "notion-capital"},
    ),
    "offline": SourceRecord(
        key="offline",
        url="https://jobs.offline.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "offline-ventures"},
    ),
    "oneragtime": SourceRecord(
        key="oneragtime",
        url="https://careers.oneragtime.com/companies",
        provider_id="consider",
        raw_metadata={"board": "oneragtime"},
    ),
    "qedinvestors": SourceRecord(
        key="qedinvestors",
        url="https://careers.qedinvestors.com/companies",
        provider_id="consider",
        raw_metadata={"board": "qed-investors"},
    ),
    "usv": SourceRecord(
        key="usv",
        url="https://jobs.usv.com/companies",
        provider_id="consider",
        raw_metadata={"board": "union-square-ventures"},
    ),
    "vuventurepartners": SourceRecord(
        key="vuventurepartners",
        url="https://jobs.vuventurepartners.com/companies",
        provider_id="consider",
        raw_metadata={"board": "vu-venture-partners"},
    ),
    "transition": SourceRecord(
        key="transition",
        url="https://jobs.transition.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "transition-ventures"},
    ),
    "threshold": SourceRecord(
        key="threshold",
        url="https://jobs.threshold.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "threshold-ventures"},
    ),
    "urbaninnovationfund": SourceRecord(
        key="urbaninnovationfund",
        url="https://jobs.urbaninnovationfund.com/companies",
        provider_id="consider",
        raw_metadata={"board": "urban-innovation-fund"},
    ),
    "woven": SourceRecord(
        key="woven",
        url="https://portfoliojobs.woven.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "woven-capital"},
    ),
    "sosv": SourceRecord(
        key="sosv",
        url="https://techjobs.sosv.com/companies",
        provider_id="consider",
        raw_metadata={"board": "sosv"},
    ),
    "startx": SourceRecord(
        key="startx",
        url="https://jobs.startx.com/companies",
        provider_id="consider",
        raw_metadata={"board": "startx"},
    ),
    "hoxtonventures": SourceRecord(
        key="hoxtonventures",
        url="https://jobs.hoxtonventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "hoxton-ventures"},
    ),
    "xange": SourceRecord(
        key="xange",
        url="https://jobs.xange.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "xange"},
    ),
    "zettavp": SourceRecord(
        key="zettavp",
        url="https://careers.zettavp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "zetta-venture-partners"},
    ),
    "5amventures": SourceRecord(
        key="5amventures",
        url="https://jobs.5amventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "5am-ventures"},
    ),
    "01a": SourceRecord(
        key="01a",
        url="https://jobs.01a.com/companies",
        provider_id="consider",
        raw_metadata={"board": "01-advisors"},
    ),
    "360cap": SourceRecord(
        key="360cap",
        url="https://jobs.360cap.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "360-capital"},
    ),
    "adara": SourceRecord(
        key="adara",
        url="https://talent.adara.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "adara-ventures"},
    ),
    "aifund": SourceRecord(
        key="aifund",
        url="https://careers.aifund.ai/companies",
        provider_id="consider",
        raw_metadata={"board": "ai-fund"},
    ),
    "alven": SourceRecord(
        key="alven",
        url="https://jobs.alven.co/companies",
        provider_id="consider",
        raw_metadata={"board": "alven"},
    ),
    "amplifyla": SourceRecord(
        key="amplifyla",
        url="https://jobs.amplify.la/companies",
        provider_id="consider",
        raw_metadata={"board": "amplify-la"},
    ),
    "congruentvc": SourceRecord(
        key="congruentvc",
        url="https://jobs.congruentvc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "congruent-ventures"},
    ),
    "etherealventures": SourceRecord(
        key="etherealventures",
        url="https://consider.com/boards/vc/ethereal-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "ethereal-ventures"},
    ),
    "foothillventures": SourceRecord(
        key="foothillventures",
        url="https://jobs.foothill.ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "foothill-ventures"},
    ),
    "founderful": SourceRecord(
        key="founderful",
        url="https://jobs.founderful.com/companies",
        provider_id="consider",
        raw_metadata={"board": "wingman"},
    ),
    "galvanizeclimate": SourceRecord(
        key="galvanizeclimate",
        url="https://consider.com/boards/vc/galvanize-climate-solutions/companies",
        provider_id="consider",
        raw_metadata={"board": "galvanize-climate-solutions"},
    ),
    "gradient": SourceRecord(
        key="gradient",
        url="https://careers.gradient.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gradient-ventures"},
    ),
    "gtmfund": SourceRecord(
        key="gtmfund",
        url="https://jobs.gtmfund.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gtmfund"},
    ),
    "istariglobal": SourceRecord(
        key="istariglobal",
        url="https://careers.istari-global.com/companies",
        provider_id="consider",
        raw_metadata={"board": "istari"},
    ),
    "lemniscap": SourceRecord(
        key="lemniscap",
        url="https://careers.lemniscap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "lemniscap"},
    ),
    "oregonventurefund": SourceRecord(
        key="oregonventurefund",
        url="https://jobs.oregonventurefund.com/companies",
        provider_id="consider",
        raw_metadata={"board": "oregon-venture-fund"},
    ),
    "peakxv": SourceRecord(
        key="peakxv",
        url="https://careers.peakxv.com/companies",
        provider_id="consider",
        raw_metadata={"board": "sequoia-capital-india"},
    ),
    "radiancapital": SourceRecord(
        key="radiancapital",
        url="https://careers.radiancapital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "radian-capital"},
    ),
    "serena": SourceRecord(
        key="serena",
        url="https://careers.serena.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "serena"},
    ),
    "setventures": SourceRecord(
        key="setventures",
        url="https://careers.setventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "set-ventures"},
    ),
    "skyvc": SourceRecord(
        key="skyvc",
        url="https://careers.sky-vc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "jetblue-ventures"},
    ),
    "sterlingpartners": SourceRecord(
        key="sterlingpartners",
        url="https://consider.com/boards/vc/sterling-partners/companies",
        provider_id="consider",
        raw_metadata={"board": "sterling-partners"},
    ),
    "thomvest": SourceRecord(
        key="thomvest",
        url="https://jobs.thomvest.com/companies",
        provider_id="consider",
        raw_metadata={"board": "thomvest"},
    ),
    "tidemarkcap": SourceRecord(
        key="tidemarkcap",
        url="https://careers.tidemarkcap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "tidemark-capital"},
    ),
    "verdane": SourceRecord(
        key="verdane",
        url="https://consider.com/boards/vc/verdane/companies",
        provider_id="consider",
        raw_metadata={"board": "verdane"},
    ),
    "leadershipforeducationalequity": SourceRecord(
        key="leadershipforeducationalequity",
        url="https://consider.com/boards/vc/leadership-for-educational-equity/companies",
        provider_id="consider",
        raw_metadata={"board": "leadership-for-educational-equity"},
    ),
    "greentownlabs": SourceRecord(
        key="greentownlabs",
        url="https://jobs.greentownlabs.com/companies",
        provider_id="consider",
        raw_metadata={"board": "greentown-labs"},
    ),
    "baincapital": SourceRecord(
        key="baincapital",
        url="https://consider.com/boards/vc/bain-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "bain-capital"},
    ),
    "sggc": SourceRecord(
        key="sggc",
        url="https://careers.sggc.sg/companies",
        provider_id="consider",
        raw_metadata={"board": "edbi"},
    ),
    "surgeahead": SourceRecord(
        key="surgeahead",
        url="https://jobs.surgeahead.com/companies",
        provider_id="consider",
        raw_metadata={"board": "surge-ahead"},
    ),
    "sorensoncap": SourceRecord(
        key="sorensoncap",
        url="https://careers.sorensoncap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "sorenson-capital"},
    ),
    "1517fund": SourceRecord(
        key="1517fund",
        url="https://consider.com/boards/vc/1517-fund/companies",
        provider_id="consider",
        raw_metadata={"board": "1517-fund"},
    ),
    "dynamovc": SourceRecord(
        key="dynamovc",
        url="https://careers.dynamo.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "dynamo"},
    ),
    "chapterone": SourceRecord(
        key="chapterone",
        url="https://consider.com/boards/vc/chapter-one/companies",
        provider_id="consider",
        raw_metadata={"board": "chapter-one"},
    ),
    "neworleansbio": SourceRecord(
        key="neworleansbio",
        url="https://careers.neworleansbio.com/companies",
        provider_id="consider",
        raw_metadata={"board": "nobic"},
    ),
    "adventinternational": SourceRecord(
        key="adventinternational",
        url="https://consider.com/boards/vc/advent-international/companies",
        provider_id="consider",
        raw_metadata={"board": "advent-international"},
    ),
    "protagonist": SourceRecord(
        key="protagonist",
        url="https://jobs.protagonist.co/companies",
        provider_id="consider",
        raw_metadata={"board": "protagonist"},
    ),
    "courtsidevc": SourceRecord(
        key="courtsidevc",
        url="https://jobs.courtsidevc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "courtside"},
    ),
    "freigeist": SourceRecord(
        key="freigeist",
        url="https://consider.com/boards/vc/freigeist/companies",
        provider_id="consider",
        raw_metadata={"board": "freigeist"},
    ),
    "1835i": SourceRecord(
        key="1835i",
        url="https://consider.com/boards/vc/1835i/companies",
        provider_id="consider",
        raw_metadata={"board": "1835i"},
    ),
    "biocom": SourceRecord(
        key="biocom",
        url="https://consider.com/boards/vc/biocom/companies",
        provider_id="consider",
        raw_metadata={"board": "biocom"},
    ),
    "newyorkbio": SourceRecord(
        key="newyorkbio",
        url="https://consider.com/boards/vc/newyorkbio/companies",
        provider_id="consider",
        raw_metadata={"board": "newyorkbio"},
    ),
    "lakestar": SourceRecord(
        key="lakestar",
        url="https://consider.com/boards/vc/lakestar/companies",
        provider_id="consider",
        raw_metadata={"board": "lakestar"},
    ),
    "amadeus": SourceRecord(
        key="amadeus",
        url="https://consider.com/boards/vc/amadeus/companies",
        provider_id="consider",
        raw_metadata={"board": "amadeus"},
    ),
    "homeworldbio": SourceRecord(
        key="homeworldbio",
        url="https://jobs.homeworld.bio/companies",
        provider_id="consider",
        raw_metadata={"board": "homeworld-collective"},
    ),
    "43north": SourceRecord(
        key="43north",
        url="https://jobs.43north.org/companies",
        provider_id="consider",
        raw_metadata={"board": "forge-buffalo"},
    ),
    "foresitelabs": SourceRecord(
        key="foresitelabs",
        url="https://careers.foresitelabs.com/companies",
        provider_id="consider",
        raw_metadata={"board": "foresite-labs"},
    ),
    "thecolumngroup": SourceRecord(
        key="thecolumngroup",
        url="https://jobs.thecolumngroup.com/companies",
        provider_id="consider",
        raw_metadata={"board": "the-column-group"},
    ),
    "maineventurefund": SourceRecord(
        key="maineventurefund",
        url="https://careers.maineventurefund.com/companies",
        provider_id="consider",
        raw_metadata={"board": "maine-venture-fund"},
    ),
    "muditaventurepartners": SourceRecord(
        key="muditaventurepartners",
        url="https://consider.com/boards/vc/mudita-venture-partners/companies",
        provider_id="consider",
        raw_metadata={"board": "mudita-venture-partners"},
    ),
    "scribblevc": SourceRecord(
        key="scribblevc",
        url="https://jobs.scribble.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "scribble"},
    ),
    "phoenixcourt": SourceRecord(
        key="phoenixcourt",
        url="https://jobs.phoenixcourt.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "localglobe-all"},
    ),
    "techaviv": SourceRecord(
        key="techaviv",
        url="https://jobs.techaviv.com/companies",
        provider_id="consider",
        raw_metadata={"board": "techaviv"},
    ),
    "ctinnovations": SourceRecord(
        key="ctinnovations",
        url="https://careers.ctinnovations.com/companies",
        provider_id="consider",
        raw_metadata={"board": "connecticut-innovations"},
    ),
    "goodwatercap": SourceRecord(
        key="goodwatercap",
        url="https://portfoliojobs.goodwatercap.com/companies",
        provider_id="consider",
        raw_metadata={"board": "goodwater-capital"},
    ),
    "shima": SourceRecord(
        key="shima",
        url="https://jobs.shima.capital/companies",
        provider_id="consider",
        raw_metadata={"board": "shima-capital"},
    ),
    "fabricvc": SourceRecord(
        key="fabricvc",
        url="https://careers.fabric.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "fabric-ventures"},
    ),
    "makersfund": SourceRecord(
        key="makersfund",
        url="https://jobs.makersfund.com/companies",
        provider_id="consider",
        raw_metadata={"board": "makers-fund"},
    ),
    "uppartners": SourceRecord(
        key="uppartners",
        url="https://careers.up.partners/companies",
        provider_id="consider",
        raw_metadata={"board": "up-partners"},
    ),
    "greathillpartners": SourceRecord(
        key="greathillpartners",
        url="https://jobs.greathillpartners.com/companies",
        provider_id="consider",
        raw_metadata={"board": "great-hill-partners"},
    ),
    "thirdrockventures": SourceRecord(
        key="thirdrockventures",
        url="https://jobs.thirdrockventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "third-rock-ventures"},
    ),
    "genoavc": SourceRecord(
        key="genoavc",
        url="https://careers.genoavc.com/companies",
        provider_id="consider",
        raw_metadata={"board": "genoa"},
    ),
    "gridironcapital": SourceRecord(
        key="gridironcapital",
        url="https://jobs.gridironcapital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "gridiron-capital"},
    ),
    "k1": SourceRecord(
        key="k1",
        url="https://portfoliocareers.k1.com/companies",
        provider_id="consider",
        raw_metadata={"board": "k1"},
    ),
    "pumagrowthpartners": SourceRecord(
        key="pumagrowthpartners",
        url="https://jobs.pumagrowthpartners.co.uk/companies",
        provider_id="consider",
        raw_metadata={"board": "puma-pe"},
    ),
    "arsenalgrowth": SourceRecord(
        key="arsenalgrowth",
        url="https://jobs.arsenalgrowth.com/companies",
        provider_id="consider",
        raw_metadata={"board": "arsenal-growth"},
    ),
    "azollaventures": SourceRecord(
        key="azollaventures",
        url="https://jobs.azollaventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "azolla-ventures"},
    ),
    "byldvc": SourceRecord(
        key="byldvc",
        url="https://careers.byld.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "byld-ventures"},
    ),
    "m1c": SourceRecord(
        key="m1c",
        url="https://careers.m1c.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "mission-one"},
    ),
    "revent": SourceRecord(
        key="revent",
        url="https://careers.revent.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "revent"},
    ),
    "zeldavc": SourceRecord(
        key="zeldavc",
        url="https://jobs.zelda.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "zelda-ventures"},
    ),
    "parameter": SourceRecord(
        key="parameter",
        url="https://jobs.parameter.vc/companies",
        provider_id="consider",
        raw_metadata={"board": "parameter-ventures"},
    ),
    "capitalg": SourceRecord(
        key="capitalg",
        url="https://careers.capitalg.com/companies",
        provider_id="consider",
        raw_metadata={"board": "capitalg"},
    ),
    "integritypowersearch": SourceRecord(
        key="integritypowersearch",
        url="https://consider.com/boards/vc/integrity-power-search/companies",
        provider_id="consider",
        raw_metadata={"board": "integrity-power-search"},
    ),
    "cultivationcapital": SourceRecord(
        key="cultivationcapital",
        url="https://portfoliojobs.cultivationcapital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "cultivation-capital"},
    ),
    "cardinalrefer": SourceRecord(
        key="cardinalrefer",
        url="https://consider.com/boards/vc/cardinal-refer/companies",
        provider_id="consider",
        raw_metadata={"board": "cardinal-refer"},
    ),
    "kaszek": SourceRecord(
        key="kaszek",
        url="https://jobs.kaszek.com/companies",
        provider_id="consider",
        raw_metadata={"board": "kaszek"},
    ),
    "rethinkcapital": SourceRecord(
        key="rethinkcapital",
        url="https://rethink-education-portfolio-jobs.rethink-capital.com/companies",
        provider_id="consider",
        raw_metadata={"board": "rethink-capital"},
    ),
    "waed": SourceRecord(
        key="waed",
        url="https://portfoliojobs.waed.com/companies",
        provider_id="consider",
        raw_metadata={"board": "waed"},
    ),
    "westcap": SourceRecord(
        key="westcap",
        url="https://consider.com/boards/vc/westcap/companies",
        provider_id="consider",
        raw_metadata={"board": "westcap"},
    ),
    "dfdf": SourceRecord(
        key="dfdf",
        url="https://consider.com/boards/vc/dfdf/companies",
        provider_id="consider",
        raw_metadata={"board": "dfdf"},
    ),
    "symboliccapital": SourceRecord(
        key="symboliccapital",
        url="https://consider.com/boards/vc/symbolic-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "symbolic-capital"},
    ),
    "greaterwashingtonpartnership": SourceRecord(
        key="greaterwashingtonpartnership",
        url="https://consider.com/boards/vc/greater-washington-partnership/companies",
        provider_id="consider",
        raw_metadata={"board": "greater-washington-partnership"},
    ),
    "trilogyequity": SourceRecord(
        key="trilogyequity",
        url="https://trilogy-equity.board.staging.consider.com/companies",
        provider_id="consider",
        raw_metadata={"board": "trilogy-equity"},
    ),
    "leoportfolio": SourceRecord(
        key="leoportfolio",
        url="https://consider.com/boards/vc/leo-portfolio/companies",
        provider_id="consider",
        raw_metadata={"board": "leo-portfolio"},
    ),
    "nightlabs": SourceRecord(
        key="nightlabs",
        url="https://consider.com/boards/vc/night-labs/companies",
        provider_id="consider",
        raw_metadata={"board": "night-labs"},
    ),
    "bekventures": SourceRecord(
        key="bekventures",
        url="https://jobs.bekventures.com/companies",
        provider_id="consider",
        raw_metadata={"board": "digital-east"},
    ),
    "techchange": SourceRecord(
        key="techchange",
        url="https://consider.com/boards/vc/techchange/companies",
        provider_id="consider",
        raw_metadata={"board": "techchange"},
    ),
    "orbitstartups": SourceRecord(
        key="orbitstartups",
        url="https://consider.com/boards/vc/orbit-startups/companies",
        provider_id="consider",
        raw_metadata={"board": "orbit-startups"},
    ),
    "monkshillventures": SourceRecord(
        key="monkshillventures",
        url="https://consider.com/boards/vc/monks-hill-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "monks-hill-ventures"},
    ),
    "skydeck": SourceRecord(
        key="skydeck",
        url="https://jobs.skydeck.berkeley.edu/companies",
        provider_id="consider",
        raw_metadata={"board": "berkeley-skydeck"},
    ),
    "highalpha": SourceRecord(
        key="highalpha",
        url="https://consider.com/boards/vc/high-alpha/companies",
        provider_id="consider",
        raw_metadata={"board": "high-alpha"},
    ),
    "gigascale": SourceRecord(
        key="gigascale",
        url="https://consider.com/boards/vc/gigascale/companies",
        provider_id="consider",
        raw_metadata={"board": "gigascale"},
    ),
    "hunterpointcapital": SourceRecord(
        key="hunterpointcapital",
        url="https://consider.com/boards/vc/hunter-point-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "hunter-point-capital"},
    ),
    "mbaexchange": SourceRecord(
        key="mbaexchange",
        url="https://consider.com/boards/vc/mba-exchange/companies",
        provider_id="consider",
        raw_metadata={"board": "mba-exchange"},
    ),
    "hashed": SourceRecord(
        key="hashed",
        url="https://consider.com/boards/vc/hashed/companies",
        provider_id="consider",
        raw_metadata={"board": "hashed"},
    ),
    "hummingbirdventures": SourceRecord(
        key="hummingbirdventures",
        url="https://consider.com/boards/vc/hummingbird-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "hummingbird-ventures"},
    ),
    "remotely": SourceRecord(
        key="remotely",
        url="https://consider.com/boards/vc/remotely/companies",
        provider_id="consider",
        raw_metadata={"board": "remotely"},
    ),
    "datapowerventures": SourceRecord(
        key="datapowerventures",
        url="https://consider.com/boards/vc/datapower-ventures/companies",
        provider_id="consider",
        raw_metadata={"board": "datapower-ventures"},
    ),
    "lightrock": SourceRecord(
        key="lightrock",
        url="https://consider.com/boards/vc/lightrock/companies",
        provider_id="consider",
        raw_metadata={"board": "lightrock"},
    ),
    "foxmontcapital": SourceRecord(
        key="foxmontcapital",
        url="https://consider.com/boards/vc/foxmont-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "foxmont-capital"},
    ),
    "adgm": SourceRecord(
        key="adgm",
        url="https://consider.com/boards/vc/adgm/companies",
        provider_id="consider",
        raw_metadata={"board": "adgm"},
    ),
    "hcvc": SourceRecord(
        key="hcvc",
        url="https://jobs.hcvc.co/companies",
        provider_id="consider",
        raw_metadata={"board": "hcvc"},
    ),
    "onepeak": SourceRecord(
        key="onepeak",
        url="https://jobs.onepeak.tech/companies",
        provider_id="consider",
        raw_metadata={"board": "one-peak"},
    ),
    "sprints": SourceRecord(
        key="sprints",
        url="https://jobs.sprints.com/companies",
        provider_id="consider",
        raw_metadata={"board": "sprints"},
    ),
    "foresitecapital": SourceRecord(
        key="foresitecapital",
        url="https://consider.com/boards/vc/foresite-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "foresite-capital"},
    ),
    "paradigmxyz": SourceRecord(
        key="paradigmxyz",
        url="https://consider.com/boards/vc/paradigm-xyz/companies",
        provider_id="consider",
        raw_metadata={"board": "paradigm-xyz"},
    ),
    "griffingp": SourceRecord(
        key="griffingp",
        url="https://careers.griffingp.com/companies",
        provider_id="consider",
        raw_metadata={"board": "griffin-gaming"},
    ),
    "allinmilwaukee": SourceRecord(
        key="allinmilwaukee",
        url="https://consider.com/boards/vc/all-in-milwaukee/companies",
        provider_id="consider",
        raw_metadata={"board": "all-in-milwaukee"},
    ),
    "struckcapital": SourceRecord(
        key="struckcapital",
        url="https://consider.com/boards/vc/struck-capital/companies",
        provider_id="consider",
        raw_metadata={"board": "struck-capital"},
    ),
    "seventyseven": SourceRecord(
        key="seventyseven",
        url="https://consider.com/boards/vc/seventy-seven/companies",
        provider_id="consider",
        raw_metadata={"board": "seventy-seven"},
    ),
    "nv": SourceRecord(
        key="nv",
        url="https://consider.com/boards/vc/nv/companies",
        provider_id="consider",
        raw_metadata={"board": "nv"},
    ),
    "tcgcrypto": SourceRecord(
        key="tcgcrypto",
        url="https://consider.com/boards/vc/tcg-crypto/companies",
        provider_id="consider",
        raw_metadata={"board": "tcg-crypto"},
    ),
    "longgame": SourceRecord(
        key="longgame",
        url="https://consider.com/boards/vc/longgame/companies",
        provider_id="consider",
        raw_metadata={"board": "longgame"},
    ),
    "baincrypto": SourceRecord(
        key="baincrypto",
        url="https://consider.com/boards/vc/bain-crypto/companies",
        provider_id="consider",
        raw_metadata={"board": "bain-crypto"},
    ),
}
SOURCE_RECORDS: tuple[SourceRecord, ...] = tuple(CONSIDER_SOURCE_CATALOG.values())


class ConsiderSourceAdapter:
    provider_id = "consider"
    provider_label = "Consider"
    provider_description = "Aggregate Consider source adapter that discovers company boards and provider hints."

    def __init__(self, settings: OpenOppsSettings, board: str | None = None):
        from openopps.providers.registry import provider_registry

        self.settings = settings
        self.board = board
        self.registry = provider_registry(settings=settings)
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
            website_url = normalize_public_website_url(
                company.website.url if company.website else None
            )
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


SOUTHPARKCOMMONSVC_SOURCE = SourceRecord(
    key="southparkcommonsvc",
    url="https://consider.com/boards/vc/south-park-commons/companies",
    provider_id="consider",
    raw_metadata={"board": "southparkcommonsvc"},
)


LCATTERTONVC_SOURCE = SourceRecord(
    key="lcattertonvc",
    url="https://consider.com/boards/vc/l-catterton/companies",
    provider_id="consider",
    raw_metadata={"board": "lcattertonvc"},
)


EVPVC_SOURCE = SourceRecord(
    key="evpvc",
    url="https://consider.com/boards/vc/evp/companies",
    provider_id="consider",
    raw_metadata={"board": "evpvc"},
)


class ConsiderA16zSourceAdapter(ConsiderSourceAdapter):
    provider_id = "consider_a16z"
    provider_label = "Consider/a16z"
    provider_description = (
        "Aggregate a16z source adapter that discovers boards and provider hints."
    )


INDIEBIO_SOURCE = SourceRecord(
    key="indiebio",
    url="https://indiebio.board.staging.consider.com/companies",
    provider_id="consider",
    raw_metadata={"board": "indiebio"},
)

VISTRIA_SOURCE = SourceRecord(
    key="vistria",
    url="https://consider.com/boards/vc/vistria/companies",
    provider_id="consider",
    raw_metadata={"board": "vistria"},
)

VALTRUIS_SOURCE = SourceRecord(
    key="valtruis",
    url="https://careers.valtruis.com/companies",
    provider_id="consider",
    raw_metadata={"board": "valtruis"},
)

GET2KNOWNOKE_SOURCE = SourceRecord(
    key="get2knownoke",
    url="https://jobs.get2knownoke.com/companies",
    provider_id="consider",
    raw_metadata={"board": "get2knownoke"},
)


WHITEBOARDADVISORS_SOURCE = SourceRecord(
    key="whiteboardadvisors",
    url="https://jobs.whiteboardadvisors.com/companies",
    provider_id="consider",
    raw_metadata={"board": "whiteboardadvisors"},
)


FIRSTROUNDCAPITAL_SOURCE = SourceRecord(
    key="firstroundcapital",
    url="https://consider.com/boards/vc/first-round-capital/companies",
    provider_id="consider",
    raw_metadata={"board": "firstroundcapital"},
)


IMPACTSOURCE_SOURCE = SourceRecord(
    key="impactsource",
    url="https://www.impactsource.ai/jobs",
    provider_id="consider",
    raw_metadata={"board": "impactsource"},
)


PROSPECT_SOURCE = SourceRecord(
    key="prospect",
    url="https://consider.com/boards/vc/prospect/companies",
    provider_id="consider",
    raw_metadata={"board": "prospect"},
)


RIVERSIDE_SOURCE = SourceRecord(
    key="riverside",
    url="https://consider.com/boards/vc/riverside/companies",
    provider_id="consider",
    raw_metadata={"board": "riverside"},
)


OWLVC_SOURCE = SourceRecord(
    key="owlvc",
    url="https://careers.owlvc.com/companies",
    provider_id="consider",
    raw_metadata={"board": "owlvc"},
)


EDBI_SOURCE = SourceRecord(
    key="edbi",
    url="https://consider.com/boards/vc/edbi/companies",
    provider_id="consider",
    raw_metadata={"board": "edbi"},
)


MUUS_SOURCE = SourceRecord(
    key="muus",
    url="https://consider.com/boards/vc/muus/companies",
    provider_id="consider",
    raw_metadata={"board": "muus"},
)


ANTHOSCAPITAL_SOURCE = SourceRecord(
    key="anthoscapital",
    url="https://consider.com/boards/vc/anthos-capital/companies",
    provider_id="consider",
    raw_metadata={"board": "anthoscapital"},
)


PROPTECH1_SOURCE = SourceRecord(
    key="proptech1",
    url="https://consider.com/boards/vc/proptech1/companies",
    provider_id="consider",
    raw_metadata={"board": "proptech1"},
)


JVPVC_SOURCE = SourceRecord(
    key="jvpvc",
    url="https://jobs.jvpvc.com/companies",
    provider_id="consider",
    raw_metadata={"board": "jvpvc"},
)


PSL_SOURCE = SourceRecord(
    key="psl",
    url="https://jobs.psl.com/companies",
    provider_id="consider",
    raw_metadata={"board": "psl"},
)

HAX_SOURCE = SourceRecord(
    key="hax",
    url="https://jobs.hax.co/companies",
    provider_id="consider",
    raw_metadata={"board": "hax"},
)


LOCALGLOBEALL_SOURCE = SourceRecord(
    key="localglobeall",
    url="https://consider.com/boards/vc/localglobe-all/companies",
    provider_id="consider",
    raw_metadata={"board": "localglobeall"},
)


CHIRATAEVC_SOURCE = SourceRecord(
    key="chirataevc",
    url="https://careers.chiratae.com/companies",
    provider_id="consider",
    raw_metadata={"board": "chirataevc"},
)


DUTCHTECH_SOURCE = SourceRecord(
    key="dutchtech",
    url="https://consider.com/boards/vc/dutchtech/companies",
    provider_id="consider",
    raw_metadata={"board": "dutchtech"},
)


MITALUMNISTARTUPS_SOURCE = SourceRecord(
    key="mitalumnistartups",
    url="https://consider.com/boards/vc/mit-alumni-startups/companies",
    provider_id="consider",
    raw_metadata={"board": "mitalumnistartups"},
)

BAINPE_SOURCE = SourceRecord(
    key="bainpe",
    url="https://consider.com/boards/vc/bain-pe/companies",
    provider_id="consider",
    raw_metadata={"board": "bainpe"},
)


COLLERCAPITAL_SOURCE = SourceRecord(
    key="collercapital",
    url="https://consider.com/boards/vc/coller-capital/companies",
    provider_id="consider",
    raw_metadata={"board": "collercapital"},
)

HIGHLANDEUROPE_SOURCE = SourceRecord(
    key="highlandeurope",
    url="https://careers.highlandeurope.com/companies",
    provider_id="consider",
    raw_metadata={"board": "highlandeurope"},
)


MOC_SOURCE = SourceRecord(
    key="moc",
    url="https://jobs.moc.vc/companies",
    provider_id="consider",
    raw_metadata={"board": "moc"},
)


AIRBUSVENTURES_SOURCE = SourceRecord(
    key="airbusventures",
    url="https://consider.com/boards/vc/airbus-ventures/companies",
    provider_id="consider",
    raw_metadata={"board": "airbusventures"},
)


NIGHTCREATOR_SOURCE = SourceRecord(
    key="nightcreator",
    url="https://consider.com/boards/vc/night-creator/companies",
    provider_id="consider",
    raw_metadata={"board": "nightcreator"},
)


VOYAGERVC_SOURCE = SourceRecord(
    key="voyagervc",
    url="https://careers.voyagervc.com/companies",
    provider_id="consider",
    raw_metadata={"board": "voyagervc"},
)


CLIMACTIC_SOURCE = SourceRecord(
    key="climactic",
    url="https://jobs.climactic.vc/companies",
    provider_id="consider",
    raw_metadata={"board": "climactic"},
)

CONSIDER_SOURCE = SourceRecord(
    key="consider",
    url="https://consider.com/boards/vc/consider/companies",
    provider_id="consider",
    raw_metadata={"board": "consider"},
)
