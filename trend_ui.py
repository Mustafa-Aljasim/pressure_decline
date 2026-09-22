"""Streamlit controls for independent selections sharing one set of results."""
import hashlib
from functools import partial
import pandas as pd
import streamlit as st

from trend_analysis import COLORS, CUMULATIVE_NOTE, DISCLAIMER, TrendSelection, build_trend_results, result_tables, build_results_csv, build_plot_workbook
from trend_plots import pressure_figure, production_figure
from pressure_selection import clear_trend_selection, update_trend_selection


def apply_chart_selection(chart_key, prefix, ordered_ids, pressure_curves):
    update_trend_selection(st.session_state, st.session_state.get(chart_key), prefix, ordered_ids, pressure_curves)



def manual_points(a, history, daily, prefix, factor, unit):
    rows = []
    for i, col in enumerate(st.columns(2)):
        with col:
            default = history.iloc[0 if i == 0 else -1]
            key = f"{prefix}_manual_{i}"
            date = pd.Timestamp(st.date_input(f"Point {i + 1} date", value=default["date"].date(), key=key + "_date"))
            pressure = st.number_input(f"Point {i + 1} pressure, psi", value=float(default["pressure_psi"]), key=key + "_pressure")
            snap = a.production_snapshot(daily, date)
            if st.button("Load cumulative and rate from production", key=key + "_load"):
                st.session_state[key + "_cum"] = float(snap["cum_bbl"]) if pd.notna(snap["cum_bbl"]) else 0.0
                st.session_state[key + "_rate"] = float(snap["rate_input"]) if pd.notna(snap["rate_input"]) else 0.0
            if pd.isna(snap["cum_bbl"]):
                st.caption("No earlier production record. Enter a known cumulative value manually.")
            cum = st.number_input(f"Point {i + 1} cumulative, bbl", min_value=0.0,
                                  value=float(snap["cum_bbl"]) if pd.notna(snap["cum_bbl"]) else 0.0, key=key + "_cum")
            rate = st.number_input(f"Point {i + 1} rate, {unit}", min_value=0.0,
                                   value=float(snap["rate_input"]) if pd.notna(snap["rate_input"]) else 0.0, key=key + "_rate")
            rows.append(dict(date=date, pressure_psi=pressure, cum_bbl=cum, rate_input=rate, rate_bpd=rate * factor))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def cached_pdf(history, daily, results, psat, metadata):
    from report import build_pdf_report
    return build_pdf_report(history, daily, results, psat, metadata)


def run_app(a):
    st.title("Pressure Decline Calculator")
    st.write("Compare up to three alternative engineering interpretations of pressure history. Trends are not statistical P10/P50/P90 scenarios.")
    data = a.build_uploader_section()
    if data.pressure.empty or data.production.empty:
        st.warning("Both tables must contain valid rows.")
        return
    with st.sidebar:
        st.header("Analysis Settings")
        unit = st.selectbox("Production rate unit", list(a.RATE_UNIT_TO_BBL))
        psat = st.number_input("Saturation pressure, psi", min_value=0.0, value=2300.0, step=25.0)
        wells = a.available_wells(data)
        well = st.selectbox("Well", wells) if len(wells) > 1 else wells[0]
        reference = st.selectbox("Forecast reference", ["Latest measured pressure", "Selected interval end"],
                                 help="Latest measured pressure preserves the existing forecast anchor. Selected interval end extends each chosen line directly to Psat.")
    factor = a.RATE_UNIT_TO_BBL[unit]
    pressure = a.filter_to_well(data.pressure, well)
    daily = a.prepare_daily_production(a.filter_to_well(data.production, well), factor)
    history = a.align_pressure_with_production(pressure, daily)
    if history.empty:
        st.warning("No pressure observations are available for this well.")
        return
    # Separate state by data, well and units so old endpoints cannot leak into a new upload.
    digest = hashlib.sha256(pd.util.hash_pandas_object(history, index=True).values.tobytes()).hexdigest()[:12]
    scope = f"{digest}_{factor}"
    columns = st.columns(3)
    columns[0].metric("Pressure observations", len(history))
    columns[1].metric("Production days", len(daily))
    columns[2].metric("Latest cumulative", f"{daily['cum_bbl'].iloc[-1]:,.0f} bbl" if not daily.empty else "N/A")
    if daily.empty:
        st.warning("No production history for this well. Cumulative analysis requires manual values.")
    st.subheader("Trend Selections")
    enabled = [1]
    c2, c3 = st.columns(2)
    if c2.checkbox("Enable Trend 2", key=scope + "_enable2"):
        enabled.append(2)
    if c3.checkbox("Enable Trend 3", key=scope + "_enable3"):
        enabled.append(3)
    active = st.selectbox("Apply chart selection to", [f"Trend {i}" for i in enabled], key=scope + "_active")
    st.caption("Click historical points one at a time in Pan mode (the default), or choose Box Select / Lasso Select from the plot toolbar. Choose exact endpoints from the selected group. Both plots use the same interval; Clear selection restores all endpoint choices.")
    selections = []
    ids = history["_point_id"].tolist()
    labels = history.set_index("_point_id")["point_label"].to_dict()
    modes = {}
    for i in enabled:
        prefix = f"{scope}_trend{i}"
        with st.expander(f"Trend {i}", expanded=True):
            mode = st.radio("Point definition mode", ["Interactive plot selection", "Manual entry"], horizontal=True, key=prefix + "_mode")
            modes[f"Trend {i}"] = mode
            if mode == "Manual entry":
                points = manual_points(a, history, daily, prefix, factor, unit)
            else:
                st.button("Clear selection", key=prefix + "_clear",
                          on_click=clear_trend_selection, args=(st.session_state, prefix, tuple(ids)))
                selected_ids = st.session_state.get(prefix + "_selected_ids", [])
                pool = [point_id for point_id in ids if point_id in selected_ids]
                if len(pool) == 1:
                    st.info("One pressure point selected. Click another point, select a group, or clear the selection.")
                    continue
                options = pool or ids
                previous_pair = st.session_state.get(prefix + "_chosen_pair", (options[0], options[-1]))
                for suffix, fallback in [("_start", previous_pair[0]), ("_end", previous_pair[1])]:
                    if st.session_state.get(prefix + suffix) not in options:
                        st.session_state[prefix + suffix] = fallback if fallback in options else options[0 if suffix == "_start" else -1]
                if pool:
                    st.caption(f"{len(pool)} historical pressure points selected. Choose the exact start and end below.")
                cols = st.columns(2)
                start = cols[0].selectbox("Start point", options, format_func=labels.get, key=prefix + "_start")
                end = cols[1].selectbox("End point", options, format_func=labels.get, key=prefix + "_end")
                st.session_state[prefix + "_chosen_pair"] = (start, end)
                points = history.set_index("_point_id", drop=False).loc[[start, end]].reset_index(drop=True)
            selections.append(TrendSelection(f"Trend {i}", points, COLORS[i - 1], mode=mode))
    results = build_trend_results(selections, history, psat, reference)
    for r in results:
        for issue in r.issues:
            st.warning(r.selection.name + ": " + issue)
    st.caption("Solid lines connect selected points; dashed forecasts use " + reference.lower() + ". The interval-average rate converts forecast oil to time. With this basis, both forecast dates coincide when valid.")
    for cumulative, col in zip([False, True], st.columns(2)):
        with col:
            prefix = f"{scope}_trend{active[-1]}"
            revision = st.session_state.get(prefix + "_chart_revision", 0)
            key = f"{scope}_{active}_{cumulative}_{revision}_chart"
            kwargs = {}
            figure = pressure_figure(history, results, psat, cumulative)
            selected_ids = st.session_state.get(prefix + "_selected_ids", [])
            pressure_curves = tuple(i for i, trace in enumerate(figure.data)
                                    if trace.meta and trace.meta.get("selection_role") == "pressure_history")
            for i in pressure_curves:
                trace = figure.data[i]
                trace.selectedpoints = [j for j, custom in enumerate(trace.customdata) if custom["_point_id"] in selected_ids] if selected_ids else None
            if a.supports_plot_selection() and modes[active] != "Manual entry":
                kwargs = dict(on_select=partial(apply_chart_selection, key, prefix, tuple(ids), pressure_curves), selection_mode=("points", "box", "lasso"))
            st.plotly_chart(figure, use_container_width=True, key=key, **kwargs)
    st.plotly_chart(production_figure(daily, results), use_container_width=True, key=scope + "_production")
    for title, frame in result_tables(results).items():
        st.subheader(title)
        st.dataframe(frame, use_container_width=True, hide_index=True)
    st.caption("Months use 30 days; years use 365 days. An already-reached date is the reference measurement date, not an estimated historical crossing date.")
    st.subheader("Engineering Report")
    def source(key, fallback):
        if st.session_state.get("demo_mode"):
            return fallback
        uploaded = st.session_state.get(key)
        name = getattr(uploaded, "name", "Uploaded table")
        sheet = st.session_state.get(key.replace("_file", "_sheet"))
        return name + (f" / sheet: {sheet}" if sheet else "")
    metadata = dict(well=well, rate_unit=unit,
                    pressure_source=source("pressure_file", "Built-in demo pressure dataset"),
                    production_source=source("production_file", "Built-in demo production dataset"))
    # Generate only on demand. Invalidate a prepared report when any input changes.
    report_key = hashlib.sha256((repr(results) + repr(metadata) + str(psat) + scope).encode()).hexdigest()
    if st.button("Prepare Professional PDF Report", type="primary", disabled=not results):
        if daily.empty:
            st.warning("A production history is required for the full engineering report.")
        else:
            with st.spinner("Preparing engineering report..."):
                st.session_state["prepared_pdf"] = (report_key, cached_pdf(history, daily, results, psat, metadata))
    stored = st.session_state.get("prepared_pdf")
    if stored and stored[0] == report_key:
        st.download_button("Download Professional PDF Report", stored[1], "pressure_decline_report.pdf", "application/pdf", type="primary")
    st.download_button("Download results CSV", build_results_csv(results), "pressure_decline_results.csv", "text/csv")
    st.download_button(
        "Download pressure plots data (Excel)",
        build_plot_workbook(history, daily, results, psat),
        "pressure_decline_plots_data.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Includes historical points, selected Trend 1/2/3 intervals, forecast-to-Psat coordinates, production history, and summary tables.",
    )
    with st.expander("Calculation notes"):
        st.write(CUMULATIVE_NOTE)
        st.write("Missing calendar dates are expanded as zero-rate days, an assumption rather than confirmation of shut-in. Pressure points include same-day production or the latest earlier cumulative value.")
        st.write("Time decline = pressure drop / elapsed days. Cumulative decline = pressure drop / cumulative increment. Interval-average rate = cumulative increment / elapsed days. Forecast oil = pressure gap / cumulative decline; forecast time = forecast oil / interval-average rate.")
        st.write(DISCLAIMER)
