# Developer Reports JSON API

This document describes the `/api/v1/devel/reports/` API added for all developer
reports, the refactoring that supports it, and the reasoning behind each
design choice.

## Motivation

Developer reports were previously HTML-only (`/devel/reports/<slug>/`). The
project is moving toward JSON APIs under Django Ninja (`/api/v1/…`), following
the pattern established by releng releases.

Goals for this change:

1. Expose all 13 developer reports as structured JSON.
2. Share logic between the HTML views and the API (DRY).
3. Add fixtures and tests so reports can be verified without production data.
4. Fix maintainer filtering that was inconsistent in the old HTML views.

## API Endpoints

All endpoints require an authenticated Django session (`django_auth`). Unauthenticated
requests receive HTTP 401.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/devel/reports/` | List all available reports (metadata only) |
| GET | `/api/v1/devel/reports/<slug>/` | Full report data |
| GET | `/api/v1/devel/reports/<slug>/<username>/` | Report filtered to a maintainer (personal reports only) |
| GET | `/api/v1/devel/reports/<slug>/pkgbases/` | Pkgbases in the report (JSON) |
| GET | `/api/v1/devel/reports/<slug>/<username>/pkgbases/` | Pkgbases for a maintainer |

OpenAPI docs are available at `/api/docs/` once the dev server is running.

### Example: list reports

```http
GET /api/v1/devel/reports/
```

```json
{
  "version": 1,
  "reports": [
    {
      "slug": "non-existing-dependencies",
      "name": "Non existing dependencies",
      "description": "Packages that have dependencies that do not exists in the repository",
      "personal": false,
      "columns": ["Non existing dependency"]
    }
  ]
}
```

### Example: report detail

```http
GET /api/v1/devel/reports/non-existing-dependencies/
```

```json
{
  "version": 1,
  "slug": "non-existing-dependencies",
  "name": "Non existing dependencies",
  "description": "Packages that have dependencies that do not exists in the repository",
  "personal": false,
  "maintainer": null,
  "count": 1,
  "arches": ["x86_64"],
  "repos": ["Core"],
  "columns": ["Non existing dependency"],
  "packages": [
    {
      "arch": "x86_64",
      "repo": "Core",
      "pkgname": "missing-dep-holder",
      "pkgbase": "missing-dep-holder",
      "version": "1.0-1",
      "last_update": "2024-01-01",
      "build_date": "2024-01-01",
      "flag_date": null,
      "extras": {
        "nonexistingdep": "ghost-dependency"
      }
    }
  ]
}
```

### Response shape notes

- **Standard package fields** mirror the HTML table columns: arch, repo, pkgname,
  version (`full_version`), last_update, build_date, flag_date.
- **`extras`** holds report-specific columns keyed by the internal attribute name
  from `DeveloperReport.attrs` (e.g. `nonexistingdep`, `compressed_size_pretty`).
- **Linkify values** (reproducible-build reports) are serialized as objects:
  `{"href": "…", "title": "…", "text": "…"}` instead of raw HTML.
- **User references** (e.g. `packager`, `sig_by`) are serialized as usernames.

## Architecture

### Before

```
devel/reports.py     → report query functions + DeveloperReport definitions
devel/views.py       → get_report_packages(), report(), report_pkgbases()
                     → duplicated slug lookup, inconsistent maintainer filtering
```

### After

```
devel/reports.py       → report definitions + REPORTS_BY_SLUG lookup table
devel/report_data.py   → shared data access + JSON serialization helpers
devel/views.py         → thin HTML views using collect_report_data()
api/schemas/devel.py   → Pydantic response schemas
api/routes/devel.py    → Django Ninja router
api/router.py          → mounts /v1/devel/
```

The HTML views and API both call `collect_report_data()` so they always return
the same package set for a given slug and optional maintainer.

## Files changed

### New: `devel/report_data.py`

Central data layer extracted from `devel/views.py`:

| Function | Purpose |
|----------|---------|
| `get_report_by_slug()` | O(1) lookup via `REPORTS_BY_SLUG` |
| `get_report_packages()` | Applies maintainer filter, dispatches to report query |
| `collect_report_data()` | Full report context: packages, arches, repos, maintainer |
| `serialize_package_for_report()` | Converts a `Package` + report attrs to a JSON dict |
| `serialize_extra_value()` | Handles `User`, `Linkify`, dates |
| `list_report_metadata()` | Report list for the index endpoint |

### Changed: `devel/reports.py`

- Introduced `_ALL_REPORTS` tuple and `REPORTS_BY_SLUG` dict so slug lookup is
  not rebuilt on every request.
- `available_reports()` now returns `_ALL_REPORTS` (same 13 reports as before).

### Changed: `devel/views.py`

- Removed inline `get_report_packages()` and duplicated slug-to-report dict
  construction.
- `report()` now calls `collect_report_data()` and passes the result to the
  template.
- `report_pkgbases()` uses `get_report_by_slug()` and `get_report_packages()`.

### New: `api/schemas/devel.py`

Pydantic schemas for OpenAPI validation and documentation:

- `ReportListSchema`, `ReportMetaSchema`
- `ReportDetailSchema`, `ReportPackageSchema`
- `ReportPkgbasesSchema`

### New: `api/routes/devel.py`

Django Ninja router with `auth=django_auth` (session-based, same as HTML views).

Route order matters: `pkgbases/` paths are registered before `/<username>/` so
they are not captured as usernames.

### Changed: `api/router.py`

```python
api.add_router("/v1/devel/", devel.router)
```

## Bug fix: maintainer filtering

The old `report()` view built a maintainer-filtered queryset but then called
`get_report_packages()`, which started from `Package.objects.normal()` again —
so the filter was discarded for most reports.

`get_report_packages()` now applies maintainer filtering **before** calling the
report query function when:

- the report has `personal=True`, and
- a `username` is provided.

For reports with `personal=False`, the username path segment is ignored (same
count as the global report). This matches the dashboard UI, which only offers
“yours only” links for personal reports.

## Authentication

HTML developer reports use `@login_required`. The API router uses Ninja’s
`django_auth`, which checks `request.user.is_authenticated` via the session
cookie. This keeps behavior aligned: you must be logged in as a developer to
access report data through either interface.

Releng’s public API remains unauthenticated; devel reports are intentionally
restricted.

## Fixtures

### New: `devel/fixtures/reports.json`

Supplemental fixture loaded on top of `main/fixtures/package.json`. It adds
packages and related rows designed to trigger specific reports:

| Package | Triggers report(s) |
|---------|-------------------|
| `unneeded-orphan` | `unneeded-orphans` |
| `orphan-dep-consumer` + `required-orphan` | `required-orphan` |
| `missing-dep-holder` + depend `ghost-dependency` | `non-existing-dependencies` |
| `flagged-old` (old `flag_date`) | `long-out-of-date` |
| `bad-compress` (ratio ≈ 1.0) | `badcompression` |
| `uncompressed-man-pkg` + PackageFile | `uncompressed-man` |
| `uncompressed-info-pkg` + PackageFile | `uncompressed-info` |
| `repro-fail-pkg` + RebuilderdStatus | `non-reproducible-packages` |
| `orphan-repro-fail` + RebuilderdStatus | `orphan-non-reproducible-packages` |

Existing packages in `package.json` (e.g. `linux` from 2017) still trigger
`old` and `big` without extra fixture data.

`coreutils` depends on `repro-fail-pkg` so that package is not classified as an
orphan (otherwise it would appear in both reproducible reports).

### New: `reports` pytest fixture (`conftest.py`)

```python
@pytest.fixture
def reports(db, package):
    call_command('loaddata', 'devel/fixtures/reports.json')
```

Depends on `package` so arches, repos, and base packages are loaded first.

Some scenarios still need dynamic setup in tests (e.g. `PackageRelation` for
`required-orphan`, which requires a user created by the `developer` fixture).

## Tests

### New: `api/tests/test_devel_reports.py`

33 tests covering:

- Authentication (401 without login)
- Report list metadata for all 13 slugs
- Detail endpoint for each report type with fixture assertions
- Pkgbases endpoints (global and per-maintainer)
- Maintainer filtering on personal reports
- Username ignored on non-personal reports
- 404 for unknown slug / unknown maintainer

### Extended: `devel/tests/test_reports.py`

Added HTML smoke tests for the four reports that were previously untested:

- `non-existing-dependencies`
- `required-orphan`
- `non-reproducible-packages`
- `orphan-non-reproducible-packages`

## Local development

1. Log in at `/login/` as a user in the Developers group.
2. Load fixtures (or use the test database):

   Use the project virtualenv (dependencies are not installed on system Python):

   ```bash
   .venv/bin/python manage.py loaddata main/fixtures/arches.json \
       main/fixtures/repos.json main/fixtures/package.json \
       devel/fixtures/reports.json
   ```

   Or activate the venv first: `source .venv/bin/activate`, then `python manage.py …`.

3. Request the API:

   ```bash
   curl -b cookies.txt http://127.0.0.1:8000/api/v1/devel/reports/non-existing-dependencies/
   ```

Without `reports.json`, `non-existing-dependencies` returns `"count": 0` — that
is expected when no package depends on a missing dependency.

## Intentionally not included

- **No legacy `/devel/reports/…/json/` endpoint.** Unlike releng, there was no
  prior JSON URL to deprecate. Consumers should use `/api/v1/devel/reports/`.
- **No OpenAPI auth scheme beyond session cookies.** Token/API-key auth is out of
  scope for this change.
- **Signature reports (`mismatched-signature`, `signature-time`)** are covered by
  auth/404 tests but not by fixture data — they need real PGP signature bytes
  and `DeveloperKey` rows, which are awkward to maintain in JSON fixtures.

## All supported report slugs

| Slug | Personal |
|------|----------|
| `old` | yes |
| `long-out-of-date` | yes |
| `big` | yes |
| `badcompression` | yes |
| `uncompressed-man` | yes |
| `uncompressed-info` | yes |
| `unneeded-orphans` | no |
| `required-orphan` | yes |
| `mismatched-signature` | yes |
| `signature-time` | yes |
| `non-existing-dependencies` | no |
| `non-reproducible-packages` | yes |
| `orphan-non-reproducible-packages` | no |
