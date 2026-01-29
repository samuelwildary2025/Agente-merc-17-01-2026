import sys
import os
import requests
import json
from pathlib import Path

# Adiciona o diretório pai ao sys.path para importar config
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import settings

def test_connection():
    base_url = (settings.whatsapp_api_base_url or "").rstrip("/")
    token = settings.whatsapp_instance_token
    agent_number = settings.whatsapp_agent_number

    print(f"Testing Uazapi Connection...")
    print(f"URL: {base_url}")
    print(f"Token: {token[:5]}...{token[-5:] if token else 'None'}")
    print(f"Agent Number: {agent_number}")

    if not base_url or not token:
        print("❌ Missing configuration!")
        return

    headers = {
        "Content-Type": "application/json",
        "apikey": token,
        "token": token,
        "Authorization": f"Bearer {token}",
        "X-Instance-Token": token
    }

    # 1. Test Instance Status (Common endpoint, might vary)
    print("\n[1] Checking Instance Status...")
    try:
        # Tenta endpoints comuns de status da Evolution/Uazapi
        status_url = f"{base_url}/instance/fetchInstances" 
        resp = requests.get(status_url, headers=headers, timeout=10)
        
        if resp.status_code == 404:
            # Tenta outro endpoint se esse falhar
            status_url = f"{base_url}/instance/connectionState"
            resp = requests.get(status_url, headers=headers, timeout=10)

        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.text[:300]}")
    except Exception as e:
        print(f"❌ Error checking status: {e}")

    # 2. Test Sending Message
    if not agent_number:
        print("\n⚠️ WA_AGENT_NUMBER not set. Skipping send message test.")
        return

    print(f"\n[2] Sending Test Message to {agent_number}...")
    send_url = f"{base_url}/message/text"
    payload = {
        "number": str(agent_number), # Algumas APIs usam 'number', outras 'to'
        "to": f"{agent_number}@s.whatsapp.net",
        "text": "🤖 Teste de conexão Uazapi - Agente Merc",
        "options": {
            "delay": 1200,
            "presence": "composing"
        }
    }
    
    try:
        resp = requests.post(send_url, headers=headers, json=payload, timeout=15)
        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.text[:300]}")
        
        if resp.status_code == 201 or resp.status_code == 200:
             print("✅ Message sent successfully!")
        else:
             print("❌ Failed to send message.")
             
             # Tenta payload alternativo se falhar
             print("\n[2.1] Retrying with alternative payload...")
             alt_payload = {
                 "id": str(agent_number),
                 "message": "Teste alternativo"
             }
             # Uazapi pode ter endpoint diferente
             
    except Exception as e:
        print(f"❌ Error sending message: {e}")

if __name__ == "__main__":
    test_connection()
