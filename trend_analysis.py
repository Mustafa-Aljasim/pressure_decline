"""Shared trend calculations and presentation tables; no production integration."""
from dataclasses import dataclass
from typing import Any
import io

import numpy as np
import pandas as pd


COLORS = ["#2563eb", "#d97706", "#7c3aed"]
NO_FORECAST = "No valid declining extrapolation to Psat"
DISCLAIMER = "Forecasts are extrapolations of user-selected historical pressure decline trends and are not a dynamic reservoir simulation or probabilistic uncertainty model."
CUMULATIVE_NOTE = "Cumulative production is calculated by summing the actual daily production volumes. Each uploaded daily rate is treated as the average rate for that calendar day, so daily volume = rate × 1 day. No averaging or trapezoidal integration between consecutive rate points is applied."


@dataclass
class TrendSelection:
    name: str
    points: pd.DataFrame
    color: str
    enabled: bool = True
    mode: str = "Uploaded pressure points"


@dataclass
class TrendResult:
    selection: TrendSelection
    metrics: dict[str, Any]
    forecast: dict[str, Any]
    issues: list[str]


def safe_date(reference, days):
    try:
        if np.isfinite(days) and days >= 0:
            return pd.Timestamp(reference) + pd.to_timedelta(days, unit="D")
    except (OverflowError, ValueError, pd.errors.OutOfBoundsDatetime):
        pass
    return None


def calculate_trend(selection, history, psat, reference="Latest measured pressure"):
    points = selection.points.sort_values("date").reset_index(drop=True)
    issues = []
    if len(points) != 2:
        raise ValueError("Each trend requires two points.")
    start, end = points.iloc[0], points.iloc[1]
    if selection.points.iloc[0]["date"] > selection.points.iloc[1]["date"]:
        issues.append("Start/end points reordered chronologically.")
    days = (end["date"] - start["date"]).total_seconds() / 86400.0
    drop = float(start["pressure_psi"] - end["pressure_psi"])
    volume = float(end["cum_bbl"] - start["cum_bbl"])
    time_slope = drop / days if days > 0 and np.isfinite(drop) else np.nan
    cum_slope = drop / volume if volume > 0 and days > 0 and np.isfinite(drop) else np.nan
    rate = volume / days if days > 0 and np.isfinite(volume) else np.nan
    cumulative_decline_day = cum_slope * rate if np.isfinite(cum_slope) and np.isfinite(rate) else np.nan
    if days <= 0:
        issues.append("Choose points on different dates; elapsed time is zero.")
    if not np.isfinite(drop):
        issues.append("Selected pressure values are missing or invalid.")
    elif drop <= 0:
        issues.append("Pressure is flat or increasing over the selected interval.")
    if not np.isfinite(volume) or volume <= 0:
        issues.append("Cumulative production must increase for a cumulative forecast.")
    m = {
        "start_date": start["date"], "end_date": end["date"],
        "start_pressure_psi": float(start["pressure_psi"]), "end_pressure_psi": float(end["pressure_psi"]),
        "start_cum_bbl": float(start["cum_bbl"]), "end_cum_bbl": float(end["cum_bbl"]),
        "delta_days": days, "pressure_drop": drop, "delta_cum_bbl": volume,
        "time_decline_day": time_slope, "time_decline_month": time_slope * 30,
        "time_decline_year": time_slope * 365,
        "decline_psi_bbl": cum_slope, "decline_per_1000_bbl": cum_slope * 1000,
        "cumulative_decline_day": cumulative_decline_day,
        "cumulative_decline_month": cumulative_decline_day * 30 if np.isfinite(cumulative_decline_day) else np.nan,
        "interval_avg_rate_bpd": rate,
    }
    valid_history = history[np.isfinite(history["pressure_psi"])].sort_values("date")
    anchor = end if reference == "Selected interval end" else (valid_history.iloc[-1] if not valid_history.empty else end)
    pressure, cumulative = float(anchor["pressure_psi"]), float(anchor["cum_bbl"])
    gap = pressure - psat
    f = {
        "reference": reference, "last_date": anchor["date"], "last_pressure_psi": pressure,
        "last_cum_bbl": cumulative, "saturation_pressure": psat,
        "time_days": np.nan, "time_months": np.nan, "time_date": None, "time_status": NO_FORECAST,
        "incremental_oil_bbl": np.nan, "cumulative_at_saturation_bbl": np.nan,
        "cum_days": np.nan, "months_left": np.nan, "forecast_date": None, "cum_status": NO_FORECAST,
        "selected_interval_growth_bpd": rate,
    }
    if np.isfinite(gap) and gap <= 0:
        f.update(time_days=0.0, time_months=0.0, time_date=anchor["date"], time_status="Psat already reached")
        if np.isfinite(cumulative):
            f.update(incremental_oil_bbl=0.0, cumulative_at_saturation_bbl=cumulative,
                     cum_days=0.0, months_left=0.0, forecast_date=anchor["date"], cum_status="Psat already reached")
    elif np.isfinite(gap):
        if np.isfinite(time_slope) and time_slope > 0:
            time_days = gap / time_slope
            date = safe_date(anchor["date"], time_days)
            f.update(time_days=time_days, time_months=time_days / 30, time_date=date,
                     time_status="Valid" if date is not None else "Forecast exceeds supported date range")
        if np.isfinite(cum_slope) and cum_slope > 0 and np.isfinite(cumulative):
            oil = gap / cum_slope
            f.update(incremental_oil_bbl=oil, cumulative_at_saturation_bbl=cumulative + oil)
            if np.isfinite(rate) and rate > 0:
                cum_days = oil / rate
                date = safe_date(anchor["date"], cum_days)
                f.update(cum_days=cum_days, months_left=cum_days / 30, forecast_date=date,
                         cum_status="Valid" if date is not None else "Forecast exceeds supported date range")
    return TrendResult(selection, m, f, issues)


def build_trend_results(selections, history, psat, reference="Latest measured pressure"):
    return [calculate_trend(s, history, psat, reference) for s in selections if s.enabled]


def date_text(value):
    return pd.Timestamp(value).strftime("%Y-%m-%d") if value is not None and pd.notna(value) else "N/A"


def result_tables(results):
    time, cumulative, forecast = [], [], []
    for r in results:
        m, f, name = r.metrics, r.forecast, r.selection.name
        time.append({"Trend": name, "Start date": date_text(m["start_date"]), "End date": date_text(m["end_date"]),
                     "P start, psi": m["start_pressure_psi"], "P end, psi": m["end_pressure_psi"],
                     "Pressure drop, psi": m["pressure_drop"], "Elapsed days": m["delta_days"],
                     "psi/day": m["time_decline_day"], "psi/month": m["time_decline_month"], "psi/year": m["time_decline_year"]})
        cumulative.append({"Trend": name, "Start cum, bbl": m["start_cum_bbl"], "End cum, bbl": m["end_cum_bbl"],
                           "Delta cum, bbl": m["delta_cum_bbl"], "Pressure drop, psi": m["pressure_drop"],
                           "psi/1,000 bbl": m["decline_per_1000_bbl"],
                           "Cum decline, psi/day": m["cumulative_decline_day"],
                           "Cum decline, psi/month": m["cumulative_decline_month"],
                           "Avg rate, bbl/day": m["interval_avg_rate_bpd"]})
        forecast.append({"Trend": name, "Reference date": date_text(f["last_date"]),
                         "Time decline, psi/day": m["time_decline_day"], "Cum decline, psi/1,000 bbl": m["decline_per_1000_bbl"],
                         "Cum at Psat, bbl": f["cumulative_at_saturation_bbl"], "Incremental oil, bbl": f["incremental_oil_bbl"],
                         "Time months": f["time_months"], "Time Psat date": date_text(f["time_date"]),
                         "Cum months": f["months_left"], "Cum Psat date": date_text(f["forecast_date"]),
                         "Time status": f["time_status"], "Cum status": f["cum_status"]})
    return {"Pressure Decline vs Time": pd.DataFrame(time),
            "Pressure Decline vs Cumulative Production": pd.DataFrame(cumulative),
            "Forecast to Saturation Pressure": pd.DataFrame(forecast)}


def build_results_csv(results):
    rows = []
    for result in results:
        for section, values in [("Interval", result.metrics), ("Forecast", result.forecast)]:
            for metric, value in values.items():
                rows.append({"trend": result.selection.name, "section": section, "metric": metric, "value": value})
        rows.append({"trend": result.selection.name, "section": "Selection", "metric": "mode", "value": result.selection.mode})
        rows.append({"trend": result.selection.name, "section": "Validation", "metric": "issues", "value": "; ".join(result.issues)})
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def build_plot_workbook(history, daily, results, psat):
    """Export the exact historical and forecast coordinates used by both plots."""
    time_rows = []
    cumulative_rows = []
    history = history.sort_values("date")
    for row in history.itertuples():
        base = {"source": "Pressure history", "trend": "", "date": row.date,
                "pressure_psi": row.pressure_psi, "cumulative_bbl": row.cum_bbl,
                "point_id": getattr(row, "_point_id", getattr(row, "point_id", ""))}
        time_rows.append(base)
        cumulative_rows.append(base.copy())
    for result in results:
        f = result.forecast
        end = f.get("time_date")
        if end is not None:
            time_rows.append({"source": "Forecast to Psat", "trend": result.selection.name,
                              "date": end, "pressure_psi": psat, "cumulative_bbl": np.nan,
                              "point_id": ""})
        cum_end = f.get("cumulative_at_saturation_bbl")
        if pd.notna(cum_end):
            cumulative_rows.append({"source": "Forecast to Psat", "trend": result.selection.name,
                                    "date": f["forecast_date"], "pressure_psi": psat,
                                    "cumulative_bbl": cum_end, "point_id": ""})
        for point in result.selection.points.sort_values("date").itertuples():
            time_rows.append({"source": "Selected interval", "trend": result.selection.name,
                              "date": point.date, "pressure_psi": point.pressure_psi,
                              "cumulative_bbl": point.cum_bbl, "point_id": getattr(point, "_point_id", getattr(point, "point_id", ""))})
            cumulative_rows.append({"source": "Selected interval", "trend": result.selection.name,
                                    "date": point.date, "pressure_psi": point.pressure_psi,
                                    "cumulative_bbl": point.cum_bbl, "point_id": getattr(point, "_point_id", getattr(point, "point_id", ""))})
    tables = result_tables(results)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        time_frame = pd.DataFrame(time_rows, columns=["source", "trend", "date", "pressure_psi", "cumulative_bbl", "point_id"])
        cumulative_frame = pd.DataFrame(cumulative_rows, columns=["source", "trend", "date", "pressure_psi", "cumulative_bbl", "point_id"])
        time_frame.sort_values(["date", "source", "trend"]).to_excel(writer, sheet_name="Pressure vs Time", index=False)
        cumulative_frame.sort_values(["cumulative_bbl", "source", "trend"]).to_excel(writer, sheet_name="Pressure vs Cumulative", index=False)
        daily.sort_values("date").to_excel(writer, sheet_name="Production History", index=False)
        summary_sheets = [tables["Pressure Decline vs Time"], tables["Pressure Decline vs Cumulative Production"], tables["Forecast to Saturation Pressure"]]
        summary_sheets = [frame if len(frame.columns) else pd.DataFrame({"Status": ["No enabled trend selection"]}) for frame in summary_sheets]
        summary_sheets[0].to_excel(writer, sheet_name="Trend Summary", index=False, startrow=0)
        summary_sheets[1].to_excel(writer, sheet_name="Trend Summary", index=False, startrow=len(summary_sheets[0]) + 3)
        summary_sheets[2].to_excel(writer, sheet_name="Trend Summary", index=False, startrow=len(summary_sheets[0]) + len(summary_sheets[1]) + 6)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for column in sheet.columns:
                width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 10), 28)
                sheet.column_dimensions[column[0].column_letter].width = width
    buffer.seek(0)
    return buffer.getvalue()
