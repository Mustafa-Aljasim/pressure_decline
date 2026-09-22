import json
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd
from streamlit.elements.plotly_chart import PlotlyChartSelectionSerde

import app
from pressure_selection import ensure_pressure_ids, extract_point_id, update_trend_selection
from trend_plots import pressure_figure


class PressureSelectionTests(unittest.TestCase):
    def test_observed_streamlit_payload_and_supported_customdata_shapes(self):
        # Captured from an actual box event in Streamlit 1.62.0 / Plotly 7.0.0.
        event = PlotlyChartSelectionSerde().deserialize(json.dumps({"selection": {
            "points": [{"curve_number": 0, "point_number": 1, "customdata": {"0": 1}}],
            "box": [], "lasso": [], "point_indices": [1],
        }}))
        self.assertEqual(extract_point_id(event.selection.points[0]), "1")
        for custom in [{"_point_id": "obs-1"}, {"point_id": "obs-1"}, {"row_id": "obs-1"},
                       {"id": "obs-1"}, {"0": "obs-1"}, ["obs-1"], ("obs-1",),
                       np.array(["obs-1"]), np.array("obs-1"), "obs-1", SimpleNamespace(_point_id="obs-1")]:
            with self.subTest(custom=repr(custom)):
                self.assertEqual(extract_point_id(SimpleNamespace(customdata=custom)), "obs-1")
        for custom in [None, [], {}, {"unexpected": 2}, np.array([]), True, 1.5, np.nan, np.inf]:
            with self.subTest(malformed=repr(custom)):
                self.assertIsNone(extract_point_id({"customdata": custom}))

    def test_selection_isolation_subsets_single_clicks_clear_and_invalid_traces(self):
        ids = ("z", "a", "m", "q")  # Chronological order is not lexical/ID order.
        state = {"trend1_selected_ids": ["z", "q"], "trend1_start": "z", "trend1_end": "q"}
        def event(points, geometry=None):
            return SimpleNamespace(selection=SimpleNamespace(points=points, box=[{}] if geometry == "box" else [], lasso=[{}] if geometry == "lasso" else []))
        def point(pid, curve=0):
            return {"curve_number": curve, "customdata": {"_point_id": pid}}
        for geometry in ("box", "lasso"):
            update_trend_selection(state, event([point("q"), point("a"), point("m"), point("z", 1),
                                                 point("unknown"), {"curve_number": 0, "customdata": {}},
                                                 {"curve_number": 0, "point_number": 0}], geometry), "trend2", ids)
            self.assertEqual(state["trend2_selected_ids"], ["a", "m", "q"])
            self.assertEqual((state["trend2_start"], state["trend2_end"]), ("a", "q"))
        update_trend_selection(state, event([point("a")]), "trend3", ids)
        update_trend_selection(state, event([point("m")]), "trend3", ids)
        self.assertEqual(state["trend3_selected_ids"], ["a", "m"])
        saved = state.copy()
        for payload in [event([point("a", 2)]), event([{"customdata": {"_point_id": "z"}}]), {}, None]:
            update_trend_selection(state, payload, "trend3", ids)
            self.assertEqual(state, saved)
        update_trend_selection(state, event([]), "trend2", ids)
        self.assertEqual(state["trend2_selected_ids"], [])
        self.assertEqual(state["trend1_selected_ids"], ["z", "q"])
        self.assertEqual(state["trend3_selected_ids"], ["a", "m"])

    def test_ids_survive_sort_filter_alignment_and_plot_serialization(self):
        raw = pd.DataFrame({"well_id": ["B", "A", "A", "A"],
                            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-01", "2024-01-01"]),
                            "pressure_psi": [3000, 2900, 3100, 3100],
                            "_point_id": ["existing-B", "existing-A", None, None]})
        identified = ensure_pressure_ids(raw)
        self.assertEqual(identified["_point_id"].nunique(), 4)
        self.assertEqual(identified.iloc[0]["_point_id"], "existing-B")
        subset = identified[identified.well_id == "A"].sort_values("date")
        pd.testing.assert_series_equal(ensure_pressure_ids(subset)["_point_id"], subset["_point_id"])
        daily = app.prepare_daily_production(pd.DataFrame({"well_id": ["A", "A"],
                  "date": pd.to_datetime(["2024-01-01", "2024-01-03"]), "rate": [100, 150]}), 1.0)
        aligned = app.align_pressure_with_production(subset, daily)
        self.assertEqual(aligned["_point_id"].tolist(), subset["_point_id"].tolist())
        figure = pressure_figure(aligned, [], 2500, cumulative=True)
        custom = json.loads(figure.to_json())["data"][0]["customdata"]
        self.assertEqual(custom, [{"_point_id": pid} for pid in aligned["_point_id"]])
        standardized = app.standardize_pressure_frame(raw, {"well_id": "well_id", "date": "date", "pressure_psi": "pressure_psi"})
        self.assertIn("existing-A", standardized["_point_id"].tolist())


if __name__ == "__main__":
    unittest.main()
