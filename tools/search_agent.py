"""
Ferramenta de Sub-Agente para Busca Especializada de Produtos
"""
import json
import logging
from typing import List, Dict, Any, Optional
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import JsonOutputParser

from config.settings import settings
from config.logger import setup_logger
from tools.db_vector_search import search_products_vector, _extract_ean_and_name
from tools.http_tools import estoque_preco

logger = setup_logger(__name__)

# ============================================
# 1. Definição do Prompt (O "Cérebro" do Sub-Agente)
# ============================================

SEARCH_AGENT_PROMPT = """
Você é o ANALISTA DE PRODUTOS do Mercadinho Queiroz.
Sua missão é receber um pedido "cru" do Vendedor (ex: "quatro carioquinha e uma coca") e retornar os produtos EXATOS e CORRETOS do banco de dados.

### SEU CLIENTE É O VENDEDOR
- O Vendedor não sabe procurar no banco de dados. Ele depende 100% de você.
- Se você errar, o Vendedor vende errado.
- Se você não achar, o Vendedor perde a venda.

### INSTRUÇÕES:
1. Analise o TERMO BUSCADO (ex: "leite", "pão", "coca").
2. Analise a LISTA DE CANDIDATOS que o sistema encontrou.
3. FILTRE RIGOROSAMENTE:
    - 🚨 **REGRA DE BEBIDAS:** Se pediu bebida (Coca, Cerveja) e NÃO falou "vasilhame/casco", **IGNORE** itens com nome "VASILHAME", "GARRAFAO", "RETORNAVEL". Priorize PET/Lata.
    - **Semântica:** "Carioquinha" = "Pão Francês". "Coca" = "Coca-Cola".
    - **Estoque:** Se souber que está sem estoque, avise.
4. RETORNE JSON LIMPO.

### CONTEXTO DE CANDIDATOS:
{candidates_context}

### TERMO BUSCADO:
"{user_query}"

### RETORNO ESPERADO (JSON):
Retorne uma lista JSON pura.
Format:
{{
    "ean": "123456",
    "nome": "Nome Exato do Produto",
    "score": 0.95,
    "razao": "Explicação breve (ex: 'Match exato com Coca PET')"
}}
"""

# ============================================
# 2. Configurações do Modelo
# ============================================

def _get_fast_llm():
    """Retorna um modelo rápido e barato para tarefas de sub-agente."""
    # Tenta usar um modelo "Flash" ou "Mini" se disponível, senão usa o padrão
    # PREFERÊNCIA: Usar o modelo configurado no settings (ex: grok-beta)
    model_name = getattr(settings, "llm_model", "gemini-2.5-flash")
    temp = 0.0 # Temperatura zero para precisão
    
    # Se quiser forçar um modelo mais leve para providers específicos:
    if settings.llm_provider == "openai" and "gpt" in model_name:
         # Se for OpenAI oficial, podemos tentar o mini. Se for xAI (que usa client openai), mantemos o do settings.
         if "x.ai" not in str(settings.openai_api_base):
            model_name = "gpt-4o-mini" 
         
    # Se houver override no settings, respeitar (mas idealmente forçamos um modelo rápido aqui)
    
    if settings.llm_provider == "google":
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.google_api_key,
            temperature=temp
        )
    else:
        client_kwargs = {}
        if settings.openai_api_base:
            client_kwargs["base_url"] = settings.openai_api_base

        return ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key,
            temperature=temp,
            **client_kwargs
        )

# ============================================
# 3. Função Principal (Tool)
# ============================================

def analista_produtos_tool(queries_str: str) -> str:
    """
    [ANALISTA DE PRODUTOS]
    Agente Especialista que traduz pedidos do cliente em produtos reais do banco de dados.
    Usa busca vetorial + inteligência semântica.
    
    Args:
        queries_str: Termos de busca (ex: "arroz, feijão, pão").
    """
    results = []
    
    # 1. Separar múltiplos termos (ex: "arroz, feijao")
    terms = [t.strip() for t in queries_str.replace('\n', ',').split(',') if t.strip()]
    
    logger.info(f"🕵️ [SUB-AGENT] Iniciando busca especialista para: {terms}")
    
    for term in terms:
        # 2. Busca Vetorial (Recuperação Bruta)
        # Usamos limit=10 para dar opções para o LLM escolher
        raw_result_str = search_products_vector(term, limit=10)
        
        # Se não achou nada na busca vetorial, pula
        if "Nenhum produto" in raw_result_str or "Erro" in raw_result_str:
            logger.warning(f"⚠️ [SUB-AGENT] Vetorial não achou nada para '{term}'")
            continue
            
        # 3. Invocar o LLM para Curadoria (O "Cérebro")
        try:
            llm = _get_fast_llm()
            prompt = ChatPromptTemplate.from_template(SEARCH_AGENT_PROMPT)
            chain = prompt | llm | JsonOutputParser()
            
            # Executar
            structured_matches = chain.invoke({
                "user_query": term,
                "candidates_context": raw_result_str
            })
            
            if structured_matches and isinstance(structured_matches, list):
                # Pegar o Top 1 (ou Top 2 se scores muito próximos, mas vamos simplificar para Top 1 por termo)
                # O LLM já deve ter ordenado por "score" ou relevância
                best_match = structured_matches[0]
                
                ean = best_match.get("ean")
                if ean:
                    # 4. Validar Estoque Real (Último Check)
                    stock_info = estoque_preco(ean)
                    
                    try:
                         #info_json = json.loads(stock_info) # A função estoque_preco as vezes retorna string direta se der erro, mas geralmente é lista JSON
                         # Melhor garantir parse seguro
                         if isinstance(stock_info, str) and stock_info.startswith("["):
                             info_json = json.loads(stock_info)
                         else:
                             info_json = []

                         if isinstance(info_json, list) and info_json:
                             item_data = info_json[0]
                             price = item_data.get("preco", 0)
                             name = item_data.get("produto", best_match.get("nome"))
                             
                             # RETORNO TÉCNICO PARA O VENDEDOR
                             # O Vendedor vai ler isso e decidir.
                             results.append(f"🔍 [ANALISTA] ITEM VALIDADO:\n- Nome: {name}\n- EAN: {ean}\n- Preço Tabela: R$ {price:.2f}\n- Score Semântico: {best_match.get('score')}\n- Obs: {best_match.get('razao')}")
                         else:
                             results.append(f"⚠️ [ANALISTA] EAN {ean} ({best_match.get('nome')}) encontrado na base, mas SEM ESTOQUE/PREÇO no sistema de vendas.")
                    except Exception as ex:
                        logger.error(f"Erro parse estoque: {ex}")
                        results.append(f"⚠️ [ANALISTA] Erro ao consultar preço do EAN {ean}.")
            else:
                results.append(f"❌ {term}: Não encontrei um produto correspondente no mix.")

        except Exception as e:
            logger.error(f"❌ [SUB-AGENT] Erro no processamento LLM para '{term}': {e}")
            results.append(f"❌ {term}: Erro interno na busca.")

    if not results:
        return "Nenhum produto encontrado."
        
    return "\n".join(results)
