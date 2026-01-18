import requests
import json

url = "https://app.aimerc.com.br/api/pedidos/"
token = "12345678"

payload = {
    "nome_cliente": "Cliente Teste Endereco",
    "telefone": "5585987520061",
    "endereco": "Rua Teste de Endereco, 500 - Centro",
    "forma": "DINHEIRO",
    "observacao": "Validando envio de endereco.",
    "itens": [
        {
            "nome_produto": "Produto Teste Endereco",
            "quantidade": 1,
            "preco_unitario": 5.0
        }
    ]
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

print(f"📡 Enviando requisição para: {url}")
print(f"📍 Endereço enviado: {payload['endereco']}")

try:
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"\n📥 Status Code: {response.status_code}")
    
    if response.status_code in [200, 201]:
        data = response.json()
        saved_address = data.get("endereco")
        print(f"✅ Endereço salvo no banco: '{saved_address}'")
        
        if saved_address == payload["endereco"]:
            print("🎉 SUCESSO: Endereço gravado corretamente!")
        else:
            print("⚠️ DIVERGÊNCIA: O que foi salvo é diferente do enviado.")
    else:
        print(f"❌ FALHA. Resposta: {response.text}")

except Exception as e:
    print(f"\n❌ ERRO NA REQUISIÇÃO: {e}")
