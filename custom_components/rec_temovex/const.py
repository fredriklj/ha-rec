"""Constants for the Rec Temovex integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "rec_temovex"

CONF_DEVICE_ID: Final = "device_id"
CONF_SERIAL_PORT: Final = "serial_port"
CONF_BAUDRATE: Final = "baudrate"
CONF_PARITY: Final = "parity"

# How the unit is reached. It only ever speaks RS485; this is about what sits
# between it and Home Assistant.
TRANSPORT_TCP: Final = "tcp"
TRANSPORT_SERIAL: Final = "serial"

DEFAULT_NAME: Final = "Rec Temovex"
DEFAULT_PORT: Final = 502

# The unit's own Modbus menu offers 150 to 19200 bps; the defaults are 9600
# and no parity. The lower rates are there for very long or noisy lines.
BAUDRATES: Final[tuple[int, ...]] = (1200, 2400, 4800, 9600, 19200, 38400)
DEFAULT_BAUDRATE: Final = 9600
# A select selector validates its value as a string before anything else, so
# both the options and the default it is given have to be strings. An int
# default makes the form impossible to submit without touching the dropdown.
BAUDRATE_OPTIONS: Final[tuple[str, ...]] = tuple(str(rate) for rate in BAUDRATES)
DEFAULT_BAUDRATE_OPTION: Final = str(DEFAULT_BAUDRATE)
PARITIES: Final[tuple[str, ...]] = ("N", "E", "O")
DEFAULT_PARITY: Final = "N"
# The technician manual's default parameters list Modbus as "1, 9600, none",
# so 1 is the address a unit carries unless someone has changed it.
DEFAULT_DEVICE_ID: Final = 1
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_TIMEOUT: Final = 5

# Pause between Modbus messages. REC Signals ch. 1 requires 3.5 character times
# between messages, and 14 when the controller shares the RS485 line — 16 ms at
# 9600 bps. 20 ms covers both and costs nothing at a 30 second poll interval.
MESSAGE_GAP: Final = 0.02

MANUFACTURER: Final = "Rec Indovent"
MODEL: Final = "Temovex"

# Operating modes, VPac1.Fan_Mode (Regin holding register 44). The index is the
# raw register value; the string is the Home Assistant fan mode key, lowercase
# because it is translated via strings.json.
FAN_MODES: Final[tuple[str, ...]] = (
    "off",
    "auto",
    "min",
    "boost",
    "max",
    "stove",
    "kitchen",
    "eco",
    "fire",
)

FAN_MODE_OFF: Final = "off"
FAN_MODE_AUTO: Final = "auto"

# Flow levels offered as a choice. Every value above is still decoded, so the
# reported mode is never a lie — these are only the ones that can be set.
#
# "min" is left out as redundant: ECO already runs at minimum flow and is
# allowed to rise towards normal when minimum cannot hold the setpoint, which
# is what you want from a low-flow mode. Fixed minimum is still reported if the
# unit is put there from its panel.
#
# "off" is left out because stopping the unit is the HVAC mode's job: one
# register, but one control per concept.
#
# Stove, kitchen and fire are left out for a different reason. Regin's own
# document is careful about it: the digital input list calls them "Stove mode",
# "Kitchen mode" and "Fire Alarm", while this register calls them "Stove flow",
# "Kitchen flow" and "Fire flow" — and the values that mean the same thing in
# both lists are worded identically. So this register selects the flow, not the
# function: no ignition timer, no after-run, no blocked bypass, no damper
# positions. Those are reached by a digital input, not over Modbus.
#
# The flows themselves are deliberately unbalanced and meant to be brief:
# stove and kitchen run the supply fan at 80 % against 20 % extract to
# pressurise the house, and fire runs 0 % supply against 100 % extract. Holding
# any of them indefinitely is not ventilation, it is a pressure imbalance.
SELECTABLE_FAN_MODES: Final[tuple[str, ...]] = (
    "off",
    "auto",
    "eco",
    "boost",
    "max",
)

PRESET_HOME: Final = "home"
PRESET_AWAY: Final = "away"

# VPac1.Regulation (Regin holding register 1). This integration assumes cascade
# room control, which is what makes the room setpoint the one that matters and
# ECO2 available at all. Other modes are read and warned about, not supported.
REGULATION_ROOM: Final = 2
REGULATION_NAMES: Final[dict[int, str]] = {
    0: "supply air control",
    1: "outdoor compensated supply air control",
    2: "cascade room control",
    3: "cascade extract air control",
}

# Which sensor supplies the room temperature is a setting on the unit: a plain
# analogue sensor, a room unit on the serial port, or the average of the two.
# The controller's own RoomTemp register holds it when an analogue sensor is in
# use and reads exactly zero when it is not, so the room unit's own reading is
# a fallback rather than a second opinion. Tried in order.
ROOM_TEMPERATURE_SOURCES: Final[tuple[str, ...]] = (
    "room_temperature",
    "room_unit_temperature",
)
SETPOINT_KEY: Final = "room_setpoint"

MIN_TEMP: Final = 10.0
MAX_TEMP: Final = 30.0
TEMP_STEP: Final = 0.5

# Flow states, as the unit's own display derives them: below normal is ECO,
# above normal is ECO2. See the technician manual, "Displayvisning vid
# forcering och ECO".
FLOW_OFF: Final = "off"
FLOW_MIN: Final = "min"
FLOW_ECO: Final = "eco"
FLOW_NORMAL: Final = "normal"
FLOW_ECO2: Final = "eco2"
FLOW_FORCED: Final = "forced"
FLOW_STATES: Final[tuple[str, ...]] = (
    FLOW_OFF,
    FLOW_MIN,
    FLOW_ECO,
    FLOW_NORMAL,
    FLOW_ECO2,
    FLOW_FORCED,
)
# The fan output is analogue and drifts a little around its setpoint, so the
# named speeds need a tolerance band rather than an exact match.
FLOW_TOLERANCE: Final = 1.5

# What the unit is doing with the air. Home Assistant's HVAC actions have no
# value for an open bypass, so these live in a sensor of their own. The
# precedence is the controller's, carried over from the integration this one
# replaces: cooling beats bypass, bypass beats heating, recycling is the rest.
STATE_OFF: Final = "off"
STATE_RECYCLING: Final = "recycling"
STATE_HEATING: Final = "heating"
STATE_BYPASS: Final = "bypass"
STATE_COOLING: Final = "cooling"
STATE_DEFROSTING: Final = "defrosting"
# VPac1.HeatType: what the heating output drives. A unit has one or the other,
# so entities that only make sense for one kind are not created for the other.
HEAT_TYPE_WATER: Final = 0
HEAT_TYPE_ELECTRIC: Final = 1
HEAT_TYPE_WATER_PWM: Final = 2
HEAT_TYPES: Final[dict[int, str]] = {
    HEAT_TYPE_WATER: "water",
    HEAT_TYPE_ELECTRIC: "electric",
    HEAT_TYPE_WATER_PWM: "water_pwm",
}
WATER_HEATING: Final[tuple[int, ...]] = (HEAT_TYPE_WATER, HEAT_TYPE_WATER_PWM)
ELECTRIC_HEATING: Final[tuple[int, ...]] = (HEAT_TYPE_ELECTRIC,)

OPERATING_STATES: Final[tuple[str, ...]] = (
    STATE_OFF,
    STATE_RECYCLING,
    STATE_HEATING,
    STATE_BYPASS,
    STATE_COOLING,
    STATE_DEFROSTING,
)
