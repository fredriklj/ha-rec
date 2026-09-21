"""Declarative Modbus register map for Rec Temovex ventilation units.

The map is taken from *REC Signals* (AB Regin, 2019-11-01), the signal list for
the Corrigo controller these units are built around.

Addressing
----------
The Regin document numbers registers from 1; Modbus PDUs — and therefore
pymodbus — number them from 0. Every address in this file is the **pymodbus**
address, and each note gives the Regin number so the two can be reconciled
without having to remember which convention is in play. The Regin number is
always one higher.

Scaling
-------
Regin's rule is that ``R`` (real) signals are transmitted multiplied by ten
while ``I``, ``X`` and ``L`` go as-is. On these units that holds for
temperatures and not for percentages, which was established by reading a
running unit rather than the document: a fan at 46 % reports 46 both on its
analogue output and in its setpoint register, and scaling either one reported
it as 5 %.

The exception to the exception is the bypass damper, which does carry the
factor. So: temperatures take ``scale=0.1``, percentages take ``1.0``, and the
bypass takes ``0.1``. Where the two disagree, believe the hardware.

Adding a register
-----------------
Append a :class:`RegisterDef` to :data:`REGISTERS`. Everything else — which
blocks get read, which entities get created — follows from this table.
``verified=False`` marks an address that has not been confirmed against real
hardware; those are never read and never produce an entity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# Maximum number of unmapped registers tolerated inside a single read block.
#
# Bridging a gap means reading addresses this map makes no claim about, which a
# unit is entitled to reject. That is survivable rather than fatal: a rejected
# block is re-planned into tighter blocks, and only a single register that is
# rejected on its own is dropped. See RecTemovexClient.async_read_all.
MAX_BLOCK_GAP = 8

# The Corrigo accepts at most 47 registers in one message (REC Signals, ch. 1).
MAX_BLOCK_REGISTERS = 40
MAX_BLOCK_BITS = 64


class RegisterKind(StrEnum):
    """Modbus address space a register lives in."""

    HOLDING = "holding"  # function 3/6/16
    INPUT = "input"  # function 4
    COIL = "coil"  # function 1/5/15
    DISCRETE = "discrete"  # function 2, Regin's "input status registers"


class DataType(StrEnum):
    """Numeric encoding of a register value."""

    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    BOOL = "bool"


_WORDS: dict[DataType, int] = {
    DataType.INT16: 1,
    DataType.UINT16: 1,
    DataType.INT32: 2,
    DataType.UINT32: 2,
    DataType.BOOL: 1,
}

BIT_KINDS = frozenset({RegisterKind.COIL, RegisterKind.DISCRETE})

# Regin scale factor for R (real) signals.
REAL = 0.1


@dataclass(frozen=True, kw_only=True)
class RegisterDef:
    """A single addressable value on the unit."""

    key: str
    kind: RegisterKind
    address: int
    data_type: DataType = DataType.INT16
    scale: float = 1.0
    offset: float = 0.0
    precision: int | None = None
    writable: bool = False
    verified: bool = False
    # For registers that act as a switch but are not coils: the raw values that
    # mean on and off. The Corrigo's mode registers use 0=Off, 1=Manual, 2=Auto.
    on_value: int = 1
    off_value: int = 0
    note: str = ""

    @property
    def count(self) -> int:
        """Number of registers (or bits) this value occupies."""
        return 1 if self.kind in BIT_KINDS else _WORDS[self.data_type]

    def decode(self, raw: int | bool) -> float | bool | int:
        """Apply scale and offset to a raw register value."""
        if self.kind in BIT_KINDS or self.data_type is DataType.BOOL:
            return bool(raw)
        value = raw * self.scale + self.offset
        if self.precision is not None:
            value = round(value, self.precision)
        if self.scale == 1.0 and self.offset == 0.0:
            return int(value)
        return value

    def encode(self, value: float) -> int:
        """Reverse :meth:`decode` for writing."""
        return round((value - self.offset) / self.scale)


def _temp(key: str, address: int, note: str, **kwargs) -> RegisterDef:
    """Build a Regin R temperature on the input register space."""
    return RegisterDef(
        key=key,
        kind=RegisterKind.INPUT,
        address=address,
        scale=REAL,
        precision=1,
        verified=True,
        note=note,
        **kwargs,
    )


def _percent(key: str, address: int, note: str) -> RegisterDef:
    """Build a Regin R percentage on the input register space."""
    return RegisterDef(
        key=key,
        kind=RegisterKind.INPUT,
        address=address,
        scale=REAL,
        precision=1,
        verified=True,
        note=note,
    )


def _output(key: str, address: int, note: str) -> RegisterDef:
    """Build an analog output on the input register space.

    The AQ registers are 0-10 V outputs, not percentages. Regin's scale factor
    of 10 applies to the *voltage*, so a raw 46 is 4.6 V — and on a 0-10 V fan
    or valve that is 46 %. The raw value is therefore already the percentage,
    and scaling it would divide the reading by ten.
    """
    return RegisterDef(
        key=key,
        kind=RegisterKind.INPUT,
        address=address,
        verified=True,
        note=note,
    )


def _flag(key: str, address: int, note: str) -> RegisterDef:
    """Build a Regin L signal on the input status (discrete input) space."""
    return RegisterDef(
        key=key,
        kind=RegisterKind.DISCRETE,
        address=address,
        data_type=DataType.BOOL,
        verified=True,
        note=note,
    )


REGISTERS: tuple[RegisterDef, ...] = (
    # --- Temperatures, scaled and filtered by the controller ----------
    # The raw AI values sit at 0-4; these are the ones the controller itself
    # regulates on.
    _temp("outdoor_temperature", 13, "Regin 14, InputOutput.OutDoorTemp."),
    _temp("supply_temperature", 14, "Regin 15, InputOutput.SupplyAirTemp."),
    # Regin's English labels are the reverse of how REC wires the sensors.
    # REC's terminal list (J9) is uteluft, tilluft, frånluft, avluft in that
    # order, so AI3 — which Regin calls "ExhaustAirTemp" — is the extract air
    # drawn from the rooms, and AI4 is the exhaust air leaving the building.
    # Confirmed against a running unit. Trust the wiring, not the label.
    _temp(
        "extract_temperature",
        15,
        "Regin 16, InputOutput.ExhaustAirTemp — "
        "wired to frånluft (extract) despite the name.",
    ),
    _temp(
        "exhaust_temperature",
        16,
        "Regin 17, InputOutput.ExtractAirTemp — "
        "wired to avluft (exhaust) despite the name.",
    ),
    _temp("room_temperature", 17, "Regin 18, VPac1.RoomTemp."),
    _temp("frost_protection_temperature", 18, "Regin 19, VPac1.FrostProtTemp."),
    _temp("room_unit_temperature", 29, "Regin 30, RoomUnit.RU1Temperature."),
    _temp(
        "desired_temperature",
        24,
        "Regin 25, VPac1.DesiredTemp — the setpoint actually in force, after "
        "outdoor compensation and any room unit adjustment.",
    ),
    # --- Fan and valve outputs ----------------------------------------
    _output("supply_fan_speed", 8, "Regin 9, QanaOut.AQ1 (SAF speed)."),
    _output("exhaust_fan_speed", 9, "Regin 10, QanaOut.AQ2 (EAF speed)."),
    _output("heating_valve", 10, "Regin 11, QanaOut.AQ3."),
    _output("cooling_valve", 11, "Regin 12, QanaOut.AQ4."),
    _output("preheat_valve", 12, "Regin 13, QanaOut.AQ5."),
    _percent("bypass_output", 20, "Regin 21, VPac1.Disp_SplitRange_Output2 (bypass)."),
    RegisterDef(
        key="filter_time_left",
        kind=RegisterKind.INPUT,
        address=19,
        verified=True,
        note="Regin 20, VPac1.FilterAlarm_TimeLeft. Integer, so no scaling.",
    ),
    # --- Setpoints and control mode -----------------------------------
    RegisterDef(
        key="regulation_mode",
        kind=RegisterKind.HOLDING,
        address=0,
        data_type=DataType.UINT16,
        verified=True,
        note="Regin 1, VPac1.Regulation. 0=supply air, 1=outdoor compensated "
        "supply, 2=room, 3=extract air. Decides which setpoint is in force.",
    ),
    RegisterDef(
        key="supply_setpoint",
        kind=RegisterKind.HOLDING,
        address=1,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 2, VPac1.Supply_Setp.",
    ),
    RegisterDef(
        key="exhaust_setpoint",
        kind=RegisterKind.HOLDING,
        address=2,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 3, VPac1.ExhaustSetP. Regin names it Exhaust but describes "
        "it as the extract air control setpoint.",
    ),
    RegisterDef(
        key="room_setpoint",
        kind=RegisterKind.HOLDING,
        address=3,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 4, VPac1.RoomSetP.",
    ),
    RegisterDef(
        key="away_setpoint_offset",
        kind=RegisterKind.HOLDING,
        address=4,
        writable=True,
        verified=True,
        note="Regin 5, VPac1.SetPAdj — how far the setpoint moves when away. "
        "Whole degrees, sent unscaled: a unit at the 2 C default reports 2.",
    ),
    RegisterDef(
        key="supply_setpoint_max",
        kind=RegisterKind.HOLDING,
        address=5,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 6, VPac1.SupplySetpointMax — upper bound on the supply "
        "setpoint the cascade may compute. Default 52 C.",
    ),
    RegisterDef(
        key="supply_setpoint_min",
        kind=RegisterKind.HOLDING,
        address=6,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 7, VPac1.SupplySetpointMin — lower bound. Default 15 C.",
    ),
    RegisterDef(
        key="supply_fan_min",
        kind=RegisterKind.HOLDING,
        address=23,
        writable=True,
        verified=True,
        note="Regin 24, VPac1.SAF_Min. Percent, transmitted as-is: a unit "
        "running at 46 % reports 46 here and 46 on AQ1.",
    ),
    RegisterDef(
        key="exhaust_fan_min",
        kind=RegisterKind.HOLDING,
        address=24,
        writable=True,
        verified=True,
        note="Regin 25, VPac1.EAF_Min.",
    ),
    RegisterDef(
        key="supply_fan_normal",
        kind=RegisterKind.HOLDING,
        address=25,
        writable=True,
        verified=True,
        note="Regin 26, VPac1.SAF_Normal.",
    ),
    RegisterDef(
        key="exhaust_fan_normal",
        kind=RegisterKind.HOLDING,
        address=26,
        writable=True,
        verified=True,
        note="Regin 27, VPac1.EAF_Normal.",
    ),
    RegisterDef(
        key="supply_fan_forced",
        kind=RegisterKind.HOLDING,
        address=27,
        writable=True,
        verified=True,
        note="Regin 28, VPac1.SAF_FF — forced flow.",
    ),
    RegisterDef(
        key="exhaust_fan_forced",
        kind=RegisterKind.HOLDING,
        address=28,
        writable=True,
        verified=True,
        note="Regin 29, VPac1.EAF_FF.",
    ),
    RegisterDef(
        key="supply_fan_max",
        kind=RegisterKind.HOLDING,
        address=29,
        writable=True,
        verified=True,
        note="Regin 30, VPac1.SAF_Max.",
    ),
    RegisterDef(
        key="exhaust_fan_max",
        kind=RegisterKind.HOLDING,
        address=30,
        writable=True,
        verified=True,
        note="Regin 31, VPac1.EAF_Max.",
    ),
    RegisterDef(
        key="supply_fan_kitchen",
        kind=RegisterKind.HOLDING,
        address=31,
        writable=True,
        verified=True,
        note="Regin 32, VPac1.SAF_Hood — the kitchen flow. Regin calls it "
        "Hood; the unit's own menu calls it Kok.",
    ),
    RegisterDef(
        key="exhaust_fan_kitchen",
        kind=RegisterKind.HOLDING,
        address=32,
        writable=True,
        verified=True,
        note="Regin 33, VPac1.EAF_Hood.",
    ),
    RegisterDef(
        key="supply_fan_stove",
        kind=RegisterKind.HOLDING,
        address=33,
        writable=True,
        verified=True,
        note="Regin 34, VPac1.SAF_Fire — the stove flow. Regin's Fire is "
        "the fireplace: 80/20, against the fire alarm's 0/100, and it "
        "matches the unit's own Bras setting.",
    ),
    RegisterDef(
        key="exhaust_fan_stove",
        kind=RegisterKind.HOLDING,
        address=34,
        writable=True,
        verified=True,
        note="Regin 35, VPac1.EAF_Fire.",
    ),
    RegisterDef(
        key="supply_fan_night_cooling",
        kind=RegisterKind.HOLDING,
        address=37,
        writable=True,
        verified=True,
        note="Regin 38, VPac1.SAF_NightCool.",
    ),
    RegisterDef(
        key="exhaust_fan_night_cooling",
        kind=RegisterKind.HOLDING,
        address=38,
        writable=True,
        verified=True,
        note="Regin 39, VPac1.EAF_NightCool.",
    ),
    # Regin 36-37, the fire alarm flows, are deliberately not mapped: they set
    # how the unit evacuates smoke, and nothing here should be able to change
    # that from a dashboard.
    RegisterDef(
        key="fan_mode",
        kind=RegisterKind.HOLDING,
        address=43,
        data_type=DataType.UINT16,
        writable=True,
        verified=True,
        note="Regin 44, VPac1.Fan_Mode. See FAN_MODES in const.py.",
    ),
    RegisterDef(
        key="heating_mode",
        kind=RegisterKind.HOLDING,
        address=47,
        data_type=DataType.UINT16,
        on_value=2,
        off_value=0,
        writable=True,
        verified=True,
        note="Regin 48, VPac1.Heating_Mode. 0=Off, 1=Manual, 2=Auto.",
    ),
    RegisterDef(
        key="bypass_mode",
        kind=RegisterKind.HOLDING,
        address=48,
        data_type=DataType.UINT16,
        on_value=2,
        off_value=0,
        writable=True,
        verified=True,
        note="Regin 49, VPac1.ByPass_Mode. 0=Off, 1=Manual, 2=Auto.",
    ),
    RegisterDef(
        key="preheat_setpoint",
        kind=RegisterKind.HOLDING,
        address=101,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 102, VPac1.Preheat_Setpoint.",
    ),
    RegisterDef(
        key="preheat_electric_mode",
        kind=RegisterKind.HOLDING,
        address=102,
        data_type=DataType.UINT16,
        on_value=2,
        off_value=0,
        writable=True,
        verified=True,
        note="Regin 103, StdObjs1.Preheat_PWMhandauto_Select — the electric "
        "preheater. 0=Manual off, 1=Manual on, 2=Auto.",
    ),
    RegisterDef(
        key="preheat_outdoor_limit",
        kind=RegisterKind.HOLDING,
        address=116,
        scale=REAL,
        precision=1,
        writable=True,
        verified=True,
        note="Regin 117, VPac1.Preheat_PWM_Outdoorlimit — outdoor temperature "
        "below which the electric preheater is allowed to run at all.",
    ),
    RegisterDef(
        key="preheat_damper_mode",
        kind=RegisterKind.HOLDING,
        address=117,
        data_type=DataType.UINT16,
        on_value=2,
        off_value=0,
        writable=True,
        verified=True,
        note="Regin 118, StdObjs1.Preheat_damperhandauto_Select — the preheat "
        "damper. 0=Manual off, 1=Manual on, 2=Auto.",
    ),
    RegisterDef(
        key="heat_type",
        kind=RegisterKind.HOLDING,
        address=123,
        data_type=DataType.UINT16,
        verified=True,
        note="Regin 124, VPac1.HeatType — what the heating output drives. "
        "0=Water (0-10 V), 1=Electric, 2=Water (PWM). Moved here from coil 1 "
        "in later firmware; read only, it is a commissioning choice.",
    ),
    RegisterDef(
        key="cooling_mode",
        kind=RegisterKind.HOLDING,
        address=49,
        data_type=DataType.UINT16,
        on_value=2,
        off_value=0,
        writable=True,
        verified=True,
        note="Regin 50, VPac1.Cooling_Mode. 0=Off, 1=Manual, 2=Auto.",
    ),
    # --- Coils --------------------------------------------------------
    RegisterDef(
        key="away",
        kind=RegisterKind.COIL,
        address=6,
        data_type=DataType.BOOL,
        writable=True,
        verified=True,
        note="Regin 7, VPac1.RUDispAway. 0=home, 1=away.",
    ),
    RegisterDef(
        key="night_cooling_enabled",
        kind=RegisterKind.COIL,
        address=2,
        data_type=DataType.BOOL,
        writable=True,
        verified=True,
        note="Regin 3, VPac1.NightCool_Enable.",
    ),
    RegisterDef(
        key="cool_recycling_enabled",
        kind=RegisterKind.COIL,
        address=1,
        data_type=DataType.BOOL,
        writable=True,
        verified=True,
        note="Regin 2, VPac1.Activate_CoolRecycle.",
    ),
    # --- Input status registers (discrete inputs, function 2) ---------
    _flag("supply_fan_running", 19, "Regin 20, VPac1.SAF_Start."),
    _flag("exhaust_fan_running", 20, "Regin 21, VPac1.EAF_Start."),
    _flag("defrosting", 21, "Regin 22, VPac1.Defrosting."),
    _flag("frost_risk", 56, "Regin 57, AlaPts.FrostProt_Alarm."),
    _flag("supply_fan_alarm", 57, "Regin 58, AlaPts.SAF_Alarm."),
    _flag("exhaust_fan_alarm", 58, "Regin 59, AlaPts.EAF_Alarm."),
    _flag("electric_heater_alarm", 60, "Regin 61, AlaPts.ElectricHeater_Alarm."),
    _flag("filter_guard_alarm", 61, "Regin 62, AlaPts.Filter_Alarm (filter guard)."),
    # The controller raises an alarm when a fan is left under manual control,
    # which is worth surfacing: it is the state any override scheme leaves
    # behind if it stops halfway.
    _flag("supply_fan_manual_alarm", 69, "Regin 70, AlaPts.SAFManual_Alarm."),
    _flag("exhaust_fan_manual_alarm", 70, "Regin 71, AlaPts.EAFManual_Alarm."),
    _flag("filter_alarm", 73, "Regin 74, AlaPts.FilterAlarmTime (filter timer)."),
    _flag("fire_alarm", 75, "Regin 76, AlaPts.FireAlarm."),
)

REGISTER_BY_KEY: dict[str, RegisterDef] = {r.key: r for r in REGISTERS}

VERIFIED_REGISTERS: tuple[RegisterDef, ...] = tuple(r for r in REGISTERS if r.verified)


@dataclass(frozen=True)
class ReadBlock:
    """A contiguous range of addresses fetched in one Modbus request."""

    kind: RegisterKind
    address: int
    count: int
    keys: tuple[str, ...] = field(default=())

    @property
    def end(self) -> int:
        """First address past the end of this block."""
        return self.address + self.count


def plan_blocks(
    registers: tuple[RegisterDef, ...] | list[RegisterDef],
    *,
    max_gap: int = MAX_BLOCK_GAP,
    max_registers: int = MAX_BLOCK_REGISTERS,
    max_bits: int = MAX_BLOCK_BITS,
) -> list[ReadBlock]:
    """Group registers into as few contiguous read requests as sensible.

    Registers are merged into one block while the unused gap between them stays
    within ``max_gap`` and the block stays within the per-request ceiling.
    """
    blocks: list[ReadBlock] = []

    for kind in RegisterKind:
        group = sorted(
            (r for r in registers if r.kind is kind), key=lambda r: r.address
        )
        if not group:
            continue

        limit = max_bits if kind in BIT_KINDS else max_registers

        start = group[0].address
        end = start + group[0].count
        keys = [group[0].key]

        for reg in group[1:]:
            reg_end = reg.address + reg.count
            fits = reg.address - end <= max_gap and reg_end - start <= limit
            if fits:
                end = max(end, reg_end)
                keys.append(reg.key)
                continue
            blocks.append(ReadBlock(kind, start, end - start, tuple(keys)))
            start, end, keys = reg.address, reg_end, [reg.key]

        blocks.append(ReadBlock(kind, start, end - start, tuple(keys)))

    return blocks
