import os
import requests

BASE = os.getenv("API_BASE", "http://localhost:11000/api")
payload = {
    "username": "admin",
    "password": "secret123",
    "email": "admin@example.com",
}

resp = requests.post(f"{BASE}/auth/register", json=payload, timeout=10)

print(resp.status_code)
print(resp.text)
print(resp.headers)