"""
ThermaSand Smart Management & Diagnostic Framework
════════════════════════════════════════════════════════════════
Six-tier industrial intelligence layer solving the Energy Trap.

Tier 1 — Predictive Maintenance & Security Unit
Tier 2 — Dynamic Operational Optimization
Tier 3 — Strategic Energy Arbitrage
Tier 4 — Industrial Benchmarking
Tier 5 — Market Validation (data only)
Tier 6 — Command Center helpers
"""

import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import List, Dict, Tuple


# ════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════
MASS = 15           # kg
CP = 830            # J/(kg·K)
AMBIENT_DEFAULT = 25  # °C


# ════════════════════════════════════════════════════════════════
# TIER 1 — PREDICTIVE MAINTENANCE & SECURITY UNIT
# ════════════════════════════════════════════════════════════════

class ThermalIntegrityMonitor:
    """
    Compares real-time cooling curves against a theoretical Newton's-law
    model. Divergence indicates insulation degradation or sand-quality
    changes (e.g. moisture ingress).

    Theoretical model:  dT/dt = -k · (T - T_ambient)
    where k_nominal ≈ 4.0e-4 /s for well-insulated Rock Wool.
    """

    K_NOMINAL = 4.0e-4  # 1/s — healthy insulation

    def __init__(self, window: int = 60):
        self.window = window
        self.observed_k_values = deque(maxlen=window)
        self.insulation_health = 100.0  # percentage
        self.alerts: List[str] = []

    def update(self, temp: float, prev_temp: float, dt: float,
               ambient: float = AMBIENT_DEFAULT, action: str = "STORAGE"):
        """Feed a temperature transition. Only meaningful during STORAGE."""
        if action != "STORAGE" or dt <= 0 or temp <= ambient:
            return
        # Estimate k from observed cooling:  k_obs = -(dT/dt) / (T - T_amb)
        rate = (temp - prev_temp) / dt
        delta_t = max(prev_temp - ambient, 1.0)
        k_obs = -rate / delta_t
        if k_obs < 0:
            k_obs = 0.0  # noise — ignore heating during storage
        self.observed_k_values.append(k_obs)
        self._recalc_health()

    def _recalc_health(self):
        if len(self.observed_k_values) < 5:
            return
        avg_k = sum(self.observed_k_values) / len(self.observed_k_values)
        # health = 100% when avg_k == K_NOMINAL, 0% when avg_k >= 3×K_NOMINAL
        ratio = avg_k / self.K_NOMINAL if self.K_NOMINAL > 0 else 1.0
        self.insulation_health = max(0.0, min(100.0, (1 - (ratio - 1) / 2) * 100))
        if self.insulation_health < 60:
            msg = (f"Insulation degradation detected — health {self.insulation_health:.0f}%. "
                   f"Observed k={avg_k:.6f} vs nominal {self.K_NOMINAL:.6f}")
            if not self.alerts or self.alerts[-1] != msg:
                self.alerts.append(msg)
                if len(self.alerts) > 20:
                    self.alerts = self.alerts[-20:]

    @property
    def current_k(self) -> float:
        if not self.observed_k_values:
            return self.K_NOMINAL
        return sum(self.observed_k_values) / len(self.observed_k_values)

    def theoretical_curve(self, start_temp: float, hours: int = 12,
                          ambient: float = AMBIENT_DEFAULT) -> List[float]:
        """Generate theoretical cooling curve from start_temp."""
        curve = [start_temp]
        t = start_temp
        for _ in range(hours * 60):  # per-minute resolution
            t += -self.K_NOMINAL * (t - ambient) * 60  # dt = 60s
            curve.append(max(ambient, t))
        return curve

    def degraded_curve(self, start_temp: float, hours: int = 12,
                       ambient: float = AMBIENT_DEFAULT) -> List[float]:
        """Generate cooling curve using OBSERVED k (may be degraded)."""
        k = self.current_k
        curve = [start_temp]
        t = start_temp
        for _ in range(hours * 60):
            t += -k * (t - ambient) * 60
            curve.append(max(ambient, t))
        return curve


class PipingDiagnostics:
    """
    Flow-to-Heat Ratio monitor.
    Compares expected air-output temperature vs actual, accounting
    for core temperature and blower flow rate.

    Model: T_out = T_ambient + η · (T_core - T_ambient)
    where η is the heat-exchanger effectiveness (0–1).
    η_nominal ≈ 0.75 for clean copper serpentine.
    """

    ETA_NOMINAL = 0.75

    def __init__(self):
        self.efficiency_history = deque(maxlen=100)
        self.current_eta = self.ETA_NOMINAL
        self.fouling_detected = False
        self.alerts: List[str] = []

    def update(self, core_temp: float, output_temp: float,
               ambient: float = AMBIENT_DEFAULT):
        if core_temp <= ambient:
            return
        eta_obs = (output_temp - ambient) / (core_temp - ambient)
        eta_obs = max(0.0, min(1.0, eta_obs))
        self.efficiency_history.append(eta_obs)
        self.current_eta = sum(self.efficiency_history) / len(self.efficiency_history)
        self.fouling_detected = self.current_eta < 0.55
        if self.fouling_detected:
            msg = (f"Piping fouling detected — η={self.current_eta:.2f} "
                   f"(nominal {self.ETA_NOMINAL})")
            if not self.alerts or self.alerts[-1] != msg:
                self.alerts.append(msg)

    def expected_output(self, core_temp: float,
                        ambient: float = AMBIENT_DEFAULT) -> float:
        return ambient + self.ETA_NOMINAL * (core_temp - ambient)

    def actual_output_sim(self, core_temp: float,
                          ambient: float = AMBIENT_DEFAULT) -> float:
        """Simulated actual output with current (possibly degraded) eta."""
        return ambient + self.current_eta * (core_temp - ambient)


# ════════════════════════════════════════════════════════════════
# TIER 2 — DYNAMIC OPERATIONAL OPTIMIZATION
# ════════════════════════════════════════════════════════════════

@dataclass
class FactoryMachine:
    name: str
    power_kw: float
    schedule: List[Tuple[int, int]]   # list of (start_hour, end_hour)
    is_running: bool = True

    def expected_running(self, hour: int) -> bool:
        for start, end in self.schedule:
            if start <= hour < end:
                return True
        return False


class DynamicLoadBalancer:
    """
    Monitors factory machines and detects surplus energy when
    machines stop unexpectedly, re-routing it to the sand battery.
    """

    DEFAULT_MACHINES = [
        FactoryMachine("Oven A",       45.0, [(6, 18)]),
        FactoryMachine("Dryer B",      30.0, [(8, 20)]),
        FactoryMachine("Steriliser C", 25.0, [(7, 15)]),
        FactoryMachine("Boiler D",     50.0, [(0, 24)]),  # 24/7
    ]

    def __init__(self, machines: List[FactoryMachine] = None):
        self.machines = machines or [
            FactoryMachine(m.name, m.power_kw, m.schedule)
            for m in self.DEFAULT_MACHINES
        ]
        self.surplus_history = deque(maxlen=200)

    def expected_load(self, hour: int) -> float:
        return sum(m.power_kw for m in self.machines if m.expected_running(hour))

    def actual_load(self, hour: int) -> float:
        return sum(
            m.power_kw for m in self.machines
            if m.expected_running(hour) and m.is_running
        )

    def detect_surplus(self, hour: int) -> Tuple[float, str]:
        expected = self.expected_load(hour)
        actual = self.actual_load(hour)
        surplus = expected - actual
        self.surplus_history.append({"hour": hour, "surplus_kw": surplus})
        if surplus > 5:
            stopped = [
                m.name for m in self.machines
                if m.expected_running(hour) and not m.is_running
            ]
            return surplus, f"Surplus {surplus:.0f} kW — {', '.join(stopped)} stopped. Re-routing to sand battery."
        return 0.0, ""

    def simulate_random_stop(self, hour: int):
        """Randomly stop a running machine (for simulation)."""
        running = [
            m for m in self.machines
            if m.expected_running(hour) and m.is_running
        ]
        if running and random.random() < 0.03:  # 3% chance per tick
            machine = random.choice(running)
            machine.is_running = False
            return machine.name
        # Randomly restart stopped machines
        stopped = [m for m in self.machines if not m.is_running]
        for m in stopped:
            if random.random() < 0.1:
                m.is_running = True
        return None

    def load_profile_24h(self) -> List[Dict]:
        return [
            {"hour": h, "expected_kw": self.expected_load(h)}
            for h in range(24)
        ]


class WeatherCompensator:
    """
    Adjusts required charge power based on Morocco ambient conditions.
    Higher ambient → lower heat loss → less charge power needed.
    """

    @staticmethod
    def morocco_ambient(hour: int, month: int = 2) -> float:
        """Simulated ambient temperature for Morocco (lat ~31°N)."""
        # Monthly base temps (Casablanca-ish)
        monthly_avg = [13, 14, 16, 18, 20, 23, 26, 26, 24, 20, 16, 14]
        base = monthly_avg[min(month - 1, 11)]
        diurnal_range = 10  # °C day-night swing
        # Min at 06:00, max at 14:00
        phase = ((hour - 6) / 24) * 2 * math.pi
        return base + diurnal_range / 2 * math.sin(phase)

    @staticmethod
    def heat_loss_factor(ambient: float) -> float:
        """
        Relative heat loss factor. Higher ambient → lower loss.
        Normalised so factor = 1.0 at 25°C.
        """
        return max(0.3, (600 - ambient) / (600 - 25))

    @staticmethod
    def adjusted_charge_power(nominal_power: float, ambient: float) -> float:
        """Reduce charge power when ambient is high."""
        factor = WeatherCompensator.heat_loss_factor(ambient)
        return nominal_power * factor


class CostCalculator:
    """
    Activity-based costing engine.
    Tracks real-time cost per thermal kWh and compares against
    direct-electric baseline.
    """

    PEAK_PRICE = 1.60      # MAD/kWh
    OFF_PEAK_PRICE = 0.80  # MAD/kWh
    GAS_PRICE = 1.20       # MAD/kWh-thermal (baseline)

    def __init__(self):
        self.total_energy_kwh = 0.0
        self.total_cost_mad = 0.0
        self.total_baseline_cost = 0.0
        self.history = deque(maxlen=500)

    def record(self, power_kw: float, dt_hours: float, hour: int):
        """Record energy consumption for a time step."""
        energy = power_kw * dt_hours
        is_peak = 17 <= hour < 22
        price = self.PEAK_PRICE if is_peak else self.OFF_PEAK_PRICE
        cost = energy * price
        baseline = energy * self.PEAK_PRICE  # baseline always pays peak

        self.total_energy_kwh += energy
        self.total_cost_mad += cost
        self.total_baseline_cost += baseline
        self.history.append({
            "energy_kwh": energy,
            "cost_mad": cost,
            "baseline_mad": baseline,
            "cumulative_cost": self.total_cost_mad,
            "cumulative_baseline": self.total_baseline_cost,
        })

    @property
    def cost_per_kwh_th(self) -> float:
        if self.total_energy_kwh <= 0:
            return 0.0
        return self.total_cost_mad / self.total_energy_kwh

    @property
    def savings_mad(self) -> float:
        return self.total_baseline_cost - self.total_cost_mad

    @property
    def savings_pct(self) -> float:
        if self.total_baseline_cost <= 0:
            return 0.0
        return (self.savings_mad / self.total_baseline_cost) * 100


# ════════════════════════════════════════════════════════════════
# TIER 3 — STRATEGIC ENERGY ARBITRAGE
# ════════════════════════════════════════════════════════════════

class ArbitrageEngine:
    """
    Calculates the economic impact of grid smoothing, solar oversizing,
    and connection-fee avoidance.
    """

    @staticmethod
    def grid_smoothing_profile(peak_mw: float = 50.0,
                               smoothed_mw: float = 2.0,
                               hours: int = 24) -> Dict:
        """
        Compare spiky direct-electric profile vs constant ThermaSand draw.
        Returns hourly profiles for both approaches.
        """
        # Direct electric: 50MW during factory hours (6-18), 0 at night
        direct = [peak_mw if 6 <= h < 18 else 0.0 for h in range(hours)]
        # ThermaSand: constant 2MW draw, 24/7
        smooth = [smoothed_mw] * hours
        total_direct = sum(direct)
        total_smooth = sum(smooth)
        return {
            "direct_profile": direct,
            "smooth_profile": smooth,
            "peak_demand_mw": peak_mw,
            "smooth_demand_mw": smoothed_mw,
            "peak_reduction_pct": ((peak_mw - smoothed_mw) / peak_mw) * 100,
            "total_direct_mwh": total_direct,
            "total_smooth_mwh": total_smooth,
        }

    @staticmethod
    def connection_fee_savings(peak_mw: float = 50.0,
                               smoothed_mw: float = 2.0) -> Dict:
        """
        Moroccan industrial connection fees scale with peak demand.
        Substation upgrade cost ≈ 150,000 MAD per MW of peak capacity.
        """
        cost_per_mw = 150_000  # MAD
        direct_fee = peak_mw * cost_per_mw
        smooth_fee = smoothed_mw * cost_per_mw
        return {
            "direct_connection_mad": direct_fee,
            "smooth_connection_mad": smooth_fee,
            "savings_mad": direct_fee - smooth_fee,
            "savings_pct": ((direct_fee - smooth_fee) / direct_fee) * 100,
        }

    @staticmethod
    def solar_oversizing(daily_demand_kwh: float = 500.0,
                         peak_sun_hours: float = 6.0) -> Dict:
        """
        Calculate solar array oversizing needed for 24/7 decarbonization.
        Capture 24h of heat in 6–8h of sunshine.
        """
        oversizing_factor = 24 / peak_sun_hours
        solar_capacity_kw = (daily_demand_kwh / peak_sun_hours) * 1.1  # 10% margin
        annual_co2_avoided_kg = daily_demand_kwh * 365 * 0.5  # ~0.5 kg CO2/kWh grid
        return {
            "daily_demand_kwh": daily_demand_kwh,
            "peak_sun_hours": peak_sun_hours,
            "oversizing_factor": round(oversizing_factor, 1),
            "required_solar_kw": round(solar_capacity_kw, 1),
            "annual_solar_mwh": round(solar_capacity_kw * peak_sun_hours * 365 / 1000, 1),
            "annual_co2_avoided_tons": round(annual_co2_avoided_kg / 1000, 1),
            "green_heat_pct": 100.0,
        }

    @staticmethod
    def decarbonization_score(renewable_hours: float,
                              total_hours: float) -> float:
        if total_hours <= 0:
            return 0.0
        return min(100.0, (renewable_hours / total_hours) * 100)


# ════════════════════════════════════════════════════════════════
# TIER 4 — INDUSTRIAL BENCHMARKING
# ════════════════════════════════════════════════════════════════

class IndustrialBenchmark:
    """
    Comparative analysis: ThermaSand M-TES vs Direct Electric Heating.
    Scores on 6 axes, each 0–10.
    """

    METRICS = {
        "Grid Impact":     {"direct": 2, "thermasand": 9,
                            "detail": ("Severe spikes, requires grid upgrades",
                                       "Gentle constant draw, stabilises grid")},
        "Operating Cost":  {"direct": 3, "thermasand": 8,
                            "detail": ("Exposed to volatile market prices",
                                       "Buys cheapest off-peak power")},
        "Reliability":     {"direct": 3, "thermasand": 9,
                            "detail": ("Heat stops during blackouts",
                                       "Hours/days of backup heat")},
        "Scalability":     {"direct": 4, "thermasand": 9,
                            "detail": ("Limited by power line capacity",
                                       "Add more sand volume")},
        "Safety":          {"direct": 5, "thermasand": 9,
                            "detail": ("Electrical fire risk",
                                       "Inert sand, zero fire risk")},
        "Decarbonization": {"direct": 4, "thermasand": 9,
                            "detail": ("Depends on real-time grid mix",
                                       "Stores and proves green energy")},
    }

    @classmethod
    def comparison_data(cls) -> Dict:
        labels = list(cls.METRICS.keys())
        direct_scores = [cls.METRICS[m]["direct"] for m in labels]
        thermasand_scores = [cls.METRICS[m]["thermasand"] for m in labels]
        details = {m: cls.METRICS[m]["detail"] for m in labels}
        return {
            "labels": labels,
            "direct_scores": direct_scores,
            "thermasand_scores": thermasand_scores,
            "details": details,
        }

    @staticmethod
    def roi_calculation(capex_mad: float = 450_000,
                        annual_savings_mad: float = 180_000,
                        lifespan_years: int = 25) -> Dict:
        payback = capex_mad / annual_savings_mad if annual_savings_mad > 0 else 99
        total_savings = annual_savings_mad * lifespan_years - capex_mad
        roi_pct = (total_savings / capex_mad) * 100 if capex_mad > 0 else 0
        return {
            "capex_mad": capex_mad,
            "annual_savings_mad": annual_savings_mad,
            "payback_years": round(payback, 1),
            "lifespan_years": lifespan_years,
            "total_net_savings_mad": round(total_savings),
            "roi_pct": round(roi_pct, 1),
        }


# ════════════════════════════════════════════════════════════════
# TIER 5 — MARKET VALIDATION (Reference Data)
# ════════════════════════════════════════════════════════════════

MARKET_REFERENCES = [
    {
        "company": "Polar Night Energy",
        "country": "Finland",
        "capacity": "100 tonnes of sand",
        "max_temp": "600°C",
        "use_case": "District heating network using excess wind power",
        "result": "Eliminates gas/biomass burning during extreme cold",
        "year": 2022,
        "url": "https://polarnightenergy.fi",
    },
    {
        "company": "NREL / Sandia National Labs",
        "country": "USA",
        "capacity": "Particle-based TES research",
        "max_temp": "1000°C+",
        "use_case": "Concentrating Solar Power (CSP) next-gen storage",
        "result": "Sand/particle systems identified as lowest-cost high-temp TES",
        "year": 2023,
        "url": "https://www.nrel.gov",
    },
    {
        "company": "Rondo Energy",
        "country": "USA",
        "capacity": "Industrial-scale heat batteries",
        "max_temp": "1500°C",
        "use_case": "Replacing industrial gas boilers",
        "result": "Backed by Bill Gates' Breakthrough Energy, $60M+ raised",
        "year": 2023,
        "url": "https://rondo.com",
    },
]
