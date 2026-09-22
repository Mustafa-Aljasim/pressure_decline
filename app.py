import inspect
import io
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd
import streamlit as st
from pressure_selection import ensure_pressure_ids




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

    return UploadedInputs(pressure=ensure_pressure_ids(pressure), production=production)


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
    for id_column in ("_point_id", "point_id", "row_id", "id"):
        if id_column in raw_df:
            out["_point_id"] = raw_df[id_column]
            break
    out = ensure_pressure_ids(out)
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
        demo_mode = st.toggle("Use demo dataset", value=False, key="demo_mode")
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
    """Sum calendar-day volumes, including the full volume on each row's date."""
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
        # Every expanded row represents one calendar day, including the first.
        daily_volume_bbl = expanded["rate_bpd"] * 1.0
        expanded["cum_bbl"] = daily_volume_bbl.cumsum()
        prepared.append(expanded)

    return pd.concat(prepared, ignore_index=True)


def align_pressure_with_production(pressure_df: pd.DataFrame, production_daily: pd.DataFrame) -> pd.DataFrame:
    if pressure_df.empty:
        return pd.DataFrame(
            columns=["well_id", "date", "pressure_psi", "rate_input", "rate_bpd", "cum_bbl", "_point_id", "point_id", "point_label"]
        )

    pressure_df = ensure_pressure_ids(pressure_df)
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
    aligned["point_id"] = aligned["_point_id"]  # Compatibility alias; never a positional index.
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


def production_snapshot(production_daily: pd.DataFrame, target_date: pd.Timestamp) -> dict[str, float]:
    if production_daily.empty:
        return {"cum_bbl": np.nan, "rate_input": np.nan, "rate_bpd": np.nan}

    match = production_daily[
        production_daily["date"] <= pd.to_datetime(target_date).normalize()
    ].sort_values("date")
    if match.empty:
        return {"cum_bbl": np.nan, "rate_input": np.nan, "rate_bpd": np.nan}

    row = match.iloc[-1]
    return {
        "cum_bbl": float(row["cum_bbl"]),
        "rate_input": float(row["rate_input"]),
        "rate_bpd": float(row["rate_bpd"]),
    }


def main() -> None:
    import sys
    from trend_ui import run_app

    st.set_page_config(page_title="Pressure Decline Calculator", layout="wide")
    run_app(sys.modules[__name__])


if __name__ == "__main__":
    main()
