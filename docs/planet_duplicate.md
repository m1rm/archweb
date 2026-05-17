# Planet Subscribe list: duplicate person entries

On `/planet`, the **Subscribe** sidebar can show the same person twice in production. That is not a template bug: the list renders every row in the `feeds` table with no deduplication. Duplicate names mean duplicate `Feed` records in the database.

## When a duplicate can appear

A duplicate shows up when **two `Feed` rows exist for one person**. The Subscribe list prints one line per row, so the same name appears twice.

Feeds are tied to an **RSS URL**, not to a user account. When a profile is saved, `create_feed_model` only deletes feeds whose `website_rss` matches the **old** value on the profile, then inserts a new row for the **new** URL. Anything that leaves an old row in place while adding another produces a duplicate.

### Scenario A — Feed URL moved by cron, profile still has the old URL (most common in production)

1. Profile has `website_rss = https://old.example/feed.xml`.
2. One `Feed` row exists with that URL.
3. `update_planet` fetches the feed; the server returns **301** and the command updates the row to `https://new.example/feed.xml` (profile is **not** updated).
4. The developer later saves their profile. The profile still has the old URL, or they update it to the new URL.
5. On save, delete runs for `website_rss = old URL` — **no row matches** (the feed row already has the new URL).
6. `Feed.objects.create(...)` adds a **second** row (often with the new URL).

**Result:** two rows, same person (same `title`), usually two different `website_rss` values.

### Scenario B — Developer changes RSS URL on their profile

1. Profile changes from URL **A** to URL **B**.
2. Delete removes rows with `website_rss = A`.
3. Create adds a row for **B**.

A duplicate appears only if a row for **B** already existed (for example left over from Scenario A, or from an earlier partial fix). Delete does not touch rows with `website_rss = B`, so you end up with two rows both pointing at **B**.

### Scenario C — Duplicate already exists; profile is saved again without changing RSS

1. Two `Feed` rows already exist (from A or B).
2. Developer saves profile; `website_rss` is unchanged.
3. `create_feed_model` returns early and **does not delete or merge** anything.

**Result:** both rows stay; Subscribe still lists the person twice. This path does not *create* a duplicate, but it explains why one can persist.

### Scenario D — First time or manual data

Less common: a `Feed` row was inserted manually (admin, migration, script) while `create_feed_model` also created one for the same URL or person. There is no uniqueness check on `website_rss` or on user identity.

### Quick reference

| What happened | Delete finds old row? | New row created? | Duplicate? |
|---------------|----------------------|------------------|--------------|
| `update_planet` 301 updates feed URL; profile save follows | Often **no** (delete uses profile’s old URL) | **Yes** | **Yes** |
| Profile RSS changes A → B; row for B already exists | Only rows with A | **Yes** | **Yes** |
| Profile saved; RSS unchanged; two rows already exist | N/A (handler exits) | **No** | Stays |
| Profile RSS changes A → B; no row for B yet | Rows with A removed | One row for B | **No** |

## Where the list is built

**Template** — `templates/planet/index.html`:

```html
<h4>Subscribe</h4>
<ul class="planet-list">
  {% for feed in official_feeds %}
  <li>
    <a href="{{ feed.website }}" title="{{ feed.title }}">{{ feed.title }}</a>
  </li>
  {% endfor %}
</ul>
```

**View** — `planet/views.py`:

```python
def index(request):
    context = {
        'official_feeds': Feed.objects.all(),
        'planets': Planet.objects.all(),
        'feed_items': FeedItem.objects.order_by('-publishdate')[:25],
    }
    return render(request, 'planet/index.html', context)
```

`Feed.objects.all()` returns every feed row; there is no `distinct()` or merge by user.

## Where duplicate `Feed` rows come from

The only code that **creates** `Feed` rows is the `UserProfile` `pre_save` handler in `devel/models.py` (`create_feed_model`):

```python
def create_feed_model(sender, **kwargs):
    ...
    if obj.website_rss == dbmodel.website_rss:
        return

    title = obj.alias
    if obj.user.first_name and obj.user.last_name:
        title = obj.user.first_name + ' ' + obj.user.last_name

    Feed.objects.filter(website_rss=dbmodel.website_rss).all().delete()
    Feed.objects.create(title=title, website=website, website_rss=obj.website_rss)
```

Relevant model facts (`planet/models.py`):

- `Feed` has no foreign key to `User`.
- `website_rss` is not unique.
- Rows are keyed only by RSS URL and display title.

### Implementation detail

The scenarios above follow from this logic in `create_feed_model`:

- **Delete** uses only `dbmodel.website_rss` (profile value *before* save), not the user id and not the feed row’s current URL if something else changed it.
- **Create** always adds a row when the profile RSS URL changed; there is no “update in place” or “only one feed per user” rule.
- **No-op** when `obj.website_rss == dbmodel.website_rss` — duplicates are not cleaned up.

`update_planet` can change a feed URL independently of the profile:

```python
if http_status == 301:
    feed_instance.website_rss = feed.href
    feed_instance.save()
```

That is what triggers Scenario A.

## Confirming in production

Inspect the `feeds` table for two rows with the same `title` (or the same person’s name) and different `website_rss` values.

Example:

```sql
SELECT title, website, website_rss FROM feeds WHERE title = 'Person Name';
```

## Code map

| Layer | File | Role |
|-------|------|------|
| Display | `templates/planet/index.html` | Renders every `official_feeds` entry under Subscribe |
| Query | `planet/views.py` | `Feed.objects.all()` |
| Data creation | `devel/models.py` → `create_feed_model` | Creates `Feed` rows; deletes only by old `website_rss` |
| URL drift | `planet/management/commands/update_planet.py` | Can update `Feed.website_rss` on HTTP 301 without updating the profile |

## Fix plan

Goal: **at most one `Feed` per staff user**, with the profile as source of truth for URL and title, and `update_planet` not leaving orphaned rows.

The three root issues in code:

| Issue | Fix |
|-------|-----|
| Delete by old URL only | Delete (and sync) by `user`, not only `dbmodel.website_rss` |
| Create always adds a row | `update_or_create` keyed on `user` |
| No per-user dedupe | `OneToOneField` from `Feed` to `User` + sync on every relevant profile save |

---

### Phase 0 — Confirm production state

1. **Find duplicates** (before changing code):

   ```sql
   SELECT title, COUNT(*) AS n, GROUP_CONCAT(website_rss) AS urls
   FROM feeds
   GROUP BY title
   HAVING n > 1;
   ```

   Also list rows with the same `website_rss`:

   ```sql
   SELECT website_rss, COUNT(*) FROM feeds
   WHERE website_rss IS NOT NULL AND website_rss != ''
   GROUP BY website_rss HAVING COUNT(*) > 1;
   ```

2. For each duplicate, note which row has `FeedItem`s (keep that one when merging).
3. Decide merge policy: **one feed per `UserProfile`**, keep the row with items (or newest), reassign `FeedItem.feed_id`, delete the extra `Feed` row.

---

### Phase 1 — Model: tie `Feed` to a user

4. Add nullable FK on `Feed` in `planet/models.py`:

   ```python
   user = models.OneToOneField(
       'auth.User', null=True, blank=True, on_delete=models.CASCADE,
       related_name='planet_feed',
   )
   ```

   (`OneToOneField` enforces one feed per user at the DB level once backfilled.)

5. Add a Django migration for the new column (nullable first).

6. **Backfill** in a data migration or management command:

   - Match `Feed` → `UserProfile` by `website_rss` (and optionally `title`).
   - Unmatched rows: manual review or delete if clearly orphan.
   - For duplicate users (two feeds, one profile): merge per Phase 0, set `user_id` on the survivor.

7. After backfill and dedupe in production, add a migration to make `user` **non-null** for rows that must exist (or keep nullable only for legacy orphans you delete).

8. Optional: `UniqueConstraint` on `website_rss` where not null (two people must not share one RSS URL; confirm that is acceptable for the project).

---

### Phase 2 — Centralize feed sync (replace delete-by-URL + create)

9. Add a small helper module (e.g. `devel/planet_feeds.py`):

   - `sync_planet_feed(profile) -> None`
   - `delete_planet_feed(profile) -> None`

   **`sync_planet_feed`** should:

   - If user not in staff groups → delete any `Feed` for `profile.user`, return.
   - If no `website_rss` → delete feed for that user, return.
   - Compute `title` / `website` (same logic as today in `create_feed_model`).
   - Use **`update_or_create`** on `user=profile.user`, with defaults `{title, website, website_rss}`.
   - **Delete any other `Feed` rows** for that `user_id` if more than one exists (safety net during transition).

   **`delete_planet_feed`**: `Feed.objects.filter(user=profile.user).delete()` (cascades `FeedItem`s — acceptable when a user is removed from the planet).

10. Replace the `create_feed_model` body with calls to `sync_planet_feed` / `delete_planet_feed`:

    - Run when `website_rss`, `website`, name fields, or group membership matter — not only when `website_rss` changed.
    - When `website_rss == dbmodel.website_rss`, still call **`sync_planet_feed`** (updates title/website, heals duplicates).
    - On clear RSS: `delete_planet_feed`.
    - Consider **`post_save`** instead of **`pre_save`** so `profile.user` and groups are stable (optional; test both).

11. Update **`delete_user_model`** in `devel/models.py`: use `Feed.objects.filter(user=obj).delete()` instead of `Feed.objects.filter(website_rss=userprofile.website_rss).delete()`.

12. When a user **loses** staff group membership: delete feed by `user`, not only when RSS is cleared.

---

### Phase 3 — `update_planet` and URL drift

13. On **HTTP 301** in `planet/management/commands/update_planet.py`, do not only update `Feed.website_rss`:

    - If `feed.user` is set: set matching `UserProfile.website_rss = feed.href` and call `sync_planet_feed(profile)` (single row, profile and feed aligned).
    - If `feed.user` is null (legacy): update feed URL in place or log for manual fix.

14. Alternative (stricter): never mutate `Feed.website_rss` in cron; log 301 and fix the profile manually. The sync approach in step 13 is preferable if `update_planet` remains scheduled.

15. Clear the etag cache key for the old URL when the URL changes (`planet:etag:{url}`).

---

### Phase 4 — One-time production cleanup

16. Add management command `dedupe_planet_feeds` (dry-run by default):

    - Group feeds by `user_id` (after backfill) or by normalized `website_rss`.
    - Merge `FeedItem`s onto the canonical feed, delete extras.
    - Report rows with no `user_id`.

17. Run on production: `--dry-run` → review → run for real. Coordinate with deploy (see order below).

---

### Phase 5 — Tests

18. Add `devel/tests/test_planet_feed.py` (or extend `devel/tests/test_user.py`):

    - Staff user sets `website_rss` → one `Feed`, correct fields.
    - Change `website_rss` A → B → still one feed, URL B; items stay on same feed pk when using `update_or_create` on `user`.
    - Save profile without RSS change → still one feed; title updates when name changes.
    - Clear RSS → no feed.
    - Remove from staff group → no feed.
    - Inactive user → feed removed.
    - Scenario that previously created an orphan: only one feed for that user.

19. Extend `planet/tests/test_command.py`:

    - 301 with `feed.user` set → profile `website_rss` updated, still one feed.

20. Run the full test suite.

---

### Phase 6 — Admin and ops

21. **Feed admin** (`planet/admin.py`): expose `user` (read-only or autocomplete from profile); discourage creating feeds without `user`. Optional: disable “add” in admin.

22. Invalidate **template cache** for the planet sidebar after deploy/dedupe (`{% cache 115 planet-page-right %}` in `templates/planet/index.html`).

23. Update this document when the fix is deployed (mark phases done, note any production-specific decisions).

---

### Deploy order

| Step | Action |
|------|--------|
| 1 | Deploy migration (nullable `user` on `Feed`) |
| 2 | Run backfill + `dedupe_planet_feeds` on production |
| 3 | Deploy application code: `sync_planet_feed`, `update_planet` 301 fix, tests |
| 4 | Optional migration: non-null `user`, unique `website_rss` |
| 5 | Verify `/planet` Subscribe list; spot-check RSS import via `update_planet` |

---

### Minimal vs full fix

| Approach | Effort | What it fixes |
|----------|--------|----------------|
| **Minimal** | Low | `update_or_create` keyed by `website_rss` + delete other rows with same `website_rss`; fix 301 to update profile; one-off SQL dedupe. Does not fully fix two different URLs per user. |
| **Recommended** | Medium | `Feed.user` `OneToOneField` + `sync_planet_feed` + 301 sync + `dedupe_planet_feeds` command + tests. |

Use the **recommended** path unless there is a hard constraint on schema changes.

---

### Duplicates without cron

If `update_planet` is never run, duplicates can still be created or left in place:

| Mechanism | Needs cron? |
|-----------|-------------|
| Profile RSS changes A → B while a row for B already exists | No |
| Orphan feed row (admin/SQL/legacy) + profile save | No |
| Manual/admin duplicate + profile `create` | No |
| Duplicate already in DB; profile saved, RSS unchanged | No (persists; does not create) |

Cron mainly adds Scenario A (301 updates feed URL while profile keeps the old URL). The recommended fix addresses both cron and non-cron paths via `Feed.user` and `sync_planet_feed`.
