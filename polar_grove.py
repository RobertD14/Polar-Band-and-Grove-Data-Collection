"""Polar Multi-Stream Manager."""

import asyncio
import contextlib
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from grove_gsr_sensor import GroveGSRSensor
from logs import LEVELS, LogLevel, configure_logger
from loguru import logger
from prompt_toolkit import prompt
from prompt_toolkit.validation import Validator

configure_logger()
ROOT = Path(__file__).parent

# --- Constants ---
# Standard Heart Rate Service
UUID_HR_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'

# Polar Proprietary PMD Service (for ECG)
UUID_PMD_SERVICE = 'fb005c80-02e7-f387-1cad-8acd2d8df0c'
UUID_PMD_CONTROL = 'fb005c81-02e7-f387-1cad-8acd2d8df0c8'
UUID_PMD_DATA = 'fb005c82-02e7-f387-1cad-8acd2d8df0c8'

GET_SETTINGS_COMMAND = b'\x01'

# Commands
# 0x02 = Start, 0x09 = ECG, followed by settings (130Hz, etc.)
# ECG_WRITE_CMD = bytearray([0x02, 0x09, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
ECG_WRITE_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
PPG_WRITE_CMD = bytearray([0x02, 0x01, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])
PPI_WRITE_CMD = bytearray([0x02, 0x03, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])
SESSION_NAME: str
ADC_CHANNEL: int

PPG_MEASUREMENT_TYPE = 0x01
PPI_MEASUREMENT_TYPE = 0x03

PPG_PACKET_LENGTH = 22
PPI_PACKET_LENGTH = 17
OH1_HR_PACKET_MIN_LENGTH = 2


class PolarMultiStreamManager:
    """Manages connections and data streaming from Polar H10, OH1+, and Grove GSR sensor."""

    client_H10: BleakClient
    client_OH1: BleakClient

    running_H10: bool = False
    running_OH1: bool = False
    running_gsr: bool = False

    def __init__(self, filename_prefix: str = 'polar_session') -> None:
        """Initialize data buffers and sensors."""
        self.prefix = filename_prefix
        self.gsr_sensor = GroveGSRSensor(ADC_CHANNEL)

        # H10 Buffers
        self.data_hr_rr_H10: list[tuple[str, int, str]] = []  # [timestamp, hr, rr_intervals_ms]
        self.data_ecg_H10: list[tuple[str, int]] = []  # [timestamp, voltage_uv]

        # OH1 Buffers
        self.data_hr_rr_OH1: list[tuple[str, int]] = []  # [timestamp, hr, rr_intervals_ms]
        self.data_ppg_OH1: list[tuple[str, int, int, int, int]] = []  # [timestamp, PPG0, PPG1, PPG2, ambient]

        # GSR buffer
        self.data_gsr: list[tuple[float, float]] = []

    def notification_handler(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Notification handler callback."""
        logger.info(f'Received response from {UUID_PMD_CONTROL}: {data.hex()}')

    async def connect_H10(self) -> None:
        """Scan and connect to Polar H10."""
        logger.debug('Scanning for Polar H10...')
        device = await BleakScanner.find_device_by_filter(lambda d, _: bool(d.name and 'Polar H10' in d.name))

        if not device:
            raise RuntimeError('Polar H10 not found.')

        logger.debug(f'Connecting to {device.name}...')
        self.client_H10 = BleakClient(device)
        await self.client_H10.connect()
        logger.success(f'Connected to {device.address}')

    async def connect_OH1(self) -> None:
        """Scan and connect to Polar OH1+."""
        logger.debug('Scanning for Polar OH1+...')

        target_address = '24:AC:AC:02:1A:05'
        device = await BleakScanner.find_device_by_filter(lambda d, _: d.address.upper() == target_address.upper())
        if not device:
            raise RuntimeError('Polar OH1+ not found.')

        logger.debug(f'Connecting to {device.name}...')
        self.client_OH1 = BleakClient(device)
        await self.client_OH1.connect()
        logger.success(f'Connected to {device.address}')

    def _parse_pmd_data_OH1(self, sender: BleakGATTCharacteristic, data: bytearray) -> None:
        """Combined parser for PMD data from OH1."""
        if data:
            if (measurement_type := data[0]) == PPI_MEASUREMENT_TYPE:
                self._parse_ppi_OH1(sender, data)
            elif measurement_type == PPG_MEASUREMENT_TYPE:
                self._parse_ppg(sender, data)
            else:
                logger.warning(f'Unknown measurement type: {measurement_type:#x}')

    def _parse_ppg(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Parses polar OH1+ PPG packet."""
        if len(data) < PPG_PACKET_LENGTH:
            return

        if data[0] != PPG_MEASUREMENT_TYPE:
            return

        # Check compression
        if (data[9] & 0x80) != 0:
            logger.error('Compressed PPG data not supported')
            return

        # Frame data starts at byte 10
        frame_offset = 10

        # Each value is 3 bytes, interpret first 2 as 16-bit little-endian

        # print(f"ppg0 byte 0: {hex(data[frame_offset])}")
        # print(f"ppg0 byte 1`: {hex(data[frame_offset+1])}")
        # print(f"ppg0 byte 2`: {hex(data[frame_offset+2])}")
        # print(f"ambient byte`: {hex(data[frame_offset+6:frame_offset+9])}")

        # print(f"raw ppg0: {int.from_bytes(data[frame_offset:frame_offset+3])}| raw ppg0: {int.from_bytes(data[frame_offset+3:frame_offset+6])}| raw ppg0: {int.from_bytes(data[frame_offset+6:frame_offset+9])}| raw ambient: {int.from_bytes(data[frame_offset+9:frame_offset+12])}")

        ppg0 = int.from_bytes(data[frame_offset : frame_offset + 2], byteorder='little')
        ppg1 = int.from_bytes(data[frame_offset + 3 : frame_offset + 5], byteorder='little')
        ppg2 = int.from_bytes(data[frame_offset + 6 : frame_offset + 8], byteorder='little')
        ambient = int.from_bytes(data[frame_offset + 9 : frame_offset + 11], byteorder='little')

        ts = time.strftime('%H:%M:%S')

        """
        time = datetime.now()

        if INITIAL_SECOND == 0
            last_time_second = 0

        time_second = time.second
        if time_second > last_time_second:

            print(f"[{ts}] ")

        last_time = datetime.now()

        last_time_second = last_time.second
        """

        self.data_ppg_OH1.append((ts, ppg0, ppg1, ppg2, ambient))

    def _parse_ppi_OH1(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Parse PPI (Peak-to-Peak Interval) data from OH1."""
        # Check minimum length
        if len(data) < PPI_PACKET_LENGTH:
            # This is actually normal - some packets are shorter
            return

        # measurement_type = data[0]
        # timestamp = data[1:9]
        # frame_type = data[9]
        hr = data[10]
        pp_interval = int.from_bytes(data[11:13], byteorder='little')
        # pp_error_est = int.from_bytes(data[13:16], byteorder='little')
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

        ts = datetime.now().strftime('%H:%M:%S.%f')
        logger.info(f'OH1 PPI: [{ts}] HR: {hr} | PP: {pp_ms:.2f}ms | Flags: {pp_flags:#04x}')

    def _parse_hr_rr_OH1(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Parses standard HR Measurement with RR intervals.

        Byte 0: Flags
        Byte 1/2: HR
        Byte 2+: RR intervals (if flag bit 4 is set)
        """
        if data[-1] & 0x80 == 1:
            logger.debug('OH1 hr data is compressed.')

        if len(data) < OH1_HR_PACKET_MIN_LENGTH:
            logger.warning(f'OH1 HR packet too short: {len(data)} bytes')
            return

        flags = data[0]
        hr_fmt_uint16 = flags & 0x01
        # rr_present = (flags & 0x10) >> 4
        # sensor_contact = (flags & 0x06) >> 1  # Bits 1-2

        # Parse Heart Rate
        hr = int.from_bytes(data[1:3], byteorder='little') if hr_fmt_uint16 else data[1]

        ts = datetime.now().strftime('%H:%M:%S.%f')
        # if rr_present:
        #     print(f"OH1: [{ts}] HR: {hr} | RRs (ms): {rrs_ms} | Contact: {sensor_contact}")
        # else:
        #     print(f"OH1: [{ts}] HR: {hr}")

        # Store as string representation of list for CSV
        self.data_hr_rr_OH1.append((ts, hr))

    def _parse_hr_rr_H10(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Parses standard HR Measurement with RR intervals.

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
                raw_rr = int.from_bytes(data[offset : offset + 2], byteorder='little')
                # Convert 1/1024s to milliseconds
                val_ms = (raw_rr / 1024.0) * 1000.0
                rrs_ms.append(round(val_ms, 2))
                offset += 2

        ts = datetime.now().strftime('%H:%M:%S.%f')
        # print(f"H10: [{ts}] HR: {hr} | RRs (ms): {rrs_ms}")

        # Store as string representation of list for CSV
        self.data_hr_rr_H10.append((ts, hr, str(rrs_ms)))

    def _parse_ecg(self, _: BleakGATTCharacteristic, data: bytearray) -> None:
        """Parses Polar PMD ECG packet.

        - Byte 0: Frame Type (0x00 for raw data)
        - Byte 1-8: Timestamp (u64)
        - Byte 9: Frame type
        - Byte 10+: Samples (3 bytes each, 24-bit 2's complement, microvolts)
        """
        if data[0] != 0x00:
            return  # Ignore non-data frames

        if data[-1] & 0x80 == 1:
            logger.debug('ECG data is compressed.')

        # r = data[9] & 0x7F
        # print(f"result of data[9]: {r}")

        # Iterate over samples starting at byte 10
        # Step is 3 bytes
        timestamp_base = datetime.now()  # Using system time for sync simplicity

        step = 3
        samples: list[int] = []

        for i in range(10, len(data) - 1, step):
            sample_bytes = data[i : i + step]
            if len(sample_bytes) < step:
                break

            uv_val = int.from_bytes(sample_bytes, byteorder='little', signed=True)
            samples.append(uv_val)

        # Bulk append
        # Note: A real production system might interpolate the micro-timestamps
        # based on the 130Hz sampling rate, but here we timestamp the batch.
        ts_str = timestamp_base.strftime('%H:%M:%S.%f')

        # average_voltage = sum(samples) / len(samples)

        # print(f"H10: [{ts_str}] Voltage: {average_voltage}")
        for s in samples:
            self.data_ecg_H10.append((ts_str, s))

    async def _parse_gsr(self) -> None:
        try:
            epoch_now = time.time()
            gsr_value = self.gsr_sensor.GSR
            self.data_gsr.append((epoch_now, gsr_value))
        except Exception as e:
            logger.error(f'GSR read error: {e}')

    async def start_streaming_GSR(self) -> None:
        """Starts the GSR streaming loop."""
        self.running_gsr = True
        next_time = time.time() + 0.3
        while self.running_gsr:
            await self._parse_gsr()
            sleep_duration = max(0, next_time - time.time())
            await asyncio.sleep(sleep_duration)
            next_time += 0.3

    async def start_streaming_H10(self) -> None:
        """Starts streaming HR/RR and ECG data from H10."""
        if not self.client_H10.is_connected:
            raise RuntimeError('Not connected')

        # receive settings from control point
        await self.client_H10.start_notify(UUID_PMD_CONTROL, self.notification_handler)

        await self.client_H10.write_gatt_char(UUID_PMD_CONTROL, GET_SETTINGS_COMMAND, response=True)
        logger.debug('Command sent. Waiting for response...')
        await asyncio.sleep(5)
        await self.client_H10.stop_notify(UUID_PMD_CONTROL)

        # 1. Start Standard HR/RR Stream
        await self.client_H10.start_notify(UUID_HR_MEASUREMENT, self._parse_hr_rr_H10)
        logger.success('H10 HR/RR stream started.')

        # 2. Start Proprietary ECG Stream
        # Subscribe to Data Notification first
        await self.client_H10.start_notify(UUID_PMD_DATA, self._parse_ecg)
        # Write Start Command to Control Point

        await self.client_H10.write_gatt_char(UUID_PMD_CONTROL, ECG_WRITE_CMD)
        logger.success('H10 ECG stream started.')

        self.running_H10 = True
        while self.running_H10:
            ts = time.strftime('%H:%M:%S')
            logger.info(f'[{ts}] ')
            await asyncio.sleep(1)

    async def start_streaming_OH1(self) -> None:
        """Starts streaming HR/RR and PPG data from OH1+."""
        if not self.client_OH1.is_connected:
            raise RuntimeError('OH1+ Not connected')

        # Get settings command
        await self.client_OH1.start_notify(UUID_PMD_CONTROL, self.notification_handler)
        await self.client_OH1.write_gatt_char(UUID_PMD_CONTROL, GET_SETTINGS_COMMAND, response=True)
        logger.debug('Command sent. Waiting for response...')
        await asyncio.sleep(5)
        await self.client_OH1.stop_notify(UUID_PMD_CONTROL)

        # Start Standard HR/RR Stream
        await self.client_OH1.start_notify(UUID_HR_MEASUREMENT, self._parse_hr_rr_OH1)
        logger.success('OH1+ HR stream started.')

        # Start SINGLE PMD Data stream (handles both PPI and PPG)
        await self.client_OH1.start_notify(UUID_PMD_DATA, self._parse_pmd_data_OH1)

        # # Start PPI stream
        # # await self.client_OH1.write_gatt_char(UUID_PMD_CONTROL, PPI_WRITE_CMD)
        # # print("OH1+ PPI stream started.")

        # await asyncio.sleep(0.5)  # Small delay between commands

        # Start PPG stream
        await self.client_OH1.write_gatt_char(UUID_PMD_CONTROL, PPG_WRITE_CMD)
        logger.success('OH1+ PPG stream started.')

        self.running_OH1 = True
        while self.running_OH1:
            await asyncio.sleep(1)

    async def stop_and_save(self) -> None:
        """Disconnect and save data."""
        # Disconnect clients
        if hasattr(self, 'client_H10') and self.client_H10.is_connected:
            try:
                await self.client_H10.disconnect()
                logger.success('H10 disconnected')
            except Exception as e:
                logger.error(f'Error disconnecting H10: {e}, error type: {type(e)}')

        await asyncio.sleep(0.5)

        if hasattr(self, 'client_OH1') and self.client_OH1.is_connected:
            try:
                await self.client_OH1.disconnect()
                logger.success('OH1 disconnected')
            except Exception as e:
                logger.error(f'Error disconnecting OH1: {e}, error type: {type(e)}')

        self._save_csvs()

    def _save_csvs(self) -> None:
        logger.info('Saving data to CSV files...')

        # Save HR/RR for H10
        fn_hr_h10 = f'{SESSION_NAME}_{self.prefix}_hr_rr_h10.csv'
        logger.debug(f'H10: Saving {len(self.data_hr_rr_H10)} HR records to {fn_hr_h10}...')
        pd.DataFrame(self.data_hr_rr_H10, columns=['Timestamp', 'HR', 'RR_Intervals_ms']).to_csv(fn_hr_h10, index=False)

        # Save HR for OH1
        fn_hr_oh1 = f'{SESSION_NAME}_{self.prefix}_hr_rr_oh1.csv'
        logger.debug(f'OH1: Saving {len(self.data_hr_rr_OH1)} HR records to {fn_hr_oh1}...')
        pd.DataFrame(self.data_hr_rr_OH1, columns=['Timestamp', 'HR']).to_csv(fn_hr_oh1, index=False)

        # Save ECG
        fn_ecg = f'{SESSION_NAME}_{self.prefix}_ecg_h10.csv'
        logger.debug(f'H10: Saving {len(self.data_ecg_H10)} ECG samples to {fn_ecg}...')
        pd.DataFrame(self.data_ecg_H10, columns=['Packet_Timestamp', 'ECG_uV']).to_csv(fn_ecg, index=False)

        # Save PPG
        fn_ppg = f'{SESSION_NAME}_{self.prefix}_ppg_oh1.csv'
        logger.debug(f'OH1: Saving {len(self.data_ppg_OH1)} PPG samples to {fn_ppg}...')
        columns = ['Timestamp', 'ppg0', 'ppg1', 'ppg2', 'ambient']
        pd.DataFrame(self.data_ppg_OH1, columns=columns).to_csv(fn_ppg, index=False)

        # save gsr
        fn_gsr = f'{SESSION_NAME}_{self.prefix}_gsr.csv'
        logger.debug(f'GSR: Saving {len(self.data_gsr)} GSR samples to {fn_gsr}...')
        pd.DataFrame(self.data_gsr, columns=['Timestamp', 'voltage']).to_csv(fn_gsr, index=False)

        logger.success('All data saved successfully.')


async def main() -> None:
    """Main entry point."""
    manager = PolarMultiStreamManager()

    # Signal handling boilerplate
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        stop_event.set()

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

        await stop_event.wait()  # Wait for Ctrl+C

        # manager.running = False
        # try:
        #     await asyncio.wait_for(stream_task1, timeout=2.0)
        # except asyncio.TimeoutError: pass

    except Exception as e:
        logger.critical(f'Runtime Error: {e}')
    finally:
        logger.info('Shutting down...')
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
            logger.error(f'Error stopping H10 notifications: {e}')

        try:
            if manager.client_OH1 and manager.client_OH1.is_connected:
                await manager.client_OH1.stop_notify(UUID_PMD_DATA)
        except Exception as e:
            logger.error(f'Error stopping OH1 notifications: {e}')

        # Small delay for BlueZ cleanup
        await asyncio.sleep(0.5)

        # Now disconnect and save
        await manager.stop_and_save()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    log_validator = Validator.from_callable(
        lambda x: x.strip().upper() in LEVELS,
        error_message=f'Please choose from {LEVELS}',
        move_cursor_to_end=True,
    )
    blank_validator = Validator.from_callable(
        lambda x: bool(x.strip()),
        error_message='This input cannot be blank',
        move_cursor_to_end=True,
    )
    yn_validator = Validator.from_callable(
        lambda x: x.strip().upper() in ('Y', 'N', ''),
        error_message='Please enter Y or N',
        move_cursor_to_end=True,
    )
    int_validator = Validator.from_callable(
        lambda x: x.isdigit(),
        error_message='This input contains non-numeric characters',
        move_cursor_to_end=True,
    )

    SESSION_NAME = prompt('>>> Session Name: ', validator=blank_validator)
    logfile = ROOT / f'{SESSION_NAME}.log'
    if logfile.exists():
        overwrite = prompt(
            f'>>> Log file found for session "{SESSION_NAME}". Overwrite? Y/[N]: ', validator=yn_validator
        )
        if overwrite.upper() != 'Y':
            logger.error('Aborting to prevent overwrite.')
            sys.exit(0)
    ADC_CHANNEL = int(prompt('>>> Grove ADC Channel: ', validator=int_validator))
    log_level: LogLevel = (
        prompt(
            '>>> Log verbosity level (TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL) [INFO]: ',
            validator=log_validator,
            default='INFO',
        )
        .strip()
        .upper()
    )  # type: ignore

    logger.success(f'Starting session "{SESSION_NAME}" using Grove ADC Channel {ADC_CHANNEL}')
    logger.info('Press Ctrl+C to stop and save data.')
    logger.info(f'Writing logs to {logfile}')
    configure_logger(log_level, file=logfile.open('w'))
    logger.log(log_level, f'Logging configured with verbosity level {log_level}')

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
