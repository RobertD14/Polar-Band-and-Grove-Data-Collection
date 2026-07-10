import argparse
import asyncio
import struct
import os
from bleak import BleakClient
from pylsl import StreamInfo, StreamOutlet
import tempfile

# Polar PMD UUIDs
PMD_COMMAND_CHAR = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA_CHAR    = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
UUID_HR_MEASUREMENT = '00002a37-0000-1000-8000-00805f9b34fb'
CONDITION_FILE = os.path.join(tempfile.gettempdir(), "polar_condition_bit.txt")
ECG_WRITE_CMD = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])


def read_category(category_file: str) -> str:
    """Lit la catégorie active depuis le fichier partagé."""
    try:
        with open(category_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return "none"


def parse_ecg(data: bytearray) -> list[int]:
    if len(data) < 10 or data[0] != 0x00:
        return []
    values = []
    for i in range(10, len(data) - 2, 3):
        value = int.from_bytes(data[i:i+3], byteorder='little', signed=True)
        values.append(value)
    return values


def parse_hr_data(data):
    if len(data) < 2:
        return None
    flags = data[0]
    return struct.unpack('<H', data[1:3])[0] if flags & 0x01 else data[1]

def read_state(category_file: str) -> tuple[str, str]:
    """Lit les deux fichiers d'état séparés."""
    try:
        with open(category_file, 'r') as f:
            cat = f.read().strip()
    except Exception:
        cat = "None"
        
    try:
        with open(CONDITION_FILE, 'r') as f:
            cond = f.read().strip()
    except Exception:
        cond = "0"
        
    return cat, cond


async def main(device_address: str, category_file: str):
    device_address = device_address.upper()
    mac_key = device_address.replace(':', '')

    print(f"Connecting directly to Polar H10 at {device_address} without scanning...")

    # Naming the streams with the MAC address to avoid conflicts
    ecg_info = StreamInfo(f'PolarH10_{mac_key}_ECG', 'ECG', 3, 130, 'string', f'polar_ecg_{mac_key}')
    ecg_info.desc().append_child_value("channel_0", "ecg_value")
    ecg_info.desc().append_child_value("channel_1", "category")
    ecg_info.desc().append_child_value("channel_2", "condition")

    hr_info = StreamInfo(f'PolarH10_{mac_key}_HR', 'HR', 3, 1, 'string', f'polar_hr_{mac_key}')
    hr_info.desc().append_child_value("channel_0", "hr_value")
    hr_info.desc().append_child_value("channel_1", "category")
    hr_info.desc().append_child_value("channel_2", "condition")

    ecg_outlet = StreamOutlet(ecg_info)
    hr_outlet  = StreamOutlet(hr_info)

    # Connexion forcée en utilisant directement l'adresse MAC fournie
    async with BleakClient(device_address) as client:
        print("Connected!")

        def on_pmd_data(sender, data):
            ecg_values = parse_ecg(data)
            category, condition = read_state(category_file)  # Lecture des 2 éléments séparés
            for ecg_val in ecg_values:
                # SÉPARATION DES COLONNES ICI : chaque virgule crée une colonne LSL / LabRecorder
                ecg_outlet.push_sample([str(ecg_val), category, condition])

        def on_hr_data(sender, data):
            hr = parse_hr_data(data)
            if hr is not None:
                category, condition = read_state(category_file)  # Lecture des 2 éléments séparés
                # SÉPARATION DES COLONNES ICI
                hr_outlet.push_sample([str(hr), category, condition])
                
        started_hr = False
        started_ecg = False

        try:
            print("Enabling HR stream...")
            await client.start_notify(UUID_HR_MEASUREMENT, on_hr_data)
            started_hr = True

            print("Enabling ECG stream...")
            await client.start_notify(PMD_DATA_CHAR, on_pmd_data)
            await client.start_notify(PMD_COMMAND_CHAR, lambda s, d: print(f"PMD response: {d.hex()}"))
            started_ecg = True

            await client.write_gatt_char(PMD_COMMAND_CHAR, ECG_WRITE_CMD)
            print("ECG stream started.")
            print("Streaming ECG and HR data via LSL...")

            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("Interrupted.")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if started_hr:
                try: await client.stop_notify(UUID_HR_MEASUREMENT)
                except Exception: pass
            if started_ecg:
                try: await client.stop_notify(PMD_DATA_CHAR)
                except Exception: pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polar H10 ECG + HR LSL streamer")
    parser.add_argument("--mac", "--address", dest="address", required=True)
    parser.add_argument("--category-file", dest="category_file", required=True,
                        help="Chemin vers le fichier de catégorie partagé")
    args = parser.parse_args()
    asyncio.run(main(args.address, args.category_file))