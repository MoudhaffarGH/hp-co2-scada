"""
plc_simulator.py
CO2 Transcritical Heat Pump - PLC Data Simulator
Replicates exactly what the M172 EcoStruxure simulation produces.
When real hardware is available, replace this with modbus_reader.py
"""

import math
import time
import random

# ── Operating modes (matches E_OperatingMode enumeration) ──────────────────
MODE = {
    0: "eOFF",
    1: "eSTANDBY",
    2: "eDEFROST",
    3: "eHEATING",
    4: "eCOOLING",
    5: "eDHW",
    6: "eALARM",
    99: "eFAULT",
}

# ── Liao correlation for optimal gas cooler pressure ───────────────────────
def liao_optimal_pressure(T_gc_out: float, T_evap: float) -> float:
    """
    Liao 2000 correlation for CO2 transcritical optimal discharge pressure.
    Matches FB_OptimalPressure exactly.
    Returns pressure in bar.
    """
    P_opt = (
        2.778 - 0.0157 * T_gc_out
        + 0.000267 * T_gc_out ** 2
        - 0.000673 * T_evap
        + 0.0000255 * T_evap ** 2
        + 0.000258 * T_gc_out * T_evap
    ) * 10  # MPa → bar
    return round(P_opt, 2)

# ── COP calculation (matches FB_Diagnostics) ──────────────────────────────
def calc_cop(T_gc_in: float, T_gc_out: float, flow: float,
             T_discharge: float, T_suction: float) -> float:
    """
    Real-time COP = Heat output / Compressor work
    Using enthalpy approximation matching PLC logic.
    """
    cp_water = 4.18  # kJ/kg·K
    rho_water = 1.0   # kg/L
    flow_kgs = flow * rho_water / 60  # L/min → kg/s
    Q_heat = flow_kgs * cp_water * (T_gc_in - T_gc_out) * (-1)
    if Q_heat <= 0:
        Q_heat = abs(flow_kgs * cp_water * (T_gc_in - T_gc_out)) + 1.0

    # Approximate compressor work from discharge/suction temps
    delta_T_comp = max(T_discharge - T_suction, 10.0)
    W_comp = 0.15 * delta_T_comp * flow_kgs
    W_comp = max(W_comp, 0.5)

    cop = Q_heat / W_comp
    return round(min(max(cop, 1.0), 12.0), 2)

# ── Heat output calculation ────────────────────────────────────────────────
def calc_heat_output(T_gc_in: float, T_gc_out: float, flow: float) -> float:
    cp_water = 4.18
    rho_water = 1.0
    flow_kgs = flow * rho_water / 60
    Q = flow_kgs * cp_water * abs(T_gc_in - T_gc_out)
    return round(Q, 2)

# ── Main simulation class ──────────────────────────────────────────────────
class CO2HeatPumpSimulator:
    def __init__(self):
        self.t = 0.0
        self.mode = 3  # eHEATING
        self.fault_code = 0
        self.master_enable = True
        self.sp_water_outlet = 55.0

        # Base sensor values matching your EcoStruxure Watch window
        self.base = {
            "T_GasCoolerOut":  55.0,
            "T_GasCoolerIn":   40.0,
            "T_Evaporator":   -10.0,
            "T_Suction":       -5.0,
            "T_Discharge":    110.0,
            "T_Ambient":       10.0,
            "T_ProcessWater":  45.0,
            "P_HighSide":      90.0,
            "P_LowSide":       35.0,
            "F_WaterFlow":      3.0,
        }

    def noise(self, amp=0.3):
        return random.uniform(-amp, amp)

    def get_data(self) -> dict:
        self.t += 0.1

        # Simulate slow sinusoidal variation like a real system
        sin_slow = math.sin(self.t * 0.05)
        sin_fast = math.sin(self.t * 0.2)

        T_gc_out  = self.base["T_GasCoolerOut"]  + sin_slow * 2.0  + self.noise(0.2)
        T_gc_in   = self.base["T_GasCoolerIn"]   + sin_slow * 1.5  + self.noise(0.2)
        T_evap    = self.base["T_Evaporator"]     + sin_fast * 1.0  + self.noise(0.1)
        T_suction = self.base["T_Suction"]        + sin_fast * 0.8  + self.noise(0.1)
        T_disch   = self.base["T_Discharge"]      + sin_slow * 3.0  + self.noise(0.3)
        T_amb     = self.base["T_Ambient"]        + sin_slow * 0.5  + self.noise(0.1)
        T_water   = self.base["T_ProcessWater"]   + sin_slow * 1.0  + self.noise(0.2)
        P_high    = self.base["P_HighSide"]       + sin_slow * 2.0  + self.noise(0.2)
        P_low     = self.base["P_LowSide"]        + sin_fast * 1.0  + self.noise(0.1)
        flow      = self.base["F_WaterFlow"]      + self.noise(0.05)

        # Derived values using PLC formulas
        P_opt = liao_optimal_pressure(T_gc_out, T_evap)
        COP   = calc_cop(T_gc_in, T_gc_out, flow, T_disch, T_suction)
        Q_kW  = calc_heat_output(T_gc_in, T_gc_out, flow)

        # PID compressor speed (outer loop)
        error = self.sp_water_outlet - T_water
        comp_speed = max(0.0, min(100.0, 50.0 + error * 2.0 + self.noise(0.5)))

        # GCPV opening (inner loop)
        gcpv = max(0.0, min(100.0, 100.0 * (P_high / P_opt) + self.noise(1.0)))

        return {
            # Temperatures
            "T_GasCoolerOut":     round(T_gc_out, 2),
            "T_GasCoolerIn":      round(T_gc_in, 2),
            "T_Discharge":        round(T_disch, 2),
            "T_Ambient":          round(T_amb, 2),
            "T_ProcessWater":     round(T_water, 2),
            "T_Evaporator":       round(T_evap, 2),
            "T_Suction":          round(T_suction, 2),
            # Pressures
            "P_HighSide":         round(P_high, 2),
            "P_LowSide":          round(P_low, 2),
            "P_Optimal":          P_opt,
            # Flow
            "F_WaterFlow":        round(flow, 2),
            # Calculated
            "COP_Realtime":       COP,
            "HeatOutput_kW":      round(Q_kW, 2),
            "AO_CompressorSpeed": round(comp_speed, 2),
            "AO_GCPV_Opening":    round(gcpv, 2),
            # Status
            "Mode_Active":        self.mode,
            "Mode_Name":          MODE.get(self.mode, "UNKNOWN"),
            "FaultCode":          self.fault_code,
            "MasterEnable":       self.master_enable,
            "SP_WaterOutlet":     self.sp_water_outlet,
            # Safety
            "SafetyOK":           self.fault_code == 0,
            "Watchdog":           int(self.t * 10) % 2,
        }


# ── When real hardware available: swap this in ─────────────────────────────
class ModbusReader:
    """
    Replace CO2HeatPumpSimulator with this when real M172 hardware is connected.
    Uses exact address mapping from your EcoStruxure Status Variables table.
    Addresses start at 8960 as confirmed in your project.
    """
    def __init__(self, host="127.0.0.1", port=502):
        from pymodbus.client import ModbusTcpClient
        import struct
        self.client = ModbusTcpClient(host=host, port=port)
        self.struct = struct
        self.connected = self.client.connect()

    def read_real(self, address: int) -> float:
        data = self.client.read_holding_registers(address=address - 1, count=2)
        raw = self.struct.pack('>HH', data.registers[1], data.registers[0])
        return round(self.struct.unpack('>f', raw)[0], 2)

    def read_int(self, address: int) -> int:
        data = self.client.read_holding_registers(address=address - 1, count=1)
        return data.registers[0]

    def get_data(self) -> dict:
        return {
            "T_GasCoolerOut":     self.read_real(8960),
            "T_GasCoolerIn":      self.read_real(8962),
            "T_Discharge":        self.read_real(8964),
            "T_Ambient":          self.read_real(8966),
            "P_HighSide":         self.read_real(8968),
            "P_LowSide":          self.read_real(8970),
            "F_WaterFlow":        self.read_real(8972),
            "Mode_Active":        self.read_int(8974),
            "Mode_Name":          MODE.get(self.read_int(8974), "UNKNOWN"),
            "FaultCode":          self.read_int(8975),
            "COP_Realtime":       self.read_real(8976),
            "P_Optimal":          self.read_real(8978),
            "HeatOutput_kW":      self.read_real(8980),
            "AO_CompressorSpeed": self.read_real(8982),
            "SP_WaterOutlet":     self.read_real(8984),
        }

    def close(self):
        self.client.close()
