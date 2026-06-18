# Testing the Devel Reports JSON API Locally

The `/api/v1/devel/reports/` endpoints use **Django session auth** — the same
login cookie as the HTML developer pages. Log in with `curl` first, then reuse
the cookie file for API requests.

Prerequisites:

- Dev server running: `uv run python manage.py runserver`
- A local user account (e.g. from `uv run python manage.py createsuperuser`)
- Optional fixture data for non-empty reports:

  ```bash
  uv run python manage.py loaddata main/fixtures/arches.json \
      main/fixtures/repos.json main/fixtures/package.json \
      devel/fixtures/reports.json
  ```

For plain HTTP locally, `local_settings.py` should have:

```python
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
```

## 1. Log in and save the session

```bash
cd ~/projects/archweb

# Fetch login page + CSRF cookie
curl -s -c /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/login/ \
  -o /tmp/login.html

# Extract CSRF token (replace username/password with your local user)
CSRF=$(grep -oP 'name="csrfmiddlewaretoken" value="\K[^"]+' /tmp/login.html)

curl -s -b /tmp/archweb-cookies.txt -c /tmp/archweb-cookies.txt \
  -X POST http://127.0.0.1:8000/login/ \
  -H "Referer: http://127.0.0.1:8000/login/" \
  -d "username=YOUR_USER&password=YOUR_PASSWORD&csrfmiddlewaretoken=${CSRF}"
```

On success, `/tmp/archweb-cookies.txt` contains a `sessionid` cookie.

## 2. Confirm auth (401 without cookies)

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:8000/api/v1/devel/reports/
```

Expected: `401`

## 3. List all reports

```bash
curl -s -b /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/api/v1/devel/reports/ | jq .
```

Without `jq`:

```bash
curl -s -b /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/api/v1/devel/reports/
```

## 4. Report detail

```bash
# Non-existing dependencies (good test case with fixtures loaded)
curl -s -b /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/api/v1/devel/reports/non-existing-dependencies/ | jq .

# Old packages
curl -s -b /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/api/v1/devel/reports/old/ | jq .

# Package names and report-specific extras only
curl -s -b /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/api/v1/devel/reports/non-existing-dependencies/ \
  | jq '{count, packages: [.packages[] | {pkgname, extras}]}'
```

## 5. Pkgbases endpoint

```bash
curl -s -b /tmp/archweb-cookies.txt \
  http://127.0.0.1:8000/api/v1/devel/reports/old/pkgbases/ | jq .
```

## 6. Maintainer-filtered report (personal reports)

```bash
# Replace YOUR_USER with the maintainer username
curl -s -b /tmp/archweb-cookies.txt \
  "http://127.0.0.1:8000/api/v1/devel/reports/old/YOUR_USER/" | jq .

curl -s -b /tmp/archweb-cookies.txt \
  "http://127.0.0.1:8000/api/v1/devel/reports/old/YOUR_USER/pkgbases/" | jq .
```

## 7. Error cases

```bash
# Unknown report → 404
curl -s -b /tmp/archweb-cookies.txt -w "\nHTTP %{http_code}\n" \
  http://127.0.0.1:8000/api/v1/devel/reports/does-not-exist/

# Unknown maintainer → 404
curl -s -b /tmp/archweb-cookies.txt -w "\nHTTP %{http_code}\n" \
  http://127.0.0.1:8000/api/v1/devel/reports/old/nobody/
```

## 8. OpenAPI docs (browser)

While logged in, open:

http://127.0.0.1:8000/api/docs/

## Troubleshooting

| Problem | Likely cause |
|---------|----------------|
| `/api/docs/` blank page | CSP blocks CDN scripts when `ninja` is missing from `INSTALLED_APPS` — use local Swagger static files (see below) |
| `401` on API calls | Session expired or login failed — repeat step 1 |
| `403` on login POST | CSRF/secure cookie settings incompatible with HTTP |
| `"count": 0` | Fixtures not loaded, or no matching data in the DB |
| Login works in browser but not curl | Different cookie jar — use `-b /tmp/archweb-cookies.txt` on every API call |

### Blank `/api/docs/` page

Archweb’s Content-Security-Policy only allows scripts from `'self'`. Without
`ninja` in `INSTALLED_APPS`, Django Ninja serves Swagger UI from a CDN
(`cdn.jsdelivr.net`), which the browser blocks — you get an empty page.

`settings.py` includes `'ninja'` in `INSTALLED_APPS` so docs load
`/static/ninja/swagger-ui-*.js` from the same origin. Restart `runserver` after
changing settings. With `DEBUG = True`, Django serves those static files
automatically.

## See also

- [devel-reports-json-api.md](devel-reports-json-api.md) — API design and response format
- [auth-mechanism.md](auth-mechanism.md) — how session auth works in archweb
