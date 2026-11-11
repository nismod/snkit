"""Draw the catalogue of examples from the conformance cases.

Reads the operation-level cases in ``conformance/operations``, draws one figure
for each into ``docs/source/_static/examples``, and writes the page
``docs/source/examples.md`` that shows them. Figures of cases that no longer
exist are removed.

    python docs/make_examples.py

The page and the list of figures are generated, never edited by hand, and a
test (``tests/test_conformance.py``) fails if either is out of date.
"""

from __future__ import annotations

import json
import math
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "conformance"))

import run  # noqa: E402

PAGE = ROOT / "docs" / "source" / "examples.md"
IMAGES = ROOT / "docs" / "source" / "_static" / "examples"

# sections of the page: heading, a line of introduction, and the operations in it
GROUPS: List[Tuple[str, str, List[str]]] = [
    (
        "Creating a network",
        "From lines, or points and lines, to nodes and edges that refer to each other.",
        ["from_edges", "from_nodes_and_edges", "from_topology"],
    ),
    (
        "Matchers",
        "Matchers find things and change nothing. Each figure shows the network with the matches marked, "
        "and the table of matches is below it.",
        ["match_nodes", "match_nodes_to_edges", "find_crossings", "match_edges"],
    ),
    ("Nodes close together", "Merge them, or keep them and link them.", ["merge_nodes", "link_nodes"]),
    (
        "Splitting and linking",
        "Operations that cut edges, at places given, at nodes, or where edges cross.",
        ["split_edges", "split_edges_at_nodes", "link_nodes_to_edges", "split_edges_at_crossings"],
    ),
    (
        "Tidying edges",
        "Fewer vertices, fewer edges.",
        ["simplify_edges", "merge_edges", "drop_duplicate_edges"],
    ),
    ("Connected parts", "", ["label_components"]),
    (
        "Several networks",
        "Each input network has a panel of its own. Edges are matched between networks, never within one.",
        ["combine", "stitch", "union", "intersection", "difference"],
    ),
]

INTRO = """\
# Examples

Every operation, on networks small enough to check by eye. Each example is one of the
conformance cases in the `conformance` directory of the repository: a data file giving an
input, parameters and the expected result, which the tests run. The figures and this page
are drawn from those files by `docs/make_examples.py`, so they cannot drift apart.

How to read a figure:

- The input is on the left and the expected result on the right, at the same scale. The
  call is written underneath.
- A dot is a node, with its id beside it. A ring is a node that the operation created.
- A line is an edge, with its id in a box and an arrow showing its direction, from
  `from_id` to `to_id`. Each edge in a panel has its own colour, so the pieces of a split
  edge can be told apart. Colours do not carry over from input to result: follow the ids.
  An edge that lies along another is dashed, so that both show.
- Attributes are not drawn. Where a case has them, they are in tables under the figure.
"""

OUTRO = """\
## Kernel cases

A second set of cases, in `conformance/kernel`, pins down the functions of the array kernel
on plain arrays. They have no figures. `conformance/README.md` sets out the format of both
sets.
"""

RESERVED = ("id", "from_id", "to_id", "geometry")

# categorical colours for edges, in a fixed order (the dataviz reference palette)
EDGE_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a897f"
GRID = "#e9e8e3"
SURFACE = "#ffffff"

# sizes, in points
WIDTH = 518.0
LEFT, RIGHT, TOP, BOTTOM = 26.0, 8.0, 20.0, 16.0
CAPTION = 22.0
MARGIN = 20.0
MIN_HEIGHT, MAX_HEIGHT = 84.0, 220.0
FONT = 7.5


# ---------------------------------------------------------------------------
# The cases, in order


def ordered_cases() -> Dict[str, Dict[str, Any]]:
    """Operation-level cases by name, in the order they are defined in generate.py"""
    cases = run.load_cases("operations")
    try:
        import generate

        position = {name: index for index, name in enumerate(generate.CASES)}
    except Exception:  # the page can still be built from the files alone
        position = {}
    return dict(sorted(cases.items(), key=lambda item: (position.get(item[0], len(position)), item[0])))


def image_name(name: str) -> str:
    _, operation, case = name.split("/")
    return f"{operation}.{case}.svg"


def image_names(cases: Dict[str, Dict[str, Any]]) -> List[str]:
    return sorted(image_name(name) for name in cases)


# ---------------------------------------------------------------------------
# The page


def _value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_value(item) for item in value)
    return str(value)


def _table(rows: List[Dict[str, Any]], columns: Sequence[str]) -> List[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + " --- |" * len(columns)]
    for row in rows:
        lines.append("| " + " | ".join(_value(row.get(column)) for column in columns) + " |")
    return lines


def _attribute_columns(rows: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for row in rows:
        names.extend(key for key in row if key not in RESERVED and key not in names)
    return names


def _attribute_tables(label: str, data: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for kind in ("points", "lines", "nodes", "edges"):
        rows = data.get(kind, [])
        columns = _attribute_columns(rows)
        if not columns:
            continue
        if "id" in rows[0] and isinstance(rows[0]["id"], int):
            columns = ["id"] + columns
        else:
            rows = [{"row": position, **row} for position, row in enumerate(rows)]
            columns = ["row"] + [c for c in ("id", "from_id", "to_id") if c in rows[0]] + columns
        lines += [f"{label} {kind}:", ""] + _table(rows, columns) + [""]
    return lines


def _tables(case: Dict[str, Any]) -> List[str]:
    """Markdown tables of what a figure cannot show: matches, and attributes"""
    data, expected = case["input"], case["expected"]
    lines: List[str] = []
    if "matches" in expected:
        rows = expected["matches"]
        if not rows:
            return ["No matches.", ""]
        return _table(rows, list(MATCH_COLUMNS[case["operation"]])) + [""]
    if "networks" in data:
        for name in sorted(data["networks"]):
            lines += _attribute_tables(f"Input `{name}`", data["networks"][name])
    else:
        lines += _attribute_tables("Input", data)
    if not expected.get("error"):
        lines += _attribute_tables("Expected", expected)
    return lines


MATCH_COLUMNS = {
    "match_nodes": ("node_a", "node_b", "distance"),
    "match_nodes_to_edges": ("node", "edge", "measure", "x", "y", "distance"),
    "find_crossings": ("edge_a", "measure_a", "edge_b", "measure_b", "x", "y"),
    "match_edges": ("edge_a", "start_a", "end_a", "edge_b", "start_b", "end_b", "reversed", "distance"),
}


def render_page(cases: Dict[str, Dict[str, Any]]) -> str:
    """The text of examples.md"""
    by_operation: Dict[str, List[str]] = {}
    for name, case in cases.items():
        by_operation.setdefault(case["operation"], []).append(name)
    grouped = [operation for _, _, operations in GROUPS for operation in operations]
    missing = sorted(set(by_operation) - set(grouped))
    assert not missing, f"operations with cases but no section of the page: {missing}"

    lines = [INTRO]
    for heading, introduction, operations in GROUPS:
        if not any(operation in by_operation for operation in operations):
            continue
        lines += [f"## {heading}", ""]
        if introduction:
            lines += [introduction, ""]
        for operation in operations:
            if operation not in by_operation:
                continue
            lines += [f"### `{operation}`", ""]
            for name in by_operation[operation]:
                case = cases[name]
                lines += [
                    f"#### {case['title']}",
                    "",
                    case["note"],
                    "",
                    f"![{operation}: {case['title']}](_static/examples/{image_name(name)})",
                    "",
                ]
                lines += _tables(case)
                lines += [f"Case file: `conformance/{name}.json`", ""]
    lines.append(OUTRO)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Figures


def _parameter(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {_parameter(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_parameter(item) for item in value) + "]"
    return json.dumps(value)


def caption(case: Dict[str, Any]) -> str:
    """The call a case makes, as text"""
    parameters = ", ".join(f"{key}={_parameter(value)}" for key, value in case.get("parameters", {}).items())
    data = case["input"]
    if "networks" in data:
        names = sorted(data["networks"])
        subject = ", ".join(names) if case["operation"] in run.TWO_NETWORKS else "{" + ", ".join(names) + "}"
    elif case["operation"] in run.CREATION:
        subject = ", ".join(kind for kind in ("points", "nodes", "lines", "edges") if kind in data)
    else:
        subject = "network"
    return f"{case['operation']}({', '.join(part for part in (subject, parameters) if part)})"


class Panel:
    """What one panel of a figure shows"""

    def __init__(self, title: str, data: Optional[Dict[str, Any]], message: str = ""):
        import shapely

        self.title = title
        self.message = message
        self.nodes: List[Tuple[str, Tuple[float, float], bool]] = []  # label, position, is new
        self.edges: List[Tuple[str, Any]] = []  # label, line
        self.matches: List[Dict[str, Any]] = []
        self.matcher = ""
        data = data or {}
        for kind in ("nodes", "points"):
            for position, row in enumerate(data.get(kind, [])):
                point = shapely.from_wkt(row["geometry"])
                label = str(row["id"]) if "id" in row else str(position)
                self.nodes.append((label, (point.x, point.y), False))
        for kind in ("edges", "lines"):
            for position, row in enumerate(data.get(kind, [])):
                geometry = shapely.from_wkt(row["geometry"]) if row["geometry"] else None
                if geometry is None or geometry.is_empty:
                    continue
                geometry = shapely.force_2d(geometry)
                label = str(row["id"]) if isinstance(row.get("id"), int) else str(position)
                for part in shapely.get_parts(geometry):
                    self.edges.append((label, part))
        if not self.nodes and not self.edges and not message:
            self.message = "nothing"

    def mark_new(self, known: Sequence[str]) -> None:
        self.nodes = [(label, xy, label not in known) for label, xy, _ in self.nodes]

    def extent(self) -> List[Tuple[float, float]]:
        points = [xy for _, xy, _ in self.nodes]
        for _, line in self.edges:
            points += [tuple(xy) for xy in line.coords]
        return points


def panels_of(case: Dict[str, Any]) -> List[Panel]:
    operation, data, expected = case["operation"], case["input"], case["expected"]
    if operation in run.MATCHERS:
        panel = Panel("input, with matches marked", data)
        panel.matches, panel.matcher = expected["matches"], operation
        return [panel]
    if "networks" in data:
        panels = [Panel(f"input: {name}", data["networks"][name]) for name in sorted(data["networks"])]
    elif operation in run.CREATION:
        kinds = " and ".join(kind for kind in ("points", "nodes", "lines", "edges") if kind in data)
        panels = [Panel(f"input: {kinds}", data)]
    else:
        panels = [Panel("input", data)]
    if expected.get("error"):
        panels.append(Panel("expected", None, "refused: an error"))
    else:
        result = Panel("expected", expected)
        if operation not in run.CREATION and "networks" not in data:
            result.mark_new([label for label, _, _ in panels[0].nodes])
        panels.append(result)
    return panels


def _along(points: List[Tuple[float, float]], fraction: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """The place a fraction of the way along a line, and the direction of the line there"""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    target = fraction * sum(lengths)
    for (a, b), length in zip(zip(points, points[1:]), lengths):
        if length > 0 and target <= length:
            t = target / length
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
        target -= length
    a, b = points[-2], points[-1]
    length = math.dist(a, b) or 1.0
    return b, ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def _samples(points: List[Tuple[float, float]], step: float) -> List[Tuple[float, float]]:
    total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    count = max(2, int(total / step) + 1)
    return [_along(points, index / (count - 1))[0] for index in range(count)]


def _clearance(point: Tuple[float, float], obstacles: List[Tuple[float, float]]) -> float:
    return min((math.dist(point, other) for other in obstacles), default=1e9)


def _step(scale: float) -> float:
    """Spacing of grid lines, in data units, that keeps them at least 26 points apart"""
    for step in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100):
        if step * scale >= 26:
            return step
    return 100.0


def draw_panel(ax: Any, panel: Panel, scale: float) -> None:
    """Draw a panel. ``scale`` is points per data unit."""
    import shapely
    from matplotlib import patheffects
    from matplotlib.patches import FancyArrowPatch
    from matplotlib.ticker import MultipleLocator
    from shapely.ops import substring

    halo = [patheffects.withStroke(linewidth=2.2, foreground=SURFACE)]
    ax.set_title(panel.title, loc="left", fontsize=8.5, color=INK_SECONDARY, pad=5)
    for side in ax.spines.values():
        side.set_visible(False)
    step = _step(scale)
    ax.xaxis.set_major_locator(MultipleLocator(step))
    ax.yaxis.set_major_locator(MultipleLocator(step))
    ax.tick_params(length=0, labelsize=6, labelcolor=INK_MUTED, pad=2)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    if panel.message:
        ax.text(0.5, 0.5, panel.message, transform=ax.transAxes, ha="center", va="center", fontsize=9, color=INK_SECONDARY)
        if not panel.nodes and not panel.edges:
            ax.tick_params(labelbottom=False, labelleft=False)
            ax.grid(False)
            return

    def to_points(xy: Tuple[float, float]) -> Tuple[float, float]:
        return (xy[0] * scale, xy[1] * scale)

    # everything a label should keep clear of, in points
    obstacles: List[Tuple[float, float]] = [to_points(xy) for _, xy, _ in panel.nodes]
    lines = [[to_points(tuple(xy)) for xy in line.coords] for _, line in panel.edges]
    for line in lines:
        obstacles += _samples(line, 5.0)

    # edges
    drawn: List[Any] = []
    for index, ((label, geometry), line) in enumerate(zip(panel.edges, lines)):
        colour = EDGE_COLOURS[index % len(EDGE_COLOURS)]
        overlaps = any(geometry.intersection(other).length > 0 for other in drawn)
        drawn.append(geometry)
        xs, ys = zip(*geometry.coords)
        ax.plot(
            xs,
            ys,
            color=colour,
            linewidth=2,
            linestyle=(0, (3, 2.5)) if overlaps else "-",
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2 + index * 0.01,
        )
        # an arrow in the middle of the segment that holds the half-way point
        middle, _ = _along(line, 0.5)
        segments = list(zip(line, line[1:]))
        lengths = [math.dist(a, b) for a, b in segments]
        best = max(range(len(segments)), key=lambda k: (lengths[k] > 0) - _point_segment(middle, *segments[k]) / 1e6)
        a, b = segments[best]
        t = 0.75 if overlaps else 0.35
        at = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        unit = ((b[0] - a[0]) / (lengths[best] or 1), (b[1] - a[1]) / (lengths[best] or 1))
        reach = min(5.5, lengths[best] / 2)
        ax.add_patch(
            FancyArrowPatch(
                ((at[0] - unit[0] * reach) / scale, (at[1] - unit[1] * reach) / scale),
                ((at[0] + unit[0] * reach) / scale, (at[1] + unit[1] * reach) / scale),
                arrowstyle="-|>",
                mutation_scale=15,
                linewidth=0,
                color=colour,
                shrinkA=0,
                shrinkB=0,
                zorder=3,
            )
        )

    # marks of matches, under the nodes
    positions = {label: xy for label, xy, _ in panel.nodes}
    edges = dict(panel.edges)
    for match in panel.matches:
        if panel.matcher == "match_nodes":
            a, b = positions[str(match["node_a"])], positions[str(match["node_b"])]
            ax.plot(*zip(a, b), color=INK, linewidth=1, linestyle=(0, (1, 2)), zorder=4)
            ax.plot(*zip(a, b), linestyle="none", marker="o", markersize=10, markerfacecolor="none", markeredgecolor=INK, markeredgewidth=1, zorder=4)
        elif panel.matcher == "match_nodes_to_edges":
            a, b = positions[str(match["node"])], (match["x"], match["y"])
            ax.plot(*zip(a, b), color=INK, linewidth=1, linestyle=(0, (1, 2)), zorder=4)
            ax.plot([b[0]], [b[1]], marker="x", markersize=6, color=INK, markeredgewidth=1.4, zorder=6)
            obstacles.append(to_points(b))
        elif panel.matcher == "find_crossings":
            ax.plot([match["x"]], [match["y"]], marker="o", markersize=9, markerfacecolor="none", markeredgecolor=INK, markeredgewidth=1.3, zorder=6)
            obstacles.append(to_points((match["x"], match["y"])))
        elif panel.matcher == "match_edges":
            for side in "ab":
                line = edges[str(match[f"edge_{side}"])]
                stretch = substring(line, match[f"start_{side}"], match[f"end_{side}"])
                ax.plot(*zip(*stretch.coords), color=INK, alpha=0.22, linewidth=9, solid_capstyle="butt", zorder=1)

    # nodes, and their labels where there is most room
    for label, xy, new in panel.nodes:
        ax.plot(
            [xy[0]],
            [xy[1]],
            marker="o",
            markersize=6.5 if new else 6,
            markerfacecolor=SURFACE if new else INK,
            markeredgecolor=INK if new else SURFACE,
            markeredgewidth=1.3 if new else 1,
            zorder=5,
        )
    placed: List[Tuple[float, float]] = []
    for label, xy, _ in panel.nodes:
        here = to_points(xy)
        others = [point for point in obstacles if math.dist(point, here) > 0.5] + placed
        choices = []
        for angle in (45, 135, 315, 225, 90, 270, 0, 180):
            reach = 9.5 + 1.5 * len(label) * abs(math.cos(math.radians(angle)))
            choices.append((here[0] + reach * math.cos(math.radians(angle)), here[1] + reach * math.sin(math.radians(angle))))
        best_choice = max(choices, key=lambda point: min(_clearance(point, others), 14.0))
        placed.append(best_choice)
        ax.annotate(
            label,
            xy,
            xytext=(best_choice[0] - here[0], best_choice[1] - here[1]),
            textcoords="offset points",
            ha="center",
            va="center",
            fontsize=FONT,
            color=INK,
            path_effects=halo,
            zorder=7,
        )

    # edge labels: beside the line, where there is most room
    for index, ((label, _), line) in enumerate(zip(panel.edges, lines)):
        colour = EDGE_COLOURS[index % len(EDGE_COLOURS)]
        choices = []
        for fraction in (0.5, 0.35, 0.65, 0.22, 0.78):
            at, unit = _along(line, fraction)
            for side in (1, -1):
                choices.append((at[0] - side * unit[1] * 10, at[1] + side * unit[0] * 10))
        best_choice = max(choices, key=lambda point: min(_clearance(point, obstacles + placed), 13.0))
        placed.append(best_choice)
        ax.text(
            best_choice[0] / scale,
            best_choice[1] / scale,
            label,
            ha="center",
            va="center",
            fontsize=FONT,
            color=INK,
            bbox={"boxstyle": "round,pad=0.22", "facecolor": SURFACE, "edgecolor": colour, "linewidth": 1.1},
            zorder=8,
        )


def _point_segment(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def draw(case: Dict[str, Any], path: Path) -> None:
    """Write the figure of one case"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = panels_of(case)
    points = [xy for panel in panels for xy in panel.extent()] or [(0.0, 0.0)]
    xs, ys = [xy[0] for xy in points], [xy[1] for xy in points]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    centre = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)

    # every panel has the same size and shows the same part of the plane
    width = WIDTH / len(panels) - LEFT - RIGHT
    scale = min((width - 2 * MARGIN) / dx if dx else 1e9, (MAX_HEIGHT - 2 * MARGIN) / dy if dy else 1e9)
    scale = min(scale, 150.0)
    height = max(MIN_HEIGHT, min(MAX_HEIGHT, dy * scale + 2 * MARGIN))
    text = textwrap.wrap(caption(case), 112, subsequent_indent="    ")
    below = CAPTION + 9.0 * (len(text) - 1)
    total = TOP + height + BOTTOM + below

    with plt.rc_context(
        {
            "svg.hashsalt": "snkit",
            "svg.fonttype": "none",
            "font.family": "sans-serif",
            "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        }
    ):
        figure = plt.figure(figsize=(WIDTH / 72, total / 72), facecolor=SURFACE)
        for index, panel in enumerate(panels):
            left = index * WIDTH / len(panels) + LEFT
            ax = figure.add_axes((left / WIDTH, (below + BOTTOM) / total, width / WIDTH, height / total))
            ax.set_xlim(centre[0] - width / scale / 2, centre[0] + width / scale / 2)
            ax.set_ylim(centre[1] - height / scale / 2, centre[1] + height / scale / 2)
            draw_panel(ax, panel, scale)
        figure.text(
            LEFT / WIDTH,
            (below - 10.0) / total,
            "\n".join(text),
            fontsize=7.5,
            family="monospace",
            color=INK_SECONDARY,
            va="top",
            linespacing=1.3,
        )
        kind = path.suffix[1:]
        metadata = {"Date": None, "Creator": None} if kind == "svg" else None
        figure.savefig(path, format=kind, metadata=metadata, facecolor=SURFACE, dpi=140)
        plt.close(figure)


def main() -> None:
    cases = ordered_cases()
    IMAGES.mkdir(parents=True, exist_ok=True)
    wanted = set(image_names(cases))
    for path in IMAGES.glob("*.svg"):
        if path.name not in wanted:
            path.unlink()
    for name, case in cases.items():
        draw(case, IMAGES / image_name(name))
    PAGE.write_text(render_page(cases), encoding="utf-8")
    print(f"drew {len(cases)} figures and wrote {PAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
