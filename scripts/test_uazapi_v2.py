import requests
import json
import sys

# Config
BASE_URL = "https://aimerc.uazapi.com"
TOKEN = "72ff78a1-d028-4753-b1ad-f05dd0c9f049"
AGENT_NUMBER = "5585991836205"
INSTANCE = "teste"

# Headers
HEADERS = {
    "Content-Type": "application/json",
    "apikey": TOKEN,
    "token": TOKEN
}

def test_endpoint(url, payload, description):
    print(f"\n👉 Testing {description}...")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload)}")
    
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:300]}")
        return resp.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def run_tests():
    # Payload format based on user docs
    payload = {
        "number": AGENT_NUMBER,
        "text": "🤖 Teste Uazapi V2 (/send/text)",
        "delay": 1200
    }
    
    # 1. Test Root Endpoint: /send/text
    test_endpoint(f"{BASE_URL}/send/text", payload, "Root /send/text")

    # 2. Test Instance Endpoint: /teste/send/text
    test_endpoint(f"{BASE_URL}/{INSTANCE}/send/text", payload, "Instance /teste/send/text")
    
    # 3. Test Instance V1: /instance/teste/send/text
    test_endpoint(f"{BASE_URL}/instance/{INSTANCE}/send/text", payload, "Instance /instance/teste/send/text")

if __name__ == "__main__":
    run_tests()
