import unittest

import numpy as np
import pandas as pd

import app
from trend_analysis import TrendSelection, build_trend_results
from trend_plots import pressure_figure, production_figure


class DailyProductionTests(unittest.TestCase):
    def production(self, rates, dates=None, factor=1.0):
        dates = pd.to_datetime(dates) if dates is not None else pd.date_range("2024-01-01", periods=len(rates))
        return app.prepare_daily_production(
            pd.DataFrame({"well_id": "A", "date": dates, "rate": rates}), factor
        )

    def test_daily_volume_acceptance_cases(self):
        for rates, expected in [
            ([100, 100], [100, 200]),
            ([100, 100, 150], [100, 200, 350]),
            ([100, 0, 100], [100, 100, 200]),
        ]:
            with self.subTest(rates=rates):
                self.assertEqual(self.production(rates)["cum_bbl"].tolist(), expected)

    def test_missing_dates_are_zero_without_interpolation(self):
        daily = self.production([150, 100], ["2024-01-03", "2024-01-01"])
        self.assertEqual(daily["date"].tolist(), list(pd.date_range("2024-01-01", periods=3)))
        self.assertEqual(daily["rate_bpd"].tolist(), [100, 0, 150])
        self.assertEqual(daily["cum_bbl"].tolist(), [100, 100, 250])

    def test_unit_conversion_and_independent_wells(self):
        raw = pd.DataFrame({
            "well_id": ["A", "B", "A", "B"],
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02"]),
            "rate": [0.1, 0.2, 0.15, 0.0],
        })
        daily = app.prepare_daily_production(raw, 1000.0)
        self.assertEqual(daily[daily["well_id"] == "A"]["cum_bbl"].tolist(), [100, 250])
        self.assertEqual(daily[daily["well_id"] == "B"]["cum_bbl"].tolist(), [200, 200])

    def test_pressure_and_manual_lookup_include_date_and_use_latest_prior_day(self):
        daily = self.production([100, 150], ["2024-01-01", "2024-01-03"])
        dates = pd.date_range("2023-12-31", periods=5)
        pressure = pd.DataFrame({"well_id": "A", "date": dates, "pressure_psi": 3000})
        aligned = app.align_pressure_with_production(pressure, daily)
        np.testing.assert_allclose(aligned["cum_bbl"], [np.nan, 100, 100, 250, 250], equal_nan=True)
        for date, expected in zip(dates, aligned["cum_bbl"]):
            with self.subTest(date=date):
                actual = app.production_snapshot(daily, date)["cum_bbl"]
                np.testing.assert_allclose(actual, expected, equal_nan=True)

    def test_plots_and_forecast_share_daily_cumulative_values(self):
        daily = self.production([100, 100, 150])
        pressure = pd.DataFrame({
            "well_id": "A", "date": daily["date"], "pressure_psi": [3000, 2900, 2750],
        })
        aligned = app.align_pressure_with_production(pressure, daily)
        selected = aligned.iloc[[0, 2]]
        results = build_trend_results([TrendSelection("Trend 1", selected, "#2563eb")], aligned, 2500)
        self.assertEqual(results[0].metrics["delta_cum_bbl"], 250)
        self.assertEqual(results[0].forecast["last_cum_bbl"], 350)
        self.assertEqual(results[0].forecast["cumulative_at_saturation_bbl"], 600)
        self.assertEqual(list(production_figure(daily, results).data[1].y), [100, 200, 350])
        figure = pressure_figure(aligned, results, 2500, cumulative=True)
        self.assertEqual(list(figure.data[0].x), [100, 200, 350])
        self.assertEqual(list(figure.data[1].x), [100, 350])
        self.assertEqual(list(figure.data[2].x), [350, 600])


if __name__ == "__main__":
    unittest.main()
