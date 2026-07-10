import argparse
import asyncio
from bleak import BleakClient
from pylsl import StreamInfo, StreamOutlet
import os
import tempfile

HR_UUID     = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA    = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
START_PPG   = bytearray([0x02, 0x01, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x16, 0x00])

_condition_file = os.path.join(tempfile.gettempdir(), "polar_condition_bit.txt")
# Outlets globaux (initialisés dans main)
hr_outlet  = None
ppg_outlet = None
_category_file = ""


def read_category() -> str:
    """Read the active category from the shared file."""
    try:
        with open(_category_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return "none"


def read_state() -> tuple[str, str]:
    """Read the 2 files from main3.py."""
    try:
        with open(_category_file, 'r') as f:
            cat = f.read().strip()
    except Exception:
        cat = "Rest"
        
    try:
        with open(_condition_file, 'r') as f:
            cond = f.read().strip()
    except Exception:
        cond = "0"
        
    return cat, cond


def create_outlets(mac_address: str):
    mac_key = mac_address.upper().replace(':', '')

    # HR : 3 canaux — valeur + catégorie + condition
    hr_info = StreamInfo(f"PolarOH1_{mac_key}_HR", "HR", 3, 1, "string", f"oh1_hr_{mac_key}")
    hr_info.desc().append_child_value("channel_0", "hr_value")
    hr_info.desc().append_child_value("channel_1", "category")
    hr_info.desc().append_child_value("channel_2", "condition")

    # PPG : 5 canaux — ch0, ch1, ch2 + category + condition 
    ppg_info = StreamInfo(f"PolarOH1_{mac_key}_PPG", "PPG", 5, 130, "string", f"oh1_ppg_{mac_key}")
    ppg_info.desc().append_child_value("channel_0", "ppg_ch0")
    ppg_info.desc().append_child_value("channel_1", "ppg_ch1")
    ppg_info.desc().append_child_value("channel_2", "ppg_ch2")
    ppg_info.desc().append_child_value("channel_3", "category")
    ppg_info.desc().append_child_value("channel_4", "condition")

    return StreamOutlet(hr_info), StreamOutlet(ppg_info)


def handle_hr(sender, data):
    flags = data[0]
    hr = int.from_bytes(data[1:3], 'little') if flags & 0x01 else data[1]
    category, condition = read_state()
    # Envoi strict de 3 éléments pour correspondre aux 3 canaux configurés
    hr_outlet.push_sample([str(hr), category, condition])


def handle_pmd_response(sender, data):
    print(f"PMD Response: {data.hex()}")


def handle_ppg(sender, data):
    if data[0] != 0x01:
        print(f"PPG : Unexpected {data[0]:#x}, ignored")
        return
        
    category, condition = read_state()
    i = 9
    while i + 9 <= len(data):
        ch0 = int.from_bytes(data[i:i+3],   'little', signed=True)
        ch1 = int.from_bytes(data[i+3:i+6], 'little', signed=True)
        ch2 = int.from_bytes(data[i+6:i+9], 'little', signed=True)
        
        # Envoi strict de 5 éléments pour correspondre aux 5 canaux configurés
        ppg_outlet.push_sample([str(ch0), str(ch1), str(ch2), category, condition])
        i += 9

async def main(device_address: str, category_file: str):
    global hr_outlet, ppg_outlet, _category_file
    _category_file = category_file

    print(f"Connecting to Polar OH1 at {device_address}...")
    hr_outlet, ppg_outlet = create_outlets(device_address)

    async with BleakClient(device_address) as client:
        print("Connected.")

        caps = await client.read_gatt_char(PMD_CONTROL)
        print(f"PMD capacity : {caps.hex()}")

        await client.start_notify(PMD_CONTROL, handle_pmd_response)
        await client.start_notify(PMD_DATA, handle_ppg)   
        await client.start_notify(PMD_CONTROL, handle_hr)

        await asyncio.sleep(0.5)

        print("Starting PPG stream...")
        await client.write_gatt_char(PMD_CONTROL, START_PPG, response=True)

        print("Streams LSL active (HR + PPG).")
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polar OH1 LSL streamer")
    parser.add_argument("--mac", "--address", dest="address", required=True)
    parser.add_argument("--category-file", dest="category_file", required=True,
                        help="Chemin vers le fichier de catégorie partagé")
    args = parser.parse_args()
    asyncio.run(main(args.address, args.category_file))
