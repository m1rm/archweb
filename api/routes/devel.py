from ninja import Router
from ninja.security import django_auth

from api.schemas.devel import (
    ReportDetailSchema,
    ReportListSchema,
    ReportMetaSchema,
    ReportPackageSchema,
    ReportPkgbasesSchema,
)
from devel.report_data import (
    collect_report_data,
    list_report_metadata,
    serialize_package_for_report,
)

router = Router(tags=['devel'], auth=django_auth)


def _report_detail(report_slug: str, username: str | None = None) -> ReportDetailSchema:
    data = collect_report_data(report_slug, username)
    report = data['report']
    maintainer = data['maintainer']
    return ReportDetailSchema(
        version=1,
        slug=report.slug,
        name=report.name,
        description=report.description,
        personal=report.personal,
        maintainer=maintainer.username if maintainer else None,
        count=len(data['packages']),
        arches=[arch.name for arch in data['arches']],
        repos=[repo.name for repo in data['repos']],
        columns=list(report.names) if report.names else [],
        packages=[
            ReportPackageSchema(**serialize_package_for_report(pkg, report))
            for pkg in data['packages']
        ],
    )


def _report_pkgbases(report_slug: str, username: str | None = None) -> ReportPkgbasesSchema:
    data = collect_report_data(report_slug, username)
    report = data['report']
    maintainer = data['maintainer']
    return ReportPkgbasesSchema(
        version=1,
        slug=report.slug,
        maintainer=maintainer.username if maintainer else None,
        pkgbases=sorted({pkg.pkgbase for pkg in data['packages']}),
    )


@router.get('/reports/', response=ReportListSchema, url_name='devel-reports-list')
def reports_list(request):
    return ReportListSchema(
        version=1,
        reports=[ReportMetaSchema(**meta) for meta in list_report_metadata()],
    )


@router.get(
    '/reports/{report_slug}/pkgbases/',
    response=ReportPkgbasesSchema,
    url_name='devel-report-pkgbases',
)
def report_pkgbases(request, report_slug: str):
    return _report_pkgbases(report_slug)


@router.get(
    '/reports/{report_slug}/{username}/pkgbases/',
    response=ReportPkgbasesSchema,
    url_name='devel-report-pkgbases-maintainer',
)
def report_pkgbases_for_maintainer(request, report_slug: str, username: str):
    return _report_pkgbases(report_slug, username)


@router.get(
    '/reports/{report_slug}/{username}/',
    response=ReportDetailSchema,
    url_name='devel-report-detail-maintainer',
)
def report_detail_for_maintainer(request, report_slug: str, username: str):
    return _report_detail(report_slug, username)


@router.get(
    '/reports/{report_slug}/',
    response=ReportDetailSchema,
    url_name='devel-report-detail',
)
def report_detail(request, report_slug: str):
    return _report_detail(report_slug)
