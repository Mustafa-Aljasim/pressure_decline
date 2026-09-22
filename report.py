"""Seven-page engineering report generated from the UI's shared trend results."""
import io
from datetime import datetime
from xml.sax.saxutils import escape

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import dates as mdates
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

from trend_analysis import CUMULATIVE_NOTE, DISCLAIMER, date_text, result_tables


def chart_image(history, daily, results, psat, kind):
    fig = Figure(figsize=(10.6, 2.1 if kind == "timeline" else 5.1), dpi=180, layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.18)
    if kind == "production":
        ax.bar(daily["date"], daily["rate_bpd"], color="#0f766e", alpha=0.45, label="Daily rate")
        other = ax.twinx()
        other.plot(daily["date"], daily["cum_bbl"], color="#334155", label="Cumulative production")
        other.set_ylabel("Cumulative production, bbl")
        ax.set_ylabel("Daily rate, bbl/day")
        for r in results:
            ax.axvspan(r.metrics["start_date"], r.metrics["end_date"], color=r.selection.color, alpha=0.13, label=r.selection.name)
        ax.set_xlabel("Date")
        handles, labels = ax.get_legend_handles_labels()
        other_handles, other_labels = other.get_legend_handles_labels()
        ax.legend(handles + other_handles, labels + other_labels, loc="upper left", fontsize=9)
    elif kind == "timeline":
        for i, r in enumerate(results):
            f = r.forecast
            if f["forecast_date"] is not None:
                ax.plot([f["last_date"], f["forecast_date"]], [i, i], color=r.selection.color, marker="o", lw=3)
                ax.annotate(date_text(f["forecast_date"]), (f["forecast_date"], i), xytext=(5, 10), textcoords="offset points", fontsize=10)
            else:
                ax.scatter([f["last_date"]], [i], color=r.selection.color)
                ax.annotate("No valid forecast", (f["last_date"], i), xytext=(5, 10), textcoords="offset points", fontsize=10)
        ax.set_yticks(range(len(results)), [r.selection.name for r in results])
        ax.set_ylim(-0.6, max(0.6, len(results) - 0.4))
        ax.set_xlabel("Forecast reference date to cumulative-based Psat date")
        ax.margins(x=0.2)
    else:
        cumulative = kind == "cumulative"
        key = "cum_bbl" if cumulative else "date"
        ax.scatter(history[key], history["pressure_psi"], color="#64748b", s=22, label="Pressure data")
        for r in results:
            p, f = r.selection.points.sort_values("date"), r.forecast
            ax.plot(p[key], p["pressure_psi"], color=r.selection.color, marker="D", lw=2.5, label=r.selection.name)
            start = f["last_cum_bbl"] if cumulative else f["last_date"]
            end = f["cumulative_at_saturation_bbl"] if cumulative else f["time_date"]
            valid = np.isfinite(start) and np.isfinite(end) if cumulative else end is not None
            if valid:
                ax.plot([start, end], [f["last_pressure_psi"], psat], color=r.selection.color, ls="--", lw=2)
        ax.axhline(psat, color="#059669", ls=":", label="Psat")
        ax.set_ylabel("Pressure, psi")
        ax.set_xlabel("Cumulative production, bbl" if cumulative else "Date")
    if kind != "cumulative":
        locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    if kind not in ("timeline", "production"):
        ax.legend(loc="best", fontsize=9)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=180)
    buffer.seek(0)
    return Image(buffer, width=735, height=354 if kind != "timeline" else 146)


def build_pdf_report(history, daily, results, psat, metadata):
    buffer = io.BytesIO()
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=42, leftMargin=42,
                            topMargin=46, bottomMargin=40, title="Pressure Decline Analysis")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#17324d"), spaceAfter=12))
    styles.add(ParagraphStyle(name="Cell", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="SmallReport", fontSize=9, leading=13, spaceAfter=7))
    story = []

    def para(text, style="SmallReport"):
        return Paragraph(escape(str(text)), styles[style])

    def title(number, text):
        story.extend([para(f"PRESSURE DECLINE ANALYSIS / {number:02d}", "SmallReport"), para(text, "ReportTitle")])

    def table(frame, widths=None):
        def fmt(v):
            if isinstance(v, (float, np.floating)):
                return f"{v:,.2f}" if np.isfinite(v) else "N/A"
            return str(v)
        cells = [[para(c, "Cell") for c in frame.columns]]
        cells += [[para(fmt(v), "Cell") for v in row] for row in frame.itertuples(index=False, name=None)]
        t = Table(cells, colWidths=widths or [735 / len(frame.columns)] * len(frame.columns), repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe7f1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#94a3b8")),
        ]))
        story.extend([t, Spacer(1, 12)])

    import pandas as pd
    tables = result_tables(results)
    forecast = tables["Forecast to Saturation Pressure"]
    title(1, "Executive Summary")
    latest = history.sort_values("date").iloc[-1]
    summary = {
        "Well / series": metadata.get("well", "All data"), "Analysis date": timestamp,
        "Pressure observations": len(history), "Production-history period": f"{date_text(daily['date'].min())} to {date_text(daily['date'].max())}",
        "Latest reservoir pressure, psi": latest["pressure_psi"], "Latest production cumulative, bbl": daily["cum_bbl"].iloc[-1],
        "Saturation pressure, psi": psat, "Enabled trends": len(results),
    }
    table(pd.DataFrame({"Parameter": summary.keys(), "Value": summary.values()}), [250, 485])
    table(forecast[["Trend", "Time decline, psi/day", "Cum decline, psi/1,000 bbl", "Cum months", "Cum Psat date"]])
    story.append(para("Alternative engineering interpretations; these are not statistical P10/P50/P90 cases. N/A means no valid forecast. Full status details appear on page 6."))
    story.append(PageBreak())
    title(2, "Pressure History")
    story.append(para("Diamonds identify the shared start/end selections. Dashed lines show each independent time forecast. Reference: " + results[0].forecast["reference"] + "."))
    story.append(chart_image(history, daily, results, psat, "time"))
    story.append(PageBreak())
    title(3, "Production Context")
    story.append(para("Shading marks selected trend intervals; overlaps are allowed. Missing calendar days retain the zero-rate assumption."))
    story.append(chart_image(history, daily, results, psat, "production"))
    story.append(PageBreak())
    title(4, "Pressure vs Cumulative Production")
    story.append(para("The selected slope determines oil required to reach Psat. The interval-average rate converts that oil requirement to time. Dashed lines use the stated forecast reference."))
    story.append(chart_image(history, daily, results, psat, "cumulative"))
    story.append(PageBreak())
    title(5, "Decline Results")
    story.append(para("Pressure Decline vs Time", "Heading2"))
    table(tables["Pressure Decline vs Time"])
    story.append(para("Pressure Decline vs Cumulative Production", "Heading2"))
    table(tables["Pressure Decline vs Cumulative Production"])
    for r in results:
        if r.issues:
            story.append(para(r.selection.name + ": " + " ".join(r.issues)))
    story.append(PageBreak())
    title(6, "Forecast to Saturation Pressure")
    # Split the wide comparison into two readable tables with the same trend keys.
    table(forecast[["Trend", "Time decline, psi/day", "Cum decline, psi/1,000 bbl", "Cum at Psat, bbl", "Incremental oil, bbl", "Time months", "Time Psat date", "Cum months", "Cum Psat date"]])
    table(forecast[["Trend", "Reference date", "Time status", "Cum status"]], [70, 115, 275, 275])
    story.append(chart_image(history, daily, results, psat, "timeline"))
    story.append(PageBreak())
    title(7, "Methodology & Assumptions")
    notes = [
        "Pressure source: " + metadata.get("pressure_source", "Uploaded pressure table"),
        "Production source: " + metadata.get("production_source", "Uploaded production table"),
        "Uploaded rate unit: " + metadata.get("rate_unit", "bbl/day") + "; all calculations use bbl and days.",
        CUMULATIVE_NOTE,
        "Missing dates are expanded as zero-rate days, an assumption rather than confirmation of shut-in. No rate interpolation is applied. Same-day production is included; pressure dates use the latest production date at or before that date.",
        "Linear decline: delta P = P start - P end; delta t is actual calendar days; Dt = delta P / delta t. Month = 30 days; year = 365 days.",
        "Cumulative decline: delta Np = Np end - Np start; DNp = delta P / delta Np. The interval-average rate is delta Np / delta t (production after the start date through the end date).",
        f"Psat = {psat:,.2f} psi. Forecast reference: {results[0].forecast['reference']}. Time to Psat = (P ref - Psat) / Dt. Oil to Psat = (P ref - Psat) / DNp. Np at Psat = Np ref + oil to Psat.",
        "Cumulative forecast time = oil to Psat / interval-average rate. With this rate basis and the same pressure reference, time-based and cumulative-based dates are algebraically equal. Production-rate assumptions do not alter the cumulative slope.",
        "Flat/increasing pressure, zero elapsed time, or non-increasing/missing cumulative production cannot supply the corresponding declining extrapolation. Already reached means pressure is at or below Psat at the reference measurement; it is not an inferred historical crossing date.",
    ]
    for note in notes:
        story.append(para(note))
    for r in results:
        story.append(para(f"{r.selection.name}: {date_text(r.metrics['start_date'])} to {date_text(r.metrics['end_date'])}; {r.selection.mode}; forecast reference {date_text(r.forecast['last_date'])}."))
    story.append(para(DISCLAIMER))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.line(42, 32, 800, 32)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(42, 20, "Pressure Decline Analysis | Generated " + timestamp)
        canvas.drawRightString(800, 20, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
