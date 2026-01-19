"""
Agente de IA para Atendimento de Supermercado usando LangGraph
Versão com suporte a VISÃO e Pedidos com Comprovante
"""

from typing import Dict, Any, TypedDict, Sequence, List
import re
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.callbacks import get_openai_callback
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition, create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from pathlib import Path
import json
import os

from config.settings import settings
from config.logger import setup_logger
from tools.http_tools import estoque, pedidos, alterar, ean_lookup, estoque_preco, busca_lote_produtos, consultar_encarte
from tools.time_tool import get_current_time, search_message_history
from tools.redis_tools import (
    mark_order_sent, 
    add_item_to_cart, 
    get_cart_items, 
    remove_item_from_cart, 
    clear_cart,
    set_comprovante,
    get_comprovante,
    clear_comprovante
)
from memory.limited_postgres_memory import LimitedPostgresChatMessageHistory

logger = setup_logger(__name__)

# ============================================
# Definição das Ferramentas (Tools)
# ============================================

@tool
def estoque_tool(url: str) -> str:
    """
    Consultar estoque e preço atual dos produtos no sistema do supermercado.
    Ex: 'https://.../api/produtos/consulta?nome=arroz'
    """
    return estoque(url)

@tool
def add_item_tool(telefone: str, produto: str, quantidade: float = 1.0, observacao: str = "", preco: float = 0.0, unidades: int = 0) -> str:
    """
    Adicionar um item ao carrinho de compras do cliente.
    USAR IMEDIATAMENTE quando o cliente demonstrar intenção de compra.
    
    Para produtos vendidos por KG (frutas, legumes, carnes):
    - quantidade: peso em kg (ex: 0.45 para 450g)
    - unidades: número de unidades pedidas (ex: 3 para 3 tomates)
    - preco: preço por kg
    
    Para produtos unitários:
    - quantidade: número de itens
    - unidades: deixar 0
    - preco: preço por unidade
    """
    
    # --- REGRAS DE NEGÓCIO (CONVERSÃO AUTOMÁTICA) ---
    # Se o agente passar unidades, tentamos converter para peso automaticamente
    # baseado nas regras médias do supermercado.
    
    prod_lower = produto.lower()
    
    WEIGHT_RULES = {
        "pao frances": 0.050, "pão francês": 0.050, "carioquinha": 0.050, "pao carioquinha": 0.050,
        "pao sovado": 0.060, "pão sovado": 0.060, "massa fina": 0.060,
        "mini bolinha": 0.016, "mini coxinha": 0.016,
        "tomate": 0.150, "cebola": 0.150, "batata": 0.150,
        "frango inteiro": 2.200, "frango abatido": 2.200,
        "calabresa": 0.250, "paio": 0.250, "linguica": 0.250,
        "bacon": 0.300,
        "limao": 0.100, "limão": 0.100, "banana": 0.100, "maca": 0.100, "maçã": 0.100,
        "mamao": 1.500, "mamão": 1.500, "melao": 1.500, "melão": 1.500,
        "melancia": 2.000,
        "abacate": 0.600
    }
    
    # Se unidades foi informado (>0) e é um produto de peso:
    if unidades > 0:
        # Tenta achar regra de peso
        peso_unitario = None
        for key, weight in WEIGHT_RULES.items():
            if key in prod_lower:
                peso_unitario = weight
                break
        
        # Se achou regra, recalcula o peso total (Override seguro)
        if peso_unitario:
            novo_peso = round(unidades * peso_unitario, 3)
            # Log de auditoria (print para debug)
            print(f"⚖️ REGRA APLICADA: {unidades}x {produto} -> {novo_peso}kg (Era: {quantidade})")
            quantidade = novo_peso
            
            # Ajuste na observação para clareza
            obs_auto = f"(~{peso_unitario*1000:.0f}g/un)"
            if obs_auto not in observacao:
                observacao = f"{observacao} {obs_auto}".strip()

    item = {
        "produto": produto,
        "quantidade": quantidade,  # Peso em kg OU quantidade de unidades
        "unidades": unidades,      # Número de unidades (se aplicável)
        "observacao": observacao,
        "preco": preco            # Preço por kg OU por unidade
    }
    
    import json as json_lib
    if add_item_to_cart(telefone, json_lib.dumps(item, ensure_ascii=False)):
        if unidades > 0:
            return f"✅ Item '{produto}' ({unidades} un, ~{quantidade:.3f}kg) adicionado.\n\nGostaria de adicionar algo mais?"
        return f"✅ Item '{produto}' ({quantidade}) adicionado ao carrinho.\n\nGostaria de adicionar algo mais?"
    return "❌ Erro ao adicionar item. Tente novamente."

@tool
def view_cart_tool(telefone: str) -> str:
    """
    Ver os itens atuais no carrinho do cliente.
    """
    items = get_cart_items(telefone)
    if not items:
        return "🛒 O carrinho está vazio."
    
    summary = ["🛒 **Carrinho Atual:**"]
    total_estimado = 0.0
    for i, item in enumerate(items):
        qtd = item.get("quantidade", 1)
        nome = item.get("produto", "?")
        obs = item.get("observacao", "")
        preco = item.get("preco", 0.0)
        subtotal = qtd * preco
        total_estimado += subtotal
        
        desc = f"{i+1}. {nome} (x{qtd})"
        if preco > 0:
            desc += f" - R$ {subtotal:.2f}"
        if obs:
            desc += f" [Obs: {obs}]"
        summary.append(desc)
    
    if total_estimado > 0:
        summary.append(f"\n💰 **Total Estimado:** R$ {total_estimado:.2f}")
    
    summary.append("\nGostaria de adicionar algo mais ou posso fechar?")
        
    return "\n".join(summary)

@tool
def remove_item_tool(telefone: str, item_index: int) -> str:
    """
    Remover um item do carrinho pelo número (índice 1-based, como mostrado no view_cart).
    Ex: Para remover o item 1, passe 1.
    """
    # Converter de 1-based para 0-based
    idx = int(item_index) - 1
    if remove_item_from_cart(telefone, idx):
        return f"✅ Item {item_index} removido do carrinho."
    return "❌ Erro ao remover item (índice inválido?)."

@tool
def finalizar_pedido_tool(cliente: str, telefone: str, endereco: str, forma_pagamento: str, observacao: str = "", comprovante: str = "", taxa_entrega: float = 0.0) -> str:
    """
    Finalizar o pedido usando os itens que estão no carrinho.
    Use quando o cliente confirmar que quer fechar a compra.
    
    Args:
    - cliente: Nome do cliente
    - telefone: Telefone (com DDD)
    - endereco: Endereço de entrega (rua, número, bairro)
    - forma_pagamento: PIX, DINHEIRO, CARTAO
    - observacao: Observações do pedido (opcional)
    - comprovante: URL do comprovante (opcional - será buscado automaticamente se não fornecido)
    - taxa_entrega: Valor da taxa de entrega em reais (opcional, padrão 0)
    """
    import json as json_lib
    
    # 0. Buscar comprovante salvo automaticamente se não foi passado
    comprovante_final = comprovante
    if not comprovante_final:
        comprovante_salvo = get_comprovante(telefone)
        if comprovante_salvo:
            comprovante_final = comprovante_salvo
            logger.info(f"🧾 Usando comprovante salvo no Redis: {comprovante_salvo[:50]}...")
    
    # 1. Obter itens do Redis
    items = get_cart_items(telefone)
    if not items:
        return "❌ O carrinho está vazio! Adicione itens antes de finalizar."
    
    # 2. Calcular total e formatar itens para API
    total = 0.0
    itens_formatados = []
    
    for item in items:
        preco = item.get("preco", 0.0)
        quantidade = item.get("quantidade", 1.0)
        unidades = item.get("unidades", 0)
        obs_item = item.get("observacao", "")
        total += preco * quantidade
        
        nome_produto = item.get("produto", item.get("nome_produto", "Produto"))
        
        # Se tem unidades, é produto pesado (tomate, cebola, pão, etc)
        if unidades > 0:
            qtd_api = unidades
            valor_estimado = round(preco * quantidade, 2)
            # IMPORTANTE: preco_unitario para API deve ser por UNIDADE, não por KG
            # Caso contrário: 8 pães × R$15.99/kg = R$127.92 (ERRADO)
            # Correto: 8 pães × R$0.80/un = R$6.40
            preco_unitario_api = round(valor_estimado / unidades, 2)
            obs_peso = f"Peso estimado: {quantidade:.3f}kg (~R${valor_estimado:.2f}). PESAR para confirmar valor."
            if obs_item:
                obs_item = f"{obs_item}. {obs_peso}"
            else:
                obs_item = obs_peso
        else:
            # Produto unitário normal
            if quantidade < 1 or quantidade != int(quantidade):
                qtd_api = 1
            else:
                qtd_api = int(quantidade)
            preco_unitario_api = round(preco, 2)
        
        itens_formatados.append({
            "nome_produto": nome_produto,
            "quantidade": qtd_api,
            "preco_unitario": preco_unitario_api,
            "observacao": obs_item
        })
    
    # 2.1 Adicionar taxa de entrega como item separado (se houver)
    if taxa_entrega > 0:
        itens_formatados.append({
            "nome_produto": "TAXA DE ENTREGA",
            "quantidade": 1,
            "preco_unitario": round(taxa_entrega, 2),
            "observacao": ""
        })
        total += taxa_entrega
        
    # 3. Montar payload do pedido (campos corretos para API)
    payload = {
        "nome_cliente": cliente,
        "telefone": telefone,
        "endereco": endereco or "A combinar",
        "forma": forma_pagamento,
        "observacao": observacao or "",
        "comprovante_pix": comprovante_final or None,
        "itens": itens_formatados
    }
    
    json_body = json_lib.dumps(payload, ensure_ascii=False)
    
    # 4. Enviar via HTTP
    result = pedidos(json_body)
    
    # 5. Se sucesso, limpar carrinho, comprovante e marcar status
    # 5. Se sucesso, limpar carrinho, comprovante e marcar status
    if "sucesso" in result.lower() or "✅" in result:
        clear_cart(telefone)
        clear_comprovante(telefone)  # Limpar comprovante salvo
        mark_order_sent(telefone)
        
        # FIX: Retornar o total calculado para evitar alucinação do agente
        return f"{result}\n\n💰 **Valor Total Processado:** R$ {total:.2f}\n(O agente DEVE usar este valor na resposta)"
        
    return result

@tool
def alterar_tool(telefone: str, json_body: str) -> str:
    """Atualizar o pedido no painel (para pedidos JÁ enviados)."""
    return alterar(telefone, json_body)

@tool
def search_history_tool(telefone: str, keyword: str = None) -> str:
    """Busca mensagens anteriores do cliente com horários."""
    return search_message_history(telefone, keyword)

@tool
def time_tool() -> str:
    """Retorna a data e hora atual."""
    return get_current_time()

@tool("ean")
def ean_tool_alias(query: str) -> str:
    """Buscar EAN/infos do produto na base de conhecimento."""
    q = (query or "").strip()
    if q.startswith("{") and q.endswith("}"): q = ""
    return ean_lookup(q)

@tool("estoque")
def estoque_preco_alias(ean: str) -> str:
    """Consulta preço e disponibilidade pelo EAN (apenas dígitos)."""
    return estoque_preco(ean)

@tool("busca_lote")
def busca_lote_tool(produtos: str) -> str:
    """
    Busca MÚLTIPLOS produtos de uma vez em paralelo. Use quando o cliente pedir vários itens.
    
    Args:
        produtos: Lista de produtos separados por vírgula.
                  Ex: "suco de acerola, suco de caju, arroz, feijão"
    
    Returns:
        Lista formatada com todos os produtos encontrados e seus preços.
    """
    # Converter string em lista
    lista_produtos = [p.strip() for p in produtos.split(",") if p.strip()]
    if not lista_produtos:
        return "❌ Informe os produtos separados por vírgula."
    return busca_lote_produtos(lista_produtos)

@tool
def salvar_comprovante_tool(telefone: str, url: str) -> str:
    """
    Salva a URL do comprovante PIX enviado pelo cliente.
    Use quando receber uma imagem de comprovante de pagamento válida.
    O comprovante será anexado automaticamente ao pedido quando finalizado.
    
    Args:
    - telefone: Telefone do cliente
    - url: URL da imagem do comprovante
    """
    if set_comprovante(telefone, url):
        return "✅ Comprovante PIX salvo com sucesso! Será anexado ao pedido automaticamente."
    return "❌ Erro ao salvar comprovante. Tente novamente."

@tool
def consultar_encarte_tool() -> str:
    """
    Consulta o encarte (folheto de ofertas) atual do supermercado.
    Use APENAS se o cliente perguntar explicitamente sobre ofertas, promoções ou encarte.
    
    Returns:
        JSON com a URL (campo encarte_url) ou lista de URLs (campo active_encartes_urls) das imagens.
    """
    return consultar_encarte()

@tool
def calcular_total_tool(telefone: str, taxa_entrega: float = 0.0) -> str:
    """
    Calcula o valor exato do pedido somando itens do carrinho + taxa de entrega.
    Use SEMPRE antes de informar o total final ao cliente.
    
    Args:
    - telefone: Telefone do cliente
    - taxa_entrega: Valor da taxa de entrega a ser somada (se houver)
    """
    items = get_cart_items(telefone)
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

@tool
def calculadora_tool(expressao: str) -> str:
    """
    Calculadora simples para operações matemáticas gerais.
    Use para conferir contas ou somar valores avulsos.
    Ex: '12.50 + 5.00', '3 * 4.50'
    """
    try:
        # Sanitização básica (permitir apenas math)
        allowed = set("0123456789.+-*/() ")
        if not all(c in allowed for c in expressao):
            return "❌ Caracteres inválidos na expressão."
        
        # Eval seguro após sanitização
        resultado = eval(expressao, {"__builtins__": None}, {})
        return f"🔢 {expressao} = {resultado}"
    except Exception as e:
        return f"❌ Erro: {str(e)}"

# Ferramentas ativas
ACTIVE_TOOLS = [
    ean_tool_alias,
    estoque_preco_alias,
    busca_lote_tool,  # Nova tool para busca em lote
    estoque_tool,
    time_tool,
    search_history_tool,
    add_item_tool,
    view_cart_tool,
    remove_item_tool,
    finalizar_pedido_tool,
    alterar_tool,
    consultar_encarte_tool,
    calcular_total_tool,  # Novo: Cálculo exato do pedido
    calculadora_tool,     # Novo: Calculadora geral
    # salvar_comprovante_tool removido - comprovante agora é salvo automaticamente pelo server.py
]

# ============================================
# Funções do Grafo
# ============================================

def load_system_prompt() -> str:
    base_dir = Path(__file__).resolve().parent
    prompt_path = str((base_dir / "prompts" / "agent_system_compact.md"))
    try:
        text = Path(prompt_path).read_text(encoding="utf-8")
        text = text.replace("{base_url}", settings.supermercado_base_url)
        text = text.replace("{ean_base}", settings.estoque_ean_base_url)
        return text
    except Exception as e:
        logger.error(f"Falha ao carregar prompt: {e}")
        raise

def _build_llm(model_override: str = None):
    model = model_override or getattr(settings, "llm_model", "gemini-2.5-flash")
    temp = float(getattr(settings, "llm_temperature", 0.0))
    provider = getattr(settings, "llm_provider", "google")
    
    if provider == "google":
        logger.info(f"🚀 Usando Google Gemini: {model}")
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=temp,
            convert_system_message_to_human=True,  # Necessário para Gemini processar system prompts
        )
    else:
        logger.info(f"🚀 Usando OpenAI: {model}")
        return ChatOpenAI(
            model=model,
            openai_api_key=settings.openai_api_key,
            temperature=temp
        )

def create_agent_with_history(model_override: str = None):
    system_prompt = load_system_prompt()
    llm = _build_llm(model_override)
    memory = MemorySaver()
    agent = create_react_agent(llm, ACTIVE_TOOLS, prompt=system_prompt, checkpointer=memory)
    return agent

_agent_graph = None
def get_agent_graph(model_override: str = None):
    # Removido cache global para permitir hot-reload do prompt
    # global _agent_graph
    # if _agent_graph is None:
    #     _agent_graph = create_agent_with_history()
    # return _agent_graph
    return create_agent_with_history(model_override)

# ============================================
# Função Principal
# ============================================

def run_agent_langgraph(telefone: str, mensagem: str) -> Dict[str, Any]:
    """
    Executa o agente. Suporta texto e imagem (via tag [MEDIA_URL: ...]).
    """
    print(f"[AGENT] Telefone: {telefone} | Msg bruta: {mensagem[:50]}...")
    
    # 1. Extrair URL de imagem se houver (Formato: [MEDIA_URL: https://...])
    image_url = None
    clean_message = mensagem
    
    # Regex para encontrar a tag de mídia injetada pelo server.py
    media_match = re.search(r"\[MEDIA_URL:\s*(.*?)\]", mensagem)
    if media_match:
        image_url = media_match.group(1)
        # Remove a tag da mensagem de texto para não confundir o histórico visual
        # Mas mantemos o texto descritivo original
        clean_message = mensagem.replace(media_match.group(0), "").strip()
        if not clean_message:
            clean_message = "Analise esta imagem/comprovante enviada."
        logger.info(f"📸 Mídia detectada para visão: {image_url}")

    # 2. Obter handler de histórico e CARREGAR mensagens anteriores
    history_handler = None
    previous_messages: List[BaseMessage] = []
    try:
        history_handler = get_session_history(telefone)
        # IMPORTANTE: Carregar histórico ANTES de adicionar a nova mensagem
        previous_messages = history_handler.messages
        logger.info(f"📚 Histórico carregado: {len(previous_messages)} mensagens anteriores")
        # Agora salva a nova mensagem do usuário
        history_handler.add_user_message(mensagem)
    except Exception as e:
        logger.error(f"Erro DB User: {e}")

    try:
        agent = get_agent_graph()
        
        # 3. Construir mensagem (Texto Simples ou Multimodal)
        # IMPORTANTE: Injetar telefone e horário no contexto para que o LLM saiba qual usar
        from tools.time_tool import get_current_time
        hora_atual = get_current_time()
        contexto = f"[TELEFONE_CLIENTE: {telefone}]\n[HORÁRIO_ATUAL: {hora_atual}]\n"
        
        # Se há URL de imagem, injetar no contexto para o agente poder usar em salvar_comprovante_tool
        if image_url:
            contexto += f"[URL_IMAGEM: {image_url}]\n"
        
        # EXPANSÃO DE MENSAGENS CURTAS para ajudar o Gemini
        # Mensagens como "sim", "não", "ok" sozinhas confundem o modelo
        mensagem_expandida = clean_message
        msg_lower = clean_message.lower().strip()
        
        if msg_lower in ["sim", "s", "ok", "pode", "isso", "quero", "beleza", "blz", "bora", "vamos"]:
            # Buscar última mensagem da IA no histórico para dar contexto
            ultima_pergunta_ia = ""
            for msg in reversed(previous_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if content.strip() and not content.startswith("["):
                        ultima_pergunta_ia = content[:200]
                        break
            
            if ultima_pergunta_ia:
                mensagem_expandida = f"O cliente respondeu '{clean_message}' à sua pergunta anterior: \"{ultima_pergunta_ia}...\". Execute a ação apropriada."
                logger.info(f"🔄 Mensagem curta expandida: '{clean_message}' → contexto adicionado")
        elif msg_lower in ["nao", "não", "n", "nope", "nao quero", "não quero"]:
            mensagem_expandida = f"O cliente respondeu '{clean_message}' (NEGATIVO). Pergunte se precisa de mais alguma coisa."
            logger.info(f"🔄 Mensagem curta expandida (negativo): '{clean_message}'")
        
        contexto += "\n"
        
        if image_url:
            # Formato multimodal para GPT-4o / GPT-4o-mini
            message_content = [
                {"type": "text", "text": contexto + mensagem_expandida},
                {
                    "type": "image_url",
                    "image_url": {"url": image_url}
                }
            ]
            current_message = HumanMessage(content=message_content)
        else:
            current_message = HumanMessage(content=contexto + mensagem_expandida)

        # 4. Montar estado inicial COM histórico de mensagens anteriores
        # Isso permite que o LLM tenha contexto da conversa
        all_messages = list(previous_messages) + [current_message]
        initial_state = {"messages": all_messages}
        logger.info(f"📨 Enviando {len(all_messages)} mensagens para o LLM (histórico + atual)")
        
        config = {"configurable": {"thread_id": telefone}, "recursion_limit": 100}
        
        # RETRY AUTOMÁTICO com FALLBACK para Gemini 2.0 Flash
        max_retries = 2
        llm_generated_nothing = True
        result = None
        fallback_model = "gemini-2.5-flash"
        
        for attempt in range(max_retries + 1):
            # Na segunda tentativa, usar modelo de fallback
            if attempt > 0:
                logger.warning(f"🔄 Tentativa {attempt + 1}/{max_retries + 1} - Tentando com {fallback_model}...")
                import time
                time.sleep(0.3)  # Pequeno delay entre tentativas
                agent = get_agent_graph(model_override=fallback_model)
            
            logger.info("Executando agente...")
            
            # Contador de tokens
            with get_openai_callback() as cb:
                result = agent.invoke(initial_state, config)
                
                # Cálculo de custo baseado no provider
                provider = getattr(settings, "llm_provider", "google")
                if provider == "google":
                    input_cost = (cb.prompt_tokens / 1_000_000) * 0.10
                    output_cost = (cb.completion_tokens / 1_000_000) * 0.40
                else:
                    input_cost = (cb.prompt_tokens / 1_000_000) * 0.15
                    output_cost = (cb.completion_tokens / 1_000_000) * 0.60
                
                total_cost = input_cost + output_cost
                
                logger.info(f"📊 TOKENS - Prompt: {cb.prompt_tokens} | Completion: {cb.completion_tokens} | Total: {cb.total_tokens}")
                logger.info(f"💰 CUSTO: ${total_cost:.6f} USD (Input: ${input_cost:.6f} | Output: ${output_cost:.6f})")
                
                llm_generated_nothing = cb.completion_tokens == 0
                
                # Se gerou algo, sair do loop
                if not llm_generated_nothing:
                    if attempt > 0:
                        logger.info(f"✅ Retry bem-sucedido na tentativa {attempt + 1}")
                    break
        
        # 4. Extrair resposta (com fallback para Gemini empty responses)
        output = ""
        if isinstance(result, dict) and "messages" in result:
            messages = result["messages"]
            logger.debug(f"📨 Total de mensagens no resultado: {len(messages) if messages else 0}")
            if messages and not llm_generated_nothing:  # ✅ Só busca mensagens se LLM gerou algo
                # Log das últimas mensagens para debug
                for i, msg in enumerate(messages[-5:]):
                    msg_type = type(msg).__name__
                    has_tool_calls = hasattr(msg, 'tool_calls') and msg.tool_calls
                    content_preview = str(msg.content)[:100] if msg.content else "(vazio)"
                    logger.debug(f"📝 Msg[{i}] type={msg_type} tool_calls={has_tool_calls} content={content_preview}")
                
                # Tentar pegar a última mensagem AI que tenha conteúdo real (não tool call)
                for msg in reversed(messages):
                    # Verificar se é AIMessage
                    if not isinstance(msg, AIMessage):
                        continue
                    
                    # Ignorar mensagens que são tool calls (não tem resposta textual)
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        continue
                    
                    # Extrair conteúdo
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    
                    # Ignorar mensagens vazias
                    if not content or not content.strip():
                        continue
                    
                    # Ignorar mensagens que parecem ser dados estruturados
                    if content.strip().startswith(("[", "{")):
                        continue
                    
                    output = content
                    break
        
        # Fallback se ainda estiver vazio
        if not output or not output.strip():
            # CRITICAL: Se LLM não gerou nada (0 completion tokens), retornar erro
            if llm_generated_nothing:
                logger.error("❌ LLM retornou 0 completion tokens - modelo pode estar sobrecarregado ou com problema")
                output = "Desculpe, tive um problema ao processar. Pode repetir por favor?"
            else:
                # Logar o que foi rejeitado para debug
                if isinstance(result, dict) and "messages" in result:
                    last_ai = None
                    for msg in reversed(result["messages"]):
                        if isinstance(msg, AIMessage):
                            last_ai = msg
                            break
                    if last_ai:
                        logger.warning(f"⚠️ Última AIMessage rejeitada: content='{str(last_ai.content)[:200]}' tool_calls={getattr(last_ai, 'tool_calls', None)}")
            
            # FALLBACK INTELIGENTE: Analisa as mensagens de tool para gerar resposta útil
            tool_results = []
            produtos_encontrados = []
            precos_encontrados: List[str] = []
            nao_encontrados_list: List[str] = []
            
            for msg in result.get("messages", []):
                if hasattr(msg, 'content') and isinstance(msg.content, str):
                    content = msg.content
                    # Detectar resposta de estoque vazio
                    if "0 item" in content or "disponíveis após filtragem" in content or "[]" in content:
                        tool_results.append("sem_estoque")
                    # Detectar busca de EAN e extrair nomes dos produtos
                    elif "EANS_ENCONTRADOS" in content:
                        tool_results.append("ean_encontrado")
                        # Extrair nomes dos produtos (formato: "1) EAN - NOME PRODUTO")
                        matches = re.findall(r'\d+\) \d+ - ([A-Z][^\n;]+)', content)
                        if matches:
                            produtos_encontrados.extend(matches[:3])  # Pegar até 3 produtos
                    # Detectar produto não encontrado
                    elif "Nenhum produto encontrado" in content or "não encontrado" in content.lower():
                        tool_results.append("nao_encontrado")
                    # Detectar formato da busca em lote
                    elif "PRODUTOS_ENCONTRADOS:" in content:
                        tool_results.append("busca_lote_ok")
                        # Capturar linhas com "• Nome - R$ XX,YY"
                        linhas = content.split("\n")
                        for ln in linhas:
                            ln_str = ln.strip()
                            if ln_str.startswith("• ") and ("R$" in ln_str or "R$" in ln_str.replace(" ", "")):
                                precos_encontrados.append(ln_str[2:].strip())
                    elif "NÃO_ENCONTRADOS:" in content or "NAO_ENCONTRADOS:" in content:
                        # Extrair lista após os dois pontos
                        try:
                            parte = content.split(":", 1)[1]
                            nomes = [x.strip() for x in parte.split(",") if x.strip()]
                            nao_encontrados_list.extend(nomes)
                        except Exception:
                            pass
                    # Detectar SUCESSO na busca em lote (Fallback para quando o LLM falha em responder)
                    elif "✅ [BUSCA LOTE] Sucesso" in content:
                        # Extrair produto e preço: "Sucesso com 'NOME' (R$ XX.XX)"
                        match = re.search(r"Sucesso com '([^']+)' \((R\$ [0-9.,]+)\)", content)
                        if match:
                            prod, preco = match.groups()
                            tool_results.append(f"sucesso:{prod}:{preco}")
            
            # Gerar resposta baseada nos resultados das tools
            if any(r.startswith("sucesso:") for r in tool_results) or ("busca_lote_ok" in tool_results and precos_encontrados):
                # Extrair itens encontrados
                itens_ok = []
                if precos_encontrados:
                    itens_ok.extend(precos_encontrados)
                for r in tool_results:
                    if r.startswith("sucesso:"):
                        _, prod, preco = r.split(":", 2)
                        itens_ok.append(f"{prod} - {preco}")

                # Montar resposta amigável
                if itens_ok:
                    linhas = ["Aqui estão os valores:"] + [f"* {ln}" for ln in itens_ok]
                    if nao_encontrados_list:
                        linhas.append(f"\nNão encontrei: {', '.join(nao_encontrados_list)}.")
                    linhas.append("Quer que eu adicione ao carrinho?")
                    output = "\n".join(linhas)
                    logger.info(f"🔄 Fallback inteligente: gerando resposta de preços - {output}")
                else:
                    output = "Não consegui obter os preços agora. Pode repetir?"

            elif "sem_estoque" in tool_results:
                if produtos_encontrados:
                    # Oferecer alternativas da lista de produtos encontrados
                    alternativas = ", ".join(produtos_encontrados[:2])
                    output = f"Não temos esse produto disponível. Temos: {alternativas}. Quer algum desses?"
                    logger.info(f"🔄 Fallback inteligente: oferecendo alternativas - {alternativas}")
                else:
                    output = "Não temos esse produto disponível no momento. Quer outro?"
                    logger.info("🔄 Fallback inteligente: produto sem estoque, sem alternativas")
            elif "nao_encontrado" in tool_results:
                output = "Não achei esse produto. Pode descrever de outra forma?"
                logger.info("🔄 Fallback inteligente: produto não encontrado")
            else:
                # 🚨 FALLBACK PARA RESPOSTAS CURTAS DE CONTEXTO (Gemini retornou vazio)
                # Se a mensagem original é curta e parece ser uma resposta de contexto,
                # tentar buscar o produto diretamente
                # Pegar a última mensagem do usuário e a última mensagem da IA (contexto)
                user_msg = ""
                last_ai_msg = ""
                messages = result.get("messages", [])
                
                for msg in reversed(messages):
                    if not user_msg and isinstance(msg, HumanMessage):
                        user_msg = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if not last_ai_msg and isinstance(msg, AIMessage) and msg.content:
                        last_ai_msg = (msg.content if isinstance(msg.content, str) else str(msg.content)).lower()
                
                mensagem_lower = user_msg.lower().strip()
                
                # Mapeamento inteligente de ASSUNTOS (Contexto Deslizante)
                # Se a última mensagem da Ana continha essas palavras, elas "deslizam" para a busca
                TOPICOS_CONTEXTO = {
                    "pão": "pao",
                    "pao": "pao",
                    "cerveja": "cerveja",
                    "carne": "carne",
                    "frango": "frango",
                    "leite": "leite",
                    "arroz": "arroz",
                    "feijão": "feijao",
                    "feijao": "feijao",
                    "açúcar": "acucar",
                    "acucar": "acucar",
                    "café": "cafe",
                    "cafe": "cafe"
                }

                search_term = None
                prefixo_contexto = ""
                
                # 1. Tentar identificar um tópico na pergunta da Ana para "deslizar"
                for topico, prefixo in TOPICOS_CONTEXTO.items():
                    if topico in last_ai_msg:
                        prefixo_contexto = prefixo
                        break
                
                # 2. Se achou um tópico e a resposta do cliente é curta, fundir (Sliding Window)
                if prefixo_contexto and len(mensagem_lower.split()) <= 3:
                    # Evitar duplicar (ex: Ana diz "pão", cliente diz "pão hot dog")
                    if prefixo_contexto not in mensagem_lower:
                        search_term = f"{prefixo_contexto} {mensagem_lower}"
                    else:
                        search_term = mensagem_lower
                
                # 3. Se não tem contexto deslizante, usar o mapeamento genérico
                if not search_term:
                    GENERIC_MAPPINGS = {
                        "hot dog": "pao hot dog",
                        "hotdog": "pao hot dog",
                        "hamburguer": "pao hamburguer",
                        "hamburger": "pao hamburguer",
                        "lata": "cerveja lata 350ml",
                        "garrafa": "cerveja garrafa 600ml"
                    }
                    search_term = GENERIC_MAPPINGS.get(mensagem_lower)

                if search_term and len(mensagem_lower) < 30:
                    logger.info(f"🔄 Fallback DESLIZANTE: '{mensagem_lower}' + Contexto '{prefixo_contexto}' → buscando '{search_term}'")
                    try:
                        from tools.http_tools import estoque_preco
                        from tools.db_vector_search import search_products_vector
                        
                        # Buscar o produto
                        ean_result = search_products_vector(search_term, limit=5)
                        
                        # Extrair primeiro EAN válido
                        ean_match = re.search(r'^\d+\) (\d+) - (.+)$', ean_result, re.MULTILINE)
                        if ean_match:
                            ean = ean_match.group(1)
                            nome = ean_match.group(2).strip()
                            
                            # Buscar preço
                            preco_result = estoque_preco(ean)
                            
                            # Extrair preço do resultado
                            preco_match = re.search(r'R\$\s*([\d,.]+)', preco_result)
                            if preco_match:
                                preco = preco_match.group(0)
                                output = f"O {nome.split()[0]} de {mensagem_lower} está {preco}. Adiciono ao carrinho?"
                                logger.info(f"✅ Fallback deslizante sucesso: {output}")
                            else:
                                output = f"Encontrei {nome}. Quer que eu adicione ao carrinho?"
                        else:
                            output = "Desculpe, não consegui processar sua solicitação. Pode repetir?"
                            logger.warning("⚠️ Fallback contextual: não encontrou EAN")
                    except Exception as e:
                        logger.error(f"❌ Erro no fallback contextual: {e}")
                        output = "Desculpe, não consegui processar sua solicitação. Pode repetir?"
                else:
                    output = "Desculpe, não consegui processar sua solicitação. Pode repetir?"
                    logger.warning("⚠️ Resposta vazia do LLM, usando fallback genérico")
        
        logger.info("✅ Agente executado")
        logger.info(f"💬 RESPOSTA: {output[:200]}{'...' if len(output) > 200 else ''}")
        
        # 5. Salvar histórico (IA)
        if history_handler:
            try:
                history_handler.add_ai_message(output)
            except Exception as e:
                logger.error(f"Erro DB AI: {e}")

        return {"output": output, "error": None}
        
    except Exception as e:
        logger.error(f"Falha agente: {e}", exc_info=True)
        return {"output": "Tive um problema técnico, tente novamente.", "error": str(e)}

def get_session_history(session_id: str) -> LimitedPostgresChatMessageHistory:
    return LimitedPostgresChatMessageHistory(
        connection_string=settings.postgres_connection_string,
        session_id=session_id,
        table_name=settings.postgres_table_name,
        max_messages=settings.postgres_message_limit
    )

run_agent = run_agent_langgraph
