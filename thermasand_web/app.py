from flask import Flask, render_template, request, jsonify
from collections import deque
import time

app = Flask(__name__)

# --- ROUTES ---


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/simulate")
def simulate_page():
    return render_template("simulate.html")


@app.route("/admin")
def admin_dashboard():
    return render_template("admin.html")


@app.route("/ai-core")
def ai_core():
    return render_template("ai_core.html")


# --- API FOR CALCULATION ---


@app.route("/api/calculate", methods=["POST"])
def calculate_feasibility():
    data = request.json

    current_fuel_cost_per_kwh_th = float(data["currentFuelCost"])
    current_efficiency = float(data["currentEfficiency"]) / 100.0

    daily_thermal_load_kwh = float(data["thermalLoad"]) * float(data["operationalHours"])

    peak_elec_price = 1.60  # MAD/kWh (Industry Peak)
    off_peak_elec_price = 0.80  # MAD/kWh (Night/Solar Surplus)
    thermasand_efficiency = 0.90  # Thermal-to-Thermal

    estimated_capex = daily_thermal_load_kwh * 3000

    years = list(range(11))
    baseline_costs = [0]
    thermasand_costs = [estimated_capex]

    annual_baseline_opex = (
        (daily_thermal_load_kwh / current_efficiency)
        * current_fuel_cost_per_kwh_th
        * 365
    )

    annual_thermasand_opex = (
        (daily_thermal_load_kwh / thermasand_efficiency) * off_peak_elec_price * 365
    )

    for i in range(1, 11):
        baseline_costs.append(baseline_costs[-1] + annual_baseline_opex)
        thermasand_costs.append(
            thermasand_costs[-1] + annual_thermasand_opex + (estimated_capex * 0.01)
        )

    total_savings_10y = baseline_costs[-1] - thermasand_costs[-1]
    annual_savings = annual_baseline_opex - annual_thermasand_opex
    savings_pct = (annual_savings / annual_baseline_opex * 100) if annual_baseline_opex > 0 else 0
    payback_years = (
        estimated_capex / (annual_baseline_opex - annual_thermasand_opex)
        if (annual_baseline_opex > annual_thermasand_opex)
        else 99
    )

    baseline_co2 = (
        (daily_thermal_load_kwh / current_efficiency) * 0.2 * 365 * 10 / 1000
    )
    thermasand_co2 = (
        (daily_thermal_load_kwh / thermasand_efficiency) * 0.08 * 365 * 10 / 1000
    )
    co2_saved = baseline_co2 - thermasand_co2

    return jsonify(
        {
            "years": years,
            "baselineCumulative": [round(x, 2) for x in baseline_costs],
            "thermasandCumulative": [round(x, 2) for x in thermasand_costs],
            "annualBaseline": round(annual_baseline_opex, 2),
            "annualThermasand": round(annual_thermasand_opex, 2),
            "annualSavings": round(annual_savings, 2),
            "savingsPct": round(savings_pct, 1),
            "totalSavings10y": round(total_savings_10y, 2),
            "monthlyBaseline": round(annual_baseline_opex / 12, 2),
            "monthlyThermasand": round(annual_thermasand_opex / 12, 2),
            "paybackYears": round(payback_years, 1),
            "co2Saved": round(co2_saved, 1),
        }
    )


# ---------------------------------------------------------------------------
# Real-time telemetry from ESP32
# The ESP32 sends ONLY temperature (format: T:<value>).
# PSI is set manually by admin via the dashboard.
# No dummy data — values stay at defaults until real data arrives.
# ---------------------------------------------------------------------------

def _safe_float(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _now_iso():
    return time.strftime("%Y-%m-%d %H:%M:%S")


telemetry_history = deque(maxlen=200)

# Starts empty — no dummy data. Dashboard shows "--" until ESP32 posts.
latest_telemetry = {
    "deviceId": None,
    "timestamp": None,
    "temperatureC": None,
    "psi": 0.0,       # Set manually by admin, not from ESP32
}


@app.route("/api/telemetry", methods=["GET", "POST"])
def telemetry_api():
    """
    POST — called by ESP32 bridge or Streamlit to push a new reading.
           Expects JSON: {"temperatureC": <float>, "deviceId": <string> (optional)}
    GET  — returns latest telemetry + history.
    """
    global latest_telemetry

    if request.method == "POST":
        data = request.json or {}
        latest_telemetry["deviceId"] = data.get("deviceId", latest_telemetry["deviceId"])
        latest_telemetry["timestamp"] = _now_iso()
        latest_telemetry["temperatureC"] = _safe_float(
            data.get("temperatureC"), latest_telemetry["temperatureC"]
        )
        # PSI can only be updated explicitly by admin (see /api/psi)
        telemetry_history.append(
            {
                "timestamp": latest_telemetry["timestamp"],
                "temperatureC": latest_telemetry["temperatureC"],
                "psi": latest_telemetry["psi"],
            }
        )
        return jsonify({"status": "ok"})

    return jsonify(
        {
            "latest": latest_telemetry,
            "history": list(telemetry_history),
        }
    )


# ---------------------------------------------------------------------------
# AI Core Compute API — mirrors the client-side engine for ESP32 integration
# POST {"temperature": float, "time": "HH:MM", "previous_temperature": float}
# Returns the full JSON output defined by the Intelligent Core spec.
# ---------------------------------------------------------------------------
@app.route("/api/ai-core/compute", methods=["POST"])
def ai_core_compute():
    data = request.json or {}
    temp = _safe_float(data.get("temperature"), 25.0)
    prev = _safe_float(data.get("previous_temperature"), temp)
    time_str = data.get("time", time.strftime("%H:%M"))

    parts = time_str.split(":")
    h = int(parts[0]) if len(parts) > 0 else 12
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0

    mass, cp, ambient = 15, 830, 25
    energy_j = mass * cp * max(0, temp - ambient)
    energy_kj = round(energy_j / 1000, 2)

    dt = _safe_float(data.get("time_delta"), 1.0)
    rate = (temp - prev) / dt if dt > 0 else 0
    if rate > 0.2:
        status = "CHARGING"
    elif rate < -0.2:
        status = "DISCHARGING"
    else:
        status = "STORAGE"

    is_peak = 17 <= h < 22
    grid_mode = "PEAK" if is_peak else "OFF-PEAK"

    is_solar = 8 <= h < 18
    is_wind = h >= 22 or h < 5
    renew = "HIGH" if (is_solar or is_wind) else "LOW"

    if not is_peak and temp < 600:
        if is_solar:
            rec = "SOLAR AVAILABLE + OFF-PEAK — GREEN CHARGE OPTIMAL"
        elif is_wind:
            rec = "WIND AVAILABLE + OFF-PEAK — INITIATE NIGHT CHARGE"
        else:
            rec = "GRID PRICE LOW — INITIATE CHARGING"
    elif is_peak and temp > 300:
        rec = "PEAK PRICING ACTIVE — DISCHARGE STORED ENERGY (AVOID GRID)"
    elif is_peak and temp <= 300:
        rec = "CRITICAL RESERVE — INSUFFICIENT THERMAL ENERGY — DO NOT USE"
    else:
        rec = "THERMAL CAPACITY NEAR MAX — MAINTAIN STORAGE"

    safety = "NORMAL"
    if temp > 800:
        safety = "CRITICAL"
    elif temp > 650:
        safety = "WARNING"

    return jsonify(
        {
            "timestamp": f"{h:02d}:{m:02d}:{s:02d}",
            "system_status": status,
            "temperature_c": round(temp, 1),
            "energy_stored_kj": energy_kj,
            "grid_price_mode": grid_mode,
            "renewable_availability": renew,
            "ai_recommendation": rec,
            "safety_alert": safety,
        }
    )


@app.route("/api/psi", methods=["GET", "POST"])
def psi_api():
    """
    POST — admin sets the PSI manually: {"psi": <float>}
    GET  — returns current PSI value.
    """
    if request.method == "POST":
        data = request.json or {}
        latest_telemetry["psi"] = _safe_float(data.get("psi"), latest_telemetry["psi"])
        return jsonify({"status": "ok", "psi": latest_telemetry["psi"]})

    return jsonify({"psi": latest_telemetry["psi"]})


if __name__ == "__main__":
    app.run(debug=True)
