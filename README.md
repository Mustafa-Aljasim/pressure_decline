# Pressure Decline Calculator

Install dependencies and run from this directory:

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```

This app is built from the logic in `Pressure_Decline_calculation.xlsx`, but it adds the workflow that the workbook is missing:

- upload a pressure table and a daily production table
- calculate cumulative production from daily rates
- align pressure points to cumulative production
- define Trend 1 and optionally enable Trend 2 and Trend 3
- select each interval from endpoint lists or either interactive pressure plot
- fall back to manual point entry when needed
- calculate decline by time and decline by cumulative production
- compare independent time and cumulative forecasts to saturation pressure
- prepare and download a seven-page engineering PDF, or export all trend results as CSV
- download an Excel workbook containing the exact pressure-plot history, selected trend points, forecast-to-Psat points, production history, and summary tables

Notes:

- the original workbook is a manual calculator and references an external workbook for source data
- cumulative production sums daily volumes (daily rate × 1 day), including production through each pressure measurement date; no endpoint averaging or trapezoidal integration is used for cumulative production
- missing calendar dates retain the existing zero-rate assumption; rates are not interpolated
- each trend uses one interval for both analyses; overlapping intervals are allowed
- forecasts default to the latest measured pressure; select "Selected interval end" to extend each selected line directly to Psat
- time decline uses actual elapsed days; months are 30 days and years are 365 days
- cumulative forecast oil is determined by the pressure/cumulative slope; interval-average production (cumulative increment / elapsed days) converts oil to time. Under this basis, the time and cumulative forecast dates coincide for the same reference
- manual overrides are scoped to each trend and identified in exports; they do not change the uploaded production history
- invalid slopes show a status instead of a forecast date; trends are engineering alternatives, not probabilistic cases
- prepare the PDF after reviewing the comparison; changing the analysis invalidates the prepared download

`trend_analysis.py` is the shared calculation engine. UI plots, PDF charts, tables and CSV consume its results. `prepare_daily_production` in `app.py` is the only cumulative-production calculation.

Run the regression checks from this directory:

```powershell
python -m unittest discover -s tests -v
```
