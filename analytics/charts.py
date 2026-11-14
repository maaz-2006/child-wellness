"""Server-rendered SVG line charts.

No chart library, for the same reasons the rest of the platform has no
framework: the project constraint is hand-written HTML/CSS/JS with no build
step, a school network may not reach a CDN, and a chart that requires JavaScript
disappears in print - which matters when the same pages go into an appendix.

The geometry lives here, not in the template, so it can be unit-tested. The
template receives coordinates and draws primitives; it performs no arithmetic.

Design details that are deliberate:

* **A gap is a gap.** Missing weeks break the line into separate segments. Joining
  across them would draw a straight line through a period with no data and imply
  measurements that were never taken.
* **0-100 is fixed.** Auto-scaling to the data range makes a two-point wobble look
  like a crisis. A constant axis keeps weeks comparable at a glance.
* **The band is the child's own normal.** `mean +/- 1 SD` of their recent data,
  not a population average, drawn behind the line so the eye can read "outside
  their usual range" without a second chart.
"""

from __future__ import annotations

WIDTH = 680
HEIGHT = 220
PAD_LEFT = 40
PAD_RIGHT = 14
PAD_TOP = 14
PAD_BOTTOM = 30

Y_TICKS = (0, 25, 50, 75, 100)

PLOT_LEFT = PAD_LEFT
PLOT_RIGHT = WIDTH - PAD_RIGHT
PLOT_TOP = PAD_TOP
PLOT_BOTTOM = HEIGHT - PAD_BOTTOM
PLOT_WIDTH = PLOT_RIGHT - PLOT_LEFT
PLOT_HEIGHT = PLOT_BOTTOM - PLOT_TOP


def _round(value: float) -> float:
    return round(value, 1)


def _y(value: float) -> float:
    """Map a 0-100 score to a y coordinate (SVG y grows downwards)."""
    return PLOT_TOP + (1.0 - value / 100.0) * PLOT_HEIGHT


def _x(index: int, count: int) -> float:
    if count <= 1:
        return PLOT_LEFT + PLOT_WIDTH / 2.0
    return PLOT_LEFT + PLOT_WIDTH * index / (count - 1)


def line_chart(
    points: list[dict],
    *,
    chart_id: str,
    title: str,
    description: str = "",
    band: dict | None = None,
) -> dict:
    """Build the drawing instructions for one chart.

    `points` is a list of `{"label": str, "value": float | None}`, oldest first.
    `band` is `{"mean": float, "stddev": float | None}` or None.
    """
    count = len(points)
    values = [point.get("value") for point in points]
    empty = not any(value is not None for value in values)

    y_ticks = [
        {"y": _round(_y(tick)), "label": str(tick)} for tick in Y_TICKS
    ]
    x_ticks = [
        {"x": _round(_x(index, count)), "label": point.get("label", "")}
        for index, point in enumerate(points)
    ]

    # Break the line where a window has no data. Single isolated points are
    # drawn as dots only; a one-point "line" is not a line.
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        value = point.get("value")
        if value is None:
            if len(current) > 1:
                segments.append(current)
            current = []
            continue
        current.append((_round(_x(index, count)), _round(_y(value))))
    if len(current) > 1:
        segments.append(current)

    paths = [
        "M " + " L ".join(f"{x} {y}" for x, y in segment) for segment in segments
    ]

    dots = [
        {
            "cx": _round(_x(index, count)),
            "cy": _round(_y(point["value"])),
            "label": point.get("label", ""),
            "value": _round(point["value"]),
        }
        for index, point in enumerate(points)
        if point.get("value") is not None
    ]

    band_rect = None
    if band and band.get("mean") is not None and band.get("stddev"):
        low = max(0.0, band["mean"] - band["stddev"])
        high = min(100.0, band["mean"] + band["stddev"])
        band_rect = {
            "x": PLOT_LEFT,
            "y": _round(_y(high)),
            "width": PLOT_WIDTH,
            "height": _round(_y(low) - _y(high)),
        }

    if not description:
        latest = next(
            (point for point in reversed(points) if point.get("value") is not None),
            None,
        )
        description = (
            f"Line chart of {title.lower()}, oldest to newest."
            + (f" Latest value {latest['value']:.0f} out of 100." if latest else "")
        )

    return {
        "id": chart_id,
        "title": title,
        "description": description,
        "width": WIDTH,
        "height": HEIGHT,
        "plot_left": PLOT_LEFT,
        "plot_right": PLOT_RIGHT,
        "plot_top": PLOT_TOP,
        "plot_bottom": PLOT_BOTTOM,
        "x_label_y": PLOT_BOTTOM + 19,
        "y_label_x": PLOT_LEFT - 8,
        "y_ticks": y_ticks,
        "x_ticks": x_ticks,
        "segments": paths,
        "dots": dots,
        "band": band_rect,
        "empty": empty,
        "points": points,
    }
