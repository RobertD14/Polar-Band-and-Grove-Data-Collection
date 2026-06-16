import argparse
import asyncio
from bleak import BleakClient
from pylsl import StreamInfo, StreamOutlet

# UUIDs corrects for Polar OH1
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

# Start the streams (PPG and HR) with PMD commands
START_PPG = bytearray([0x02, 0x01, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])


def create_outlets(mac_address: str):
    mac_key = mac_address.upper().replace(':', '')
    hr_info = StreamInfo(f"PolarOH1_{mac_key}_HR", "HR", 1, 1, "float32", f"oh1_hr_{mac_key}")
    ppg_info = StreamInfo(f"PolarOH1_{mac_key}_PPG", "PPG", 3, 130, "float32", f"oh1_ppg_{mac_key}")
    return StreamOutlet(hr_info), StreamOutlet(ppg_info)


def handle_hr(sender, data):
    flags = data[0]
    hr = int.from_bytes(data[1:3], 'little') if flags & 0x01 else data[1]
    hr_outlet.push_sample([float(hr)])
    #print(f"HR : {hr} bpm")


def handle_pmd_response(sender, data):
    print(f"PMD Response: {data.hex()}")


def handle_ppg(sender, data):
    if data[0] != 0x01:
        print(f"PPG : Unexpected {data[0]:#x}, ignored")
        return
    i = 9
    count = 0
    while i + 9 <= len(data):
        ch0 = int.from_bytes(data[i:i+3],   'little', signed=True)
        ch1 = int.from_bytes(data[i+3:i+6], 'little', signed=True)
        ch2 = int.from_bytes(data[i+6:i+9], 'little', signed=True)
        ppg_outlet.push_sample([float(ch0), float(ch1), float(ch2)])
        i += 9
        count += 1
    #print(f"PPG : {count} sample(s) — ch0={ch0}, ch1={ch1}, ch2={ch2}")


async def main(device_address: str):
    print(f"Connecting to Polar OH1 at {device_address}...")
    global hr_outlet, ppg_outlet
    hr_outlet, ppg_outlet = create_outlets(device_address)

    async with BleakClient(device_address) as client:
        print("Connected.")

        caps = await client.read_gatt_char(PMD_CONTROL)
        print(f"PMD capacity : {caps.hex()}")

        await client.start_notify(PMD_CONTROL, handle_pmd_response)
        await client.write_gatt_char(PMD_CONTROL, START_PPG, response=True)
        await asyncio.sleep(1)

        await client.start_notify(PMD_DATA, handle_ppg)
        await client.start_notify(HR_UUID, handle_hr)

        print("Streams LSL active (HR + PPG). Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polar OH1 LSL streamer")
    parser.add_argument("--mac", "--address", dest="address", required=True, help="BLE MAC address of the Polar OH1")
    args = parser.parse_args()
    asyncio.run(main(args.address))
