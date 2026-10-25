#!/usr/bin/env python3
"""
Renders the activity graph from metrics.json (written by github_stats.py)
plus the language distribution of the owner's repositories.

The daily line shows public, itemized contributions only. Private activity
is reported by GitHub as an aggregate that cannot be verified, so it is
left out of the chart.

Two versions are written: OUT for desktop and OUT_MOBILE (narrower, larger
text) for the README <picture> switch on small screens.
"""

import json
import math
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

LOGIN = os.getenv("GH_LOGIN", "therunnas")
OUT = os.getenv("OUT", "assets/cards/activity-graph.svg")
OUT_MOBILE = os.getenv("OUT_MOBILE", "assets/cards/activity-graph-mobile.svg")
METRICS_IN = os.getenv("METRICS_IN", "assets/cards/metrics.json")
EXCLUDE_REPOS = {
    name.strip().lower()
    for name in os.getenv("EXCLUDE_REPOS", "").split(",")
    if name.strip()
}
WINDOW_DAYS = 122

BG = "#0d1117"
FG = "#c9d1d9"
MUTED = "#8b949e"
GRID = "#21262d"
GREEN = "#40c463"
FONT = "Segoe UI, Ubuntu, Arial, sans-serif"

# Geometry per version. Font sizes are multiplied by "scale".
LAYOUTS = {
    "desktop": {
        "width": 1100,
        "scale": 1.0,
        "left": 70,
        "right": 35,
        "top": 70,
        "plot_height": 185,
        "ticks": 8,
        "stacked_header": False,
        "title": "{total} public {noun} in the last 4 months",
        "note": "Private activity is not itemized by GitHub and is not plotted.",
        "languages": "languages · owned repositories, public and private, by code size",
    },
    "mobile": {
        "width": 600,
        "scale": 1.5,
        "left": 56,
        "right": 24,
        "top": 104,
        "plot_height": 200,
        "ticks": 4,
        "stacked_header": True,
        "title": "{total} public {noun} · last 4 months",
        "note": "Private activity is not itemized; not plotted.",
        "languages": "languages · owned repos, public + private",
    },
}


def graphql(query, **variables):
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]

    for key, value in variables.items():
        if value is not None:
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


REPOSITORIES_QUERY = """
query($login:String!, $after:String) {
  user(login:$login) {
    repositories(
      first:100
      after:$after
      ownerAffiliations:OWNER
      isFork:false
      orderBy:{field:PUSHED_AT, direction:DESC}
    ) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        isArchived
        languages(first:100, orderBy:{field:SIZE, direction:DESC}) {
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
"""


def get_recent_activity(metrics):
    end = datetime.strptime(metrics["as_of"], "%Y-%m-%d")
    public = metrics["daily"]["public"]
    days = []

    for offset in range(WINDOW_DAYS - 1, -1, -1):
        day = (end - timedelta(days=offset)).strftime("%Y-%m-%d")
        days.append((day, int(public.get(day, 0))))

    return days


def get_repositories():
    repositories = []
    after = None

    while True:
        data = graphql(REPOSITORIES_QUERY, login=LOGIN, after=after)
        connection = data["user"]["repositories"]
        repositories += connection["nodes"]

        if not connection["pageInfo"]["hasNextPage"]:
            return repositories

        after = connection["pageInfo"]["endCursor"]


def get_language_distribution():
    # The profile repository only holds generated assets and scripts.
    excluded_repositories = {f"{LOGIN}/{LOGIN}".lower()} | EXCLUDE_REPOS

    totals = defaultdict(int)
    colors = {}

    for repository in get_repositories():
        repository_name = repository["nameWithOwner"]

        if repository["isArchived"]:
            continue

        if repository_name.lower() in excluded_repositories:
            continue

        for edge in repository["languages"]["edges"]:
            language = edge["node"]["name"]
            size = int(edge["size"])

            if size <= 0:
                continue

            totals[language] += size

            if edge["node"].get("color"):
                colors[language] = edge["node"]["color"]

    grand_total = sum(totals.values())

    if grand_total == 0:
        return [], {}

    ordered = sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    visible = []
    other = 0.0

    for language, size in ordered:
        percentage = size / grand_total * 100

        if percentage >= 1.0:
            visible.append((language, percentage))
        else:
            other += percentage

    if other >= 0.5:
        visible.append(("Other", other))

    return visible, colors


def nice_axis_max(value):
    """Axis top divisible by 4, so the 5 grid lines get whole numbers."""
    if value <= 4:
        return 4

    if value < 40:
        return 4 * math.ceil(value / 4)

    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude

    if normalized <= 2:
        nice = 2
    elif normalized <= 4:
        nice = 4
    elif normalized <= 8:
        nice = 8
    else:
        nice = 20

    return int(nice * magnitude)


def build_svg(days, languages, colors, as_of, layout):
    width = layout["width"]
    scale = layout["scale"]

    left = layout["left"]
    right = layout["right"]
    top = layout["top"]
    plot_height = layout["plot_height"]
    plot_width = width - left - right

    def size(points):
        return round(points * scale, 1)

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
    noun = "contribution" if total_contributions == 1 else "contributions"

    pill_height = size(30)
    char_width = 7.2 * scale
    row_gap = pill_height + size(12)
    legend_start = top + plot_height + size(110)

    legend_rows = []
    current_row = []
    used_width = 0

    for language, percentage in languages:
        estimated = 50 * scale + len(f"{language}  {percentage:.1f}%") * char_width + 16

        if used_width + estimated > width - 40 and current_row:
            legend_rows.append(current_row)
            current_row = []
            used_width = 0

        current_row.append((language, percentage))
        used_width += estimated

    if current_row:
        legend_rows.append(current_row)

    height = int(legend_start + max(1, len(legend_rows)) * row_gap + size(10))

    title = layout["title"].format(total=f"{total_contributions:,}", noun=noun)
    subtitle = f"daily public activity · as of {as_of} · @{LOGIN}"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Public GitHub activity for {LOGIN}">',
        f"<title>Public GitHub activity for {LOGIN}</title>",
        f'<rect width="100%" height="100%" rx="8" fill="{BG}"/>',
    ]

    if layout["stacked_header"]:
        parts += [
            f'<text x="{right}" y="{size(26)}" fill="{FG}" font-family="{FONT}" font-size="{size(18)}" font-weight="700">{title}</text>',
            f'<text x="{right}" y="{size(46)}" fill="{MUTED}" font-family="{FONT}" font-size="{size(11)}">{subtitle}</text>',
        ]
    else:
        parts += [
            f'<text x="{left}" y="36" fill="{FG}" font-family="{FONT}" font-size="20" font-weight="700">{title}</text>',
            f'<text x="{width-right}" y="36" text-anchor="end" fill="{MUTED}" font-family="{FONT}" font-size="13">{subtitle}</text>',
        ]

    for i in range(5):
        value = maximum * i // 4
        py = top + plot_height - plot_height * i / 4

        parts.append(
            f'<line x1="{left}" y1="{py:.2f}" x2="{width-right}" y2="{py:.2f}" stroke="{GRID}" stroke-width="1"/>'
        )

        parts.append(
            f'<text x="{left-12}" y="{py+5:.2f}" text-anchor="end" fill="{MUTED}" font-family="{FONT}" font-size="{size(12)}">{value}</text>'
        )

    if days:
        tick_every = max(1, len(days) // layout["ticks"])

        for i in range(0, len(days), tick_every):
            date = datetime.strptime(days[i][0], "%Y-%m-%d")

            parts.append(
                f'<text x="{x(i):.2f}" y="{top + plot_height + size(24):.1f}" text-anchor="middle" fill="{MUTED}" font-family="{FONT}" font-size="{size(12)}">{date.strftime("%b %d")}</text>'
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
                f'<title>{days[index][0]}: {days[index][1]} public contributions</title>'
                f'</circle>'
            )

    parts.append(
        f'<text x="{right}" y="{top + plot_height + size(50):.1f}" fill="{MUTED}" font-family="{FONT}" font-size="{size(11)}">{layout["note"]}</text>'
    )

    parts.append(
        f'<text x="{right}" y="{legend_start - size(28):.1f}" fill="{MUTED}" font-family="{FONT}" font-size="{size(12)}">{layout["languages"]}</text>'
    )

    current_y = legend_start

    for row in legend_rows:
        current_x = right

        for language, percentage in row:
            color = colors.get(language, MUTED)
            if language == "Other":
                color = MUTED

            label = f"{language}  {percentage:.1f}%"
            pill_width = 50 * scale + len(label) * char_width
            middle = current_y - size(7)

            parts.append(
                f'<rect x="{current_x:.1f}" y="{current_y - size(22):.1f}" width="{pill_width:.1f}" height="{pill_height}" rx="{pill_height / 2}" fill="{color}" fill-opacity="0.11" stroke="{color}" stroke-opacity="0.65"/>'
            )

            parts.append(
                f'<circle cx="{current_x + size(16):.1f}" cy="{middle:.1f}" r="{size(6)}" fill="{color}"/>'
            )

            parts.append(
                f'<text x="{current_x + size(30):.1f}" y="{current_y - size(2):.1f}" fill="{FG}" font-family="{FONT}" font-size="{size(13)}">{language}</text>'
            )

            parts.append(
                f'<text x="{current_x + pill_width - size(12):.1f}" y="{current_y - size(2):.1f}" text-anchor="end" fill="{color}" font-family="{FONT}" font-weight="700" font-size="{size(13)}">{percentage:.1f}%</text>'
            )

            current_x += pill_width + 16

        current_y += row_gap

    parts.append("</svg>")

    return "\n".join(parts)


def write(path, content):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


def main():
    with open(METRICS_IN, encoding="utf-8") as file:
        metrics = json.load(file)

    print("Reading public activity from metrics...")
    days = get_recent_activity(metrics)

    print("Calculating language distribution...")
    languages, colors = get_language_distribution()

    write(OUT, build_svg(days, languages, colors, metrics["as_of"], LAYOUTS["desktop"]))
    write(OUT_MOBILE, build_svg(days, languages, colors, metrics["as_of"], LAYOUTS["mobile"]))

    print(f"Generated {OUT} and {OUT_MOBILE}")


if __name__ == "__main__":
    main()
