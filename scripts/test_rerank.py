import os
import sys
import logging
import json

# ==========================================
# MOCK ENV VARS TO BYPASS PYDANTIC SETTINGS
# ==========================================
os.environ["POSTGRES_CONNECTION_STRING"] = "postgresql://mock:5432/db"
os.environ["PRODUCTS_DB_CONNECTION_STRING"] = "postgresql://mock:5432/db"
os.environ["VECTOR_DB_CONNECTION_STRING"] = "postgresql://mock:5432/db"
os.environ["SUPERMERCADO_BASE_URL"] = "http://mock"
os.environ["SUPERMERCADO_AUTH_TOKEN"] = "mock"
os.environ["OPENAI_API_KEY"] = "mock-key"

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_rerank")

from flashrank import RerankRequest

def test_flashrank_direct():
    """
    Testa o ranker diretamente sem depender do banco de dados.
    Simula uma lista de resultados que o banco retornaria (com ordem 'errada')
    e verifica se o FlashRank corrige.
    """
    try:
        # Import lazy para garantir que os mocks de env funcionem
        from tools.db_vector_search import _get_ranker
        
        print("\n⏳ Carregando/Baixando modelo FlashRank (pode demorar no primeiro uso)...")
        ranker = _get_ranker()
        print("✅ Modelo carregado!\n")

        # Cenario: Busca por "Coca Cola 2L"
        # O banco vetorial (simulado) retornou 'Coca Lata' primeiro por similaridade semântica simples
        query = "Coca Cola 2L"
        
        # Passages simulando retorno do banco (ids arbitrários)
        # Note que a Coca 2L está na posição 2 (índice 1) ou 3, não em primeiro.
        passages = [
            {"id": 0, "text": '{"produto": "Coca Cola Lata 350ml", "ean": "789123"}'},
            {"id": 1, "text": '{"produto": "Coca Cola Pet 2L", "ean": "789456"}'}, # ALVO
            {"id": 2, "text": '{"produto": "Refrigerante Coca Cola Zero 2L", "ean": "789789"}'}, 
            {"id": 3, "text": '{"produto": "Fanta Laranja 2L", "ean": "123456"}'},
        ]
        
        print(f"🔎 QUERY: '{query}'")
        print("📋 ORDEM ORIGINAL (simulada do banco):")
        for p in passages:
            print(f"   [{p['id']}] {p['text']}")
            
        # Executar Re-rank
        rerank_request = RerankRequest(query=query, passages=passages)
        results = ranker.rerank(rerank_request)
        
        print("\n🚀 ORDEM APÓS RE-RANK:")
        for r in results:
            # Encontrar o texto original pelo ID
            original_text = next(p['text'] for p in passages if p['id'] == r['id'])
            print(f"   [{r['score']:.4f}] {original_text}")
            
        # Verificação simples
        top_result_id = results[0]['id']
        if top_result_id == 1:
            print("\n✅ SUCESSO: Coca Cola 2L subiu para o topo!")
        else:
            print(f"\n⚠️ AVISO: O top result foi ID {top_result_id}, esperava-se 1 (Coca 2L).")

    except Exception as e:
        print(f"\n❌ ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_flashrank_direct()
