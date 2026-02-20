import asyncio
import csv
import struct
import math
import signal
import sys
from datetime import datetime
from bleak import BleakClient, BleakScanner
from grove.grove_gsr_sensor import GroveGSRSensor
from grove.adc import ADC
import time



# --- Constants ---
# Standard Heart Rate Service
UUID_HR_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"

# Polar Proprietary PMD Service (for ECG)
UUID_PMD_SERVICE = "fb005c80-02e7-f387-1cad-8acd2d8df0c"
UUID_PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
UUID_PMD_DATA    = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

GET_SETTINGS_COMMAND = b'\x01'

# Commands
# 0x02 = Start, 0x09 = ECG, followed by settings (130Hz, etc.)
# ECG_WRITE_CMD = bytearray([0x02, 0x09, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
ECG_WRITE_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
PPG_WRITE_CMD = bytearray([0x02, 0x01, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])
PPI_WRITE_CMD = bytearray([0x02, 0x03, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])
SESSION_NAME = None
ADC_CHANNEL = 0

class PolarMultiStreamManager:
    def __init__(self, filename_prefix="polar_session"):
        self.prefix = filename_prefix
        self.client_H10 = None
        self.client_OH1 = None
        self.running_H10 = False
        self.running_OH1 = False
        self.running_gsr = False
        self.gsr_sensor = GroveGSRSensor(ADC_CHANNEL)

        # H10 Buffers
        self.data_hr_rr_H10 = [] # [timestamp, hr, rr_intervals_ms]
        self.data_ecg_H10 = []   # [timestamp, voltage_uv]

        # OH1 Buffers
        self.data_hr_rr_OH1 = [] # [timestamp, hr, rr_intervals_ms]
        self.data_ppg_OH1 = []   # [timestamp, PPG0, PPG1, PPG2, ambient]

        #GSR buffer
        self.data_gsr = []
    
    def notification_handler(self, characteristic, data: bytearray):
            print(f"Received response from {UUID_PMD_CONTROL}: {data.hex()}")
   

    async def connect_H10(self):
        print("Scanning for Polar H10...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name and "Polar H10" in d.name
        )
        
        if not device:
            raise RuntimeError("Polar H10 not found.")

        print(f"Connecting to {device.name}...")
        self.client_H10 = BleakClient(device)
        await self.client_H10.connect()
        print(f"Connected to {device.address}")

    async def connect_OH1(self):
        print("Scanning for Polar OH1+...")
        
        target_address = "24:AC:AC:02:1A:05"
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: d.address.upper() == target_address.upper()  
        )
        if not device:
            raise RuntimeError("Polar OH1+ not found.")

        print(f"Connecting to {device.name}...")
        self.client_OH1 = BleakClient(device)
        await self.client_OH1.connect()
        print(f"Connected to {device.address}")


    def _parse_pmd_data_OH1(self, sender, data: bytearray):
        """Combined parser for PMD data from OH1"""
        if len(data) < 1:
            return
        
        measurement_type = data[0]
        
        if measurement_type == 0x03:  # PPI data
            self._parse_ppi_OH1(sender, data)
        elif measurement_type == 0x01:  # PPG data
            self._parse_ppg(sender, data)
        else:
            print(f"Unknown measurement type: {measurement_type:#x}")


    def _parse_ppg(self, sender, data: bytearray):
        """Parses polar OH1+ PPG packet"""
        
        if len(data) < 22:
            return
        
        if data[0] != 0x01:  # 0x01 = PPG
            return
        
        # Check compression
        if (data[9] & 0x80) != 0:
            print("Compressed PPG data not supported")
            return
        
        # Frame data starts at byte 10
        frame_offset = 10
        
        # Each value is 3 bytes, interpret first 2 as 16-bit little-endian

        # print(f"ppg0 byte 0: {hex(data[frame_offset])}")
        # print(f"ppg0 byte 1`: {hex(data[frame_offset+1])}")
        # print(f"ppg0 byte 2`: {hex(data[frame_offset+2])}")
        # print(f"ambient byte`: {hex(data[frame_offset+6:frame_offset+9])}")

        # print(f"raw ppg0: {int.from_bytes(data[frame_offset:frame_offset+3])}| raw ppg0: {int.from_bytes(data[frame_offset+3:frame_offset+6])}| raw ppg0: {int.from_bytes(data[frame_offset+6:frame_offset+9])}| raw ambient: {int.from_bytes(data[frame_offset+9:frame_offset+12])}")

        ppg0 = int.from_bytes(data[frame_offset:frame_offset+2], byteorder='little')
        ppg1 = int.from_bytes(data[frame_offset+3:frame_offset+5], byteorder='little')
        ppg2 = int.from_bytes(data[frame_offset+6:frame_offset+8], byteorder='little')
        ambient = int.from_bytes(data[frame_offset+9:frame_offset+11], byteorder='little')

        ts = datetime.now().strftime("%H:%M:%S.%f")
        print(f"[{ts}] PPG0: {ppg0} | PPG1: {ppg1} | PPG2: {ppg2} | ambient: {ambient}")
        
        self.data_ppg_OH1.append([ts, ppg0, ppg1, ppg2, ambient])

    def _parse_ppi_OH1(self, sender, data: bytearray):
        """Parse PPI (Peak-to-Peak Interval) data from OH1"""
        
        # Check minimum length
        if len(data) < 17:
            # This is actually normal - some packets are shorter
            return
        
        measurement_type = data[0]
        timestamp = data[1:9]
        frame_type = data[9]
        hr = data[10]
        pp_interval = int.from_bytes(data[11:13], byteorder='little')
        pp_error_est = int.from_bytes(data[13:16], byteorder='little')
        pp_flags = data[16]

        # Bit 0: 0 = valid, 1 = invalid
        # Bit 1: 0 = no contact, 1 = contact detected  
        # Bit 2: 0 = contact supported, 1 = not supported
        
        is_valid = not (pp_flags & 0x01)
        has_contact = bool(pp_flags & 0x02)
        contact_supported = not (pp_flags & 0x04)

        if not is_valid:
            # Measurement not valid - skip silently or uncomment to debug
            # print("PPI: measurement not valid")
            return
        
        if contact_supported and not has_contact:
            # Contact detection is supported but no contact detected
            # print("PPI: no sensor contact")
            return

        # Convert PP interval to milliseconds (1/1024s to ms)
        pp_ms = (pp_interval / 1024.0) * 1000.0
        
        ts = datetime.now().strftime("%H:%M:%S.%f")
        print(f"OH1 PPI: [{ts}] HR: {hr} | PP: {pp_ms:.2f}ms | Flags: {pp_flags:#04x}")

    def _parse_hr_rr_OH1(self, sender, data: bytearray):
        """
        Parses standard HR Measurement with RR intervals.
        Byte 0: Flags
        Byte 1/2: HR
        Byte 2+: RR intervals (if flag bit 4 is set)
        """


        if data[-1] & 0x80 == 1:
            print("OH1 hr data is compressed.")

        if len(data) < 2:
            print(f"OH1 HR packet too short: {len(data)} bytes")
            return

        


        flags = data[0]
        hr_fmt_uint16 = flags & 0x01
        rr_present = (flags & 0x10) >> 4
        sensor_contact = (flags & 0x06) >> 1  # Bits 1-2

        # Parse Heart Rate
        if hr_fmt_uint16:
            hr = int.from_bytes(data[1:3], byteorder='little')
            offset = 3
        else:
            hr = data[1]
            offset = 2

        


        # Parse RR Intervals (if present)
        # RR values are in 1/1024 seconds
        rrs_ms = []
        if rr_present:
            while offset < len(data):
                # RR intervals are always uint16
                raw_rr = int.from_bytes(data[offset:offset+2], byteorder='little')
                # Convert 1/1024s to milliseconds
                val_ms = (raw_rr / 1024.0) * 1000.0
                rrs_ms.append(round(val_ms, 2))
                offset += 2


        ts = datetime.now().strftime("%H:%M:%S.%f")
        # if rr_present:
        #     print(f"OH1: [{ts}] HR: {hr} | RRs (ms): {rrs_ms} | Contact: {sensor_contact}")
        # else:
        #     print(f"OH1: [{ts}] HR: {hr}")
        


        # Store as string representation of list for CSV
        self.data_hr_rr_OH1.append([ts, hr])

    def _parse_hr_rr_H10(self, sender, data: bytearray):
        """
        Parses standard HR Measurement with RR intervals.
        Byte 0: Flags
        Byte 1/2: HR
        Byte 2+: RR intervals (if flag bit 4 is set)
        """

        

        flags = data[0]
        hr_fmt_uint16 = flags & 0x01
        rr_present = (flags & 0x10) >> 4

        # Parse Heart Rate
        if hr_fmt_uint16:
            hr = int.from_bytes(data[1:3], byteorder='little')
            offset = 3
        else:
            hr = data[1]
            offset = 2

        # Parse RR Intervals (if present)
        # RR values are in 1/1024 seconds
        rrs_ms = []
        if rr_present:
            while offset < len(data):
                # RR intervals are always uint16
                raw_rr = int.from_bytes(data[offset:offset+2], byteorder='little')
                # Convert 1/1024s to milliseconds
                val_ms = (raw_rr / 1024.0) * 1000.0
                rrs_ms.append(round(val_ms, 2))
                offset += 2

        ts = datetime.now().strftime("%H:%M:%S.%f")
        # print(f"H10: [{ts}] HR: {hr} | RRs (ms): {rrs_ms}")
        
        # Store as string representation of list for CSV
        self.data_hr_rr_H10.append([ts, hr, str(rrs_ms)])

    def _parse_ecg(self, sender, data: bytearray):
        """
        Parses Polar PMD ECG packet.
        Format:
        - Byte 0: Frame Type (0x00 for raw data)
        - Byte 1-8: Timestamp (u64)
        - Byte 9: Frame type
        - Byte 10+: Samples (3 bytes each, 24-bit 2's complement, microvolts)
        """

        # print("made it to parse ECG loop")

        # print(sender)

        if data[0] != 0x00:
            return # Ignore non-data frames

        if data[-1] & 0x80 == 1:
            print("This data is compressed.")

        # r = data[9] & 0x7F
        # print(f"result of data[9]: {r}")


        # Helper to parse 24-bit signed int
        def parse_24bit(b_arr):
            # Pad with 0x00 or 0xFF depending on sign bit (bit 23)
            # if (b_arr[2] & 0x80) -> negative
            val = int.from_bytes(b_arr, byteorder='little', signed=True)
            return val

        # Iterate over samples starting at byte 10
        # Step is 3 bytes
        timestamp_base = datetime.now() # Using system time for sync simplicity
        
        step = 3
        samples = []
        
        for i in range(10, len(data) - 1, step):
            sample_bytes = data[i:i+step]
            if len(sample_bytes) < 3: break
            
            uv_val = parse_24bit(sample_bytes)
            samples.append(uv_val)

        # Bulk append
        # Note: A real production system might interpolate the micro-timestamps 
        # based on the 130Hz sampling rate, but here we timestamp the batch.
        ts_str = timestamp_base.strftime("%H:%M:%S.%f")
        
        average_voltage = sum(samples) / len(samples)

        # print(f"H10: [{ts_str}] Voltage: {average_voltage}")
        for s in samples:
            self.data_ecg_H10.append([ts_str, s])

    async def _parse_gsr(self):
        try:
            epoch_now = time.time()
            gsr_value = self.gsr_sensor.GSR
            self.data_gsr.append([epoch_now, gsr_value])
        except Exception as e:
            print(f"GSR read error: {e}")

    async def start_streaming_GSR(self):
        self.running_gsr = True
        next_time = time.time() + 0.3
        while self.running_gsr:
            await self._parse_gsr()
            sleep_duration = max(0, next_time - time.time())
            await asyncio.sleep(sleep_duration)
            next_time += 0.3

    async def start_streaming_H10(self):
        if not self.client_H10.is_connected:
            raise RuntimeError("Not connected")

        #receive settings from control point
        await self.client_H10.start_notify(UUID_PMD_CONTROL , self.notification_handler)
        
        await self.client_H10.write_gatt_char(UUID_PMD_CONTROL, GET_SETTINGS_COMMAND, response=True)
        print("Command sent. Waiting for response...")
        await asyncio.sleep(5) 
        await self.client_H10.stop_notify(UUID_PMD_CONTROL)


        
        # 1. Start Standard HR/RR Stream
        await self.client_H10.start_notify(UUID_HR_MEASUREMENT, self._parse_hr_rr_H10)
        print("H10 HR/RR stream started.")

        # 2. Start Proprietary ECG Stream
        # Subscribe to Data Notification first
        await self.client_H10.start_notify(UUID_PMD_DATA, self._parse_ecg)
        # Write Start Command to Control Point

        

        await self.client_H10.write_gatt_char(UUID_PMD_CONTROL, ECG_WRITE_CMD)
        print("H10 ECG stream started.")
        
        self.running_H10 = True
        while self.running_H10:
            await asyncio.sleep(1)


    async def start_streaming_OH1(self):
        if not self.client_OH1.is_connected:
            raise RuntimeError("OH1+ Not connected")

        #Get settings command
        await self.client_OH1.start_notify(UUID_PMD_CONTROL, self.notification_handler)
        await self.client_OH1.write_gatt_char(UUID_PMD_CONTROL, GET_SETTINGS_COMMAND, response=True)
        print("Command sent. Waiting for response...")
        await asyncio.sleep(5) 
        await self.client_OH1.stop_notify(UUID_PMD_CONTROL)

        # Start Standard HR/RR Stream
        await self.client_OH1.start_notify(UUID_HR_MEASUREMENT, self._parse_hr_rr_OH1)
        print("OH1+ HR/RR stream started.")

        #Start SINGLE PMD Data stream (handles both PPI and PPG)
        await self.client_OH1.start_notify(UUID_PMD_DATA, self._parse_pmd_data_OH1)
        
        # # Start PPI stream
        # # await self.client_OH1.write_gatt_char(UUID_PMD_CONTROL, PPI_WRITE_CMD)
        # # print("OH1+ PPI stream started.")
        
        # await asyncio.sleep(0.5)  # Small delay between commands
        
        # Start PPG stream
        await self.client_OH1.write_gatt_char(UUID_PMD_CONTROL, PPG_WRITE_CMD)
        print("OH1+ PPG stream started.")
        
        self.running_OH1 = True
        while self.running_OH1:
 
    async def stop_and_save(self):
        """Disconnect and save data"""
        # Disconnect clients
        if self.client_H10 and self.client_H10.is_connected:
            try:
                await self.client_H10.disconnect()
                print("H10 disconnected")
            except Exception as e:
                print(f"Error disconnecting H10: {e}")
        
        if self.client_OH1 and self.client_OH1.is_connected:
            try:
                await self.client_OH1.disconnect()
                print("OH1 disconnected")
            except Exception as e:
                print(f"Error disconnecting OH1: {e}")


        self._save_csvs()

    def _save_csvs(self):
        # Save HR/RR for H10
        fn_hr_h10 = f"{SESSION_NAME}_{self.prefix}_hr_rr_h10.csv"
        print(f"H10: Saving {len(self.data_hr_rr_H10)} HR records to {fn_hr_h10}...")
        with open(fn_hr_h10, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "HR", "RR_Intervals_ms"])
            w.writerows(self.data_hr_rr_H10)

        #Save HR for OH1
        fn_hr_oh1 = f"{SESSION_NAME}_{self.prefix}_hr_rr_oh1.csv"
        print(f"OH1: Saving {len(self.data_hr_rr_OH1)} HR records to {fn_hr_oh1}...")
        with open(fn_hr_oh1, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "HR"])
            w.writerows(self.data_hr_rr_OH1)
        
        # Save ECG
        fn_ecg = f"{SESSION_NAME}_{self.prefix}_ecg_h10.csv"
        print(f"H10: Saving {len(self.data_ecg_H10)} ECG samples to {fn_ecg}...")
        with open(fn_ecg, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Packet_Timestamp", "ECG_uV"])
            w.writerows(self.data_ecg_H10)

        #Save PPG
        fn_ppg = f"{SESSION_NAME}_{self.prefix}_ppg_oh1.csv"
        print(f"OH1: Saving {len(self.data_ppg_OH1)} PPG samples to {fn_ppg}...")
        with open(fn_ppg, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "ppg0", "ppg1", "ppg2", "ambient"])
            w.writerows(self.data_ppg_OH1)


        #save gsr 
        fn_gsr = f"{SESSION_NAME}_{self.prefix}_gsr.csv"
        print(f"GSR: Saving {len(self.data_gsr)} GSR samples to {fn_gsr}...")
        with open(fn_gsr, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "voltage"])
            w.writerows(self.data_gsr)

async def main():
    manager = PolarMultiStreamManager()
    
    # Signal handling boilerplate
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    def signal_handler(): stop_event.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    stream_task1 = None
    stream_task2 = None
    stream_task3 = None 
    try:
        await manager.connect_H10()
        await manager.connect_OH1()
        stream_task1 = asyncio.create_task(manager.start_streaming_H10())
        stream_task2 = asyncio.create_task(manager.start_streaming_OH1())
        stream_task3 = asyncio.create_task(manager.start_streaming_GSR())
        
        await stop_event.wait() # Wait for Ctrl+C
        
        # manager.running = False
        # try:
        #     await asyncio.wait_for(stream_task1, timeout=2.0)
        # except asyncio.TimeoutError: pass
            
    except Exception as e:
        print(f"Runtime Error: {e}")
    finally:
        print("Shutting down...")
        manager.running_H10 = False
        manager.running_OH1 = False
        manager.running_gsr = False


        tasks = [t for t in [stream_task1, stream_task2, stream_task3] if t is not None]
        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            if manager.client_H10 and manager.client_H10.is_connected:
                await manager.client_H10.stop_notify(UUID_HR_MEASUREMENT)
        except Exception as e:
            print(f"Error stopping H10 notifications: {e}")
        
        try:
            if manager.client_OH1 and manager.client_OH1.is_connected:
                await manager.client_OH1.stop_notify(UUID_PMD_DATA)
        except Exception as e:
            print(f"Error stopping OH1 notifications: {e}")
        
        # Small delay for BlueZ cleanup
        await asyncio.sleep(0.5)
        
        # Now disconnect and save
        await manager.stop_and_save()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if len(sys.argv) < 3:
        print("Usage: python read_file.py <session_name> <grove_adc_channel>")
        sys.exit(1)

    SESSION_NAME = sys.argv[1]
    ADC_CHANNEL = int(sys.argv[2])

    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass