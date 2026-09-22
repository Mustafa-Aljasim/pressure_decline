"""Plot builders consume the shared results without recalculating forecasts."""
import numpy as np
import plotly.graph_objects as go


def pressure_figure(history, results, psat, cumulative=False):
    xkey = "cum_bbl" if cumulative else "date"
    data = history.dropna(subset=[xkey, "pressure_psi"])
    fig = go.Figure(go.Scatter(
        x=data[xkey], y=data["pressure_psi"], mode="markers", name="Pressure data",
        customdata=[{"_point_id": value} for value in data["_point_id"]],
        meta={"selection_role": "pressure_history"},
        marker=dict(color="#64748b", size=8),
    ))
    for r in results:
        points = r.selection.points.sort_values("date")
        details = [[str(p.date.date()), p.cum_bbl, getattr(p, "rate_bpd", np.nan)] for p in points.itertuples()]
        fig.add_trace(go.Scatter(
            x=points[xkey], y=points["pressure_psi"], mode="lines+markers", name=r.selection.name,
            line=dict(color=r.selection.color, width=3), marker=dict(size=12, symbol="diamond"), customdata=details,
            hovertemplate=r.selection.name + " start/end<br>Date=%{customdata[0]}<br>Pressure=%{y:,.2f} psi"
            "<br>Cumulative=%{customdata[1]:,.0f} bbl<br>Daily rate=%{customdata[2]:,.2f} bbl/day<extra></extra>",
        ))
        f = r.forecast
        end = f["cumulative_at_saturation_bbl"] if cumulative else f["time_date"]
        start = f["last_cum_bbl"] if cumulative else f["last_date"]
        valid = np.isfinite(end) and np.isfinite(start) if cumulative else end is not None
        if valid:
            fig.add_trace(go.Scatter(
                x=[start, end], y=[f["last_pressure_psi"], psat], mode="lines+markers",
                name=r.selection.name + " forecast", line=dict(color=r.selection.color, dash="dash", width=2),
            ))
    fig.add_hline(y=psat, line_dash="dot", line_color="#059669", annotation_text="Psat")
    fig.update_layout(
        title="Pressure vs Cumulative Production" if cumulative else "Pressure vs Time",
        xaxis_title="Cumulative production, bbl" if cumulative else "Date", yaxis_title="Pressure, psi",
        height=500, dragmode="pan", clickmode="event+select",
        legend=dict(orientation="h", y=-0.22), margin=dict(b=110),
    )
    return fig


def production_figure(daily, results):
    fig = go.Figure(go.Bar(x=daily["date"], y=daily["rate_bpd"], name="Daily rate", marker_color="#0f766e", opacity=0.55))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["cum_bbl"], name="Cumulative production", yaxis="y2", line=dict(color="#334155")))
    for r in results:
        fig.add_vrect(x0=r.metrics["start_date"], x1=r.metrics["end_date"], fillcolor=r.selection.color,
                      opacity=0.1, line_width=1, annotation_text=r.selection.name,
                      annotation_position="top left")
    fig.update_layout(title="Production Context", xaxis_title="Date", yaxis_title="Daily rate, bbl/day",
                      yaxis2=dict(title="Cumulative production, bbl", overlaying="y", side="right"),
                      height=400, legend=dict(orientation="h", y=-0.2))
    return fig
