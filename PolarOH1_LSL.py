import asyncio
import struct
from bleak import BleakClient
from pylsl import StreamInfo, StreamOutlet

DEVICE_ADDRESS = "24:AC:AC:02:1A:05"     # change with your Polar OH1 address

# UUIDs corrects for Polar OH1
HR_UUID      = "00002a37-0000-1000-8000-00805f9b34fb" # standard HR measurement, don't change
PMD_CONTROL  = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"  # PMD control point, don't change
PMD_DATA     = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"  # PMD data stream, don't change

# Start the streams (PPG and HR) with PMD commands
START_PPG = bytearray([0x02, 0x01, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])

# LSL outlets
hr_info  = StreamInfo("PolarOH1_HR",  "HR",  1,   1, "float32", "oh1_hr")
ppg_info = StreamInfo("PolarOH1_PPG", "PPG", 3, 130, "float32", "oh1_ppg")
hr_outlet  = StreamOutlet(hr_info)
ppg_outlet = StreamOutlet(ppg_info)

def handle_hr(sender, data):
    flags = data[0]
    hr = int.from_bytes(data[1:3], 'little') if flags & 0x01 else data[1]
    hr_outlet.push_sample([float(hr)])
    print(f"HR : {hr} bpm")

def handle_pmd_response(sender, data):
    print(f"PMD Response: {data.hex()}")

def handle_ppg(sender, data):
    if data[0] != 0x01:
        print(f"PPG : Unexpected {data[0]:#x}, ignored")
        return
    # Octet 0 = type, octets 1-8 = timestamp, suite = échantillons (3x3 octets)
    i = 9
    count = 0
    while i + 9 <= len(data):
        ch0 = int.from_bytes(data[i:i+3],   'little', signed=True)
        ch1 = int.from_bytes(data[i+3:i+6], 'little', signed=True)
        ch2 = int.from_bytes(data[i+6:i+9], 'little', signed=True)
        ppg_outlet.push_sample([float(ch0), float(ch1), float(ch2)])
        i += 9
        count += 1
    print(f"PPG : {count} sample(s) — ch0={ch0}, ch1={ch1}, ch2={ch2}")

async def main():
    async with BleakClient(DEVICE_ADDRESS) as client:
        print("Connecté.")

        # Read PMD capacity
        caps = await client.read_gatt_char(PMD_CONTROL)
        print(f"PMD capacity : {caps.hex()}")

        # Subscribe to PMD responses
        await client.start_notify(PMD_CONTROL, handle_pmd_response)

        # Sending the PMD command to start PPG streaming
        await client.write_gatt_char(PMD_CONTROL, START_PPG, response=True)
        await asyncio.sleep(1)

        # Subscribe to PPG data
        await client.start_notify(PMD_DATA, handle_ppg)

        # Subscribe to HR data
        await client.start_notify(HR_UUID, handle_hr)

        print("Streams LSL active (HR + PPG). Ctrl+C to stop.")
        while True:
            await asyncio.sleep(1)

asyncio.run(main())