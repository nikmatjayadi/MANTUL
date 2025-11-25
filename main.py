#!/usr/bin/env python3
"""
main_menu.py
Professional, clean main menu interface (no ANSI codes)
"""

import sys
import os
import time
from aci import main_aci
from legacy import main_legacy


# ============================================================
# Utility Functions
# ============================================================

def clear_screen():
    """Clear terminal screen for clean display"""
    os.system("cls" if os.name == "nt" else "clear")


def pause(message="\nPress ENTER to continue..."):
    """Pause execution for user input"""
    input(message)


def slow_print(text, delay=0.02):
    """Smooth typewriter-style output"""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def print_header():
    """Display main header"""
    clear_screen()
    print("=" * 50)
    print("🚀  SYSTEM COMMAND CENTER".center(50))
    print("=" * 50)
    print()


def print_menu():
    """Display the main menu"""
    print("MAIN MENU")
    print("-" * 50)
    print("1. ACI Systems")
    print("2. Legacy Systems")
    print("q. Exit Program")
    print("-" * 50)


# ============================================================
# Main Control
# ============================================================

def main():
    while True:
        print_header()
        print_menu()

        choice = input("\nEnter your choice: ").strip().lower()

        if choice == "1":
            slow_print("\nLaunching ACI Systems...")
            main_aci.main()

        elif choice == "2":
            slow_print("\nAccessing Legacy Systems...")
            main_legacy.main()

        elif choice == "q":
            slow_print("\nExit system...")
            time.sleep(0.3)
            print("✅ System exit complete. Goodbye! 👋")
            break

        else:
            print("\n❌ Invalid selection. Please try again.")
            pause()


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Exiting gracefully...")
        sys.exit(0)
