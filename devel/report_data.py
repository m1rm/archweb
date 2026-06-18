from datetime import date, datetime
from typing import Any

from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import get_object_or_404

from main.models import Package
from packages.models import PackageRelation

from .reports import REPORTS_BY_SLUG, Linkify, available_reports

_USERNAME_FILTERED_SLUGS = frozenset({'uncompressed-man', 'uncompressed-info'})


def get_report_by_slug(slug: str):
    return REPORTS_BY_SLUG.get(slug)


def get_report_packages(report, username: str | None = None):
    packages = Package.objects.normal()
    effective_username = username if report.personal else None

    if effective_username:
        user = get_object_or_404(User, username=effective_username, is_active=True)
        maintained = PackageRelation.objects.filter(
            user=user, type=PackageRelation.MAINTAINER).values('pkgbase')
        packages = packages.filter(pkgbase__in=maintained)

    if report.slug in _USERNAME_FILTERED_SLUGS:
        return report.packages(packages, effective_username)
    return report.packages(packages)


def collect_report_data(report_slug: str, username: str | None = None) -> dict[str, Any]:
    report = get_report_by_slug(report_slug)
    if report is None:
        raise Http404

    maintainer = None
    effective_username = username if report.personal else None
    if effective_username:
        maintainer = get_object_or_404(User, username=effective_username, is_active=True)

    packages = list(get_report_packages(report, effective_username))

    arches = sorted({pkg.arch for pkg in packages}, key=lambda arch: arch.name)
    repos = sorted({pkg.repo for pkg in packages}, key=lambda repo: repo.name)

    return {
        'report': report,
        'maintainer': maintainer,
        'packages': packages,
        'arches': arches,
        'repos': repos,
    }


def serialize_extra_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, User):
        return value.username
    if isinstance(value, Linkify):
        return {'href': value.href, 'title': value.title, 'text': value.desc}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def serialize_package_for_report(pkg: Package, report) -> dict[str, Any]:
    data = {
        'arch': pkg.arch.name,
        'repo': pkg.repo.name,
        'pkgname': pkg.pkgname,
        'pkgbase': pkg.pkgbase,
        'version': pkg.full_version,
        'last_update': pkg.last_update.date(),
        'build_date': pkg.build_date.date() if pkg.build_date else None,
        'flag_date': pkg.flag_date.date() if pkg.flag_date else None,
        'extras': {},
    }
    if report.attrs:
        for attr in report.attrs:
            data['extras'][attr] = serialize_extra_value(getattr(pkg, attr, None))
    return data


def list_report_metadata() -> list[dict[str, Any]]:
    return [
        {
            'slug': report.slug,
            'name': report.name,
            'description': report.description,
            'personal': report.personal,
            'columns': list(report.names) if report.names else [],
        }
        for report in available_reports()
    ]
