#!/usr/bin/env python3
"""
Renders the activity graph from metrics.json (written by github_stats.py)
plus the language distribution of the owner's repositories.

The daily line shows public, itemized contributions only. Private activity
is reported by GitHub as an aggregate that cannot be verified, so it is
left out of the chart.

The language distribution is also written to LANGUAGES_OUT. It is the single
source for every language chart in the profile (this graph and the donut in
the 3D calendar), so both always show the same numbers.

Two versions are written: OUT for desktop and OUT_MOBILE for the README
<picture> switch on small screens.
"""

import json
import math
import os
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta

import card_style as style

LOGIN = os.getenv("GH_LOGIN", "therunnas")
OUT = os.getenv("OUT", "assets/cards/activity-graph.svg")
OUT_MOBILE = os.getenv("OUT_MOBILE", "assets/cards/activity-graph-mobile.svg")
METRICS_IN = os.getenv("METRICS_IN", "assets/cards/metrics.json")
LANGUAGES_OUT = os.getenv("LANGUAGES_OUT", "assets/cards/languages.json")
EXCLUDE_REPOS = {
    name.strip().lower()
    for name in os.getenv("EXCLUDE_REPOS", "").split(",")
    if name.strip()
}
WINDOW_DAYS = 122
TOP_LANGUAGES = 5

OTHER_COLOR = style.APAGADO

# Geometry per version.
LAYOUTS = {
    "desktop": {
        "width": style.DESKTOP_WIDTH,
        "left": 56,
        "right": 32,
        "top": 96,
        "plot_height": 150,
        "ticks": 6,
        "pills_per_row": 3,
        "title": "{total} public {noun} in the last 4 months",
        "note": "Private activity is not itemized by GitHub and is not plotted.",
    },
    "mobile": {
        "width": style.MOBILE_WIDTH,
        "left": 46,
        "right": 22,
        "top": 104,
        "plot_height": 130,
        "ticks": 3,
        "pills_per_row": 2,
        "title": "{total} public {noun} · last 4 months",
        "note": "Private activity is not itemized; not plotted.",
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
    """Share of code size per language: top languages plus "Other"."""
    # The profile repository only holds generated assets and scripts.
    excluded_repositories = {f"{LOGIN}/{LOGIN}".lower()} | EXCLUDE_REPOS

    totals = defaultdict(int)
    colors = {}
    counted = 0

    for repository in get_repositories():
        repository_name = repository["nameWithOwner"]

        if repository["isArchived"]:
            continue

        if repository_name.lower() in excluded_repositories:
            continue

        counted += 1

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
        return {"languages": [], "repositories": counted}

    ordered = sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    languages = [
        {
            "name": language,
            "percentage": round(size / grand_total * 100, 1),
            "color": colors.get(language, OTHER_COLOR),
        }
        for language, size in ordered[:TOP_LANGUAGES]
    ]

    rest = sum(size for _, size in ordered[TOP_LANGUAGES:])
    if rest:
        languages.append(
            {
                "name": "Other",
                "percentage": round(rest / grand_total * 100, 1),
                "color": OTHER_COLOR,
            }
        )

    return {"languages": languages, "repositories": counted}


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


def build_svg(days, languages, as_of, layout):
    width = layout["width"]
    left = layout["left"]
    right = layout["right"]
    top = layout["top"]
    plot_height = layout["plot_height"]
    plot_width = width - left - right
    bottom = top + plot_height

    values = [count for _, count in days]
    maximum = nice_axis_max(max(values) if values else 0)

    def x(index):
        if len(days) <= 1:
            return left

        return left + plot_width * index / (len(days) - 1)

    def y(value):
        return bottom - (value / maximum) * plot_height

    points = [(x(i), y(value)) for i, value in enumerate(values)]
    total_contributions = sum(values)
    noun = "contribution" if total_contributions == 1 else "contributions"
    title = layout["title"].format(total=f"{total_contributions:,}", noun=noun)
    pad = right

    body = [
        f'<text class="k" x="{pad}" y="38">PUBLIC ACTIVITY</text>',
        f'<text class="k" x="{width - pad}" y="38" text-anchor="end">AS OF {as_of}</text>',
        f'<text class="h" x="{pad}" y="66">{style.text(title)}</text>',
    ]

    for i in range(5):
        value = maximum * i // 4
        py = bottom - plot_height * i / 4
        body.append(f'<line x1="{left}" y1="{py:.1f}" x2="{width - right}" y2="{py:.1f}" stroke="{style.BORDA}" stroke-width="1"/>')
        body.append(f'<text class="ax" x="{left - 10}" y="{py + 4:.1f}" text-anchor="end">{value}</text>')

    tick_every = max(1, len(days) // layout["ticks"])
    for i in range(0, len(days), tick_every):
        date = datetime.strptime(days[i][0], "%Y-%m-%d")
        body.append(f'<text class="ax" x="{x(i):.1f}" y="{bottom + 20}" text-anchor="middle">{date:%b %d}</text>')

    if points:
        line = " ".join(("M" if i == 0 else "L") + f"{px:.1f} {py:.1f}" for i, (px, py) in enumerate(points))
        area = f"{line} L{points[-1][0]:.1f} {bottom} L{points[0][0]:.1f} {bottom} Z"
        dots = "".join(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{style.CLARO}"><title>{days[i][0]}: {days[i][1]} public contributions</title></circle>'
            for i, (px, py) in enumerate(points)
            if days[i][1]
        )
        body.append(
            f'<g class="up" {style.delay(.2)}><path d="{area}" fill="url(#area)"/>'
            f'<path class="ln" d="{line}" fill="none" stroke="{style.DESTAQUE}" stroke-width="2" stroke-linejoin="round" pathLength="100"/>'
            f"{dots}</g>"
        )

    body.append(f'<text class="f" x="{pad}" y="{bottom + 42}">{style.text(layout["note"])}</text>')

    # Language pills.
    legend_top = bottom + 72
    body.append(f'<text class="k" x="{pad}" y="{legend_top}">LANGUAGES · CODE SIZE · OWNED REPOSITORIES</text>')

    per_row = layout["pills_per_row"]
    gap = 10
    pill_width = (width - 2 * pad - gap * (per_row - 1)) / per_row
    pill_height = 30
    rows = -(-len(languages) // per_row) if languages else 0

    for index, language in enumerate(languages):
        row, col = divmod(index, per_row)
        px = pad + col * (pill_width + gap)
        py = legend_top + 14 + row * (pill_height + gap)
        color = language["color"]
        body.append(
            f'<g class="up" {style.delay(.4 + index * .08)}>'
            f'<rect x="{px:.1f}" y="{py}" width="{pill_width:.1f}" height="{pill_height}" rx="{pill_height / 2}" fill="{style.CAIXA}" stroke="{style.BORDA2}"/>'
            f'<circle cx="{px + 15:.1f}" cy="{py + pill_height / 2}" r="5" fill="{color}"/>'
            f'<text class="lg" x="{px + 27:.1f}" y="{py + 19.5}">{style.text(language["name"])}</text>'
            f'<text class="lp" x="{px + pill_width - 12:.1f}" y="{py + 19.5}" text-anchor="end" fill="{style.TINTA}">{language["percentage"]:.1f}%</text>'
            "</g>"
        )

    height = int(legend_top + 14 + max(rows, 1) * (pill_height + gap) + 18)
    label = f"Public GitHub activity for {LOGIN}: {title}. Languages by code size: " + ", ".join(
        f'{language["name"]} {language["percentage"]:.1f}%' for language in languages
    )

    return style.svg(width, height, label, "\n".join(body))


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
    distribution = get_language_distribution()
    languages = distribution["languages"]

    write(
        LANGUAGES_OUT,
        json.dumps(
            {
                "as_of": metrics["as_of"],
                "criterion": "Share of code size (GitHub linguist bytes) across owned, non-fork, non-archived repositories, public and private; the profile repository and EXCLUDE_REPOS are left out.",
                "grouping": f"Top {TOP_LANGUAGES} languages, the rest as Other.",
                "repositories_counted": distribution["repositories"],
                "languages": languages,
            },
            indent=2,
        ),
    )

    write(OUT, build_svg(days, languages, metrics["as_of"], LAYOUTS["desktop"]))
    write(OUT_MOBILE, build_svg(days, languages, metrics["as_of"], LAYOUTS["mobile"]))

    print(f"Generated {OUT}, {OUT_MOBILE} and {LANGUAGES_OUT}")


if __name__ == "__main__":
    main()
