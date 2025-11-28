# utils/crypto.py
import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv("ENCRYPTION_KEY")
if not KEY or KEY == "change_this_to_a_random_32_byte_base64":
    # create ephemeral key (not for production). Replace in env for production.
    KEY = Fernet.generate_key().decode()
    # print("Generated key:", KEY)

fernet = Fernet(KEY.encode() if isinstance(KEY,str) else KEY)

def encrypt_bytes(b: bytes) -> bytes:
    return fernet.encrypt(b)

def decrypt_bytes(token: bytes) -> bytes:
    return fernet.decrypt(token)
