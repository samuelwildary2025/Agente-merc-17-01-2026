from unittest.mock import MagicMock
import json

# Define the tools (copy-paste logic for unit test simulation)
def get_cart_items_mock(telefone):
    if telefone == "empty": return []
    return [
        {"produto": "Arroz", "preco": 5.50, "quantidade": 2},
        {"produto": "Tomate", "preco": 4.00, "quantidade": 0.5, "unidades": 3}
    ]

def calcular_total_tool(telefone: str, taxa_entrega: float = 0.0) -> str:
    items = get_cart_items_mock(telefone)
    if not items:
        return "❌ Carrinho vazio. Não é possível calcular total."
    
    subtotal = 0.0
    item_details = []
    
    for i, item in enumerate(items):
        preco = float(item.get("preco", 0.0))
        qtd = float(item.get("quantidade", 1.0))
        nome = item.get("produto", "Item")
        
        valor_item = round(preco * qtd, 2)
        subtotal += valor_item
        item_details.append(f"- {nome}: R$ {valor_item:.2f}")
        
    subtotal = round(subtotal, 2)
    taxa_entrega = round(float(taxa_entrega), 2)
    total_final = round(subtotal + taxa_entrega, 2)
    
    res = (
        f"📝 **Cálculo Oficial do Sistema:**\n"
        f"Subtotal: R$ {subtotal:.2f}\n"
        f"Taxa de Entrega: R$ {taxa_entrega:.2f}\n"
        f"----------------\n"
        f"💰 **TOTAL FINAL: R$ {total_final:.2f}**"
    )
    return res

def calculadora_tool(expressao: str) -> str:
    try:
        allowed = set("0123456789.+-*/() ")
        if not all(c in allowed for c in expressao):
            return "❌ Caracteres inválidos na expressão."
        resultado = eval(expressao, {"__builtins__": None}, {})
        return f"🔢 {expressao} = {resultado}"
    except Exception as e:
        return f"❌ Erro: {str(e)}"

# Tests
print("--- TEST 1: Calculadora Geral ---")
print(calculadora_tool("10 + 5 * 2"))
print(calculadora_tool("10.50 + 4.50"))
print(calculadora_tool("import os")) # Security check

print("\n--- TEST 2: Calcular Total Pedido ---")
print(calcular_total_tool("123", taxa_entrega=5.0))

print("\n--- TEST 3: Calcular Total (Sem taxa) ---")
print(calcular_total_tool("123", taxa_entrega=0))

print("\n--- TEST 4: Carrinho Vazio ---")
print(calcular_total_tool("empty"))
