#!/usr/bin/env python3

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

LOGIN = os.getenv("GH_LOGIN", "therunnas")
STAT_OUT = os.getenv("STAT_OUT", "assets/cards/stats.svg")
STREAK_OUT = os.getenv("STREAK_OUT", "assets/cards/streak.svg")

BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#8b949e"
TRACK = "#21262d"
GREEN = "#40c463"
BLUE = "#58a6ff"
YELLOW = "#e3b341"
RED = "#f85149"
PURPLE = "#bc8cff"

FONT = "Segoe UI, Ubuntu, Arial, sans-serif"


def graphql(query, **variables):
    command = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={query}",
    ]

    for key, value in variables.items():
        command += ["-f", f"{key}={value}"]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)

    if data.get("errors"):
        raise RuntimeError(data["errors"])

    return data["data"]


def search_count(query):
    result = subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "GET",
            "search/issues",
            "-f",
            f"q={query}",
            "--jq",
            ".total_count",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return int(result.stdout.strip())


def iso(date):
    return date.strftime("%Y-%m-%dT00:00:00Z")


PROFILE_QUERY = """
query($login:String!) {
  user(login:$login) {
    createdAt

    repositories(
      first:100
      ownerAffiliations:OWNER
      isFork:false
    ) {
      nodes {
        stargazerCount
      }
    }

    repositoriesContributedTo(first:1) {
      totalCount
    }
  }
}
"""


CONTRIBUTIONS_QUERY = """
query(
  $login:String!
  $from:DateTime!
  $to:DateTime!
) {
  user(login:$login) {
    contributionsCollection(
      from:$from
      to:$to
    ) {
      totalCommitContributions

      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_history(created_at):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = created_at

    total_commits = 0
    days = {}

    while start < now:
        end = min(
            start + timedelta(days=330),
            now,
        )

        data = graphql(
            CONTRIBUTIONS_QUERY,
            login=LOGIN,
            **{
                "from": iso(start),
                "to": iso(end),
            },
        )

        collection = data["user"]["contributionsCollection"]

        total_commits += int(
            collection["totalCommitContributions"]
        )

        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                date = day["date"]
                count = int(day["contributionCount"])

                days[date] = count

        start = end + timedelta(days=1)

    return total_commits, days


def calculate_streaks(days):
    if not days:
        return 0, 0, 0, None, []

    ordered = sorted(days.items())

    longest = 0
    running = 0

    for _, count in ordered:
        if count > 0:
            running += 1
            longest = max(longest, running)
        else:
            running = 0

    current = 0

    for _, count in reversed(ordered):
        if count > 0:
            current += 1
        else:
            break

    if current > 0:
        current_start = ordered[len(ordered) - current][0]
    else:
        current_start = None

    total_contributions = sum(
        count for _, count in ordered
    )

    recent = ordered[-52:]

    return (
        current,
        longest,
        total_contributions,
        current_start,
        recent,
    )


def format_number(number):
    return f"{int(number):,}"


def svg_header(width, title):
    return [
        (
            f'<circle cx="27" cy="30" r="4" '
            f'fill="{GREEN}"/>'
        ),
        (
            f'<text x="40" y="35" '
            f'fill="{MUTED}" '
            f'font-size="12" '
            f'font-family="{FONT}" '
            f'letter-spacing="2.4">'
            f'{title}'
            f'</text>'
        ),
        (
            f'<text x="{width - 25}" y="35" '
            f'text-anchor="end" '
            f'fill="{MUTED}" '
            f'fill-opacity="0.28" '
            f'font-size="11" '
            f'font-family="{FONT}">'
            f'@{LOGIN}'
            f'</text>'
        ),
    ]


def render_stats(
    stars,
    commits,
    prs,
    issues,
    contributed,
):
    width = 480
    height = 245

    rows = [
        ("★", "Total Stars", stars, YELLOW),
        ("●", "Total Commits", commits, GREEN),
        ("↗", "Total PRs", prs, BLUE),
        ("!", "Total Issues", issues, RED),
        ("◆", "Contributed to", contributed, PURPLE),
    ]

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" '
            f'height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            f'role="img" '
            f'aria-label="GitHub statistics for {LOGIN}">'
        ),
        f'<title>{LOGIN} GitHub statistics</title>',
        (
            f'<rect width="{width}" '
            f'height="{height}" '
            f'rx="10" '
            f'fill="{BG}"/>'
        ),
    ]

    parts.extend(
        svg_header(width, "GITHUB STATS")
    )

    start_y = 74
    row_height = 32

    for index, (
        symbol,
        label,
        value,
        color,
    ) in enumerate(rows):

        y = start_y + index * row_height

        parts.append(
            (
                f'<rect x="25" y="{y - 17}" '
                f'width="24" height="24" '
                f'rx="7" '
                f'fill="{color}"/>'
            )
        )

        parts.append(
            (
                f'<text x="37" y="{y}" '
                f'text-anchor="middle" '
                f'fill="{BG}" '
                f'font-size="14" '
                f'font-weight="700" '
                f'font-family="{FONT}">'
                f'{symbol}'
                f'</text>'
            )
        )

        parts.append(
            (
                f'<text x="64" y="{y}" '
                f'fill="{FG}" '
                f'font-size="14" '
                f'font-family="{FONT}">'
                f'{label}'
                f'</text>'
            )
        )

        parts.append(
            (
                f'<line x1="190" y1="{y - 5}" '
                f'x2="385" y2="{y - 5}" '
                f'stroke="{TRACK}" '
                f'stroke-width="1" '
                f'stroke-dasharray="2 5"/>'
            )
        )

        parts.append(
            (
                f'<text x="{width - 28}" '
                f'y="{y}" '
                f'text-anchor="end" '
                f'fill="{FG}" '
                f'font-size="16" '
                f'font-weight="700" '
                f'font-family="{FONT}">'
                f'{format_number(value)}'
                f'</text>'
            )
        )

    parts.append(
        (
            f'<text x="25" y="{height - 15}" '
            f'fill="{MUTED}" '
            f'font-size="9" '
            f'font-family="{FONT}">'
            f'GitHub contribution statistics · @{LOGIN}'
            f'</text>'
        )
    )

    parts.append("</svg>")

    os.makedirs(
        os.path.dirname(STAT_OUT),
        exist_ok=True,
    )

    with open(
        STAT_OUT,
        "w",
        encoding="utf-8",
    ) as file:
        file.write("\n".join(parts))


def render_streak(
    total,
    current,
    longest,
    current_start,
    recent,
):
    width = 480
    height = 245

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" '
            f'height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            f'role="img" '
            f'aria-label="GitHub contribution streak for {LOGIN}">'
        ),
        f'<title>{LOGIN} contribution streak</title>',
        (
            f'<rect width="{width}" '
            f'height="{height}" '
            f'rx="10" '
            f'fill="{BG}"/>'
        ),
    ]

    parts.extend(
        svg_header(width, "STREAKS")
    )

    parts.append(
        (
            f'<text x="30" y="92" '
            f'fill="{GREEN}" '
            f'font-size="38" '
            f'font-family="{FONT}">'
            f'♨'
            f'</text>'
        )
    )

    parts.append(
        (
            f'<text x="30" y="142" '
            f'fill="{FG}" '
            f'font-size="50" '
            f'font-weight="700" '
            f'font-family="{FONT}">'
            f'{format_number(current)}'
            f'</text>'
        )
    )

    parts.append(
        (
            f'<text x="30" y="165" '
            f'fill="{GREEN}" '
            f'font-size="11" '
            f'font-weight="700" '
            f'letter-spacing="1.8" '
            f'font-family="{FONT}">'
            f'CURRENT STREAK'
            f'</text>'
        )
    )

    if current_start:
        parsed = datetime.strptime(
            current_start,
            "%Y-%m-%d",
        )

        start_label = parsed.strftime(
            "%b %d, %Y"
        )

        period_label = (
            f"{start_label} - Present"
        )
    else:
        period_label = "No active streak"

    parts.append(
        (
            f'<text x="30" y="184" '
            f'fill="{MUTED}" '
            f'font-size="10" '
            f'font-family="{FONT}">'
            f'{period_label}'
            f'</text>'
        )
    )

    parts.append(
        (
            f'<line x1="270" y1="58" '
            f'x2="270" y2="187" '
            f'stroke="{TRACK}"/>'
        )
    )

    parts.append(
        (
            f'<text x="291" y="91" '
            f'fill="{MUTED}" '
            f'font-size="10" '
            f'letter-spacing="1.5" '
            f'font-family="{FONT}">'
            f'LONGEST STREAK'
            f'</text>'
        )
    )

    parts.append(
        (
            f'<text x="291" y="121" '
            f'fill="{FG}" '
            f'font-size="28" '
            f'font-weight="700" '
            f'font-family="{FONT}">'
            f'{format_number(longest)}'
            f'</text>'
        )
    )

    parts.append(
        (
            f'<text x="291" y="158" '
            f'fill="{MUTED}" '
            f'font-size="10" '
            f'letter-spacing="1.5" '
            f'font-family="{FONT}">'
            f'TOTAL CONTRIBUTIONS'
            f'</text>'
        )
    )

    parts.append(
        (
            f'<text x="291" y="188" '
            f'fill="{FG}" '
            f'font-size="28" '
            f'font-weight="700" '
            f'font-family="{FONT}">'
            f'{format_number(total)}'
            f'</text>'
        )
    )

    if recent:
        maximum = max(
            count for _, count in recent
        ) or 1

        start_x = 30
        baseline = 228
        available_width = 420

        bar_width = max(
            2.5,
            available_width / len(recent) - 2,
        )

        gap = 2

        for index, (
            date,
            count,
        ) in enumerate(recent):

            bar_height = max(
                2,
                28 * count / maximum,
            )

            x = (
                start_x
                + index
                * (bar_width + gap)
            )

            parts.append(
                (
                    f'<rect '
                    f'x="{x:.2f}" '
                    f'y="{baseline - bar_height:.2f}" '
                    f'width="{bar_width:.2f}" '
                    f'height="{bar_height:.2f}" '
                    f'rx="1.4" '
                    f'fill="{GREEN}" '
                    f'fill-opacity="0.85">'
                    f'<title>{date}: '
                    f'{count} contributions'
                    f'</title>'
                    f'</rect>'
                )
            )

    parts.append("</svg>")

    os.makedirs(
        os.path.dirname(STREAK_OUT),
        exist_ok=True,
    )

    with open(
        STREAK_OUT,
        "w",
        encoding="utf-8",
    ) as file:
        file.write("\n".join(parts))


def main():
    print(
        f"Collecting GitHub statistics for @{LOGIN}..."
    )

    profile = graphql(
        PROFILE_QUERY,
        login=LOGIN,
    )["user"]

    created_at = datetime.strptime(
        profile["createdAt"][:10],
        "%Y-%m-%d",
    )

    stars = sum(
        repository["stargazerCount"]
        for repository
        in profile["repositories"]["nodes"]
    )

    contributed = int(
        profile[
            "repositoriesContributedTo"
        ]["totalCount"]
    )

    print(
        "Collecting contribution history..."
    )

    commits, days = fetch_history(
        created_at
    )

    print(
        "Collecting pull requests and issues..."
    )

    prs = search_count(
        f"author:{LOGIN} type:pr"
    )

    issues = search_count(
        f"author:{LOGIN} type:issue"
    )

    (
        current,
        longest,
        total,
        current_start,
        recent,
    ) = calculate_streaks(days)

    print("")
    print("=== GitHub Stats ===")
    print(f"Stars: {stars}")
    print(f"Commits: {commits}")
    print(f"Pull Requests: {prs}")
    print(f"Issues: {issues}")
    print(f"Contributed to: {contributed}")
    print(f"Current streak: {current}")
    print(f"Longest streak: {longest}")
    print(f"Total contributions: {total}")
    print("")

    render_stats(
        stars,
        commits,
        prs,
        issues,
        contributed,
    )

    render_streak(
        total,
        current,
        longest,
        current_start,
        recent,
    )

    print(
        f"Generated {STAT_OUT}"
    )

    print(
        f"Generated {STREAK_OUT}"
    )


if __name__ == "__main__":
    main()
