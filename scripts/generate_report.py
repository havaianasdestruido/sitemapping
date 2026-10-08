import os
import sys
import csv
import json
import time
import tempfile
import html
import re
import requests
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlsplit

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

TOKEN = os.environ.get("GITHUB_TOKEN")
USERNAME = os.environ.get("GITHUB_ACTOR")

if not TOKEN or not USERNAME:
    print("ERROR: GITHUB_TOKEN and GITHUB_ACTOR must be set.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

BASE_URL = "https://api.github.com"
OUTPUT_DIR = "reports"

MAX_COMMITS_PAGES = 4      # how many commit pages to list per branch
MAX_ISSUES = 20            # max issues to list per repo
MAX_PRS = 20               # max PRs to list per repo
MAX_BRANCHES = 8           # max branches to list per repo

# Acumula os registros de cada categoria em paralelo à geração do Markdown.
# Cada valor é uma lista de dicts com o MESMO conjunto de chaves (exigência do CSV).
DATA = {
    "repos": [],
    "branches": [],
    "commits": [],
    "issues": [],
    "pull_requests": [],
    "pull_request_commits": [],
    "forks": [],
    "stargazers": [],
    "watchers": [],
    "contributors": [],
    "releases": [],
    "release_assets": [],
    "languages": [],
    "followers": [],
    "following": [],
    "starred_by_user": [],
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

# Registra toda resposta não-200 (exceto 409, que é esperado em repo vazio),
# para diagnosticar por que uma categoria ficou vazia (rate limit, 403 de
# escopo, 404 de endpoint, etc.) em vez de deixar isso passar em silêncio.
API_ERRORS = []
REPORT_GENERATED_AT = None


def safe_request(url, params=None, headers=None):
    """GET with bounded timeouts and retries for transient API failures."""
    try:
        parsed = urlsplit(url)
        trusted_url = (
            parsed.scheme.lower() == "https"
            and parsed.hostname is not None
            and parsed.hostname.lower() == "api.github.com"
            and not parsed.username
            and not parsed.password
            and (parsed.port is None or parsed.port == 443)
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        trusted_url = False
    if not trusted_url:
        print("  Refusing a request outside the trusted GitHub API origin.")
        API_ERRORS.append({"url": "<blocked non-API URL>", "status": "blocked_untrusted_url", "body": ""})
        return []

    request_headers = {**HEADERS, **(headers or {})}
    last_failure = None
    for attempt in range(5):
        try:
            response = requests.get(
                url,
                headers=request_headers,
                params=params,
                timeout=(5, 30),
            )
        except requests.RequestException as error:
            last_failure = {"url": url, "status": "request_error", "body": str(error)[:200]}
            if attempt < 4:
                wait = min(2 ** attempt, 8)
                print(f"  Temporary request failure. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            break

        if response.status_code == 200:
            try:
                return response.json()
            except (ValueError, requests.RequestException) as error:
                API_ERRORS.append({"url": url, "status": "invalid_json", "body": str(error)[:200]})
                print(f"  Warning: invalid JSON response on {url}")
                return []
        if response.status_code == 409:
            # Empty repository or a GitHub conflict is expected for these read endpoints.
            return []
        if response.status_code == 403 and "rate limit" in response.text.lower():
            wait = 60 * (attempt + 1)
            print(f"  Rate limited. Waiting {wait}s...")
            time.sleep(wait)
            continue
        if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < 4:
            wait = min(2 ** attempt, 8)
            print(f"  GitHub returned {response.status_code}. Retrying in {wait}s...")
            time.sleep(wait)
            continue

        print(f"  Warning: {response.status_code} on {url}")
        API_ERRORS.append({"url": url, "status": response.status_code, "body": response.text[:200]})
        return []

    if last_failure:
        API_ERRORS.append(last_failure)
        return []
    API_ERRORS.append({"url": url, "status": "rate_limit_exhausted", "body": ""})
    return []


def get_all_pages(url, max_pages=10, per_page=100):
    """Paginate through all pages of a GitHub API endpoint."""
    results = []
    page = 1
    while page <= max_pages:
        data = safe_request(url, params={"per_page": per_page, "page": page})
        if not data:
            break
        results.extend(data)
        if len(data) < per_page:
            break
        page += 1
    return results


def commit_page_url(owner, repo, branch, after_sha=None, per_page=35):
    """Build a GitHub commits page URL with optional 'after' param."""
    base = f"https://github.com/{quote(str(owner), safe='-._~')}/{quote(str(repo), safe='-._~')}"
    base += f"/commits/{quote(str(branch), safe='/-._~')}"
    if after_sha:
        return f"{base}/?{urlencode({'after': f'{after_sha} {per_page - 1}'})}"
    return base


def github_repo_url(owner, repo, *path_parts):
    """Build a path beneath a GitHub repository without allowing URL syntax injection."""
    base = f"https://github.com/{quote(str(owner), safe='-._~')}/{quote(str(repo), safe='-._~')}"
    encoded = []
    for index, part in enumerate(path_parts):
        allowed = "/-._~" if index == len(path_parts) - 1 else "-._~"
        encoded.append(quote(str(part), safe=allowed))
    return base + ("/" + "/".join(encoded) if encoded else "")


def indent(level):
    return "  " * level


def esc(text):
    """Render untrusted values as one safe Markdown text fragment.

    GitHub names, descriptions, issue titles, and commit messages are external
    data. Flatten newlines, HTML-escape first (to stop raw HTML), then escape
    Markdown punctuation so data cannot create headings, links, or emphasis.
    """
    value = " ".join(str("" if text is None else text).replace("\x00", "").split())
    value = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|:/?+>~=])", r"\\\1", value)


def code_span(text):
    """Create a safe CommonMark code span for an untrusted value."""
    value = " ".join(str("" if text is None else text).replace("\x00", "").split())
    if not value:
        return "—"
    runs = re.findall(r"`+", value)
    fence = "`" * (max((len(run) for run in runs), default=0) + 1)
    padding = " " if value.startswith(("`", " ")) or value.endswith(("`", " ")) else ""
    return f"{fence}{padding}{value}{padding}{fence}"


SAFE_MARKDOWN_HOSTS = {
    "github.com",
    "avatars.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


def safe_markdown_url(value):
    """Return an encoded HTTPS link for an allowlisted GitHub host, else None."""
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 for char in value):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            return None
        if parsed.hostname.lower() not in SAFE_MARKDOWN_HOSTS:
            return None
        if parsed.username or parsed.password or (parsed.port and parsed.port != 443):
            return None
    except ValueError:
        return None
    return quote(value.strip(), safe=":/?#@!$&'()*+,;=%-._~")


def md_link(label, url):
    """Build a Markdown link only for a safe, allowlisted HTTPS URL."""
    safe_url = safe_markdown_url(url)
    safe_label = esc(label)
    return f"[{safe_label}](<{safe_url}>)" if safe_url else safe_label


def md_image(alt, url):
    """Build an image only from the dedicated GitHub avatar host."""
    safe_url = safe_markdown_url(url)
    if not safe_url or urlsplit(safe_url).hostname != "avatars.githubusercontent.com":
        return ""
    return f"![{esc(alt)}](<{safe_url}>)"


# ─────────────────────────────────────────────
# SECTION BUILDERS
# (cada função gera as linhas de Markdown E preenche DATA[...],
#  num único passe pelas mesmas chamadas de API)
# ─────────────────────────────────────────────

def build_commits_section(owner, repo_name, branch, level=3):
    """Lists commit pages (paginated) for a given branch."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/commits"

    page = 1
    last_sha = None

    while page <= MAX_COMMITS_PAGES:
        params = {"sha": branch, "per_page": 35, "page": page}
        data = safe_request(url, params=params)

        if not data:
            break

        page_url = commit_page_url(owner, repo_name, branch, last_sha)
        prefix = indent(level)
        lines.append(f"{prefix}- 📄 {md_link(f'Commits Page {page}', page_url)}")

        for commit in data[:10]:  # show up to 10 commits per page
            sha = commit["sha"][:7]
            msg = esc(commit["commit"]["message"].split("\n")[0][:72])
            author = commit["commit"]["author"]["name"]
            date = commit["commit"]["author"]["date"][:10]
            commit_url = github_repo_url(owner, repo_name, "commit", commit["sha"])
            lines.append(
                f"{indent(level + 1)}- {md_link(sha, commit_url)} "
                f"{msg} — {esc(author)} ({esc(date)})"
            )

            DATA["commits"].append({
                "repo": repo_name,
                "branch": branch,
                "sha": commit["sha"],
                "sha_short": sha,
                "author": author,
                "date": commit["commit"]["author"]["date"],
                "message": commit["commit"]["message"].split("\n")[0],
                "url": commit_url,
            })

        last_sha = data[-1]["sha"]

        if len(data) < 35:
            break
        page += 1

    return lines


def build_issues_section(owner, repo_name, level=2):
    """Lists open and closed issues."""
    lines = []
    lines.append(f"{indent(level)}- ### 🐛 Issues")

    for state in ["open", "closed"]:
        url = f"{BASE_URL}/repos/{owner}/{repo_name}/issues"
        issues = safe_request(url, params={"state": state, "per_page": MAX_ISSUES, "page": 1})
        issues = [i for i in issues if "pull_request" not in i] if issues else []

        lines.append(f"{indent(level + 1)}- **{state.capitalize()} Issues** ({len(issues)})")

        for issue in issues[:MAX_ISSUES]:
            num = issue["number"]
            issue_url = issue["html_url"]
            user = issue["user"]["login"]
            created = issue["created_at"][:10]
            labels = ", ".join(l["name"] for l in issue.get("labels", []))
            label_str = f" {code_span(labels)}" if labels else ""
            issue_link = md_link(f"#{num} {issue['title'][:60]}", issue_url)
            lines.append(
                f"{indent(level + 2)}- {issue_link}"
                f" — {esc(user)} ({esc(created)}){label_str}"
            )

            comments = issue.get("comments", 0)
            if comments > 0:
                lines.append(
                    f"{indent(level + 3)}- 💬 {comments} comment(s) — "
                    f"{md_link('View thread', issue_url)}"
                )

            DATA["issues"].append({
                "repo": repo_name,
                "state": state,
                "number": num,
                "title": issue["title"],
                "user": user,
                "created_at": issue["created_at"],
                "labels": labels,
                "comments": comments,
                "url": issue_url,
            })

    return lines


def build_prs_section(owner, repo_name, level=2):
    """Lists open and closed pull requests."""
    lines = []
    lines.append(f"{indent(level)}- ### 🔀 Pull Requests")

    for state in ["open", "closed"]:
        url = f"{BASE_URL}/repos/{owner}/{repo_name}/pulls"
        prs = safe_request(url, params={"state": state, "per_page": MAX_PRS, "page": 1})
        if not prs:
            prs = []

        lines.append(f"{indent(level + 1)}- **{state.capitalize()} PRs** ({len(prs)})")

        for pr in prs[:MAX_PRS]:
            num = pr["number"]
            pr_url = pr["html_url"]
            user = pr["user"]["login"]
            created = pr["created_at"][:10]
            base_branch = pr["base"]["ref"]
            head_branch = pr["head"]["ref"]
            merged = pr.get("merged_at")
            status = "✅ Merged" if merged else ("🟢 Open" if state == "open" else "🔴 Closed")
            pr_link = md_link(f"#{num} {pr['title'][:60]}", pr_url)
            lines.append(
                f"{indent(level + 2)}- {status} {pr_link}"
                f" — {esc(user)} ({esc(created)}) {code_span(head_branch)} → {code_span(base_branch)}"
            )

            pr_commits_url = f"{BASE_URL}/repos/{owner}/{repo_name}/pulls/{num}/commits"
            pr_commits = safe_request(pr_commits_url)
            if pr_commits:
                lines.append(f"{indent(level + 3)}- 📝 {len(pr_commits)} commit(s) in this PR")
                for c in pr_commits[:5]:
                    csha = c["sha"][:7]
                    cmsg = esc(c["commit"]["message"].split("\n")[0][:60])
                    c_url = github_repo_url(owner, repo_name, "commit", c["sha"])
                    lines.append(f"{indent(level + 4)}- {md_link(csha, c_url)} {cmsg}")

                    DATA["pull_request_commits"].append({
                        "repo": repo_name,
                        "pr_number": num,
                        "sha": c["sha"],
                        "sha_short": csha,
                        "message": c["commit"]["message"].split("\n")[0],
                        "url": c_url,
                    })

            DATA["pull_requests"].append({
                "repo": repo_name,
                "state": state,
                "status": "merged" if merged else state,
                "number": num,
                "title": pr["title"],
                "user": user,
                "created_at": pr["created_at"],
                "base_branch": base_branch,
                "head_branch": head_branch,
                "commit_count": len(pr_commits) if pr_commits else 0,
                "url": pr_url,
            })

    return lines


def build_forks_section(owner, repo_name, level=2):
    """Lists forks with forker info."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/forks"
    forks = get_all_pages(url, max_pages=3)

    lines.append(f"{indent(level)}- ### 🍴 Forks ({len(forks)})")

    for fork in forks:
        fork_owner = fork["owner"]["login"]
        fork_name = fork["name"]
        fork_url = fork["html_url"]
        created = fork["created_at"][:10]
        stars = fork.get("stargazers_count", 0)
        fork_link = md_link(f"{fork_owner}/{fork_name}", fork_url)
        lines.append(
            f"{indent(level + 1)}- {fork_link}"
            f" — forked on {esc(created)} ⭐ {stars}"
        )

        DATA["forks"].append({
            "repo": repo_name,
            "fork_owner": fork_owner,
            "fork_name": fork_name,
            "created_at": fork["created_at"],
            "stars": stars,
            "url": fork_url,
        })

        fork_branches_url = f"{BASE_URL}/repos/{fork_owner}/{fork_name}/branches"
        fork_branches = safe_request(fork_branches_url)
        if fork_branches:
            for b in fork_branches[:3]:
                lines.append(f"{indent(level + 2)}- 🌿 Branch: {code_span(b['name'])}")

    return lines


def build_stargazers_section(owner, repo_name, level=2):
    """Lists people who starred the repo."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/stargazers"
    stargazers = safe_request(
        url,
        params={"per_page": 100},
        headers={"Accept": "application/vnd.github.star+json"},
    )
    if not isinstance(stargazers, list):
        stargazers = []

    lines.append(f"{indent(level)}- ### ⭐ Stargazers ({len(stargazers)})")

    for star in stargazers:
        if isinstance(star, dict) and "user" in star:
            user = star["user"]
            starred_at = star.get("starred_at", "unknown")[:10]
        elif isinstance(star, dict) and "login" in star:
            user = star
            starred_at = "unknown"
        else:
            continue

        login = user["login"]
        profile_url = user["html_url"]
        star_link = md_link(f"@{login}", profile_url)
        lines.append(
            f"{indent(level + 1)}- {star_link} — starred on {esc(starred_at)}"
        )

        DATA["stargazers"].append({
            "repo": repo_name,
            "login": login,
            "starred_at": starred_at,
            "profile_url": profile_url,
        })

    return lines


def build_watchers_section(owner, repo_name, level=2):
    """Lists people watching the repo."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/subscribers"
    watchers = get_all_pages(url, max_pages=2)

    lines.append(f"{indent(level)}- ### 👀 Watchers / Subscribers ({len(watchers)})")

    for w in watchers:
        login = w["login"]
        profile_url = w["html_url"]
        lines.append(f"{indent(level + 1)}- {md_link(f'@{login}', profile_url)}")

        DATA["watchers"].append({
            "repo": repo_name,
            "login": login,
            "profile_url": profile_url,
        })

    return lines


def build_contributors_section(owner, repo_name, level=2):
    """Lists contributors with commit count."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/contributors"
    contribs = safe_request(url)
    if not contribs:
        contribs = []

    lines.append(f"{indent(level)}- ### 👥 Contributors ({len(contribs)})")

    for c in contribs:
        login = c.get("login", "ghost")
        profile_url = c.get("html_url", "#")
        contributions = c.get("contributions", 0)
        contributor_link = md_link(f"@{login}", profile_url)
        lines.append(
            f"{indent(level + 1)}- {contributor_link} — {contributions} commit(s)"
        )

        DATA["contributors"].append({
            "repo": repo_name,
            "login": login,
            "contributions": contributions,
            "profile_url": profile_url,
        })

    return lines


def build_releases_section(owner, repo_name, level=2):
    """Lists releases."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/releases"
    releases = safe_request(url)
    if not releases:
        releases = []

    lines.append(f"{indent(level)}- ### 🏷️ Releases ({len(releases)})")

    for rel in releases:
        name = rel.get("name") or rel.get("tag_name", "unnamed")
        rel_url = rel["html_url"]
        published = rel.get("published_at", "")[:10]
        prerelease = " _(pre-release)_" if rel.get("prerelease") else ""
        draft = " _(draft)_" if rel.get("draft") else ""
        lines.append(
            f"{indent(level + 1)}- {md_link(name, rel_url)} — {esc(published)}{prerelease}{draft}"
        )

        DATA["releases"].append({
            "repo": repo_name,
            "name": rel.get("name") or rel.get("tag_name", "unnamed"),
            "published_at": rel.get("published_at", ""),
            "prerelease": rel.get("prerelease", False),
            "draft": rel.get("draft", False),
            "url": rel_url,
        })

        for asset in rel.get("assets", []):
            asset_name = asset["name"]
            asset_url = asset["browser_download_url"]
            downloads = asset.get("download_count", 0)
            size_mb = round(asset["size"] / 1024 / 1024, 2)
            lines.append(
                f"{indent(level + 2)}- 📦 {md_link(asset_name, asset_url)}"
                f" — {size_mb} MB, {downloads} downloads"
            )

            DATA["release_assets"].append({
                "repo": repo_name,
                "release_name": rel.get("name") or rel.get("tag_name", "unnamed"),
                "asset_name": asset_name,
                "downloads": downloads,
                "size_mb": size_mb,
                "url": asset_url,
            })

    return lines


def build_languages_section(owner, repo_name, level=2):
    """Shows language breakdown."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/languages"
    langs = safe_request(url)
    if not langs or not isinstance(langs, dict):
        return lines

    total = sum(langs.values())
    lines.append(f"{indent(level)}- ### 💻 Languages")

    for lang, bytes_count in sorted(langs.items(), key=lambda x: x[1], reverse=True):
        pct = round(bytes_count / total * 100, 1)
        lines.append(f"{indent(level + 1)}- {code_span(lang)} — {pct}% ({bytes_count:,} bytes)")

        DATA["languages"].append({
            "repo": repo_name,
            "language": lang,
            "bytes": bytes_count,
            "percent": pct,
        })

    return lines


def build_branches_and_commits(owner, repo_name, default_branch, level=2):
    """Lists branches with their commit pages."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/branches"
    branches = get_all_pages(url, max_pages=2)

    lines.append(f"{indent(level)}- ### 🌿 Branches ({len(branches)})")

    for branch in branches[:MAX_BRANCHES]:
        bname = branch["name"]
        sha = branch["commit"]["sha"][:7]
        branch_url = github_repo_url(owner, repo_name, "tree", bname)
        default_tag = " _(default)_" if bname == default_branch else ""
        lines.append(
            f"{indent(level + 1)}- {md_link(bname, branch_url)}{default_tag} — HEAD: {code_span(sha)}"
        )

        DATA["branches"].append({
            "repo": repo_name,
            "name": bname,
            "head_sha": branch["commit"]["sha"],
            "head_sha_short": sha,
            "is_default": bname == default_branch,
            "url": branch_url,
        })

        commits_url_link = github_repo_url(owner, repo_name, "commits", bname)
        lines.append(f"{indent(level + 2)}- 📋 {md_link('All Commits', commits_url_link)}")

        commit_lines = build_commits_section(owner, repo_name, bname, level=level + 2)
        lines.extend(commit_lines)

    if len(branches) > MAX_BRANCHES:
        remaining = len(branches) - MAX_BRANCHES
        all_branches_url = github_repo_url(owner, repo_name, "branches")
        lines.append(
            f"{indent(level + 1)}- …and {remaining} more — "
            f"{md_link('View all branches', all_branches_url)}"
        )

    return lines


# ─────────────────────────────────────────────
# FOLLOWERS / FOLLOWING
# ─────────────────────────────────────────────

def build_social_section(username):
    """Builds followers/following section."""
    lines = []
    lines.append("---")
    lines.append("")
    lines.append("## 👤 Social Graph")
    lines.append("")

    followers = get_all_pages(f"{BASE_URL}/users/{username}/followers", max_pages=5)
    lines.append(f"### Followers ({len(followers)})")
    lines.append("")
    for f in followers:
        login = f["login"]
        url = f["html_url"]
        lines.append(f"- {md_link(f'@{login}', url)}")

        user_data = safe_request(f"{BASE_URL}/users/{login}")
        public_repos = 0
        following_count = 0
        if user_data and isinstance(user_data, dict):
            public_repos = user_data.get("public_repos", 0)
            following_count = user_data.get("following", 0)
            lines.append(f"  - 📦 {public_repos} public repos | 👥 follows {following_count} people")

        DATA["followers"].append({
            "login": login,
            "profile_url": url,
            "public_repos": public_repos,
            "following_count": following_count,
        })

    lines.append("")

    following = get_all_pages(f"{BASE_URL}/users/{username}/following", max_pages=5)
    lines.append(f"### Following ({len(following)})")
    lines.append("")
    for f in following:
        login = f["login"]
        url = f["html_url"]
        lines.append(f"- {md_link(f'@{login}', url)}")

        DATA["following"].append({
            "login": login,
            "profile_url": url,
        })

    lines.append("")

    starred = get_all_pages(f"{BASE_URL}/users/{username}/starred", max_pages=3)
    lines.append(f"### ⭐ Repos Starred by @{esc(username)} ({len(starred)})")
    lines.append("")
    for repo in starred:
        rname = repo["full_name"]
        rurl = repo["html_url"]
        desc = (repo.get("description") or "")[:60]
        lines.append(f"- {md_link(rname, rurl)} — {esc(desc)}")

        DATA["starred_by_user"].append({
            "full_name": rname,
            "url": rurl,
            "description": repo.get("description") or "",
        })

    return lines


# ─────────────────────────────────────────────
# MAIN REPORT BUILDER
# ─────────────────────────────────────────────

def build_report():
    global REPORT_GENERATED_AT
    user_data = safe_request(f"{BASE_URL}/users/{USERNAME}")
    if not isinstance(user_data, dict) or not isinstance(user_data.get("login"), str):
        raise RuntimeError("GitHub profile lookup failed; existing report and exports were left untouched.")
    bio = user_data.get("bio", "")
    public_repos_count = user_data.get("public_repos", 0) if isinstance(user_data, dict) else 0
    avatar = user_data.get("avatar_url", "") if isinstance(user_data, dict) else ""
    profile_url = f"https://github.com/{quote(str(USERNAME), safe='-._~')}"

    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    REPORT_GENERATED_AT = generated_at.isoformat().replace("+00:00", "Z")
    now = generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = []
    profile_link = md_link(f"@{USERNAME}", profile_url)
    lines.append(f"# 📊 GitHub Profile Report: {profile_link}")
    lines.append("")
    if avatar:
        image = md_image(f"GitHub avatar for @{USERNAME}", avatar)
        if image:
            lines.append(image)
        lines.append("")
    if bio:
        lines.append(f"> {esc(bio)}")
        lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Public Repositories:** {public_repos_count}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📁 Public Repositories")
    lines.append("")

    repos_data = get_all_pages(f"{BASE_URL}/users/{USERNAME}/repos", max_pages=10)
    repos_data = [r for r in repos_data if not r.get("private", False)]
    repos_data.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)

    for repo in repos_data:
        owner = repo["owner"]["login"]
        repo_name = repo["name"]
        repo_url = repo["html_url"]
        description = esc((repo.get("description") or "No description")[:80])
        stars = repo.get("stargazers_count", 0)
        forks_count = repo.get("forks_count", 0)
        watchers_count = repo.get("watchers_count", 0)
        open_issues = repo.get("open_issues_count", 0)
        default_branch = repo.get("default_branch", "main")
        language = repo.get("language") or "unknown"
        created = repo.get("created_at", "")[:10]
        updated = repo.get("updated_at", "")[:10]
        is_fork = repo.get("fork", False)
        is_archived = repo.get("archived", False)
        is_template = repo.get("is_template", False)

        tags = []
        if is_fork:
            tags.append("🍴 Fork")
        if is_archived:
            tags.append("📦 Archived")
        if is_template:
            tags.append("🗃️ Template")
        tag_str = " | ".join(tags)
        tag_str = f" `{tag_str}`" if tag_str else ""

        lines.append(f"- ## {md_link(repo_name, repo_url)}{tag_str}")
        lines.append(f"  > {description}")
        lines.append(
            f"  > ⭐ {stars} | 🍴 {forks_count} | 👀 {watchers_count} "
            f"| 🐛 {open_issues} open issues | 💻 {esc(language)} "
            f"| 📅 Created: {created} | 🔄 Updated: {updated}"
        )
        lines.append("")

        parent_full_name = ""
        if is_fork:
            repo_detail = safe_request(f"{BASE_URL}/repos/{owner}/{repo_name}")
            if repo_detail and isinstance(repo_detail, dict):
                parent = repo_detail.get("parent", {})
                if parent:
                    parent_full_name = parent.get("full_name", "")
                    purl = parent.get("html_url", "")
                    lines.append(f"  - 🔗 Forked from: {md_link(parent_full_name, purl)}")

        DATA["repos"].append({
            "name": repo_name,
            "owner": owner,
            "url": repo_url,
            "description": repo.get("description") or "",
            "stars": stars,
            "forks": forks_count,
            "watchers": watchers_count,
            "open_issues": open_issues,
            "language": language,
            "default_branch": default_branch,
            "created_at": repo.get("created_at", ""),
            "updated_at": repo.get("updated_at", ""),
            "is_fork": is_fork,
            "is_archived": is_archived,
            "is_template": is_template,
            "forked_from": parent_full_name,
        })

        lines.extend(build_branches_and_commits(owner, repo_name, default_branch, level=2))
        lines.append("")
        lines.extend(build_issues_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_prs_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_forks_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_stargazers_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_watchers_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_contributors_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_releases_section(owner, repo_name, level=2))
        lines.append("")
        lines.extend(build_languages_section(owner, repo_name, level=2))
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.extend(build_social_section(USERNAME))
    lines.append("")
    lines.append("---")
    lines.append(f"Report auto-generated by {md_link('GitHub Actions', 'https://github.com/features/actions')} on {esc(now)}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# EXPORT (CSV / JSON / JSONL)
# ─────────────────────────────────────────────

def atomic_write(path, write_content, newline=None):
    """Replace one output file atomically so interruptions never leave partial JSON/CSV."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline=newline) as handle:
            write_content(handle)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def export_csv(records, path):
    def write_csv(handle):
        if not records:
            return
        writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)

    atomic_write(path, write_csv, newline="")


def export_json(records, path):
    atomic_write(path, lambda handle: json.dump(records, handle, ensure_ascii=False, indent=2))


def export_jsonl(records, path):
    def write_jsonl(handle):
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    atomic_write(path, write_jsonl)


def gh_warning(message):
    """Emite uma anotação de warning visível na aba Actions/Summary do run."""
    # Formato de workflow command do GitHub Actions; %0A vira quebra de linha
    # dentro da mensagem exibida na anotação.
    safe_message = message.replace("\n", "%0A")
    print(f"::warning::{safe_message}")


def export_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    empty_categories = []

    for category, records in DATA.items():
        export_csv(records, os.path.join(OUTPUT_DIR, f"{category}.csv"))
        export_json(records, os.path.join(OUTPUT_DIR, f"{category}.json"))
        export_jsonl(records, os.path.join(OUTPUT_DIR, f"{category}.jsonl"))
        print(f"  {category}: {len(records)} registro(s) exportado(s)")

        if len(records) == 0:
            empty_categories.append(category)

    generated_at = REPORT_GENERATED_AT or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    metadata = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "profile": {
            "login": USERNAME,
            "url": f"https://github.com/{quote(str(USERNAME), safe='-._~')}",
        },
        "counts": {category: len(records) for category, records in DATA.items()},
        "formats": ["json", "jsonl", "csv"],
        "dataSource": "GitHub public API report snapshot",
    }
    export_json(metadata, os.path.join(OUTPUT_DIR, "metadata.json"))
    print("  metadata: report timestamp and category counts exported")

    if empty_categories:
        gh_warning(
            "As seguintes categorias ficaram vazias (0 registros) em "
            f"CSV/JSON/JSONL: {', '.join(empty_categories)}. "
            "Verifique se é esperado (ex: nenhum fork/issue mesmo) ou se "
            "houve erro de API/rate limit — veja os warnings de API abaixo, "
            "se houver."
        )

    if API_ERRORS:
        # Agrupa por endpoint base + status pra não gerar um warning gigante
        # repetido por repositório.
        by_status = {}
        for err in API_ERRORS:
            key = err["status"]
            by_status.setdefault(key, []).append(err["url"])

        summary_lines = [f"{len(API_ERRORS)} chamada(s) de API falharam durante a coleta:"]
        for status, urls in by_status.items():
            sample = urls[0]
            summary_lines.append(f"- status {status}: {len(urls)} chamada(s), ex: {sample}")

        gh_warning("\n".join(summary_lines))


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Starting report generation for @{USERNAME}...")

    report = build_report()  # também popula DATA[...] durante a coleta
    atomic_write("REPORT.md", lambda handle: handle.write(report))
    print("Report written to REPORT.md")

    export_all()
    print(f"Exports written to {OUTPUT_DIR}/")
