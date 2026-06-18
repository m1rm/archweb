from datetime import date
from typing import Any

from ninja import Schema


class ReportMetaSchema(Schema):
    slug: str
    name: str
    description: str
    personal: bool
    columns: list[str]


class ReportListSchema(Schema):
    version: int
    reports: list[ReportMetaSchema]


class ReportPackageSchema(Schema):
    arch: str
    repo: str
    pkgname: str
    pkgbase: str
    version: str
    last_update: date
    build_date: date | None = None
    flag_date: date | None = None
    extras: dict[str, Any] = {}


class ReportDetailSchema(Schema):
    version: int
    slug: str
    name: str
    description: str
    personal: bool
    maintainer: str | None = None
    count: int
    arches: list[str]
    repos: list[str]
    columns: list[str]
    packages: list[ReportPackageSchema]


class ReportPkgbasesSchema(Schema):
    version: int
    slug: str
    maintainer: str | None = None
    pkgbases: list[str]
