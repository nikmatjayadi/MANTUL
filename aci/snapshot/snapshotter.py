# ✅ Updated snapshotter.py to include timestamped filenames and history viewer with interactive snapshot comparison

import json
import os
import datetime
from aci.api.aci_client import (
    get_fabric_health,
    get_faults,
    get_interface_status,
    get_endpoints,
    get_urib_routes,
    get_interface_errors,
    get_crc_errors,
    get_drop_errors,
    get_output_errors,

)

def take_snapshot(cookies, apic_ip, base_filename):
    # Collect all data
    data = {
        "fabric_health": get_fabric_health(cookies, apic_ip),
        "faults": get_faults(cookies, apic_ip),
        "interfaces": get_interface_status(cookies, apic_ip),
        "interface_errors": get_interface_errors(cookies, apic_ip),
        "drop_errors": get_drop_errors(cookies, apic_ip),
        "output_errors": get_output_errors(cookies, apic_ip),
        "crc_errors": get_crc_errors(cookies, apic_ip),
        "endpoints": get_endpoints(cookies, apic_ip),
        "urib_routes": get_urib_routes(cookies, apic_ip),
    }

    # Create directory structure
    snapshot_dir = os.path.join("aci", "snapshot", "output")

    os.makedirs("output", exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M")
    filename = f"{base_filename}_{apic_ip}_{timestamp}.json"
    filepath = os.path.join(snapshot_dir, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Snapshot saved to {filepath}")
    return filepath

def list_snapshots():
    folder = os.path.join("aci", "snapshot", "output")
    if not os.path.exists(folder):
        print("📂 No snapshots taken yet.")
        return []
    files = [f for f in os.listdir(folder) if f.endswith(".json")]
    if not files:
        print("📂 No snapshot files found.")
        return []
    files.sort()
    print("\n🕓 Available Snapshots:")
    for i, f in enumerate(files):
        print(f"  [{i+1}] {f}")
    return files

def choose_snapshots():
    files = list_snapshots()
    folder = os.path.join("aci", "snapshot", "output")
    if len(files) < 2:
        print("❌ Need at least 2 snapshots to compare.")
        return None, None
    try:
        first = int(input("🔢 Enter number for FIRST snapshot: ")) - 1
        second = int(input("🔢 Enter number for SECOND snapshot: ")) - 1
        if 0 <= first < len(files) and 0 <= second < len(files):
            return os.path.join(folder, files[first]), os.path.join(folder, files[second])
        else:
            print("❌ Invalid selection.")
            return None, None
    except ValueError:
        print("❌ Please enter valid numbers.")
        return None, None
