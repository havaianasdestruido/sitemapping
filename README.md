# GH Sitemap Generator

A GitHub Actions workflow that builds a point-in-time report from public GitHub profile data and exports it as Markdown, CSV, JSON, and JSONL.

## Explore the report

- **Website:** [havaianasdestruido.github.io/sitemapping](https://havaianasdestruido.github.io/sitemapping/)
- **Full generated report:** [REPORT.md](REPORT.md)
- **Structured exports:** [`reports/`](reports/)

The website includes a searchable dataset explorer and downloads for all generated categories. The exports are static snapshots; opening the site does not make live GitHub API requests. For a local preview, run `python scripts/preview_server.py`; use `--host 0.0.0.0` in a proxied development environment.

## WebMCP support

The explorer progressively registers five tools through the current imperative WebMCP API (`document.modelContext.registerTool()`) when a compatible browser/runtime makes it available. They cover the report overview, repository search and details, category search, and bounded dataset pages. Tools read only committed public exports; search/page tools may change the visible filter or selection temporarily, but never modify report data. Normal website functionality does not depend on WebMCP support.

Tool results can contain user-authored repository, issue, and commit text, so they are explicitly marked as untrusted. Tool inputs are validated, dataset access is allowlisted, results are bounded, and the site does not expose write actions, GitHub credentials, cross-origin tools, a remote MCP server, or an automatically loaded polyfill. See [the WebMCP tool catalog and security notes](https://havaianasdestruido.github.io/sitemapping/webmcp.html).

WebMCP is an experimental browser API. This site implements the page-scoped tool API; it does not treat the prompts/resources/sampling features of separate WebMCP or MCP-B libraries as part of the browser standard.

## Report categories

The report contains repository, branch, commit, issue, pull request and pull-request commit, fork, stargazer, watcher, contributor, release and release-asset, language, follower, following, and starred-repository records (16 categories). Each category is exported in CSV, JSON, and JSONL form.

## Generator reliability

The analyzer validates the profile response before generating files, uses bounded connection/read timeouts with retries for transient request failures, and atomically replaces each report/export file to avoid partial files. Category-level API failures are recorded in the GitHub Actions warnings so incomplete snapshots are visible in the run logs.

## Star history

<a href="https://www.star-history.com/?repos=havaianasdestruido%2Fsitemapping&type=date&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=havaianasdestruido/sitemapping&type=date&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=havaianasdestruido/sitemapping&type=date&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=havaianasdestruido/sitemapping&type=date&legend=top-left" />
  </picture>
</a>
