
import json
import requests
from unittest.mock import MagicMock, patch

# Mock settings and logger
class MockSettings:
    supermercado_base_url = "https://api.test.com"
    supermercado_auth_token = "test-token"

settings = MockSettings()
logger = MagicMock()

# Import logic to test (copying for self-contained test if needed or patching)
# Here we will simulate the logic from http_tools.py

domain = "https://app.aimerc.com.br"

def _fix_url(u: str) -> str:
    if not u: return u
    if u.startswith("/"):
        u = f"{domain}{u}"
    elif "supermercadoqueiroz.com.br" in u:
        u = u.replace("https://supermercadoqueiroz.com.br", domain).replace("http://supermercadoqueiroz.com.br", domain)
    return u

def test_process_encartes(data):
    # 1. Tentar processar lista de encartes ativos (Novo comportamento)
    active_urls = data.get("active_encartes_urls")
    if isinstance(active_urls, list):
        data["active_encartes_urls"] = [_fix_url(u) for u in active_urls if u]
        # Se tivermos a lista, atualizamos o encarte_url legado com o primeiro da lista para compatibilidade
        if data["active_encartes_urls"]:
            data["encarte_url"] = data["active_encartes_urls"][0]
        else:
            data["encarte_url"] = ""
    
    # 2. Fallback/Processamento fixo do campo antigo se o novo não existir ou não for lista
    else:
        encarte_url = data.get("encarte_url", "")
        if encarte_url:
            data["encarte_url"] = _fix_url(encarte_url)
            # Garante que active_encartes_urls também exista como lista de um item
            data["active_encartes_urls"] = [data["encarte_url"]]
        else:
            data["encarte_url"] = ""
            data["active_encartes_urls"] = []
    return data

# Test Case 1: New API format with list
payload1 = {
    "active_encartes_urls": [
        "/media/encarte1.jpg",
        "https://supermercadoqueiroz.com.br/media/encarte2.png",
        "https://external.com/promo.webp"
    ]
}
result1 = test_process_encartes(payload1)
print("Test Case 1 (List):")
print(json.dumps(result1, indent=2))
assert result1["active_encartes_urls"][0] == "https://app.aimerc.com.br/media/encarte1.jpg"
assert result1["active_encartes_urls"][1] == "https://app.aimerc.com.br/media/encarte2.png"
assert result1["active_encartes_urls"][2] == "https://external.com/promo.webp"
assert result1["encarte_url"] == result1["active_encartes_urls"][0]

# Test Case 2: Legacy API format
payload2 = {
    "encarte_url": "/media/legacy.jpg"
}
result2 = test_process_encartes(payload2)
print("\nTest Case 2 (Legacy):")
print(json.dumps(result2, indent=2))
assert result2["encarte_url"] == "https://app.aimerc.com.br/media/legacy.jpg"
assert result2["active_encartes_urls"] == ["https://app.aimerc.com.br/media/legacy.jpg"]

# Test Case 3: Empty API format
payload3 = {
    "encarte_url": "",
    "active_encartes_urls": []
}
result3 = test_process_encartes(payload3)
print("\nTest Case 3 (Empty):")
print(json.dumps(result3, indent=2))
assert result3["encarte_url"] == ""
assert result3["active_encartes_urls"] == []

# Test Case 4: Missing fields
payload4 = {}
result4 = test_process_encartes(payload4)
print("\nTest Case 4 (Missing):")
print(json.dumps(result4, indent=2))
assert result4["encarte_url"] == ""
assert result4["active_encartes_urls"] == []

print("\n✅ All tests passed!")
