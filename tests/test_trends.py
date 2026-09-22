import io
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from trend_analysis import COLORS, NO_FORECAST, TrendSelection, build_trend_results, build_results_csv, result_tables, build_plot_workbook


class TrendTests(unittest.TestCase):
    def setUp(self):
        self.history = pd.DataFrame(dict(
            date=pd.to_datetime(["2024-01-01", "2024-01-11", "2024-01-21"]),
            pressure_psi=[3000.0, 2900.0, 2700.0], cum_bbl=[100.0, 1100.0, 3100.0],
            rate_bpd=[100.0, 100.0, 200.0], point_id=[0, 1, 2],
        ))

    def selection(self, indices=(0, 1), name="Trend 1", enabled=True):
        return TrendSelection(name, self.history.iloc[list(indices)], COLORS[0], enabled)

    def test_independent_overlapping_trends_and_units(self):
        results = build_trend_results([self.selection(), self.selection((0, 2), "Trend 2"),
                                       self.selection((1, 2), "Trend 3", False)], self.history, 2500)
        self.assertEqual(len(results), 2)
        first, second = results
        self.assertEqual(first.metrics["time_decline_day"], 10)
        self.assertEqual(first.metrics["time_decline_month"], 300)
        self.assertEqual(first.metrics["time_decline_year"], 3650)
        self.assertEqual(first.metrics["decline_per_1000_bbl"], 100)
        self.assertEqual(first.metrics["cumulative_decline_day"], 10)
        self.assertEqual(first.metrics["cumulative_decline_month"], 300)
        self.assertEqual(first.forecast["cumulative_at_saturation_bbl"], 5100)
        self.assertEqual(first.forecast["forecast_date"], pd.Timestamp("2024-02-10"))
        self.assertNotEqual(first.forecast["forecast_date"], second.forecast["forecast_date"])
        self.assertEqual(first.forecast["time_date"], first.forecast["forecast_date"])
        csv = pd.read_csv(io.BytesIO(build_results_csv(results)))
        self.assertEqual(set(csv.trend), {"Trend 1", "Trend 2"})
        for table in result_tables(results).values():
            self.assertEqual(table["Trend"].tolist(), ["Trend 1", "Trend 2"])
        cumulative = result_tables(results)["Pressure Decline vs Cumulative Production"]
        self.assertNotIn("psi/10,000 bbl", cumulative.columns)
        self.assertNotIn("psi/100,000 bbl", cumulative.columns)

    def test_plot_data_excel_contains_history_selected_points_and_forecasts(self):
        results = build_trend_results([self.selection(), self.selection((0, 2), "Trend 2")], self.history, 2500)
        workbook = build_plot_workbook(self.history, self.history.rename(columns={"date": "date", "cum_bbl": "cum_bbl"}), results, 2500)
        import io
        sheets = pd.ExcelFile(io.BytesIO(workbook)).sheet_names
        self.assertEqual(sheets, ["Pressure vs Time", "Pressure vs Cumulative", "Production History", "Trend Summary"])
        time = pd.read_excel(io.BytesIO(workbook), sheet_name="Pressure vs Time")
        cumulative = pd.read_excel(io.BytesIO(workbook), sheet_name="Pressure vs Cumulative")
        self.assertTrue((time["source"] == "Pressure history").any())
        self.assertTrue((time["source"] == "Forecast to Psat").any())
        self.assertEqual(set(time.loc[time["source"] == "Forecast to Psat", "trend"]), {"Trend 1", "Trend 2"})
        self.assertEqual(set(cumulative.loc[cumulative["source"] == "Forecast to Psat", "trend"]), {"Trend 1", "Trend 2"})

    def test_reference_and_reversed_points(self):
        result = build_trend_results([self.selection((1, 0))], self.history, 2500, "Selected interval end")[0]
        self.assertEqual(result.metrics["delta_days"], 10)
        self.assertEqual(result.forecast["last_date"], pd.Timestamp("2024-01-11"))
        self.assertEqual(result.forecast["forecast_date"], pd.Timestamp("2024-02-20"))
        self.assertTrue(result.issues)

    def test_invalid_slopes_and_missing_values(self):
        for field, values in [("pressure_psi", [2900, 3000, 3100]),
                              ("pressure_psi", [3000, 3000, 3000]),
                              ("pressure_psi", [np.nan, 3000, 3000]),
                              ("cum_bbl", [100, 100, 100]),
                              ("cum_bbl", [np.nan, 100, 100])]:
            with self.subTest(field=field, values=values):
                history = self.history.copy()
                history[field] = values
                result = build_trend_results([TrendSelection("Trend 1", history.iloc[:2], COLORS[0])], history, 2500)[0]
                self.assertEqual(result.forecast["cum_status"], NO_FORECAST)
                self.assertIsNone(result.forecast["forecast_date"])
        result = build_trend_results([self.selection((0, 0))], self.history, 2500)[0]
        self.assertIsNone(result.forecast["time_date"])
        self.assertIsNone(result.forecast["forecast_date"])

    def test_already_reached_and_unrepresentable_date(self):
        reached = build_trend_results([self.selection()], self.history, 2800)[0]
        self.assertEqual(reached.forecast["cum_status"], "Psat already reached")
        self.assertEqual(reached.forecast["incremental_oil_bbl"], 0)
        self.assertEqual(reached.forecast["forecast_date"], self.history.iloc[-1].date)
        self.history.loc[1, "pressure_psi"] = 3000 - 1e-9
        far = build_trend_results([self.selection()], self.history, 2500)[0]
        self.assertIsNone(far.forecast["forecast_date"])

    def test_streamlit_demo_multiple_manual_and_disabled_trends(self):
        at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
        at.toggle[0].set_value(True).run()
        self.assertFalse(at.exception)
        at.checkbox[0].check().run()
        at.checkbox[1].check().run()
        self.assertEqual(len(at.radio), 3)
        self.assertFalse(at.exception)
        for radio in list(at.radio):
            radio.set_value("Manual entry")
        at.run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.date_input), 6)
        at.checkbox[0].uncheck().run()
        self.assertEqual(len(at.radio), 2)
        self.assertFalse(at.exception)
        next(button for button in at.button if button.label == "Prepare Professional PDF Report").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(any(button.label == "Download Professional PDF Report" for button in at.get("download_button")))
        self.assertTrue(any(button.label == "Download pressure plots data (Excel)" for button in at.get("download_button")))



if __name__ == "__main__":
    unittest.main()
