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
Você é um ESPECIALISTA em encontrar produtos de supermercado.
Sua missão é receber uma busca do usuário, analisar os candidatos encontrados no banco de dados e retornar APENAS os produtos corretos que o cliente deseja.

### INSTRUÇÕES:
1. Analise o TERMO BUSCADO pelo usuário (ex: "leite", "pão", "coca").
2. Analise a LISTA DE CANDIDATOS que o sistema encontrou para este termo.
3. FILTRE os candidatos:
    - Remova produtos sem estoque (se a informação estiver disponível).
    - Remova produtos que não correspondem ao que o usuário quer (ex: se pediu "leite", remova "chocolate ao leite", "doce de leite").
    - Se o usuário foi genérico (ex: "café"), priorize os tradicionais/mais comuns.
    - Se o usuário foi específico (ex: "café solúvel"), traga apenas os que atendem.
4. PADRONIZE a saída em JSON.

### CONTEXTO DE CANDIDATOS:
{candidates_context}

### TERMO BUSCADO:
"{user_query}"

### RETORNO ESPERADO (JSON):
Retorne uma lista JSON pura com os produtos selecionados.
Se nenhum produto servir, retorne lista vazia [].

Formato do Item:
{{
    "ean": "123456",
    "nome": "Nome do Produto",
    "score": 0.95 (quão bom é esse match, de 0 a 1),
    "razao": "Explicação breve de por que escolheu este item"
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

def search_specialist_tool(queries_str: str) -> str:
    """
    Agente Especialista em Busca de Produtos.
    Recebe uma string com termos (ex: "arroz, feijão, 2 coca cola") e retorna os melhores matches validados.
    
    Args:
        queries_str: String com nomes de produtos, pode ser separada por vírgula ou quebra de linha.
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
                    
                    # Adicionar à lista final
                    # Precisamos parsear o retorno do estoque_preco para formatar bonito?
                    # Ou podemos retornar uma estrutura que o agente principal entenda?
                    # Vamos retornar um "Resumo" textual já pronto para o Agente Principal usar.
                    
                    try:
                         info_json = json.loads(stock_info)
                         if isinstance(info_json, list) and info_json:
                             item_data = info_json[0]
                             price = item_data.get("preco", 0)
                             name = item_data.get("produto", best_match.get("nome"))
                             
                             results.append(f"✅ Encontrado: {name} (R$ {price:.2f})")
                         else:
                             # Se estoque_preco retornou vazio (sem estoque)
                             results.append(f"⚠️ {term}: Produto '{best_match.get('nome')}' encontrado, mas está SEM ESTOQUE no momento.")
                    except:
                        results.append(f"⚠️ {term}: Erro ao consultar preço.")
            else:
                results.append(f"❌ {term}: Não encontrei um produto correspondente no mix.")

        except Exception as e:
            logger.error(f"❌ [SUB-AGENT] Erro no processamento LLM para '{term}': {e}")
            results.append(f"❌ {term}: Erro interno na busca.")

    if not results:
        return "Nenhum produto encontrado."
        
    return "\n".join(results)
