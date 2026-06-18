# Developer Reports Filter Behavior

The developer report pages (`/devel/reports/<slug>/`) include client-side arch/repo
filters. This document explains how they work and why certain checkbox combinations
show no results.

## Subtractive, not additive

The filter is **subtractive**: it hides rows that match **unchecked** filters.
It does not show rows that match **checked** filters.

On page load the table contains all packages returned by the report. JavaScript
then hides rows based on the filter form.

Mental model: *“Hide packages matching unchecked filters”* — not *“Show packages
matching checked filters.”*

## How rows are matched

Each table row gets CSS classes from the package’s architecture and repository:

```html
<tr class="x86_64 core">
```

Filter checkboxes use the same values (`x86_64`, `core`, etc.). The logic in
`sitestatic/archweb.js` (`filter_pkgs_list`) does the following:

1. Start with all rows in the table body.
2. For every **unchecked** arch or repo checkbox, remove rows with that CSS class.
3. Hide all rows, then show only the rows that survived.

```javascript
if (!$(this).is(':checked')) {
    rows = rows.not('.' + $(this).val());
}
```

Checked boxes do not add rows. Unchecked boxes remove them.

## Why “Arch any” alone shows nothing

In Arch Linux, `any` is a real architecture for architecture-independent packages
(e.g. data-only packages). It is not a wildcard meaning “all architectures.”

Most packages — including fixture data and typical report results — are built for
a specific arch such as `x86_64`. Those rows have class `x86_64`, not `any`.

If you check **only** “Arch any”:

| Checkbox      | Effect |
|---------------|--------|
| Arch any      | Checked → `.any` rows are not removed |
| Arch x86_64   | Unchecked → all `.x86_64` rows are **removed** |
| Arch i686     | Unchecked → all `.i686` rows are removed |

Report data is almost entirely `x86_64`, so it is filtered out. Unless the report
actually contains `any`-arch packages, the table ends up empty.

You also need at least one **repository** checkbox checked (e.g. Core). If every
repo is unchecked, rows with classes like `.core` or `.extra` are removed as well.

## What to check for typical local fixture data

Packages in `main/fixtures/package.json` and `devel/fixtures/reports.json` use:

- **Arch:** `x86_64`
- **Repo:** `Core`

To see those packages, both **Arch x86_64** and **[core]** should be checked.
Clicking **Reset** on the filter form checks all arches and repos currently shown
on the page.

## Saved filter state (`localStorage`)

Filter choices are saved per report slug in `localStorage` under keys like
`filter_report_non-existing-dependencies`. On reload, saved state is restored.

If saved filters reference arches or repos that are unchecked, or if stale state
does not match the current page, the table can appear empty even though the
server returned packages (a brief flash of rows before JavaScript runs).

To clear saved filters for one report, in the browser console:

```javascript
localStorage.removeItem('filter_report_non-existing-dependencies')
```

Or use the **Reset** button on the filter form.

Recent changes to `filter_report_apply()` in `archweb.js` reset filters when they
would hide all rows while data exists, and drop invalid saved state.

## Related files

| File | Role |
|------|------|
| `templates/devel/packages.html` | Filter form and table; calls `filter_report_apply()` |
| `sitestatic/archweb.js` | `filter_pkgs_list`, `filter_report_load`, `filter_report_apply` |
| `devel/fixtures/reports.json` | Test packages (all `x86_64` / Core) |
