#!/usr/bin/env python3

import json
import math
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone

LOGIN = os.getenv("GH_LOGIN", "therunnas")
OUT = os.getenv("OUT", "assets/cards/activity-graph.svg")
WINDOW_DAYS = 122

BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#8b949e"
GRID = "#21262d"
GREEN = "#40c463"
FONT = "Segoe UI, Ubuntu, Arial, sans-serif"


def graphql(query, **variables):
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]

    for key, value in variables.items():
        cmd += ["-f", f"{key}={value}"]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)

    if data.get("errors"):
        raise RuntimeError(data["errors"])

    return data["data"]


def iso(date):
    return date.strftime("%Y-%m-%dT00:00:00Z")


PROFILE_QUERY = """
query($login:String!) {
  user(login:$login) {
    createdAt
  }
}
"""


CALENDAR_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
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


LANGUAGE_QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    contributionsCollection(from:$from, to:$to) {
      commitContributionsByRepository(maxRepositories:100) {
        contributions {
          totalCount
        }
        repository {
          nameWithOwner
          languages(first:30, orderBy:{field:SIZE, direction:DESC}) {
            edges {
              size
              node {
                name
                color
              }
            }
          }
        }
      }
    }
  }
}
"""


def get_recent_activity(start, end):
    data = graphql(
        CALENDAR_QUERY,
        login=LOGIN,
        **{"from": iso(start), "to": iso(end)},
    )

    days = []

    weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]

    for week in weeks:
        for day in week["contributionDays"]:
            date = datetime.strptime(day["date"], "%Y-%m-%d")

            if start.date() <= date.date() <= end.date():
                days.append(
                    (
                        day["date"],
                        int(day["contributionCount"]),
                    )
                )

    return sorted(days)


def get_language_distribution(created, now):
    weighted = defaultdict(float)
    colors = {}

    start = created

    while start < now:
        end = min(start + timedelta(days=330), now)

        data = graphql(
            LANGUAGE_QUERY,
            login=LOGIN,
            **{"from": iso(start), "to": iso(end)},
        )

        entries = data["user"]["contributionsCollection"]["commitContributionsByRepository"]

        for entry in entries:
            commits = entry["contributions"]["totalCount"]

            if not commits:
                continue

            edges = entry["repository"]["languages"]["edges"]
            total_bytes = sum(edge["size"] for edge in edges)

            if not total_bytes:
                continue

            for edge in edges:
                language = edge["node"]["name"]
                size = edge["size"]

                weighted[language] += commits * (size / total_bytes)

                if edge["node"].get("color"):
                    colors[language] = edge["node"]["color"]

        start = end + timedelta(days=1)

    total = sum(weighted.values())

    if total == 0:
        return [], {}

    ordered = sorted(
        weighted.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    visible = []
    other = 0.0

    for language, value in ordered:
        percentage = value / total * 100

        if percentage >= 1.0:
            visible.append((language, percentage))
        else:
            other += percentage

    if other >= 0.5:
        visible.append(("Other", other))

    return visible, colors


def nice_axis_max(value):
    if value <= 0:
        return 10

    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude

    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10

    return int(nice * magnitude)


def build_svg(days, languages, colors):
    width = 1100
    chart_height = 310
    legend_start = 390

    left = 70
    right = 35
    top = 70
    bottom = 55

    plot_width = width - left - right
    plot_height = chart_height - top - bottom

    values = [count for _, count in days]
    maximum = nice_axis_max(max(values) if values else 0)

    def x(index):
        if len(days) <= 1:
            return left

        return left + plot_width * index / (len(days) - 1)

    def y(value):
        return top + plot_height - (value / maximum) * plot_height

    points = [(x(i), y(value)) for i, value in enumerate(values)]

    if points:
        line = " ".join(
            [
                ("M" if i == 0 else "L") + f" {px:.2f} {py:.2f}"
                for i, (px, py) in enumerate(points)
            ]
        )

        area = (
            line
            + f" L {points[-1][0]:.2f} {top + plot_height:.2f}"
            + f" L {points[0][0]:.2f} {top + plot_height:.2f} Z"
        )
    else:
        line = ""
        area = ""

    total_contributions = sum(values)

    legend_rows = []
    current_row = []
    used_width = 0

    for language, percentage in languages:
        estimated = 115 + len(language) * 7

        if used_width + estimated > width - 80 and current_row:
            legend_rows.append(current_row)
            current_row = []
            used_width = 0

        current_row.append((language, percentage))
        used_width += estimated

    if current_row:
        legend_rows.append(current_row)

    height = legend_start + max(1, len(legend_rows)) * 42 + 30

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" rx="8" fill="{BG}"/>',
        f'<text x="{left}" y="36" fill="{FG}" font-family="{FONT}" font-size="20" font-weight="700">{total_contributions:,} contributions in the last 4 months</text>',
        f'<text x="{width-right}" y="36" text-anchor="end" fill="{MUTED}" font-family="{FONT}" font-size="13">daily activity · @{LOGIN}</text>',
    ]

    for i in range(5):
        value = maximum * i / 4
        py = top + plot_height - plot_height * i / 4

        parts.append(
            f'<line x1="{left}" y1="{py:.2f}" x2="{width-right}" y2="{py:.2f}" stroke="{GRID}" stroke-width="1"/>'
        )

        parts.append(
            f'<text x="{left-12}" y="{py+5:.2f}" text-anchor="end" fill="{MUTED}" font-family="{FONT}" font-size="12">{int(value)}</text>'
        )

    if days:
        tick_every = max(1, len(days) // 8)

        for i in range(0, len(days), tick_every):
            date = datetime.strptime(days[i][0], "%Y-%m-%d")

            parts.append(
                f'<text x="{x(i):.2f}" y="{top+plot_height+28}" text-anchor="middle" fill="{MUTED}" font-family="{FONT}" font-size="12">{date.strftime("%b %d")}</text>'
            )

    if area:
        parts.append(
            f'<path d="{area}" fill="{GREEN}" fill-opacity="0.14"/>'
        )

        parts.append(
            f'<path d="{line}" fill="none" stroke="{GREEN}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        )

        for index, (px, py) in enumerate(points):
            parts.append(
                f'<circle cx="{px:.2f}" cy="{py:.2f}" r="2.4" fill="{GREEN}">'
                f'<title>{days[index][0]}: {days[index][1]} contributions</title>'
                f'</circle>'
            )

    parts.append(
        f'<text x="40" y="{legend_start-28}" fill="{MUTED}" font-family="{FONT}" font-size="12">share of commits by stack · all time</text>'
    )

    current_y = legend_start

    for row in legend_rows:
        current_x = 40

        for language, percentage in row:
            color = colors.get(language, MUTED)
            if language == "Other":
                color = MUTED

            label = f"{language}  {percentage:.1f}%"
            pill_width = 50 + len(label) * 7.2

            parts.append(
                f'<rect x="{current_x}" y="{current_y-22}" width="{pill_width:.1f}" height="30" rx="15" fill="{color}" fill-opacity="0.11" stroke="{color}" stroke-opacity="0.65"/>'
            )

            parts.append(
                f'<circle cx="{current_x+16}" cy="{current_y-7}" r="6" fill="{color}"/>'
            )

            parts.append(
                f'<text x="{current_x+30}" y="{current_y-2}" fill="{FG}" font-family="{FONT}" font-size="13">{language}</text>'
            )

            parts.append(
                f'<text x="{current_x+pill_width-12}" y="{current_y-2}" text-anchor="end" fill="{color}" font-family="{FONT}" font-weight="700" font-size="13">{percentage:.1f}%</text>'
            )

            current_x += pill_width + 16

        current_y += 42

    parts.append("</svg>")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    with open(OUT, "w", encoding="utf-8") as file:
        file.write("\n".join(parts))


def main():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=WINDOW_DAYS - 1)

    profile = graphql(PROFILE_QUERY, login=LOGIN)["user"]
    created = datetime.strptime(profile["createdAt"][:10], "%Y-%m-%d")

    print("Fetching recent contribution activity...")
    days = get_recent_activity(start, now)

    print("Calculating language distribution...")
    languages, colors = get_language_distribution(created, now)

    build_svg(days, languages, colors)

    print(f"Generated {OUT}")


if __name__ == "__main__":
    main()
