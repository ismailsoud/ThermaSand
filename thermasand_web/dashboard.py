"""
ThermaSand Intelligent Core -- Streamlit Dashboard
══════════════════════════════════════════════════════════════════
Real-time M-TES thermal energy storage management system.
Supports both autonomous SIMULATION mode and ESP32 LIVE mode.

Run:  streamlit run dashboard.py
"""

import time
import datetime
import math
import json
import random

import numpy as np
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from ai_engine import (
    DispatchAgent,
    TemperaturePredictor,
    AnomalyDetector,
    DayAheadPlanner,
    ACTION_NAMES,
)
from smart_framework import (
    ThermalIntegrityMonitor,
    PipingDiagnostics,
    DynamicLoadBalancer,
    WeatherCompensator,
    CostCalculator,
    ArbitrageEngine,
    IndustrialBenchmark,
    MARKET_REFERENCES,
)

# Serial is OPTIONAL -- dashboard works fully in Simulation mode without it.
try:
    import serial
    import serial.tools.list_ports

    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


# ════════════════════════════════════════════════════════════════
# SYSTEM CONSTANTS (Physical Prototype)
# ════════════════════════════════════════════════════════════════
MASS = 15  # kg (silica sand)
CP = 830  # J/(kg·K) specific heat capacity
AMBIENT = 25  # °C ambient temperature
HEATER_POWER = 1500  # Watts (220V resistive element)
MAX_TEMP = 800  # °C safety limit
CHARGE_RATE = HEATER_POWER / (MASS * CP)  # ≈ 0.12 °C/s
DISCHARGE_RATE = -0.15  # °C/s (blower cooling)
STORAGE_LOSS = -0.005  # °C/s (insulated heat loss)
MAX_HISTORY = 500


# ════════════════════════════════════════════════════════════════
# AI CORE ENGINE
# ════════════════════════════════════════════════════════════════
def compute_state(temp, sim_time, prev_temp=None, dt=1.0, action_override=None):
    """
    ThermaSand Intelligent Core -- computes the full system state.

    Modules:
        A. State Inference (Physics Engine)
        B. Economic Dispatch (Grid Pricing Brain)
        C. Renewable Integration (Green Layer)

    Returns a dict matching the JSON API specification.
    """
    h = sim_time.hour
    m = sim_time.minute
    s = sim_time.second
    ts = f"{h:02d}:{m:02d}:{s:02d}"

    # ── A. Physics Engine ─────────────────────────────────────
    energy_j = MASS * CP * max(0, temp - AMBIENT)
    energy_kj = round(energy_j / 1000, 2)

    # State inference from temperature rate-of-change
    system_status = "STORAGE"
    if prev_temp is not None and dt > 0:
        rate = (temp - prev_temp) / dt
        if rate > 0.2:
            system_status = "CHARGING"
        elif rate < -0.2:
            system_status = "DISCHARGING"

    # In simulation mode, controller knows the relay state
    if action_override:
        system_status = action_override

    # ── B. Economic Dispatch ──────────────────────────────────
    is_peak = 17 <= h < 22
    grid_mode = "PEAK" if is_peak else "OFF-PEAK"

    # ── C. Renewable Integration ──────────────────────────────
    is_solar = 8 <= h < 18
    is_wind = h >= 22 or h < 5
    renew_avail = "HIGH" if (is_solar or is_wind) else "LOW"

    # Solar intensity curve (0-1, peaks at 13:00)
    solar_i = 0.0
    if is_solar:
        solar_i = math.sin(((h + m / 60 - 8) / 10) * math.pi)

    # Wind intensity (0-1)
    wind_i = 0.0
    if h >= 22:
        wind_i = 0.6 + 0.2 * math.sin(((h - 22) / 7) * math.pi)
    elif h < 5:
        wind_i = 0.6 + 0.2 * math.sin(((h + 2) / 7) * math.pi)

    # ── AI Recommendation ─────────────────────────────────────
    rec = ""
    rec_type = "storage"
    if not is_peak and temp < 600:
        if is_solar:
            rec = "SOLAR AVAILABLE + OFF-PEAK -- GREEN CHARGE OPTIMAL"
            rec_type = "charge"
        elif is_wind:
            rec = "WIND AVAILABLE + OFF-PEAK -- INITIATE NIGHT CHARGE"
            rec_type = "charge"
        else:
            rec = "GRID PRICE LOW -- INITIATE CHARGING"
            rec_type = "charge"
    elif is_peak and temp > 300:
        rec = "PEAK PRICING ACTIVE -- DISCHARGE STORED ENERGY (AVOID GRID)"
        rec_type = "discharge"
    elif is_peak and temp <= 300:
        rec = "CRITICAL RESERVE -- INSUFFICIENT THERMAL ENERGY -- DO NOT USE"
        rec_type = "critical"
    elif not is_peak and temp >= 600:
        rec = "THERMAL CAPACITY NEAR MAX -- MAINTAIN STORAGE"
        rec_type = "storage"

    # ── Carbon Footprint ──────────────────────────────────────
    carbon = "LOW"
    if system_status == "CHARGING":
        if is_solar or is_wind:
            carbon = "LOW"
        elif is_peak:
            carbon = "HIGH"
        else:
            carbon = "MEDIUM"

    # ── Safety Alert ──────────────────────────────────────────
    safety = "NORMAL"
    if temp > 800:
        safety = "CRITICAL"
    elif temp > 650:
        safety = "WARNING"

    # Safety override -- emergency cutoff
    if safety == "CRITICAL":
        rec = "SAFETY CUTOFF -- HEATER DISABLED -- TEMPERATURE EXCEEDS SAFE LIMIT"
        rec_type = "critical"

    return {
        "timestamp": ts,
        "system_status": system_status,
        "temperature_c": round(temp, 1),
        "energy_stored_kj": energy_kj,
        "grid_price_mode": grid_mode,
        "renewable_availability": renew_avail,
        "ai_recommendation": rec,
        "safety_alert": safety,
        # Internal fields for visualization
        "_carbon": carbon,
        "_rec_type": rec_type,
        "_solar_i": solar_i,
        "_wind_i": wind_i,
        "_is_peak": is_peak,
        "_hour": h + m / 60,
    }


def get_gauge_color(temp):
    """Return a hex color based on temperature zone."""
    if temp < 150:
        return "#3b82f6"  # Blue (cold)
    if temp < 350:
        return "#10b981"  # Green (warm)
    if temp < 550:
        return "#f59e0b"  # Amber (hot)
    if temp < 700:
        return "#f97316"  # Orange (very hot)
    return "#ef4444"  # Red (danger)


def get_next_action(state):
    """Determine what the controller should do next based on AI recommendation."""
    if state["safety_alert"] == "CRITICAL":
        return "STORAGE"
    if "CHARGE" in state["ai_recommendation"]:
        return "CHARGING"
    if "DISCHARGE" in state["ai_recommendation"]:
        return "DISCHARGING"
    return "STORAGE"


def parse_esp_line(line: str):
    """Parse ESP32 serial line. Format: T:<temperature>"""
    line = line.strip()
    if not line.startswith("T:"):
        return None
    try:
        temp_part = line.split("|")[0]
        return float(temp_part[2:])
    except (ValueError, IndexError):
        return None


# ════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="ThermaSand Intelligent Core",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ════════════════════════════════════════════════════════════════
# SESSION STATE
# ════════════════════════════════════════════════════════════════
_defaults = {
    "sim_running": False,
    "sim_temp": 25.0,
    "sim_prev_temp": 25.0,
    "sim_time": datetime.datetime.now().replace(
        hour=8, minute=0, second=0, microsecond=0
    ),
    "sim_action": "STORAGE",
    "sim_speed": 60,
    "history": [],
    "mode": "simulation",
    "control_mode": "ai",  # "rules" or "ai"
    # ESP32
    "serial_connected": False,
    "ser_object": None,
    "serial_port": None,
    "serial_error": "",
    "latest_temp_esp": None,
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# AI objects persist across reruns via session_state
if "ai_agent" not in st.session_state:
    st.session_state.ai_agent = DispatchAgent()
if "ai_predictor" not in st.session_state:
    st.session_state.ai_predictor = TemperaturePredictor()
if "ai_anomaly" not in st.session_state:
    st.session_state.ai_anomaly = AnomalyDetector()
if "ai_planner" not in st.session_state:
    st.session_state.ai_planner = DayAheadPlanner()
if "ai_reward_history" not in st.session_state:
    st.session_state.ai_reward_history = []

# Smart Framework objects (Tiers 1-3)
if "fw_thermal" not in st.session_state:
    st.session_state.fw_thermal = ThermalIntegrityMonitor()
if "fw_piping" not in st.session_state:
    st.session_state.fw_piping = PipingDiagnostics()
if "fw_load" not in st.session_state:
    st.session_state.fw_load = DynamicLoadBalancer()
if "fw_cost" not in st.session_state:
    st.session_state.fw_cost = CostCalculator()
if "fw_surplus_log" not in st.session_state:
    st.session_state.fw_surplus_log = []


# ════════════════════════════════════════════════════════════════
# CUSTOM CSS
# ════════════════════════════════════════════════════════════════
st.markdown(
    """
<style>
    div[data-testid="stMetric"] {
        background: rgba(22, 27, 34, 0.9);
        border: 1px solid rgba(48, 54, 61, 0.8);
        border-radius: 10px;
        padding: 12px 16px;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.72rem !important;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    div[data-testid="stMetricValue"] {
        font-family: 'Consolas', 'Monaco', monospace;
    }
    .block-container { padding-top: 1.5rem; }
</style>
""",
    unsafe_allow_html=True,
)


# ════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 🔥 ThermaSand")
    st.caption("Intelligent Core -- M-TES Controller")
    st.divider()

    # ── Mode Selection ────────────────────────────────────────
    mode = st.radio(
        "Operating Mode",
        ["Simulation", "ESP32 Live"],
        index=0 if st.session_state.mode == "simulation" else 1,
        horizontal=True,
    )
    st.session_state.mode = "simulation" if mode == "Simulation" else "esp32"

    # ── Control Brain ─────────────────────────────────────────
    ctrl = st.radio(
        "Control Brain",
        ["AI Agent (Q-Learning)", "Rule-Based"],
        index=0 if st.session_state.control_mode == "ai" else 1,
        horizontal=True,
        help="**AI Agent** learns optimal dispatch via reinforcement learning. "
             "**Rule-Based** uses fixed if/else rules.",
    )
    st.session_state.control_mode = "ai" if "AI" in ctrl else "rules"
    st.divider()

    # ── Simulation Controls ───────────────────────────────────
    if st.session_state.mode == "simulation":
        st.subheader("Simulation Controls")

        # Time
        if not st.session_state.sim_running:
            init_time = st.time_input(
                "Start Time",
                value=st.session_state.sim_time.time(),
                step=datetime.timedelta(minutes=15),
            )
            st.session_state.sim_time = datetime.datetime.combine(
                datetime.date.today(), init_time
            )
        else:
            st.metric(
                "Simulated Clock",
                st.session_state.sim_time.strftime("%H:%M:%S"),
            )

        # Temperature
        if not st.session_state.sim_running:
            init_temp = st.slider(
                "Initial Temperature (°C)",
                25,
                800,
                int(st.session_state.sim_temp),
            )
            st.session_state.sim_temp = float(init_temp)
            st.session_state.sim_prev_temp = float(init_temp)
        else:
            st.metric("Temperature", f"{st.session_state.sim_temp:.1f} °C")

        # Speed
        speed_map = {
            "Real-time (1×)": 1,
            "Fast (10×)": 10,
            "1 min / sec (60×)": 60,
            "5 min / sec (300×)": 300,
            "30 min / sec (1800×)": 1800,
        }
        speed_label = st.selectbox(
            "Simulation Speed",
            list(speed_map.keys()),
            index=2,
        )
        st.session_state.sim_speed = speed_map[speed_label]

        # Buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.session_state.sim_running:
                if st.button("⏸ Pause", use_container_width=True):
                    st.session_state.sim_running = False
                    st.rerun()
            else:
                if st.button("▶ Start", use_container_width=True, type="primary"):
                    st.session_state.sim_running = True
                    st.session_state.sim_action = "STORAGE"
                    st.rerun()
        with col2:
            if st.button("↺ Reset", use_container_width=True):
                st.session_state.sim_running = False
                st.session_state.sim_temp = 25.0
                st.session_state.sim_prev_temp = 25.0
                st.session_state.sim_time = datetime.datetime.now().replace(
                    hour=8, minute=0, second=0, microsecond=0
                )
                st.session_state.sim_action = "STORAGE"
                st.session_state.history = []
                st.session_state.ai_agent = DispatchAgent()
                st.session_state.ai_predictor = TemperaturePredictor()
                st.session_state.ai_anomaly = AnomalyDetector()
                st.session_state.ai_reward_history = []
                st.rerun()

        # Status
        if st.session_state.sim_running:
            st.success(f"🟢 Running -- {speed_label}")
        else:
            st.info("⏹ Simulation idle")

    # ── ESP32 Controls ────────────────────────────────────────
    else:
        st.subheader("ESP32 Connection")
        if not SERIAL_AVAILABLE:
            st.error("⚠️ `pyserial` not installed.")
            st.code("pip install pyserial", language="bash")
            st.info("Switch to **Simulation** mode to use the dashboard without hardware.")
        else:
            ports = [p.device for p in serial.tools.list_ports.comports()]
            if ports:
                sel_port = st.selectbox("Serial Port", ports)
            else:
                sel_port = st.text_input("Serial Port (manual)", "COM3")
            baud = st.selectbox("Baud Rate", [115200, 9600, 57600], index=0)

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Connect", use_container_width=True):
                    try:
                        if st.session_state.ser_object:
                            st.session_state.ser_object.close()
                        ser = serial.Serial(sel_port, baud, timeout=1)
                        st.session_state.ser_object = ser
                        st.session_state.serial_connected = True
                        st.session_state.serial_port = sel_port
                        st.session_state.serial_error = ""
                    except Exception as e:
                        st.session_state.serial_error = str(e)
                        st.session_state.serial_connected = False
            with c2:
                if st.button("Disconnect", use_container_width=True):
                    if st.session_state.ser_object:
                        try:
                            st.session_state.ser_object.close()
                        except Exception:
                            pass
                    st.session_state.ser_object = None
                    st.session_state.serial_connected = False

    if st.session_state.serial_connected:
        st.success(f"🟢 {st.session_state.serial_port}")
    elif st.session_state.serial_error:
        st.error(f"Error: {st.session_state.serial_error}")
    else:
        st.warning("Not connected")

    # ── System Specs ──────────────────────────────────────────
    st.divider()
    st.caption("**System Specifications**")
    st.caption(f"Sand Mass: **{MASS} kg** · Cp: **{CP}** J/(kg·K)")
    st.caption(f"Heater: **{HEATER_POWER}W** / 220V Resistive")
    st.caption(f"Sensor: MAX6675 K-Type (0–1024°C)")
    st.caption(f"Grid: Morocco ONEE")

    if st.session_state.history:
        st.divider()
        csv_data = pd.DataFrame(st.session_state.history).to_csv(index=False)
        st.download_button(
            "📥 Download CSV",
            csv_data,
            f"thermasand_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv",
            "text/csv",
            use_container_width=True,
        )


# ════════════════════════════════════════════════════════════════
# SIMULATION TICK (runs before rendering so display is fresh)
# ════════════════════════════════════════════════════════════════
if st.session_state.mode == "simulation" and st.session_state.sim_running:
    speed = st.session_state.sim_speed
    refresh_s = 0.4  # real seconds between ticks
    dt = speed * refresh_s  # simulated seconds per tick

    st.session_state.sim_prev_temp = st.session_state.sim_temp

    # Apply temperature change based on current controller action
    action = st.session_state.sim_action
    if action == "CHARGING":
        st.session_state.sim_temp += CHARGE_RATE * dt
    elif action == "DISCHARGING":
        st.session_state.sim_temp += DISCHARGE_RATE * dt
    else:
        st.session_state.sim_temp += STORAGE_LOSS * dt
    st.session_state.sim_temp = max(AMBIENT, min(850, st.session_state.sim_temp))

    # ── Feed AI components ────────────────────────────────────
    st.session_state.ai_predictor.update(st.session_state.sim_temp)

    # ── Feed Smart Framework ──────────────────────────────────
    _h = st.session_state.sim_time.hour
    _amb = WeatherCompensator.morocco_ambient(_h)
    st.session_state.fw_thermal.update(
        st.session_state.sim_temp, st.session_state.sim_prev_temp,
        dt, _amb, action,
    )
    st.session_state.fw_load.simulate_random_stop(_h)
    _surplus, _surplus_msg = st.session_state.fw_load.detect_surplus(_h)
    if _surplus_msg:
        st.session_state.fw_surplus_log.append(_surplus_msg)
        if len(st.session_state.fw_surplus_log) > 30:
            st.session_state.fw_surplus_log = st.session_state.fw_surplus_log[-30:]
    if action == "CHARGING":
        st.session_state.fw_cost.record(HEATER_POWER / 1000, dt / 3600, _h)

    # Advance clock
    st.session_state.sim_time += datetime.timedelta(seconds=dt)

# ESP32 data read
elif st.session_state.mode == "esp32" and st.session_state.serial_connected:
    ser = st.session_state.ser_object
    if ser and ser.is_open:
        try:
            raw = ser.readline().decode("utf-8", errors="replace").strip()
            temp_val = parse_esp_line(raw)
            if temp_val is not None:
                st.session_state.latest_temp_esp = temp_val
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
# COMPUTE CURRENT STATE
# ════════════════════════════════════════════════════════════════
if st.session_state.mode == "simulation":
    current_state = compute_state(
        st.session_state.sim_temp,
        st.session_state.sim_time,
        st.session_state.sim_prev_temp,
        1.0,
        action_override=(
            st.session_state.sim_action if st.session_state.sim_running else None
        ),
    )
    # ── Determine next action ────────────────────────────────
    if st.session_state.sim_running:
        h = st.session_state.sim_time.hour
        is_pk = 17 <= h < 22
        is_rn = (8 <= h < 18) or h >= 22 or h < 5
        temp_now = st.session_state.sim_temp

        if st.session_state.control_mode == "ai":
            agent = st.session_state.ai_agent
            # Q-Learning: choose action, compute reward, update Q-table
            ai_action, ai_state = agent.choose_action(
                temp_now, h, is_pk, is_rn
            )
            reward = agent.compute_reward(ai_action, temp_now, is_pk, is_rn)
            # Update Q-table with current transition
            next_h = (st.session_state.sim_time + datetime.timedelta(seconds=speed * 0.4)).hour
            next_pk = 17 <= next_h < 22
            next_rn = (8 <= next_h < 18) or next_h >= 22 or next_h < 5
            agent.update(ai_state, ai_action, reward, temp_now, next_h, next_pk, next_rn)
            st.session_state.ai_reward_history.append(reward)
            st.session_state.sim_action = ACTION_NAMES[ai_action]
        else:
            st.session_state.sim_action = get_next_action(current_state)

        # Anomaly detection
        st.session_state.ai_anomaly.check(
            st.session_state.sim_temp,
            st.session_state.sim_prev_temp,
            dt,
            st.session_state.sim_action,
        )
else:
    temp = st.session_state.latest_temp_esp or AMBIENT
    current_state = compute_state(temp, datetime.datetime.now())

# Record history
if st.session_state.sim_running or (
    st.session_state.mode == "esp32" and st.session_state.serial_connected
):
    st.session_state.history.append(
        {
            "timestamp": current_state["timestamp"],
            "temperature_c": current_state["temperature_c"],
            "energy_stored_kj": current_state["energy_stored_kj"],
            "status": current_state["system_status"],
            "grid": current_state["grid_price_mode"],
            "safety": current_state["safety_alert"],
        }
    )
    if len(st.session_state.history) > MAX_HISTORY:
        st.session_state.history = st.session_state.history[-MAX_HISTORY:]


# ════════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════════
hcol1, hcol2 = st.columns([3, 1])
with hcol1:
    st.markdown("## 🔥 ThermaSand **Intelligent Core**")
    st.caption(
        "M-TES Controller · Morocco ONEE Grid · "
        "MAX6675 Thermocouple (0–1024°C)"
    )
with hcol2:
    is_live = st.session_state.sim_running or st.session_state.serial_connected
    mode_lbl = "SIMULATION" if st.session_state.mode == "simulation" else "ESP32 LIVE"
    badge_color = "#22c55e" if is_live else "#8b949e"
    st.markdown(
        f'<div style="text-align:right;padding-top:12px;">'
        f'<span style="background:rgba(251,146,60,0.15);color:#fb923c;'
        f"padding:4px 12px;border-radius:20px;font-size:0.7rem;"
        f'font-weight:600;letter-spacing:1px;">MOROCCO</span> '
        f'<span style="background:rgba({badge_color},0.15);color:{badge_color};'
        f"padding:4px 12px;border-radius:20px;font-size:0.7rem;"
        f'font-weight:600;letter-spacing:1px;">'
        f'{"🟢" if is_live else "⏹"} {mode_lbl}</span></div>',
        unsafe_allow_html=True,
    )

st.divider()


# ════════════════════════════════════════════════════════════════
# KPI METRICS ROW
# ════════════════════════════════════════════════════════════════
k1, k2, k3, k4, k5, k6 = st.columns(6)

with k1:
    st.metric("System Status", current_state["system_status"])
with k2:
    st.metric("Temperature", f"{current_state['temperature_c']:.1f} °C")
with k3:
    ekj = current_state["energy_stored_kj"]
    estr = f"{ekj / 1000:.2f} MJ" if ekj >= 1000 else f"{ekj:.1f} kJ"
    st.metric("Energy Stored", estr)
with k4:
    st.metric("Grid Price", current_state["grid_price_mode"])
with k5:
    st.metric("Renewable", current_state["renewable_availability"])
with k6:
    st.metric("Safety", current_state["safety_alert"])



# ════════════════════════════════════════════════════════════════
# GAUGE + 24-HOUR LANDSCAPE
# ════════════════════════════════════════════════════════════════
gauge_col, land_col = st.columns([3, 2])

# ── Temperature Gauge ─────────────────────────────────────────
with gauge_col:
    temp = current_state["temperature_c"]
    g_color = get_gauge_color(temp)
    status_text = current_state["system_status"]

    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=temp,
            number={"suffix": " °C", "font": {"size": 52, "family": "Consolas"}},
            gauge={
                "axis": {
                    "range": [0, 800],
                    "tickcolor": "#8b949e",
                    "dtick": 100,
                    "tickfont": {"size": 10},
                },
                "bar": {"color": g_color, "thickness": 0.75},
                "bgcolor": "#161b22",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 200], "color": "rgba(59,130,246,0.10)"},
                    {"range": [200, 400], "color": "rgba(16,185,129,0.10)"},
                    {"range": [400, 600], "color": "rgba(245,158,11,0.10)"},
                    {"range": [600, 700], "color": "rgba(249,115,22,0.10)"},
                    {"range": [700, 800], "color": "rgba(239,68,68,0.10)"},
                ],
                "threshold": {
                    "line": {"color": "#ef4444", "width": 3},
                    "thickness": 0.8,
                    "value": MAX_TEMP,
                },
            },
            title={
                "text": (
                    f"<b>{status_text}</b><br>"
                    f"<span style='font-size:12px;color:#8b949e;'>"
                    f"Thermal Core</span>"
                ),
                "font": {"color": g_color, "size": 16},
            },
        )
    )
    fig_gauge.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#e6edf3"},
        height=300,
        margin=dict(l=30, r=30, t=70, b=10),
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

# ── 24-Hour Energy Landscape ─────────────────────────────────
with land_col:
    hours = list(range(24))
    solar_data = [
        max(0, math.sin(((h - 8) / 10) * math.pi) * 100) if 8 <= h < 18 else 0
        for h in hours
    ]
    wind_data = [65 if (h >= 22 or h < 5) else 3 for h in hours]
    peak_data = [80 if (17 <= h < 22) else 0 for h in hours]

    fig_land = go.Figure()
    fig_land.add_trace(
        go.Bar(
            x=hours,
            y=solar_data,
            name="Solar",
            marker_color="rgba(251,191,36,0.55)",
            marker_line_color="#fbbf24",
            marker_line_width=1,
        )
    )
    fig_land.add_trace(
        go.Bar(
            x=hours,
            y=wind_data,
            name="Wind",
            marker_color="rgba(6,182,212,0.45)",
            marker_line_color="#06b6d4",
            marker_line_width=1,
        )
    )
    fig_land.add_trace(
        go.Bar(
            x=hours,
            y=peak_data,
            name="Peak Grid",
            marker_color="rgba(239,68,68,0.18)",
            marker_line_color="rgba(239,68,68,0.5)",
            marker_line_width=1,
        )
    )
    # Current time marker
    fig_land.add_vline(
        x=current_state["_hour"],
        line_dash="dash",
        line_color="#e6edf3",
        line_width=2,
        annotation_text="NOW",
        annotation_font_color="#e6edf3",
        annotation_font_size=10,
    )
    fig_land.update_layout(
        barmode="overlay",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#8b949e", "size": 10},
        height=250,
        margin=dict(l=10, r=10, t=35, b=30),
        legend=dict(orientation="h", y=1.18, font=dict(size=10)),
        xaxis=dict(
            title="Hour",
            gridcolor="#21262d",
            tickmode="linear",
            dtick=3,
        ),
        yaxis=dict(visible=False),
        title=dict(
            text="24-Hour Energy Landscape",
            font=dict(size=12, color="#8b949e"),
        ),
    )
    st.plotly_chart(fig_land, use_container_width=True)

    # Carbon footprint badge
    carbon = current_state["_carbon"]
    c_colors = {"LOW": "#22c55e", "MEDIUM": "#eab308", "HIGH": "#ef4444"}
    cc = c_colors.get(carbon, "#8b949e")
    st.markdown(
        f'<div style="background:rgba(22,27,34,0.9);border:1px solid #30363d;'
        f"border-radius:8px;padding:10px 14px;display:flex;"
        f'align-items:center;gap:10px;">'
        f'<div style="width:10px;height:10px;border-radius:50%;background:{cc};"></div>'
        f"<div>"
        f'<div style="font-size:0.65rem;color:#8b949e;text-transform:uppercase;'
        f'letter-spacing:1px;">Carbon Footprint</div>'
        f'<div style="font-weight:700;font-size:0.95rem;color:{cc};">{carbon}</div>'
        f"</div></div>",
        unsafe_allow_html=True,
    )


# ════════════════════════════════════════════════════════════════
# TEMPERATURE & ENERGY HISTORY
# ════════════════════════════════════════════════════════════════
st.divider()

if st.session_state.history:
    df = pd.DataFrame(st.session_state.history)

    fig_hist = go.Figure()
    fig_hist.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["temperature_c"],
                name="Temperature (°C)",
            mode="lines",
            line=dict(color="#f59e0b", width=2),
            fill="tozeroy",
            fillcolor="rgba(245,158,11,0.06)",
            yaxis="y",
        )
    )
    fig_hist.add_trace(
            go.Scatter(
                x=df["timestamp"],
            y=df["energy_stored_kj"],
            name="Energy Stored (kJ)",
            mode="lines",
            line=dict(color="#10b981", width=2),
            fill="tozeroy",
            fillcolor="rgba(16,185,129,0.04)",
            yaxis="y2",
        )
    )

    max_e = max(df["energy_stored_kj"].max(), 100)
    fig_hist.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8b949e", size=10),
        height=300,
        margin=dict(l=50, r=50, t=35, b=40),
        legend=dict(orientation="h", y=1.12, font=dict(size=10)),
        xaxis=dict(gridcolor="#21262d", title="Time"),
        yaxis=dict(
            title=dict(text="°C", font=dict(color="#f59e0b")),
            tickfont=dict(color="#f59e0b"),
            gridcolor="#21262d",
            range=[0, 850],
        ),
        yaxis2=dict(
            title=dict(text="kJ", font=dict(color="#10b981")),
            tickfont=dict(color="#10b981"),
            overlaying="y",
            side="right",
            range=[0, math.ceil(max_e / 500) * 500],
        ),
        title=dict(
            text="Temperature & Energy History",
            font=dict(size=12, color="#8b949e"),
        ),
    )
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info(
        "📊 No history data yet. **Start the simulation** or "
        "connect the ESP32 to begin collecting data."
    )


# ════════════════════════════════════════════════════════════════
# AI INTELLIGENCE PANEL
# ════════════════════════════════════════════════════════════════
st.divider()
st.markdown("### 🧠 AI Intelligence Panel")

ai_tab1, ai_tab2, ai_tab3, ai_tab4 = st.tabs([
    "Q-Learning Agent",
    "Temperature Forecast",
    "Day-Ahead Plan",
    "Anomaly Detection",
])

# ── Tab 1: Q-Learning Agent ──────────────────────────────────
with ai_tab1:
    agent = st.session_state.ai_agent
    h_now = st.session_state.sim_time.hour
    is_pk = 17 <= h_now < 22
    is_rn = (8 <= h_now < 18) or h_now >= 22 or h_now < 5
    t_now = current_state["temperature_c"]

    q1, q2, q3 = st.columns(3)
    with q1:
        st.metric("Total RL Steps", f"{agent.total_steps:,}")
    with q2:
        st.metric(
            "Exploration Rate (ε)",
            f"{agent.epsilon:.1%}",
            help="Probability of random exploration. Decays over time as the agent learns.",
        )
    with q3:
        st.metric(
            "Cumulative Reward",
            f"{agent.cumulative_reward:+.1f}",
        )

    # Q-values for current state
    qv = agent.get_q_values(t_now, h_now, is_pk, is_rn)
    conf = agent.get_confidence(t_now, h_now, is_pk, is_rn)

    qcol1, qcol2 = st.columns([2, 1])
    with qcol1:
        st.markdown("**Q-Values for Current State**")
        fig_q = go.Figure()
        colors = ["#f59e0b", "#3b82f6", "#10b981"]
        fig_q.add_trace(go.Bar(
            x=list(qv.keys()),
            y=list(qv.values()),
            marker_color=colors,
            text=[f"{v:+.2f}" for v in qv.values()],
            textposition="outside",
            textfont=dict(color="#e6edf3"),
        ))
        best = max(qv, key=qv.get)
        fig_q.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=11),
            height=220,
            margin=dict(l=20, r=20, t=10, b=40),
            yaxis=dict(gridcolor="#21262d"),
            xaxis=dict(title="Action"),
        )
        st.plotly_chart(fig_q, use_container_width=True)
        st.caption(
            f"Agent prefers **{best}** (Q={qv[best]:+.2f}). "
            f"Confidence: **{conf:.0%}**"
        )

    with qcol2:
        st.markdown("**24-Hour Learned Policy**")
        policy = agent.get_policy_summary()
        pol_colors = {
            "CHARGING": "#f59e0b",
            "DISCHARGING": "#3b82f6",
            "STORAGE": "#10b981",
        }
        fig_pol = go.Figure()
        for h_i, act in enumerate(policy):
            fig_pol.add_trace(go.Bar(
                x=[1], y=[1],
                orientation="h",
                marker_color=pol_colors.get(act, "#8b949e"),
                name=act if h_i == 0 else None,
                showlegend=False,
                hovertext=f"{h_i:02d}:00 → {act}",
                hoverinfo="text",
            ))
        # Simpler: use a heatmap-style display
        fig_pol = go.Figure(go.Heatmap(
            z=[[{"CHARGING": 2, "DISCHARGING": 0, "STORAGE": 1}[a] for a in policy]],
            x=[f"{h:02d}" for h in range(24)],
            y=["Action"],
            colorscale=[[0, "#3b82f6"], [0.5, "#10b981"], [1, "#f59e0b"]],
            showscale=False,
            hovertext=[[a[:3] for a in policy]],
            hoverinfo="text",
        ))
        fig_pol.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=9),
            height=80,
            margin=dict(l=0, r=0, t=0, b=25),
            xaxis=dict(title="Hour", side="bottom"),
        )
        st.plotly_chart(fig_pol, use_container_width=True)
        st.caption("🟠 Charge · 🟢 Store · 🔵 Discharge")

    # Reward history
    if st.session_state.ai_reward_history:
        rh = st.session_state.ai_reward_history
        window = min(50, len(rh))
        smoothed = pd.Series(rh).rolling(window=window, min_periods=1).mean().tolist()
        fig_rw = go.Figure()
        fig_rw.add_trace(go.Scatter(
            y=smoothed, mode="lines",
            line=dict(color="#f59e0b", width=2),
            fill="tozeroy", fillcolor="rgba(245,158,11,0.06)",
            name="Rolling Avg Reward",
        ))
        fig_rw.add_hline(y=0, line_dash="dash", line_color="#8b949e", line_width=1)
        fig_rw.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=10),
            height=200,
            margin=dict(l=40, r=10, t=30, b=30),
            xaxis=dict(title="Step", gridcolor="#21262d"),
            yaxis=dict(title="Reward", gridcolor="#21262d"),
            title=dict(
                text="RL Learning Curve (Rolling Average Reward)",
                font=dict(size=12, color="#8b949e"),
            ),
        )
        st.plotly_chart(fig_rw, use_container_width=True)

# ── Tab 2: Temperature Forecast ──────────────────────────────
with ai_tab2:
    predictor = st.session_state.ai_predictor
    n_steps = 15
    fc, lower, upper = predictor.prediction_interval(n_steps)

    if st.session_state.history and len(st.session_state.history) > 3:
        hist_temps = [h["temperature_c"] for h in st.session_state.history[-30:]]
        hist_times = list(range(-len(hist_temps), 0))
        fc_times = list(range(0, n_steps))

        fig_fc = go.Figure()
        # Confidence band
        fig_fc.add_trace(go.Scatter(
            x=fc_times + fc_times[::-1],
            y=upper + lower[::-1],
            fill="toself",
            fillcolor="rgba(245,158,11,0.1)",
            line=dict(color="rgba(0,0,0,0)"),
            name="95% Confidence",
        ))
        # History
        fig_fc.add_trace(go.Scatter(
            x=hist_times, y=hist_temps,
            mode="lines", name="Observed",
            line=dict(color="#f59e0b", width=2),
        ))
        # Forecast
        fig_fc.add_trace(go.Scatter(
            x=fc_times, y=fc,
            mode="lines+markers", name="Forecast",
            line=dict(color="#06b6d4", width=2, dash="dash"),
            marker=dict(size=4),
        ))
        fig_fc.add_vline(x=0, line_color="#8b949e", line_dash="dash", line_width=1)
        fig_fc.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=10),
            height=300,
            margin=dict(l=50, r=20, t=30, b=40),
            xaxis=dict(
                title="Steps (← past | future →)",
                gridcolor="#21262d",
            ),
            yaxis=dict(
                title="Temperature (°C)",
                gridcolor="#21262d",
            ),
            legend=dict(orientation="h", y=1.12, font=dict(size=10)),
            title=dict(
                text="Holt's Double Exponential Smoothing -- Temperature Forecast",
                font=dict(size=12, color="#8b949e"),
            ),
        )
        st.plotly_chart(fig_fc, use_container_width=True)

        f1, f2, f3 = st.columns(3)
        with f1:
            st.metric("Predicted (next step)", f"{fc[0]:.1f} °C")
        with f2:
            st.metric("Predicted (+5 steps)", f"{fc[min(4, n_steps-1)]:.1f} °C")
        with f3:
            trend_dir = "📈 Rising" if fc[-1] > fc[0] else "📉 Falling" if fc[-1] < fc[0] else "➡️ Flat"
            st.metric("Trend", trend_dir)
    else:
        st.info("Start the simulation to see temperature forecasts.")

# ── Tab 3: Day-Ahead Optimal Plan ────────────────────────────
with ai_tab3:
    planner = st.session_state.ai_planner
    start_h = st.session_state.sim_time.hour
    start_t = current_state["temperature_c"]
    schedule = planner.plan(start_temp=start_t, start_hour=start_h)

    # Build visualization
    sched_hours = [s["hour"] for s in schedule]
    sched_temps = [s["expected_temp"] for s in schedule]
    sched_actions = [s["action"] for s in schedule]
    action_num = [{"CHARGE": 2, "DISCHARGE": 0, "STORE": 1}[a] for a in sched_actions]

    pcol1, pcol2 = st.columns([3, 1])
    with pcol1:
        fig_plan = go.Figure()
        fig_plan.add_trace(go.Scatter(
            x=[f"{h:02d}:00" for h in sched_hours],
            y=sched_temps,
                mode="lines+markers",
            name="Expected Temp",
            line=dict(color="#f59e0b", width=2),
            marker=dict(
                size=8,
                color=["#f59e0b" if a == "CHARGE" else "#3b82f6" if a == "DISCHARGE" else "#10b981" for a in sched_actions],
                line=dict(width=1, color="#0d1117"),
            ),
        ))
        fig_plan.add_hline(y=300, line_dash="dot", line_color="#8b949e",
                           annotation_text="Min Discharge (300°C)", line_width=1,
                           annotation_font=dict(size=9, color="#8b949e"))
        fig_plan.add_hline(y=600, line_dash="dot", line_color="#f59e0b",
                           annotation_text="Target (600°C)", line_width=1,
                           annotation_font=dict(size=9, color="#f59e0b"))
        # Shade peak hours
        for sh in schedule:
            if 17 <= sh["hour"] < 22:
                fig_plan.add_vrect(
                    x0=f"{sh['hour']:02d}:00",
                    x1=f"{(sh['hour']+1) % 24:02d}:00",
                    fillcolor="rgba(239,68,68,0.07)",
                    line_width=0,
                )
        fig_plan.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=10),
            height=300,
            margin=dict(l=50, r=20, t=30, b=40),
            xaxis=dict(title="Hour", gridcolor="#21262d"),
            yaxis=dict(title="Temperature (°C)", gridcolor="#21262d", range=[0, 850]),
            title=dict(
                text="Dynamic Programming -- Optimal 24h Schedule",
                font=dict(size=12, color="#8b949e"),
            ),
        )
        st.plotly_chart(fig_plan, use_container_width=True)

    with pcol2:
        st.markdown("**Planned Actions**")
        for s in schedule:
            icon = "🟠" if s["action"] == "CHARGE" else "🔵" if s["action"] == "DISCHARGE" else "🟢"
            peak_mark = " ⚡" if 17 <= s["hour"] < 22 else ""
            st.caption(f"{icon} **{s['hour']:02d}:00** {s['action']}{peak_mark} → {s['expected_temp']}°C")

# ── Tab 4: Anomaly Detection ─────────────────────────────────
with ai_tab4:
    detector = st.session_state.ai_anomaly

    a1, a2 = st.columns([1, 1])
    with a1:
        st.metric("Detection Window", f"{detector.window} samples")
        st.metric("Z-Score Threshold", f"{detector.threshold}")
        st.metric("Alerts Logged", str(len(detector.alerts)))

    with a2:
        if detector.alerts:
            st.markdown("**Recent Anomaly Alerts**")
            for alert in detector.alerts[-5:]:
                st.error(f"⚠️ {alert}", icon="🔍")
        else:
            st.success("✅ No anomalies detected. System behaviour is nominal.")

    if detector.deviations and len(detector.deviations) > 2:
        devs = list(detector.deviations)
        fig_dev = go.Figure()
        fig_dev.add_trace(go.Scatter(
            y=devs, mode="lines",
            line=dict(color="#06b6d4", width=1.5),
            name="Rate Deviation",
        ))
        mean_d = sum(devs) / len(devs)
        std_d = (sum((d - mean_d) ** 2 for d in devs) / len(devs)) ** 0.5
        fig_dev.add_hline(
            y=mean_d + detector.threshold * std_d,
            line_dash="dash", line_color="#ef4444", line_width=1,
            annotation_text="Anomaly Threshold",
            annotation_font=dict(color="#ef4444", size=9),
        )
        fig_dev.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#8b949e", size=10),
            height=200,
            margin=dict(l=40, r=20, t=30, b=30),
            xaxis=dict(title="Sample", gridcolor="#21262d"),
            yaxis=dict(title="Deviation (°C/s)", gridcolor="#21262d"),
            title=dict(
                text="Statistical Anomaly Detector -- Rate Deviation",
                font=dict(size=12, color="#8b949e"),
            ),
        )
        st.plotly_chart(fig_dev, use_container_width=True)
    else:
        st.info("Anomaly detector needs more data. Run the simulation to start monitoring.")


# ════════════════════════════════════════════════════════════════
# JSON API OUTPUT
# ════════════════════════════════════════════════════════════════
st.divider()
with st.expander("📋 **JSON API Output** -- Dashboard-Parseable", expanded=False):
    json_obj = {
        "timestamp": current_state["timestamp"],
        "system_status": current_state["system_status"],
        "temperature_c": current_state["temperature_c"],
        "energy_stored_kj": current_state["energy_stored_kj"],
        "grid_price_mode": current_state["grid_price_mode"],
        "renewable_availability": current_state["renewable_availability"],
        "ai_recommendation": current_state["ai_recommendation"],
        "safety_alert": current_state["safety_alert"],
    }
    st.code(json.dumps(json_obj, indent=2), language="json")


# ════════════════════════════════════════════════════════════════
# DATA TABLE
# ════════════════════════════════════════════════════════════════
if st.session_state.history:
    with st.expander("📊 Raw Data Table (last 50 readings)"):
        df_table = pd.DataFrame(st.session_state.history[-50:])
        st.dataframe(df_table, use_container_width=True, hide_index=True)


# ╔══════════════════════════════════════════════════════════════╗
# ║  SMART MANAGEMENT & DIAGNOSTIC FRAMEWORK (Tiers 1-5)      ║
# ╚══════════════════════════════════════════════════════════════╝
st.markdown("---")
st.markdown("## 🏭 Smart Management & Diagnostic Framework")

fw_tabs = st.tabs([
    "🔧 Predictive Maintenance",
    "⚡ Dynamic Optimization",
    "💰 Energy Arbitrage",
    "📊 Industrial Benchmark",
    "🌍 Market Validation",
])

# ────────────────────────────────────────────────────────────
# TIER 1 -- PREDICTIVE MAINTENANCE & SECURITY UNIT
# ────────────────────────────────────────────────────────────
with fw_tabs[0]:
    pm_c1, pm_c2 = st.columns(2)
    with pm_c1:
        st.markdown("### 🛡️ Insulation Health")
        health = st.session_state.fw_thermal.insulation_health
        health_colour = "#22c55e" if health >= 80 else ("#f59e0b" if health >= 50 else "#ef4444")
        st.markdown(
            f"<div style='text-align:center;padding:18px;background:#161b22;"
            f"border-radius:12px;border:1px solid {health_colour}'>"
            f"<span style='font-size:3rem;font-weight:700;color:{health_colour}'>"
            f"{health:.0f}%</span><br>"
            f"<span style='color:#8b949e'>Insulation Health Score</span></div>",
            unsafe_allow_html=True,
        )
        k_obs = st.session_state.fw_thermal.current_k
        k_nom = ThermalIntegrityMonitor.K_NOMINAL
        st.metric("Observed Decay Constant (k)", f"{k_obs:.6f} /s",
                   delta=f"{((k_obs - k_nom)/k_nom)*100:+.1f}% vs nominal")
        if st.session_state.fw_thermal.alerts:
            st.warning(st.session_state.fw_thermal.alerts[-1])

    with pm_c2:
        st.markdown("### 🌡️ Thermal Decay Curve")
        start = max(current_state["temperature_c"], 200)
        th_curve = st.session_state.fw_thermal.theoretical_curve(start, hours=12)
        dg_curve = st.session_state.fw_thermal.degraded_curve(start, hours=12)
        x_mins = [i for i in range(len(th_curve))]
        fig_decay = go.Figure()
        fig_decay.add_trace(go.Scatter(
            x=x_mins, y=th_curve, mode="lines", name="Theoretical (healthy)",
            line=dict(color="#22c55e", width=2)))
        fig_decay.add_trace(go.Scatter(
            x=x_mins, y=dg_curve, mode="lines", name="Observed (current k)",
            line=dict(color="#f59e0b", width=2, dash="dash")))
        fig_decay.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117", height=320,
            xaxis=dict(title="Minutes", color="#8b949e"),
            yaxis=dict(title="Temperature (°C)", color="#8b949e"),
            legend=dict(font=dict(color="#8b949e")),
            margin=dict(l=40, r=20, t=30, b=40),
        )
        st.plotly_chart(fig_decay, use_container_width=True)

    st.markdown("### 🔩 Piping & Extraction Diagnostics")
    pip_c1, pip_c2, pip_c3 = st.columns(3)
    core_t = current_state["temperature_c"]
    _amb = WeatherCompensator.morocco_ambient(
        st.session_state.sim_time.hour if hasattr(st.session_state, "sim_time") else 12)
    exp_out = st.session_state.fw_piping.expected_output(core_t, _amb)
    # Simulate a slightly degraded output
    sim_out = exp_out * (0.85 + 0.15 * random.random())
    st.session_state.fw_piping.update(core_t, sim_out, _amb)
    with pip_c1:
        st.metric("Heat Exchanger η",
                   f"{st.session_state.fw_piping.current_eta:.2f}",
                   delta=f"{((st.session_state.fw_piping.current_eta - PipingDiagnostics.ETA_NOMINAL)/PipingDiagnostics.ETA_NOMINAL)*100:+.1f}% vs nominal")
    with pip_c2:
        st.metric("Expected Output", f"{exp_out:.1f}°C")
    with pip_c3:
        st.metric("Actual Output", f"{sim_out:.1f}°C")
    if st.session_state.fw_piping.fouling_detected:
        st.error("⚠️ Fouling detected in copper piping! Schedule maintenance.")

# ────────────────────────────────────────────────────────────
# TIER 2 -- DYNAMIC OPERATIONAL OPTIMIZATION
# ────────────────────────────────────────────────────────────
with fw_tabs[1]:
    dyn_c1, dyn_c2 = st.columns(2)
    with dyn_c1:
        st.markdown("### ⚙️ Factory Load Profile")
        load_data = st.session_state.fw_load.load_profile_24h()
        hours_x = [d["hour"] for d in load_data]
        expected_y = [d["expected_kw"] for d in load_data]
        actual_y = [st.session_state.fw_load.actual_load(h) for h in hours_x]
        fig_load = go.Figure()
        fig_load.add_trace(go.Bar(
            x=hours_x, y=expected_y, name="Expected Load",
            marker_color="#3b82f6", opacity=0.5))
        fig_load.add_trace(go.Bar(
            x=hours_x, y=actual_y, name="Actual Load",
            marker_color="#f59e0b"))
        fig_load.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117", barmode="overlay", height=340,
            xaxis=dict(title="Hour of Day", color="#8b949e"),
            yaxis=dict(title="Power (kW)", color="#8b949e"),
            legend=dict(font=dict(color="#8b949e")),
            margin=dict(l=40, r=20, t=30, b=40),
        )
        st.plotly_chart(fig_load, use_container_width=True)

    with dyn_c2:
        st.markdown("### 🔄 Machine Status")
        _h = st.session_state.sim_time.hour if hasattr(st.session_state, "sim_time") else 12
        for m in st.session_state.fw_load.machines:
            scheduled = m.expected_running(_h)
            icon = "🟢" if m.is_running else ("🔴" if scheduled else "⚫")
            status = "Running" if m.is_running else ("STOPPED" if scheduled else "Off-schedule")
            st.markdown(
                f"**{icon} {m.name}** -- {m.power_kw} kW -- *{status}*")
        _surplus, _msg = st.session_state.fw_load.detect_surplus(_h)
        if _surplus > 0:
            st.success(f"⚡ Surplus detected: {_surplus:.0f} kW → Re-routing to sand battery")
        if st.session_state.fw_surplus_log:
            with st.expander("Surplus Event Log"):
                for msg in reversed(st.session_state.fw_surplus_log[-10:]):
                    st.caption(msg)

    st.markdown("### 🌤️ Ambient Weather Compensation")
    wth_c1, wth_c2, wth_c3, wth_c4 = st.columns(4)
    _h_now = st.session_state.sim_time.hour if hasattr(st.session_state, "sim_time") else 12
    amb_now = WeatherCompensator.morocco_ambient(_h_now)
    hlf = WeatherCompensator.heat_loss_factor(amb_now)
    adj_pwr = WeatherCompensator.adjusted_charge_power(HEATER_POWER / 1000, amb_now)
    with wth_c1:
        st.metric("Ambient Temp", f"{amb_now:.1f}°C")
    with wth_c2:
        st.metric("Heat Loss Factor", f"{hlf:.3f}")
    with wth_c3:
        st.metric("Adjusted Charge Power", f"{adj_pwr:.2f} kW")
    with wth_c4:
        savings_pwr = (HEATER_POWER / 1000) - adj_pwr
        st.metric("Power Saved", f"{savings_pwr:.2f} kW",
                   delta=f"{(savings_pwr / (HEATER_POWER/1000))*100:.1f}% reduction")

    st.markdown("### 💵 Activity-Based Costing")
    cst = st.session_state.fw_cost
    cst_c1, cst_c2, cst_c3 = st.columns(3)
    with cst_c1:
        st.metric("Cost / kWh(th)", f"{cst.cost_per_kwh_th:.2f} MAD")
    with cst_c2:
        st.metric("Cumulative Cost", f"{cst.total_cost_mad:.2f} MAD")
    with cst_c3:
        st.metric("Savings vs Baseline", f"{cst.savings_mad:.2f} MAD",
                   delta=f"{cst.savings_pct:.1f}%")
    if cst.history:
        cdf = pd.DataFrame(list(cst.history)[-200:])
        fig_cost = go.Figure()
        fig_cost.add_trace(go.Scatter(
            y=cdf["cumulative_cost"], mode="lines", name="ThermaSand Cost",
            line=dict(color="#22c55e", width=2)))
        fig_cost.add_trace(go.Scatter(
            y=cdf["cumulative_baseline"], mode="lines", name="Direct Electric (baseline)",
            line=dict(color="#ef4444", width=2, dash="dash")))
        fig_cost.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117", height=260,
            xaxis=dict(title="Ticks", color="#8b949e"),
            yaxis=dict(title="Cumulative Cost (MAD)", color="#8b949e"),
            legend=dict(font=dict(color="#8b949e")),
            margin=dict(l=40, r=20, t=20, b=40),
        )
        st.plotly_chart(fig_cost, use_container_width=True)

# ────────────────────────────────────────────────────────────
# TIER 3 -- STRATEGIC ENERGY ARBITRAGE
# ────────────────────────────────────────────────────────────
with fw_tabs[2]:
    st.markdown("### ⚡ Grid Smoothing: The Connection Trap")
    gs = ArbitrageEngine.grid_smoothing_profile()
    arb_c1, arb_c2 = st.columns(2)
    with arb_c1:
        fig_grid = go.Figure()
        fig_grid.add_trace(go.Bar(
            x=list(range(24)), y=gs["direct_profile"], name="Direct Electric (spiky)",
            marker_color="#ef4444", opacity=0.7))
        fig_grid.add_trace(go.Scatter(
            x=list(range(24)), y=gs["smooth_profile"], name="ThermaSand (constant)",
            mode="lines+markers", line=dict(color="#22c55e", width=3)))
        fig_grid.update_layout(
            template="plotly_dark", paper_bgcolor="#0d1117",
            plot_bgcolor="#0d1117", height=340,
            xaxis=dict(title="Hour of Day", color="#8b949e"),
            yaxis=dict(title="Grid Draw (MW)", color="#8b949e"),
            legend=dict(font=dict(color="#8b949e")),
            margin=dict(l=40, r=20, t=30, b=40),
        )
        st.plotly_chart(fig_grid, use_container_width=True)
    with arb_c2:
        st.markdown(
            f"""
            | Metric | Value |
            |--------|-------|
            | Peak Demand (Direct) | **{gs['peak_demand_mw']} MW** |
            | Smoothed Demand (ThermaSand) | **{gs['smooth_demand_mw']} MW** |
            | Peak Reduction | **{gs['peak_reduction_pct']:.0f}%** |
            | Daily Energy (Direct) | {gs['total_direct_mwh']} MWh |
            | Daily Energy (ThermaSand) | {gs['total_smooth_mwh']} MWh |
            """
        )
        cf = ArbitrageEngine.connection_fee_savings()
        st.markdown("#### 💰 Connection Fee Impact")
        st.markdown(
            f"""
            | | Cost (MAD) |
            |--|-----------|
            | Direct Electric Connection | **{cf['direct_connection_mad']:,.0f}** |
            | ThermaSand Connection | **{cf['smooth_connection_mad']:,.0f}** |
            | **Savings** | **{cf['savings_mad']:,.0f} MAD ({cf['savings_pct']:.0f}%)** |
            """
        )

    st.markdown("### ☀️ 24/7 Decarbonization -- Solar Oversizing")
    sol = ArbitrageEngine.solar_oversizing()
    sol_c1, sol_c2, sol_c3, sol_c4 = st.columns(4)
    with sol_c1:
        st.metric("Daily Demand", f"{sol['daily_demand_kwh']} kWh")
    with sol_c2:
        st.metric("Required Solar", f"{sol['required_solar_kw']} kW")
    with sol_c3:
        st.metric("Oversizing Factor", f"{sol['oversizing_factor']}×")
    with sol_c4:
        st.metric("CO₂ Avoided / Year", f"{sol['annual_co2_avoided_tons']} tons")

    # Solar capture visualization
    solar_gen = [0]*6 + [sol['required_solar_kw'] * min(1.0, math.sin(math.pi*(h-6)/12))
                         for h in range(6, 19)] + [0]*5
    demand_line = [sol['daily_demand_kwh']/24] * 24
    fig_sol = go.Figure()
    fig_sol.add_trace(go.Scatter(
        x=list(range(24)), y=solar_gen, fill="tozeroy",
        name="Solar Generation", line=dict(color="#f59e0b"),
        fillcolor="rgba(245,158,11,0.3)"))
    fig_sol.add_trace(go.Scatter(
        x=list(range(24)), y=demand_line, name="Avg Heat Demand",
        mode="lines", line=dict(color="#ef4444", width=2, dash="dash")))
    fig_sol.add_vrect(x0=18, x1=24, fillcolor="rgba(30,30,60,0.5)",
                      line_width=0, annotation_text="Night (stored heat)",
                      annotation_position="top left",
                      annotation=dict(font=dict(color="#8b949e")))
    fig_sol.add_vrect(x0=0, x1=6, fillcolor="rgba(30,30,60,0.5)",
                      line_width=0)
    fig_sol.update_layout(
        template="plotly_dark", paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117", height=300,
        xaxis=dict(title="Hour of Day", color="#8b949e"),
        yaxis=dict(title="Power (kW)", color="#8b949e"),
        legend=dict(font=dict(color="#8b949e")),
        margin=dict(l=40, r=20, t=30, b=40),
    )
    st.plotly_chart(fig_sol, use_container_width=True)
    st.info(
        f"☀️ Oversizing solar capture during {sol['peak_sun_hours']:.0f}h of sunshine "
        f"provides **100% green heat** through the remaining {24 - sol['peak_sun_hours']:.0f}h of darkness. "
        f"Annual production: **{sol['annual_solar_mwh']} MWh** -- **{sol['annual_co2_avoided_tons']} tons CO₂ avoided**."
    )

# ────────────────────────────────────────────────────────────
# TIER 4 -- INDUSTRIAL BENCHMARKING
# ────────────────────────────────────────────────────────────
with fw_tabs[3]:
    bm = IndustrialBenchmark.comparison_data()
    bm_c1, bm_c2 = st.columns([1, 1])
    with bm_c1:
        st.markdown("### 📊 Radar Comparison")
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=bm["direct_scores"] + [bm["direct_scores"][0]],
            theta=bm["labels"] + [bm["labels"][0]],
            fill="toself", name="Direct Electric",
            fillcolor="rgba(239,68,68,0.2)", line=dict(color="#ef4444"),
        ))
        fig_radar.add_trace(go.Scatterpolar(
            r=bm["thermasand_scores"] + [bm["thermasand_scores"][0]],
            theta=bm["labels"] + [bm["labels"][0]],
            fill="toself", name="ThermaSand M-TES",
            fillcolor="rgba(34,197,94,0.2)", line=dict(color="#22c55e"),
        ))
        fig_radar.update_layout(
            polar=dict(
                bgcolor="#0d1117",
                radialaxis=dict(visible=True, range=[0, 10], color="#8b949e"),
                angularaxis=dict(color="#8b949e"),
            ),
            template="plotly_dark", paper_bgcolor="#0d1117",
            height=420, showlegend=True,
            legend=dict(font=dict(color="#e6edf3")),
            margin=dict(l=60, r=60, t=40, b=40),
        )
        st.plotly_chart(fig_radar, use_container_width=True)

    with bm_c2:
        st.markdown("### 📋 Feature Comparison")
        for metric_name in bm["labels"]:
            detail = bm["details"][metric_name]
            d_score = IndustrialBenchmark.METRICS[metric_name]["direct"]
            t_score = IndustrialBenchmark.METRICS[metric_name]["thermasand"]
            st.markdown(
                f"**{metric_name}**  \n"
                f"🔴 Direct Electric: {d_score}/10 -- *{detail[0]}*  \n"
                f"🟢 ThermaSand: {t_score}/10 -- *{detail[1]}*"
            )
            st.markdown("---")

    st.markdown("### 📈 Return on Investment")
    roi = IndustrialBenchmark.roi_calculation()
    roi_c1, roi_c2, roi_c3, roi_c4 = st.columns(4)
    with roi_c1:
        st.metric("CAPEX", f"{roi['capex_mad']:,.0f} MAD")
    with roi_c2:
        st.metric("Annual Savings", f"{roi['annual_savings_mad']:,.0f} MAD")
    with roi_c3:
        st.metric("Payback Period", f"{roi['payback_years']} years")
    with roi_c4:
        st.metric("25-Year ROI", f"{roi['roi_pct']}%")

    # Cumulative savings curve
    years = list(range(roi["lifespan_years"] + 1))
    cum_savings = [-roi["capex_mad"] + roi["annual_savings_mad"] * y for y in years]
    fig_roi = go.Figure()
    colors = ["#ef4444" if v < 0 else "#22c55e" for v in cum_savings]
    fig_roi.add_trace(go.Bar(x=years, y=cum_savings, marker_color=colors, name="Net Position"))
    fig_roi.add_hline(y=0, line_dash="dash", line_color="#8b949e")
    fig_roi.update_layout(
        template="plotly_dark", paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117", height=300,
        xaxis=dict(title="Year", color="#8b949e"),
        yaxis=dict(title="Cumulative Net (MAD)", color="#8b949e"),
        margin=dict(l=40, r=20, t=20, b=40),
    )
    st.plotly_chart(fig_roi, use_container_width=True)

# ────────────────────────────────────────────────────────────
# TIER 5 -- MARKET VALIDATION
# ────────────────────────────────────────────────────────────
with fw_tabs[4]:
    st.markdown("### 🌍 Global Market Validation & Precedent")
    st.markdown(
        "ThermaSand follows a **globally validated industrial trend**. "
        "Sand-based thermal energy storage is being deployed across "
        "multiple continents to solve the industrial heat decarbonization challenge."
    )
    for ref in MARKET_REFERENCES:
        with st.container():
            rc1, rc2 = st.columns([1, 3])
            with rc1:
                st.markdown(
                    f"<div style='text-align:center;padding:16px;background:#161b22;"
                    f"border-radius:12px;border:1px solid #30363d'>"
                    f"<span style='font-size:2rem'>🏭</span><br>"
                    f"<b style='color:#f59e0b'>{ref['company']}</b><br>"
                    f"<span style='color:#8b949e'>{ref['country']}</span></div>",
                    unsafe_allow_html=True,
                )
            with rc2:
                st.markdown(f"**Capacity:** {ref['capacity']}  •  **Max Temp:** {ref['max_temp']}")
                st.markdown(f"**Use Case:** {ref['use_case']}")
                st.success(f"**Result:** {ref['result']}")
                st.caption(f"Year: {ref['year']}  •  {ref['url']}")
            st.markdown("---")

    st.markdown("### 🇲🇦 ThermaSand -- Morocco Advantage")
    ma_c1, ma_c2, ma_c3 = st.columns(3)
    with ma_c1:
        st.markdown(
            "<div style='text-align:center;padding:20px;background:#161b22;"
            "border-radius:12px;border:1px solid #f59e0b'>"
            "<span style='font-size:2.5rem'>☀️</span><br>"
            "<b style='font-size:1.3rem;color:#f59e0b'>3,000+ hrs/yr</b><br>"
            "<span style='color:#8b949e'>Solar Irradiance</span></div>",
            unsafe_allow_html=True,
        )
    with ma_c2:
        st.markdown(
            "<div style='text-align:center;padding:20px;background:#161b22;"
            "border-radius:12px;border:1px solid #22c55e'>"
            "<span style='font-size:2.5rem'>🏜️</span><br>"
            "<b style='font-size:1.3rem;color:#22c55e'>Abundant Sand</b><br>"
            "<span style='color:#8b949e'>Locally Sourced Media</span></div>",
            unsafe_allow_html=True,
        )
    with ma_c3:
        st.markdown(
            "<div style='text-align:center;padding:20px;background:#161b22;"
            "border-radius:12px;border:1px solid #3b82f6'>"
            "<span style='font-size:2.5rem'>🏗️</span><br>"
            "<b style='font-size:1.3rem;color:#3b82f6'>MASEN Support</b><br>"
            "<span style='color:#8b949e'>Government RE Investment</span></div>",
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════════════════════════════
# AUTO-REFRESH LOOP
# ════════════════════════════════════════════════════════════════
if st.session_state.sim_running or (
    st.session_state.mode == "esp32" and st.session_state.serial_connected
):
    time.sleep(0.4)
    st.rerun()
