"""Tests for the SVG chart geometry.

The template draws whatever this module returns, so the behaviour that matters
(a gap is not bridged, the axis does not auto-scale, the band is clamped) has to
be asserted here.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from . import charts


def points(*values):
    return [
        {"label": f"W{index + 1}", "value": value}
        for index, value in enumerate(values)
    ]


class LineChartTests(SimpleTestCase):
    def test_grid_is_fixed_to_zero_to_one_hundred(self):
        chart = charts.line_chart(points(72, 74), chart_id="t", title="Test")
        self.assertEqual(
            [tick["label"] for tick in chart["y_ticks"]],
            ["0", "25", "50", "75", "100"],
        )

    def test_a_gap_breaks_the_line(self):
        chart = charts.line_chart(
            points(50, None, 60, 70), chart_id="t", title="Test"
        )

        self.assertFalse(chart["empty"])
        self.assertEqual(len(chart["segments"]), 1)
        self.assertIn("M", chart["segments"][0])

    def test_isolated_points_are_dots_not_segments(self):
        chart = charts.line_chart(
            points(50, None, None, 70), chart_id="t", title="Test"
        )

        self.assertEqual(chart["segments"], [])
        self.assertEqual(len(chart["dots"]), 2)

    def test_no_data_is_empty_and_has_no_geometry(self):
        chart = charts.line_chart(
            points(None, None, None), chart_id="t", title="Test"
        )

        self.assertTrue(chart["empty"])
        self.assertEqual(chart["segments"], [])
        self.assertEqual(chart["dots"], [])

    def test_a_single_point_is_centred(self):
        chart = charts.line_chart(points(80), chart_id="t", title="Test")

        self.assertAlmostEqual(
            chart["dots"][0]["cx"],
            charts.PLOT_LEFT + charts.PLOT_WIDTH / 2,
            places=1,
        )

    def test_higher_scores_are_higher_on_the_chart(self):
        chart = charts.line_chart(points(20, 80), chart_id="t", title="Test")
        low, high = chart["dots"]
        self.assertGreater(low["cy"], high["cy"])

    def test_band_is_clamped_to_the_axis(self):
        chart = charts.line_chart(
            points(50),
            chart_id="t",
            title="Test",
            band={"mean": 95, "stddev": 20},
        )

        self.assertAlmostEqual(chart["band"]["y"], charts.PLOT_TOP, places=1)
        self.assertGreater(chart["band"]["height"], 0)

    def test_zero_stddev_draws_no_band(self):
        chart = charts.line_chart(
            points(50),
            chart_id="t",
            title="Test",
            band={"mean": 100, "stddev": 0.0},
        )
        self.assertIsNone(chart["band"])

    def test_every_point_has_an_x_label(self):
        chart = charts.line_chart(points(10, 20, 30), chart_id="t", title="Test")
        self.assertEqual(len(chart["x_ticks"]), 3)
        self.assertEqual(
            [tick["label"] for tick in chart["x_ticks"]], ["W1", "W2", "W3"]
        )
