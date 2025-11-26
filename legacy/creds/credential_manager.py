import os
import json
from cryptography.fernet import Fernet

KEY_FILE = os.path.join(os.path.dirname(__file__), "key.key")
CRED_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")

def generate_key():
    """Generate a new encryption key if it doesn't exist."""
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(key)

def load_key():
    """Load the encryption key."""
    with open(KEY_FILE, "rb") as key_file:
        return key_file.read()

def save_credentials(username, password):
    """Encrypt and save credentials."""
    generate_key()
    key = load_key()
    fernet = Fernet(key)

    data = {
        "username": fernet.encrypt(username.encode()).decode(),
        "password": fernet.encrypt(password.encode()).decode()
    }

    with open(CRED_FILE, "w") as cred_file:
        json.dump(data, cred_file)
    print("✅ Credentials saved securely.")

def load_credentials():
    """Decrypt and load saved credentials."""
    if not os.path.exists(CRED_FILE):
        print("⚠️ No saved credentials found.")
        return None, None

    key = load_key()
    fernet = Fernet(key)

    with open(CRED_FILE, "r") as cred_file:
        data = json.load(cred_file)

    username = fernet.decrypt(data["username"].encode()).decode()
    password = fernet.decrypt(data["password"].encode()).decode()
    return username, password
