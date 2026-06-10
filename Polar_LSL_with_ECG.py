import asyncio
from xmlrpc import client
from bleak import BleakScanner, BleakClient #for Bluetooth Low Energy (BLE) communication
from pylsl import StreamInfo, StreamOutlet  #Python API for Lab Streaming Layer (LSL)
import struct

# --- Device configuration ---
POLAR_DEVICE_NAME = "Polar H10 099EED32"  #change the name

# Polar PMD UUIDs
PMD_SERVICE = "0000feee-0000-1000-8000-00805f9b34fb"  # not to change
PMD_COMMAND_CHAR = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"  # not to change
PMD_DATA_CHAR = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"  # not to change

# Standard HR Service
UUID_HR_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'  # not to change

# --- Create LSL streams ---
ecg_info = StreamInfo('PolarH10_099EED32_ECG', 'ECG', 1, 130, 'float32', 'polar_ecg')  #change the name
hr_info  = StreamInfo('PolarH10_099EED32_HR',  'HR',  1, 1,  'float32', 'polar_hr')  #change the name

ecg_outlet = StreamOutlet(ecg_info)
hr_outlet  = StreamOutlet(hr_info)

# PMD Commands
# Format based on Polar H10 specification
ECG_WRITE_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])

def create_pmd_command(measurement_type):
    """Create a PMD command to start streaming a measurement type"""
    if measurement_type == 0:  # ECG
        return ECG_WRITE_CMD
    return None

def parse_pmd_data(data):
    """Parse Polar PMD data format"""
    if len(data) < 4:
        return None
    
    # Frame type (1 byte) and measurement type (1 byte)
    frame_type = data[0]
    measurement_type = data[1]
    
    # Payload size (2 bytes, little-endian)
    payload_size = struct.unpack('<H', data[2:4])[0]
    
    # Skip header and parse payload (starts at index 4)
    if measurement_type == 0:  # ECG
        # ECG data format: 3 bytes per sample (24-bit little-endian signed)
        ecg_values = []
        for i in range(4, 4 + payload_size, 3):  # 3 bytes per ECG sample
            if i + 3 <= len(data):
                # Read 3 bytes as signed 24-bit value
                value_bytes = data[i:i+3]
                # Convert 3 bytes to 32-bit signed integer
                value = int.from_bytes(value_bytes, byteorder='little', signed=True)
                ecg_values.append(value)
        return ('ECG', ecg_values) if ecg_values else None
    
    elif measurement_type == 3:  # PPI (Heart Rate)
        # PPI data format: HR (uint16) and RR (uint16)
        if len(data) >= 6:
            hr = struct.unpack('<H', data[4:6])[0]
            return ('HR', hr)
    
    return None


def parse_ecg(data: bytearray) -> list[int]:
    if len(data) < 10:
        return []
    
    measurement_type = data[0]
    if measurement_type != 0x00:  # 0x00 = ECG
        return []
    
    # data[1:9] = timestamp (8 bytes) — ignored
    # data[9]   = frame type
    # data[10:] = ECG samples, 3 bytes each (int24 little-endian)
    
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
    
    # Parse Heart Rate
    if hr_fmt_uint16:
        hr = struct.unpack('<H', data[1:3])[0]
    else:
        hr = data[1]
    
    return hr

async def main():
    print(f"Scanning for {POLAR_DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_filter(
        lambda bd, ad: bd.name and POLAR_DEVICE_NAME in bd.name, timeout=15  # plus de temps
    )
    if not device:
        print("Device not found. Please ensure your Polar device is awake and nearby.")
        return

    print(f"Found {device.name}, connecting...")

    async with BleakClient(device.address) as client:
        print("Connected!")
        
        # Callback for PMD ECG data
        def on_pmd_data(sender, data):
            print(f"Raw ECG data received: {data.hex()} (len={len(data)})")
            ecg_values = parse_ecg(data)
            if ecg_values:
                for ecg_val in ecg_values:
                    ecg_outlet.push_sample([float(ecg_val)])
                    print(f"ECG: {ecg_val}")
            else:
                print(f"Parse failed for ECG data: {data.hex()}")
        
        # Callback for HR data
        def on_hr_data(sender, data):
            print(f"Raw HR data received: {data.hex()} (len={len(data)})")
            hr = parse_hr_data(data)
            if hr is not None:
                hr_outlet.push_sample([float(hr)])
                #print(f"HR: {hr}")
            else:
                print(f"Parse failed for HR data: {data.hex()}")
        
        try:
            # Enable HR/RR Stream
            print("Enabling HR stream...")
            await client.start_notify(UUID_HR_MEASUREMENT, on_hr_data)
            print("HR stream enabled.")
            
            # Enable PMD notifications for ECG
            print("Enabling ECG stream...")
            await client.start_notify(PMD_DATA_CHAR, on_pmd_data)
            # Start listening for PMD command responses
            await client.start_notify(PMD_COMMAND_CHAR, lambda s, d: print(f"PMD response: {d.hex()}"))

            # Prepare and send ECG start command
            ecg_cmd = create_pmd_command(0)  # 0 = ECG
            if ecg_cmd is None:
                print("Failed to create ECG PMD command; check create_pmd_command().")
            else:
                print("Sending ECG start command...")
                await client.write_gatt_char(PMD_COMMAND_CHAR, ecg_cmd)
                print("ECG stream started.")
            
            print("Streaming ECG and HR data via LSL... (Ctrl+C to stop)")
            while True:
                await asyncio.sleep(1)
        
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await client.stop_notify(UUID_HR_MEASUREMENT)
            await client.stop_notify(PMD_DATA_CHAR)

if __name__ == "__main__":
    asyncio.run(main())