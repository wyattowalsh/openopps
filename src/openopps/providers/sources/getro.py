from __future__ import annotations

import json
import math
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx

from openopps.http import retrying_json_request
from openopps.models import (
    BoardProviderRecord,
    BoardRecord,
    GetroCompaniesResponse,
    GetroCompany,
    SourceRecord,
    normalize_public_website_url,
    utc_now,
    validate_public_https_url,
)
from openopps.settings import OpenOppsSettings
from openopps.utils import slugify, source_board_key

_COLLECTION_RE = re.compile(r'"id":"(?P<id>\d+)".{0,120}?"label":"(?P<label>[^"]+)"')
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(?P<data>.*?)</script>'
)


GETRO_SOURCE_CATALOG = {
    "accel": SourceRecord(
        key="accel",
        url="https://jobs.accel.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8672"},
    ),
    "8vc": SourceRecord(
        key="8vc",
        url="https://jobs.8vc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1005"},
    ),
    "1011vc": SourceRecord(
        key="1011vc",
        url="https://jobs.1011vc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1488"},
    ),
    "airtree": SourceRecord(
        key="airtree",
        url="https://jobs.airtree.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7418"},
    ),
    "alleycorp": SourceRecord(
        key="alleycorp",
        url="https://jobs.alleycorp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "636"},
    ),
    "antler": SourceRecord(
        key="antler",
        url="https://careers.antler.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7715"},
    ),
    "645ventures": SourceRecord(
        key="645ventures",
        url="https://jobs.645ventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1621"},
    ),
    "atomico": SourceRecord(
        key="atomico",
        url="https://careers.atomico.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "36986"},
    ),
    "blackbird": SourceRecord(
        key="blackbird",
        url="https://jobs.blackbird.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "219"},
    ),
    "bbgventures": SourceRecord(
        key="bbgventures",
        url="https://jobs.bbgventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "766"},
    ),
    "blumbergcapital": SourceRecord(
        key="blumbergcapital",
        url="https://careers.blumbergcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "34577"},
    ),
    "blockchaincapital": SourceRecord(
        key="blockchaincapital",
        url="https://jobs.blockchaincapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "815"},
    ),
    "bonfirevc": SourceRecord(
        key="bonfirevc",
        url="https://jobs.bonfirevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "790"},
    ),
    "btv": SourceRecord(
        key="btv",
        url="https://jobs.btv.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1637"},
    ),
    "canaan": SourceRecord(
        key="canaan",
        url="https://careers.canaan.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1419"},
    ),
    "climatedraft": SourceRecord(
        key="climatedraft",
        url="https://jobs.climatedraft.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "994"},
    ),
    "bcapital": SourceRecord(
        key="bcapital",
        url="https://jobs.b.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "515"},
    ),
    "dcg": SourceRecord(
        key="dcg",
        url="https://jobs.dcg.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "116"},
    ),
    "craftventures": SourceRecord(
        key="craftventures",
        url="https://jobs.craftventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "340"},
    ),
    "dcvc": SourceRecord(
        key="dcvc",
        url="https://jobs.dcvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "514"},
    ),
    "designerfund": SourceRecord(
        key="designerfund",
        url="https://jobs.designerfund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11511"},
    ),
    "drivecapital": SourceRecord(
        key="drivecapital",
        url="https://jobs.drivecapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "158"},
    ),
    "eclipse": SourceRecord(
        key="eclipse",
        url="https://jobs.eclipse.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "348"},
    ),
    "everywhere": SourceRecord(
        key="everywhere",
        url="https://jobs.everywhere.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "625"},
    ),
    "earlybird": SourceRecord(
        key="earlybird",
        url="https://jobs.earlybird.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "617"},
    ),
    "firstmark": SourceRecord(
        key="firstmark",
        url="https://jobs.firstmark.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "45303"},
    ),
    "femalefoundersfund": SourceRecord(
        key="femalefoundersfund",
        url="https://jobs.femalefoundersfund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "183"},
    ),
    "flarecapital": SourceRecord(
        key="flarecapital",
        url="https://careers.flarecapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9366"},
    ),
    "foundationcapital": SourceRecord(
        key="foundationcapital",
        url="https://jobs.foundationcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "941"},
    ),
    "foundry": SourceRecord(
        key="foundry",
        url="https://jobs.foundry.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "25"},
    ),
    "freestyle": SourceRecord(
        key="freestyle",
        url="https://jobs.freestyle.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "108"},
    ),
    "fprimecapital": SourceRecord(
        key="fprimecapital",
        url="https://jobs.fprimecapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "258"},
    ),
    "hvcapital": SourceRecord(
        key="hvcapital",
        url="https://hv.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "234"},
    ),
    "greycroft": SourceRecord(
        key="greycroft",
        url="https://jobs.greycroft.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "616"},
    ),
    "indexventures": SourceRecord(
        key="indexventures",
        url="https://indexventures.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1629"},
    ),
    "joinef": SourceRecord(
        key="joinef",
        url="https://portfolio.joinef.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "228"},
    ),
    "kaporcapital": SourceRecord(
        key="kaporcapital",
        url="https://jobs.kaporcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "224"},
    ),
    "inovia": SourceRecord(
        key="inovia",
        url="https://careers.inovia.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1201"},
    ),
    "inspiredcapital": SourceRecord(
        key="inspiredcapital",
        url="https://jobs.inspiredcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "935"},
    ),
    "khoslaventures": SourceRecord(
        key="khoslaventures",
        url="https://jobs.khoslaventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "257"},
    ),
    "kindredcapital": SourceRecord(
        key="kindredcapital",
        url="https://jobs.kindredcapital.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "221"},
    ),
    "lowercarbon": SourceRecord(
        key="lowercarbon",
        url="https://lowercarbon.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "801"},
    ),
    "lererhippeau": SourceRecord(
        key="lererhippeau",
        url="https://jobs.lererhippeau.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "120"},
    ),
    "leftlanecap": SourceRecord(
        key="leftlanecap",
        url="https://jobs.leftlanecap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "789"},
    ),
    "insightpartners": SourceRecord(
        key="insightpartners",
        url="https://jobs.insightpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "246"},
    ),
    "luxcapital": SourceRecord(
        key="luxcapital",
        url="https://jobs.luxcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "103"},
    ),
    "madrona": SourceRecord(
        key="madrona",
        url="https://jobs.madrona.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "151"},
    ),
    "m13": SourceRecord(
        key="m13",
        url="https://jobs.m13.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "318"},
    ),
    "mayfield": SourceRecord(
        key="mayfield",
        url="https://mayfield.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "245"},
    ),
    "mcj": SourceRecord(
        key="mcj",
        url="https://jobs.mcj.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1775"},
    ),
    "menlovc": SourceRecord(
        key="menlovc",
        url="https://jobs.menlovc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "767"},
    ),
    "metaprop": SourceRecord(
        key="metaprop",
        url="https://jobs.metaprop.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "177"},
    ),
    "multicoin": SourceRecord(
        key="multicoin",
        url="https://jobs.multicoin.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "390"},
    ),
    "nfx": SourceRecord(
        key="nfx",
        url="https://jobs.nfx.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "307"},
    ),
    "northzone": SourceRecord(
        key="northzone",
        url="https://portfolio.northzone.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3791"},
    ),
    "notablecap": SourceRecord(
        key="notablecap",
        url="https://jobs.notablecap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "764"},
    ),
    "nyca": SourceRecord(
        key="nyca",
        url="https://jobs.nyca.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "681"},
    ),
    "oakhcft": SourceRecord(
        key="oakhcft",
        url="https://jobs.oakhcft.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "637"},
    ),
    "pointnine": SourceRecord(
        key="pointnine",
        url="https://jobs.pointnine.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1680"},
    ),
    "primary": SourceRecord(
        key="primary",
        url="https://jobs.primary.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1124"},
    ),
    "redpoint": SourceRecord(
        key="redpoint",
        url="https://careers.redpoint.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "189"},
    ),
    "reachcapital": SourceRecord(
        key="reachcapital",
        url="https://jobs.reachcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "685"},
    ),
    "rre": SourceRecord(
        key="rre",
        url="https://jobs.rre.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "114"},
    ),
    "pnptc": SourceRecord(
        key="pnptc",
        url="https://jobs.pnptc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "250"},
    ),
    "saasventurecapital": SourceRecord(
        key="saasventurecapital",
        url="https://careers.saasventurecapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "929"},
    ),
    "signalfire": SourceRecord(
        key="signalfire",
        url="https://jobs.signalfire.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "135"},
    ),
    "sapphireventures": SourceRecord(
        key="sapphireventures",
        url="https://jobs.sapphireventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "199"},
    ),
    "scalevp": SourceRecord(
        key="scalevp",
        url="https://jobs.scalevp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "776"},
    ),
    "seedcamp": SourceRecord(
        key="seedcamp",
        url="https://talent.seedcamp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4186"},
    ),
    "speedinvest": SourceRecord(
        key="speedinvest",
        url="https://careers.speedinvest.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "947"},
    ),
    "squarepeg": SourceRecord(
        key="squarepeg",
        url="https://squarepeg.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "243"},
    ),
    "stage2capital": SourceRecord(
        key="stage2capital",
        url="https://careers.stage2.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1112"},
    ),
    "summitpartners": SourceRecord(
        key="summitpartners",
        url="https://jobs.summitpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "36623"},
    ),
    "teamworthy": SourceRecord(
        key="teamworthy",
        url="https://teamworthy.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "639"},
    ),
    "susaventures": SourceRecord(
        key="susaventures",
        url="https://jobs.susaventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "386"},
    ),
    "thrivecap": SourceRecord(
        key="thrivecap",
        url="https://jobs.thrivecap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2105"},
    ),
    "technyc": SourceRecord(
        key="technyc",
        url="https://jobs.technyc.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1543"},
    ),
    "techstars": SourceRecord(
        key="techstars",
        url="https://jobs.techstars.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "89"},
    ),
    "trueventures": SourceRecord(
        key="trueventures",
        url="https://jobs.trueventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "646"},
    ),
    "uncorkcapital": SourceRecord(
        key="uncorkcapital",
        url="https://jobs.uncorkcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "247"},
    ),
    "venrock": SourceRecord(
        key="venrock",
        url="https://jobs.venrock.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "319"},
    ),
    "wing": SourceRecord(
        key="wing",
        url="https://careers.wing.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "43520"},
    ),
    "acme": SourceRecord(
        key="acme",
        url="https://jobs.acme.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "477"},
    ),
    "2150": SourceRecord(
        key="2150",
        url="https://jobs.2150.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1287"},
    ),
    "avp": SourceRecord(
        key="avp",
        url="https://jobs.avp.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1673"},
    ),
    "base10": SourceRecord(
        key="base10",
        url="https://careers.base10.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1207"},
    ),
    "buildingventures": SourceRecord(
        key="buildingventures",
        url="https://jobs.buildingventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1420"},
    ),
    "cherry": SourceRecord(
        key="cherry",
        url="https://talent.cherry.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "44081"},
    ),
    "citylight": SourceRecord(
        key="citylight",
        url="https://jobs.citylight.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9796"},
    ),
    "convectivecapital": SourceRecord(
        key="convectivecapital",
        url="https://jobs.convectivecapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1732"},
    ),
    "cventures": SourceRecord(
        key="cventures",
        url="https://jobs.cventures.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9365"},
    ),
    "digitalfuelcapital": SourceRecord(
        key="digitalfuelcapital",
        url="https://careers.digitalfuelcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6758"},
    ),
    "edisonpartners": SourceRecord(
        key="edisonpartners",
        url="https://jobs.edisonpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "148"},
    ),
    "fyrfly": SourceRecord(
        key="fyrfly",
        url="https://careers.fyrfly.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6461"},
    ),
    "galaxy": SourceRecord(
        key="galaxy",
        url="https://venturecareers.galaxy.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9134"},
    ),
    "garuda": SourceRecord(
        key="garuda",
        url="https://jobs.garuda.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3590"},
    ),
    "headline": SourceRecord(
        key="headline",
        url="https://talent.headline.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3293"},
    ),
    "hellokoru": SourceRecord(
        key="hellokoru",
        url="https://careers.hellokoru.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11675"},
    ),
    "hivemind": SourceRecord(
        key="hivemind",
        url="https://jobs.hivemind.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1298"},
    ),
    "loeb": SourceRecord(
        key="loeb",
        url="https://jobs.loeb.nyc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1427"},
    ),
    "longjourney": SourceRecord(
        key="longjourney",
        url="https://jobs.longjourney.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8279"},
    ),
    "lool": SourceRecord(
        key="lool",
        url="https://opportunities.lool.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "309"},
    ),
    "mannatreepartners": SourceRecord(
        key="mannatreepartners",
        url="https://careers.mannatreepartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1444"},
    ),
    "meridianstreetcapital": SourceRecord(
        key="meridianstreetcapital",
        url="https://careers.meridianstreetcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1501"},
    ),
    "moderneventures": SourceRecord(
        key="moderneventures",
        url="https://portfoliocareers.moderneventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13293"},
    ),
    "munichreventures": SourceRecord(
        key="munichreventures",
        url="https://portfoliojobs.munichreventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1182"},
    ),
    "newmarketsvp": SourceRecord(
        key="newmarketsvp",
        url="https://jobs.newmarketsvp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3260"},
    ),
    "norrsken": SourceRecord(
        key="norrsken",
        url="https://jobs.norrsken.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4217"},
    ),
    "octopusventures": SourceRecord(
        key="octopusventures",
        url="https://talent.octopusventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4580"},
    ),
    "openocean": SourceRecord(
        key="openocean",
        url="https://jobs.openocean.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13919"},
    ),
    "partechpartners": SourceRecord(
        key="partechpartners",
        url="https://portfoliojobs.partechpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10421"},
    ),
    "pelionvp": SourceRecord(
        key="pelionvp",
        url="https://jobs.pelionvp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1631"},
    ),
    "playvc": SourceRecord(
        key="playvc",
        url="https://careers.play.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1624"},
    ),
    "preludeventures": SourceRecord(
        key="preludeventures",
        url="https://jobs.preludeventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "638"},
    ),
    "rev1ventures": SourceRecord(
        key="rev1ventures",
        url="https://jobs.rev1ventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "405"},
    ),
    "toyotaventures": SourceRecord(
        key="toyotaventures",
        url="https://jobs.toyota.ventures/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "205"},
    ),
    "breakthroughenergy": SourceRecord(
        key="breakthroughenergy",
        url="https://bevjobs.breakthroughenergy.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1533"},
    ),
    "cervinventures": SourceRecord(
        key="cervinventures",
        url="https://jobs.cervinventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7385"},
    ),
    "definevc": SourceRecord(
        key="definevc",
        url="https://careers.definevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1019"},
    ),
    "fintech": SourceRecord(
        key="fintech",
        url="https://jobs.fintech.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1590"},
    ),
    "firstminute": SourceRecord(
        key="firstminute",
        url="https://jobs.firstminute.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "178"},
    ),
    "frameworkventures": SourceRecord(
        key="frameworkventures",
        url="https://jobs.framework.ventures/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1127"},
    ),
    "georgian": SourceRecord(
        key="georgian",
        url="https://careers.georgian.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "14282"},
    ),
    "jumpcap": SourceRecord(
        key="jumpcap",
        url="https://jobs.jumpcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "951"},
    ),
    "mavenventures": SourceRecord(
        key="mavenventures",
        url="https://careers.mavenventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1678"},
    ),
    "omegavp": SourceRecord(
        key="omegavp",
        url="https://jobs.omegavp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1343"},
    ),
    "ret": SourceRecord(
        key="ret",
        url="https://jobs.ret.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "216"},
    ),
    "rho": SourceRecord(
        key="rho",
        url="https://jobs.rho.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1033"},
    ),
    "somacap": SourceRecord(
        key="somacap",
        url="https://jobs.somacap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3194"},
    ),
    "tcv": SourceRecord(
        key="tcv",
        url="https://portfoliojobs.tcv.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6428"},
    ),
    "thirdpointventures": SourceRecord(
        key="thirdpointventures",
        url="https://jobs.thirdpointventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1592"},
    ),
    "vestigoventures": SourceRecord(
        key="vestigoventures",
        url="https://jobs.vestigoventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "953"},
    ),
    "acurio": SourceRecord(
        key="acurio",
        url="https://acurio.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1169"},
    ),
    "angelesinvestors": SourceRecord(
        key="angelesinvestors",
        url="https://careers.angelesinvestors.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7748"},
    ),
    "banktechventures": SourceRecord(
        key="banktechventures",
        url="https://careers.banktechventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11477"},
    ),
    "canapi": SourceRecord(
        key="canapi",
        url="https://careers.canapi.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1000"},
    ),
    "collidecap": SourceRecord(
        key="collidecap",
        url="https://jobs.collidecap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2766"},
    ),
    "cornerstonevc": SourceRecord(
        key="cornerstonevc",
        url="https://careers.cornerstonevc.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1737"},
    ),
    "elevateventures": SourceRecord(
        key="elevateventures",
        url="https://jobs.elevateventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11444"},
    ),
    "energizecap": SourceRecord(
        key="energizecap",
        url="https://jobs.energizecap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1212"},
    ),
    "flourishventures": SourceRecord(
        key="flourishventures",
        url="https://jobs.flourishventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "249"},
    ),
    "globalvc": SourceRecord(
        key="globalvc",
        url="https://jobs.global.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12434"},
    ),
    "gsv": SourceRecord(
        key="gsv",
        url="https://gsv.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "777"},
    ),
    "hgventures": SourceRecord(
        key="hgventures",
        url="https://portcojobs.hgventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1500"},
    ),
    "hyperplane": SourceRecord(
        key="hyperplane",
        url="https://careers.hyperplane.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "35402"},
    ),
    "imaginary": SourceRecord(
        key="imaginary",
        url="https://imaginary.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "923"},
    ),
    "kingriver": SourceRecord(
        key="kingriver",
        url="https://jobs.kingriver.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3558"},
    ),
    "lightbank": SourceRecord(
        key="lightbank",
        url="https://jobs.lightbank.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10322"},
    ),
    "motion": SourceRecord(
        key="motion",
        url="https://jobs.motion.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11807"},
    ),
    "polychain": SourceRecord(
        key="polychain",
        url="https://jobs.polychain.capital/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "203"},
    ),
    "racap": SourceRecord(
        key="racap",
        url="https://open-positions.racap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "45599"},
    ),
    "realventures": SourceRecord(
        key="realventures",
        url="https://jobs.realventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "166"},
    ),
    "sarahsmith": SourceRecord(
        key="sarahsmith",
        url="https://jobs.sarahsmith.fund/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10817"},
    ),
    "seventures": SourceRecord(
        key="seventures",
        url="https://seventures.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7583"},
    ),
    "springtimeventures": SourceRecord(
        key="springtimeventures",
        url="https://careers.springtimeventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1437"},
    ),
    "uluventures": SourceRecord(
        key="uluventures",
        url="https://jobs.uluventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11411"},
    ),
    "venturestudios": SourceRecord(
        key="venturestudios",
        url="https://jobsatventurestudios.com/discover/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13820"},
    ),
    "variant": SourceRecord(
        key="variant",
        url="https://jobs.variant.fund/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1508"},
    ),
    "25madison": SourceRecord(
        key="25madison",
        url="https://jobs.25madison.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1171"},
    ),
    "archetype": SourceRecord(
        key="archetype",
        url="https://jobs.archetype.fund/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2765"},
    ),
    "backed": SourceRecord(
        key="backed",
        url="https://talent.backed.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4350"},
    ),
    "breakout": SourceRecord(
        key="breakout",
        url="https://jobs.breakout.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1516"},
    ),
    "capitalfactory": SourceRecord(
        key="capitalfactory",
        url="https://jobs.capitalfactory.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "719"},
    ),
    "correlationvc": SourceRecord(
        key="correlationvc",
        url="https://jobs.correlationvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "107"},
    ),
    "detroitvc": SourceRecord(
        key="detroitvc",
        url="https://jobs.detroit.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "308"},
    ),
    "g2vp": SourceRecord(
        key="g2vp",
        url="https://jobs.g2vp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "787"},
    ),
    "humbaventures": SourceRecord(
        key="humbaventures",
        url="https://jobs.humbaventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11642"},
    ),
    "macventurecapital": SourceRecord(
        key="macventurecapital",
        url="https://jobs.macventurecapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1449"},
    ),
    "marvinvc": SourceRecord(
        key="marvinvc",
        url="https://jobs.marvinvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10950"},
    ),
    "moxxie": SourceRecord(
        key="moxxie",
        url="https://careers.moxxie.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1168"},
    ),
    "originventures": SourceRecord(
        key="originventures",
        url="https://jobs.originventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13589"},
    ),
    "powerhouseventures": SourceRecord(
        key="powerhouseventures",
        url="https://careers.powerhouse-ventures.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "952"},
    ),
    "radical": SourceRecord(
        key="radical",
        url="https://radical.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "816"},
    ),
    "rallyventures": SourceRecord(
        key="rallyventures",
        url="https://jobs.rallyventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1613"},
    ),
    "squadra": SourceRecord(
        key="squadra",
        url="https://talent.squadra.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4778"},
    ),
    "theoryvc": SourceRecord(
        key="theoryvc",
        url="https://jobs.theoryvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "29066"},
    ),
    "tribecavp": SourceRecord(
        key="tribecavp",
        url="https://jobs.tribecavp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "101"},
    ),
    "trinityventures": SourceRecord(
        key="trinityventures",
        url="https://jobs.trinityventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "393"},
    ),
    "tusk": SourceRecord(
        key="tusk",
        url="https://jobs.tusk.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "261"},
    ),
    "underscore": SourceRecord(
        key="underscore",
        url="https://jobs.underscore.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "864"},
    ),
    "upwest": SourceRecord(
        key="upwest",
        url="https://jobs.upwest.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "298"},
    ),
    "volitioncapital": SourceRecord(
        key="volitioncapital",
        url="https://jobs.volitioncapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "786"},
    ),
    "xyz": SourceRecord(
        key="xyz",
        url="https://jobs.xyz.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13359"},
    ),
    "53stations": SourceRecord(
        key="53stations",
        url="https://jobs.53stations.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "45269"},
    ),
    "acp": SourceRecord(
        key="acp",
        url="https://jobs.acp.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1339"},
    ),
    "activate": SourceRecord(
        key="activate",
        url="https://jobs.activate.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "937"},
    ),
    "b2venture": SourceRecord(
        key="b2venture",
        url="https://jobs.b2venture.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4283"},
    ),
    "becocapital": SourceRecord(
        key="becocapital",
        url="https://careers.becocapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10883"},
    ),
    "benchstrengthvc": SourceRecord(
        key="benchstrengthvc",
        url="https://jobs.benchstrengthvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12600"},
    ),
    "brightspark": SourceRecord(
        key="brightspark",
        url="https://careers.brightspark.com/",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1436"},
    ),
    "cmont": SourceRecord(
        key="cmont",
        url="https://careers.cmont.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12698"},
    ),
    "communitech": SourceRecord(
        key="communitech",
        url="https://www1.communitech.ca/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "628"},
    ),
    "comcastventures": SourceRecord(
        key="comcastventures",
        url="https://portfoliojobs.comcastventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "256"},
    ),
    "dawncapital": SourceRecord(
        key="dawncapital",
        url="https://jobs.dawncapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3063"},
    ),
    "deepscienceventures": SourceRecord(
        key="deepscienceventures",
        url="https://jobs.deepscienceventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1630"},
    ),
    "diagram": SourceRecord(
        key="diagram",
        url="https://careers.diagram.ca/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1084"},
    ),
    "eniac": SourceRecord(
        key="eniac",
        url="https://jobs.eniac.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "117"},
    ),
    "israelvcforum": SourceRecord(
        key="israelvcforum",
        url="https://israelvcforum.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10949"},
    ),
    "investottawa": SourceRecord(
        key="investottawa",
        url="https://techjobfinder.investottawa.ca/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1546"},
    ),
    "jamjarinvestments": SourceRecord(
        key="jamjarinvestments",
        url="https://jobs.jamjarinvestments.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12863"},
    ),
    "ngpcap": SourceRecord(
        key="ngpcap",
        url="https://jobs.ngpcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3426"},
    ),
    "planeta": SourceRecord(
        key="planeta",
        url="https://jobs.planet-a.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1426"},
    ),
    "queertech": SourceRecord(
        key="queertech",
        url="https://queertech.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "883"},
    ),
    "qumracapital": SourceRecord(
        key="qumracapital",
        url="https://jobs.qumracapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "474"},
    ),
    "redseaventures": SourceRecord(
        key="redseaventures",
        url="https://jobs.redseaventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "78"},
    ),
    "stripes": SourceRecord(
        key="stripes",
        url="https://jobs.stripes.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "167"},
    ),
    "ffwd": SourceRecord(
        key="ffwd",
        url="https://jobs.ffwd.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "997"},
    ),
    "annarborusa": SourceRecord(
        key="annarborusa",
        url="https://jobs.annarborusa.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "29331"},
    ),
    "thisiscny": SourceRecord(
        key="thisiscny",
        url="https://careers.thisiscny.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "392"},
    ),
    "investedinthemission": SourceRecord(
        key="investedinthemission",
        url="https://careers.investedinthemission.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8540"},
    ),
    "revolution": SourceRecord(
        key="revolution",
        url="https://jobs.revolution.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "143"},
    ),
    "protocolai": SourceRecord(
        key="protocolai",
        url="https://jobs.protocol.ai/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1336"},
    ),
    "climatejobs": SourceRecord(
        key="climatejobs",
        url="https://climatejobs.shortlist.net/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6857"},
    ),
    "elementalimpact": SourceRecord(
        key="elementalimpact",
        url="https://jobs.elementalimpact.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "624"},
    ),
    "ta": SourceRecord(
        key="ta",
        url="https://careers.ta.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4415"},
    ),
    "launchtn": SourceRecord(
        key="launchtn",
        url="https://jobs.launchtn.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "260"},
    ),
    "emcap": SourceRecord(
        key="emcap",
        url="https://talent.emcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "164"},
    ),
    "energyimpactpartners": SourceRecord(
        key="energyimpactpartners",
        url="https://jobs.energyimpactpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "253"},
    ),
    "astanor": SourceRecord(
        key="astanor",
        url="https://jobs.astanor.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8243"},
    ),
    "anitab": SourceRecord(
        key="anitab",
        url="https://jobs.anitab.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10323"},
    ),
    "motivatevc": SourceRecord(
        key="motivatevc",
        url="https://jobs.motivate.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1021"},
    ),
    "collaborativefund": SourceRecord(
        key="collaborativefund",
        url="https://collaborative-fund.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "97"},
    ),
    "cyberfund": SourceRecord(
        key="cyberfund",
        url="https://talent.cyber.fund/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9035"},
    ),
    "crosscutvc": SourceRecord(
        key="crosscutvc",
        url="https://careers.crosscut.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "948"},
    ),
    "humanvc": SourceRecord(
        key="humanvc",
        url="https://jobs.human.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "769"},
    ),
    "bettervc": SourceRecord(
        key="bettervc",
        url="https://jobs.better.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1370"},
    ),
    "blackjaysvc": SourceRecord(
        key="blackjaysvc",
        url="https://jobs.blackjays.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1164"},
    ),
    "thewia": SourceRecord(
        key="thewia",
        url="https://jobs.thewia.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "106"},
    ),
    "stanfordclimateventures": SourceRecord(
        key="stanfordclimateventures",
        url="https://jobs.stanfordclimateventures.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9729"},
    ),
    "fusevc": SourceRecord(
        key="fusevc",
        url="https://careers.fuse.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1337"},
    ),
    "emergecapital": SourceRecord(
        key="emergecapital",
        url="https://careers.emergecapital.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4514"},
    ),
    "climateinvestment": SourceRecord(
        key="climateinvestment",
        url="https://jobs.climateinvestment.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8639"},
    ),
    "fil": SourceRecord(
        key="fil",
        url="https://careers.fil.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1486"},
    ),
    "tacostars": SourceRecord(
        key="tacostars",
        url="https://talent.tacostars.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1597"},
    ),
    "femtechinsider": SourceRecord(
        key="femtechinsider",
        url="https://jobs.femtechinsider.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "14612"},
    ),
    "gd1": SourceRecord(
        key="gd1",
        url="https://careers.gd1.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1676"},
    ),
    "greenfieldgrowth": SourceRecord(
        key="greenfieldgrowth",
        url="https://careers.greenfield-growth.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1534"},
    ),
    "rubio": SourceRecord(
        key="rubio",
        url="https://rubio.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1354"},
    ),
    "cleanenergyventures": SourceRecord(
        key="cleanenergyventures",
        url="https://jobs.cleanenergyventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1198"},
    ),
    "circadianvc": SourceRecord(
        key="circadianvc",
        url="https://jobs.circadian.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1181"},
    ),
    "unreasonablegroup": SourceRecord(
        key="unreasonablegroup",
        url="https://jobs.unreasonablegroup.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1254"},
    ),
    "medtechinnovator": SourceRecord(
        key="medtechinnovator",
        url="https://jobs.medtechinnovator.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12236"},
    ),
    "leadedge": SourceRecord(
        key="leadedge",
        url="https://jobs.leadedge.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1076"},
    ),
    "franciscopartners": SourceRecord(
        key="franciscopartners",
        url="https://careers.franciscopartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1442"},
    ),
    "breakthroughenergyfellows": SourceRecord(
        key="breakthroughenergyfellows",
        url="https://befjobs.breakthroughenergy.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2567"},
    ),
    "riverparkvc": SourceRecord(
        key="riverparkvc",
        url="https://jobs.riverparkvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1429"},
    ),
    "thirdsphere": SourceRecord(
        key="thirdsphere",
        url="https://jobs.thirdsphere.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "862"},
    ),
    "massmutualventures": SourceRecord(
        key="massmutualventures",
        url="https://jobs.massmutualventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "813"},
    ),
    "pilabs": SourceRecord(
        key="pilabs",
        url="https://jobs.pilabs.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2666"},
    ),
    "s3vc": SourceRecord(
        key="s3vc",
        url="https://jobs.s3vc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "684"},
    ),
    "mevp": SourceRecord(
        key="mevp",
        url="https://jobs.mevp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1034"},
    ),
    "westboundequity": SourceRecord(
        key="westboundequity",
        url="https://jobs.westboundequity.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1007"},
    ),
    "canvasvc": SourceRecord(
        key="canvasvc",
        url="https://jobs.canvas.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "34379"},
    ),
    "industriousvc": SourceRecord(
        key="industriousvc",
        url="https://jobs.industrious.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "33917"},
    ),
    "bluebearcap": SourceRecord(
        key="bluebearcap",
        url="https://jobs.bluebearcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "645"},
    ),
    "shieldcap": SourceRecord(
        key="shieldcap",
        url="https://portfoliocareers.shieldcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7517"},
    ),
    "purdueinnovates": SourceRecord(
        key="purdueinnovates",
        url="https://purdueinnovates.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8045"},
    ),
    "claltech": SourceRecord(
        key="claltech",
        url="https://careers.claltech.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1128"},
    ),
    "type1ventures": SourceRecord(
        key="type1ventures",
        url="https://jobs.type1ventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3393"},
    ),
    "xista": SourceRecord(
        key="xista",
        url="https://careers.xista.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1353"},
    ),
    "tenexcm": SourceRecord(
        key="tenexcm",
        url="https://tenexcm.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8805"},
    ),
    "ascendvc": SourceRecord(
        key="ascendvc",
        url="https://jobs.ascend.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "14876"},
    ),
    "vertexventureshc": SourceRecord(
        key="vertexventureshc",
        url="https://jobs.vertexventureshc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9563"},
    ),
    "perotjain": SourceRecord(
        key="perotjain",
        url="https://jobs.perotjain.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6626"},
    ),
    "gcvc": SourceRecord(
        key="gcvc",
        url="https://jobs.gc-vc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4019"},
    ),
    "elsewherepartners": SourceRecord(
        key="elsewherepartners",
        url="https://jobs.elsewhere.partners/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1020"},
    ),
    "pangacapital": SourceRecord(
        key="pangacapital",
        url="https://careers.pangacapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10388"},
    ),
    "lrnewenergy": SourceRecord(
        key="lrnewenergy",
        url="https://jobs.lrnewenergy.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4349"},
    ),
    "sovereignscapital": SourceRecord(
        key="sovereignscapital",
        url="https://portcojobs.sovereignscapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1281"},
    ),
    "allegiscyber": SourceRecord(
        key="allegiscyber",
        url="https://careers.allegiscyber.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2369"},
    ),
    "leadoutcapital": SourceRecord(
        key="leadoutcapital",
        url="https://jobs.leadoutcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "5174"},
    ),
    "overturevc": SourceRecord(
        key="overturevc",
        url="https://jobs.overture.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1876"},
    ),
    "sjfventures": SourceRecord(
        key="sjfventures",
        url="https://jobs.sjfventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "721"},
    ),
    "penderventures": SourceRecord(
        key="penderventures",
        url="https://careers.penderventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3854"},
    ),
    "arenaco": SourceRecord(
        key="arenaco",
        url="https://jobs.arenaco.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1113"},
    ),
    "hydeparkvp": SourceRecord(
        key="hydeparkvp",
        url="https://jobs.hydeparkvp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "112"},
    ),
    "mxv": SourceRecord(
        key="mxv",
        url="https://careers.mxv.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1528"},
    ),
    "maveron": SourceRecord(
        key="maveron",
        url="https://jobs.maveron.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "810"},
    ),
    "getrocommunity": SourceRecord(
        key="getrocommunity",
        url="https://community.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8870"},
    ),
    "innovationendeavors": SourceRecord(
        key="innovationendeavors",
        url="https://jobs.innovationendeavors.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "156"},
    ),
    "venturesplatform": SourceRecord(
        key="venturesplatform",
        url="https://jobs.venturesplatform.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10784"},
    ),
    "deepworkcapital": SourceRecord(
        key="deepworkcapital",
        url="https://careers.deepworkcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9497"},
    ),
    "blueyard": SourceRecord(
        key="blueyard",
        url="https://jobs.blueyard.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "796"},
    ),
    "abven": SourceRecord(
        key="abven",
        url="https://jobs.abven.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "400"},
    ),
    "differentialvc": SourceRecord(
        key="differentialvc",
        url="https://jobs.differential.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "765"},
    ),
    "arcternventures": SourceRecord(
        key="arcternventures",
        url="https://careers.arcternventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1087"},
    ),
    "fiveelms": SourceRecord(
        key="fiveelms",
        url="https://careers.fiveelms.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10586"},
    ),
    "echelon": SourceRecord(
        key="echelon",
        url="https://careers.echelon.xyz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12203"},
    ),
    "cerberus": SourceRecord(
        key="cerberus",
        url="https://portfoliojobs.cerberus.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12962"},
    ),
    "meron": SourceRecord(
        key="meron",
        url="https://careers.meron.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1257"},
    ),
    "relevanceventures": SourceRecord(
        key="relevanceventures",
        url="https://careers.relevanceventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6065"},
    ),
    "elabvc": SourceRecord(
        key="elabvc",
        url="https://jobs.elabvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1089"},
    ),
    "nightdragon": SourceRecord(
        key="nightdragon",
        url="https://careers.nightdragon.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1105"},
    ),
    "greymattercapital": SourceRecord(
        key="greymattercapital",
        url="https://careers.greymattercapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4910"},
    ),
    "amplitudevc": SourceRecord(
        key="amplitudevc",
        url="https://careers.amplitudevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1271"},
    ),
    "aldrichcap": SourceRecord(
        key="aldrichcap",
        url="https://careers.aldrichcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6659"},
    ),
    "valoventures": SourceRecord(
        key="valoventures",
        url="https://valoventures.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1540"},
    ),
    "kcrise": SourceRecord(
        key="kcrise",
        url="https://kcrise.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1503"},
    ),
    "skyviewventures": SourceRecord(
        key="skyviewventures",
        url="https://jobs.skyviewventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "5339"},
    ),
    "pulsefund": SourceRecord(
        key="pulsefund",
        url="https://careers.pulsefund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13985"},
    ),
    "superorganism": SourceRecord(
        key="superorganism",
        url="https://jobs.superorganism.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10058"},
    ),
    "i2iventures": SourceRecord(
        key="i2iventures",
        url="https://i2iventures.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1485"},
    ),
    "westlygroup": SourceRecord(
        key="westlygroup",
        url="https://jobs.westlygroup.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10685"},
    ),
    "jobsinvc": SourceRecord(
        key="jobsinvc",
        url="https://jobsinvc.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "15272"},
    ),
    "innovationbay": SourceRecord(
        key="innovationbay",
        url="https://jobs.innovationbay.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1014"},
    ),
    "praxis": SourceRecord(
        key="praxis",
        url="https://jobs.praxis.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "130"},
    ),
    "cranevc": SourceRecord(
        key="cranevc",
        url="https://careers.crane.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1940"},
    ),
    "upfront": SourceRecord(
        key="upfront",
        url="https://jobs.upfront.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "184"},
    ),
    "kickstart": SourceRecord(
        key="kickstart",
        url="https://jobs.kickstart.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "131"},
    ),
    "learncapital": SourceRecord(
        key="learncapital",
        url="https://learncapital.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "396"},
    ),
    "imagineh2o": SourceRecord(
        key="imagineh2o",
        url="https://watertechjobs.imagineh2o.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2336"},
    ),
    "engine": SourceRecord(
        key="engine",
        url="https://jobs.engine.xyz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "223"},
    ),
    "orbitmit": SourceRecord(
        key="orbitmit",
        url="https://jobs.orbit.mit.edu/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "186"},
    ),
    "brv": SourceRecord(
        key="brv",
        url="https://jobs.brv.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "168"},
    ),
    "startupcincy": SourceRecord(
        key="startupcincy",
        url="https://jobs.startupcincy.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "14810"},
    ),
    "amplifylaunchpad": SourceRecord(
        key="amplifylaunchpad",
        url="https://amplifylaunchpad.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "925"},
    ),
    "wassonenterprise": SourceRecord(
        key="wassonenterprise",
        url="https://careers.wassonenterprise.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "873"},
    ),
    "onewayvc": SourceRecord(
        key="onewayvc",
        url="https://careers.onewayvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "942"},
    ),
    "luminarventures": SourceRecord(
        key="luminarventures",
        url="https://careers.luminarventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10487"},
    ),
    "clearventures": SourceRecord(
        key="clearventures",
        url="https://jobs.clear.ventures/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "36293"},
    ),
    "javelinvp": SourceRecord(
        key="javelinvp",
        url="https://careers.javelinvp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "324"},
    ),
    "grovevc": SourceRecord(
        key="grovevc",
        url="https://careers.grovevc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9398"},
    ),
    "forgepointcap": SourceRecord(
        key="forgepointcap",
        url="https://jobs.forgepointcap.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1369"},
    ),
    "blackwoodvc": SourceRecord(
        key="blackwoodvc",
        url="https://careers.blackwood.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11543"},
    ),
    "albumvc": SourceRecord(
        key="albumvc",
        url="https://jobs.album.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "134"},
    ),
    "americanunderground": SourceRecord(
        key="americanunderground",
        url="https://jobs.americanunderground.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1117"},
    ),
    "deciens": SourceRecord(
        key="deciens",
        url="https://careers.deciens.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "5240"},
    ),
    "georgiafintechacademy": SourceRecord(
        key="georgiafintechacademy",
        url="https://jobs.georgiafintechacademy.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1357"},
    ),
    "ideavillage": SourceRecord(
        key="ideavillage",
        url="https://jobs.ideavillage.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1183"},
    ),
    "4pt0": SourceRecord(
        key="4pt0",
        url="https://jobs.4pt0.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13523"},
    ),
    "supermooncapital": SourceRecord(
        key="supermooncapital",
        url="https://jobs.supermooncapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1208"},
    ),
    "bluehaveninitiative": SourceRecord(
        key="bluehaveninitiative",
        url="https://jobs.bluehaveninitiative.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "329"},
    ),
    "firstraysvc": SourceRecord(
        key="firstraysvc",
        url="https://jobs.firstraysvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1194"},
    ),
    "nextfrontiercapital": SourceRecord(
        key="nextfrontiercapital",
        url="https://jobs.nextfrontiercapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "583"},
    ),
    "marble": SourceRecord(
        key="marble",
        url="https://careers.marble.studio/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7946"},
    ),
    "techtitans": SourceRecord(
        key="techtitans",
        url="https://careers.techtitans.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1186"},
    ),
    "thegarage": SourceRecord(
        key="thegarage",
        url="https://jobs.thegarage.northwestern.edu/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "5801"},
    ),
    "marsdd": SourceRecord(
        key="marsdd",
        url="https://techjobs.marsdd.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "383"},
    ),
    "jumpstartinc": SourceRecord(
        key="jumpstartinc",
        url="https://talent.jumpstartinc.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1012"},
    ),
    "massdigitalhealth": SourceRecord(
        key="massdigitalhealth",
        url="https://jobs.massdigitalhealth.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "218"},
    ),
    "ohiox": SourceRecord(
        key="ohiox",
        url="https://jobs.ohiox.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "785"},
    ),
    "xrcventures": SourceRecord(
        key="xrcventures",
        url="https://careers.xrcventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1211"},
    ),
    "mmc": SourceRecord(
        key="mmc",
        url="https://jobs.mmc.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2303"},
    ),
    "theventurecity": SourceRecord(
        key="theventurecity",
        url="https://careers.theventure.city/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4646"},
    ),
    "tandeminvest": SourceRecord(
        key="tandeminvest",
        url="https://jobs.tandeminvest.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "13193"},
    ),
    "decisivepoint": SourceRecord(
        key="decisivepoint",
        url="https://jobs.decisivepoint.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1074"},
    ),
    "aqpsearch": SourceRecord(
        key="aqpsearch",
        url="https://jobs.aqpsearch.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "761"},
    ),
    "midweststartups": SourceRecord(
        key="midweststartups",
        url="https://jobs.midweststartups.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "768"},
    ),
    "aihubmasstech": SourceRecord(
        key="aihubmasstech",
        url="https://jobs.aihub.masstech.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "39725"},
    ),
    "icehouseventures": SourceRecord(
        key="icehouseventures",
        url="https://jobs.icehouseventures.co.nz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "943"},
    ),
    "hub71": SourceRecord(
        key="hub71",
        url="https://jobs.hub71.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9266"},
    ),
    "safary": SourceRecord(
        key="safary",
        url="https://jobs.safary.club/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "36128"},
    ),
    "lhh": SourceRecord(
        key="lhh",
        url="https://jobs.lhh.co.il/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1200"},
    ),
    "coinbase": SourceRecord(
        key="coinbase",
        url="https://coinbase.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1625"},
    ),
    "theblockchainassociation": SourceRecord(
        key="theblockchainassociation",
        url="https://jobs.theblockchainassociation.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "869"},
    ),
    "valorcapitalgroup": SourceRecord(
        key="valorcapitalgroup",
        url="https://jobs.valorcapitalgroup.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "299"},
    ),
    "allhands": SourceRecord(
        key="allhands",
        url="https://jobs.all-hands.us/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "634"},
    ),
    "thepeoplepeoplegroup": SourceRecord(
        key="thepeoplepeoplegroup",
        url="https://jobs.thepeoplepeoplegroup.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "42266"},
    ),
    "sandscapitalventures": SourceRecord(
        key="sandscapitalventures",
        url="https://jobs.sandscapitalventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1638"},
    ),
    "vcet": SourceRecord(
        key="vcet",
        url="https://jobs.vcet.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "15470"},
    ),
    "nzero": SourceRecord(
        key="nzero",
        url="https://nzero.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "4218"},
    ),
    "quona": SourceRecord(
        key="quona",
        url="https://jobs.quona.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "313"},
    ),
    "obvious": SourceRecord(
        key="obvious",
        url="https://jobs.obvious.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "69"},
    ),
    "4dxventures": SourceRecord(
        key="4dxventures",
        url="https://careers.4dxventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11906"},
    ),
    "outlierventures": SourceRecord(
        key="outlierventures",
        url="https://jobs.outlierventures.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1524"},
    ),
    "morpheus": SourceRecord(
        key="morpheus",
        url="https://jobs.morpheus.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10916"},
    ),
    "byfounders": SourceRecord(
        key="byfounders",
        url="https://jobs.byfounders.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "248"},
    ),
    "ibexinvestors": SourceRecord(
        key="ibexinvestors",
        url="https://jobs.ibexinvestors.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1081"},
    ),
    "outsidersfund": SourceRecord(
        key="outsidersfund",
        url="https://jobs.outsidersfund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "6956"},
    ),
    "sogalventures": SourceRecord(
        key="sogalventures",
        url="https://jobs.sogalventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "136"},
    ),
    "fabervc": SourceRecord(
        key="fabervc",
        url="https://talent.faber.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2601"},
    ),
    "jumpcrypto": SourceRecord(
        key="jumpcrypto",
        url="https://jobs.jumpcrypto.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "20916"},
    ),
    "superseed": SourceRecord(
        key="superseed",
        url="https://careers.superseed.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7088"},
    ),
    "socialleverage": SourceRecord(
        key="socialleverage",
        url="https://jobs.socialleverage.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1371"},
    ),
    "intudovc": SourceRecord(
        key="intudovc",
        url="https://careers.intudovc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1177"},
    ),
    "polkadot": SourceRecord(
        key="polkadot",
        url="https://jobs.polkadot.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11180"},
    ),
    "traveltechessentialist": SourceRecord(
        key="traveltechessentialist",
        url="https://jobs.traveltechessentialist.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7682"},
    ),
    "folklorevc": SourceRecord(
        key="folklorevc",
        url="https://roles.folklore.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1730"},
    ),
    "alphapartners": SourceRecord(
        key="alphapartners",
        url="https://jobs.alphapartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1541"},
    ),
    "emeraldmanagers": SourceRecord(
        key="emeraldmanagers",
        url="https://careers.emeraldmanagers.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1448"},
    ),
    "syndicateone": SourceRecord(
        key="syndicateone",
        url="https://syndicate-one.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "15503"},
    ),
    "dukecapitalpartners": SourceRecord(
        key="dukecapitalpartners",
        url="https://jobs.dukecapitalpartners.duke.edu/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2734"},
    ),
    "inuplands": SourceRecord(
        key="inuplands",
        url="https://jobs.inuplands.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8606"},
    ),
    "bnbchain": SourceRecord(
        key="bnbchain",
        url="https://jobs.bnbchain.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3788"},
    ),
    "endicottgp": SourceRecord(
        key="endicottgp",
        url="https://jobs.endicottgp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7352"},
    ),
    "arborview": SourceRecord(
        key="arborview",
        url="https://arborview.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1492"},
    ),
    "terae": SourceRecord(
        key="terae",
        url="https://terae.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "871"},
    ),
    "schmidtmarine": SourceRecord(
        key="schmidtmarine",
        url="https://jobs.schmidtmarine.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "110"},
    ),
    "concorde": SourceRecord(
        key="concorde",
        url="https://talent.concorde.network/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9695"},
    ),
    "fireup": SourceRecord(
        key="fireup",
        url="https://jobs.fire-up.net/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9893"},
    ),
    "dragonfly": SourceRecord(
        key="dragonfly",
        url="https://jobs.dragonfly.xyz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1118"},
    ),
    "delphiventures": SourceRecord(
        key="delphiventures",
        url="https://jobs.delphiventures.io/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1440"},
    ),
    "levelequity": SourceRecord(
        key="levelequity",
        url="https://portfoliocareers.levelequity.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1729"},
    ),
    "floridafunders": SourceRecord(
        key="floridafunders",
        url="https://jobs.floridafunders.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "781"},
    ),
    "electriccapital": SourceRecord(
        key="electriccapital",
        url="https://jobs.electriccapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1640"},
    ),
    "launchcapital": SourceRecord(
        key="launchcapital",
        url="https://jobs.launchcapital.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "109"},
    ),
    "flashpointvc": SourceRecord(
        key="flashpointvc",
        url="https://jobs.flashpointvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "11513"},
    ),
    "suffolktech": SourceRecord(
        key="suffolktech",
        url="https://careers.suffolktech.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "9596"},
    ),
    "blackhornvc": SourceRecord(
        key="blackhornvc",
        url="https://careers.blackhornvc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "2733"},
    ),
    "nascent": SourceRecord(
        key="nascent",
        url="https://jobs.nascent.xyz/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "5372"},
    ),
    "uvcpartners": SourceRecord(
        key="uvcpartners",
        url="https://talent.uvcpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3062"},
    ),
    "blueventurefund": SourceRecord(
        key="blueventurefund",
        url="https://jobs.blueventurefund.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "145"},
    ),
    "liveoakvp": SourceRecord(
        key="liveoakvp",
        url="https://jobs.liveoakvp.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "946"},
    ),
    "tlvpartners": SourceRecord(
        key="tlvpartners",
        url="https://jobs.tlv.partners/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "190"},
    ),
    "atxventurepartners": SourceRecord(
        key="atxventurepartners",
        url="https://jobs.atxventurepartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "325"},
    ),
    "moneta": SourceRecord(
        key="moneta",
        url="https://jobs.moneta.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1015"},
    ),
    "cedarparktexasedc": SourceRecord(
        key="cedarparktexasedc",
        url="https://jobs.cedarparktexasedc.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "803"},
    ),
    "petersonventures": SourceRecord(
        key="petersonventures",
        url="https://jobs.petersonventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "395"},
    ),
    "beliade": SourceRecord(
        key="beliade",
        url="https://jobs.beliade.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "191"},
    ),
    "oifvc": SourceRecord(
        key="oifvc",
        url="https://oifvc.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1265"},
    ),
    "updata": SourceRecord(
        key="updata",
        url="https://jobs.updata.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "3128"},
    ),
    "uphonestcapital": SourceRecord(
        key="uphonestcapital",
        url="https://uphonestcapital.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1733"},
    ),
    "nebraskaangels": SourceRecord(
        key="nebraskaangels",
        url="https://careers.nebraskaangels.org/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "7286"},
    ),
    "trailheadcap": SourceRecord(
        key="trailheadcap",
        url="https://trailheadcap.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1493"},
    ),
    "ballisticventures": SourceRecord(
        key="ballisticventures",
        url="https://careers.ballisticventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "8441"},
    ),
    "thehelm": SourceRecord(
        key="thehelm",
        url="https://jobs.thehelm.co/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1519"},
    ),
    "supercellinvestments": SourceRecord(
        key="supercellinvestments",
        url="https://supercellinvestments.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "12500"},
    ),
    "revelpartners": SourceRecord(
        key="revelpartners",
        url="https://jobs.revelpartners.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "683"},
    ),
    "sandboxindustries": SourceRecord(
        key="sandboxindustries",
        url="https://jobs.sandboxindustries.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "877"},
    ),
    "eoventures": SourceRecord(
        key="eoventures",
        url="https://jobs.eoventures.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "14018"},
    ),
    "blindspot": SourceRecord(
        key="blindspot",
        url="https://blindspot.getro.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "1497"},
    ),
    "placeholder": SourceRecord(
        key="placeholder",
        url="https://jobs.placeholder.vc/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "922"},
    ),
    "blacktalentdatabase": SourceRecord(
        key="blacktalentdatabase",
        url="https://jobs.blacktalentdatabase.com/companies",
        provider_id="getro",
        enabled=True,
        raw_metadata={"collectionId": "10982"},
    ),
}

SOURCE_RECORDS: tuple[SourceRecord, ...] = tuple(GETRO_SOURCE_CATALOG.values())


ABLEPARTNERS_SOURCE = SourceRecord(
    key="ablepartners",
    url="https://careers.ablepartners.nyc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ABUNDANCENETWORK_SOURCE = SourceRecord(
    key="abundancenetwork",
    url="https://jobs.abundancenetwork.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ALKEON_SOURCE = SourceRecord(
    key="alkeon",
    url="https://jobs.alkeon.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ARBITRUM_SOURCE = SourceRecord(
    key="arbitrum",
    url="https://jobs.arbitrum.io/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


BOOKSCAPITAL13_SOURCE = SourceRecord(
    key="13bookscapital",
    url="https://careers.13bookscapital.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


BUOYANT_SOURCE = SourceRecord(
    key="buoyant",
    url="https://careers.buoyant.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


CHARLESTONORG_SOURCE = SourceRecord(
    key="charlestonorg",
    url="https://jobs.charlestoncareers.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


CHOOSEMKETECH_SOURCE = SourceRecord(
    key="choosemketech",
    url="https://jobs.choosemketech.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


CLEVELANDTALENT_SOURCE = SourceRecord(
    key="clevelandtalent",
    url="https://jobs.clevelandtalent.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


DCEDC_SOURCE = SourceRecord(
    key="dcedc",
    url="https://careers.dcedc.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ENTREPRENEURS_SOURCE = SourceRecord(
    key="entrepreneurs",
    url="https://jobs.entrepreneurs.utoronto.ca/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


FORWARD_SOURCE = SourceRecord(
    key="forward",
    url="https://careers.forward.one/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


FUTURE_SOURCE = SourceRecord(
    key="future",
    url="https://jobs.future.ventures/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


GRANDFORKSISCOOLER_SOURCE = SourceRecord(
    key="grandforksiscooler",
    url="https://jobs.grandforksiscooler.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


GREATERSATX_SOURCE = SourceRecord(
    key="greatersatx",
    url="https://careers.greatersatx.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


HEALTHXVENTURES_SOURCE = SourceRecord(
    key="healthxventures",
    url="https://jobs.healthxventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


HIGHFIVEPARTNERS_SOURCE = SourceRecord(
    key="highfivepartners",
    url="https://jobs.highfivepartners.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


HOPELAB_SOURCE = SourceRecord(
    key="hopelab",
    url="https://hopelab.getro.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


IMECISTART_SOURCE = SourceRecord(
    key="imecistart",
    url="https://jobs.imecistart.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


INNOVATIONWORKS_SOURCE = SourceRecord(
    key="innovationworks",
    url="https://jobs.innovationworks.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


INWOMENSHEALTH_SOURCE = SourceRecord(
    key="inwomenshealth",
    url="https://jobs.inwomenshealth.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


IRONSPRING_SOURCE = SourceRecord(
    key="ironspring",
    url="https://jobs.ironspring.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


JOBSWITHNOBOSS_SOURCE = SourceRecord(
    key="jobswithnoboss",
    url="https://jobs.jobswithnoboss.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


KDTVC_SOURCE = SourceRecord(
    key="kdtvc",
    url="https://jobs.kdtvc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MAKEITCU_SOURCE = SourceRecord(
    key="makeitcu",
    url="https://jobs.makeitcu.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MOBERLYEDC_SOURCE = SourceRecord(
    key="moberlyedc",
    url="https://jobs.moberly-edc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MORESTARTSHERE_SOURCE = SourceRecord(
    key="morestartshere",
    url="https://careers.morestartshere.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MYJONESBOROCOM_SOURCE = SourceRecord(
    key="myjonesborocom",
    url="https://jobs.myjonesborojobs.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

PHXFWD_SOURCE = SourceRecord(
    key="phxfwd",
    url="https://jobs.phxfwd.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
FOODTECHSCOUT_SOURCE = SourceRecord(
    key="foodtechscout",
    url="https://jobs.foodtechscout.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
I2BF_SOURCE = SourceRecord(
    key="i2bf",
    url="https://talent.i2bf.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
NARREACH_SOURCE = SourceRecord(
    key="narreach",
    url="https://careers.narreach.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
COINFUND_SOURCE = SourceRecord(
    key="coinfund",
    url="https://jobs.coinfund.io/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
MATCHSTICKVENTURES_SOURCE = SourceRecord(
    key="matchstickventures",
    url="https://jobs.matchstickventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
PLUGANDPLAYFOUNDATION_SOURCE = SourceRecord(
    key="plugandplayfoundation",
    url="https://accessopportunities.plugandplayfoundation.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
CASTLEISLAND_SOURCE = SourceRecord(
    key="castleisland",
    url="https://jobs.castleisland.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
TOGETHXR_SOURCE = SourceRecord(
    key="togethxr",
    url="https://jobs.togethxr.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
EDOMARKETPLACE_SOURCE = SourceRecord(
    key="edomarketplace",
    url="https://edomarketplace.getro.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
CANTOS_SOURCE = SourceRecord(
    key="cantos",
    url="https://jobs.cantos.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
SILVERTONPARTNERS_SOURCE = SourceRecord(
    key="silvertonpartners",
    url="https://jobs.silvertonpartners.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
GFRFUND_SOURCE = SourceRecord(
    key="gfrfund",
    url="https://jobs.gfrfund.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
FORTINOCAPITAL_SOURCE = SourceRecord(
    key="fortinocapital",
    url="https://talent.fortinocapital.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
ZIGGTALENT_SOURCE = SourceRecord(
    key="ziggtalent",
    url="https://jobs.ziggtalent.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
DRIVETLV_SOURCE = SourceRecord(
    key="drivetlv",
    url="https://jobs.drivetlv.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
STARTMUNICH_SOURCE = SourceRecord(
    key="startmunich",
    url="https://jobs.startmunich.de/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
DEFINITIONCAP_SOURCE = SourceRecord(
    key="definitioncap",
    url="https://jobs.definitioncap.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
ALMAZCAPITAL_SOURCE = SourceRecord(
    key="almazcapital",
    url="https://jobs.almazcapital.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
SPARTANGROUP_SOURCE = SourceRecord(
    key="spartangroup",
    url="https://jobs.spartangroup.io/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
JDSSPORTS_SOURCE = SourceRecord(
    key="jdssports",
    url="https://jobs.jdssports.co/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
LYRAGROWTH_SOURCE = SourceRecord(
    key="lyragrowth",
    url="https://jobs.lyragrowth.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
THEADCLUB_SOURCE = SourceRecord(
    key="theadclub",
    url="https://careers.theadclub.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
TNENTERTAINMENT_SOURCE = SourceRecord(
    key="tnentertainment",
    url="https://jobs.tnentertainment.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
ROWANEDC_SOURCE = SourceRecord(
    key="rowanedc",
    url="https://jobs.rowanedc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
CLARKSVILLEISHIRING_SOURCE = SourceRecord(
    key="clarksvilleishiring",
    url="https://jobs.clarksvilleishiring.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
FLINTANDGENESEE_SOURCE = SourceRecord(
    key="flintandgenesee",
    url="https://jobs.flintandgenesee.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
GROWINGREENVILLENC_SOURCE = SourceRecord(
    key="growingreenvillenc",
    url="https://jobs.growingreenvillenc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

NOROMOSELEY_SOURCE = SourceRecord(
    key="noromoseley",
    url="https://careers.noromoseley.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ONEVENTURES_SOURCE = SourceRecord(
    key="oneventures",
    url="https://jobs.one-ventures.com.au/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


PEOPLEFUNCTION_SOURCE = SourceRecord(
    key="peoplefunction",
    url="https://jobs.peoplefunction.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SEAEVENTURES_SOURCE = SourceRecord(
    key="seaeventures",
    url="https://careers.seaeventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SIERRAVENTURES_SOURCE = SourceRecord(
    key="sierraventures",
    url="https://careers.sierraventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SIXTY8_SOURCE = SourceRecord(
    key="sixty8",
    url="https://jobs.sixty8.capital/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SKAGIT_SOURCE = SourceRecord(
    key="skagit",
    url="https://jobs.skagit.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SPIRITTECHCOLLECTIVE_SOURCE = SourceRecord(
    key="spirittechcollective",
    url="https://jobs.spirit-tech-collective.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


STVENTURESLAB_SOURCE = SourceRecord(
    key="stventureslab",
    url="https://careers.stventureslab.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


VAMOSVENTURES_SOURCE = SourceRecord(
    key="vamosventures",
    url="https://jobs.vamosventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


VERTEXVENTURES_SOURCE = SourceRecord(
    key="vertexventures",
    url="https://jobs.vertexventures.co.il/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


WATERSHED_SOURCE = SourceRecord(
    key="watershed",
    url="https://portfolio.watershed.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


WEAREADAMARIE_SOURCE = SourceRecord(
    key="weareadamarie",
    url="https://jobs.weareadamarie.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


WHATSUPSTATENY_SOURCE = SourceRecord(
    key="whatsupstateny",
    url="https://jobs.whatsupstateny.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


WORKFORCEINNOVATIONCENTER_SOURCE = SourceRecord(
    key="workforceinnovationcenter",
    url="https://careers.workforceinnovationcenter.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


WORKINSEGUIN_SOURCE = SourceRecord(
    key="workinseguin",
    url="https://www.workinseguin.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


UPROTTERDAM_SOURCE = SourceRecord(
    key="uprotterdam",
    url="https://jobs.uprotterdam.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MASSCYBERCENTER_SOURCE = SourceRecord(
    key="masscybercenter",
    url="https://jobs.masscybercenter.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


TOLEDOREGION_SOURCE = SourceRecord(
    key="toledoregion",
    url="https://jobs.toledoregion.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


WORKINBA_SOURCE = SourceRecord(
    key="workinba",
    url="https://careers.workinba.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ONEWAGONERCOUNTY_SOURCE = SourceRecord(
    key="onewagonercounty",
    url="https://jobs.onewagonercounty.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ROCKFORDCHAMBER_SOURCE = SourceRecord(
    key="rockfordchamber",
    url="https://jobs.rockfordchamber.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


PLACETOBELNK_SOURCE = SourceRecord(
    key="placetobelnk",
    url="https://jobs.placetobelnk.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MAIP_SOURCE = SourceRecord(
    key="maip",
    url="https://jobs.maip.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


INOVAIT_SOURCE = SourceRecord(
    key="inovait",
    url="https://jobs.inovait.ca/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


MEHI_SOURCE = SourceRecord(
    key="mehi",
    url="https://jobs.mehi.masstech.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


PEAK_SOURCE = SourceRecord(
    key="peak",
    url="https://jobs.peak.capital/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


VMGPARTNERS_SOURCE = SourceRecord(
    key="vmgpartners",
    url="https://jobs.vmgpartners.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


NUCLEUSCAPITAL_SOURCE = SourceRecord(
    key="nucleuscapital",
    url="https://careers.nucleus-capital.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SWAYVC_SOURCE = SourceRecord(
    key="swayvc",
    url="https://talent.swayvc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


FAYETTECHAMBER_SOURCE = SourceRecord(
    key="fayettechamber",
    url="https://careers.fayettechamber.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SMARTFINVC_SOURCE = SourceRecord(
    key="smartfinvc",
    url="https://jobs.smartfinvc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SAINTJOSEPH_SOURCE = SourceRecord(
    key="saintjoseph",
    url="https://jobs.saintjoseph.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


NBCHAMBER_SOURCE = SourceRecord(
    key="nbchamber",
    url="https://jobs.nbchamber.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SSEDC_SOURCE = SourceRecord(
    key="ssedc",
    url="https://jobs.ss-edc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


INNOVATE_SOURCE = SourceRecord(
    key="innovate",
    url="https://jobs.innovate.ms/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


KAYYAKVENTURES_SOURCE = SourceRecord(
    key="kayyakventures",
    url="https://jobs.kayyakventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


HETZ_SOURCE = SourceRecord(
    key="hetz",
    url="https://careers.hetz.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


CONNEXACAPITAL_SOURCE = SourceRecord(
    key="connexacapital",
    url="https://careers.connexacapital.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


SKALE_SOURCE = SourceRecord(
    key="skale",
    url="https://jobs.skale.space/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


GEORGETOWN_SOURCE = SourceRecord(
    key="georgetown",
    url="https://georgetown.getro.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


ALPINESG_SOURCE = SourceRecord(
    key="alpinesg",
    url="https://jobs.alpinesg.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


LUMOSCAPITALGROUP_SOURCE = SourceRecord(
    key="lumoscapitalgroup",
    url="https://lumoscapitalgroup.getro.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)


class GetroSourceAdapter:
    provider_id = "getro"
    provider_label = "Getro"
    provider_description = (
        "Aggregate Getro source adapter that discovers company boards."
    )

    def __init__(self, settings: OpenOppsSettings):
        self.settings = settings
        self._request_json = retrying_json_request(settings)

    async def iter_boards(
        self,
        client: httpx.AsyncClient,
        source: SourceRecord,
        *,
        page_size: int,
    ) -> AsyncIterator[tuple[list[BoardRecord], list[BoardProviderRecord], dict]]:
        validate_public_https_url(source.url)
        collection_id = str(
            source.raw_metadata.get("collectionId")
            or await self._discover_collection_id(client, source)
        )
        parsed = urlparse(source.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        page = 0
        total: int | None = None
        while total is None or page * page_size < total:
            payload = {
                "hitsPerPage": page_size,
                "page": page,
                "query": "",
                "filters": "",
            }
            try:
                data = await self._request_json(
                    client,
                    "POST",
                    f"https://api.getro.com/api/v2/collections/{collection_id}/search/companies",
                    json=payload,
                    headers={
                        "accept": "application/json",
                        "content-type": "application/json",
                        "origin": origin,
                        "referer": source.url,
                    },
                )
                partial = False
            except httpx.HTTPStatusError as exc:
                if page != 0 or exc.response.status_code != 403:
                    raise
                data = await self._embedded_initial_state(client, source)
                partial = True
            if not isinstance(data, dict) or not isinstance(data.get("results"), dict):
                raise ValueError("Getro companies endpoint returned invalid JSON")
            response = GetroCompaniesResponse.model_validate(data)
            companies = response.results.companies
            total = response.results.count or len(companies)
            boards = self._normalize_companies(source.key, companies)
            yield (
                boards,
                [],
                {
                    "collectionId": collection_id,
                    "page": page,
                    "pageSize": page_size,
                    "total": total,
                    "pages": math.ceil(total / page_size) if page_size else 0,
                    "partial": partial,
                },
            )
            if not companies:
                break
            if partial:
                break
            page += 1

    async def _discover_collection_id(
        self, client: httpx.AsyncClient, source: SourceRecord
    ) -> str:
        response = await client.get(source.url, follow_redirects=True)
        response.raise_for_status()
        match = _COLLECTION_RE.search(response.text)
        if not match:
            raise ValueError(
                f"Could not discover Getro collection id from {source.url}"
            )
        return match.group("id")

    async def _embedded_initial_state(
        self, client: httpx.AsyncClient, source: SourceRecord
    ) -> dict[str, Any]:
        response = await client.get(source.url, follow_redirects=True)
        response.raise_for_status()
        match = _NEXT_DATA_RE.search(response.text)
        if not match:
            raise ValueError(
                f"Could not find embedded Getro initial state in {source.url}"
            )
        data = json.loads(match.group("data"))
        companies = data["props"]["pageProps"]["initialState"]["companies"]
        return {
            "results": {
                "companies": companies.get("found") or [],
                "count": companies.get("total") or 0,
            }
        }

    def _normalize_companies(
        self, source_key: str, companies: list[GetroCompany]
    ) -> list[BoardRecord]:
        boards: list[BoardRecord] = []
        now = utc_now()
        for company in companies:
            remote_id = str(
                company.id or company.object_id or company.slug or company.name
            )
            remote_slug = str(company.slug or slugify(str(company.name or remote_id)))
            website_url = self._website_url(company.domain)
            domain = self._domain_from_url(website_url)
            board = BoardRecord(
                key=source_board_key(source_key, remote_slug),
                source_key=source_key,
                remote_id=remote_id,
                remote_slug=remote_slug,
                name=company.name or remote_id,
                domain=domain,
                website_url=website_url,
                description=company.description,
                markets=company.visible_industry_tags or company.industry_tags,
                locations=company.locations,
                staff_count=company.head_count,
                num_jobs_hint=company.active_jobs_count,
                raw_payload=company.as_raw_payload(),
                synced_at=now,
            )
            boards.append(board)
        return boards

    def _website_url(self, domain: str | None) -> str | None:
        return normalize_public_website_url(domain)

    def _domain_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        return urlparse(url).netloc.lower() or None


CLEVELANDTALENT_SOURCE = SourceRecord(
    key="clevelandtalent",
    url="https://jobs.clevelandtalent.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

HIGHFIVEPARTNERS_SOURCE = SourceRecord(
    key="highfivepartners",
    url="https://jobs.highfivepartners.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

ENTREPRENEURS_SOURCE = SourceRecord(
    key="entrepreneurs",
    url="https://jobs.entrepreneurs.utoronto.ca/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

MORESTARTSHERE_SOURCE = SourceRecord(
    key="morestartshere",
    url="https://careers.morestartshere.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

MAKEITCU_SOURCE = SourceRecord(
    key="makeitcu",
    url="https://jobs.makeitcu.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

INNOVATIONWORKS_SOURCE = SourceRecord(
    key="innovationworks",
    url="https://jobs.innovationworks.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

CHARLESTONORG_SOURCE = SourceRecord(
    key="charlestonorg",
    url="https://jobs.charlestoncareers.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

GREATERSATX_SOURCE = SourceRecord(
    key="greatersatx",
    url="https://careers.greatersatx.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

INWOMENSHEALTH_SOURCE = SourceRecord(
    key="inwomenshealth",
    url="https://jobs.inwomenshealth.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

SKAGIT_SOURCE = SourceRecord(
    key="skagit",
    url="https://jobs.skagit.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

WORKFORCEINNOVATIONCENTER_SOURCE = SourceRecord(
    key="workforceinnovationcenter",
    url="https://careers.workforceinnovationcenter.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

JOBSWITHNOBOSS_SOURCE = SourceRecord(
    key="jobswithnoboss",
    url="https://jobs.jobswithnoboss.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

GRANDFORKSISCOOLER_SOURCE = SourceRecord(
    key="grandforksiscooler",
    url="https://jobs.grandforksiscooler.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

SPIRITTECHCOLLECTIVE_SOURCE = SourceRecord(
    key="spirittechcollective",
    url="https://jobs.spirit-tech-collective.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

IMECISTART_SOURCE = SourceRecord(
    key="imecistart",
    url="https://jobs.imecistart.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

ABUNDANCENETWORK_SOURCE = SourceRecord(
    key="abundancenetwork",
    url="https://jobs.abundancenetwork.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

ABLEPARTNERS_SOURCE = SourceRecord(
    key="ablepartners",
    url="https://careers.ablepartners.nyc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

SIERRAVENTURES_SOURCE = SourceRecord(
    key="sierraventures",
    url="https://careers.sierraventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

ALKEON_SOURCE = SourceRecord(
    key="alkeon",
    url="https://jobs.alkeon.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

VERTEXVENTURES_SOURCE = SourceRecord(
    key="vertexventures",
    url="https://jobs.vertexventures.co.il/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

KDTVC_SOURCE = SourceRecord(
    key="kdtvc",
    url="https://jobs.kdtvc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

MOBERLYEDC_SOURCE = SourceRecord(
    key="moberlyedc",
    url="https://jobs.moberly-edc.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

WEAREADAMARIE_SOURCE = SourceRecord(
    key="weareadamarie",
    url="https://jobs.weareadamarie.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

ARBITRUM_SOURCE = SourceRecord(
    key="arbitrum",
    url="https://jobs.arbitrum.io/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

ONEVENTURES_SOURCE = SourceRecord(
    key="oneventures",
    url="https://jobs.one-ventures.com.au/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

CHOOSEMKETECH_SOURCE = SourceRecord(
    key="choosemketech",
    url="https://jobs.choosemketech.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

HEALTHXVENTURES_SOURCE = SourceRecord(
    key="healthxventures",
    url="https://jobs.healthxventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

WATERSHED_SOURCE = SourceRecord(
    key="watershed",
    url="https://portfolio.watershed.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

BOOKSCAPITAL13_SOURCE = SourceRecord(
    key="13bookscapital",
    url="https://careers.13bookscapital.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

FUTURE_SOURCE = SourceRecord(
    key="future",
    url="https://jobs.future.ventures/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

VAMOSVENTURES_SOURCE = SourceRecord(
    key="vamosventures",
    url="https://jobs.vamosventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

PEOPLEFUNCTION_SOURCE = SourceRecord(
    key="peoplefunction",
    url="https://jobs.peoplefunction.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

IRONSPRING_SOURCE = SourceRecord(
    key="ironspring",
    url="https://jobs.ironspring.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

FORWARD_SOURCE = SourceRecord(
    key="forward",
    url="https://careers.forward.one/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

NOROMOSELEY_SOURCE = SourceRecord(
    key="noromoseley",
    url="https://careers.noromoseley.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

HOPELAB_SOURCE = SourceRecord(
    key="hopelab",
    url="https://hopelab.getro.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

SEAEVENTURES_SOURCE = SourceRecord(
    key="seaeventures",
    url="https://careers.seaeventures.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

STVENTURESLAB_SOURCE = SourceRecord(
    key="stventureslab",
    url="https://careers.stventureslab.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

BUOYANT_SOURCE = SourceRecord(
    key="buoyant",
    url="https://careers.buoyant.vc/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

SIXTY8_SOURCE = SourceRecord(
    key="sixty8",
    url="https://jobs.sixty8.capital/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

DCEDC_SOURCE = SourceRecord(
    key="dcedc",
    url="https://careers.dcedc.org/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

WORKINSEGUIN_SOURCE = SourceRecord(
    key="workinseguin",
    url="https://www.workinseguin.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

WHATSUPSTATENY_SOURCE = SourceRecord(
    key="whatsupstateny",
    url="https://jobs.whatsupstateny.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)

MYJONESBOROCOM_SOURCE = SourceRecord(
    key="myjonesborocom",
    url="https://jobs.myjonesborojobs.com/companies",
    provider_id="getro",
    enabled=True,
    raw_metadata={},
)
