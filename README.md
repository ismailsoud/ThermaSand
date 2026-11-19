# ThermaSand

ThermaSand is a prototype intelligent control system for modular thermal energy storage (M-TES). It stores electrical energy as heat in silica sand, then releases that heat when industrial demand is high or electricity is expensive.

The repository combines:

- A Streamlit dashboard for simulation and ESP32 telemetry.
- A Flask web application with a feasibility calculator, admin views, and JSON APIs.
- A Python AI and optimization engine.
- A smart diagnostic framework for thermal integrity, piping, load, weather, and cost monitoring.
- ESP32 firmware for temperature acquisition.
- Technical and patent-oriented project documentation.

## What the system does

The prototype models a 15 kg silica-sand thermal store with a nominal ambient temperature of 25 C, a 1,500 W heater, and an operating limit of 800 C. The control loop uses temperature, temperature rate, time of day, peak/off-peak pricing, renewable availability, and safety thresholds to recommend one of three operating states:

- `CHARGING`: add heat to the sand.
- `DISCHARGING`: extract heat for the industrial load.
- `STORAGE`: hold the stored heat and allow normal thermal losses.

The application can run without hardware in Simulation mode. In ESP32 mode, the dashboard reads temperature messages in the form `T:<temperature>` over serial. The ESP32 firmware provides temperature only; PSI is entered manually through the admin interface.

## Architecture

```text
ESP32 + temperature sensor
          |
          v
  Streamlit dashboard  <---->  AI engine + smart framework
          |
          +---- simulation loop and charts

Flask web app
  +-- feasibility calculator
  +-- telemetry API
  +-- AI core compute API
  +-- admin and browser views
```

The safety logic has priority over optimization. A recommendation must not be treated as permission to exceed the configured temperature limit. Hardware cutoffs and production-grade actuator interlocks are still required for a real installation.

## AI model and algorithms

There is no single pretrained neural network in this project. The intelligent core is a hybrid of reinforcement learning, time-series forecasting, statistical detection, physics models, and deterministic optimization.

### 1. Tabular Q-learning dispatch agent

Implemented by `DispatchAgent` in `thermasand_web/ai_engine.py`.

The agent chooses `CHARGE`, `DISCHARGE`, or `STORE` from a discrete state:

```text
(temperature_bin, hour, is_peak, is_renewable)
```

The Q-table contains 8 x 24 x 2 x 2 x 3 values:

- 8 temperature bins covering 0-800 C.
- 24 hours of the day.
- Peak flag: peak is 17:00-22:00.
- Renewable flag: solar is modeled from 08:00-18:00 and wind from 22:00-05:00.
- 3 possible actions.

The update is the standard Bellman Q-learning update:

```text
Q(s,a) = Q(s,a) + alpha * (reward + gamma * max(Q(next_state)) - Q(s,a))
```

Current parameters are:

- Learning rate `alpha = 0.1`.
- Discount factor `gamma = 0.95`.
- Initial exploration rate `epsilon = 0.25`.
- Minimum exploration rate `0.05`.
- Exploration decay `0.9995` per update.

The reward function encodes the operating objective: charge during renewable or cheap periods, discharge during peak periods when reserves are available, avoid unsafe temperatures, and avoid wasteful discharge.

### 2. Holt temperature predictor

`TemperaturePredictor` uses Holt double exponential smoothing with `alpha = 0.4` and `beta = 0.3`. It tracks a smoothed temperature level and trend, then forecasts future temperatures. When enough history exists, it also estimates prediction intervals from recent residuals.

This model is appropriate for the prototype because it is small, interpretable, and can update online as readings arrive. It does not require a large labeled dataset.

### 3. Statistical anomaly detector

`AnomalyDetector` compares the observed temperature rate against the expected rate for the current action:

- Charging: approximately `+0.12 C/s`.
- Discharging: approximately `-0.15 C/s`.
- Storage: approximately `-0.005 C/s`.

It maintains a rolling window of deviations and raises an alert when the z-score exceeds `2.5`. This can indicate unexpected heating or cooling, sensor problems, insulation issues, or actuator behavior that differs from the model.

### 4. Day-ahead dynamic programming planner

`DayAheadPlanner` computes a 24-hour schedule using backward-induction dynamic programming. It discretizes temperature into 50 C bins and evaluates the cost of charging, discharging, or storing while enforcing the 25-800 C operating range.

The planner uses the prototype tariff assumptions of 1.60 MAD/kWh during peak hours and 0.80 MAD/kWh otherwise, with a modeled renewable discount and an avoided-peak-energy value.

## How the model has been trained

The Q-learning agent is trained online, during execution. When the Streamlit dashboard is running in AI control mode and the simulation is active, each simulation tick does the following:

1. Convert the current temperature and operating context into a discrete state.
2. Select an action with epsilon-greedy exploration.
3. Calculate a reward from the action, temperature, peak status, and renewable status.
4. Update the Q-table using the next state.
5. Apply the selected action to the simulation.

The Q-table is created with zeros when a new `DispatchAgent` is initialized and is kept in Streamlit session state while that dashboard session runs. The repository currently contains:

- No offline training dataset.
- No saved Q-table or model checkpoint.
- No neural-network weights.
- No separate training script or evaluation benchmark.

Therefore, claims about convergence or performance should be understood as prototype behavior observed during simulation, not as certification from a fixed trained model. A production version should collect validated telemetry, persist model versions, replay historical episodes, and compare the learned policy against rule-based and optimization baselines before controlling hardware autonomously.

## Why this model choice

The hybrid design is intentional:

- **Tabular Q-learning** is easy to inspect, has a small state space, and can learn online without a large dataset. Its Q-values and rewards can be displayed and audited.
- **Holt smoothing** provides fast, explainable short-term forecasts for a slowly changing thermal process.
- **Z-score detection** is inexpensive and useful when labeled fault data is not yet available.
- **Dynamic programming** gives a deterministic day-ahead schedule and provides a useful comparison with the learned policy.
- **Physics and safety rules** provide hard operational boundaries. A learned policy should optimize within those boundaries, not replace them.

This approach is better suited to an early physical prototype than a large black-box model because the available data is limited, the thermal system is constrained, and operators need to understand why a recommendation was made.

## Smart management framework

`thermasand_web/smart_framework.py` adds supporting diagnostics and optimization:

- Thermal integrity monitoring using Newton's law of cooling.
- Piping heat-exchanger effectiveness monitoring.
- Industrial machine load and surplus detection.
- Morocco ambient-temperature compensation.
- Activity-based cost calculation.
- Energy arbitrage and industrial benchmarking helpers.

These components complement the AI engine; they are not additional pretrained models.

## Project layout

```text
ThermaSand/
|-- README.md
|-- TECHNICAL_GUIDE.md
|-- PATENT_AI_ALGORITHM.md
|-- thermasand_web/
    |-- ai_engine.py
    |-- smart_framework.py
    |-- dashboard.py
    |-- app.py
    |-- requirements.txt
    |-- templates/
    `-- esp32/thermasand_ds18b20/
        `-- thermasand_ds18b20.ino
```

## Installation

From the `thermasand_web` directory, create and activate a virtual environment, then install the dependencies:

```powershell
cd thermasand_web
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`pyserial` is optional for Simulation mode but is required for ESP32 serial input.

## Run the applications

### Streamlit intelligent dashboard

```powershell
streamlit run dashboard.py
```

Use Simulation mode to exercise the control loop without hardware. Use ESP32 mode when the board is connected and sending `T:<temperature>` readings.

### Flask web application

```powershell
python app.py
```

The Flask app exposes the browser pages and APIs, including:

- `/` - project landing page.
- `/simulate` - feasibility calculator.
- `/admin` - telemetry and PSI administration.
- `/ai-core` - AI core browser interface.
- `/api/telemetry` - telemetry GET/POST endpoint.
- `/api/ai-core/compute` - stateless AI-core calculation endpoint.

The Flask application currently runs with `debug=True`; use a production WSGI server and secure configuration before deployment.

## Hardware and safety scope

The included ESP32 code is a telemetry prototype. It reads and transmits temperature; it does not implement a complete industrial safety system or autonomous actuator interlock. Before connecting a heater, blower, valve, or other high-power equipment, add independently wired emergency stops, rated protection, sensor-failure handling, watchdogs, commissioning tests, and a review by a qualified controls engineer.

## Further documentation

- [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) - architecture, hardware assumptions, algorithms, and control loop details.
- [PATENT_AI_ALGORITHM.md](PATENT_AI_ALGORITHM.md) - detailed invention-oriented description of the AI and optimization algorithms.
- [thermasand_web/ai_engine.py](thermasand_web/ai_engine.py) - executable AI and optimization implementations.
- [thermasand_web/dashboard.py](thermasand_web/dashboard.py) - Streamlit control loop and UI.
- [thermasand_web/smart_framework.py](thermasand_web/smart_framework.py) - diagnostic and management framework.