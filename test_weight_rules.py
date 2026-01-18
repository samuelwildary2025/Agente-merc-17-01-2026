from unittest.mock import MagicMock
import json

# Mock dependencies
mock_add_to_cart = MagicMock(return_value=True)

# Copy-paste the NEW add_item_tool logic for testing
def add_item_tool(telefone: str, produto: str, quantidade: float = 1.0, observacao: str = "", preco: float = 0.0, unidades: int = 0) -> str:
    # --- REGRAS DE NEGÓCIO ---
    prod_lower = produto.lower()
    WEIGHT_RULES = {
        "pao frances": 0.050, "pão francês": 0.050, "carioquinha": 0.050, 
        "tomate": 0.150, "frango inteiro": 2.200
    }
    
    if unidades > 0:
        peso_unitario = None
        for key, weight in WEIGHT_RULES.items():
            if key in prod_lower:
                peso_unitario = weight
                break
        
        if peso_unitario:
            novo_peso = round(unidades * peso_unitario, 3)
            print(f"⚖️ REGRA APLICADA: {unidades}x {produto} -> {novo_peso}kg")
            quantidade = novo_peso
            obs_auto = f"(~{peso_unitario*1000:.0f}g/un)"
            if obs_auto not in observacao:
                observacao = f"{observacao} {obs_auto}".strip()

    item = {
        "produto": produto, "quantidade": quantidade, "unidades": unidades,
        "observacao": observacao, "preco": preco
    }
    return mock_add_to_cart(item)

# Test Cases
print("\n--- TEST 1: Pão Francês Units -> Weight ---")
# Agent sends 5 units but dummy weight 1.0 (or 0)
add_item_tool("123", "Pão Carioquinha", quantidade=1.0, unidades=5, preco=10.0)
call_args = mock_add_to_cart.call_args[0][0]
print(f"Item enviado pro Redis: {call_args}")
assert call_args["quantidade"] == 0.250 # 5 * 0.050

print("\n--- TEST 2: Tomate Units -> Weight ---")
add_item_tool("123", "Tomate maduro", quantidade=1.0, unidades=3, preco=5.0)
call_args = mock_add_to_cart.call_args[0][0]
print(f"Item enviado pro Redis: {call_args}")
assert call_args["quantidade"] == 0.450 # 3 * 0.150

print("\n--- TEST 3: Coca-Cola (Sem regra de peso) ---")
add_item_tool("123", "Coca Cola 2L", quantidade=2, unidades=0, preco=10.0)
call_args = mock_add_to_cart.call_args[0][0]
print(f"Item enviado pro Redis: {call_args}")
assert call_args["quantidade"] == 2 # Mantém quantidade original
