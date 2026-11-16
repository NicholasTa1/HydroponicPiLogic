"""Print the Edenic devices on your organisation, to find a device id for .env.

    python3 list_edenic_devices.py
"""

import json

from sensors.edenic import list_devices


def main():
    devices = list_devices()
    if not devices:
        print("no devices returned — check EDENIC_ORGANIZATION_ID")
        return

    for device in devices:
        # `label` is the name shown in the Edenic app; `name` is an internal
        # organisation__serial string, which is no use for picking a device out.
        name = device.get("label") or device.get("name") or "(unnamed)"
        print(f"{name}\n  id: {device.get('id')}\n")

    print("Put the id of your Guardian into .env as EDENIC_DEVICE_ID.")
    print("\nRaw response, if the fields above look wrong:")
    print(json.dumps(devices, indent=2)[:1500])


if __name__ == "__main__":
    main()
