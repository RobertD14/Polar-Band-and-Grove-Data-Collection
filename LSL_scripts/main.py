import asyncio
import subprocess
import sys
import tempfile
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from typing import Literal, Optional

from pylsl import StreamInfo, StreamOutlet
from bleak import BleakScanner

#file shared temporarily between the main process and the subprocesses
CATEGORY_FILE = os.path.join(tempfile.gettempdir(), "polar_category.txt")
CONDITION_FILE = os.path.join(tempfile.gettempdir(), "polar_condition_bit.txt")

# History file to log all events (START/STOP) with timestamps
HISTORY_FILE = "polar_history_log.csv"

# ─────────────────────────────────────────────
# UDP Network settings
# ─────────────────────────────────────────────
UDP_IP = "127.0.0.1"
UDP_PORT = 5005

# global variables initialized for the main process
choice_connection: Optional[str] = None
in_streaming: bool = False  

# ─────────────────────────────────────────────
# Types & Configuration Bluetooth
# ─────────────────────────────────────────────
DeviceType = Literal["polar_h10", "polar_oh1"]

@dataclass
class Device:
    mac: str
    name: str
    type: DeviceType
    rssi: int = 0

POLAR_MODELS = {
    "Polar H10":  "polar_h10",
    "Polar OH1":  "polar_oh1",
    "H10":        "polar_h10",
    "OH1":        "polar_oh1",
}

async def _ble_scan(timeout: float = 8.0) -> list[Device]:
    found: list[Device] = []
    print("\n[Polar] Scan Bluetooth en cours...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for ble_dev, adv_data in devices.values():
        name = ble_dev.name or ""
        for model_key, dev_type in POLAR_MODELS.items():
            if model_key.lower() in name.lower():
                dev = Device(
                    mac=ble_dev.address.upper(),
                    name=name,
                    type=dev_type,
                    rssi=adv_data.rssi if adv_data.rssi else 0,
                )
                found.append(dev)
                break
    return found

def scan_polar() -> list[Device]:
    return asyncio.run(_ble_scan())

# ─────────────────────────────────────────────
# 3. Selection and management of markers
# ─────────────────────────────────────────────
DEVICE_LABELS = {
    "polar_h10": "Polar H10",
    "polar_oh1": "Polar OH1",
}

EVENT_LABELS: dict[str, str] = {
    's': 'Stroop',
    'r': 'Reaction',
    'n': 'N-Back',
    't': 'Rest',
    'q': 'Test1',
    'w': 'Test2',
    'e': 'Test3'
    # ADD EVENT_LABEL ('z': '...')
}

class MarkerSender:
    def __init__(self) -> None:
        # Ajouter un UUID unique pour éviter les collisions si le script est relancé
        unique_id = str(uuid.uuid4())[:8]
        
        # Configuration LSL avec source_id unique
        info = StreamInfo('TaskMarkers', 'Markers', 2, 0, 'string', f'events_{unique_id}')
        info.desc().append_child_value("channel_0", "event_type")       
        info.desc().append_child_value("channel_1", "label")   
        self.outlet = StreamOutlet(info)
        
        self.current_category: Optional[str] = 'Rest' 
        self._write_files('Rest', 0)

    def _write_files(self, label: str, numeric_value: int) -> None:
        """ Write distinctly the data in different files for the subprocesses to read """
        with open(CATEGORY_FILE, 'w') as f:
            f.write(label)
        with open(CONDITION_FILE, 'w') as f:
            f.write(str(numeric_value))

    def _log_history_event(self, action: str, label: str) -> None:
        pass

    def send(self, key: str) -> None:
        label = EVENT_LABELS.get(key)
        if label is None:
            return
            
        # avoid data in double
        if self.current_category == label:
            return

        # --- Transition logic START / STOP ---
        
        # 1. STOP : If the current category is not None and not "Rest"
        # we send a STOP marker for the previous category and log it. 
        # This ensures that we properly close out any ongoing task before starting a new one.
        if self.current_category and self.current_category != 'Rest':
            self.outlet.push_sample(['Stop', self.current_category])
            self._log_history_event("Stop", self.current_category)

        # Update status
        self.current_category = label
        numeric_value = 0 if label == 'Rest' else 1
        
        # Update temporary files for subprocesses
        self._write_files(label, numeric_value)
        
        # 2. START : If new category is a task --> we send a START marker and log it.
        if label != 'Rest':
            self.outlet.push_sample(['Start', label])
            self._log_history_event("Start", label)
        #else:
            # If REST "INFO" marker is sent to indicate the transition to a resting state.
            #self.outlet.push_sample(['INFO', 'Rest'])
        
        now = datetime.now().strftime('%H:%M:%S')
        print(f"\n[{now}] ▶ Category active : {label} (Value : {numeric_value})")

    def cleanup(self) -> None:
        """ Clean temporary files and shut down the last active task properly"""
        if self.current_category and self.current_category != 'Rest':
            self.outlet.push_sample(['Stop', self.current_category])
            self._log_history_event("Stop", self.current_category)
            

class TimestampPrinter:
    def __init__(self, stop_event: Event, marker_sender: "MarkerSender") -> None:
        self.stop_event = stop_event
        self.marker_sender = marker_sender
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        keys_hint = "  ".join(f"[{k}] {v}" for k, v in EVENT_LABELS.items())
        while not self.stop_event.is_set():
            now = datetime.now().strftime('%H:%M:%S')
            cat = self.marker_sender.current_category or "None"
            print(f"[{now}] Category : {cat}  |  {keys_hint}", end='\r')
            self.stop_event.wait(1.0)

# ─────────────────────────────────────────────
# Listening to UDP for key presses and device selection
# ─────────────────────────────────────────────
def server_listen_udp(stop_event: Event, on_press_callback):
    global choice_connection, in_streaming 
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 5005))
    sock.settimeout(0.5) 

    while not stop_event.is_set():
        try:
            data, _ = sock.recvfrom(1024)
            if not data:
                continue
                
            key = data.decode('utf-8', errors='ignored').strip().lower()
            if not key:
                continue

            if key in ('y', 'n') and not in_streaming:
                choice_connection = key
                print(f"[UDP] Connection choice saved : {key.upper()}")
            else:
                on_press_callback(key)
                
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[UDP] Server Error : {e}")
            break
            
    sock.close()

def select_devices(devices: list[Device]) -> list[Device]:
    global choice_connection
    selected: list[Device] = []
    if not devices:
        print("\nNo devices detected.")
        return selected

    print("SELECT DEVICES")

    for dev in devices:
        label = DEVICE_LABELS.get(dev.type, dev.type)
        print(f"  [{label}] {dev.name}  ({dev.mac}) — In waiting of validation [Y/N] from the interface...")
        
        while True:
            if choice_connection is not None:
                answer = choice_connection.upper()
                choice_connection = None
                
                if answer in ("Y"):
                    selected.append(dev)
                    print(f"    -> Selected ")
                    break
                elif answer == "N":
                    print(f"    -> Ignored")
                    break
            time.sleep(0.1)
            
    return selected

# ─────────────────────────────────────────────
# 4. Start and wait the streaming
# ─────────────────────────────────────────────
SCRIPT_MAP: dict[DeviceType, str] = {
    "polar_h10": "PolarH10_LSL.py",
    "polar_oh1": "PolarOH1_LSL.py",
}

def launch_streams(devices: list[Device]) -> list[subprocess.Popen]:
    processes: list[subprocess.Popen] = []
    print("START STREAMING")

    for dev in devices:
        script = SCRIPT_MAP.get(dev.type)
        if not script:
            continue
        cmd = [sys.executable, script, "--mac", dev.mac, "--category-file", CATEGORY_FILE]
        print(f"  {DEVICE_LABELS[dev.type]}  {dev.mac}  :  {' '.join(cmd)}")
        proc = subprocess.Popen(cmd)
        processes.append(proc)
    return processes

def wait_for_exit(processes: list[subprocess.Popen], marker_sender: Optional[MarkerSender] = None, stop_event: Optional[Event] = None) -> None:
    if not processes:
        return

    TimestampPrinter(stop_event, marker_sender)
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if marker_sender:
            marker_sender.cleanup()
        print("\n\nStop the streamings...")
        for proc in processes:
            proc.terminate()
        print("The process has been stopped.")

# ─────────────────────────────────────────────
# 6. MAIN
# ─────────────────────────────────────────────
def main():
    global in_streaming 
    
    print("=" * 50)
    print("  SCANNER MULTI-DEVICES POLAR (H10 / OH1) + LSL + UDP")
    print("=" * 50)

    stop_event = Event()
    in_streaming = False  

    def on_press(key: str) -> None:
        if key == "stop":
            stop_event.set()
            return
        if key not in EVENT_LABELS:
            return
        if marker_sender:
            marker_sender.send(key)

    # 1. Starting UDP server
    listener = Thread(target=server_listen_udp, args=(stop_event, on_press), daemon=True)
    listener.start()

    # 2. Scan Bluetooth
    all_devices = scan_polar()
    
    # 3. UDP validation of devices
    selected = select_devices(all_devices)

    if not selected:
        stop_event.set()
        return

    # 4. Activation of streaming mode (free the 'n' key for N-Back)
    in_streaming = True  
    print("[INFO] Streaming LSL mode activated")

    marker_sender = MarkerSender()
    processes = launch_streams(selected)
    
    wait_for_exit(processes, marker_sender, stop_event)

if __name__ == "__main__":
    main()