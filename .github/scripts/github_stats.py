#!/usr/bin/env python3
"""
Collects verifiable GitHub metrics for the profile and renders the
stats and streak cards.

Every counter keeps its own definition, source and period. Counters with
different meanings are never added together:

- calendar contributions: what GitHub shows on the profile calendar
  (public + private, every contribution type);
- restricted contributions: private contributions GitHub reports only as
  an aggregate, of any type (not necessarily commits);
- public contributions: itemized contributions in public repositories.

Only public, itemized activity feeds the cards. Calendar and restricted
counts are kept in metrics.json for traceability and are not displayed.

The output metrics.json is the single source for the activity graph.
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

LOGIN = os.getenv("GH_LOGIN", "therunnas")
STAT_OUT = os.getenv("STAT_OUT", "assets/cards/stats.svg")
STREAK_OUT = os.getenv("STREAK_OUT", "assets/cards/streak.svg")
METRICS_OUT = os.getenv("METRICS_OUT", "assets/cards/metrics.json")

BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#8b949e"
TRACK = "#21262d"
GREEN = "#40c463"
BLUE = "#58a6ff"
YELLOW = "#e3b341"
PURPLE = "#bc8cff"

FONT = "Segoe UI, Ubuntu, Arial, sans-serif"

PAGE = 100


def graphql(query, **variables):
    command = ["gh", "api", "graphql", "-f", f"query={query}"]

    for key, value in variables.items():
        if value is None:
            continue
        flag = "-F" if isinstance(value, int) else "-f"
        command += [flag, f"{key}={value}"]

    result = subprocess.run(command, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    if data.get("errors"):
        raise RuntimeError(data["errors"])

    return data["data"]


def rest(path, *fields):
    command = ["gh", "api", "-X", "GET", path]

    for field in fields:
        command += ["-f", field]

    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def search_count(query):
    return int(rest("search/issues", f"q={query}", "per_page=1")["total_count"])


def search_items(query):
    items = []
    page = 1

    while True:
        data = rest("search/issues", f"q={query}", f"per_page={PAGE}", f"page={page}")
        items += data["items"]

        if len(data["items"]) < PAGE or len(items) >= data["total_count"]:
            break

        page += 1

    return items


def timestamp(day):
    return day.strftime("%Y-%m-%dT00:00:00Z")


def end_of(day):
    return day.strftime("%Y-%m-%dT23:59:59Z")


def quarters(first_day, last_day):
    """Contiguous [start, end] windows, no gap and no overlap between them."""
    start = first_day

    while start <= last_day:
        month = ((start.month - 1) // 3) * 3 + 1
        next_quarter = date(start.year + (month + 3 > 12), (month + 2) % 12 + 1, 1)
        end = min(next_quarter - timedelta(days=1), last_day)
        yield start, end
        start = end + timedelta(days=1)


VIEWER_QUERY = """
query($login:String!) {
  viewer { login }
  user(login:$login) { createdAt }
}
"""


WINDOW_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      totalCommitContributions
      restrictedContributionsCount

      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }

      commitContributionsByRepository(maxRepositories:100) {
        repository { nameWithOwner isPrivate owner { login } }
        contributions(first:100) {
          totalCount
          pageInfo { hasNextPage }
          nodes { occurredAt commitCount }
        }
      }
    }
  }
}
"""


CONNECTION_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!, $after:String) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      %s(first:100, after:$after) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { occurredAt %s }
      }
    }
  }
}
"""

# Itemized contribution types that GitHub counts on the calendar.
CONNECTIONS = {
    "issueContributions": "issue { repository { isPrivate } }",
    "pullRequestContributions": "pullRequest { repository { isPrivate } }",
    "pullRequestReviewContributions": "repository { isPrivate }",
    "repositoryContributions": "repository { isPrivate }",
}


YEAR_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      contributionCalendar { totalContributions }
    }
  }
}
"""


def repository_of(field, node):
    if field == "issueContributions":
        return node["issue"]["repository"]
    if field == "pullRequestContributions":
        return node["pullRequest"]["repository"]
    return node["repository"]


def fetch_connection(field, start, end):
    nodes = []
    after = None

    while True:
        data = graphql(
            CONNECTION_QUERY % (field, CONNECTIONS[field]),
            login=LOGIN,
            after=after,
            **{"from": timestamp(start), "to": end_of(end)},
        )
        connection = data["user"]["contributionsCollection"][field]
        nodes += connection["nodes"]

        if not connection["pageInfo"]["hasNextPage"]:
            break

        after = connection["pageInfo"]["endCursor"]

    if len(nodes) != connection["totalCount"]:
        raise RuntimeError(f"{field} {start}..{end}: paginated {len(nodes)} of {connection['totalCount']}")

    return nodes


def add(days, day, count):
    days[day] = days.get(day, 0) + count


def fetch_history(first_day, last_day):
    calendar = {}
    public = {}
    totals = {
        "visible_commits": 0,
        "restricted": 0,
        "public_commits": 0,
        "public_issues": 0,
        "public_pull_requests": 0,
        "public_reviews": 0,
        "public_repositories_created": 0,
    }
    external_repositories = set()

    for start, end in quarters(first_day, last_day):
        data = graphql(
            WINDOW_QUERY,
            login=LOGIN,
            **{"from": timestamp(start), "to": end_of(end)},
        )
        collection = data["user"]["contributionsCollection"]

        totals["visible_commits"] += collection["totalCommitContributions"]
        totals["restricted"] += collection["restrictedContributionsCount"]

        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                if start.isoformat() <= day["date"] <= end.isoformat():
                    calendar[day["date"]] = int(day["contributionCount"])

        by_repository = collection["commitContributionsByRepository"]

        if len(by_repository) >= 100:
            raise RuntimeError(f"commit repositories {start}..{end}: limit of 100 reached")

        for item in by_repository:
            repository = item["repository"]
            contributions = item["contributions"]

            # One node per day, so a quarter never needs a second page;
            # totalCount is the number of commits, not of nodes.
            commits = sum(node["commitCount"] for node in contributions["nodes"])

            if contributions["pageInfo"]["hasNextPage"] or commits != contributions["totalCount"]:
                raise RuntimeError(f"{repository['nameWithOwner']} {start}..{end}: commit days truncated")

            if repository["isPrivate"]:
                continue

            if repository["owner"]["login"].lower() != LOGIN.lower():
                external_repositories.add(repository["nameWithOwner"])

            for node in contributions["nodes"]:
                totals["public_commits"] += node["commitCount"]
                add(public, node["occurredAt"][:10], node["commitCount"])

        for field, key in (
            ("issueContributions", "public_issues"),
            ("pullRequestContributions", "public_pull_requests"),
            ("pullRequestReviewContributions", "public_reviews"),
            ("repositoryContributions", "public_repositories_created"),
        ):
            for node in fetch_connection(field, start, end):
                if repository_of(field, node)["isPrivate"]:
                    continue
                totals[key] += 1
                add(public, node["occurredAt"][:10], 1)

    return calendar, public, totals, external_repositories


def streaks(days, first_day, last_day):
    """Longest and current runs of days with activity.

    The last day may still be in progress, so a zero there does not break
    the current streak.
    """
    longest = (0, None, None)
    running = 0
    run_start = None
    day = first_day

    while day <= last_day:
        if days.get(day.isoformat(), 0) > 0:
            running += 1
            run_start = run_start or day
            if running > longest[0]:
                longest = (running, run_start, day)
        else:
            running = 0
            run_start = None
        day += timedelta(days=1)

    current = 0
    current_end = last_day if days.get(last_day.isoformat(), 0) > 0 else last_day - timedelta(days=1)
    day = current_end

    while day >= first_day and days.get(day.isoformat(), 0) > 0:
        current += 1
        day -= timedelta(days=1)

    def iso(value):
        return value.isoformat() if value else None

    return {
        "current": current,
        "current_start": iso(day + timedelta(days=1)) if current else None,
        "current_end": iso(current_end) if current else None,
        "longest": longest[0],
        "longest_start": iso(longest[1]),
        "longest_end": iso(longest[2]),
    }


def public_stars():
    stars = 0
    page = 1

    while True:
        repositories = rest(f"users/{LOGIN}/repos", "type=owner", f"per_page={PAGE}", f"page={page}")
        stars += sum(r["stargazers_count"] for r in repositories if not r["fork"] and not r["private"])

        if len(repositories) < PAGE:
            return stars

        page += 1


def check_years(calendar, first_day, last_day):
    """Compares the merged quarterly calendar with independent yearly queries."""
    results = []

    for year in range(first_day.year, last_day.year + 1):
        start = max(date(year, 1, 1), first_day)
        end = min(date(year, 12, 31), last_day)
        data = graphql(YEAR_QUERY, login=LOGIN, **{"from": timestamp(start), "to": end_of(end)})
        expected = data["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
        merged = sum(v for k, v in calendar.items() if start.isoformat() <= k <= end.isoformat())
        results.append({"year": year, "yearly_query": expected, "merged_quarters": merged, "ok": expected == merged})

    return results


def format_number(number):
    return f"{int(number):,}"


def svg_header(width, title):
    return [
        f'<circle cx="27" cy="30" r="4" fill="{GREEN}"/>',
        f'<text x="40" y="35" fill="{MUTED}" font-size="12" font-family="{FONT}" letter-spacing="2.4">{title}</text>',
        f'<text x="{width - 25}" y="35" text-anchor="end" fill="{MUTED}" fill-opacity="0.6" font-size="11" font-family="{FONT}">@{LOGIN}</text>',
    ]


def svg_open(width, height, label):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">',
        f"<title>{label}</title>",
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
    ]


def write(path, parts):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        file.write("\n".join(parts))


def render_stats(rows, as_of):
    width = 480
    height = 245
    parts = svg_open(width, height, f"Public GitHub statistics for {LOGIN}")
    parts.extend(svg_header(width, "GITHUB STATS"))

    start_y = 78
    row_height = 34

    for index, (symbol, label, scope, value, color) in enumerate(rows):
        y = start_y + index * row_height
        parts += [
            f'<rect x="25" y="{y - 17}" width="24" height="24" rx="7" fill="{color}"/>',
            f'<text x="37" y="{y}" text-anchor="middle" fill="{BG}" font-size="14" font-weight="700" font-family="{FONT}">{symbol}</text>',
            f'<text x="64" y="{y - 3}" fill="{FG}" font-size="14" font-family="{FONT}">{label}</text>',
            f'<text x="64" y="{y + 11}" fill="{MUTED}" font-size="10" font-family="{FONT}">{scope}</text>',
            f'<text x="{width - 28}" y="{y}" text-anchor="end" fill="{FG}" font-size="16" font-weight="700" font-family="{FONT}">{format_number(value)}</text>',
        ]

    parts.append(
        f'<text x="25" y="{height - 15}" fill="{MUTED}" font-size="9" font-family="{FONT}">'
        f"Source: GitHub GraphQL &amp; Search API · as of {as_of}</text>"
    )
    parts.append("</svg>")
    write(STAT_OUT, parts)


def render_streak(streak, public_last_year, recent, as_of):
    width = 480
    height = 245
    parts = svg_open(width, height, f"Public contribution streak for {LOGIN}")
    parts.extend(svg_header(width, "PUBLIC STREAK"))

    if streak["current"]:
        start = datetime.strptime(streak["current_start"], "%Y-%m-%d").strftime("%b %d, %Y")
        period = f"since {start}"
    else:
        period = "No active public streak"

    if streak["longest"]:
        longest_start = datetime.strptime(streak["longest_start"], "%Y-%m-%d").strftime("%b %d, %Y")
        longest_period = f"from {longest_start}"
    else:
        longest_period = ""

    parts += [
        f'<text x="30" y="132" fill="{FG}" font-size="50" font-weight="700" font-family="{FONT}">{format_number(streak["current"])}</text>',
        f'<text x="30" y="157" fill="{GREEN}" font-size="11" font-weight="700" letter-spacing="1.8" font-family="{FONT}">CURRENT STREAK (DAYS)</text>',
        f'<text x="30" y="176" fill="{MUTED}" font-size="10" font-family="{FONT}">{period}</text>',
        f'<line x1="270" y1="58" x2="270" y2="187" stroke="{TRACK}"/>',
        f'<text x="291" y="80" fill="{MUTED}" font-size="10" letter-spacing="1.5" font-family="{FONT}">LONGEST STREAK</text>',
        f'<text x="291" y="108" fill="{FG}" font-size="28" font-weight="700" font-family="{FONT}">{format_number(streak["longest"])}</text>',
        f'<text x="291" y="124" fill="{MUTED}" font-size="10" font-family="{FONT}">{longest_period}</text>',
        f'<text x="291" y="152" fill="{MUTED}" font-size="10" letter-spacing="1.5" font-family="{FONT}">LAST 365 DAYS</text>',
        f'<text x="291" y="180" fill="{FG}" font-size="28" font-weight="700" font-family="{FONT}">{format_number(public_last_year)}</text>',
    ]

    maximum = max([count for _, count in recent] + [1])
    bar_width = 420 / len(recent) - 2

    for index, (day, count) in enumerate(recent):
        bar_height = max(2, 22 * count / maximum)
        x = 30 + index * (bar_width + 2)
        parts.append(
            f'<rect x="{x:.2f}" y="{218 - bar_height:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="1.4" '
            f'fill="{GREEN if count else TRACK}" fill-opacity="0.85"><title>{day}: {count} public contributions</title></rect>'
        )

    parts.append(
        f'<text x="25" y="{height - 12}" fill="{MUTED}" font-size="9" font-family="{FONT}">'
        f"Public contributions only, last {len(recent)} days shown · as of {as_of}</text>"
    )
    parts.append("</svg>")
    write(STREAK_OUT, parts)


def main():
    print(f"Collecting GitHub metrics for @{LOGIN}...")

    head = graphql(VIEWER_QUERY, login=LOGIN)

    # Private and search counts depend on what the token can see. A token
    # from another identity (e.g. the default workflow token) would silently
    # change the numbers, so it is refused.
    if head["viewer"]["login"].lower() != LOGIN.lower():
        sys.exit(f"Token belongs to @{head['viewer']['login']}, expected @{LOGIN}. Refusing to publish metrics.")

    now = datetime.now(timezone.utc)
    first_day = datetime.strptime(head["user"]["createdAt"][:10], "%Y-%m-%d").date()
    last_day = now.date()

    calendar, public, totals, external_repositories = fetch_history(first_day, last_day)

    print("Collecting pull requests, issues and stars...")

    search = {}
    for key, query in (
        ("pull_requests", f"author:{LOGIN} is:pr"),
        ("pull_requests_merged", f"author:{LOGIN} is:pr is:merged"),
        ("public_pull_requests", f"author:{LOGIN} is:pr is:public"),
        ("public_pull_requests_merged", f"author:{LOGIN} is:pr is:public is:merged"),
        ("issues", f"author:{LOGIN} is:issue"),
        ("public_issues", f"author:{LOGIN} is:issue is:public"),
    ):
        search[key] = {"query": query, "value": search_count(query)}

    for item in search_items(f"author:{LOGIN} is:pr is:public is:merged"):
        name = item["repository_url"].split("/repos/", 1)[1]
        if name.split("/")[0].lower() != LOGIN.lower():
            external_repositories.add(name)

    stars = public_stars()

    year_ago = last_day - timedelta(days=364)
    public_last_year = sum(v for k, v in public.items() if k >= year_ago.isoformat())
    public_streak = streaks(public, first_day, last_day)
    calendar_streak = streaks(calendar, first_day, last_day)

    days_over = sorted(k for k, v in public.items() if v > calendar.get(k, 0))
    years = check_years(calendar, first_day, last_day)

    checks = {
        "yearly_calendar_matches_quarters": years,
        "public_days_exceeding_calendar": days_over,
        "ok": all(y["ok"] for y in years) and not days_over,
    }

    as_of = last_day.isoformat()
    metrics = {
        "login": LOGIN,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of,
        "period": {"from": first_day.isoformat(), "to": as_of},
        "definitions": {
            "calendar": "Contributions on the GitHub profile calendar: public and private, all types.",
            "restricted": "Private contributions GitHub reports only as an aggregate (any type, not only commits).",
            "public": "Itemized contributions in public repositories: commits on default branches, issues, pull requests, reviews and repositories created.",
            "search": "GitHub Search API counts, all time, limited to what the profile owner's token can see.",
            "external_repositories": "Public repositories not owned by the profile with at least one counted commit or merged pull request by the profile.",
        },
        "displayed": {
            "public_commits_all_time": totals["public_commits"],
            "pull_requests_merged_all_repositories": search["pull_requests_merged"]["value"],
            "public_pull_requests": search["public_pull_requests"]["value"],
            "public_repositories_contributed_to": len(external_repositories),
            "public_streak": public_streak,
            "public_contributions_last_365_days": public_last_year,
        },
        "public": {
            "commits": totals["public_commits"],
            "issues_opened": totals["public_issues"],
            "pull_requests_opened": totals["public_pull_requests"],
            "reviews": totals["public_reviews"],
            "repositories_created": totals["public_repositories_created"],
            "external_repositories": len(external_repositories),
            "external_repositories_sources": [
                "commitContributionsByRepository (public, not owned)",
                f"search: author:{LOGIN} is:pr is:public is:merged (not owned)",
            ],
            "stars_on_owned_non_fork_repositories": stars,
        },
        "search": search,
        "not_displayed": {
            "calendar_total": sum(calendar.values()),
            "calendar_last_365_days": sum(v for k, v in calendar.items() if k >= year_ago.isoformat()),
            "restricted_contributions": totals["restricted"],
            "commits_visible_to_token": totals["visible_commits"],
            "calendar_streak": calendar_streak,
            "reason": "Includes private activity that is not itemized and cannot be verified as manual work.",
        },
        "checks": checks,
        "daily": {
            "public": dict(sorted((k, v) for k, v in public.items() if v)),
            "calendar": dict(sorted((k, v) for k, v in calendar.items() if v)),
        },
    }

    print(json.dumps({"displayed": metrics["displayed"], "checks": checks}, indent=2))

    if not checks["ok"]:
        sys.exit("Validation failed: cards not updated.")

    write(METRICS_OUT, [json.dumps(metrics, indent=2, ensure_ascii=False)])

    render_stats(
        [
            ("●", "Commits", "public repositories · all time", totals["public_commits"], GREEN),
            ("↗", "Pull requests merged", "all repositories, incl. private · all time", search["pull_requests_merged"]["value"], BLUE),
            ("↗", "Public pull requests", "opened · all time", search["public_pull_requests"]["value"], YELLOW),
            ("◆", "Contributed to", "public repos of others, commits or merged PRs", len(external_repositories), PURPLE),
        ],
        as_of,
    )

    recent = []
    for offset in range(51, -1, -1):
        day = (last_day - timedelta(days=offset)).isoformat()
        recent.append((day, public.get(day, 0)))

    render_streak(public_streak, public_last_year, recent, as_of)

    print(f"Generated {METRICS_OUT}, {STAT_OUT}, {STREAK_OUT}")


if __name__ == "__main__":
    main()
