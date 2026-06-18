import pytest

from devel.reports import REPORTS_BY_SLUG
from packages.models import PackageRelation

API_PREFIX = '/api/v1/devel/reports'
ALL_REPORT_SLUGS = tuple(REPORTS_BY_SLUG.keys())


@pytest.fixture
def maintainer_relation(developer, reports):
    relation = PackageRelation.objects.create(
        pkgbase='orphan-dep-consumer',
        user=developer,
        type=PackageRelation.MAINTAINER,
    )
    yield relation
    relation.delete()


@pytest.fixture
def linux_maintainer_relation(developer, reports):
    relation = PackageRelation.objects.create(
        pkgbase='linux',
        user=developer,
        type=PackageRelation.MAINTAINER,
    )
    yield relation
    relation.delete()


def test_reports_list_requires_auth(client):
    response = client.get(f'{API_PREFIX}/')
    assert response.status_code == 401


def test_reports_list(developer_client):
    response = developer_client.get(f'{API_PREFIX}/')
    assert response.status_code == 200
    data = response.json()
    assert data['version'] == 1
    assert len(data['reports']) == len(ALL_REPORT_SLUGS)
    slugs = {report['slug'] for report in data['reports']}
    assert slugs == set(ALL_REPORT_SLUGS)


def test_reports_list_metadata(developer_client):
    response = developer_client.get(f'{API_PREFIX}/')
    report = next(item for item in response.json()['reports']
                  if item['slug'] == 'non-existing-dependencies')
    assert report['name'] == 'Non existing dependencies'
    assert report['personal'] is False
    assert report['columns'] == ['Non existing dependency']


@pytest.mark.parametrize('slug', ALL_REPORT_SLUGS)
def test_report_detail_requires_auth(client, slug):
    response = client.get(f'{API_PREFIX}/{slug}/')
    assert response.status_code == 401


def test_report_detail_unknown_slug(developer_client):
    response = developer_client.get(f'{API_PREFIX}/does-not-exist/')
    assert response.status_code == 404


def test_report_detail_old_packages(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/old/')
    assert response.status_code == 200
    data = response.json()
    assert data['slug'] == 'old'
    assert data['count'] >= 5
    pkgnames = {pkg['pkgname'] for pkg in data['packages']}
    assert 'linux' in pkgnames


def test_report_detail_long_out_of_date(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/long-out-of-date/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'flagged-old' in pkgnames


def test_report_detail_big_packages(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/big/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'linux' in pkgnames
    linux = next(pkg for pkg in response.json()['packages'] if pkg['pkgname'] == 'linux')
    assert linux['extras']['compressed_size_pretty']
    assert linux['extras']['installed_size_pretty']


def test_report_detail_badcompression(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/badcompression/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'bad-compress' in pkgnames


def test_report_detail_uncompressed_man(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/uncompressed-man/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'uncompressed-man-pkg' in pkgnames


def test_report_detail_uncompressed_info(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/uncompressed-info/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'uncompressed-info-pkg' in pkgnames


def test_report_detail_unneeded_orphans(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/unneeded-orphans/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'unneeded-orphan' in pkgnames
    assert 'required-orphan' not in pkgnames


def test_report_detail_required_orphan(developer_client, reports, maintainer_relation):
    response = developer_client.get(f'{API_PREFIX}/required-orphan/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'orphan-dep-consumer' in pkgnames
    consumer = next(pkg for pkg in response.json()['packages']
                    if pkg['pkgname'] == 'orphan-dep-consumer')
    assert consumer['extras']['orphandeps'] == 'required-orphan'


def test_report_detail_non_existing_dependencies(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/non-existing-dependencies/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'missing-dep-holder' in pkgnames
    holder = next(pkg for pkg in response.json()['packages']
                  if pkg['pkgname'] == 'missing-dep-holder')
    assert holder['extras']['nonexistingdep'] == 'ghost-dependency'


def test_report_detail_non_reproducible_packages(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/non-reproducible-packages/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'repro-fail-pkg' in pkgnames
    repro = next(pkg for pkg in response.json()['packages'] if pkg['pkgname'] == 'repro-fail-pkg')
    assert repro['extras']['diffoscope']['href'].endswith('/diffoscope')
    assert repro['extras']['log']['text'] == 'log'


def test_report_detail_orphan_non_reproducible_packages(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/orphan-non-reproducible-packages/')
    assert response.status_code == 200
    pkgnames = {pkg['pkgname'] for pkg in response.json()['packages']}
    assert 'orphan-repro-fail' in pkgnames
    assert 'repro-fail-pkg' not in pkgnames


def test_report_pkgbases(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/old/pkgbases/')
    assert response.status_code == 200
    data = response.json()
    assert data['slug'] == 'old'
    assert 'linux' in data['pkgbases']


def test_report_pkgbases_for_maintainer(developer_client, reports, linux_maintainer_relation):
    response = developer_client.get(f'{API_PREFIX}/old/{linux_maintainer_relation.user.username}/pkgbases/')
    assert response.status_code == 200
    data = response.json()
    assert data['maintainer'] == linux_maintainer_relation.user.username
    assert data['pkgbases'] == ['linux']


def test_report_detail_for_maintainer(developer_client, reports, linux_maintainer_relation):
    username = linux_maintainer_relation.user.username
    response = developer_client.get(f'{API_PREFIX}/old/{username}/')
    assert response.status_code == 200
    data = response.json()
    assert data['maintainer'] == username
    assert data['count'] == 1
    assert data['packages'][0]['pkgname'] == 'linux'


def test_report_detail_ignores_maintainer_for_non_personal_report(developer_client, reports,
                                                                linux_maintainer_relation):
    username = linux_maintainer_relation.user.username
    global_response = developer_client.get(f'{API_PREFIX}/unneeded-orphans/')
    filtered_response = developer_client.get(f'{API_PREFIX}/unneeded-orphans/{username}/')
    assert global_response.json()['count'] == filtered_response.json()['count']


def test_report_detail_unknown_maintainer(developer_client, reports):
    response = developer_client.get(f'{API_PREFIX}/old/nobody/')
    assert response.status_code == 404
