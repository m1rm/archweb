# Authentication in Archweb

Archweb is primarily a **public** website (packages, news, releases, mirrors).
Authentication is used to gate **staff/developer tooling** and to reveal extra
data (staging repos, private mirrors, etc.) to logged-in users.

There is **no API-key or OAuth** system. Staff auth is **Django session-based**
(username + password at `/login/`). One separate mechanism uses **HTTP Basic
auth** for tier-0 mirror access via nginx.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     HTTP request                                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   Session cookie      CSRF token          Authorization:
   (sessionid)         (POST forms)        Basic (mirrorauth only)
         │                   │                   │
         └─────────┬─────────┘                   │
                   ▼                             ▼
      AuthenticationMiddleware          tier0_mirror_auth()
      → request.user                    (token in UserProfile)
                   │
     ┌─────────────┼─────────────┬──────────────────┐
     ▼             ▼             ▼                  ▼
 @login_required  @permission_  is_authenticated   django_auth
                  required       (soft checks)      (Ninja API)
```

| Mechanism | Used for | Credential |
|-----------|----------|------------|
| Django session | `/devel/`, signoffs, admin, devel API | `sessionid` cookie after `/login/` |
| Django permissions | Signoffs, flags, news edit, todo edit | Session + per-model permissions |
| Superuser check | Admin action log | Session + `is_superuser` |
| `is_authenticated` | Staging repos, mirror details, templates | Session (no extra gate) |
| HTTP Basic | `/devel/mirrorauth` (nginx `auth_request`) | `username` + `repos_auth_token` |

## Session-based login (primary mechanism)

### Login and logout

Configured in `urls.py`:

- **Login:** `GET/POST /login/` → Django `LoginView` (`registration/login.html`)
- **Logout:** `/logout/` → Django `LogoutView`
- **Redirect when unauthenticated:** `LOGIN_URL = '/login/'` (`settings.py`)
- **After login:** `LOGIN_REDIRECT_URL = '/'`

The login form is a standard Django auth form with CSRF protection:

```html
<form method="post">{% csrf_token %}
```

On success, Django creates a **server-side session** and sets the **`sessionid`**
cookie. Subsequent requests send that cookie; `AuthenticationMiddleware` attaches
`request.user`.

Unauthenticated access to protected views redirects to `/login/?next=<path>`
(see `devel/tests/test_user.py`).

### Session storage

From `settings.py`:

```python
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_COOKIE_HTTPONLY = True
```

Sessions are stored in the database with a cache layer. The cookie is
JavaScript-inaccessible (`HttpOnly`).

In production, `SESSION_COOKIE_SECURE = True` is expected (HTTPS only). Local
`local_settings.py.example` sets `SESSION_COOKIE_SECURE = False` for HTTP dev.

### Password verification

Archweb uses Django’s default **`ModelBackend`** (username/password against
`auth_user`). There are no custom `AUTHENTICATION_BACKENDS` in `settings.py`.
Password hashing follows Django defaults (PBKDF2).

User accounts are created via Django admin or the developer “Create User” form
(`/devel/newuser/`, requires `auth.add_user` permission).

## Middleware chain

Relevant middleware order in `settings.py`:

1. `SessionMiddleware` — reads/writes session
2. `CsrfViewMiddleware` — validates CSRF on unsafe methods
3. `AuthenticationMiddleware` — sets `request.user` from session

Every view receives `request.user`. For anonymous visitors,
`request.user.is_authenticated` is `False`.

## CSRF

`CsrfViewMiddleware` protects state-changing HTML forms (login, profile edit,
flag package, etc.). Settings:

```python
CSRF_COOKIE_SECURE = True   # production
CSRF_COOKIE_HTTPONLY = True
```

**GET-only JSON/API endpoints** do not require a CSRF token. The devel reports
API (`/api/v1/devel/reports/`) is read-only GET; session cookie alone is enough.

If POST endpoints are added to the Ninja API later, CSRF or an alternative would
need to be considered.

## Authorization layers

Archweb uses several patterns. They are **not interchangeable**.

### 1. `@login_required` — authenticated user

Used on most `/devel/` views (dashboard, reports, stats, clock, profile,
tier-0 mirror page).

```python
@login_required
def report(request, report_name, username=None):
    ...
```

**Requires:** valid session (any active Django user).

**Does not require:** membership in Developers / Package Maintainers / Support
Staff groups. In practice only staff have accounts, but the decorator itself only
checks `is_authenticated`.

### 2. `@permission_required` — Django model permission

Used for actions that need specific capabilities:

| Area | Permission | Example URL |
|------|------------|-------------|
| Signoffs | `packages.change_signoff` | `/packages/signoffs/` |
| Package flags | `main.change_package` | flag approval views |
| News | `news.add_news`, `change_news`, `delete_news` | `/news/` edit views |
| Todo lists | `todolists.add_todolist`, etc. | `/todo/` management |
| New user | `auth.add_user` | `/devel/newuser/` |
| Package relations | `packages.delete_packagerelation` | admin-style actions |

Permissions are assigned per user or via groups in Django admin. A user can be
logged in but still get **403 Forbidden** without the right permission.

### 3. `@user_passes_test` — custom predicate

Example: admin action log (`/devel/admin_log/`) requires **superuser**:

```python
@user_passes_test(lambda u: u.is_superuser)
def admin_log(request, username=None):
```

### 4. Soft checks — `request.user.is_authenticated`

No redirect; behavior or visibility changes:

| Feature | Logged out | Logged in |
|---------|------------|-----------|
| Package search | Hides **staging** repos | Shows staging repos |
| Homepage recent updates | Stable repos only | Includes testing/staging |
| Mirror list/details | Public, active mirrors only | All mirrors; inactive URLs |
| Mirror JSON API | Limited fields | Extra fields if `mirrors.change_mirror` |
| Package details | Hides reproducibility, flag UI | Shows developer-only rows |
| Templates | No dev navbar (`base.html`) | `devmode` body class, devel links |

`Package.objects.restricted(user)` in `main/models.py` filters staging repos for
anonymous users.

### 5. Django admin

`/admin/` uses Django’s built-in admin auth (same session). Staff need
`is_staff=True`; destructive actions often need superuser.

## Django Ninja API (`/api/`)

Mounted at `/api/` via `api/router.py`. Two routers today:

| Router | Path | Auth |
|--------|------|------|
| `releng` | `/api/v1/releng/` | **None** (public) |
| `devel` | `/api/v1/devel/` | **`django_auth`** (session) |

### Public API example

```python
# api/routes/releng.py
router = Router(tags=["releng"])  # no auth=
```

Anyone can `GET /api/v1/releng/releases/`.

### Authenticated API example

```python
# api/routes/devel.py
from ninja.security import django_auth

router = Router(tags=['devel'], auth=django_auth)
```

`django_auth` checks `request.user.is_authenticated` using the **same session
cookie** as HTML views. Unauthenticated requests get **HTTP 401** (not a
redirect to `/login/`).

**Usage with curl** (after logging in via browser, export cookies):

```bash
curl -b cookies.txt http://127.0.0.1:8000/api/v1/devel/reports/
```

Or in tests:

```python
client.login(username='joeuser', password='joeuser')
client.get('/api/v1/devel/reports/')
```

OpenAPI docs at `/api/docs/` describe endpoints; authenticated routes still
require a logged-in browser session to try them interactively.

### Legacy JSON endpoints (non-Ninja)

Older JSON URLs live on their original paths and mostly follow the **same
visibility rules** as their HTML siblings:

| Endpoint | Auth |
|----------|------|
| `/releng/releases/json/` | Public (deprecated → `/api/v1/releng/releases/`) |
| `/packages/.../json/` | Public |
| `/mirrors/.../json/` | Public; extra fields when logged in |
| `/master-keys/json/` | Public |
| `/todo/<slug>/json` | Uses session for write; read varies |
| `/api/v1/devel/reports/` | **Session required** |

There is no separate “API user” or token for these.

## Tier-0 mirror authentication (separate from sessions)

Documented in `docs/mirror_access.md`. This is **not** browser session auth.

1. Developer logs in normally and visits `/devel/tier0mirror/`.
2. Page shows/generates a **`repos_auth_token`** stored on `UserProfile`.
3. nginx calls `/devel/mirrorauth` with **HTTP Basic** `username:token`.
4. View validates:
   - User is active
   - User is in **Developers**, **Package Maintainers**, or **Support Staff**
   - Token matches `user.userprofile.repos_auth_token`

```python
SELECTED_GROUPS = ['Developers', 'Package Maintainers', 'Support Staff']
```

Optional `TIER0_MIRROR_SECRET` (`X-Sent-From` header) limits who can hit the
auth endpoint. Response is cached 5 minutes (`cache_control(max_age=300)`).

This path does **not** use `@login_required`; it uses Basic credentials only.

## Groups vs permissions

| Concept | Purpose |
|---------|---------|
| **Groups** (`Developers`, `Package Maintainers`, …) | Public staff pages, planet feeds, tier-0 mirror eligibility, `allowed_repos` on profile |
| **Permissions** (`main.change_package`, …) | Fine-grained action gates on specific views |
| **`@login_required`** | Any authenticated account |

Tests often use the **`developer`** fixture (`conftest.py`): creates a user,
adds them to the **Developers** group, and logs them in via `developer_client`.

Group membership alone does **not** automatically grant model permissions;
those are configured separately in Django admin.

## Developer reports: HTML vs API parity

Both use the same session requirement:

| Interface | Enforcement |
|-----------|-------------|
| `/devel/reports/<slug>/` | `@login_required` on `devel.views.report` |
| `/api/v1/devel/reports/<slug>/` | `auth=django_auth` on the Ninja router |

Same data layer (`devel/report_data.py`); same login cookie.

## Caching and auth

`cache_user_page()` (`main/utils.py`) disables page caching for authenticated
users so logged-in content (e.g. staging) is not served from a anonymous cache
entry.

Template fragments may key on `user.is_authenticated` (e.g. homepage updates).

## Local development

1. Create a user (Django admin or shell).
2. Optionally add to **Developers** group for realistic staff setup.
3. Log in at `http://127.0.0.1:8000/login/`.
4. Access `/devel/` or `/api/v1/devel/reports/` in the same browser session.

For local HTTP, ensure `local_settings.py` has:

```python
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
```

Otherwise the session cookie may not be sent over `http://127.0.0.1`.

Run commands via the project env:

```bash
uv run python manage.py createsuperuser
```

## Security notes

- **No bearer tokens** for the main site or Ninja API today.
- **Session cookie** is the sole credential for devel API and HTML tools.
- **mirrorauth** uses a long-lived per-user token (regeneratable on tier-0 page);
  intended for nginx only, not general API access.
- Production should use **HTTPS** with secure cookies enabled.
- Rate limiting on auth failures is delegated to nginx for mirrorauth; Django
  login uses standard auth throttling only if configured upstream.

## Related files

| File | Role |
|------|------|
| `settings.py` | `LOGIN_URL`, session/CSRF cookie settings, middleware |
| `urls.py` | Login/logout routes, `/api/` mount |
| `api/routes/devel.py` | `django_auth` on devel reports API |
| `api/routes/releng.py` | Public API (no auth) |
| `devel/views.py` | `@login_required`, tier-0 mirror auth |
| `docs/mirror_access.md` | nginx + Basic auth for mirrors |
| `conftest.py` | `developer` / `developer_client` test fixtures |
| `devel-reports-json-api.md` | Devel reports API design and auth note |
