import csv
import logging
from napalm import get_network_driver
from legacy.creds.credential_manager import load_credentials, save_credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

INVENTORY_FILE = "inventory.csv"


def detect_os_type(ip, username=None, password=None):
    """Try to detect OS type and hostname using NAPALM drivers."""
    possible_drivers = ["ios", "junos", "nxos", "eos", "iosxr"]

    for driver_name in possible_drivers:
        try:
            driver = get_network_driver(driver_name)
            device = driver(
                hostname=ip,
                username=username,
                password=password,
                optional_args={"timeout": 5}
            )
            device.open()
            facts = device.get_facts()
            device.close()

            hostname = facts.get("hostname", "unknown")
            os_version = facts.get("os_version", "unknown")

            logging.info(
                f"Detected {os_version} on {ip} ({driver_name}) - Hostname: {hostname}"
            )

            return driver_name, hostname

        except Exception:
            continue

    return None, None


def add_to_inventory(ip, hostname, os_type):
    """Add or update a device entry in inventory.csv."""
    rows = []
    found = False

    try:
        with open(INVENTORY_FILE, mode="r") as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if not row:
                    continue

                row_ip = row[0]

                if row_ip == ip:
                    rows.append([ip, hostname, os_type])
                    found = True
                else:
                    # Normalize existing rows
                    if len(row) == 1:
                        rows.append([row[0], "", ""])
                    elif len(row) == 2:
                        rows.append([row[0], "", row[1]])
                    else:
                        rows.append(row)

    except FileNotFoundError:
        pass

    if not found:
        rows.append([ip, hostname, os_type])
        print(f"✅ Added {ip} ({hostname}, {os_type}) to inventory.")
    else:
        print(f"🔄 Updated {ip} ({hostname}, {os_type}) in inventory.")

    with open(INVENTORY_FILE, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(rows)


def create_inventory(username=None, password=None):
    print("\n=== Create or Update Device Inventory ===")

    # Load credentials
    username, password = load_credentials()

    if not username or not password:
        print("⚠️ No saved credentials found.")
        username = input("Enter username: ").strip()
        password = input("Enter password: ").strip()
        if input("Save credentials? (y/n): ").lower() == "y":
            save_credentials(username, password)

    # ▶▶ NEW: auto-update old/incomplete entries before adding new ones
    auto_fix_inventory(username, password)

    while True:
        ip = input("Enter device IP (or 'done' to finish): ").strip()
        if ip.lower() == "done":
            break

        print(f"🔍 Detecting OS type for {ip}...")
        os_type, hostname = detect_os_type(ip, username, password)

        if os_type:
            add_to_inventory(ip, hostname, os_type)
        else:
            print(f"❌ Could not detect OS type for {ip}")

    print("\n📁 Inventory creation complete. Saved to inventory.csv.")


def auto_fix_inventory(username, password):
    """Scan existing inventory and update incomplete entries."""
    print("\n🔄 Checking inventory for incomplete entries...")

    rows = []
    updated = False

    try:
        with open(INVENTORY_FILE, mode="r") as csvfile:
            reader = csv.reader(csvfile)

            for row in reader:
                if not row:
                    continue

                # CASE 1: Only IP
                if len(row) == 1:
                    ip = row[0]
                    print(f"🔍 Updating {ip} (missing hostname + os)")
                    os_type, hostname = detect_os_type(ip, username, password)
                    rows.append([ip, hostname or "", os_type or ""])
                    updated = True

                # CASE 2: IP + OS
                elif len(row) == 2:
                    ip, os_type = row
                    print(f"🔍 Updating {ip} (missing hostname)")
                    os_type_new, hostname = detect_os_type(ip, username, password)
                    rows.append([ip, hostname or "", os_type_new or os_type])
                    updated = True

                # CASE 3: Full row → keep
                else:
                    rows.append(row)

    except FileNotFoundError:
        print("📁 No inventory to fix.")
        return

    # Rewrite updated inventory
    with open(INVENTORY_FILE, mode="w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(rows)

    if updated:
        print("✅ Inventory has been automatically updated.\n")
    else:
        print("✔ Inventory is already complete.\n")


def show_inventory():
    """Display all devices in the inventory."""
    print("\n=== Current Device Inventory ===")
    try:
        with open(INVENTORY_FILE, "r") as csvfile:
            reader = csv.reader(csvfile)
            print(f"{'IP Address':<20} {'Hostname':<20} {'OS Type'}")
            print("-" * 60)
            for row in reader:
                if len(row) >= 3:
                    print(f"{row[0]:<20} {row[1]:<20} {row[2]}")
                else:
                    print(f"{row}")
    except FileNotFoundError:
        print("⚠️ No inventory file found. Please create one first.")
