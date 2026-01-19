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

        # ==============================================================================
        # CENÁRIO 2: PRODUTO MAIS COMPLEXO (Diferença sutil de tipo/fragrância)
        # ==============================================================================
        print(f"\n{'='*50}")
        query_complex = "Detergente Ype Maçã 500ml"
        print(f"🔎 QUERY COMPLEXA: '{query_complex}'")
        
        # O banco vetorial pode trazer "Neutro" ou "Coco" primeiro pois são visualmente/textualmente 
        # muito similares e populares.
        passages_complex = [
            {"id": 10, "text": '{"produto": "Detergente Liquido Ype Neutro 500ml", "ean": "11111"}'}, # Muito comum
            {"id": 11, "text": '{"produto": "Detergente Liquido Ype Coco 500ml", "ean": "22222"}'},
            {"id": 12, "text": '{"produto": "Detergente Liquido Ype Maçã 500ml", "ean": "33333"}'}, # ALVO
            {"id": 13, "text": '{"produto": "Amaciante Ype Aconchego 500ml", "ean": "44444"}'},
            {"id": 14, "text": '{"produto": "Detergente Em Po Ype Caixa", "ean": "55555"}'},
        ]

        print("📋 ORDEM ORIGINAL (simulada):")
        for p in passages_complex:
            print(f"   [{p['id']}] {p['text']}")

        rerank_req_complex = RerankRequest(query=query_complex, passages=passages_complex)
        results_complex = ranker.rerank(rerank_req_complex)

        print("\n🚀 ORDEM APÓS RE-RANK:")
        for r in results_complex:
            original_text = next(p['text'] for p in passages_complex if p['id'] == r['id'])
            print(f"   [{r['score']:.4f}] {original_text}")

        if results_complex[0]['id'] == 12:
            print("\n✅ SUCESSO: Detergente Maçã foi identificado corretamente!")
        else:
            print(f"\n⚠️ FALHA: Esperava-se ID 12 (Maçã), veio ID {results_complex[0]['id']}")

        # ==============================================================================
        # CENÁRIO 3: COMBO COMPLETO (Marca + Tipo + Peso)
        # ==============================================================================
        print(f"\n{'='*50}")
        query_hard = "Feijão Carioca Camil 1kg"
        print(f"🔎 QUERY HARD: '{query_hard}'")
        
        passages_hard = [
            {"id": 20, "text": '{"produto": "Feijão Preto Camil 1kg", "ean": "AAAA"}'}, # Tipo errado
            {"id": 21, "text": '{"produto": "Feijão Carioca Kicaldo 1kg", "ean": "BBBB"}'}, # Marca errada
            {"id": 22, "text": '{"produto": "Feijão Carioca Camil 1kg", "ean": "CCCC"}'}, # ALVO
            {"id": 23, "text": '{"produto": "Feijão Carioca Camil 500g", "ean": "DDDD"}'}, # Peso errado
        ]

        print("📋 ORDEM ORIGINAL (simulada):")
        for p in passages_hard:
            print(f"   [{p['id']}] {p['text']}")

        rerank_req_hard = RerankRequest(query=query_hard, passages=passages_hard)
        results_hard = ranker.rerank(rerank_req_hard)

        print("\n🚀 ORDEM APÓS RE-RANK:")
        for r in results_hard:
            original_text = next(p['text'] for p in passages_hard if p['id'] == r['id'])
            print(f"   [{r['score']:.4f}] {original_text}")

        if results_hard[0]['id'] == 22:
            print("\n✅ SUCESSO: Feijão Carioca Camil 1kg isolado no topo!")
        else:
            print(f"\n⚠️ FALHA: Esperava-se ID 22 (Camil 1kg), veio ID {results_hard[0]['id']}")

        # ==============================================================================
        # CENÁRIO 4: RESTRIÇÃO ALIMENTAR (Sem Lactose vs Integral)
        # ==============================================================================
        print(f"\n{'='*50}")
        query_diet = "Leite Sem Lactose 1L"
        print(f"🔎 QUERY DIET: '{query_diet}'")
        
        # O "Integral" costuma ter score vetorial altíssimo com a palavra "Leite"
        passages_diet = [
            {"id": 30, "text": '{"produto": "Leite UHT Integral Itambe 1L", "ean": "X1"}'}, # Vilão comum
            {"id": 31, "text": '{"produto": "Leite UHT Desnatado Itambe 1L", "ean": "X2"}'},
            {"id": 32, "text": '{"produto": "Leite em Po Integral Itambe 400g", "ean": "X3"}'},
            {"id": 33, "text": '{"produto": "Leite UHT Zero Lactose Itambe 1L", "ean": "X4"}'}, # ALVO
        ]

        print("📋 ORDEM ORIGINAL (simulada):")
        for p in passages_diet:
            print(f"   [{p['id']}] {p['text']}")

        rerank_req_diet = RerankRequest(query=query_diet, passages=passages_diet)
        results_diet = ranker.rerank(rerank_req_diet)

        print("\n🚀 ORDEM APÓS RE-RANK:")
        for r in results_diet:
            original_text = next(p['text'] for p in passages_diet if p['id'] == r['id'])
            print(f"   [{r['score']:.4f}] {original_text}")

        if results_diet[0]['id'] == 33:
            print("\n✅ SUCESSO: Leite Zero Lactose identificado como prioridade!")
        else:
            print(f"\n⚠️ FALHA: Esperava-se ID 33 (Zero Lactose), veio ID {results_diet[0]['id']}")

        # ==============================================================================
        # CENÁRIO 5: MULTIPACK vs UNIDADE (Quantidade)
        # ==============================================================================
        print(f"\n{'='*50}")
        query_pack = "Cerveja Heineken Long Neck Pack 6"
        print(f"🔎 QUERY PACK: '{query_pack}'")
        
        passages_pack = [
            # A unidade individual costuma aparecer primeiro por ser o produto "base"
            {"id": 40, "text": '{"produto": "Cerveja Heineken Long Neck 330ml (Unidade)", "ean": "Y1"}'},
            {"id": 41, "text": '{"produto": "Cerveja Heineken Lata 350ml", "ean": "Y2"}'},
            # O Pack 6 correto
            {"id": 42, "text": '{"produto": "Cerveja Heineken Long Neck 330ml Pack com 6 Unidades", "ean": "Y3"}'}, # ALVO
            # Um pack errado (Zero alcool)
            {"id": 43, "text": '{"produto": "Cerveja Heineken Zero Long Neck 330ml Pack 6", "ean": "Y4"}'},
        ]

        print("📋 ORDEM ORIGINAL (simulada):")
        for p in passages_pack:
            print(f"   [{p['id']}] {p['text']}")

        rerank_req_pack = RerankRequest(query=query_pack, passages=passages_pack)
        results_pack = ranker.rerank(rerank_req_pack)

        print("\n🚀 ORDEM APÓS RE-RANK:")
        for r in results_pack:
            original_text = next(p['text'] for p in passages_pack if p['id'] == r['id'])
            print(f"   [{r['score']:.4f}] {original_text}")

        if results_pack[0]['id'] == 42:
            print("\n✅ SUCESSO: Pack de 6 unidades identificado!")
        else:
            print(f"\n⚠️ FALHA: Esperava-se ID 42 (Pack 6), veio ID {results_pack[0]['id']} (provável empate técnico)")

        # ==============================================================================
        # CENÁRIO 6: QUANTIDADE + TIPO (Papel Higiênico)
        # ==============================================================================
        print(f"\n{'='*50}")
        query_tp = "Papel Higiênico Neve Folha Dupla 12 Rolos"
        print(f"🔎 QUERY TP: '{query_tp}'")
        
        passages_tp = [
            {"id": 50, "text": '{"produto": "Papel Higienico Neve Folha Tripla 4 Rolos", "ean": "Z1"}'}, # Tipo/Qtd errada
            {"id": 51, "text": '{"produto": "Papel Higienico Personal Folha Dupla 12 Rolos", "ean": "Z2"}'}, # Marca errada
            {"id": 52, "text": '{"produto": "Papel Higienico Neve Folha Dupla 4 Rolos", "ean": "Z3"}'}, # Qtd errada
            {"id": 53, "text": '{"produto": "Papel Higienico Neve Folha Dupla 12 Rolos", "ean": "Z4"}'}, # ALVO
            {"id": 54, "text": '{"produto": "Papel Higienico Neve Supreme Folha Tripla 12 Rolos", "ean": "Z5"}'}, # Tipo errado
        ]

        print("📋 ORDEM ORIGINAL (simulada):")
        for p in passages_tp:
            print(f"   [{p['id']}] {p['text']}")

        rerank_req_tp = RerankRequest(query=query_tp, passages=passages_tp)
        results_tp = ranker.rerank(rerank_req_tp)

        print("\n🚀 ORDEM APÓS RE-RANK:")
        for r in results_tp:
            original_text = next(p['text'] for p in passages_tp if p['id'] == r['id'])
            print(f"   [{r['score']:.4f}] {original_text}")

        if results_tp[0]['id'] == 53:
            print("\n✅ SUCESSO: Neve FD 12 Rolos isolado!")
        else:
            print(f"\n⚠️ FALHA: Esperava-se ID 53, veio ID {results_tp[0]['id']}")


    except Exception as e:
        print(f"\n❌ ERRO FATAL: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_flashrank_direct()
