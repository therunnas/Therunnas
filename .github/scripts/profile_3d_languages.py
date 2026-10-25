#!/usr/bin/env python3
"""
Replaces the language donut of the 3D contribution calendar with the
profile's single language source (languages.json, written by
activity_graph.py).

Why: github-profile-3d-contrib always draws a donut of *commits in the last
year grouped by each repository's primary language*, limited to what its
token can see. The profile reports languages by *code size* instead, so the
two charts disagreed (e.g. Kotlin from the profile repository's template).
The action has no setting to change or hide that donut.

What it does, for every SVG in PROFILE_3D_DIR:
- finds the donut group, which the action (pinned by SHA) draws at a fixed
  position on a fixed 1280x850 canvas;
- replaces only that group with a donut drawn from languages.json, using the
  SVG's own theme classes (fill-fg / stroke-bg) so every variant keeps its
  colors;
- leaves the calendar, radar and totals untouched.

It is idempotent (the replaced group is marked) and stops without writing
anything if any file does not have the expected structure.
"""

import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from html import escape
from pathlib import Path

LANGUAGES_IN = os.getenv("LANGUAGES_IN", "assets/cards/languages.json")
PROFILE_3D_DIR = os.getenv("PROFILE_3D_DIR", "profile-3d-contrib")

CANVAS = '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="850" viewBox="0 0 1280 850">'
ORIGINAL = '<g transform="translate(40, 520)">'
MARKED = '<g id="languages-code-size" transform="translate(40, 520)">'

# Same geometry as the action's createPieLanguage (pieHeight = 260).
HEIGHT = 260
RADIUS = HEIGHT / 2
MARGIN = RADIUS / 10
ROWS = 8
FONT_SIZE = HEIGHT / ROWS / 1.5

TAG = re.compile(r"<g[\s>]|</g>")


def group_end(text, start):
    """Index just after the </g> that closes the <g> opened at start."""
    depth = 0

    for match in TAG.finditer(text, start):
        if match.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return match.end()
        else:
            depth += 1

    raise ValueError("unbalanced <g>")


def point(radius, angle):
    # Angle 0 at 12 o'clock, clockwise, as d3.pie draws it.
    return RADIUS + radius * math.sin(angle), RADIUS - radius * math.cos(angle)


def slice_path(start, end, outer, inner):
    if end - start >= 2 * math.pi:
        end = start + 2 * math.pi - 1e-4

    large = 1 if end - start > math.pi else 0
    ox0, oy0 = point(outer, start)
    ox1, oy1 = point(outer, end)
    ix1, iy1 = point(inner, end)
    ix0, iy0 = point(inner, start)

    return (
        f"M{ox0:.2f},{oy0:.2f}A{outer:.2f},{outer:.2f},0,{large},1,{ox1:.2f},{oy1:.2f}"
        f"L{ix1:.2f},{iy1:.2f}A{inner:.2f},{inner:.2f},0,{large},0,{ix0:.2f},{iy0:.2f}Z"
    )


def donut(languages):
    total = sum(language["percentage"] for language in languages)
    offset = (ROWS - len(languages) - 1) / 2 + 0.5
    row_height = HEIGHT / ROWS

    paths = []
    labels = []
    angle = 0.0

    for index, language in enumerate(languages):
        name = escape(language["name"])
        share = f'{language["percentage"]:.1f}%'
        end = angle + 2 * math.pi * language["percentage"] / total

        paths.append(
            f'<path d="{slice_path(angle, end, RADIUS - MARGIN, RADIUS / 2)}" style="fill: {language["color"]};" '
            f'class="stroke-bg" stroke-width="2px"><title>{name} {share} of code size</title></path>'
        )
        angle = end

        y = (index + offset) * row_height
        labels.append(
            f'<rect x="0" y="{y - FONT_SIZE / 2:.2f}" width="{FONT_SIZE:.2f}" height="{FONT_SIZE:.2f}" '
            f'fill="{language["color"]}" class="stroke-bg" stroke-width="1px"></rect>'
            f'<text dominant-baseline="middle" x="{FONT_SIZE * 1.2:.2f}" y="{y:.2f}" class="fill-fg" '
            f'font-size="{FONT_SIZE:.2f}px">{name} {share}</text>'
        )

    caption_y = (len(languages) + offset) * row_height + row_height * 0.15
    labels.append(
        f'<text dominant-baseline="middle" x="0" y="{caption_y:.2f}" class="fill-fg" fill-opacity="0.6" '
        f'font-size="{FONT_SIZE * 0.72:.2f}px">share of code size · owned repositories</text>'
    )

    return (
        f"{MARKED}"
        f'<g transform="translate({RADIUS * 2.1}, 0)">{"".join(labels)}</g>'
        f'<g transform="translate({RADIUS}, {RADIUS})"><g transform="translate({-RADIUS}, {-RADIUS})">{"".join(paths)}</g></g>'
        "</g>"
    )


def replace(text, replacement):
    if CANVAS not in text[:400]:
        raise ValueError("unexpected canvas")

    original = text.count(ORIGINAL)
    marked = text.count(MARKED)

    if original + marked != 1:
        raise ValueError(f"expected one donut group, found {original} original and {marked} replaced")

    start = text.index(ORIGINAL if original else MARKED)
    end = group_end(text, start)
    group = text[start:end]

    if original and not ('class="stroke-bg"' in group and 'class="fill-fg"' in group and "<path" in group):
        raise ValueError("group at the donut position does not look like the language donut")

    return text[:start] + replacement + text[end:]


def main():
    with open(LANGUAGES_IN, encoding="utf-8") as file:
        languages = json.load(file)["languages"]

    if not languages:
        sys.exit("No languages in the source: 3D graphs left unchanged.")

    replacement = donut(languages)
    updated = {}

    for path in sorted(Path(PROFILE_3D_DIR).glob("*.svg")):
        text = path.read_text(encoding="utf-8")

        try:
            result = replace(text, replacement)
            ElementTree.fromstring(result)
        except (ValueError, ElementTree.ParseError) as error:
            sys.exit(f"{path}: {error}. No file was changed.")

        updated[path] = result

    if not updated:
        sys.exit(f"No SVG found in {PROFILE_3D_DIR}.")

    for path, result in updated.items():
        path.write_text(result, encoding="utf-8")

    summary = ", ".join(f'{language["name"]} {language["percentage"]:.1f}%' for language in languages)
    print(f"Updated language donut in {len(updated)} files: {summary}")


if __name__ == "__main__":
    main()
