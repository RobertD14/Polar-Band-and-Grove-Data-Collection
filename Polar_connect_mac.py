import asyncio
import argparse

from bleak import BleakScanner, BleakClient
from pylsl import StreamInfo, StreamOutlet

POLAR_KEYWORDS = ["polar", "h10", "oh1", "verity", "ignite", "vantage"]

# UUIDs
UUID_HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL_CHAR = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA_CHAR = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

# Commands
START_PPG = bytearray([0x02, 0x01, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])
ECG_WRITE_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])


def is_polar_device(device) -> bool:
    name = (device.name or "").lower()
    return any(k in name for k in POLAR_KEYWORDS)


def choose_device_from_scan(devices):
    if not devices:
        return None
    print("Appareils trouvés :")
    for i, d in enumerate(devices, start=1):
        print(f"  {i}) {d.name or '<unknown>'} — {d.address} (RSSI {d.rssi})")
    while True:
        choice = input("Choisir un numéro (ou q pour quitter): ").strip()
        if choice.lower() == 'q':
            return None
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(devices):
                return devices[idx-1]
        print("Entrée invalide.")


def detect_device_type(device) -> str:
    name = (device.name or "").lower()
    if "h10" in name:
        return "H10"
    if "oh1" in name:
        return "OH1"
    return "UNKNOWN"


def parse_hr_data(data: bytearray) -> float | None:
    if len(data) < 2:
        return None
    flags = data[0]
    if flags & 0x01:
        if len(data) < 3:
            return None
        hr = int.from_bytes(data[1:3], byteorder='little')
    else:
        hr = data[1]
    return float(hr)


def parse_oh1_ppg_payload(data: bytearray):
    if len(data) < 10 or data[0] != 0x01:
        return []
    samples = []
    i = 9
    while i + 9 <= len(data):
        ch0 = int.from_bytes(data[i:i+3], byteorder='little', signed=True)
        ch1 = int.from_bytes(data[i+3:i+6], byteorder='little', signed=True)
        ch2 = int.from_bytes(data[i+6:i+9], byteorder='little', signed=True)
        samples.append((float(ch0), float(ch1), float(ch2)))
        i += 9
    return samples


def parse_h10_ecg_payload(data: bytearray):
    if len(data) < 10 or data[0] != 0x00:
        return []
    values = []
    for i in range(10, len(data)-2, 3):
        v = int.from_bytes(data[i:i+3], byteorder='little', signed=True)
        values.append(float(v))
    return values


async def scan_polar(timeout: float = 10.0):
    print(f"Scanning for Polar devices ({timeout:.0f}s)...")
    all_devices = await BleakScanner.discover(timeout=timeout)
    return [d for d in all_devices if is_polar_device(d)]


async def connect_and_stream(device, device_type: str):
    tag = (device.name or 'PolarDevice').replace(' ', '_')

    if device_type == 'H10':
        ecg_info = StreamInfo(f"{tag}_ECG", "ECG", 1, 130, "float32", f"{tag}_ecg")
        hr_info = StreamInfo(f"{tag}_HR", "HR", 1, 1, "float32", f"{tag}_hr")
        ecg_outlet = StreamOutlet(ecg_info)
        hr_outlet = StreamOutlet(hr_info)

        def on_pmd_data(sender, data):
            vals = parse_h10_ecg_payload(bytearray(data))
            if not vals:
                return
            for v in vals:
                ecg_outlet.push_sample([v])

        def on_hr(sender, data):
            hr = parse_hr_data(bytearray(data))
            if hr is not None:
                hr_outlet.push_sample([hr])

        print(f"Connecting to H10: {device.name}")
        async with BleakClient(device) as client:
            print("Connected.")
            await client.start_notify(UUID_HR_MEASUREMENT, on_hr)
            await client.start_notify(PMD_DATA_CHAR, on_pmd_data)
            await client.start_notify(PMD_CONTROL_CHAR, lambda s, d: print(f"PMD resp: {d.hex()}"))
            await client.write_gatt_char(PMD_CONTROL_CHAR, ECG_WRITE_CMD)
            print("Streaming ECG + HR. Ctrl+C to stop.")
            try:
                while True:
                    await asyncio.sleep(1)
            finally:
                await client.stop_notify(UUID_HR_MEASUREMENT)
                await client.stop_notify(PMD_DATA_CHAR)

    else:  # OH1 or fallback
        hr_info = StreamInfo(f"{tag}_HR", "HR", 1, 1, "float32", f"{tag}_hr")
        ppg_info = StreamInfo(f"{tag}_PPG", "PPG", 3, 130, "float32", f"{tag}_ppg")
        hr_outlet = StreamOutlet(hr_info)
        ppg_outlet = StreamOutlet(ppg_info)

        def on_pmd_resp(sender, data):
            print(f"PMD: {data.hex()}")

        def on_hr(sender, data):
            hr = parse_hr_data(bytearray(data))
            if hr is not None:
                hr_outlet.push_sample([hr])

        def on_ppg(sender, data):
            samples = parse_oh1_ppg_payload(bytearray(data))
            for ch0, ch1, ch2 in samples:
                ppg_outlet.push_sample([ch0, ch1, ch2])

        print(f"Connecting to OH1: {device.name}")
        async with BleakClient(device) as client:
            print("Connected.")
            await client.start_notify(PMD_CONTROL_CHAR, on_pmd_resp)
            await client.write_gatt_char(PMD_CONTROL_CHAR, START_PPG, response=True)
            await asyncio.sleep(1)
            await client.start_notify(PMD_DATA_CHAR, on_ppg)
            await client.start_notify(UUID_HR_MEASUREMENT, on_hr)
            print("Streaming PPG + HR. Ctrl+C to stop.")
            try:
                while True:
                    await asyncio.sleep(1)
            finally:
                await client.stop_notify(PMD_CONTROL_CHAR)
                await client.stop_notify(PMD_DATA_CHAR)
                await client.stop_notify(UUID_HR_MEASUREMENT)


async def main(timeout: float = 10.0, auto_select: bool = False, name_filter: str | None = None):
    devices = await scan_polar(timeout=timeout)
    if name_filter:
        devices = [d for d in devices if name_filter.lower() in (d.name or '').lower()]

    if not devices:
        print("Aucun appareil Polar trouvé.")
        return

    device = None
    if auto_select and len(devices) == 1:
        device = devices[0]
    else:
        device = choose_device_from_scan(devices)

    if not device:
        print("Aucun appareil sélectionné, fin.")
        return

    dev_type = detect_device_type(device)
    if dev_type == 'UNKNOWN':
        print("Type d'appareil non détecté automatiquement.")
        choice = input("Est-ce un H10 (ECG) ? [y/N]: ").strip().lower()
        dev_type = 'H10' if choice in ('y', 'yes') else 'OH1'

    await connect_and_stream(device, dev_type)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Connect to Polar device without requiring MAC (Mac-friendly)')
    parser.add_argument('-t', '--timeout', type=float, default=10.0, help='Scan timeout in seconds')
    parser.add_argument('-a', '--auto', action='store_true', help='Auto-select if one device found')
    parser.add_argument('-n', '--name', type=str, help='Filter devices by name substring')
    args = parser.parse_args()

    try:
        asyncio.run(main(timeout=args.timeout, auto_select=args.auto, name_filter=args.name))
    except KeyboardInterrupt:
        print('\nStopped by user')
