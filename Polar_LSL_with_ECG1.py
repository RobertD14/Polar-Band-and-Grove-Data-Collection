import argparse
import asyncio
import struct
from bleak import BleakScanner, BleakClient  # for Bluetooth Low Energy (BLE) communication
from pylsl import StreamInfo, StreamOutlet  # Python API for Lab Streaming Layer (LSL)

# Polar PMD UUIDs
PMD_COMMAND_CHAR = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA_CHAR = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

# Standard HR Service
UUID_HR_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'

# PMD Commands
# Format based on Polar H10 specification
ECG_WRITE_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])

def create_pmd_command(measurement_type):
    """Create a PMD command to start streaming a measurement type"""
    if measurement_type == 0:  # ECG
        return ECG_WRITE_CMD
    return None


def parse_ecg(data: bytearray) -> list[int]:
    if len(data) < 10:
        return []

    measurement_type = data[0]
    if measurement_type != 0x00:
        return []

    values = []
    for i in range(10, len(data) - 2, 3):
        value = int.from_bytes(data[i:i+3], byteorder='little', signed=True)
        values.append(value)

    return values


def parse_hr_data(data):
    """Parse standard Bluetooth Heart Rate Measurement"""
    if len(data) < 2:
        return None

    flags = data[0]
    hr_fmt_uint16 = flags & 0x01
    if hr_fmt_uint16:
        return struct.unpack('<H', data[1:3])[0]
    return data[1]


async def find_device_by_address(address: str, timeout: float = 15.0):
    address = address.upper()
    print(f"Scanning for Polar H10 at {address}...")
    return await BleakScanner.find_device_by_filter(
        lambda bd, ad: bd.address and bd.address.upper() == address,
        timeout=timeout,
    )


async def main(device_address: str):
    device_address = device_address.upper()
    device = await find_device_by_address(device_address)
    if not device:
        print("Device not found. Please ensure your Polar device is awake and nearby.")
        return

    print(f"Found {device.name or device_address}, connecting...")
    mac_key = device_address.replace(':', '')

    ecg_info = StreamInfo(f'PolarH10_{mac_key}_ECG', 'ECG', 1, 130, 'float32', f'polar_ecg_{mac_key}')
    hr_info = StreamInfo(f'PolarH10_{mac_key}_HR', 'HR', 1, 1, 'float32', f'polar_hr_{mac_key}')
    ecg_outlet = StreamOutlet(ecg_info)
    hr_outlet = StreamOutlet(hr_info)

    async with BleakClient(device.address) as client:
        print("Connected!")

        def on_pmd_data(sender, data):
            ecg_values = parse_ecg(data)
            if ecg_values:
                for ecg_val in ecg_values:
                    ecg_outlet.push_sample([float(ecg_val)])
                    #print(f"ECG: {ecg_val}")
            else:
                print(f"Parse failed for ECG data: {data.hex()}")

        def on_hr_data(sender, data):
            hr = parse_hr_data(data)
            if hr is not None:
                hr_outlet.push_sample([float(hr)])
                #print(f"HR: {hr}")
            else:
                print(f"Parse failed for HR data: {data.hex()}")

        started_hr = False
        started_ecg = False

        try:
            print("Enabling HR stream...")
            await client.start_notify(UUID_HR_MEASUREMENT, on_hr_data)
            started_hr = True
            print("HR stream enabled.")

            print("Enabling ECG stream...")
            await client.start_notify(PMD_DATA_CHAR, on_pmd_data)
            await client.start_notify(PMD_COMMAND_CHAR, lambda s, d: print(f"PMD response: {d.hex()}"))
            started_ecg = True

            ecg_cmd = create_pmd_command(0)
            if ecg_cmd is None:
                print("Failed to create ECG PMD command; check create_pmd_command().")
            else:
                print("Sending ECG start command...")
                await client.write_gatt_char(PMD_COMMAND_CHAR, ecg_cmd)
                print("ECG stream started.")

            print("Streaming ECG and HR data via LSL... (Ctrl+C to stop)")
            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("Interrupted by user.")

        except Exception as e:
            print(f"Error: {e}")

        finally:
            if started_hr:
                try:
                    await client.stop_notify(UUID_HR_MEASUREMENT)
                except Exception:
                    pass
            if started_ecg:
                try:
                    await client.stop_notify(PMD_DATA_CHAR)
                except Exception:
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polar H10 ECG + HR LSL streamer")
    parser.add_argument("--mac", "--address", dest="address", required=True, help="MAC address of the Polar H10 device")
    args = parser.parse_args()
    asyncio.run(main(args.address))
