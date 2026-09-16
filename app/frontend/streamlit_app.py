import streamlit as st
import requests
import os
from requests.exceptions import RequestException
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import numpy as np
import segyio
from pathlib import Path

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
        detail = None
        if getattr(e, "response", None) is not None:
            try:
                detail = e.response.json().get("detail")
            except ValueError:
                detail = None
        st.error(f"API request failed: {detail or e}")
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
            "flow_bpm": row.get("flow_bpm"),
            "bhp": row.get("bhp"),
            "corrected_bottom_hole_pressure": row.get("corrected_bottom_hole_pressure"),
            "bht": row.get("bht"),
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


def render_digital_twin(current_data: dict, flow_bpm=None):
    def display_value(value, unit="", decimals=0):
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):,.{decimals}f} {unit}".strip()

    surface_psi = display_value(current_data.get("surface_psi"), "PSI")
    surface_temp = display_value(current_data.get("surface_temp"), "°F", 1)
    annulus_psi = display_value(current_data.get("annulus_psi"), "PSI")
    bottom_pressure = display_value(
        current_data.get("corrected_bottom_hole_pressure") or current_data.get("bhp"), "PSI"
    )
    bottom_temperature = display_value(current_data.get("bht"), "°C", 1)
    flow = display_value(flow_bpm, "BPM", 2)

    st.markdown(
        f"""
        <style>
        .digital-twin {{
            position: relative; overflow: hidden; min-height: 430px; margin: .35rem 0 1.25rem;
            border: 1px solid #1c3345; border-radius: 12px; background: #060b1e;
            color: #d9e9f2; font-family: 'IBM Plex Mono', 'Cascadia Code', monospace;
        }}
        .digital-twin::before {{
            content: ''; position: absolute; inset: 0; opacity: .36;
            background: linear-gradient(rgba(65, 105, 135, .12) 1px, transparent 1px),
                linear-gradient(90deg, rgba(65, 105, 135, .10) 1px, transparent 1px);
            background-size: 32px 32px; pointer-events: none;
        }}
        .twin-header, .twin-footer, .twin-stage {{ position: relative; z-index: 1; }}
        .twin-header {{ display: flex; align-items: center; justify-content: space-between; padding: 1rem 1.25rem .65rem; }}
        .twin-title {{ color: #edf4ff; font: 700 1.05rem 'IBM Plex Sans', sans-serif; }}
        .twin-title span {{ color: #15d6c9; }}
        .twin-flow {{ padding: .42rem .75rem; border: 1px solid #233c59; border-radius: 6px; color: #a9c8ef; background: #0c1930; font-size: .78rem; }}
        .twin-stage {{ height: 325px; margin: 0 1.25rem; position: relative; }}
        .twin-surface-line {{ position: absolute; top: 49px; left: 18%; right: 20%; height: 5px; border-radius: 5px; background: #596b86; box-shadow: 0 0 0 1px #263b56; }}
        .twin-label {{ position: absolute; color: #7b9abc; font-size: .68rem; letter-spacing: .03em; }}
        .twin-surface {{ top: 30px; left: 18%; }}
        .twin-formations {{ position: absolute; top: 51px; bottom: 0; left: 20%; width: 60%; background: rgba(25, 35, 60, .7); }}
        .twin-overburden {{ height: 36%; padding: 1.6rem .7rem; color: #637da4; font-size: .7rem; }}
        .twin-caprock {{ height: 22%; padding: .9rem .7rem; border-top: 1px dashed #bfc9d8; border-bottom: 1px dashed #bfc9d8; background: rgba(82, 99, 126, .62); color: #f1f4fc; font-size: .7rem; }}
        .twin-caprock b, .twin-target b {{ display: block; margin-bottom: .35rem; color: #f7fbff; }}
        .twin-target {{ height: 42%; padding: 1.15rem .7rem; background: rgba(0, 70, 78, .75); color: #98f8ed; font-size: .7rem; }}
        .twin-well {{ position: absolute; top: 18px; bottom: -4px; left: 48%; width: 42px; border-left: 4px solid #97a7be; border-right: 4px solid #97a7be; background: linear-gradient(90deg, #07867f, #12b9a9 48%, #087d78); box-shadow: 0 0 18px rgba(11, 214, 194, .2); }}
        .twin-well::before {{ content: ''; position: absolute; top: -2px; left: -18px; width: 70px; height: 31px; border: 2px solid #8293aa; border-radius: 4px; background: #4b5c73; }}
        .twin-well::after {{ content: ''; position: absolute; top: -11px; left: 12px; width: 14px; height: 14px; border-radius: 50%; background: #10b9ad; }}
        .twin-sensor {{ position: absolute; left: 17px; width: 7px; height: 7px; border-radius: 50%; background: #d9f5ef; }}
        .sensor-one {{ top: 66px; }} .sensor-two {{ top: 136px; }} .sensor-three {{ top: 206px; }}
        .twin-callout {{ position: absolute; padding: .55rem .65rem; border: 1px solid #10d5ce; border-radius: 6px; background: #062b31; color: #75fff4; font-size: .68rem; line-height: 1.45; }}
        .twin-surface-callout {{ top: 25px; left: 56%; }}
        .twin-bottom-callout {{ right: 14%; bottom: 8px; }}
        .twin-annulus {{ top: 111px; left: 23%; color: #f0a62b; }}
        .twin-annulus::before {{ content: ''; position: absolute; top: 50%; right: -45px; width: 42px; border-top: 2px dotted #f0a62b; }}
        .twin-footer {{ display: flex; justify-content: space-between; margin: 0 1.25rem; padding: .8rem .35rem 1rem; border-top: 1px solid #1d3046; color: #b4c5db; font: .9rem 'IBM Plex Sans', sans-serif; }}
        .twin-footer strong {{ color: #14d5ca; }}
        @media (max-width: 700px) {{
            .twin-header {{ align-items: flex-start; gap: .7rem; flex-direction: column; }}
            .twin-stage {{ margin: 0 .5rem; }} .twin-formations {{ left: 8%; width: 84%; }}
            .twin-surface {{ left: 8%; }} .twin-surface-line {{ left: 8%; right: 8%; }}
            .twin-surface-callout {{ left: 55%; }} .twin-annulus {{ left: 5%; }} .twin-bottom-callout {{ right: 3%; }}
            .twin-footer {{ margin: 0 .75rem; font-size: .75rem; }}
        }}
        </style>
        <div class="digital-twin">
            <div class="twin-header">
                <div class="twin-title"><span>◉</span>&nbsp; Subsurface profile <span>(TVD: 7,450 ft)</span></div>
                <div class="twin-flow">Flow: {flow}</div>
            </div>
            <div class="twin-stage">
                <div class="twin-surface-line"></div><div class="twin-label twin-surface">SURFACE&nbsp; (0 ft)</div>
                <div class="twin-formations">
                    <div class="twin-overburden">Overburden Shales &amp; Sands</div>
                    <div class="twin-caprock"><b>PRIMARY CAPROCK SEAL (Eau Claire Shale)</b>Depth: 6,800 - 7,100 ft · P_break: 4,180 PSI</div>
                    <div class="twin-target"><b>TARGET SALINE FORMATION (Mount Simon Sandstone)</b>Porosity: 18.4% · Perm: 145 mD · Salinity: 120,000 ppm</div>
                </div>
                <div class="twin-well"><span class="twin-sensor sensor-one"></span><span class="twin-sensor sensor-two"></span><span class="twin-sensor sensor-three"></span></div>
                <div class="twin-label twin-annulus">A-Annulus: {annulus_psi}</div>
                <div class="twin-callout twin-surface-callout">P_surf: <b>{surface_psi}</b><br>T_surf: {surface_temp}</div>
                <div class="twin-callout twin-bottom-callout">BHP: <b>{bottom_pressure}</b><br>BHT: {bottom_temperature}</div>
            </div>
            <div class="twin-footer"><span>Hydrostatic Head: <strong>+1,582 PSI</strong></span><span>Fluid: <strong>Supercritical CO₂</strong></span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def toggle_flow_unit():
    current_unit = st.session_state.get("flow_unit", "flow_bpm")
    st.session_state["flow_unit"] = "flow_gpm" if current_unit == "flow_bpm" else "flow_bpm"


@st.cache_data(show_spinner=False)
def load_segy_file(file_path: str):
    """Load a SEGY gather and return a compact, serializable analysis bundle."""
    with segyio.open(file_path, "r", ignore_geometry=True) as segy_file:
        trace_count = segy_file.tracecount
        samples = np.asarray(segy_file.samples, dtype=float)
        traces = np.asarray(segy_file.trace.raw[:trace_count], dtype=np.float32)
        traces = np.nan_to_num(traces, nan=0.0, posinf=0.0, neginf=0.0)
        robust_limit = float(np.percentile(np.abs(traces), 99.9) * 10)
        if robust_limit > 0:
            traces = np.clip(traces, -robust_limit, robust_limit)
        group_x = np.asarray(segy_file.attributes(segyio.TraceField.GroupX)[:trace_count])
        group_y = np.asarray(segy_file.attributes(segyio.TraceField.GroupY)[:trace_count])
        sample_interval_us = float(segyio.dt(segy_file))

    return {
        "traces": traces,
        "samples": samples,
        "sample_interval_us": sample_interval_us,
        "group_x": group_x,
        "group_y": group_y,
        "trace_count": trace_count,
    }


def apply_fft_bandpass(trace, sample_rate_hz, low_hz, high_hz):
    frequencies = np.fft.rfftfreq(trace.size, d=1.0 / sample_rate_hz)
    spectrum = np.fft.rfft(trace)
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    return np.fft.irfft(spectrum * mask, n=trace.size)


def get_fft_spectrum(trace, sample_rate_hz):
    centered = trace - np.mean(trace)
    frequencies = np.fft.rfftfreq(centered.size, d=1.0 / sample_rate_hz)
    amplitude = np.abs(np.fft.rfft(centered)) / max(centered.size, 1)
    return frequencies, amplitude


def build_segy_file_index(segy_dir):
    files = {}
    for path in Path(segy_dir).glob("event_*_*_strain_geom.sgy"):
        parts = path.stem.split("_")
        if len(parts) >= 5:
            files[(int(parts[1]), f"CRC-{parts[2]}")] = path
    return files


def style_segy_figure(fig, height=460):
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=52, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0b1720",
        font=dict(family="IBM Plex Sans, sans-serif", color="#c5d2d8"),
        title=dict(x=0.02, xanchor="left", font=dict(size=16, color="#edf5f4")),
        hoverlabel=dict(bgcolor="#13242d", font_size=12),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, color="#90a5ad")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(164, 194, 201, 0.12)", zeroline=False, color="#90a5ad")
    return fig


EVENT_CATALOG = {
    2: {"date": "2020-10-29 02:29", "easting": 658631.5, "northing": 5733858, "depth": 1490, "magnitude": -1.0, "corner": 90},
    11: {"date": "2021-02-25 20:23", "easting": 658804.5, "northing": 5733873, "depth": 1510, "magnitude": None, "corner": None},
    12: {"date": "2021-02-25 22:10", "easting": 657879.3, "northing": 5733980, "depth": 1470, "magnitude": None, "corner": None},
    13: {"date": "2021-02-25 23:10", "easting": 657899, "northing": 5733950, "depth": 1470, "magnitude": None, "corner": None},
    4: {"date": "2021-01-30 16:55", "easting": 657999.1, "northing": 5733742, "depth": 1470, "magnitude": -1.1, "corner": 180},
    5: {"date": "2021-01-30 18:46", "easting": 657992.4, "northing": 5733723, "depth": 1470, "magnitude": -0.5, "corner": 180},
    6: {"date": "2021-02-06 10:41", "easting": 657979.2, "northing": 5733722, "depth": 1450, "magnitude": -0.7, "corner": 180},
    7: {"date": "2021-02-07 13:19", "easting": 657991.7, "northing": 5733721, "depth": 1450, "magnitude": -1.3, "corner": 130},
    8: {"date": "2021-02-07 14:20", "easting": 658016.3, "northing": 5733785, "depth": 1430, "magnitude": -1.5, "corner": 110},
    9: {"date": "2021-02-07 14:21", "easting": 658010.5, "northing": 5733768, "depth": 1450, "magnitude": -1.0, "corner": 150},
    10: {"date": "2021-02-07 15:48", "easting": 657999.4, "northing": 5733740, "depth": 1470, "magnitude": -1.5, "corner": 150},
    14: {"date": "2021-02-26 09:39", "easting": 657997, "northing": 5733742, "depth": 1470, "magnitude": -0.6, "corner": 180},
    16: {"date": "2021-03-16 01:54", "easting": 658013.6, "northing": 5733770, "depth": 1450, "magnitude": None, "corner": None},
    18: {"date": "2021-04-14 08:58", "easting": 658454.8, "northing": 5733845, "depth": 1470, "magnitude": None, "corner": None},
    20: {"date": "2021-06-13 05:11", "easting": 658633.5, "northing": 5734494, "depth": 1490, "magnitude": -0.3, "corner": 140},
    21: {"date": "2021-06-25 05:48", "easting": 658562.1, "northing": 5734460, "depth": 1450, "magnitude": 0.1, "corner": 140},
    24: {"date": "2021-11-06 23:35", "easting": 658347.3, "northing": 5733978, "depth": 1450, "magnitude": -1.0, "corner": 120},
}

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

nav_options = ["Overview", "Prediction", "Injection Optimization Simulator", "Anomaly Detection", "SEGY Analysis"]
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
    render_digital_twin(current_data or {})

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

            # Show the latest predicted parameters using the same status cards as Overview.
            prediction_df = prediction_df.sort_values("date_time")
            pressure_values = pd.to_numeric(
                prediction_df["corrected_bottom_hole_pressure"], errors="coerce"
            ).dropna()
            temperature_values = pd.to_numeric(prediction_df["bht"], errors="coerce").dropna()
            if not pressure_values.empty and not temperature_values.empty:
                latest_pressure = float(pressure_values.iloc[-1])
                latest_temperature = float(temperature_values.iloc[-1])
                pressure_previous = pressure_values.iloc[max(0, len(pressure_values) - 11):-1]
                temperature_previous = temperature_values.iloc[max(0, len(temperature_values) - 11):-1]
                pressure_average = pressure_previous.mean()
                temperature_average = temperature_previous.mean()
                pressure_trend = ((latest_pressure - pressure_average) / pressure_average * 100) if pressure_average else 0
                temperature_trend = ((latest_temperature - temperature_average) / temperature_average * 100) if temperature_average else 0

                st.subheader("Current Status")
                status_col1, status_col2 = st.columns(2)
                with status_col1:
                    metric_card(
                        label="Corrected Bottom-Hole Pressure",
                        value=latest_pressure,
                        unit="PSI",
                        color="#0078D4",
                        icon="📊",
                        trend=pressure_trend,
                        min_val=float(pressure_values.min()),
                        max_val=float(pressure_values.max()),
                    )
                with status_col2:
                    metric_card(
                        label="Bottom-Hole Temperature",
                        value=latest_temperature,
                        unit="°C",
                        color="#FF6B6B",
                        icon="🌡️",
                        trend=temperature_trend,
                        min_val=float(temperature_values.min()),
                        max_val=float(temperature_values.max()),
                    )

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

    st.header("Notebook Prediction Analysis")
    prediction_action_col, prediction_status_col = st.columns([1, 2])
    with prediction_action_col:
        if "prediction_analysis" not in st.session_state:
            with st.spinner("Training pressure and temperature models..."):
                analysis_response = api_get("/api/prediction", timeout=120)
            if analysis_response is not None:
                st.session_state["prediction_analysis"] = analysis_response
        if st.button("Import Full Data to PostgreSQL"):
            with st.spinner("Importing the Full sheet into fulldata..."):
                ingest_response = api_post("/api/ingest-fulldata", timeout=120)
            if ingest_response is not None:
                st.success(f"Imported {ingest_response.get('inserted', 0):,} rows")
    with prediction_status_col:
        prediction_analysis = st.session_state.get("prediction_analysis")
        if prediction_analysis:
            st.caption(
                f"Trained on {prediction_analysis.get('row_count', 0):,} active recording rows "
                "from PostgreSQL fulldata."
            )

    prediction_analysis = st.session_state.get("prediction_analysis")
    if prediction_analysis:
        for target_key, target_data in (
            ("pressure", prediction_analysis.get("pressure", {})),
            ("temperature", prediction_analysis.get("temperature", {})),
        ):
            st.subheader(target_data.get("label", target_key.title()))
            st.write(f"Selected model: **{target_data.get('best_model', 'Unavailable')}**")
            metrics_df = pd.DataFrame(target_data.get("metrics", {})).T
            if not metrics_df.empty:
                metrics_df.index.name = "Model"
                st.dataframe(metrics_df, use_container_width=True)

            test_df = pd.DataFrame(target_data.get("test_predictions", []))
            importance_df = pd.DataFrame(target_data.get("feature_importance", []))
            if test_df.empty:
                st.warning("No test predictions were returned for this target.")
                continue

            test_df["timestamp"] = pd.to_datetime(test_df["timestamp"])
            with st.expander("Prediction results table"):
                st.dataframe(test_df, use_container_width=True)
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                actual_predicted_fig = px.scatter(
                    test_df,
                    x="actual",
                    y="predicted",
                    title=f"{target_data.get('label')}: Actual vs Predicted",
                    labels={"actual": "Actual", "predicted": "Predicted"},
                )
                st.plotly_chart(actual_predicted_fig, use_container_width=True)
            with chart_col2:
                residual_fig = px.histogram(
                    test_df,
                    x="residual",
                    nbins=50,
                    title=f"{target_data.get('label')}: Residual Distribution",
                    labels={"residual": "Residual (actual - predicted)"},
                )
                st.plotly_chart(residual_fig, use_container_width=True)

            time_fig = px.line(
                test_df,
                x="timestamp",
                y=["actual", "predicted"],
                title=f"{target_data.get('label')}: Actual vs Predicted Over Time",
                labels={"value": target_data.get("label"), "timestamp": "Date and time"},
            )
            st.plotly_chart(time_fig, use_container_width=True)

            if not importance_df.empty:
                importance_fig = px.bar(
                    importance_df.sort_values("importance"),
                    x="importance",
                    y="feature",
                    orientation="h",
                    title=f"Feature Importance: {target_data.get('label')}",
                    labels={"importance": "Importance", "feature": "Feature"},
                )
                st.plotly_chart(importance_fig, use_container_width=True)

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

elif page == "Injection Optimization Simulator":
    st.header("Injection Optimization Simulator")
    st.write("Use the trained CBHP and BHT models to test operating limits before injection.")

    default_conditions_response = api_get("/api/injection-optimization/defaults", timeout=30)
    default_conditions = (default_conditions_response or {}).get("conditions") or {}
    if default_conditions:
        st.caption(f"Operating-condition defaults loaded from database row: {default_conditions.get('timestamp', 'latest')}")
    else:
        st.warning("No database row contains nonzero values for all operating-condition inputs. Using zero defaults.")

    mode_labels = {
        "Maximum Injection": "maximum_injection",
        "Safe Operation": "safe_operation",
        "Temperature Control": "temperature_control",
    }
    selected_mode = st.segmented_control("Optimization mode", list(mode_labels), default="Maximum Injection")
    mode = mode_labels[selected_mode]

    with st.container(border=True):
        st.subheader("Operating conditions")
        input_col1, input_col2, input_col3 = st.columns(3)
        with input_col1:
            surface_psi = st.number_input("Surface PSI", value=float(default_conditions.get("surface_psi", 0.0)), key="optimizer_surface_psi")
            annulus_psi = st.number_input("Annulus PSI", value=float(default_conditions.get("annulus_psi", 0.0)), key="optimizer_annulus_psi")
            pump_speed = st.number_input("Pump speed", value=float(default_conditions.get("pump_speed", 0.0)), key="optimizer_pump_speed")
        with input_col2:
            surface_temp = st.number_input("Surface temperature", value=float(default_conditions.get("surface_temp", 0.0)), key="optimizer_surface_temp")
            temperature_before_triplex = st.number_input("Temperature before Triplex", value=float(default_conditions.get("temperature_before_triplex", 0.0)), key="optimizer_triplex_temp")
        with input_col3:
            pressure_before_triplex = st.number_input("Pressure before Triplex", value=float(default_conditions.get("pressure_before_triplex", 0.0)), key="optimizer_triplex_pressure")
            flow_min = st.number_input("Search flow minimum (BPM)", min_value=0.0, value=0.0, key="optimizer_flow_min")
            flow_max = st.number_input("Search flow maximum (BPM)", min_value=0.01, value=100.0, key="optimizer_flow_max")
            flow_step = st.number_input("Search step (BPM)", min_value=0.01, value=1.0, key="optimizer_flow_step")

    with st.container(border=True):
        st.subheader("Safety target")
        target_col, action_col = st.columns([1, 2])
        with target_col:
            if mode == "maximum_injection":
                limit = st.number_input("Maximum allowable CBHP (psi)", value=2200.0, key="optimizer_cbhp_limit_maximum")
            elif mode == "safe_operation":
                limit = st.number_input("Maximum allowable CBHP (psi)", value=2200.0, key="optimizer_cbhp_limit_safe")
                safety_margin_pct = st.number_input(
                    "Target safety margin (%)",
                    min_value=0.0,
                    max_value=99.99,
                    value=10.0,
                    step=0.5,
                    key="optimizer_safety_margin",
                )
                st.caption(f"Safe operating limit: {limit * (1 - safety_margin_pct / 100):.2f} psi")
            else:
                limit = st.number_input("Maximum allowable BHT (°C)", value=95.0, key="optimizer_bht_limit")
        with action_col:
            st.caption("The optimizer evaluates the selected flow range using the existing Prediction models.")
            run_optimizer = st.button("Run optimization", type="primary", key="optimizer_run")

    if run_optimizer:
        if flow_max < flow_min:
            st.error("Search flow maximum must be greater than or equal to the minimum.")
        else:
            payload = {
                "mode": mode,
                "inputs": {
                    "surface_psi": surface_psi,
                    "annulus_psi": annulus_psi,
                    "pump_speed": pump_speed,
                    "surface_temp": surface_temp,
                    "temperature_before_triplex": temperature_before_triplex,
                    "pressure_before_triplex": pressure_before_triplex,
                },
                "flow_min": flow_min,
                "flow_max": flow_max,
                "flow_step": flow_step,
            }
            if mode in {"maximum_injection", "safe_operation"}:
                payload["cbhp_limit"] = limit
                if mode == "safe_operation":
                    payload["safety_margin_pct"] = safety_margin_pct
            else:
                payload["bht_limit"] = limit
            with st.spinner("Evaluating operating conditions..."):
                optimizer_response = api_post("/api/injection-optimization", json=payload, timeout=120)
            if optimizer_response is not None:
                st.session_state["optimizer_response"] = optimizer_response

    result = st.session_state.get("optimizer_response")
    if result and result.get("mode") == mode:
        if mode == "temperature_control" and not result.get("feasible", True):
            closest = result["closest_result"]
            st.warning(
                f"No flow in the selected range satisfies the BHT limit of {result['bht_limit']:.2f} °C. "
                f"The closest result is {closest['predicted_bht']:.2f} °C at {closest['flow_bpm']:.2f} BPM."
            )
            result_col1, result_col2 = st.columns(2)
            result_col1.metric("Closest flow", f"{closest['flow_bpm']:.2f} BPM")
            result_col2.metric("Closest predicted BHT", f"{closest['predicted_bht']:.2f} °C")
        elif mode == "maximum_injection":
            result_col1, result_col2, result_col3 = st.columns(3)
            result_col1.metric("Recommended flow", f"{result['recommended_flow_bpm']:.2f} BPM")
            result_col2.metric("Predicted CBHP", f"{result['predicted_cbhp']:.2f} psi")
            result_col3.metric("Predicted BHT", f"{result['predicted_bht']:.2f} °C")
        elif mode == "safe_operation":
            result_col1, result_col2, result_col3 = st.columns(3)
            result_col1.metric("Maximum safe flow", f"{result['recommended_flow_bpm']:.2f} BPM")
            result_col2.metric("Predicted CBHP", f"{result['predicted_cbhp']:.2f} psi")
            result_col3.metric("Remaining pressure margin", f"{result['remaining_pressure_margin']:.2f} psi")
            st.caption(
                f"Safe operating limit: {result['safe_operating_limit']:.2f} psi "
                f"({result['safety_margin_pct']:.2f}% below the {result['maximum_allowable_cbhp']:.2f} psi maximum)."
            )
        else:
            acceptable_df = pd.DataFrame(result["acceptable_results"])
            result_col1, result_col2, result_col3 = st.columns(3)
            result_col1.metric("Acceptable flow range", f"{result['acceptable_flow_min_bpm']:.2f} - {result['acceptable_flow_max_bpm']:.2f} BPM")
            result_col2.metric("CBHP range", f"{acceptable_df['predicted_cbhp'].min():.2f} - {acceptable_df['predicted_cbhp'].max():.2f} psi")
            result_col3.metric("BHT limit", f"{result['bht_limit']:.2f} °C")
            chart = px.line(
                acceptable_df,
                x="flow_bpm",
                y=["predicted_cbhp", "predicted_bht"],
                markers=True,
                title="Acceptable operating conditions",
                labels={"flow_bpm": "Flow (BPM)", "value": "Predicted value"},
            )
            st.plotly_chart(chart, width="stretch")
            st.dataframe(acceptable_df, hide_index=True, width="stretch")
        st.caption(f"CBHP model: {result['models']['cbhp']} | BHT model: {result['models']['bht']}")
    elif not result:
        st.info("Enter operating conditions and run an optimization mode to see recommendations.")

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
    st.markdown(
        "<style>\n"
        ".segy-hero {padding: 1.25rem 1.5rem; border: 1px solid #28424a; border-radius: 10px; background: linear-gradient(115deg, #10252d 0%, #152e34 56%, #183a37 100%); margin-bottom: 1rem;}\n"
        ".segy-kicker {color: #70d7bf; font-size: .74rem; letter-spacing: .14em; text-transform: uppercase; font-weight: 700;}\n"
        ".segy-hero h1 {color: #f2f8f6; font-size: 2rem; margin: .25rem 0 .35rem;}\n"
        ".segy-hero p {color: #b7c9c9; margin: 0; max-width: 760px;}\n"
        "</style>\n"
        "<div class='segy-hero'><div class='segy-kicker'>CO₂CRC Otway Stage 3</div>"
        "<h1>Microseismic Event &amp; SEGY Analysis Dashboard</h1>"
        "<p>Explore enhanced DAS waveforms, event locations, frequency content, and trace-level signal quality across the monitoring wells.</p></div>",
        unsafe_allow_html=True,
    )

    segy_dir = Path("data/segy")
    file_index = build_segy_file_index(segy_dir)
    available_events = sorted({event_id for event_id, _ in file_index})
    well_options = [f"CRC-{well_id}" for well_id in range(3, 8)]
    if not available_events:
        st.warning("No SEGY files were found in data/segy.", icon=":material/warning:")
    else:
        with st.container(border=True):
            event_col, well_col, channel_col = st.columns([1, 1, 1.2])
            with event_col:
                event_id = st.selectbox("Event ID", available_events, format_func=lambda value: f"Event {value}")
            available_wells = [well for event, well in file_index if event == event_id]
            with well_col:
                well = st.selectbox("Recording well", well_options, index=well_options.index(available_wells[0]) if available_wells else 0)
            selected_path = file_index.get((event_id, well))
            event = EVENT_CATALOG.get(event_id, {})
            with channel_col:
                channel_hint = st.number_input("Channel selector", min_value=1, value=121, step=1)
            if selected_path is None:
                st.info(f"No file is available for Event {event_id} in {well}. Available wells: {', '.join(available_wells) or 'none'}.", icon=":material/info:")
            else:
                st.caption(f"Loaded automatically: `{selected_path.name}`")

        if selected_path is not None:
            try:
                bundle = load_segy_file(str(selected_path))
            except Exception as exc:
                st.error(f"Could not read {selected_path.name}: {exc}", icon=":material/error:")
            else:
                traces = bundle["traces"]
                trace_count = bundle["trace_count"]
                channel = min(int(channel_hint), trace_count)
                samples_ms = bundle["samples"] / 1000.0
                sample_rate_hz = 1_000_000.0 / bundle["sample_interval_us"]
                raw_trace = traces[channel - 1].astype(float)
                duration_s = len(raw_trace) / sample_rate_hz

                with st.sidebar:
                    st.subheader("Signal controls")
                    low_hz = st.number_input("Bandpass low (Hz)", min_value=0.0, max_value=float(sample_rate_hz / 2), value=5.0, step=5.0)
                    high_default = min(450.0, sample_rate_hz / 2 - 1)
                    high_hz = st.number_input("Bandpass high (Hz)", min_value=1.0, max_value=float(sample_rate_hz / 2), value=high_default, step=5.0)
                    clip_percentile = st.slider("Heatmap amplitude clip", 90, 100, 99, 1, format="%dth percentile")
                    heatmap_stride = st.slider("Heatmap time stride", 1, 10, 4)

                if high_hz <= low_hz:
                    high_hz = min(sample_rate_hz / 2, low_hz + 1)
                filtered_trace = apply_fft_bandpass(raw_trace, sample_rate_hz, low_hz, high_hz)
                frequencies, spectrum = get_fft_spectrum(raw_trace, sample_rate_hz)
                useful_spectrum = spectrum.copy()
                useful_spectrum[frequencies < max(low_hz, 1)] = 0
                dominant_frequency = float(frequencies[np.argmax(useful_spectrum)]) if len(useful_spectrum) else float("nan")
                signal_rms = float(np.sqrt(np.mean(np.square(filtered_trace, dtype=np.float64))))
                peak_amplitude = float(np.max(np.abs(raw_trace)))
                noise_window = raw_trace[:max(1, int(raw_trace.size * 0.1))]
                noise_rms = float(np.sqrt(np.mean(np.square(noise_window, dtype=np.float64))))
                snr_db = 20 * np.log10(max(signal_rms, 1e-12) / max(noise_rms, 1e-12))
                all_rms = np.sqrt(np.mean(np.square(traces, dtype=np.float64), axis=1))
                rms_z = (all_rms[channel - 1] - np.mean(all_rms)) / max(np.std(all_rms), 1e-12)

                def catalog_value(key, suffix=""):
                    value = event.get(key)
                    return "N/A" if value is None else f"{value}{suffix}"

                st.subheader(f"Event {event_id} · {well} · channel {channel}")
                kpi_cols = st.columns(6)
                kpi_cols[0].metric("Event ID", str(event_id), border=True)
                kpi_cols[1].metric("Magnitude", catalog_value("magnitude"), border=True)
                kpi_cols[2].metric("Depth", catalog_value("depth", " m"), border=True)
                kpi_cols[3].metric("Corner frequency", catalog_value("corner", " Hz"), border=True)
                kpi_cols[4].metric("Date / time", event.get("date", "N/A"), border=True)
                kpi_cols[5].metric("UTM East / North", f"{event.get('easting', 'N/A')} / {event.get('northing', 'N/A')}", border=True)

                map_col, timeline_col = st.columns(2)
                catalog_df = pd.DataFrame([{"event_id": event_number, **metadata} for event_number, metadata in EVENT_CATALOG.items()])
                catalog_df["date_time"] = pd.to_datetime(catalog_df["date"])
                catalog_df["selected"] = catalog_df["event_id"].eq(event_id)
                catalog_df["magnitude_size"] = catalog_df["magnitude"].abs().fillna(0.3) + 0.3
                with map_col:
                    map_fig = px.scatter(catalog_df, x="easting", y="northing", size="depth", color="selected", hover_name="event_id", hover_data=["date", "depth", "magnitude"], color_discrete_map={True: "#f0a35b", False: "#70d7bf"}, title="Event locations · UTM zone 54H")
                    map_fig.update_traces(marker_line_width=1.5, marker_line_color="#f2f8f6")
                    map_fig.update_layout(xaxis_title="UTM East (m)", yaxis_title="UTM North (m)")
                    style_segy_figure(map_fig, 360)
                    st.plotly_chart(map_fig, width="stretch")
                with timeline_col:
                    timeline_fig = px.scatter(catalog_df, x="date_time", y="depth", size="magnitude_size", color="selected", hover_name="event_id", color_discrete_map={True: "#f0a35b", False: "#70d7bf"}, title="Microseismic event timeline")
                    timeline_fig.update_yaxes(autorange="reversed", title="Depth (m)")
                    timeline_fig.update_xaxes(title="UTC date")
                    style_segy_figure(timeline_fig, 360)
                    st.plotly_chart(timeline_fig, width="stretch")

                waveform_col, spectrum_col = st.columns([1.35, 1])
                with waveform_col:
                    waveform_fig = go.Figure()
                    waveform_fig.add_trace(go.Scatter(x=samples_ms, y=raw_trace, name="Raw", line=dict(color="#91aab1", width=1)))
                    waveform_fig.add_trace(go.Scatter(x=samples_ms, y=filtered_trace, name=f"Filtered {low_hz:g}–{high_hz:g} Hz", line=dict(color="#70d7bf", width=1.5)))
                    waveform_fig.update_layout(title=f"Channel {channel} waveform", xaxis_title="Time (ms)", yaxis_title="Amplitude", legend=dict(orientation="h"))
                    style_segy_figure(waveform_fig, 390)
                    st.plotly_chart(waveform_fig, width="stretch")
                with spectrum_col:
                    spectrum_fig = go.Figure(go.Scatter(x=frequencies, y=spectrum, name="Amplitude spectrum", line=dict(color="#f0a35b", width=1.5)))
                    spectrum_fig.add_vline(x=dominant_frequency, line_dash="dash", line_color="#70d7bf", annotation_text=f"Dominant {dominant_frequency:.1f} Hz")
                    if event.get("corner") is not None:
                        spectrum_fig.add_vline(x=event["corner"], line_dash="dot", line_color="#ef7c7c", annotation_text=f"Catalogue corner {event['corner']} Hz")
                    spectrum_fig.update_layout(title="FFT spectrum", xaxis_title="Frequency (Hz)", yaxis_title="Amplitude", xaxis_range=[0, min(sample_rate_hz / 2, max(500, high_hz * 1.2))])
                    style_segy_figure(spectrum_fig, 390)
                    st.plotly_chart(spectrum_fig, width="stretch")

                analysis_cols = st.columns(4)
                analysis_cols[0].metric("Sampling rate", f"{sample_rate_hz:,.0f} Hz", border=True)
                analysis_cols[1].metric("Duration", f"{duration_s:.2f} s", border=True)
                analysis_cols[2].metric("SNR estimate", f"{snr_db:.1f} dB", border=True)
                analysis_cols[3].metric("Channel RMS z-score", f"{rms_z:+.2f}", border=True)

                st.subheader("DAS channel response")
                channel_range = st.slider("DAS channel range", 1, trace_count, (1, trace_count))
                selected_traces = traces[channel_range[0] - 1:channel_range[1], ::heatmap_stride]
                clipped = max(float(np.nanpercentile(np.abs(selected_traces), clip_percentile)), 1e-8)
                das_fig = go.Figure(go.Heatmap(x=samples_ms[::heatmap_stride], y=np.arange(channel_range[0], channel_range[1] + 1), z=selected_traces, zmin=-clipped, zmax=clipped, colorscale=[[0, "#123d58"], [0.5, "#081116"], [1, "#f0a35b"]], colorbar=dict(title="amplitude", thickness=12), hovertemplate="Channel %{y}<br>Time %{x:.0f} ms<br>Amplitude %{z:.2f}<extra></extra>"))
                das_fig.update_layout(title="Channel vs time amplitude image", xaxis_title="Time (ms)", yaxis_title="DAS channel")
                style_segy_figure(das_fig, 480)
                st.plotly_chart(das_fig, width="stretch")

                compare_col, insight_col = st.columns([1.3, 1])
                with compare_col:
                    st.subheader("Event comparison")
                    comparison_df = catalog_df.dropna(subset=["magnitude"])
                    comparison_tabs = st.tabs(["Magnitude vs depth", "Magnitude vs corner frequency"])
                    with comparison_tabs[0]:
                        comparison_fig = px.scatter(comparison_df, x="depth", y="magnitude", size="corner", color="event_id", hover_name="event_id", title="Catalogued magnitude and depth")
                        comparison_fig.add_trace(go.Scatter(x=[event.get("depth")], y=[event.get("magnitude")], mode="markers", marker=dict(size=16, color="#f0a35b", symbol="star"), name="Selected event"))
                        style_segy_figure(comparison_fig, 350)
                        st.plotly_chart(comparison_fig, width="stretch")
                    with comparison_tabs[1]:
                        corner_df = comparison_df.dropna(subset=["corner"])
                        corner_fig = px.scatter(corner_df, x="corner", y="magnitude", size="depth", color="event_id", hover_name="event_id", title="Catalogued magnitude and corner frequency")
                        style_segy_figure(corner_fig, 350)
                        st.plotly_chart(corner_fig, width="stretch")
                with insight_col:
                    st.subheader("Analytical insights")
                    quality = "strong" if snr_db >= 10 else "moderate" if snr_db >= 3 else "limited"
                    anomaly = "unusually energetic" if abs(rms_z) >= 2 else "within the channel energy distribution"
                    st.markdown(f"**Signal quality:** {quality} by the simple first-10%-window SNR estimate ({snr_db:.1f} dB).")
                    st.markdown(f"**Channel behavior:** channel {channel} is {anomaly} (RMS z-score {rms_z:+.2f}).")
                    if event.get("corner") is not None:
                        difference = dominant_frequency - event["corner"]
                        st.markdown(f"**Frequency check:** the measured spectral peak is {dominant_frequency:.1f} Hz; it differs from the catalogue corner frequency by {difference:+.1f} Hz. These are distinct quantities.")
                    else:
                        st.markdown(f"**Frequency check:** the measured spectral peak is {dominant_frequency:.1f} Hz; no catalogue corner frequency is available for this event.")
                    st.caption("These indicators describe the recorded signal only. They do not establish CO₂ leakage or other geological conclusions.")

                with st.expander("SEGY metadata and trace headers", icon=":material/description:"):
                    metadata_df = pd.DataFrame({"Field": ["Filename", "Number of traces", "Samples per trace", "Sampling interval", "Sampling rate", "Selected channel", "Depth context"], "Value": [selected_path.name, trace_count, len(bundle["samples"]), f"{bundle['sample_interval_us']:g} μs", f"{sample_rate_hz:,.0f} Hz", channel, f"Event catalogue depth: {event.get('depth', 'N/A')} m; channel depth is not encoded in the available headers"]})
                    metadata_df["Value"] = metadata_df["Value"].astype(str)
                    st.dataframe(metadata_df, hide_index=True, width="stretch")
                    with segyio.open(str(selected_path), "r", ignore_geometry=True) as segy_file:
                        header = segy_file.header[channel - 1]
                        header_fields = {"TRACE_SEQUENCE_FILE": segyio.TraceField.TRACE_SEQUENCE_FILE, "TRACE_SEQUENCE_LINE": segyio.TraceField.TRACE_SEQUENCE_LINE, "FieldRecord": segyio.TraceField.FieldRecord, "TraceNumber": segyio.TraceField.TraceNumber, "CDP": segyio.TraceField.CDP, "CDP_TRACE": segyio.TraceField.CDP_TRACE, "GroupX": segyio.TraceField.GroupX, "GroupY": segyio.TraceField.GroupY, "SourceX": segyio.TraceField.SourceX, "SourceY": segyio.TraceField.SourceY, "DelayRecordingTime": segyio.TraceField.DelayRecordingTime, "TRACE_SAMPLE_INTERVAL": segyio.TraceField.TRACE_SAMPLE_INTERVAL}
                        headers_df = pd.DataFrame({"Header": list(header_fields), "Value": [int(header[field]) for field in header_fields.values()]})
                    st.dataframe(headers_df, hide_index=True, width="stretch")
