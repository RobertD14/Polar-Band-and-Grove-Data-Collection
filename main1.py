"""
main.py — Scan, sélection et lancement des streamings Polar H10 / Polar OH1
Usage : python main.py

Prérequis :
    pip install bleak

Structure attendue du projet :
    main.py
    Polar_LSL_with_ECG.py     (doit accepter --mac <adresse>)
    PolarOH1_LSL.py           (doit accepter --mac <adresse>)
"""

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from typing import Literal, Optional

from pylsl import StreamInfo, StreamOutlet
from sshkeyboard import listen_keyboard, stop_listening
from bleak import BleakScanner


# ─────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────

DeviceType = Literal["polar_h10", "polar_oh1"]

@dataclass
class Device:
    mac: str
    name: str
    type: DeviceType
    rssi: int = 0


# (EmotiBit support removed) — only Polar BLE scanning remains


# ─────────────────────────────────────────────
# 2. Scan Polar (Bluetooth Low Energy)
# ─────────────────────────────────────────────

POLAR_MODELS = {
    "Polar H10":  "polar_h10",
    "Polar OH1":  "polar_oh1",
    "H10":        "polar_h10",
    "OH1":        "polar_oh1",
}

async def _ble_scan(timeout: float = 8.0) -> list[Device]:
    """Scan BLE et retourne les appareils Polar H10/OH1 trouvés."""
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
                print(f"  ✓ Trouvé : {name}  (MAC {ble_dev.address})  RSSI {adv_data.rssi} dBm")
                break

    return found


def scan_polar() -> list[Device]:
    return asyncio.run(_ble_scan())


# ─────────────────────────────────────────────
# 3. Sélection interactive
# ─────────────────────────────────────────────

DEVICE_LABELS = {
    "polar_h10": "Polar H10",
    "polar_oh1": "Polar OH1",
}

EVENT_LABELS: dict[str, str] = {
    's': 'stroop test',
    'r': 'reaction test',
    'n': 'N-back',
    't': 'rest',
}

class MarkerSender:
    """Send associated task markers over LSL."""

    def __init__(self) -> None:
        info = StreamInfo('TaskMarkers', 'Markers', 1, 0, 'string', 'task_markers')
        self.outlet = StreamOutlet(info)

    def send(self, key: str) -> None:
        label = EVENT_LABELS.get(key)
        if label is None:
            return
        self.outlet.push_sample([label])
        print(f"Marker envoyé : {label}")


class TimestampPrinter:
    """Print a terminal timestamp once par seconde."""

    def __init__(self, stop_event: Event) -> None:
        self.stop_event = stop_event
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            now = datetime.now().strftime('%H:%M:%S')
            print(f'[{now}] Appuyez sur s,r,n,t pour envoyer un marqueur ; Entrée pour quitter.', end='\r')
            self.stop_event.wait(1.0)


def select_devices(devices: list[Device]) -> list[Device]:
    """
    Parcourt la liste des appareils détectés et demande Y/N pour chacun.
    Retourne uniquement les appareils sélectionnés.
    """
    selected: list[Device] = []

    if not devices:
        print("\nAucun appareil détecté.")
        return selected

    print("\n" + "─" * 50)
    print("SÉLECTION DES APPAREILS")
    print("─" * 50)

    for dev in devices:
        label = DEVICE_LABELS.get(dev.type, dev.type)
        prompt = f"  [{label}] {dev.name}  ({dev.mac}) — Connecter ? [Y/N] : "

        while True:
            answer = input(prompt).strip().upper()
            if answer in ("Y", "O"):   # accepte aussi "O" pour Oui
                selected.append(dev)
                print(f"    → Retenu ✓")
                break
            elif answer == "N":
                print(f"    → Ignoré")
                break
            else:
                print("    Répondez Y ou N.")

    return selected


# ─────────────────────────────────────────────
# 4. Lancement des streamings
# ─────────────────────────────────────────────

SCRIPT_MAP: dict[DeviceType, str] = {
    "polar_h10": "Polar_LSL_with_ECG.py",
    "polar_oh1": "PolarOH1_LSL.py",
}

def launch_streams(devices: list[Device]) -> list[subprocess.Popen]:
    """
    Lance un subprocess par appareil sélectionné.
    Chaque script reçoit --mac <adresse_MAC> en argument.
    Retourne la liste des processus lancés.
    """
    processes: list[subprocess.Popen] = []

    print("\n" + "─" * 50)
    print("LANCEMENT DU STREAMING")
    print("─" * 50)

    for dev in devices:
        script = SCRIPT_MAP.get(dev.type)
        if not script:
            print(f"  [!] Pas de script connu pour le type '{dev.type}', ignoré.")
            continue

        cmd = [sys.executable, script, "--mac", dev.mac]
        print(f"  → {DEVICE_LABELS[dev.type]}  {dev.mac}  :  {' '.join(cmd)}")

        proc = subprocess.Popen(cmd)
        processes.append(proc)

    return processes


# ─────────────────────────────────────────────
# 5. Attente et arrêt propre
# ─────────────────────────────────────────────

def wait_for_exit(processes: list[subprocess.Popen], marker_sender: Optional[MarkerSender] = None) -> None:
    if not processes:
        print("\nAucun appareil sélectionné. Fin du programme.")
        return

    stop_event = Event()
    timestamp_printer = TimestampPrinter(stop_event)

    def on_press(key: str) -> None:
        if key in EVENT_LABELS:
            if marker_sender:
                marker_sender.send(key)
            else:
                print(f"Clé {key} pressée, mais aucun outlet LSL disponible.")

    listener = Thread(target=listen_keyboard, kwargs={'on_press': on_press}, daemon=True)
    listener.start()

    print(f"\n{len(processes)} streaming(s) actif(s). Appuyez sur Entrée pour tout arrêter.")
    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if listener.is_alive():
            stop_listening()
        print("\nArrêt des streamings...")
        for proc in processes:
            proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("Tous les processus sont arrêtés.")


# ─────────────────────────────────────────────
# 6. Point d'entrée
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  SCANNER MULTI-APPAREILS BIOMÉTRIQUES")
    print("=" * 50)

    # --- Scan ---
    all_devices: list[Device] = []
    all_devices += scan_polar()

    total = len(all_devices)
    print(f"\n{total} appareil(s) détecté(s) au total.")

    # --- Sélection ---
    selected = select_devices(all_devices)
    print(f"\n{len(selected)} appareil(s) retenu(s).")

    # --- Streaming ---
    processes = launch_streams(selected)
    marker_sender = MarkerSender()

    # --- Attente ---
    wait_for_exit(processes, marker_sender)


if __name__ == "__main__":
    main()
