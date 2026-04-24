import inspect
import io
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Pressure Decline Calculator", layout="wide")


PRESSURE_WELL_ALIASES = ["well", "well_id", "wellname", "well_name", "wellbore", "wellbore_id"]
PRESSURE_DATE_ALIASES = ["date", "pressure_date", "test_date", "measurement_date", "reading_date"]
PRESSURE_VALUE_ALIASES = [
    "pressure",
    "pressure_psi",
    "bhp",
    "fbhp",
    "datum_pressure",
    "reservoir_pressure",
]
PROD_WELL_ALIASES = ["well", "well_id", "wellname", "well_name", "wellbore", "wellbore_id"]
PROD_DATE_ALIASES = ["date", "prod_date", "production_date", "day"]
PROD_RATE_ALIASES = [
    "rate",
    "prod_rate",
    "production_rate",
    "liquid_rate",
    "total_liquid_rate",
    "oil_rate",
    "qo",
    "q_liq",
]

RATE_UNIT_TO_BBL = {
    "bbl/day": 1.0,
    "kbbl/day (same basis as M.bbl/day in the workbook)": 1000.0,
}

SINGLE_SERIES_WELL = "All data"


@dataclass
class UploadedInputs:
    pressure: pd.DataFrame
    production: pd.DataFrame


def canonicalize_column_name(name: str) -> str:
    return (
        str(name)
        .strip()
        .lower()
        .replace("(", " ")
        .replace(")", " ")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(".", "_")
        .replace(" ", "_")
    )


def find_best_column(columns: list[str], aliases: list[str]) -> Optional[str]:
    canonical = {canonicalize_column_name(col): col for col in columns}
    for alias in aliases:
        if alias in canonical:
            return canonical[alias]

    for alias in aliases:
        for key, raw in canonical.items():
            if alias in key:
                return raw
    return None


@st.cache_data(show_spinner=False)
def build_template_workbook() -> bytes:
    pressure = pd.DataFrame(
        {
            "well_name": ["RU-555"] * 6,
            "date": [
                "2024-10-01",
                "2024-11-15",
                "2025-01-05",
                "2025-02-20",
                "2025-04-01",
                "2025-05-20",
            ],
            "pressure_psi": [3120, 3075, 3010, 2950, 2895, 2840],
        }
    )
    production = pd.DataFrame(
        {
            "well_name": ["RU-555"] * 180,
            "date": pd.date_range("2024-10-01", periods=180, freq="D"),
            "rate": np.clip(2150 - np.linspace(0, 550, 180), 1100, None),
        }
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pressure.to_excel(writer, sheet_name="pressure_data", index=False)
        production.to_excel(writer, sheet_name="production_daily", index=False)
    buffer.seek(0)
    return buffer.read()


@st.cache_data(show_spinner=False)
def build_demo_inputs() -> UploadedInputs:
    rng = np.random.default_rng(7)
    prod_dates = pd.date_range("2024-09-01", "2025-06-30", freq="D")
    rate = np.clip(2350 - np.linspace(0, 700, len(prod_dates)) + rng.normal(0, 35, len(prod_dates)), 1050, None)
    production = pd.DataFrame(
        {
            "well_id": ["RU-555"] * len(prod_dates),
            "date": prod_dates,
            "rate": rate,
        }
    )

    pressure_dates = pd.date_range("2024-09-10", "2025-06-20", freq="18D")
    pressure = pd.DataFrame(
        {
            "well_id": ["RU-555"] * len(pressure_dates),
            "date": pressure_dates,
            "pressure_psi": 3240 - np.linspace(0, 520, len(pressure_dates)) + rng.normal(0, 18, len(pressure_dates)),
        }
    )

    return UploadedInputs(pressure=pressure, production=production)


@st.cache_data(show_spinner=False)
def get_sheet_names(file_name: str, file_bytes: bytes) -> list[str]:
    if file_name.lower().endswith((".xlsx", ".xls")):
        workbook = pd.ExcelFile(io.BytesIO(file_bytes))
        return workbook.sheet_names
    return []


@st.cache_data(show_spinner=False)
def read_uploaded_table(file_name: str, file_bytes: bytes, sheet_name: Optional[str] = None) -> pd.DataFrame:
    if file_name.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    if file_name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)
    return pd.DataFrame()


def mapping_widget(
    df: pd.DataFrame,
    title: str,
    mapping_specs: dict[str, tuple[bool, list[str]]],
    key_prefix: str,
) -> dict[str, str]:
    columns = list(df.columns)
    options = [""] + columns
    st.markdown(f"**{title}**")
    selected: dict[str, str] = {}

    for field_name, (required, aliases) in mapping_specs.items():
        guessed = find_best_column(columns, aliases)
        default_index = options.index(guessed) if guessed in options else 0
        label = field_name.replace("_", " ").title()
        if required:
            label = f"{label} *"
        selected[field_name] = st.selectbox(
            label,
            options=options,
            index=default_index,
            key=f"{key_prefix}_{field_name}",
        )

    return selected


def ensure_well_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "well_id" not in out.columns:
        out["well_id"] = SINGLE_SERIES_WELL
    out["well_id"] = out["well_id"].astype(str).str.strip().replace("", SINGLE_SERIES_WELL)
    return out


def standardize_pressure_frame(raw_df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    required = ["date", "pressure_psi"]
    missing = [field for field in required if not mapping.get(field)]
    if missing:
        st.error("Pressure table: map all required fields before analysis.")
        return pd.DataFrame()

    renamed = {}
    for new_name, old_name in mapping.items():
        if old_name:
            renamed[new_name] = raw_df[old_name]

    out = pd.DataFrame(renamed).copy()
    if out.empty:
        return out

    out = ensure_well_column(out)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["pressure_psi"] = pd.to_numeric(out["pressure_psi"], errors="coerce")
    out = out.dropna(subset=["well_id", "date", "pressure_psi"]).sort_values(["well_id", "date"]).reset_index(drop=True)
    return out


def standardize_production_frame(raw_df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    required = ["date", "rate"]
    missing = [field for field in required if not mapping.get(field)]
    if missing:
        st.error("Production table: map all required fields before analysis.")
        return pd.DataFrame()

    renamed = {}
    for new_name, old_name in mapping.items():
        if old_name:
            renamed[new_name] = raw_df[old_name]

    out = pd.DataFrame(renamed).copy()
    if out.empty:
        return out

    out = ensure_well_column(out)
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["rate"] = pd.to_numeric(out["rate"], errors="coerce")
    out = out.dropna(subset=["well_id", "date", "rate"]).sort_values(["well_id", "date"]).reset_index(drop=True)
    return out


def build_uploader_section() -> UploadedInputs:
    with st.sidebar:
        st.header("Inputs")
        demo_mode = st.toggle("Use demo dataset", value=False)
        st.download_button(
            "Download Excel template",
            data=build_template_workbook(),
            file_name="pressure_decline_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        if demo_mode:
            return build_demo_inputs()

        pressure_file = st.file_uploader("Pressure table", type=["csv", "xlsx", "xls"], key="pressure_file")
        production_file = st.file_uploader("Production daily table", type=["csv", "xlsx", "xls"], key="production_file")

    if pressure_file is None or production_file is None:
        st.info("Upload a pressure table and a daily production table from the sidebar, or turn on the demo dataset.")
        st.stop()

    uploaded = {"Pressure": pressure_file, "Production": production_file}
    raw_tables: dict[str, pd.DataFrame] = {}

    st.subheader("Column Mapping")
    st.caption("You can keep your existing headers. Map them to the fields below.")

    for label, file_obj in uploaded.items():
        file_bytes = file_obj.getvalue()
        sheet_names = get_sheet_names(file_obj.name, file_bytes)
        chosen_sheet = None
        with st.expander(f"{label} upload", expanded=(label == "Pressure")):
            st.write(f"File: `{file_obj.name}`")
            if sheet_names:
                chosen_sheet = st.selectbox(
                    f"{label} sheet",
                    options=sheet_names,
                    key=f"{label.lower()}_sheet",
                )
            raw_df = read_uploaded_table(file_obj.name, file_bytes, chosen_sheet)
            raw_tables[label] = raw_df
            st.dataframe(raw_df.head(12), use_container_width=True)

    pressure_mapping = {
        "well_id": (False, PRESSURE_WELL_ALIASES),
        "date": (True, PRESSURE_DATE_ALIASES),
        "pressure_psi": (True, PRESSURE_VALUE_ALIASES),
    }
    production_mapping = {
        "well_id": (False, PROD_WELL_ALIASES),
        "date": (True, PROD_DATE_ALIASES),
        "rate": (True, PROD_RATE_ALIASES),
    }

    with st.expander("Pressure field mapping", expanded=True):
        mapped_pressure = standardize_pressure_frame(
            raw_tables["Pressure"],
            mapping_widget(raw_tables["Pressure"], "Pressure columns", pressure_mapping, "pressure"),
        )
        st.write(f"Valid pressure rows after cleaning: `{len(mapped_pressure):,}`")
        st.dataframe(mapped_pressure.head(12), use_container_width=True)

    with st.expander("Production field mapping", expanded=True):
        mapped_production = standardize_production_frame(
            raw_tables["Production"],
            mapping_widget(raw_tables["Production"], "Production columns", production_mapping, "production"),
        )
        st.write(f"Valid production rows after cleaning: `{len(mapped_production):,}`")
        st.dataframe(mapped_production.head(12), use_container_width=True)

    return UploadedInputs(pressure=mapped_pressure, production=mapped_production)


def available_wells(data: UploadedInputs) -> list[str]:
    well_values = set()
    for frame in [data.pressure, data.production]:
        if not frame.empty and "well_id" in frame.columns:
            well_values.update(frame["well_id"].dropna().astype(str))
    return sorted(value for value in well_values if value)


def filter_to_well(df: pd.DataFrame, selected_well: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    if "well_id" not in df.columns:
        return df.copy()
    return df[df["well_id"] == selected_well].copy()


def prepare_daily_production(production_df: pd.DataFrame, rate_unit_to_bbl: float) -> pd.DataFrame:
    if production_df.empty:
        return pd.DataFrame(columns=["well_id", "date", "rate_input", "rate_bpd", "cum_bbl"])

    prepared = []
    grouped = (
        production_df.groupby(["well_id", "date"], as_index=False)
        .agg(rate_input=("rate", "sum"))
        .sort_values(["well_id", "date"])
    )

    for well_id, group in grouped.groupby("well_id", sort=True):
        full_index = pd.date_range(group["date"].min(), group["date"].max(), freq="D")
        expanded = (
            group.set_index("date")[["rate_input"]]
            .reindex(full_index, fill_value=0.0)
            .rename_axis("date")
            .reset_index()
        )
        expanded["well_id"] = well_id
        expanded["rate_input"] = expanded["rate_input"].astype(float)
        expanded["rate_bpd"] = expanded["rate_input"] * rate_unit_to_bbl
        expanded["cum_bbl"] = expanded["rate_bpd"].cumsum()
        prepared.append(expanded)

    return pd.concat(prepared, ignore_index=True)


def align_pressure_with_production(pressure_df: pd.DataFrame, production_daily: pd.DataFrame) -> pd.DataFrame:
    if pressure_df.empty:
        return pd.DataFrame(
            columns=["well_id", "date", "pressure_psi", "rate_input", "rate_bpd", "cum_bbl", "point_id", "point_label"]
        )

    aligned_parts = []
    production_columns = ["date", "rate_input", "rate_bpd", "cum_bbl"]

    for well_id, pressure_group in pressure_df.groupby("well_id", sort=True):
        prod_group = production_daily[production_daily["well_id"] == well_id].copy()
        part = pressure_group.sort_values("date").copy()

        if prod_group.empty:
            part["rate_input"] = np.nan
            part["rate_bpd"] = np.nan
            part["cum_bbl"] = np.nan
        else:
            merged = pd.merge_asof(
                part.sort_values("date"),
                prod_group[production_columns].sort_values("date"),
                on="date",
                direction="backward",
            )
            part = merged

        aligned_parts.append(part)

    aligned = pd.concat(aligned_parts, ignore_index=True).sort_values(["well_id", "date"]).reset_index(drop=True)
    aligned["point_id"] = aligned.index
    aligned["point_label"] = aligned.apply(
        lambda row: (
            f"{pd.to_datetime(row['date']).date()} | "
            f"P={row['pressure_psi']:.1f} psi | "
            f"Cum={row['cum_bbl'] if pd.notna(row['cum_bbl']) else np.nan:,.0f} bbl"
        ),
        axis=1,
    )
    return aligned


def supports_plot_selection() -> bool:
    return "on_select" in inspect.signature(st.plotly_chart).parameters


def _get_item_or_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def extract_selection_indices(plot_state: Any) -> list[int]:
    if plot_state is None:
        return []

    selection = _get_item_or_attr(plot_state, "selection")
    if selection is None:
        return []

    points = _get_item_or_attr(selection, "points", []) or []
    selected: list[int] = []
    for point in points:
        custom_data = _get_item_or_attr(point, "customdata")
        if isinstance(custom_data, (list, tuple, np.ndarray)) and len(custom_data) > 0:
            try:
                selected.append(int(custom_data[0]))
                continue
            except Exception:
                pass

        for key in ("point_index", "pointIndex", "pointNumber", "point_number"):
            candidate = _get_item_or_attr(point, key)
            if candidate is None:
                continue
            try:
                selected.append(int(candidate))
                break
            except Exception:
                continue

    if selected:
        return sorted(set(selected))

    point_indices = _get_item_or_attr(selection, "point_indices")
    if point_indices is not None:
        try:
            return sorted({int(value) for value in point_indices})
        except Exception:
            pass

    return sorted(set(selected))


def store_selection_from_widget(widget_key: str, state_key: str) -> None:
    plot_state = st.session_state.get(widget_key)
    st.session_state[state_key] = extract_selection_indices(plot_state)


def clear_selection(state_key: str) -> None:
    st.session_state[state_key] = []


def selection_pool(plot_df: pd.DataFrame, selected_indices: list[int]) -> pd.DataFrame:
    if not selected_indices:
        return plot_df.iloc[0:0].copy()
    return plot_df[plot_df["point_id"].isin(selected_indices)].sort_values("date").reset_index(drop=True)


def resolve_selected_pair(pool_df: pd.DataFrame) -> tuple[pd.DataFrame, Optional[str]]:
    if len(pool_df) < 2:
        return pool_df.iloc[0:0].copy(), None

    if len(pool_df) == 2:
        return pool_df.sort_values("date").reset_index(drop=True), None

    st.warning("More than two points are currently selected. Choose the exact start and end points below.")
    options = {
        f"{row.point_label} | idx {row.point_id}": int(row.point_id)
        for row in pool_df.itertuples()
    }
    labels = list(options.keys())

    left_col, right_col = st.columns(2)
    with left_col:
        start_label = st.selectbox("Start point", options=labels, index=0, key="interactive_start_point")
    with right_col:
        end_label = st.selectbox("End point", options=labels, index=len(labels) - 1, key="interactive_end_point")

    start_id = options[start_label]
    end_id = options[end_label]
    chosen = pool_df[pool_df["point_id"].isin([start_id, end_id])].sort_values("date").reset_index(drop=True)

    if len(chosen) != 2 or chosen["point_id"].nunique() != 2:
        st.error("Choose two different points to continue.")
        return pool_df.iloc[0:0].copy(), None

    return chosen, "Custom pair chosen from a larger selected set."


def production_snapshot(production_daily: pd.DataFrame, target_date: pd.Timestamp) -> dict[str, float]:
    if production_daily.empty:
        return {"cum_bbl": np.nan, "rate_input": np.nan, "rate_bpd": np.nan}

    match = production_daily[production_daily["date"] == pd.to_datetime(target_date).normalize()]
    if match.empty:
        return {"cum_bbl": np.nan, "rate_input": np.nan, "rate_bpd": np.nan}

    row = match.iloc[0]
    return {
        "cum_bbl": float(row["cum_bbl"]),
        "rate_input": float(row["rate_input"]),
        "rate_bpd": float(row["rate_bpd"]),
    }


def initialize_manual_state_from_production(
    production_daily: pd.DataFrame,
    date_1: pd.Timestamp,
    date_2: pd.Timestamp,
) -> None:
    snap_1 = production_snapshot(production_daily, date_1)
    snap_2 = production_snapshot(production_daily, date_2)
    st.session_state["manual_cum_1"] = float(snap_1["cum_bbl"]) if pd.notna(snap_1["cum_bbl"]) else 0.0
    st.session_state["manual_cum_2"] = float(snap_2["cum_bbl"]) if pd.notna(snap_2["cum_bbl"]) else 0.0
    st.session_state["manual_rate_1"] = float(snap_1["rate_input"]) if pd.notna(snap_1["rate_input"]) else 0.0
    st.session_state["manual_rate_2"] = float(snap_2["rate_input"]) if pd.notna(snap_2["rate_input"]) else 0.0


def build_manual_points(
    pressure_df: pd.DataFrame,
    production_daily: pd.DataFrame,
    rate_unit_label: str,
) -> pd.DataFrame:
    st.subheader("Manual Point Entry")
    st.caption("Manual entry is useful when you want to override the plotted values or work with a custom pair.")

    default_date_1 = pd.to_datetime(pressure_df["date"].min()).date() if not pressure_df.empty else pd.Timestamp.today().date()
    default_date_2 = pd.to_datetime(pressure_df["date"].max()).date() if not pressure_df.empty else pd.Timestamp.today().date()
    default_p_1 = float(pressure_df["pressure_psi"].iloc[0]) if len(pressure_df) >= 1 else 0.0
    default_p_2 = float(pressure_df["pressure_psi"].iloc[-1]) if len(pressure_df) >= 1 else 0.0

    left_col, right_col = st.columns(2)
    with left_col:
        manual_date_1 = pd.to_datetime(st.date_input("Point 1 date", value=default_date_1))
        manual_pressure_1 = st.number_input("Point 1 pressure, psi", value=default_p_1, step=10.0)
    with right_col:
        manual_date_2 = pd.to_datetime(st.date_input("Point 2 date", value=default_date_2))
        manual_pressure_2 = st.number_input("Point 2 pressure, psi", value=default_p_2, step=10.0)

    snap_1 = {"cum_bbl": np.nan, "rate_input": np.nan, "rate_bpd": np.nan}
    snap_2 = {"cum_bbl": np.nan, "rate_input": np.nan, "rate_bpd": np.nan}
    if production_daily.empty:
        st.info("No production data is available for auto-fill, so enter cumulative and endpoint rates manually.")
    else:
        snap_1 = production_snapshot(production_daily, manual_date_1)
        snap_2 = production_snapshot(production_daily, manual_date_2)
        st.caption(
            "Auto-fill suggestions from the uploaded production table: "
            f"Point 1 cum {snap_1['cum_bbl'] if pd.notna(snap_1['cum_bbl']) else np.nan:,.0f} bbl, "
            f"rate {snap_1['rate_input'] if pd.notna(snap_1['rate_input']) else np.nan:,.2f} {rate_unit_label}; "
            f"Point 2 cum {snap_2['cum_bbl'] if pd.notna(snap_2['cum_bbl']) else np.nan:,.0f} bbl, "
            f"rate {snap_2['rate_input'] if pd.notna(snap_2['rate_input']) else np.nan:,.2f} {rate_unit_label}."
        )
        if st.button("Load cumulative and rate from the production table", key="load_manual_snapshots"):
            initialize_manual_state_from_production(production_daily, manual_date_1, manual_date_2)

    default_cum_1 = float(snap_1["cum_bbl"]) if pd.notna(snap_1["cum_bbl"]) else 0.0
    default_cum_2 = float(snap_2["cum_bbl"]) if pd.notna(snap_2["cum_bbl"]) else 0.0
    default_rate_1 = float(snap_1["rate_input"]) if pd.notna(snap_1["rate_input"]) else 0.0
    default_rate_2 = float(snap_2["rate_input"]) if pd.notna(snap_2["rate_input"]) else 0.0
    st.session_state.setdefault("manual_cum_1", default_cum_1)
    st.session_state.setdefault("manual_cum_2", default_cum_2)
    st.session_state.setdefault("manual_rate_1", default_rate_1)
    st.session_state.setdefault("manual_rate_2", default_rate_2)

    lower_col, upper_col = st.columns(2)
    with lower_col:
        manual_cum_1 = st.number_input("Point 1 cumulative, bbl", min_value=0.0, step=1000.0, key="manual_cum_1")
        manual_rate_1 = st.number_input(
            f"Point 1 rate, {rate_unit_label}",
            min_value=0.0,
            step=10.0,
            key="manual_rate_1",
        )
    with upper_col:
        manual_cum_2 = st.number_input("Point 2 cumulative, bbl", min_value=0.0, step=1000.0, key="manual_cum_2")
        manual_rate_2 = st.number_input(
            f"Point 2 rate, {rate_unit_label}",
            min_value=0.0,
            step=10.0,
            key="manual_rate_2",
        )

    manual_points = pd.DataFrame(
        [
            {
                "date": manual_date_1.normalize(),
                "pressure_psi": float(manual_pressure_1),
                "cum_bbl": float(manual_cum_1),
                "rate_input": float(manual_rate_1),
            },
            {
                "date": manual_date_2.normalize(),
                "pressure_psi": float(manual_pressure_2),
                "cum_bbl": float(manual_cum_2),
                "rate_input": float(manual_rate_2),
            },
        ]
    )
    return manual_points.sort_values("date").reset_index(drop=True)


def calculate_decline_metrics(points_df: pd.DataFrame, rate_unit_to_bbl: float, target_pressure: float) -> dict[str, Any]:
    ordered = points_df.sort_values("date").reset_index(drop=True)
    start = ordered.iloc[0]
    end = ordered.iloc[1]

    delta_days = (pd.to_datetime(end["date"]) - pd.to_datetime(start["date"])).total_seconds() / 86400.0
    delta_pressure_signed = float(end["pressure_psi"] - start["pressure_psi"])
    pressure_drop = float(start["pressure_psi"] - end["pressure_psi"])
    delta_cum_bbl = float(end["cum_bbl"] - start["cum_bbl"]) if {"cum_bbl"} <= set(ordered.columns) else np.nan

    rate_1_bpd = float(start["rate_input"]) * rate_unit_to_bbl if pd.notna(start.get("rate_input", np.nan)) else np.nan
    rate_2_bpd = float(end["rate_input"]) * rate_unit_to_bbl if pd.notna(end.get("rate_input", np.nan)) else np.nan

    endpoint_avg_rate_bpd = np.nan
    if pd.notna(rate_1_bpd) and pd.notna(rate_2_bpd):
        endpoint_avg_rate_bpd = (rate_1_bpd + rate_2_bpd) / 2.0

    interval_avg_rate_bpd = np.nan
    if delta_days > 0 and pd.notna(delta_cum_bbl):
        interval_avg_rate_bpd = delta_cum_bbl / delta_days

    if not np.isfinite(endpoint_avg_rate_bpd):
        endpoint_avg_rate_bpd = interval_avg_rate_bpd

    time_decline_day = pressure_drop / delta_days if delta_days > 0 else np.nan
    time_decline_month = time_decline_day * 30.0 if np.isfinite(time_decline_day) else np.nan

    decline_per_1000_bbl = np.nan
    if pd.notna(delta_cum_bbl) and delta_cum_bbl > 0:
        decline_per_1000_bbl = pressure_drop / (delta_cum_bbl / 1000.0)

    cumulative_decline_day = np.nan
    if np.isfinite(decline_per_1000_bbl) and np.isfinite(endpoint_avg_rate_bpd):
        cumulative_decline_day = decline_per_1000_bbl * (endpoint_avg_rate_bpd / 1000.0)
    cumulative_decline_month = cumulative_decline_day * 30.0 if np.isfinite(cumulative_decline_day) else np.nan

    latest_pressure = float(end["pressure_psi"])
    latest_date = pd.to_datetime(end["date"])
    remaining_pressure_to_target = latest_pressure - target_pressure

    def forecast_from_monthly_decline(monthly_decline: float) -> tuple[float, Optional[pd.Timestamp]]:
        if remaining_pressure_to_target <= 0:
            return 0.0, latest_date
        if not np.isfinite(monthly_decline) or monthly_decline <= 0:
            return np.nan, None
        months_remaining = remaining_pressure_to_target / monthly_decline
        forecast_date = latest_date + pd.to_timedelta(months_remaining * 30.0, unit="D")
        return float(months_remaining), forecast_date

    months_time, forecast_time = forecast_from_monthly_decline(time_decline_month)
    months_cum, forecast_cum = forecast_from_monthly_decline(cumulative_decline_month)

    return {
        "start_date": pd.to_datetime(start["date"]),
        "end_date": pd.to_datetime(end["date"]),
        "start_pressure_psi": float(start["pressure_psi"]),
        "end_pressure_psi": float(end["pressure_psi"]),
        "start_cum_bbl": float(start["cum_bbl"]) if pd.notna(start.get("cum_bbl", np.nan)) else np.nan,
        "end_cum_bbl": float(end["cum_bbl"]) if pd.notna(end.get("cum_bbl", np.nan)) else np.nan,
        "start_rate_input": float(start["rate_input"]) if pd.notna(start.get("rate_input", np.nan)) else np.nan,
        "end_rate_input": float(end["rate_input"]) if pd.notna(end.get("rate_input", np.nan)) else np.nan,
        "delta_days": float(delta_days),
        "delta_pressure_signed": delta_pressure_signed,
        "pressure_drop": pressure_drop,
        "delta_cum_bbl": delta_cum_bbl,
        "endpoint_avg_rate_bpd": endpoint_avg_rate_bpd,
        "interval_avg_rate_bpd": interval_avg_rate_bpd,
        "time_decline_day": time_decline_day,
        "time_decline_month": time_decline_month,
        "decline_per_1000_bbl": decline_per_1000_bbl,
        "cumulative_decline_day": cumulative_decline_day,
        "cumulative_decline_month": cumulative_decline_month,
        "remaining_pressure_to_target": remaining_pressure_to_target,
        "months_to_target_time": months_time,
        "forecast_date_time": forecast_time,
        "months_to_target_cumulative": months_cum,
        "forecast_date_cumulative": forecast_cum,
    }


def calculate_pressure_cumulative_forecast(
    calc: dict[str, Any],
    plot_df: pd.DataFrame,
    saturation_pressure: float,
    rate_unit_to_bbl: float,
) -> dict[str, Any]:
    cross_df = plot_df.dropna(subset=["cum_bbl"]).sort_values("date").reset_index(drop=True)
    if cross_df.empty:
        return {
            "last_date": None,
            "last_pressure_psi": np.nan,
            "last_cum_bbl": np.nan,
            "saturation_pressure": saturation_pressure,
            "pressure_gap": np.nan,
            "slope_psi_per_1000_bbl": calc["decline_per_1000_bbl"],
            "incremental_oil_bbl": np.nan,
            "cumulative_at_saturation_bbl": np.nan,
            "time_basis": "No valid cumulative anchor point",
            "selected_interval_growth_bpd": np.nan,
            "selected_interval_growth_input_units": np.nan,
            "months_left": np.nan,
            "forecast_date": None,
        }

    anchor = cross_df.iloc[-1]
    last_date = pd.to_datetime(anchor["date"])
    last_pressure = float(anchor["pressure_psi"])
    last_cum_bbl = float(anchor["cum_bbl"])
    pressure_gap = last_pressure - saturation_pressure if np.isfinite(last_pressure) else np.nan
    slope_psi_per_1000_bbl = calc["decline_per_1000_bbl"]
    selected_interval_growth_bpd = calc["interval_avg_rate_bpd"]
    time_basis = "Selected interval cumulative growth rate"

    incremental_oil_bbl = np.nan
    cumulative_at_saturation_bbl = np.nan
    months_left = np.nan
    forecast_date = None

    if np.isfinite(pressure_gap) and pressure_gap <= 0 and np.isfinite(last_cum_bbl):
        incremental_oil_bbl = 0.0
        cumulative_at_saturation_bbl = last_cum_bbl
        months_left = 0.0
        forecast_date = last_date
    elif (
        np.isfinite(pressure_gap)
        and pressure_gap > 0
        and np.isfinite(last_cum_bbl)
        and np.isfinite(slope_psi_per_1000_bbl)
        and slope_psi_per_1000_bbl > 0
    ):
        incremental_oil_bbl = (pressure_gap / slope_psi_per_1000_bbl) * 1000.0
        cumulative_at_saturation_bbl = last_cum_bbl + incremental_oil_bbl
        if np.isfinite(selected_interval_growth_bpd) and selected_interval_growth_bpd > 0:
            months_left = incremental_oil_bbl / selected_interval_growth_bpd / 30.0
            forecast_date = last_date + pd.to_timedelta(months_left * 30.0, unit="D")

    selected_interval_growth_input_units = (
        selected_interval_growth_bpd / rate_unit_to_bbl if np.isfinite(selected_interval_growth_bpd) else np.nan
    )

    return {
        "last_date": last_date,
        "last_pressure_psi": last_pressure,
        "last_cum_bbl": last_cum_bbl,
        "saturation_pressure": saturation_pressure,
        "pressure_gap": pressure_gap,
        "slope_psi_per_1000_bbl": slope_psi_per_1000_bbl,
        "incremental_oil_bbl": incremental_oil_bbl,
        "cumulative_at_saturation_bbl": cumulative_at_saturation_bbl,
        "time_basis": time_basis,
        "selected_interval_growth_bpd": selected_interval_growth_bpd,
        "selected_interval_growth_input_units": selected_interval_growth_input_units,
        "months_left": months_left,
        "forecast_date": forecast_date,
    }


def metric_text(value: float, digits: int = 2, suffix: str = "") -> str:
    if value is None or not np.isfinite(value):
        return "N/A"
    return f"{value:,.{digits}f}{suffix}"


def timestamp_text(value: Optional[pd.Timestamp]) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def render_pressure_vs_time_plot(plot_df: pd.DataFrame, selected_pair: pd.DataFrame, target_pressure: float) -> None:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=plot_df["date"],
            y=plot_df["pressure_psi"],
            mode="lines+markers",
            name="Pressure",
            customdata=np.column_stack([plot_df["point_id"]]),
            marker=dict(size=9, color="#b45309", line=dict(width=1, color="#7c2d12")),
            line=dict(color="#b45309", width=2),
            hovertemplate="Date=%{x|%Y-%m-%d}<br>Pressure=%{y:.2f} psi<extra></extra>",
        )
    )

    if not selected_pair.empty:
        fig.add_trace(
            go.Scatter(
                x=selected_pair["date"],
                y=selected_pair["pressure_psi"],
                mode="markers+lines",
                name="Chosen interval",
                marker=dict(size=15, color="#2563eb", line=dict(width=2, color="#1e3a8a")),
                line=dict(color="#2563eb", width=3, dash="dot"),
                hovertemplate="Chosen point<br>Date=%{x|%Y-%m-%d}<br>Pressure=%{y:.2f} psi<extra></extra>",
            )
        )

    fig.add_hline(y=target_pressure, line_dash="dash", line_color="#059669")
    fig.update_layout(
        title="Pressure vs Time",
        height=430,
        dragmode="select",
        xaxis_title="Date",
        yaxis_title="Pressure, psi",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
    )

    if supports_plot_selection():
        st.plotly_chart(
            fig,
            use_container_width=True,
            key="pressure_time_plot",
            on_select=lambda: store_selection_from_widget("pressure_time_plot", "selected_pressure_points"),
            selection_mode=("points", "box", "lasso"),
        )
    else:
        st.plotly_chart(fig, use_container_width=True)


def render_production_context_plot(production_daily: pd.DataFrame, selected_pair: pd.DataFrame) -> None:
    if production_daily.empty:
        st.info("Production plot is not available because the production table is empty after filtering.")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=production_daily["date"],
            y=production_daily["rate_bpd"],
            name="Daily rate",
            marker_color="#0f766e",
            opacity=0.65,
            yaxis="y1",
            hovertemplate="Date=%{x|%Y-%m-%d}<br>Rate=%{y:,.0f} bbl/day<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=production_daily["date"],
            y=production_daily["cum_bbl"],
            mode="lines",
            name="Cumulative",
            line=dict(color="#1d4ed8", width=3),
            yaxis="y2",
            hovertemplate="Date=%{x|%Y-%m-%d}<br>Cumulative=%{y:,.0f} bbl<extra></extra>",
        )
    )

    if not selected_pair.empty:
        for row in selected_pair.itertuples():
            fig.add_vline(x=row.date, line_dash="dot", line_color="#dc2626")

    fig.update_layout(
        title="Production Context",
        height=430,
        xaxis_title="Date",
        yaxis=dict(title="Daily rate, bbl/day"),
        yaxis2=dict(title="Cumulative, bbl", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_pressure_vs_cumulative_plot(
    plot_df: pd.DataFrame,
    selected_pair: pd.DataFrame,
    forecast: Optional[dict[str, Any]] = None,
    selection_enabled: bool = True,
    chart_key: str = "pressure_cum_plot",
) -> None:
    cross_df = plot_df.dropna(subset=["cum_bbl"]).copy()
    if cross_df.empty:
        st.info("Pressure vs cumulative cannot be plotted yet because no pressure points could be aligned to cumulative production.")
        return

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=cross_df["cum_bbl"],
            y=cross_df["pressure_psi"],
            mode="lines+markers",
            name="Pressure cross-plot",
            customdata=np.column_stack([cross_df["point_id"]]),
            marker=dict(size=9, color="#2563eb", line=dict(width=1, color="#1e3a8a")),
            line=dict(color="#2563eb", width=2),
            hovertemplate="Cum=%{x:,.0f} bbl<br>Pressure=%{y:.2f} psi<extra></extra>",
        )
    )

    if not selected_pair.empty and selected_pair["cum_bbl"].notna().all():
        fig.add_trace(
            go.Scatter(
                x=selected_pair["cum_bbl"],
                y=selected_pair["pressure_psi"],
                mode="markers+lines",
                name="Chosen interval",
                marker=dict(size=15, color="#dc2626", line=dict(width=2, color="#7f1d1d")),
                line=dict(color="#dc2626", width=3, dash="dot"),
                hovertemplate="Chosen point<br>Cum=%{x:,.0f} bbl<br>Pressure=%{y:.2f} psi<extra></extra>",
            )
        )

    if forecast is not None:
        x0 = forecast.get("last_cum_bbl")
        y0 = forecast.get("last_pressure_psi")
        x1 = forecast.get("cumulative_at_saturation_bbl")
        y1 = forecast.get("saturation_pressure")
        if all(np.isfinite(value) for value in [x0, y0, x1, y1]):
            fig.add_trace(
                go.Scatter(
                    x=[x0, x1],
                    y=[y0, y1],
                    mode="lines+markers",
                    name="Forecast to saturation",
                    marker=dict(size=12, color="#059669", line=dict(width=2, color="#065f46")),
                    line=dict(color="#059669", width=3, dash="dash"),
                    hovertemplate="Cum=%{x:,.0f} bbl<br>Pressure=%{y:.2f} psi<extra></extra>",
                )
            )

    chart_title = "Pressure vs Cumulative Production with Forecast" if forecast is not None and not selection_enabled else "Pressure vs Cumulative Production"
    fig.update_layout(
        title=chart_title,
        height=430,
        dragmode="select",
        xaxis_title="Cumulative production, bbl",
        yaxis_title="Pressure, psi",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
    )

    if selection_enabled and supports_plot_selection():
        st.plotly_chart(
            fig,
            use_container_width=True,
            key=chart_key,
            on_select=lambda: store_selection_from_widget(chart_key, "selected_pressure_points"),
            selection_mode=("points", "box", "lasso"),
        )
    else:
        st.plotly_chart(fig, use_container_width=True)


def build_results_download(calc: dict[str, Any], forecast: dict[str, Any], rate_unit_label: str) -> bytes:
    results = pd.DataFrame(
        [
            {"section": "Method 1", "metric": "Start date", "value": timestamp_text(calc["start_date"])},
            {"section": "Method 1", "metric": "End date", "value": timestamp_text(calc["end_date"])},
            {"section": "Method 1", "metric": "Start pressure, psi", "value": calc["start_pressure_psi"]},
            {"section": "Method 1", "metric": "End pressure, psi", "value": calc["end_pressure_psi"]},
            {"section": "Method 1", "metric": "Pressure drop, psi", "value": calc["pressure_drop"]},
            {"section": "Method 1", "metric": "Delta time, days", "value": calc["delta_days"]},
            {"section": "Method 1", "metric": "Time decline, psi/day", "value": calc["time_decline_day"]},
            {"section": "Method 1", "metric": "Time decline, psi/month", "value": calc["time_decline_month"]},
            {"section": "Method 2", "metric": "Delta cumulative, bbl", "value": calc["delta_cum_bbl"]},
            {"section": "Method 2", "metric": f"Start rate, {rate_unit_label}", "value": calc["start_rate_input"]},
            {"section": "Method 2", "metric": f"End rate, {rate_unit_label}", "value": calc["end_rate_input"]},
            {"section": "Method 2", "metric": "Decline, psi/1000 bbl", "value": calc["decline_per_1000_bbl"]},
            {"section": "Method 2", "metric": "Cumulative decline, psi/day", "value": calc["cumulative_decline_day"]},
            {"section": "Method 2", "metric": "Cumulative decline, psi/month", "value": calc["cumulative_decline_month"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Latest pressure date", "value": timestamp_text(forecast["last_date"])},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Latest pressure, psi", "value": forecast["last_pressure_psi"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Latest cumulative, bbl", "value": forecast["last_cum_bbl"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Saturation pressure, psi", "value": forecast["saturation_pressure"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Pressure gap to saturation, psi", "value": forecast["pressure_gap"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Selected slope, psi/1000 bbl", "value": forecast["slope_psi_per_1000_bbl"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Incremental oil to saturation, bbl", "value": forecast["incremental_oil_bbl"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Forecast cumulative at saturation, bbl", "value": forecast["cumulative_at_saturation_bbl"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Time basis", "value": forecast["time_basis"]},
            {
                "section": "Pressure vs Cumulative Forecast",
                "metric": f"Selected interval cumulative growth rate, {rate_unit_label}",
                "value": forecast["selected_interval_growth_input_units"],
            },
            {
                "section": "Pressure vs Cumulative Forecast",
                "metric": "Selected interval cumulative growth rate, bbl/day",
                "value": forecast["selected_interval_growth_bpd"],
            },
            {"section": "Pressure vs Cumulative Forecast", "metric": "Months left to saturation", "value": forecast["months_left"]},
            {"section": "Pressure vs Cumulative Forecast", "metric": "Forecast date", "value": timestamp_text(forecast["forecast_date"])},
        ]
    )
    return results.to_csv(index=False).encode("utf-8")


def main() -> None:
    st.title("Pressure Decline Calculator")
    st.write(
        "This app reproduces the workbook logic behind pressure decline by time and pressure decline by cumulative "
        "production, while adding interactive point selection from the plots and manual point overrides."
    )

    data = build_uploader_section()
    if data.pressure.empty or data.production.empty:
        st.warning("Both the pressure table and the production table must contain valid rows.")
        st.stop()

    with st.sidebar:
        st.header("Analysis Settings")
        rate_unit_label = st.selectbox(
            "Production rate unit",
            options=list(RATE_UNIT_TO_BBL.keys()),
            index=0,
            help="Choose the unit used in your uploaded daily production rate column.",
        )
        target_pressure = st.number_input(
            "Saturation pressure, psi",
            min_value=0.0,
            value=2300.0,
            step=25.0,
            help="Used by the separate pressure-vs-cumulative forecast section.",
        )

    wells = available_wells(data)
    if not wells:
        st.error("No usable well identifier was found after cleaning the input tables.")
        st.stop()

    selected_well = wells[0]
    if len(wells) > 1:
        selected_well = st.sidebar.selectbox("Well", options=wells, index=0)

    pressure_df = filter_to_well(data.pressure, selected_well)
    production_df = filter_to_well(data.production, selected_well)
    production_daily = prepare_daily_production(production_df, RATE_UNIT_TO_BBL[rate_unit_label])
    plot_df = align_pressure_with_production(pressure_df, production_daily)

    if plot_df.empty:
        st.warning("No pressure points are available for the selected well.")
        st.stop()

    st.subheader("Prepared Data")
    prep_col_1, prep_col_2, prep_col_3 = st.columns(3)
    prep_col_1.metric("Pressure points", f"{len(plot_df):,}")
    prep_col_2.metric("Production days", f"{len(production_daily):,}")
    prep_col_3.metric("Latest cumulative", metric_text(production_daily["cum_bbl"].iloc[-1], 0, " bbl") if not production_daily.empty else "N/A")

    selection_mode = st.radio(
        "Point definition mode",
        options=["Interactive plot selection", "Manual entry"],
        horizontal=True,
        help="Use plot selection for the best workflow, or manual entry when you want to type the two points yourself.",
    )

    selected_pair = pd.DataFrame()
    selection_note = None

    if selection_mode == "Interactive plot selection":
        control_col_1, control_col_2 = st.columns([5, 1])
        with control_col_1:
            st.caption("Select two pressure points from either plot. If you select more than two, you can refine the exact pair below.")
        with control_col_2:
            if st.button("Clear selection"):
                clear_selection("selected_pressure_points")

        selected_indices = st.session_state.get("selected_pressure_points", [])
        pool = selection_pool(plot_df, selected_indices)
        if len(pool) >= 2:
            selected_pair, selection_note = resolve_selected_pair(pool)

        plot_col_1, plot_col_2 = st.columns(2)
        with plot_col_1:
            render_pressure_vs_time_plot(plot_df, selected_pair, target_pressure)
        with plot_col_2:
            render_production_context_plot(production_daily, selected_pair)

        if len(pool) < 2:
            st.info("Select at least two pressure points from the chart to run the decline calculation.")
            st.stop()

        if selected_pair.empty:
            st.stop()
    else:
        selected_pair = build_manual_points(pressure_df, production_daily, rate_unit_label)
        plot_col_1, plot_col_2 = st.columns(2)
        with plot_col_1:
            render_pressure_vs_time_plot(plot_df, selected_pair, target_pressure)
        with plot_col_2:
            render_production_context_plot(production_daily, selected_pair)

    calc = calculate_decline_metrics(selected_pair, RATE_UNIT_TO_BBL[rate_unit_label], target_pressure)
    cumulative_forecast = calculate_pressure_cumulative_forecast(
        calc,
        plot_df,
        target_pressure,
        RATE_UNIT_TO_BBL[rate_unit_label],
    )

    if calc["delta_days"] <= 0:
        st.error("The two points must be on different dates.")
        st.stop()

    if selection_note:
        st.caption(selection_note)
    if calc["pressure_drop"] < 0:
        st.warning("The later point has higher pressure than the earlier point, so the calculated decline values are negative.")

    if pd.notna(calc["delta_cum_bbl"]) and calc["delta_cum_bbl"] <= 0:
        st.warning("Cumulative production did not increase between the selected points, so the cumulative-based method is not meaningful for this pair.")

    st.subheader("Selected Interval")
    selected_view = selected_pair.copy()
    selected_view["date"] = pd.to_datetime(selected_view["date"]).dt.strftime("%Y-%m-%d")
    selected_view = selected_view.rename(
        columns={
            "pressure_psi": "pressure_psi",
            "cum_bbl": "cumulative_bbl",
            "rate_input": f"rate_{rate_unit_label}",
        }
    )
    st.dataframe(selected_view[["date", "pressure_psi", "cumulative_bbl", f"rate_{rate_unit_label}"]], use_container_width=True)

    st.subheader("Core Interval Metrics")
    metric_col_1, metric_col_2, metric_col_3, metric_col_4 = st.columns(4)
    metric_col_1.metric("Pressure drop", metric_text(calc["pressure_drop"], 2, " psi"))
    metric_col_2.metric("Delta time", metric_text(calc["delta_days"], 1, " days"))
    metric_col_3.metric("Delta cumulative", metric_text(calc["delta_cum_bbl"], 0, " bbl"))
    metric_col_4.metric(
        f"Average endpoint rate",
        metric_text(calc["endpoint_avg_rate_bpd"] / RATE_UNIT_TO_BBL[rate_unit_label], 2, f" {rate_unit_label}"),
    )

    results_col_1, results_col_2 = st.columns(2)
    with results_col_1:
        st.markdown("**Method 1: Pressure Drop Over Time**")
        time_results = pd.DataFrame(
            [
                {"metric": "Signed Delta P (P2 - P1)", "value": metric_text(calc["delta_pressure_signed"], 2, " psi")},
                {"metric": "Pressure drop (P1 - P2)", "value": metric_text(calc["pressure_drop"], 2, " psi")},
                {"metric": "Delta time", "value": metric_text(calc["delta_days"], 1, " days")},
                {"metric": "Decline per day", "value": metric_text(calc["time_decline_day"], 4, " psi/day")},
                {"metric": "Decline per month", "value": metric_text(calc["time_decline_month"], 3, " psi/month")},
            ]
        )
        st.dataframe(time_results, use_container_width=True, hide_index=True)

    with results_col_2:
        st.markdown("**Method 2: Pressure Drop Over Cumulative Production**")
        cumulative_results = pd.DataFrame(
            [
                {"metric": "Delta cumulative", "value": metric_text(calc["delta_cum_bbl"], 0, " bbl")},
                {"metric": "Decline per 1000 bbl", "value": metric_text(calc["decline_per_1000_bbl"], 4, " psi/1000 bbl")},
                {
                    "metric": f"Average endpoint rate",
                    "value": metric_text(
                        calc["endpoint_avg_rate_bpd"] / RATE_UNIT_TO_BBL[rate_unit_label],
                        2,
                        f" {rate_unit_label}",
                    ),
                },
                {
                    "metric": "Interval-average rate",
                    "value": metric_text(
                        calc["interval_avg_rate_bpd"] / RATE_UNIT_TO_BBL[rate_unit_label],
                        2,
                        f" {rate_unit_label}",
                    ),
                },
                {"metric": "Decline per day", "value": metric_text(calc["cumulative_decline_day"], 4, " psi/day")},
                {"metric": "Decline per month", "value": metric_text(calc["cumulative_decline_month"], 3, " psi/month")},
            ]
        )
        st.dataframe(cumulative_results, use_container_width=True, hide_index=True)

    st.subheader("Pressure vs Cumulative Forecast to Saturation Pressure")
    st.caption(
        "This forecast uses the slope from the selected pressure-vs-cumulative interval, but it starts from the latest pressure data point on the full plot and stays separate from Methods 1 and 2."
    )
    st.caption(
        "Time to saturation logic: first the app finds the cumulative oil at saturation from the selected straight-line pressure-vs-cumulative relation. "
        "Then it converts that cumulative gap to time using the selected interval cumulative growth rate: "
        "`Time = (Cumulative at saturation - Latest cumulative) / Selected interval cumulative growth rate`."
    )
    render_pressure_vs_cumulative_plot(
        plot_df,
        selected_pair,
        forecast=cumulative_forecast,
        selection_enabled=False,
        chart_key="pressure_cum_forecast_plot",
    )
    forecast_table = pd.DataFrame(
        [
            {"metric": "Latest pressure date", "value": timestamp_text(cumulative_forecast["last_date"])},
            {"metric": "Latest pressure", "value": metric_text(cumulative_forecast["last_pressure_psi"], 2, " psi")},
            {"metric": "Latest cumulative", "value": metric_text(cumulative_forecast["last_cum_bbl"], 0, " bbl")},
            {"metric": "Saturation pressure", "value": metric_text(cumulative_forecast["saturation_pressure"], 2, " psi")},
            {"metric": "Pressure gap to saturation", "value": metric_text(cumulative_forecast["pressure_gap"], 2, " psi")},
            {"metric": "Selected slope", "value": metric_text(cumulative_forecast["slope_psi_per_1000_bbl"], 4, " psi/1000 bbl")},
            {"metric": "Incremental oil to saturation", "value": metric_text(cumulative_forecast["incremental_oil_bbl"], 0, " bbl")},
            {
                "metric": "Forecast cumulative at saturation",
                "value": metric_text(cumulative_forecast["cumulative_at_saturation_bbl"], 0, " bbl"),
            },
            {"metric": "Time basis", "value": cumulative_forecast["time_basis"]},
            {
                "metric": f"Selected interval cumulative growth rate",
                "value": metric_text(cumulative_forecast["selected_interval_growth_input_units"], 2, f" {rate_unit_label}"),
            },
            {
                "metric": "Selected interval cumulative growth rate",
                "value": metric_text(cumulative_forecast["selected_interval_growth_bpd"], 2, " bbl/day"),
            },
            {"metric": "Months left to saturation", "value": metric_text(cumulative_forecast["months_left"], 2, " months")},
            {"metric": "Forecast date", "value": timestamp_text(cumulative_forecast["forecast_date"])},
        ]
    )
    st.dataframe(forecast_table, use_container_width=True, hide_index=True)
    st.caption(
        "Time logic: the forecast line itself comes only from the selected pressure-vs-cumulative straight line. "
        "The selected interval cumulative growth rate is used only to convert forecasted cumulative oil into time to saturation and forecast date."
    )

    st.download_button(
        "Download results CSV",
        data=build_results_download(calc, cumulative_forecast, rate_unit_label),
        file_name="pressure_decline_results.csv",
        mime="text/csv",
    )

    with st.expander("Calculation notes"):
        st.write(
            "1. Cumulative production is built from the uploaded daily production rate table after converting the chosen unit to bbl/day.\n"
            "2. Missing calendar days in the production table are expanded as zero-rate days so cumulative production stays calendar-aligned.\n"
            "3. The cumulative method keeps the workbook’s idea of using the average of the two endpoint rates, while also showing the true interval-average rate for reference.\n"
            "4. Pressure points are aligned to cumulative production using the production record on the same day or the latest earlier day."
        )


if __name__ == "__main__":
    main()
