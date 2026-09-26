# Rec Temovex for Home Assistant
[![CI](https://github.com/fredriklj/ha-rec/actions/workflows/push.yaml/badge.svg)](https://github.com/fredriklj/ha-rec/actions/workflows/push.yaml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

Home Assistant integration for **Rec Temovex** ventilation units with a Modbus
interface. Local polling, configured from the UI.

## Requirements

- **Modbus enabled from the factory.** It is a factory option; if the unit's
  panel has no Modbus menu, contact REC.
- **Cascade room control** (*kaskad rumsreglering*). The climate entity shows
  room temperature against the room setpoint, which is only what the unit
  regulates on in this mode. Other modes work, with a warning in the log.
- **A way to reach the unit's RS485 port**: a serial adapter on the Home
  Assistant host, or a Modbus TCP gateway.

## Installation

Via HACS: add `https://github.com/fredriklj/ha-rec` as a custom repository of
type **Integration**, install **Rec Temovex** and restart Home Assistant.

Manually: copy `custom_components/rec_temovex/` into your
`config/custom_components/` and restart.

## Configuration

Settings → Devices & Services → **Add Integration** → *Rec Temovex*. Choose
serial or TCP and enter the connection details and the unit's Modbus address
(1 by default). The integration checks that what answers really is a Rec
Temovex before the entry is created.

## Development

```console
$ pip install -r requirements.test.txt
$ ruff check . && ruff format --check .
$ pytest
```

Python 3.13 is required. The register map is in
[`registers.py`](custom_components/rec_temovex/registers.py), taken from Regin's
*REC Signals* document for the Corrigo controller. `scripts/scan_registers.py`
reads a unit's address space read-only, for checking new registers.

## License

MIT
