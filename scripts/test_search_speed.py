import sys
import time
import os
from pathlib import Path

# Fix imports
sys.path.append(str(Path(__file__).parent.parent))

from tools.search_agent import analista_produtos_tool
from config.settings import settings

def test_speed():
    # Simulate a complex order
    query = "arroz, feijao, macarrao, oleo, acucar"
    print(f"🚀 Iniciando teste de velocidade com 5 itens: {query}")
    
    start = time.time()
    result = analista_produtos_tool(query, telefone="TEST_SPEED")
    end = time.time()
    
    elapsed = end - start
    print(f"\n⏱️ Tempo Total: {elapsed:.2f} segundos")
    print(f"📦 Resultado (primeiros 200 chars): {result[:200]}...")
    
    if elapsed < 10: # Assuming 2s per item in serial vs 2s total in parallel + overhead
        print("✅ Teste de Velocidade: APROVADO (Rápido)")
    else:
        print("⚠️ Teste de Velocidade: LENTO (Possível falha na paralelização)")

if __name__ == "__main__":
    test_speed()
