import requests
import json
import sys
from pathlib import Path

# Config
BASE_URL = "https://aimerc.uazapi.com"
TOKEN = "72ff78a1-d028-4753-b1ad-f05dd0c9f049"
AGENT_NUMBER = "5585991836205"

# Headers
HEADERS = {
    "Content-Type": "application/json",
    "apikey": TOKEN,
    "token": TOKEN,
    "Authorization": f"Bearer {TOKEN}",
    "X-Instance-Token": TOKEN
}

POSSIBLE_INSTANCES = ["teste", "Aimerc", "aimerc", "instance", "default"]

def probe(method, endpoint, payload=None):
    url = f"{BASE_URL}{endpoint}"
    print(f"👉 Probing {method} {url} ...")
    try:
        if method == "GET":
            resp = requests.get(url, headers=HEADERS, timeout=5)
        else:
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=5)
        
        print(f"   Status: {resp.status_code}")
        if resp.status_code not in [404, 502]:
            print(f"   Response: {resp.text[:200]}")
            return True
    except Exception as e:
        print(f"   Error: {e}")
    return False

def run_probe():
    # 1. Try to find Swagger/Docs
    probe("GET", "/docs")
    probe("GET", "/api-docs")
    
    # 2. Try generic instance fetch (without instance name)
    probe("GET", "/instance/fetchInstances")
    
    # 3. Try with Instance Names
    for instance in POSSIBLE_INSTANCES:
        print(f"\n🔍 Testing Instance Name: '{instance}'")
        
        # Check Status
        probe("GET", f"/instance/connectionState/{instance}")
        
        # Try Send Text patterns
        payload = {"number": AGENT_NUMBER, "options": {"delay": 1200}, "textMessage": {"text": "Teste Probing"}}
        
        # Evolution V1/V2 patterns
        probe("POST", f"/message/sendText/{instance}", payload) # V2
        probe("POST", f"/message/text/{instance}", payload)    # Check
        
        # Try simplified payload for V1 or others
        simple_payload = {"number": AGENT_NUMBER, "text": "Teste Probing"}
        probe("POST", f"/message/sendText/{instance}", simple_payload)

if __name__ == "__main__":
    run_probe()
