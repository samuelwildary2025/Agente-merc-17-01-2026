import requests
import json

url = "https://app.aimerc.com.br/api/pedidos/"
token = "12345678"

payload = {
    "nome_cliente": "Cliente Teste Receipt",
    "telefone": "5585987520060",
    "endereco": "Rua Exemplo, 123",
    "forma": "PIX",
    "observacao": "Pedido de teste com comprovante enviado via script.",
    "comprovante_pix": "https://placehold.co/600x400.png?text=Comprovante+Pix+Teste",
    "itens": [
        {
            "nome_produto": "Produto Teste Comprovante",
            "quantidade": 1,
            "preco_unitario": 10.0
        }
    ]
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

print(f"📡 Enviando requisição para: {url}")
print(f"🔑 Token: {token}")
print(f"📦 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")

try:
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"\n📥 Status Code: {response.status_code}")
    print(f"📄 Response Body: {response.text}")
    
    if response.status_code in [200, 201]:
        print("\n✅ SUCESSO! Pedido criado com comprovante.")
    else:
        print("\n❌ FALHA. Verifique a resposta acima.")

except Exception as e:
    print(f"\n❌ ERRO NA REQUISIÇÃO: {e}")
