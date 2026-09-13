import os
import sys
import time
import requests
from datetime import datetime
from github import Github, GithubException

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

TOKEN = os.environ.get("GITHUB_TOKEN")
USERNAME = os.environ.get("GITHUB_ACTOR")

if not TOKEN or not USERNAME:
    print("ERROR: GITHUB_TOKEN and GITHUB_ACTOR must be set.")
    sys.exit(1)

g = Github(TOKEN)
HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

BASE_URL = "https://api.github.com"
MAX_COMMITS_PAGES = 5      # how many commit pages to list per branch
MAX_ISSUES = 20            # max issues to list per repo
MAX_PRS = 20               # max PRs to list per repo
MAX_BRANCHES = 5           # max branches to list per repo


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def safe_request(url, params=None):
    """GET with retry on rate limit."""
    for attempt in range(5):
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 403 and "rate limit" in r.text.lower():
            wait = 60 * (attempt + 1)
            print(f"  Rate limited. Waiting {wait}s...")
            time.sleep(wait)
        elif r.status_code == 409:
            # Empty repo or conflict
            return []
        else:
            print(f"  Warning: {r.status_code} on {url}")
            return []
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
    base = f"https://github.com/{owner}/{repo}/commits/{branch}"
    if after_sha:
        return f"{base}/?after={after_sha}+{per_page - 1}"
    return base


def indent(level):
    return "  " * level


# ─────────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────────

def build_commits_section(owner, repo_name, branch, level=3):
    """
    Lists commit pages (paginated) for a given branch.
    Each page after the first uses the last SHA of that page as 'after'.
    """
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/commits"
    
    page = 1
    last_sha = None
    visited_shas = []

    while page <= MAX_COMMITS_PAGES:
        params = {"sha": branch, "per_page": 35, "page": page}
        data = safe_request(url, params=params)

        if not data:
            break

        page_url = commit_page_url(owner, repo_name, branch, last_sha)
        prefix = indent(level)

        if page == 1:
            lines.append(f"{prefix}- 📄 [Commits Page 1]({page_url})")
        else:
            lines.append(f"{prefix}- 📄 [Commits Page {page}]({page_url})")

        # Sub-entries: individual commits on this page
        for commit in data[:10]:  # show up to 10 commits per page
            sha = commit["sha"][:7]
            full_sha = commit["sha"]
            msg = commit["commit"]["message"].split("\n")[0][:72]
            msg = msg.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
            author = commit["commit"]["author"]["name"]
            date = commit["commit"]["author"]["date"][:10]
            commit_url = f"https://github.com/{owner}/{repo_name}/commit/{commit['sha']}"
            lines.append(
                f"{indent(level + 1)}- [`{sha}`]({commit_url}) "
                f"**{msg}** — _{author}_ ({date})"
            )

        last_sha = data[-1]["sha"]
        visited_shas.append(last_sha)

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
        # Filter out PRs (GitHub returns PRs in issues endpoint too)
        issues = [i for i in issues if "pull_request" not in i] if issues else []

        lines.append(f"{indent(level + 1)}- **{state.capitalize()} Issues** ({len(issues)})")

        for issue in issues[:MAX_ISSUES]:
            num = issue["number"]
            title = issue["title"][:60].replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
            issue_url = issue["html_url"]
            user = issue["user"]["login"]
            created = issue["created_at"][:10]
            labels = ", ".join(l["name"] for l in issue.get("labels", []))
            label_str = f" `{labels}`" if labels else ""
            lines.append(
                f"{indent(level + 2)}- [#{num} {title}]({issue_url})"
                f" — _{user}_ ({created}){label_str}"
            )

            # Comments count as sub-sub-entry
            comments = issue.get("comments", 0)
            if comments > 0:
                lines.append(
                    f"{indent(level + 3)}- 💬 {comments} comment(s) — "
                    f"[View thread]({issue_url})"
                )

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
            title = pr["title"][:60].replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
            pr_url = pr["html_url"]
            user = pr["user"]["login"]
            created = pr["created_at"][:10]
            base_branch = pr["base"]["ref"]
            head_branch = pr["head"]["ref"]
            merged = pr.get("merged_at")
            status = "✅ Merged" if merged else ("🟢 Open" if state == "open" else "🔴 Closed")
            lines.append(
                f"{indent(level + 2)}- {status} [#{num} {title}]({pr_url})"
                f" — _{user}_ ({created}) `{head_branch}` → `{base_branch}`"
            )

            # Commits in this PR as sub-sub-entry
            pr_commits_url = f"{BASE_URL}/repos/{owner}/{repo_name}/pulls/{num}/commits"
            pr_commits = safe_request(pr_commits_url)
            if pr_commits:
                lines.append(f"{indent(level + 3)}- 📝 {len(pr_commits)} commit(s) in this PR")
                for c in pr_commits[:5]:
                    sha = c["sha"][:7]
                    msg = c["commit"]["message"].split("\n")[0][:60]
                    msg = msg.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
                    c_url = f"https://github.com/{owner}/{repo_name}/commit/{c['sha']}"
                    lines.append(f"{indent(level + 4)}- [`{sha}`]({c_url}) {msg}")

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
        lines.append(
            f"{indent(level + 1)}- [{fork_owner}/{fork_name}]({fork_url})"
            f" — forked on {created} ⭐ {stars}"
        )
        # Fork's own branches
        fork_branches_url = f"{BASE_URL}/repos/{fork_owner}/{fork_name}/branches"
        fork_branches = safe_request(fork_branches_url)
        if fork_branches:
            for b in fork_branches[:3]:
                lines.append(f"{indent(level + 2)}- 🌿 Branch: `{b['name']}`")

    return lines


def build_stargazers_section(owner, repo_name, level=2):
    """Lists people who starred the repo."""
    lines = []
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/stargazers"
    # Need special header for starred_at timestamp
    r = requests.get(url, headers={
        **HEADERS,
        "Accept": "application/vnd.github.star+json"
    }, params={"per_page": 100})
    
    stargazers = r.json() if r.status_code == 200 else []
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
        lines.append(
            f"{indent(level + 1)}- [@{login}]({profile_url}) — starred on {starred_at}"
        )

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
        lines.append(f"{indent(level + 1)}- [@{login}]({profile_url})")

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
        lines.append(
            f"{indent(level + 1)}- [@{login}]({profile_url}) — {contributions} commit(s)"
        )

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
        name = name.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
        rel_url = rel["html_url"]
        published = rel.get("published_at", "")[:10]
        prerelease = " _(pre-release)_" if rel.get("prerelease") else ""
        draft = " _(draft)_" if rel.get("draft") else ""
        lines.append(
            f"{indent(level + 1)}- [{name}]({rel_url}) — {published}{prerelease}{draft}"
        )

        # Assets
        assets = rel.get("assets", [])
        for asset in assets:
            asset_name = asset["name"]
            asset_url = asset["browser_download_url"]
            downloads = asset.get("download_count", 0)
            size_mb = round(asset["size"] / 1024 / 1024, 2)
            lines.append(
                f"{indent(level + 2)}- 📦 [{asset_name}]({asset_url})"
                f" — {size_mb} MB, {downloads} downloads"
            )

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
        lines.append(f"{indent(level + 1)}- `{lang}` — {pct}% ({bytes_count:,} bytes)")

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
        branch_url = f"https://github.com/{owner}/{repo_name}/tree/{bname}"
        default_tag = " _(default)_" if bname == default_branch else ""
        lines.append(
            f"{indent(level + 1)}- [`{bname}`]({branch_url}){default_tag} — HEAD: `{sha}`"
        )

        # Commit pages for this branch
        commits_url_link = f"https://github.com/{owner}/{repo_name}/commits/{bname}"
        lines.append(f"{indent(level + 2)}- 📋 [All Commits]({commits_url_link})")

        # Individual paginated commit pages
        commit_lines = build_commits_section(owner, repo_name, bname, level=level + 2)
        lines.extend(commit_lines)

    if len(branches) > MAX_BRANCHES:
        remaining = len(branches) - MAX_BRANCHES
        all_branches_url = f"https://github.com/{owner}/{repo_name}/branches"
        lines.append(
            f"{indent(level + 1)}- _...and {remaining} more — "
            f"[View all branches]({all_branches_url})_"
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

    # Followers
    followers = get_all_pages(f"{BASE_URL}/users/{username}/followers", max_pages=5)
    lines.append(f"### Followers ({len(followers)})")
    lines.append("")
    for f in followers:
        login = f["login"]
        url = f["html_url"]
        lines.append(f"- [@{login}]({url})")
        # Their public repos count
        user_data = safe_request(f"{BASE_URL}/users/{login}")
        if user_data and isinstance(user_data, dict):
            repos = user_data.get("public_repos", 0)
            following_count = user_data.get("following", 0)
            lines.append(f"  - 📦 {repos} public repos | 👥 follows {following_count} people")

    lines.append("")

    # Following
    following = get_all_pages(f"{BASE_URL}/users/{username}/following", max_pages=5)
    lines.append(f"### Following ({len(following)})")
    lines.append("")
    for f in following:
        login = f["login"]
        url = f["html_url"]
        lines.append(f"- [@{login}]({url})")

    lines.append("")

    # Starred repos by user
    starred = get_all_pages(f"{BASE_URL}/users/{username}/starred", max_pages=3)
    lines.append(f"### ⭐ Repos Starred by @{username} ({len(starred)})")
    lines.append("")
    for repo in starred:
        rname = repo["full_name"]
        rurl = repo["html_url"]
        desc = (repo.get("description") or "")[:60]
        lines.append(f"- [{rname}]({rurl}) — _{desc}_")

    return lines


# ─────────────────────────────────────────────
# MAIN REPORT BUILDER
# ─────────────────────────────────────────────

def build_report():
    user_data = safe_request(f"{BASE_URL}/users/{USERNAME}")
    name = user_data.get("name", USERNAME) if isinstance(user_data, dict) else USERNAME
    bio = user_data.get("bio", "") if isinstance(user_data, dict) else ""
    public_repos_count = user_data.get("public_repos", 0) if isinstance(user_data, dict) else 0
    avatar = user_data.get("avatar_url", "") if isinstance(user_data, dict) else ""
    profile_url = f"https://github.com/{USERNAME}"

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = []
    lines.append(f"# 📊 GitHub Profile Report: [@{USERNAME}]({profile_url})")
    lines.append("")
    if avatar:
        lines.append(f"![]({avatar})")
        lines.append("")
    if bio:
        lines.append(f"> {bio}")
        lines.append("")
    lines.append(f"**Generated:** {now}")
    lines.append(f"**Public Repositories:** {public_repos_count}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📁 Public Repositories")
    lines.append("")

    # Get all public repos
    repos_data = get_all_pages(
        f"{BASE_URL}/users/{USERNAME}/repos",
        max_pages=10
    )
    repos_data = [r for r in repos_data if not r.get("private", False)]
    repos_data.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)

    for repo in repos_data:
        owner = repo["owner"]["login"]
        repo_name = repo["name"]
        repo_url = repo["html_url"]
        description = (repo.get("description") or "No description")[:80]
        description = description.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")
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

        lines.append(
            f"- ## [{repo_name}]({repo_url}){tag_str}"
        )
        lines.append(
            f"  > {description}"
        )
        lines.append(
            f"  > ⭐ {stars} | 🍴 {forks_count} | 👀 {watchers_count} "
            f"| 🐛 {open_issues} open issues | 💻 {language} "
            f"| 📅 Created: {created} | 🔄 Updated: {updated}"
        )
        lines.append("")

        # If forked, show parent
        if is_fork:
            parent_url = f"{BASE_URL}/repos/{owner}/{repo_name}"
            repo_detail = safe_request(parent_url)
            if repo_detail and isinstance(repo_detail, dict):
                parent = repo_detail.get("parent", {})
                if parent:
                    pname = parent.get("full_name", "")
                    purl = parent.get("html_url", "")
                    lines.append(f"  - 🔗 Forked from: [{pname}]({purl})")

        # Branches + Commits
        lines.extend(build_branches_and_commits(owner, repo_name, default_branch, level=2))
        lines.append("")

        # Issues
        lines.extend(build_issues_section(owner, repo_name, level=2))
        lines.append("")

        # PRs
        lines.extend(build_prs_section(owner, repo_name, level=2))
        lines.append("")

        # Forks
        lines.extend(build_forks_section(owner, repo_name, level=2))
        lines.append("")

        # Stargazers
        lines.extend(build_stargazers_section(owner, repo_name, level=2))
        lines.append("")

        # Watchers
        lines.extend(build_watchers_section(owner, repo_name, level=2))
        lines.append("")

        # Contributors
        lines.extend(build_contributors_section(owner, repo_name, level=2))
        lines.append("")

        # Releases
        lines.extend(build_releases_section(owner, repo_name, level=2))
        lines.append("")

        # Languages
        lines.extend(build_languages_section(owner, repo_name, level=2))
        lines.append("")

        lines.append("---")
        lines.append("")

    # Social section
    lines.extend(build_social_section(USERNAME))

    lines.append("")
    lines.append("---")
    lines.append(f"_Report auto-generated by [GitHub Actions](https://github.com/features/actions) on {now}_")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Starting report generation for @{USERNAME}...")
    report = build_report()
    output_path = "REPORT.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Report written to {output_path}")
