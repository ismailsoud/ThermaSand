# ThermaSand — Technical Guide

**For new team members — everything you need to understand the system.**

Last updated: March 2026

---

## Table of Contents

1. [What is ThermaSand?](#1-what-is-thermasand)
2. [The Big Picture — Why This Exists](#2-the-big-picture)
3. [System Architecture Overview](#3-system-architecture-overview)
4. [Hardware Layer](#4-hardware-layer)
5. [Software Architecture](#5-software-architecture)
6. [AI Engine — The Four Algorithms](#6-ai-engine)
7. [Smart Management Framework — The Six Tiers](#7-smart-management-framework)
8. [The Control Loop — How Everything Runs Together](#8-the-control-loop)
9. [The Dashboard (Streamlit UI)](#9-the-dashboard)
10. [The Flask Web App](#10-the-flask-web-app)
11. [How to Run the Project](#11-how-to-run-the-project)
12. [Key Constants and Parameters](#12-key-constants-and-parameters)
13. [File Map](#13-file-map)

---

## 1. What is ThermaSand?

ThermaSand is a **sand battery** — a system that stores heat in silica sand (SiO2) and releases it on demand. Think of it like a rechargeable battery, but instead of storing electricity, it stores **thermal energy** at temperatures up to 800 °C.

The twist: the system is controlled by **AI algorithms** that decide *when* to charge, *when* to discharge, and *when* to just hold the heat — all based on electricity prices, renewable energy availability, safety conditions, and industrial demand.

### The one-sentence version

> Charge sand with cheap/green electricity, store heat for hours, discharge when energy is expensive or the grid is stressed.

---

## 2. The Big Picture

### The Two Traps ThermaSand Solves

**Trap 1 — The Connection Trap:**
A factory needs 50 MW of heat but the local grid substation only supplies 5 MW. Upgrading costs millions. ThermaSand draws a gentle 2 MW constantly (24/7), stores it as heat, then discharges 50 MW worth of thermal energy during factory hours. No grid upgrade needed.

**Trap 2 — The Decarbonization Trap:**
Solar produces power for ~8 hours/day. The factory runs 24/7. Without storage, the factory burns fossil fuel at night. ThermaSand captures solar surplus during the day and provides heat all night. 24/7 green heat from an 8-hour solar window.

### Why Sand?

| Property | Value |
|----------|-------|
| Max operating temperature | 800 °C (stable beyond 1,000 °C) |
| Specific heat capacity (Cp) | 700–1,000 J/(kg·K) |
| Cost | Extremely cheap, locally available in Morocco |
| Toxicity | Zero — inert, non-flammable, no leaks |
| Lifetime | Practically unlimited (no degradation cycles) |
| Thermal-to-thermal efficiency | ~95% (vs 60-65% for lithium battery round-trip) |

---

## 3. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTROL UNIT (PC / Server)                │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  AI Engine    │  │   Smart      │  │   Dashboard      │  │
│  │              │  │  Framework   │  │  (Streamlit)     │  │
│  │ - Q-Learning │  │ - Integrity  │  │  - Gauges        │  │
│  │ - Forecaster │  │ - Piping Dx  │  │  - Charts        │  │
│  │ - Anomaly    │  │ - Load Bal.  │  │  - AI Panel      │  │
│  │ - Planner    │  │ - Weather    │  │  - Framework     │  │
│  │              │  │ - Cost       │  │    Tabs          │  │
│  │              │  │ - Arbitrage  │  │                  │  │
│  │              │  │ - Benchmark  │  │                  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         └─────────┬───────┘                    │            │
│                   │  ┌─────────────────────────┘            │
│                   │  │                                      │
│              ┌────▼──▼──────┐                               │
│              │  Serial/WiFi │                               │
│              └──────┬───────┘                               │
└─────────────────────┼───────────────────────────────────────┘
                      │
           ┌──────────▼──────────┐
           │    ESP32 (MCU)      │
           │  - MAX6675 sensor   │
           │  - Serial @ 115200  │
           │  - Format: T:<temp> │
           └──────────┬──────────┘
                      │
        ┌─────────────▼──────────────┐
        │     PHYSICAL PROTOTYPE     │
        │                            │
        │  ┌──────────────────────┐  │
        │  │  Silica Sand (15 kg) │  │
        │  │                      │  │
        │  │  ┌────────────────┐  │  │
        │  │  │ Copper Coil    │  │  │
        │  │  │ (12mm × 6m)   │  │  │
        │  │  └────────────────┘  │  │
        │  │                      │  │
        │  │  ┌────────────────┐  │  │
        │  │  │ Heater 1500W   │  │  │
        │  │  └────────────────┘  │  │
        │  │                      │  │
        │  │  K-Type Thermocouple │  │
        │  └──────────────────────┘  │
        │  Rock Wool Insulation      │
        │  (100 mm thick)            │
        └────────────────────────────┘
```

The system has three layers:

1. **Physical layer** — Sand, heater, copper coil, thermocouple, insulation
2. **Microcontroller layer** — ESP32 reads the thermocouple and sends data over serial
3. **Intelligence layer** — Python (AI engine + Smart Framework + Dashboard)

---

## 4. Hardware Layer

### 4.1 The Sand Tank

- **Medium:** Silica sand (SiO2), 15 kg in the prototype
- **Insulation:** Rock wool, 100 mm thick
- **Thermal constant:** k_nominal = 4.0 × 10⁻⁴ /s (healthy insulation)

The insulation quality is modeled by Newton's law of cooling:

```
dT/dt = -k × (T_core - T_ambient)
```

When k_observed starts exceeding k_nominal, the insulation is degrading.

### 4.2 The Heater

- **Type:** Resistive heating element, 1,500 W, 220 V AC
- **Charge rate:** HEATER_POWER / (MASS × Cp) ≈ 0.12 °C/s

At full power, the 15 kg sand goes from 25 °C to 600 °C in about 80 minutes.

### 4.3 The Heat Exchanger

- **Type:** Helical copper serpentine coil
- **Dimensions:** 12 mm outer diameter, 6 m length
- **Function:** Air flows through the coil, picks up heat from the sand, exits hot
- **Nominal efficiency (η):** 0.75

The exchanger effectiveness is monitored with:

```
η_obs = (T_output - T_ambient) / (T_core - T_ambient)
```

When η drops below 0.55, fouling (internal deposits) is detected.

### 4.4 The Sensor — ESP32 + MAX6675

The ESP32 firmware is minimal — it reads the K-type thermocouple via the MAX6675 chip and sends the temperature over serial:

```
Pin Layout:
  GPIO 19 → SO  (Serial Out)
  GPIO 5  → CS  (Chip Select)
  GPIO 18 → CLK (Clock)

Serial: 115200 baud
Output format: "T:<temperature>"    (e.g., "T:347.25")
Sampling rate: 2 Hz (every 500ms)
```

The ESP32 only reads temperature. PSI (pressure) is set manually in the admin dashboard. The firmware includes a safety check — if the sensor returns NaN or negative values, it sends `ERROR:SENSOR_NOT_READY`.

### 4.5 Actionneurs (Actuators)

In the full system design (beyond the prototype), three actuators are controlled:

| Actuator | Controls | Signal Type |
|----------|----------|-------------|
| Solid-state relay | Heater ON/OFF (or PWM) | Binary or modulated |
| Solenoid valve | Air circuit open/close | Binary |
| Variable-speed blower | Air flow rate through coil | Analog (0-100%) |

---

## 5. Software Architecture

### File Map

```
thermasand_web/
├── ai_engine.py          ← The 4 AI algorithms
├── smart_framework.py    ← The 6-tier management framework
├── dashboard.py          ← Streamlit real-time dashboard (main UI)
├── app.py                ← Flask web app (landing page, calculator, admin)
├── requirements.txt      ← Python dependencies
├── .streamlit/
│   └── config.toml       ← Dark theme config
├── templates/
│   ├── base.html         ← Layout + nav
│   ├── index.html        ← Landing page
│   ├── simulate.html     ← Feasibility calculator
│   ├── admin.html        ← Admin dashboard
│   └── ai_core.html      ← Intelligent Core UI
└── esp32/
    └── thermasand_ds18b20/
        └── thermasand_ds18b20.ino   ← ESP32 firmware
```

### The Two-Layer Software Hierarchy

The software follows the same safety-first hierarchy as described in the patent:

```
┌────────────────────────────────────────────────┐
│           SAFETY LAYER (Priority 1)            │
│  Always runs first. Can override anything.     │
│                                                │
│  1. Hardware relay (physical cutoff)           │
│  2. Software T > T_crit check                 │
│  3. Anomaly detector (z-score)                │
│  4. Temperature forecast (Holt)               │
├────────────────────────────────────────────────┤
│         OPTIMIZATION LAYER (Priority 2)        │
│  Only runs if Safety Layer says "all clear."   │
│                                                │
│  5. Q-Learning dispatch agent                 │
│  6. Day-ahead DP planner                      │
│  7. Load balancer                             │
│  8. Weather compensator                       │
│  9. Cost calculator                           │
│ 10. Carbon classifier                         │
├────────────────────────────────────────────────┤
│             MANUAL OVERRIDE (Priority 3)       │
│  Operator commands via UI.                     │
│  Blocked if Safety Layer says no.              │
└────────────────────────────────────────────────┘
```

The key rule: **No optimization decision can override a safety decision. Ever.**

---

## 6. AI Engine — The Four Algorithms

All four are in `ai_engine.py`.

### 6.1 Q-Learning Dispatch Agent (`DispatchAgent`)

This is the brain that decides: **CHARGE, DISCHARGE, or STORE?**

#### What is Q-Learning?

Q-Learning is a reinforcement learning algorithm. The agent doesn't have pre-programmed rules. Instead, it *learns* the best policy by trial and error:

1. It observes the current **state** (temperature, time, prices, renewables)
2. It picks an **action** (charge, discharge, store)
3. It receives a **reward** (good action = positive, bad action = negative)
4. It updates its **Q-table** — a lookup table of "how good is action A in state S?"
5. Over thousands of iterations, the Q-table converges to the optimal policy.

#### State Space

The state is a tuple of 4 dimensions, discretized for the Q-table:

| Dimension | Values | Count |
|-----------|--------|-------|
| Temperature bin | 0-100, 100-200, ..., 700-800 °C | 8 |
| Hour of day | 0-23 | 24 |
| Is peak pricing? | 0 or 1 (peak = 17:00–22:00) | 2 |
| Is renewable available? | 0 or 1 (solar 08-18, wind 22-05) | 2 |

**Total state space: 8 × 24 × 2 × 2 = 768 states**

#### Action Space

3 actions: `CHARGE (0)`, `DISCHARGE (1)`, `STORE (2)`

#### Q-Table

A 5D numpy array: `shape = (8, 24, 2, 2, 3)` — one Q-value per state-action pair.

#### The Bellman Update (core of Q-Learning)

After each step, the Q-value is updated:

```
Q(S, A) ← Q(S, A) + α × [R + γ × max_a' Q(S', a') - Q(S, A)]
```

Where:
- `α = 0.1` — learning rate (how fast we update)
- `γ = 0.95` — discount factor (how much we value future rewards)
- `R` — immediate reward
- `S'` — next state after taking action A

#### Reward Function

This is the most important design decision — it encodes our business objectives:

| Scenario | Reward |
|----------|--------|
| Charge during renewable availability | +3.0 |
| Charge during off-peak (grid) | +1.0 |
| Charge during peak (expensive!) | -3.0 |
| Discharge during peak with reserves (T > 300°C) | +3.0 |
| Discharge during off-peak | -2.0 |
| Temperature > 800 °C (safety violation) | -5.0 |
| Discharge when nearly empty (T < 30°C) | -5.0 |
| Store when full during off-peak | +0.5 |
| Store during peak with reserves (missed opportunity) | -0.5 |
| Charge when reserves low (T < 300°C) | +0.5 bonus |

#### Exploration vs Exploitation (ε-greedy)

- `ε` starts at 0.25 (25% random exploration)
- Decays by `× 0.9995` each step
- Minimum: 0.05 (always keeps 5% exploration)

Early on, the agent explores randomly. As it learns, it mostly exploits its Q-table but occasionally tries random actions to discover better strategies.

#### What the Agent Learns

After ~3,000 simulated hours, the agent converges to a policy like:

- **00:00–05:00** — CHARGE (wind available, off-peak → cheapest power)
- **06:00–07:00** — STORE (waiting for solar)
- **08:00–16:00** — CHARGE (solar available → free power)
- **17:00–21:00** — DISCHARGE (peak pricing → avoid expensive grid)
- **22:00–23:00** — CHARGE (wind kicks in, off-peak)

This is not hardcoded — the agent *discovers* this strategy on its own.

---

### 6.2 Temperature Predictor (`TemperaturePredictor`)

**Algorithm:** Holt's Double Exponential Smoothing

This predicts where the temperature is heading N steps into the future. It's used by the safety layer to preemptively cut the heater before the temperature actually reaches the critical threshold.

#### How It Works

Holt's method tracks two components:

1. **Level** (Lₜ) — the current smoothed value
2. **Trend** (Tₜ) — the rate of change

Update equations on each new reading:

```
Level:  Lₜ = α × Yₜ + (1 - α) × (Lₜ₋₁ + Tₜ₋₁)
Trend:  Tₜ = β × (Lₜ - Lₜ₋₁) + (1 - β) × Tₜ₋₁
```

Forecast k steps ahead:

```
Ŷₜ₊ₖ = Lₜ + k × Tₜ
```

#### Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| α (alpha) | 0.4 | Level smoothing — higher = more responsive to new data |
| β (beta) | 0.3 | Trend smoothing — higher = trend changes faster |
| History window | 200 readings | Rolling buffer for residual variance |

#### Confidence Intervals

The predictor also computes 95% prediction intervals based on residual variance:

```
Upper/Lower = Forecast ± 1.96 × σ_residual × √(step)
```

The uncertainty grows with the square root of the forecast horizon — predictions further out are less certain.

#### Safety Integration

If the forecast hits `T_warn` (e.g., 650 °C) → reduce power.
If the forecast hits `T_crit` (e.g., 800 °C) → immediate heater cutoff + max extraction.

---

### 6.3 Anomaly Detector (`AnomalyDetector`)

**Algorithm:** Rolling Z-Score on rate-of-change deviations

This catches unexpected thermal behavior — sensor failures, insulation breaches, stuck relays, etc.

#### How It Works

1. For each time step, compute the **observed rate of change**: `rate = (T_now - T_prev) / dt`
2. Compare against the **expected rate** for the current action:

| Action | Expected Rate (°C/s) |
|--------|---------------------|
| CHARGING | +0.12 |
| DISCHARGING | -0.15 |
| STORAGE | -0.005 |

3. Compute the **deviation**: `d = |rate_observed - rate_expected|`
4. Keep a rolling window of deviations (default: 30 samples)
5. Compute the **z-score**: `z = (d - mean_d) / std_d`
6. If `z > threshold` (default: 2.5), flag an anomaly

#### Example

If the system is in STORAGE mode, we expect the temperature to drop at about -0.005 °C/s. If instead it's dropping at -0.08 °C/s (16× faster), the z-score will spike and an anomaly is declared — probably an insulation breach.

---

### 6.4 Day-Ahead Planner (`DayAheadPlanner`)

**Algorithm:** Backward-Induction Dynamic Programming

This computes the **cost-optimal 24-hour schedule** — which hours to charge, discharge, or store.

#### The Optimization Problem

```
Minimize: Σ (grid_cost × energy_consumed) − (peak_value × energy_discharged)
Subject to: 25 °C ≤ T ≤ 800 °C at all times
```

#### State Space

Temperature is discretized into 17 bins of 50 °C each: 25, 75, 125, ..., 825 °C.

#### Transition Model

For each action, the planner predicts the next temperature:

| Action | Transition |
|--------|-----------|
| CHARGE | T_{t+1} = T_t + charge_rate_per_hour |
| DISCHARGE | T_{t+1} = T_t - discharge_rate_per_hour |
| STORE | T_{t+1} = T_t - loss_rate_per_hour |

#### Cost Model (Morocco ONEE Tariffs)

| Period | Cost (MAD/kWh) |
|--------|---------------|
| Peak (17:00–22:00) | 1.60 |
| Off-peak | 0.80 |
| Renewable discount (solar/wind hours) | 70% reduction |
| Avoided peak energy value | 2.00 MAD/kWh |

#### Algorithm

1. **Backward pass** (hour 24 → hour 0): For each temperature bin, find the cheapest action considering the future cost-to-go
2. **Forward pass** (hour 0 → hour 24): Starting from the actual temperature, follow the optimal actions to build the schedule

Safety penalties are added for:
- Temperature > 780 °C: +5.0 MAD
- Discharging below 50 °C: +10.0 MAD

The result is a list of 24 entries: `{hour, action, expected_temp, cost}`.

---

## 7. Smart Management Framework — The Six Tiers

All in `smart_framework.py`. These modules run alongside the AI engine and provide industrial-grade monitoring and optimization.

### Tier 1 — Predictive Maintenance

#### ThermalIntegrityMonitor

Compares the real cooling curve against Newton's theoretical model to detect insulation degradation.

**How it works:**

During STORAGE mode, the system observes how fast the sand cools. From Newton's law:

```
k_obs = -(dT/dt) / (T_core - T_ambient)
```

The **insulation health score** is:

```
H = max(0, min(100, (1 - (k_obs/k_nominal - 1) / 2) × 100))
```

- H = 100%: k_obs matches k_nominal — insulation is perfect
- H = 50%: k_obs is 2× k_nominal — significant degradation
- H = 0%: k_obs is 3× k_nominal — critical failure

When H < 60%, a maintenance alert is generated.

The monitor also generates two curves for visualization:
- **Theoretical curve:** How the system *should* cool with perfect insulation
- **Observed curve:** How the system *actually* cools (using measured k)

The gap between these curves is the degradation.

#### PipingDiagnostics

Monitors heat exchanger effectiveness (η) to detect fouling (mineral deposits inside the copper coil).

```
η_obs = (T_output - T_ambient) / (T_core - T_ambient)
```

- η_nominal = 0.75 (clean copper)
- η < 0.55 → fouling detected → schedule maintenance

---

### Tier 2 — Dynamic Operational Optimization

#### DynamicLoadBalancer

Monitors factory machines and redirects surplus energy to the sand battery when machines stop unexpectedly.

Default factory model:

| Machine | Power (kW) | Schedule |
|---------|-----------|----------|
| Oven A | 45 | 06:00–18:00 |
| Dryer B | 30 | 08:00–20:00 |
| Steriliser C | 25 | 07:00–15:00 |
| Boiler D | 50 | 24/7 |

When a machine stops unexpectedly during its scheduled hours:
```
surplus = expected_load - actual_load
```
If surplus > 5 kW, it's redirected to charge the sand battery (free energy!).

In simulation mode, machines have a 3% chance of random stoppage per tick, simulating real-world factory conditions.

#### WeatherCompensator

Adjusts charge power based on Morocco ambient temperature.

Higher ambient → lower heat loss → less charge power needed.

```python
heat_loss_factor = max(0.3, (600 - T_ambient) / (600 - 25))
adjusted_power = nominal_power × heat_loss_factor
```

At 25°C ambient, factor = 1.0 (full power). At 40°C, it's slightly less. This saves energy on hot days.

The ambient model uses a sinusoidal day-night cycle based on Casablanca-region monthly averages.

#### CostCalculator

Activity-based costing that tracks real-time cost per thermal kWh and compares against a "direct electric" baseline (always paying peak prices).

Tracks: cumulative energy (kWh), cumulative cost (MAD), savings vs baseline (MAD and %).

---

### Tier 3 — Strategic Energy Arbitrage

#### ArbitrageEngine

Three calculations:

1. **Grid smoothing** — Compares a factory drawing 50 MW during work hours (spiky) vs ThermaSand drawing 2 MW constantly (flat). Shows the 96% peak reduction.

2. **Connection fee savings** — At ~150,000 MAD per MW of peak capacity, going from 50 MW to 2 MW saves 7,200,000 MAD in connection fees.

3. **Solar oversizing** — Calculates the solar array size needed for 24/7 decarbonization: `oversizing_factor = 24 / peak_sun_hours`. For 6h of sun, you need a 4× oversized array. The surplus is stored in the sand battery.

---

### Tier 4 — Industrial Benchmarking

#### IndustrialBenchmark

Radar chart comparison: ThermaSand vs Direct Electric Heating on 6 axes (0-10 scale):

| Metric | Direct Electric | ThermaSand |
|--------|----------------|------------|
| Grid Impact | 2 | 9 |
| Operating Cost | 3 | 8 |
| Reliability | 3 | 9 |
| Scalability | 4 | 9 |
| Safety | 5 | 9 |
| Decarbonization | 4 | 9 |

Also computes ROI: at 450,000 MAD CAPEX and 180,000 MAD/year savings → 2.5 year payback, 900% ROI over 25 years.

---

### Tier 5 — Market Validation

Reference data on global companies doing similar work:
- **Polar Night Energy** (Finland) — 100-tonne sand battery, 600°C, district heating
- **NREL / Sandia** (USA) — Particle-based TES research for CSP
- **Rondo Energy** (USA) — Industrial heat batteries, >1500°C

ThermaSand's differentiation: AI-controlled, pneumatic copper extraction, Morocco-optimized, integrated predictive maintenance.

---

## 8. The Control Loop — How Everything Runs Together

Every tick (0.4 real seconds in simulation mode), the system executes this sequence:

```
1. ACQUIRE
   │  Read temperature from sensor (ESP32) or simulation model
   │  Read system clock
   │
2. PREPROCESS
   │  Compute: dT/dt, stored energy (E = m×Cp×ΔT), η_exchanger
   │  Determine: is_peak? is_renewable? ambient temp?
   │  Build state vector for AI
   │
3. FEED SMART FRAMEWORK
   │  Update ThermalIntegrityMonitor (insulation health)
   │  Update PipingDiagnostics (exchanger η)
   │  Check DynamicLoadBalancer for surplus
   │  Record CostCalculator entry
   │
4. SAFETY CHECK (Priority 1)
   │  If T > 800°C → CRITICAL: cut heater, max extraction
   │  If T > 650°C → WARNING: reduce or stop charging
   │  Run AnomalyDetector → if z > 2.5, restrict charging
   │  Run TemperaturePredictor → if forecast hits T_crit, preemptive cutoff
   │
5. OPTIMIZATION (Priority 2 — only if safety allows)
   │  If control_mode == "ai":
   │    Q-Learning agent picks action, gets reward, updates Q-table
   │  If control_mode == "rules":
   │    Simple if/else logic based on price + temperature
   │
6. APPLY ACTION
   │  Update simulation temperature:
   │    CHARGE:    T += 0.12 × dt
   │    DISCHARGE: T -= 0.15 × dt
   │    STORE:     T -= 0.005 × dt
   │  Clamp to [25, 850] °C
   │
7. RECORD & DISPLAY
   │  Append to history buffer (max 500 entries)
   │  Update all dashboard charts and metrics
   │
8. ADVANCE CLOCK
   │  sim_time += dt × speed_multiplier
   │
9. LOOP (auto-rerun after 0.4s)
```

### Simulation Speed

| Setting | dt per tick | Meaning |
|---------|-----------|---------|
| Real-time (1×) | 0.4s | Real-time |
| Fast (10×) | 4s | 10 seconds pass per tick |
| 1 min/sec (60×) | 24s | 1 simulated minute per real second |
| 5 min/sec (300×) | 120s | 5 simulated minutes per real second |
| 30 min/sec (1800×) | 720s | 30 simulated minutes per real second |

---

## 9. The Dashboard (Streamlit UI)

Run with: `streamlit run dashboard.py`

### Layout

```
┌─────────────────────────────────────────────────────┐
│  SIDEBAR                                            │
│  - Mode: Simulation / ESP32 Live                    │
│  - Control: AI Agent / Rule-Based                   │
│  - Start time, initial temp, speed                  │
│  - Start/Pause/Reset buttons                        │
│  - System specs                                     │
│  - CSV download                                     │
├─────────────────────────────────────────────────────┤
│  KPI ROW: Status | Temp | Energy | Grid | Renew | Safety
├──────────────────────────┬──────────────────────────┤
│  Temperature Gauge       │  24-Hour Energy Landscape │
│  (Plotly indicator)      │  (Solar/Wind/Peak bars)   │
│                          │  + Carbon footprint badge │
├──────────────────────────┴──────────────────────────┤
│  Temperature & Energy History (dual-axis chart)      │
├─────────────────────────────────────────────────────┤
│  AI INTELLIGENCE PANEL (4 tabs)                      │
│  ┌──────────┬───────────┬───────────┬──────────┐    │
│  │Q-Learning│ Forecast  │ Day-Ahead │ Anomaly  │    │
│  │  Agent   │           │   Plan    │Detection │    │
│  └──────────┴───────────┴───────────┴──────────┘    │
├─────────────────────────────────────────────────────┤
│  SMART FRAMEWORK (5 tabs)                            │
│  ┌──────────┬──────────┬──────────┬─────────┬─────┐ │
│  │Predictive│ Dynamic  │ Energy   │Benchmark│Market│ │
│  │Maintenan.│Optimizat.│Arbitrage │         │Valid.│ │
│  └──────────┴──────────┴──────────┴─────────┴─────┘ │
├─────────────────────────────────────────────────────┤
│  JSON API Output (collapsible)                       │
│  Raw Data Table (collapsible)                        │
└─────────────────────────────────────────────────────┘
```

### Two Operating Modes

**Simulation Mode:** The dashboard simulates the thermal physics internally. No hardware needed. The temperature updates based on:
- CHARGE: `+0.12 °C/s × dt`
- DISCHARGE: `-0.15 °C/s × dt`
- STORE: `-0.005 °C/s × dt`

**ESP32 Live Mode:** Reads real temperature from the ESP32 via serial port. Parses the `T:<value>` format. Requires `pyserial`.

### Session State

All AI objects and state persist across Streamlit reruns via `st.session_state`:
- `ai_agent` — Q-Learning agent (Q-table persists)
- `ai_predictor` — Holt smoother (level/trend persist)
- `ai_anomaly` — Anomaly detector (rolling window persists)
- `ai_planner` — Day-ahead planner (stateless, recomputes each call)
- `fw_thermal` — Insulation monitor (k history persists)
- `fw_piping` — Piping diagnostics (η history persists)
- `fw_load` — Load balancer (machine states persist)
- `fw_cost` — Cost calculator (cumulative totals persist)

---

## 10. The Flask Web App

Run with: `python app.py`

### Routes

| Route | Page | Purpose |
|-------|------|---------|
| `/` | index.html | Landing page — Morocco TOU charts, sovereignty pitch |
| `/simulate` | simulate.html | Feasibility calculator — input params, get ROI |
| `/admin` | admin.html | Admin dashboard — telemetry, manual PSI input |
| `/ai-core` | ai_core.html | Dark-themed AI core UI with client-side simulation |

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/calculate` | POST | Feasibility calculation (sand mass, cost, payback) |
| `/api/telemetry` | GET | Current sensor data (bridges ESP32 to web) |
| `/api/ai-core/compute` | POST | AI state computation (JSON in, JSON out) |
| `/api/psi` | POST | Set PSI value manually |

---

## 11. How to Run the Project

### Prerequisites

- Python 3.9+
- (Optional) ESP32 with MAX6675 thermocouple

### Install

```bash
cd thermasand_web
pip install -r requirements.txt
```

Dependencies: flask, streamlit, pyserial, pandas, plotly, numpy

### Run the Dashboard (main interface)

```bash
cd thermasand_web
streamlit run dashboard.py
```

Opens at `http://localhost:8501`. Works fully in simulation mode — no hardware needed.

### Run the Flask App

```bash
cd thermasand_web
python app.py
```

Opens at `http://localhost:5000`.

### Flash the ESP32

1. Open `esp32/thermasand_ds18b20/thermasand_ds18b20.ino` in Arduino IDE
2. Install the `max6675` library
3. Select ESP32 board, correct COM port
4. Flash
5. In the Streamlit dashboard, switch to "ESP32 Live" mode and connect to the serial port

---

## 12. Key Constants and Parameters

### Physical Constants

| Constant | Symbol | Value | Unit |
|----------|--------|-------|------|
| Sand mass | m | 15 | kg |
| Specific heat | Cp | 830 | J/(kg·K) |
| Ambient temperature | T_amb | 25 | °C |
| Heater power | P | 1,500 | W |
| Max safe temperature | T_max | 800 | °C |
| Warning temperature | T_warn | 650 | °C |
| Charge rate | — | 0.12 | °C/s |
| Discharge rate | — | -0.15 | °C/s |
| Storage loss rate | — | -0.005 | °C/s |
| Insulation decay constant | k_nominal | 4.0 × 10⁻⁴ | /s |
| Exchanger effectiveness | η_nominal | 0.75 | — |

### AI Hyperparameters

| Parameter | Symbol | Value |
|-----------|--------|-------|
| Learning rate | α | 0.1 |
| Discount factor | γ | 0.95 |
| Initial exploration | ε₀ | 0.25 |
| Min exploration | ε_min | 0.05 |
| Exploration decay | — | 0.9995 per step |
| Holt level smoothing | α_holt | 0.4 |
| Holt trend smoothing | β_holt | 0.3 |
| Anomaly window | — | 30 samples |
| Anomaly z-threshold | — | 2.5 |
| DP temperature bins | — | 17 (50°C each) |

### Morocco Grid (ONEE)

| Period | Hours | Cost (MAD/kWh) |
|--------|-------|---------------|
| Peak | 17:00–22:00 | 1.60 |
| Off-peak | 22:00–17:00 | 0.80 |
| Solar window | 08:00–18:00 | — |
| Wind window | 22:00–05:00 | — |

### Energy Calculations

```
Stored energy:  E = m × Cp × (T_core - T_ambient)
At 600°C:       E = 15 × 830 × (600 - 25) = 7,158,750 J ≈ 7,159 kJ ≈ 1.99 kWh
At max (800°C): E = 15 × 830 × (800 - 25) = 9,641,250 J ≈ 9,641 kJ ≈ 2.68 kWh
```

---

## 13. File Map

| File | Lines | What It Does |
|------|-------|-------------|
| `ai_engine.py` | ~415 | 4 AI algorithms: Q-Learning, Holt forecast, z-score anomaly, DP planner |
| `smart_framework.py` | ~497 | 6-tier framework: integrity, piping, load, weather, cost, arbitrage, benchmark |
| `dashboard.py` | ~1633 | Full Streamlit dashboard — simulation, ESP32, all visualizations |
| `app.py` | ~varies | Flask web server — landing, calculator, admin, APIs |
| `thermasand_ds18b20.ino` | ~40 | ESP32 firmware — MAX6675 thermocouple reader |
| `main.typ` | ~640 | Patent document (Typst) — OMPIC-compliant mémoire descriptif |

---

*If you have questions, ask Ismail or Soundous. Welcome to the team.*
