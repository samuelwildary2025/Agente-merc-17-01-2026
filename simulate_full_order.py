import requests
import json
import datetime

url = "https://app.aimerc.com.br/api/pedidos/"
token = "12345678"

# Gerando um telefone aleatório para não misturar com testes anteriores
timestamp = int(datetime.datetime.now().timestamp())
telefone_teste = f"55859{str(timestamp)[-8:]}"

payload = {
    "nome_cliente": "Cliente Full Teste",
    "telefone": telefone_teste,
    "endereco": "Av. Beira Mar, 2000 - Meireles, Fortaleza-CE",
    "forma": "PIX",
    "observacao": "Pedido COMPLETO: Endereço + Comprovante.",
    "comprovante_pix": "https://placehold.co/600x800.png?text=Comprovante+Pix+Original",
    "itens": [
        {
            "nome_produto": "Picanha 1kg",
            "quantidade": 1,
            "preco_unitario": 89.90
        },
        {
            "nome_produto": "Carvão 5kg",
            "quantidade": 1,
            "preco_unitario": 25.00
        }
    ]
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}"
}

print(f"📡 Enviando Pedido COMPLETO para: {url}")
print(f"👤 Cliente: {payload['nome_cliente']}")
print(f"📍 Endereço: {payload['endereco']}")
print(f"🧾 Comprovante: {payload['comprovante_pix']}")

try:
    response = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"\n📥 Status Code: {response.status_code}")
    print(f"📄 Response Body: {response.text}")
    
    if response.status_code in [200, 201]:
        data = response.json()
        
        # Validação
        saved_addr = data.get("endereco")
        saved_receipt = data.get("comprovante_pix")
        
        errors = []
        if saved_addr != payload["endereco"]:
            errors.append(f"❌ Endereço incorreto: {saved_addr}")
        if saved_receipt != payload["comprovante_pix"]:
            errors.append(f"❌ Comprovante incorreto: {saved_receipt}")
            
        if not errors:
            print("\n🎉 SUCESSO TOTAL! Pedido gravado com Endereço E Comprovante.")
        else:
            print("\n⚠️ ALERTA DE DIVERGÊNCIA:")
            for err in errors:
                print(err)
    else:
        print(f"\n❌ FALHA NA REQUISIÇÃO. Status: {response.status_code}")

except Exception as e:
    print(f"\n❌ ERRO CRÍTICO: {e}")
