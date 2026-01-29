import requests

BASE_URL = "https://aimerc.uazapi.com"
TOKEN = "72ff78a1-d028-4753-b1ad-f05dd0c9f049"
HEADERS = {
    "apikey": TOKEN,
    "Authorization": f"Bearer {TOKEN}",
    "X-Instance-Token": TOKEN,
    "Content-Type": "application/json"
}

PATHS = [
    "/swagger.json",
    "/openapi.json",
    "/v1/swagger.json",
    "/v1/openapi.json",
    "/api/swagger.json",
    "/api-docs/swagger.json",
    "/docs/swagger.json"
]

PREFIXES = ["", "/v1", "/api", "/api/v1"]

print(f"🕵️ Searching for API Spec on {BASE_URL}...")

# 1. Look for Spec
for path in PATHS:
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            print(f"✅ FOUND Spec at {url}")
            print(resp.text[:200])
            break
    except:
        pass

# 2. Try to Send Text with Token only (No instance name in URL)
print("\n🕵️ Probing Send Text (Token Only)...")
payload = {"number": "5585991836205", "textMessage": {"text": "Teste"}, "text": "Teste"}

for prefix in PREFIXES:
    for endpoint in ["/message/sendText", "/message/text", "/send-message"]:
        url = f"{BASE_URL}{prefix}{endpoint}"
        try:
            resp = requests.post(url, headers=HEADERS, json=payload, timeout=5)
            if resp.status_code != 404:
                print(f"👉 {url} -> {resp.status_code}")
                # print(resp.text[:100])
        except Exception as e:
            print(f"Error {url}: {e}")
