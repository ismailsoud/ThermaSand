"""
ThermaSand AI Engine
════════════════════════════════════════════════════════════════
Real machine-learning components for intelligent thermal dispatch.

Components:
    1. DispatchAgent      — Q-Learning (Reinforcement Learning) agent
    2. TemperaturePredictor — Holt double-exponential smoothing forecast
    3. AnomalyDetector     — Statistical anomaly detection (z-score)
    4. DayAheadPlanner     — Dynamic programming optimal 24h schedule
"""

import math
import random
import numpy as np
from collections import deque


# ════════════════════════════════════════════════════════════════
# 1. Q-LEARNING DISPATCH AGENT (Reinforcement Learning)
# ════════════════════════════════════════════════════════════════
# State space:  (temp_bin, hour, is_peak, is_renewable)
#   temp_bin:    0..7  (0-100, 100-200, ..., 700-800)  = 8
#   hour:        0..23                                   = 24
#   is_peak:     0 | 1                                   = 2
#   is_renewable: 0 | 1                                  = 2
#   ─────────────────────────────────────────────────────
#   Total states: 8 × 24 × 2 × 2 = 768
#
# Actions:  0 = CHARGE,  1 = DISCHARGE,  2 = STORE
# ════════════════════════════════════════════════════════════════

ACTION_NAMES = {0: "CHARGING", 1: "DISCHARGING", 2: "STORAGE"}
ACTION_FROM_NAME = {"CHARGING": 0, "DISCHARGING": 1, "STORAGE": 2}


class DispatchAgent:
    """
    Tabular Q-Learning agent that learns the optimal charge/discharge
    policy from experience. Over many simulated hours it discovers that:
      - Charging during off-peak / renewable windows is rewarded
      - Discharging during peak hours is rewarded
      - Charging during peak hours is penalised
      - Exceeding safety limits is heavily penalised
    """

    def __init__(self, lr=0.1, gamma=0.95, epsilon=0.25):
        # Q-table: shape (8 temp_bins, 24 hours, 2 peak, 2 renew, 3 actions)
        self.q_table = np.zeros((8, 24, 2, 2, 3), dtype=np.float32)
        self.lr = lr                # learning rate  α
        self.gamma = gamma          # discount factor γ
        self.epsilon = epsilon      # exploration rate ε
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.9995
        self.total_steps = 0
        self.episode_rewards = []   # per-step reward history
        self.cumulative_reward = 0.0

    # ── Discretise continuous state ───────────────────────────
    @staticmethod
    def _discretise(temp, hour, is_peak, is_renewable):
        temp_bin = min(7, max(0, int(temp / 100)))
        return (temp_bin, int(hour) % 24, int(is_peak), int(is_renewable))

    # ── ε-greedy action selection ─────────────────────────────
    def choose_action(self, temp, hour, is_peak, is_renewable):
        state = self._discretise(temp, hour, is_peak, is_renewable)
        if random.random() < self.epsilon:
            action = random.randint(0, 2)           # explore
        else:
            action = int(np.argmax(self.q_table[state]))  # exploit
        return action, state

    # ── Reward function ───────────────────────────────────────
    @staticmethod
    def compute_reward(action, temp, is_peak, is_renewable):
        """
        Reward signal encodes the business objectives:
          +3  charge during renewable availability
          +1  charge off-peak (grid)
          -3  charge during peak (expensive!)
          +3  discharge during peak with reserves
          -2  discharge off-peak (wastes stored energy)
          -5  safety violation (temp > 800 or discharge when empty)
        """
        reward = 0.0

        if action == 0:  # CHARGE
            if is_renewable:
                reward = 3.0
            elif not is_peak:
                reward = 1.0
            else:
                reward = -3.0
            # Bonus for charging to useful levels
            if temp < 300:
                reward += 0.5  # need more reserves
        elif action == 1:  # DISCHARGE
            if is_peak and temp > 300:
                reward = 3.0
            elif is_peak and temp <= 300:
                reward = -1.0
            else:
                reward = -2.0
        else:  # STORE
            if is_peak and temp > 300:
                reward = -0.5  # missed discharge opportunity
            elif not is_peak and temp >= 600:
                reward = 0.5   # smart: full and holding
            else:
                reward = 0.0

        # Safety penalties
        if temp > 800:
            reward -= 5.0
        if temp < 30 and action == 1:
            reward -= 5.0

        return reward

    # ── Q-table update (Bellman equation) ─────────────────────
    def update(self, state, action, reward, next_temp, next_hour,
               next_is_peak, next_is_renewable):
        next_state = self._discretise(
            next_temp, next_hour, next_is_peak, next_is_renewable
        )
        old_q = self.q_table[state + (action,)]
        next_max = np.max(self.q_table[next_state])
        new_q = old_q + self.lr * (reward + self.gamma * next_max - old_q)
        self.q_table[state + (action,)] = new_q

        # Track
        self.total_steps += 1
        self.cumulative_reward += reward
        self.episode_rewards.append(reward)

        # Decay exploration
        self.epsilon = max(self.epsilon_min,
                           self.epsilon * self.epsilon_decay)

    # ── Utility: get Q-values for display ─────────────────────
    def get_q_values(self, temp, hour, is_peak, is_renewable):
        state = self._discretise(temp, hour, is_peak, is_renewable)
        return {
            "CHARGE": float(self.q_table[state + (0,)]),
            "DISCHARGE": float(self.q_table[state + (1,)]),
            "STORE": float(self.q_table[state + (2,)]),
        }

    def get_confidence(self, temp, hour, is_peak, is_renewable):
        """Return confidence 0-1 based on how differentiated the Q-values are."""
        qv = self.get_q_values(temp, hour, is_peak, is_renewable)
        vals = list(qv.values())
        spread = max(vals) - min(vals)
        return min(1.0, spread / 6.0)  # normalise

    def get_policy_summary(self):
        """Return a 24-hour policy summary for the current Q-table."""
        policy = []
        for h in range(24):
            is_peak = 1 if 17 <= h < 22 else 0
            is_renew = 1 if (8 <= h < 18 or h >= 22 or h < 5) else 0
            # Use mid-range temp bin (300-400°C, bin 3)
            state = (3, h, is_peak, is_renew)
            best = int(np.argmax(self.q_table[state]))
            policy.append(ACTION_NAMES[best])
        return policy


# ════════════════════════════════════════════════════════════════
# 2. TEMPERATURE PREDICTOR (Holt's Double Exponential Smoothing)
# ════════════════════════════════════════════════════════════════

class TemperaturePredictor:
    """
    Holt's method (double exponential smoothing) for temperature
    forecasting. Captures both level and trend to predict the
    temperature curve N steps into the future.
    """

    def __init__(self, alpha=0.4, beta=0.3):
        self.alpha = alpha     # level smoothing
        self.beta = beta       # trend smoothing
        self.level = None
        self.trend = None
        self.history = deque(maxlen=200)
        self.fitted = []

    def update(self, value):
        """Feed a new temperature reading."""
        self.history.append(value)
        if self.level is None:
            self.level = value
            self.trend = 0.0
            return
        prev_level = self.level
        self.level = self.alpha * value + (1 - self.alpha) * (self.level + self.trend)
        self.trend = self.beta * (self.level - prev_level) + (1 - self.beta) * self.trend

    def predict(self, steps_ahead=15):
        """Forecast `steps_ahead` future values."""
        if self.level is None:
            return [25.0] * steps_ahead
        return [
            self.level + (i + 1) * self.trend
            for i in range(steps_ahead)
        ]

    def prediction_interval(self, steps_ahead=15, z=1.96):
        """Return (forecast, lower, upper) for confidence bands."""
        if len(self.history) < 5:
            fc = self.predict(steps_ahead)
            return fc, fc, fc
        # Estimate residual variance from recent history
        residuals = []
        h = list(self.history)
        for i in range(2, len(h)):
            naive_pred = h[i - 1] + (h[i - 1] - h[i - 2])
            residuals.append(h[i] - naive_pred)
        if not residuals:
            fc = self.predict(steps_ahead)
            return fc, fc, fc
        std = (sum(r ** 2 for r in residuals) / len(residuals)) ** 0.5
        fc = self.predict(steps_ahead)
        lower = [f - z * std * math.sqrt(i + 1) for i, f in enumerate(fc)]
        upper = [f + z * std * math.sqrt(i + 1) for i, f in enumerate(fc)]
        return fc, lower, upper


# ════════════════════════════════════════════════════════════════
# 3. ANOMALY DETECTOR (Statistical Z-Score)
# ════════════════════════════════════════════════════════════════

class AnomalyDetector:
    """
    Detects anomalous temperature behaviour by comparing the observed
    rate of change against the expected rate for the current action.
    Uses a rolling z-score to flag deviations.
    """

    EXPECTED_RATES = {
        "CHARGING": 0.12,
        "DISCHARGING": -0.15,
        "STORAGE": -0.005,
    }

    def __init__(self, window=30, threshold=2.5):
        self.window = window
        self.threshold = threshold
        self.deviations = deque(maxlen=window)
        self.alerts = []         # recent alert messages

    def check(self, temp, prev_temp, dt, action):
        """
        Returns (is_anomaly: bool, message: str, severity: float).
        severity is the z-score magnitude (0 = normal).
        """
        if dt <= 0:
            return False, "Normal", 0.0

        rate = (temp - prev_temp) / dt
        expected = self.EXPECTED_RATES.get(action, 0.0)
        deviation = abs(rate - expected)
        self.deviations.append(deviation)

        if len(self.deviations) < 5:
            return False, "Collecting baseline data…", 0.0

        mean_dev = sum(self.deviations) / len(self.deviations)
        std_dev = (
            sum((d - mean_dev) ** 2 for d in self.deviations) / len(self.deviations)
        ) ** 0.5

        if std_dev < 1e-6:
            return False, "Normal", 0.0

        z_score = (deviation - mean_dev) / std_dev

        if z_score > self.threshold:
            msg = (
                f"Rate anomaly detected: {rate:+.4f} °C/s "
                f"(expected ~{expected:+.3f} for {action}). "
                f"Z-score: {z_score:.1f}"
            )
            self.alerts.append(msg)
            if len(self.alerts) > 20:
                self.alerts = self.alerts[-20:]
            return True, msg, z_score

        return False, "Normal", 0.0


# ════════════════════════════════════════════════════════════════
# 4. DAY-AHEAD PLANNER (Dynamic Programming)
# ════════════════════════════════════════════════════════════════

class DayAheadPlanner:
    """
    Uses backward-induction dynamic programming to compute the
    cost-optimal 24-hour charge/discharge schedule.

    Minimises:  Σ (grid_cost × energy_consumed) − (peak_value × energy_discharged)
    Subject to:  25°C ≤ T ≤ 800°C
    """

    # Grid cost per simulated hour of operation (MAD/kWh equivalent)
    PEAK_COST = 1.60
    OFF_PEAK_COST = 0.80
    PEAK_VALUE = 2.00  # value of avoided peak energy

    def __init__(self, temp_bins=17, mass=15, cp=830, heater_w=1500):
        self.temp_bins = temp_bins        # 50°C bins: 25, 75, ..., 825
        self.mass = mass
        self.cp = cp
        self.heater_w = heater_w
        self.charge_rate_per_hour = (heater_w / (mass * cp)) * 3600  # °C/hr
        self.discharge_rate_per_hour = 0.15 * 3600  # °C/hr
        self.loss_rate_per_hour = 0.005 * 3600       # °C/hr

    def _temp_from_bin(self, b):
        return 25 + b * 50

    def _bin_from_temp(self, t):
        return min(self.temp_bins - 1, max(0, int((t - 25) / 50)))

    def plan(self, start_temp=25.0, start_hour=0):
        """
        Compute optimal 24-hour schedule from start_temp at start_hour.
        Returns list of 24 dicts: [{hour, action, expected_temp, cost}]
        """
        INF = float("inf")
        n_hours = 24
        n_bins = self.temp_bins
        actions = ["CHARGE", "DISCHARGE", "STORE"]

        # cost_to_go[h][b] = minimum future cost from hour h in temp-bin b
        cost_to_go = [[INF] * n_bins for _ in range(n_hours + 1)]
        best_action = [["STORE"] * n_bins for _ in range(n_hours)]

        # Terminal cost: prefer high temperature at end of day
        for b in range(n_bins):
            t = self._temp_from_bin(b)
            cost_to_go[n_hours][b] = -t * 0.01  # small reward for stored heat

        # Backward induction
        for step in range(n_hours - 1, -1, -1):
            h = (start_hour + step) % 24
            is_peak = 17 <= h < 22
            is_solar = 8 <= h < 18
            is_wind = h >= 22 or h < 5
            grid_cost = self.PEAK_COST if is_peak else self.OFF_PEAK_COST

            for b in range(n_bins):
                t = self._temp_from_bin(b)

                for act in actions:
                    # Compute next temperature
                    if act == "CHARGE":
                        next_t = t + self.charge_rate_per_hour
                        op_cost = grid_cost * (self.heater_w / 1000)  # kWh cost
                        # Renewable discount
                        if is_solar or is_wind:
                            op_cost *= 0.3  # 70% cheaper with renewables
                    elif act == "DISCHARGE":
                        next_t = t - self.discharge_rate_per_hour
                        # Revenue from avoided peak energy
                        if is_peak:
                            op_cost = -self.PEAK_VALUE * (self.heater_w / 1000) * 0.5
                        else:
                            op_cost = 0.2  # small cost, wasted discharge
                    else:  # STORE
                        next_t = t - self.loss_rate_per_hour
                        op_cost = 0.0

                    # Enforce constraints
                    next_t = max(25, min(800, next_t))
                    next_b = self._bin_from_temp(next_t)

                    # Safety penalty
                    if next_t > 780:
                        op_cost += 5.0
                    if next_t < 50 and act == "DISCHARGE":
                        op_cost += 10.0

                    total = op_cost + cost_to_go[step + 1][next_b]
                    if total < cost_to_go[step][b]:
                        cost_to_go[step][b] = total
                        best_action[step][b] = act

        # Forward pass: extract schedule
        schedule = []
        b = self._bin_from_temp(start_temp)
        for step in range(n_hours):
            h = (start_hour + step) % 24
            t = self._temp_from_bin(b)
            act = best_action[step][b]

            if act == "CHARGE":
                next_t = t + self.charge_rate_per_hour
            elif act == "DISCHARGE":
                next_t = t - self.discharge_rate_per_hour
            else:
                next_t = t - self.loss_rate_per_hour
            next_t = max(25, min(800, next_t))

            schedule.append({
                "hour": h,
                "action": act,
                "expected_temp": round(next_t, 1),
                "cost": round(cost_to_go[step][b], 2),
            })
            b = self._bin_from_temp(next_t)

        return schedule
