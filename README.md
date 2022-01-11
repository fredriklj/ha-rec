# Home assistant integration for Rec Temovex balanced ventilation system

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

[![Discord][discord-shield]][discord]
[![Community Forum][forum-shield]][forum]

This component allows for integration of Rec Temovex balanced ventilation systems with modbus functionality to be integrated into [home assistant](https://home-assistant.io/). It will set up the following platforms:

Platform | Description
-- | --
`climate` | A climate control
`binary_sensor` | Show something `True` or `False`.
`sensor` | Show info from blueprint API.
`switch` | Switch something `True` or `False`.

## HACS Installation

1. Add this repository to "Custom repositories"
2. Add and search for porscheconnect in HACS
3. Install

## Manual installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it.
3. In the `custom_components` directory (folder) create a new folder called `ha-rec`.
4. Download _all_ the files from the `custom_components/ha-rec/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Integration blueprint"

Using your HA configuration directory (folder) as a starting point you should now also have this:

```text
custom_components/ha-rec/translations/en.json
custom_components/ha-rec/translations/nb.json
custom_components/ha-rec/translations/sensor.nb.json
custom_components/ha-rec/__init__.py
custom_components/ha-rec/api.py
custom_components/ha-rec/binary_sensor.py
custom_components/ha-rec/config_flow.py
custom_components/ha-rec/const.py
custom_components/ha-rec/manifest.json
custom_components/ha-rec/sensor.py
custom_components/ha-rec/switch.py
```

## Configuration is done in the UI

<!---->

## Contributions are welcome!

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

***

[ha-rec]: https://github.com/custom-components/ha-rec
[commits-shield]: https://img.shields.io/github/commit-activity/y/fredriklj/ha-rec/blueprint.svg?style=for-the-badge
[commits]: https://github.com/fredriklj/ha-rec/commits/master
[hacs]: https://hacs.xyz
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[discord]: https://discord.gg/Qa5fW2R
[discord-shield]: https://img.shields.io/discord/330944238910963714.svg?style=for-the-badge
[forum-shield]: https://img.shields.io/badge/community-forum-brightgreen.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[license-shield]: https://img.shields.io/github/license/fredriklj/ha-rec.svg?style=for-the-badge
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40fredriklj-blue.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/fredriklj/ha-rec.svg?style=for-the-badge
[releases]: https://github.com/fredriklj/ha-rec/releases
