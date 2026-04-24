# Pressure Decline Calculator

Run from the repo root:

```powershell
streamlit run pressure_decline_app/app.py
```

This app is built from the logic in `Pressure_Decline_calculation.xlsx`, but it adds the workflow that the workbook is missing:

- upload a pressure table and a daily production table
- calculate cumulative production from daily rates
- align pressure points to cumulative production
- pick any two points from interactive plots
- fall back to manual point entry when needed
- calculate decline by time and decline by cumulative production
- estimate months and forecast date to a target or saturation pressure

Notes:

- the original workbook is a manual calculator and references an external workbook for source data
- the cumulative method in this app preserves the workbook’s endpoint-rate averaging, while also showing the interval-average rate for reference
