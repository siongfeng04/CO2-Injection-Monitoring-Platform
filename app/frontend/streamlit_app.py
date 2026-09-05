import streamlit as st
import requests
import os
from requests.exceptions import RequestException
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io

st.set_page_config(page_title="CCS Digital Twin", layout="wide")

st.title("CCS Digital Twin — Injection Monitoring")

# Backend configuration: set BACKEND_URL to an absolute URL (e.g. http://localhost:8000).
# Python `requests` requires a full URL (scheme + host). Default to localhost for
# local development. To point to another server set the `BACKEND_URL` env var.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

def api_url(path: str) -> str:
    return BACKEND_URL.rstrip("/") + path

def api_get(path: str, params=None, timeout=30):
    try:
        url = api_url(path)
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except RequestException as e:
        st.error(f"API request failed: {e}")
        return None

def api_post(path: str, json=None, params=None, timeout=30):
    try:
        url = api_url(path)
        resp = requests.post(url, json=json, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except RequestException as e:
        st.error(f"API request failed: {e}")
        return None


# Excel helper: detect earliest and latest dates from the Dataset_Test sheet
def get_excel_date_range(file_path="data/excel/combined_co2_data_only_file.xls", sheet_name="Dataset_Test", col_name="Date & Time"):
    try:
        df_dates = pd.read_excel(file_path, sheet_name=sheet_name, usecols=[col_name], engine="xlrd")
        dates = pd.to_datetime(df_dates[col_name], errors="coerce")
        dates = dates.dropna()
        if dates.empty:
            return None, None
        return dates.min().date().isoformat(), dates.max().date().isoformat()
    except Exception:
        return None, None

# Excel helper: get current data at a specific timestamp
def get_current_data(file_path="data/excel/combined_co2_data_only_file.xls", sheet_name="Dataset_Test", timestamp="2009-09-25 07:42:45"):
    try:
        target = pd.to_datetime(timestamp)
        target = pd.to_datetime(timestamp)
        response = api_get(
            "/api/dashboard/metrics",
            params={"start": target.isoformat(), "end": target.isoformat()},
        )
        if not response or not response.get("timeseries"):
            return None

        row = response["timeseries"][-1]
        return {
            "timestamp": pd.to_datetime(row["timestamp"]),
            "surface_temp": row.get("surface_temp"),
            "surface_psi": row.get("surface_psi"),
            "annulus_psi": row.get("annulus_psi"),
        }
    except Exception as e:
        st.error(f"Error reading Excel data: {e}")
        return None

# Power BI-style interactive metric card
def metric_card(label: str, value: float, unit: str = "", color: str = "#0078D4", icon: str = "📊", 
                min_val: float = None, max_val: float = None, trend: float = None):
    """Create an interactive Power BI-style metric card"""
    
    # Format value with 2 decimal places
    formatted_value = f"{value:.2f}" if isinstance(value, (int, float)) else "N/A"
    
    # Determine trend emoji and color
    trend_indicator = ""
    trend_color = "#28A745"  # Green
    if trend is not None:
        if trend > 0:
            trend_indicator = f"📈 +{trend:.1f}%"
            trend_color = "#28A745"  # Green
        elif trend < 0:
            trend_indicator = f"📉 {trend:.1f}%"
            trend_color = "#DC3545"  # Red
    
    # Create custom HTML for the card using st.container
    with st.container(border=True):
        col_content, col_icon = st.columns([5, 1])
        
        with col_content:
            st.markdown(f"<p style='font-size: 11px; color: #666; text-transform: uppercase; font-weight: 600; margin: 0;'>{label}</p>", unsafe_allow_html=True)
            
            st.markdown(f"""
            <div style='display: flex; align-items: baseline; margin: 10px 0 0 0;'>
                <h2 style='margin: 0; font-size: 28px; font-weight: 700; color: {color};'>{formatted_value}</h2>
                <span style='margin-left: 8px; font-size: 14px; color: #666; font-weight: 500;'>{unit}</span>
            </div>
            """, unsafe_allow_html=True)
            
            if trend_indicator:
                st.markdown(f"<p style='margin: 8px 0 0 0; font-size: 12px; color: {trend_color}; font-weight: 600;'>{trend_indicator}</p>", unsafe_allow_html=True)
            
            if min_val is not None and max_val is not None:
                st.markdown(f"<p style='margin: 8px 0 0 0; font-size: 10px; color: #999;'>Range: {min_val:.1f} - {max_val:.1f} {unit}</p>", unsafe_allow_html=True)
        
        with col_icon:
            st.markdown(f"<p style='font-size: 36px; margin: 0; text-align: center;'>{icon}</p>", unsafe_allow_html=True)


def toggle_flow_unit():
    current_unit = st.session_state.get("flow_unit", "flow_bpm")
    st.session_state["flow_unit"] = "flow_gpm" if current_unit == "flow_bpm" else "flow_bpm"

# Sidebar navigation (vertical only)
get_qs = getattr(st, "experimental_get_query_params", None)
set_qs = getattr(st, "experimental_set_query_params", None)
default_page = "Overview"
if callable(get_qs):
    params = get_qs()
    default_page = params.get("page", [default_page])[0]
else:
    if "page" in st.session_state:
        default_page = st.session_state["page"]

nav_options = ["Overview", "Prediction", "Anomaly Detection", "SEGY Analysis"]
try:
    default_index = nav_options.index(default_page)
except Exception:
    default_index = 0
# Use a selectbox as a compact menu in the sidebar
page = st.sidebar.selectbox("Menu", nav_options, index=default_index)
st.session_state["page"] = page
if callable(set_qs):
    set_qs(page=page)

st.info("Using existing Excel source: data/excel/combined_co2_data_only_file.xls")
if st.button("Reload data from Excel"):
    # clear cached session data so UI reloads from excel source on next actions
    for k in ["metrics", "anomalies", "forecast", "simulation"]:
        if k in st.session_state:
            del st.session_state[k]
    st.success("Cleared session cache — use Load Metrics / Run Forecast to reload from Excel")

col1, col2 = st.columns([1, 3])

if page == "Overview":
    st.header("Dashboard")
    
    # Get and display current data
    current_data = get_current_data()
    if current_data:
        # Display update timestamp
        update_time = current_data["timestamp"].strftime("%d/%m/%Y %I:%M:%S %p")
        st.info(f"📊 Dashboard updated at {update_time}")
        
        # Display metric cards with Power BI style
        st.subheader("Current Status")
        
        # Read Excel to get historical data for trends
        try:
            df = pd.read_excel("data/excel/combined_co2_data_only_file.xls", sheet_name="Dataset_Test", engine="xlrd")
            df['Date & Time'] = pd.to_datetime(df['Date & Time'])
            
            # Calculate trends (% change from average of last 10 records vs current)
            current_idx = len(df) - 1
            start_idx = max(0, current_idx - 10)
            
            if current_idx > start_idx:
                prev_avg_temp = df['Surface Temp.'].iloc[start_idx:current_idx].mean()
                prev_avg_psi = df['Surface PSI'].iloc[start_idx:current_idx].mean()
                prev_avg_annulus = df['Annulus PSI'].iloc[start_idx:current_idx].mean()
                
                trend_temp = ((current_data['surface_temp'] - prev_avg_temp) / prev_avg_temp * 100) if prev_avg_temp else 0
                trend_psi = ((current_data['surface_psi'] - prev_avg_psi) / prev_avg_psi * 100) if prev_avg_psi else 0
                trend_annulus = ((current_data['annulus_psi'] - prev_avg_annulus) / prev_avg_annulus * 100) if prev_avg_annulus else 0
            else:
                trend_temp = trend_psi = trend_annulus = 0
            
            # Get min/max for range display
            temp_min, temp_max = df['Surface Temp.'].min(), df['Surface Temp.'].max()
            psi_min, psi_max = df['Surface PSI'].min(), df['Surface PSI'].max()
            annulus_min, annulus_max = df['Annulus PSI'].min(), df['Annulus PSI'].max()
        except:
            trend_temp = trend_psi = trend_annulus = 0
            temp_min = temp_max = psi_min = psi_max = annulus_min = annulus_max = 0
        
        # Create three columns for metric cards
        card_col1, card_col2, card_col3 = st.columns(3)
        
        with card_col1:
            metric_card(
                label="Surface Temperature",
                value=current_data['surface_temp'] if current_data['surface_temp'] else 0,
                unit="°F",
                color="#FF6B6B",
                icon="🌡️",
                trend=trend_temp,
                min_val=temp_min,
                max_val=temp_max
            )
        
        with card_col2:
            metric_card(
                label="Surface Pressure",
                value=current_data['surface_psi'] if current_data['surface_psi'] else 0,
                unit="PSI",
                color="#0078D4",
                icon="📊",
                trend=trend_psi,
                min_val=psi_min,
                max_val=psi_max
            )
        
        with card_col3:
            metric_card(
                label="Annulus Pressure",
                value=current_data['annulus_psi'] if current_data['annulus_psi'] else 0,
                unit="PSI",
                color="#20C997",
                icon="⚙️",
                trend=trend_annulus,
                min_val=annulus_min,
                max_val=annulus_max
            )
    
    # Display KPIs and timeseries
    st.subheader("Analytics")

    subset_start, subset_end = get_excel_date_range()
    if subset_start and subset_end:
        if "flow_unit" not in st.session_state:
            st.session_state["flow_unit"] = "flow_bpm"
        st.button(
            "Switch to GPM" if st.session_state["flow_unit"] == "flow_bpm" else "Switch to BPM",
            key="flow_unit_toggle",
            on_click=toggle_flow_unit,
        )

        with st.spinner("Loading flow data..."):
            subset_response = api_get(
                "/api/dashboard/subset-flow",
                params={
                    "start": f"{subset_start}T00:00:00",
                    "end": f"{subset_end}T23:59:59",
                },
                timeout=30,
            )
        subset_df = pd.DataFrame((subset_response or {}).get("data", []))
        if not subset_df.empty:
            subset_df["date_time"] = pd.to_datetime(subset_df["date_time"])
            flow_unit = st.session_state["flow_unit"]
            flow_label = "Flow (GPM)" if flow_unit == "flow_gpm" else "Flow (BPM)"
            flow_fig = px.line(
                subset_df,
                x="date_time",
                y=flow_unit,
                title=f"Flow Rate (Subset Data) - {flow_label.split('(')[-1].rstrip(')')}",
                labels={"date_time": "Date and time", flow_unit: flow_label},
            )
            st.plotly_chart(flow_fig, use_container_width=True)

            surface_psi_fig = px.line(
                subset_df,
                x="date_time",
                y="surface_psi",
                title="Surface Pressure (Subset Data)",
                labels={"date_time": "Date and time", "surface_psi": "Surface PSI"},
            )
            st.plotly_chart(surface_psi_fig, use_container_width=True)

            surface_temperature_fig = px.line(
                subset_df,
                x="date_time",
                y="surface_temperature",
                title="Surface Temperature (Subset Data)",
                labels={"date_time": "Date and time", "surface_temperature": "Surface Temperature"},
            )
            st.plotly_chart(surface_temperature_fig, use_container_width=True)
        else:
            st.info("No subset flow data is available for this period.")
    
    # Only load metrics on demand with a button
    if st.button("Load Detailed Metrics"):
        start, end = get_excel_date_range()
        if start and end:
            with st.spinner("Loading metrics..."):
                params = {"start": f"{start}T00:00:00", "end": f"{end}T23:59:59"}
                resp = api_get("/api/dashboard/metrics", params=params, timeout=30)
                if resp is not None:
                    st.session_state["metrics"] = resp
        else:
            st.warning("Could not detect date range from Excel.")
    
    metrics = st.session_state.get("metrics")
    if metrics:
        kpis = metrics.get("kpis", {})
        st.subheader("KPIs")
        st.write(kpis)

        ts = pd.DataFrame(metrics.get("timeseries", []))
        if not ts.empty:
            ts["timestamp"] = pd.to_datetime(ts["timestamp"])
            fig = px.line(ts, x="timestamp", y=[c for c in ["bhp","bht","injection_rate","pump_speed"] if c in ts.columns], title="Time Series")
            st.plotly_chart(fig, use_container_width=True)

elif page == "Prediction":
    st.header("Bottom-Hole Conditions")
    prediction_start, prediction_end = get_excel_date_range()
    if prediction_start and prediction_end:
        with st.spinner("Loading fulldata charts..."):
            prediction_response = api_get(
                "/api/dashboard/metrics",
                params={
                    "start": f"{prediction_start}T00:00:00",
                    "end": f"{prediction_end}T23:59:59",
                },
                timeout=30,
            )

        prediction_df = pd.DataFrame((prediction_response or {}).get("timeseries", []))
        if not prediction_df.empty:
            prediction_df["date_time"] = pd.to_datetime(prediction_df["timestamp"])
            chart_col1, chart_col2 = st.columns(2)

            with chart_col1:
                corrected_pressure_fig = px.line(
                    prediction_df,
                    x="date_time",
                    y="corrected_bottom_hole_pressure",
                    title="Corrected Bottom-Hole Pressure (fulldata)",
                    labels={
                        "date_time": "Date and time",
                        "corrected_bottom_hole_pressure": "Corrected pressure",
                    },
                )
                st.plotly_chart(corrected_pressure_fig, use_container_width=True)

            with chart_col2:
                bottom_temperature_fig = px.line(
                    prediction_df,
                    x="date_time",
                    y="bht",
                    title="Bottom-Hole Temperature (fulldata)",
                    labels={"date_time": "Date and time", "bht": "Temperature"},
                )
                st.plotly_chart(bottom_temperature_fig, use_container_width=True)
        else:
            st.info("No fulldata records are available for this period.")

    prediction_controls, prediction_results = st.columns([1, 1])

    with prediction_controls:
        st.header("Predictive - Pressure Forecast")
        # No well selection: train using Excel-source aggregated data or default behavior
        if st.button("Train Pressure Model"):
            resp = api_post("/api/train-pressure", params={"use_excel": True})
            if resp is not None:
                st.success("Model trained")
                st.write(resp.get("metrics"))

        # Default forecast start date from Excel range if available
        s_start, s_end = get_excel_date_range()
        if s_start:
            try:
                default_start = pd.to_datetime(s_start).date()
            except Exception:
                default_start = None
        else:
            default_start = None

        start_date = st.date_input("Forecast start date", value=default_start)
        days = st.number_input("Days to forecast", min_value=1, max_value=365, value=14)
        inj_rate = st.number_input("Assumed injection rate (what-if)", value=0.0)
        if st.button("Run Forecast"):
            params = {"start": start_date.isoformat(), "days": int(days), "injection_rate": float(inj_rate), "use_excel": True}
            resp = api_get("/api/predict-pressure", params=params)
            if resp is not None:
                st.session_state["forecast"] = resp.get("predictions")

        # Auto-run a default forecast once per session if not present and default_start available
        if "forecast" not in st.session_state and default_start is not None:
            params = {"start": default_start.isoformat(), "days": int(days), "injection_rate": float(inj_rate), "use_excel": True}
            resp = api_get("/api/predict-pressure", params=params)
            if resp is not None:
                st.session_state["forecast"] = resp.get("predictions")

        st.header("What-if Simulator")
        st.write("Upload a CSV with columns `date,injection_rate` or enter manual schedule below.")
        uploaded_sched = st.file_uploader("Upload schedule CSV", type=["csv"], key="sched")
        manual_date = st.date_input("Manual date", [])
        manual_rate = st.number_input("Manual injection rate", value=0.0, key="manual_rate")
        if uploaded_sched is not None:
            sched_df = pd.read_csv(uploaded_sched)
            schedule = sched_df.to_dict(orient="records")
        else:
            schedule = []
            if len(manual_date) == 2:
                schedule = [{"date": manual_date[0].isoformat(), "injection_rate": manual_rate}, {"date": manual_date[1].isoformat(), "injection_rate": manual_rate}]

        if st.button("Run What-if"):
            payload = {"schedule": schedule}
            resp = api_post("/api/simulate-whatif", json=payload)
            if resp is not None:
                st.session_state["simulation"] = resp.get("simulation")

    with prediction_results:
        st.header("Forecast Results")
        forecast = st.session_state.get("forecast")
        if forecast:
            fdf = pd.DataFrame(forecast)
            fdf["timestamp"] = pd.to_datetime(fdf["timestamp"])
            fig = px.line(fdf, x="timestamp", y="predicted_bhp", title="Predicted BHP")
            st.plotly_chart(fig, use_container_width=True)

        sim = st.session_state.get("simulation")
        if sim:
            sdf = pd.DataFrame(sim)
            sdf["timestamp"] = pd.to_datetime(sdf["timestamp"])
            fig2 = px.line(sdf, x="timestamp", y="predicted_bhp", title="What-if Predicted BHP")
            st.plotly_chart(fig2, use_container_width=True)

elif page == "Anomaly Detection":
    with col1:
        st.header("Anomaly Detection Filters")
        # Auto-detect date range from Excel
        start, end = get_excel_date_range()
        if start and end:
            st.info(f"Date range detected: {start} → {end}")
            if st.button("Load Anomalies"):
                with st.spinner("Detecting anomalies..."):
                    params = {"start": start, "end": end, "use_excel": True}
                    resp = api_get("/api/anomalies", params=params, timeout=30)
                    if resp is not None:
                        st.session_state["anomalies"] = resp.get("anomalies")
        else:
            st.warning("Could not detect date range from Excel. Please ensure the file and sheet/column exist.")

    with col2:
        st.header("Anomalies")
        anomalies = st.session_state.get("anomalies")
        if anomalies:
            a_df = pd.DataFrame(anomalies)
            if not a_df.empty:
                a_df["timestamp"] = pd.to_datetime(a_df["timestamp"])
                st.write(a_df)
                fig2 = px.scatter(a_df, x="timestamp", y="bhp", color="anomaly", title="Anomaly timeline")
                st.plotly_chart(fig2, use_container_width=True)

elif page == "SEGY Analysis":
    import os
    with col1:
        st.header("SEGY Analysis")
        segy_dir = "data/segy"
        segy_files = []
        try:
            segy_files = [f for f in os.listdir(segy_dir) if f.lower().endswith('.sgy') or f.lower().endswith('.segy')]
        except Exception:
            segy_files = []
        sel = st.selectbox("SEGY file", options=segy_files)
        if st.button("Analyze SEGY") and sel:
            st.info(f"Placeholder: run SEGY analysis for {sel}.")
            st.write("Implement SEGY analysis backend endpoint and visualization here.")

        st.markdown("**Note:** SEGY analysis requires `segyio` and domain-specific visualizations. This is a placeholder page.")
