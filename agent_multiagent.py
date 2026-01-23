"""
Agente de IA Multi-Agente para Atendimento de Supermercado usando LangGraph
Arquitetura: Orquestrador + Vendedor + Caixa

Versão 5.0 - Multi-Agent Architecture
"""

from typing import Dict, Any, TypedDict, Annotated, List, Literal
import re
import operator
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from pathlib import Path
import json

from config.settings import settings
from config.logger import setup_logger
from tools.http_tools import estoque, pedidos, alterar, ean_lookup, estoque_preco, consultar_encarte
from tools.search_agent import analista_produtos_tool
from tools.time_tool import get_current_time, search_message_history
from tools.redis_tools import (
    mark_order_sent, 
    add_item_to_cart, 
    get_cart_items, 
    remove_item_from_cart, 
    clear_cart,
    set_comprovante,
    get_comprovante,
    clear_comprovante,
    get_saved_address,
    save_address,
    get_order_session
)
from memory.limited_postgres_memory import LimitedPostgresChatMessageHistory

logger = setup_logger(__name__)

# ============================================
# Estado Compartilhado do Grafo
# ============================================

def add_messages(left: list, right: list) -> list:
    """Função para combinar listas de mensagens."""
    return left + right

class AgentState(TypedDict):
    """Estado compartilhado entre os agentes."""
    messages: Annotated[list, add_messages]
    current_agent: str  # "orchestrator" | "vendedor" | "caixa"
    intent: str  # "vendas" | "checkout" | "unknown"
    phone: str
    final_response: str  # Resposta final para o cliente

# ============================================
# Definição das Ferramentas (Separadas por Agente)
# ============================================

# --- FERRAMENTAS DO VENDEDOR ---

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
    
    if unidades > 0:
        peso_unitario = None
        for key, weight in WEIGHT_RULES.items():
            if key in prod_lower:
                peso_unitario = weight
                break
        
        if peso_unitario:
            novo_peso = round(unidades * peso_unitario, 3)
            if quantidade <= 0 or abs(quantidade - novo_peso) > 0.5:
                quantidade = novo_peso
                logger.info(f"⚖️ [ADD_ITEM] Peso calculado: {unidades} unidades × {peso_unitario}kg = {quantidade}kg")
    
    # Construir JSON do item para add_item_to_cart
    import json
    item_data = {
        "produto": produto,
        "quantidade": quantidade,
        "observacao": observacao,
        "preco": preco,
        "unidades": unidades
    }
    item_json = json.dumps(item_data, ensure_ascii=False)
    
    success = add_item_to_cart(telefone, item_json)
    if success:
        if unidades > 0:
            # Calcular valor estimado TOTAL para ajudar o LLM
            valor_estimado = quantidade * preco
            return f"✅ Adicionado: {unidades}x {produto} - Total Estimado: R$ {valor_estimado:.2f}. (IMPORTANTE: Avise que o valor final pode variar na balança pois é item de peso)"
        else:
            qtd_int = int(quantidade) if quantidade == int(quantidade) else quantidade
            valor_total = quantidade * preco
            return f"✅ Adicionado: {qtd_int}x {produto} - Total: R$ {valor_total:.2f}"
    return "❌ Erro ao adicionar item."

@tool
def view_cart_tool(telefone: str) -> str:
    """Ver os itens atuais no carrinho do cliente."""
    items = get_cart_items(telefone)
    if not items:
        return "🛒 Carrinho vazio."
    
    lines = ["🛒 **Carrinho atual:**"]
    total = 0.0
    for i, item in enumerate(items, 1):
        nome = item.get("produto", "Item")
        qtd = item.get("quantidade", 1)
        preco = item.get("preco", 0)
        unidades = item.get("unidades", 0)
        
        valor = preco * qtd
        total += valor
        
        if unidades > 0:
            lines.append(f"{i}. {unidades}x {nome} - Total Estimado: R$ {valor:.2f}")
        else:
            qtd_display = int(qtd) if qtd == int(qtd) else qtd
            lines.append(f"{i}. {qtd_display}x {nome} - R$ {valor:.2f}")
    
    lines.append(f"\n**Subtotal:** R$ {total:.2f}")
    return "\n".join(lines)

@tool
def remove_item_tool(telefone: str, item_index: int) -> str:
    """
    Remover um item do carrinho pelo número (índice 1-based, como mostrado no view_cart).
    Ex: Para remover o item 1, passe 1.
    """
    success = remove_item_from_cart(telefone, item_index)
    if success:
        return f"✅ Item {item_index} removido do carrinho."
    return f"❌ Erro: Item {item_index} não encontrado."

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
    [VENDEDOR -> ANALISTA]
    Ponte para o Analista de Produtos.
    O Vendedor envia o texto cru do cliente (ex: "arroz, leite"), e o Analista retorna os produtos validados com EAN.
    
    Args:
        produtos: Termos de busca.
    """
    if not produtos or not produtos.strip():
        return "❌ Informe os produtos para o analista."
        
    return analista_produtos_tool(produtos)

@tool
def consultar_encarte_tool() -> str:
    """
    Consulta o encarte (folheto de ofertas) atual do supermercado.
    Use APENAS se o cliente perguntar explicitamente sobre ofertas, promoções ou encarte.
    
    Returns:
        JSON com a URL (campo encarte_url) ou lista de URLs (campo active_encartes_urls) das imagens.
    """
    return consultar_encarte()

# --- FERRAMENTAS DO CAIXA ---

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
def salvar_endereco_tool(telefone: str, endereco: str) -> str:
    """
    Salva o endereço do cliente para usar depois no fechamento do pedido.
    Use IMEDIATAMENTE quando o cliente informar o endereço (mesmo no início da conversa).
    """
    if save_address(telefone, endereco):
        return f"✅ Endereço salvo: {endereco}"
    return "❌ Erro ao salvar endereço."

@tool
def finalizar_pedido_tool(cliente: str, telefone: str, endereco: str, forma_pagamento: str, observacao: str = "", comprovante: str = "", taxa_entrega: float = 0.0) -> str:
    """
    Finalizar o pedido usando os itens que estão no carrinho.
    Use quando o cliente confirmar que quer fechar a compra.
    
    Args:
    - cliente: Nome do cliente
    - telefone: Telefone (com DDD)
    - endereco: Endereço de entrega completo
    - forma_pagamento: Pix, Cartão ou Dinheiro
    - observacao: Observações extras (troco, etc)
    - comprovante: URL do comprovante PIX (se houver)
    - taxa_entrega: Valor da taxa de entrega em reais (opcional, padrão 0)
    """
    import json as json_lib
    
    items = get_cart_items(telefone)
    if not items:
        return "❌ O carrinho está vazio! Adicione produtos antes de finalizar."
    
    comprovante_salvo = get_comprovante(telefone)
    comprovante_final = comprovante or comprovante_salvo or ""
    
    total = 0.0
    itens_formatados = []
    
    for item in items:
        preco = item.get("preco", 0.0)
        quantidade = item.get("quantidade", 1.0)
        unidades = item.get("unidades", 0)
        obs_item = item.get("observacao", "")
        total += preco * quantidade
        
        nome_produto = item.get("produto", item.get("nome_produto", "Produto"))
        
        if unidades > 0:
            qtd_api = unidades
            valor_estimado = round(preco * quantidade, 2)
            preco_unitario_api = round(valor_estimado / unidades, 2)
            obs_peso = f"Peso estimado: {quantidade:.3f}kg (~R${valor_estimado:.2f}). PESAR para confirmar valor."
            if obs_item:
                obs_item = f"{obs_item}. {obs_peso}"
            else:
                obs_item = obs_peso
        else:
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
    
    if taxa_entrega > 0:
        itens_formatados.append({
            "nome_produto": "TAXA DE ENTREGA",
            "quantidade": 1,
            "preco_unitario": round(taxa_entrega, 2),
            "observacao": ""
        })
        total += taxa_entrega
        
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
    
    result = pedidos(json_body)
    
    if "sucesso" in result.lower() or "✅" in result:
        # NÃO LIMPAR O CARRINHO AQUI!
        # O carrinho deve persistir por 15 minutos (TTL do Redis) para permitir alterações.
        # clear_cart(telefone) -> REMOVIDO
        
        # O comprovante pode ser limpo ou não? Melhor manter por segurança, mas o pedido já foi.
        # clear_comprovante(telefone) -> REMOVIDO (TTL cuida disso)
        
        mark_order_sent(telefone, result) # Atualiza o status da sessão para 'sent'
        
        return f"{result}\n\n💰 **Valor Total Processado:** R$ {total:.2f}\n(O agente DEVE usar este valor na resposta)"
        
    return result

# --- FERRAMENTAS COMPARTILHADAS ---

@tool
def time_tool() -> str:
    """Retorna a data e hora atual."""
    return get_current_time()

@tool
def search_history_tool(telefone: str, keyword: str = None) -> str:
    """Busca mensagens anteriores do cliente com horários."""
    return search_message_history(telefone, keyword)

# ============================================
# Listas de Ferramentas por Agente
# ============================================

VENDEDOR_TOOLS = [
    # ean_tool_alias, -> Removido: Use busca_lote (Analista)
    # estoque_preco_alias, -> Removido: Use busca_lote (Analista)
    busca_lote_tool,
    # estoque_tool, -> (Já estava encapsulado na busca_lote, confirmando remoção completa do acesso direto)
    add_item_tool,
    view_cart_tool,
    remove_item_tool,
    consultar_encarte_tool,
    time_tool,
    search_history_tool,
]

CAIXA_TOOLS = [
    view_cart_tool,
    calcular_total_tool,
    finalizar_pedido_tool,
    salvar_endereco_tool,
    time_tool,
]

# ============================================
# Funções de Carregamento de Prompts
# ============================================

def load_prompt(filename: str) -> str:
    """Carrega um prompt do diretório prompts/"""
    base_dir = Path(__file__).resolve().parent
    prompt_path = base_dir / "prompts" / filename
    
    logger.info(f"📄 Carregando prompt: {prompt_path}")
    
    try:
        text = prompt_path.read_text(encoding="utf-8")
        text = text.replace("{base_url}", settings.supermercado_base_url)
        text = text.replace("{ean_base}", settings.estoque_ean_base_url)
        return text
    except Exception as e:
        logger.error(f"Falha ao carregar prompt {filename}: {e}")
        raise

# ============================================
# Construção dos LLMs
# ============================================

def _build_llm(temperature: float = 0.0, model_override: str = None):
    """Constrói um LLM baseado nas configurações."""
    model = model_override or getattr(settings, "llm_model", "gemini-2.5-flash")
    provider = getattr(settings, "llm_provider", "google")
    
    if provider == "google":
        logger.debug(f"🚀 Usando Google Gemini: {model}")
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=temperature,
        )
    else:
        logger.debug(f"🚀 Usando OpenAI (compatível): {model}")
        
        client_kwargs = {}
        if settings.openai_api_base:
            client_kwargs["base_url"] = settings.openai_api_base

        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            temperature=temperature,
            **client_kwargs
        )

def _build_fast_llm():
    """Constrói um LLM rápido e leve para o Orquestrador."""
    # Usa o mesmo modelo mas com temperatura 0 para determinismo
    return _build_llm(temperature=0.0)

# ============================================
# Nós do Grafo (Agentes)
# ============================================

def orchestrator_node(state: AgentState) -> dict:
    """
    Nó Orquestrador: Classifica a intenção e roteia para o agente correto.
    Usa um prompt ultra-leve (~150 tokens).
    """
    logger.info("🧠 [ORCHESTRATOR] Analisando intenção...")
    
    llm = _build_fast_llm()
    prompt = load_prompt("orchestrator.md")
    
    # Pegar apenas a última mensagem do cliente para classificação
    last_user_message = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Limpar tags de contexto
            content = re.sub(r'\[TELEFONE_CLIENTE:.*?\]', '', content)
            content = re.sub(r'\[HORÁRIO_ATUAL:.*?\]', '', content)
            content = re.sub(r'\[URL_IMAGEM:.*?\]', '', content)
            last_user_message = content.strip()
            break
    
    if not last_user_message:
        logger.warning("⚠️ [ORCHESTRATOR] Nenhuma mensagem do usuário encontrada")
        return {"intent": "vendas", "current_agent": "vendedor"}
    
    # Invocar o LLM para classificar
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=last_user_message)
    ]
    
    try:
        response = llm.invoke(messages)
        intent_raw = response.content.strip().lower()
        
        # Normalizar resposta
        if "checkout" in intent_raw or "caixa" in intent_raw:
            intent = "checkout"
        else:
            intent = "vendas"
        
        logger.info(f"🧠 [ORCHESTRATOR] Intenção detectada: {intent} (raw: '{intent_raw}')")
        
        new_agent = "caixa" if intent == "checkout" else "vendedor"
        
        return {
            "intent": intent,
            "current_agent": new_agent
        }
        
    except Exception as e:
        logger.error(f"❌ [ORCHESTRATOR] Erro: {e}")
        return {"intent": "vendas", "current_agent": "vendedor"}


def vendedor_node(state: AgentState) -> dict:
    """
    Nó Vendedor: Agente especializado em vendas com prompt completo.
    """
    logger.info("👩‍💼 [VENDEDOR] Processando...")
    
    prompt = load_prompt("vendedor.md")
    llm = _build_llm()
    
    # Criar agente ReAct com as ferramentas do vendedor
    agent = create_react_agent(llm, VENDEDOR_TOOLS, prompt=prompt)
    
    # Configuração
    config = {
        "configurable": {"thread_id": state["phone"]},
        "recursion_limit": 15
    }
    
    # Executar
    result = agent.invoke({"messages": state["messages"]}, config)
    
    # Extrair resposta
    response = _extract_response(result)

    # --- TRAVA DE ALUCINAÇÃO (SAFETY CHECK) ---
    # Verifica se o agente disse que adicionou, mas NÃO chamou a tool
    if "adicionei" in response.lower() or "adicionado" in response.lower():
        tool_called = False
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                for call in msg.tool_calls:
                    if call['name'] == 'add_item_tool':
                        tool_called = True
                        break
            if tool_called: break
        
        if not tool_called:
            logger.warning("⚠️ ALUCINAÇÃO DETECTADA: Agente disse que adicionou mas não chamou a tool.")
            # Forçar uma resposta de erro para o próprio agente corrigir
            response = "❌ ERRO DE SISTEMA: Você disse que adicionou, mas NENHUM item foi registrado no carrinho. Você DEVE chamar `add_item_tool` com os argumentos corretos agora. Tente novamente."
            # Opcional: Poderíamos retentar automaticamente, mas por enquanto vamos alterar a resposta final para o usuário não ser enganado
            # Ou melhor: vamos injetar essa mensagem como se fosse o sistema e rodar de novo (loop).
            # Para simplificar na V5, vamos apenas alterar a resposta final alertando o erro.
            response = "Desculpe, tive um erro técnico ao salvar no carrinho. Vou tentar novamente. O que você pediu mesmo?"

    logger.info(f"👩‍💼 [VENDEDOR] Resposta: {response[:100]}...")
    
    return {
        "final_response": response,
        "messages": result.get("messages", [])[-1:] if result.get("messages") else []
    }


def caixa_node(state: AgentState) -> dict:
    """
    Nó Caixa: Agente especializado em checkout com prompt enxuto.
    """
    logger.info("💰 [CAIXA] Processando...")
    
    prompt = load_prompt("caixa.md")
    llm = _build_llm()
    
    # Criar agente ReAct com as ferramentas do caixa
    agent = create_react_agent(llm, CAIXA_TOOLS, prompt=prompt)
    
    # Configuração
    config = {
        "configurable": {"thread_id": state["phone"]},
        "recursion_limit": 10  # Limite menor, operações mais simples
    }
    
    # Executar
    result = agent.invoke({"messages": state["messages"]}, config)
    
    # Extrair resposta
    response = _extract_response(result)
    
    # Verificar se o cliente quer voltar ao vendedor
    if "para alterar itens" in response.lower() or "mudar o pedido" in response.lower():
        logger.info("💰 [CAIXA] Cliente quer alterar → Devolvendo para Orquestrador")
        return {
            "final_response": response,
            "current_agent": "orchestrator",
            "messages": result.get("messages", [])[-1:] if result.get("messages") else []
        }
    
    logger.info(f"💰 [CAIXA] Resposta: {response[:100]}...")
    
    return {
        "final_response": response,
        "messages": result.get("messages", [])[-1:] if result.get("messages") else []
    }


def _extract_response(result: dict) -> str:
    """Extrai a resposta textual do resultado do agente."""
    if not result or "messages" not in result:
        return "Desculpe, tive um problema. Pode repetir?"
    
    messages = result["messages"]
    
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            continue
        
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        
        if not content or not content.strip():
            continue
        
        if content.strip().startswith(("[", "{")):
            continue
        
        return content
    
    return "Desculpe, não consegui processar. Pode repetir?"

# ============================================
# Roteamento
# ============================================

def route_by_intent(state: AgentState) -> Literal["vendedor", "caixa"]:
    """Decide para qual agente rotear baseado na intenção."""
    intent = state.get("intent", "vendas")
    
    if intent == "checkout":
        return "caixa"
    return "vendedor"

def route_from_caixa(state: AgentState) -> Literal["end", "orchestrator"]:
    """
    Decide se o caixa finaliza ou devolve para o orquestrador.
    """
    # Se o nó caixa definiu 'current_agent' como 'orchestrator', voltamos
    current = state.get("current_agent", "caixa")
    if current == "orchestrator":
        return "orchestrator"
    
    return "end"

# ============================================
# Construção do Grafo
# ============================================

def build_multi_agent_graph():
    """Constrói o StateGraph com a arquitetura de 3 agentes."""
    
    graph = StateGraph(AgentState)
    
    # Adicionar nós
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("vendedor", vendedor_node)
    graph.add_node("caixa", caixa_node)
    
    # Fluxo: START → Orquestrador
    graph.add_edge(START, "orchestrator")
    
    # Orquestrador decide para onde ir
    graph.add_conditional_edges(
        "orchestrator",
        route_by_intent,
        {
            "vendedor": "vendedor",
            "caixa": "caixa"
        }
    )
    
    # Vendedor termina (mas poderia loopar se quisesse, por enquanto mantemos simples)
    graph.add_edge("vendedor", END)
    
    # Caixa pode terminar ou voltar
    graph.add_conditional_edges(
        "caixa",
        route_from_caixa,
        {
            "end": END,
            "orchestrator": "orchestrator"
        }
    )
    
    # Compilar
    memory = MemorySaver()
    return graph.compile(checkpointer=memory)

# ============================================
# Cache do Grafo
# ============================================

_multi_agent_graph = None

def get_multi_agent_graph():
    """Retorna o grafo multi-agente (com cache)."""
    global _multi_agent_graph
    if _multi_agent_graph is None:
        _multi_agent_graph = build_multi_agent_graph()
    return _multi_agent_graph

# ============================================
# Função Principal
# ============================================

def run_agent_langgraph(telefone: str, mensagem: str) -> Dict[str, Any]:
    """
    Executa o agente multi-agente. Suporta texto e imagem (via tag [MEDIA_URL: ...]).
    """
    logger.info(f"[MULTI-AGENT] Telefone: {telefone} | Msg: {mensagem[:50]}...")
    
    # 1. Extrair URL de imagem se houver
    image_url = None
    clean_message = mensagem
    
    media_match = re.search(r"\[MEDIA_URL:\s*(.*?)\]", mensagem)
    if media_match:
        image_url = media_match.group(1)
        clean_message = mensagem.replace(media_match.group(0), "").strip()
        if not clean_message:
            clean_message = "Analise esta imagem/comprovante enviada."
        logger.info(f"📸 Mídia detectada: {image_url}")

    # 2. Carregar histórico
    history_handler = None
    previous_messages: List[BaseMessage] = []
    try:
        history_handler = get_session_history(telefone)
        previous_messages = history_handler.messages
        logger.info(f"📚 Histórico: {len(previous_messages)} mensagens anteriores")
        history_handler.add_user_message(mensagem)
    except Exception as e:
        logger.error(f"Erro DB User: {e}")

    try:
        graph = get_multi_agent_graph()
        
        # 3. Construir mensagem com contexto
        from tools.time_tool import get_current_time
        hora_atual = get_current_time()
        contexto = f"[TELEFONE_CLIENTE: {telefone}]\n[HORÁRIO_ATUAL: {hora_atual}]\n"
        
        if image_url:
            contexto += f"[URL_IMAGEM: {image_url}]\n"
        
        # Expansão de mensagens curtas
        mensagem_expandida = clean_message
        msg_lower = clean_message.lower().strip()
        
        if msg_lower in ["sim", "s", "ok", "pode", "isso", "quero", "beleza", "blz", "bora", "vamos"]:
            ultima_pergunta_ia = ""
            for msg in reversed(previous_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if content.strip() and not content.startswith("["):
                        ultima_pergunta_ia = content[:200]
                        break
            
            if ultima_pergunta_ia:
                mensagem_expandida = f"O cliente respondeu '{clean_message}' CONFIRMANDO. Sua mensagem anterior foi: \"{ultima_pergunta_ia}...\". Se você sugeriu produtos com preços, VOCÊ DEVE CHAMAR add_item_tool AGORA para cada produto sugerido usando os dados (EAN, nome, preço) que você já tem do contexto anterior."
                logger.info(f"🔄 Mensagem curta expandida: '{clean_message}'")
        elif msg_lower in ["nao", "não", "n", "nope", "nao quero", "não quero"]:
            mensagem_expandida = f"O cliente respondeu '{clean_message}' (NEGATIVO). Pergunte se precisa de mais alguma coisa."
        
        contexto += "\n"
        
        # Construir mensagem (multimodal se tiver imagem)
        if image_url:
            message_content = [
                {"type": "text", "text": contexto + mensagem_expandida},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
            current_message = HumanMessage(content=message_content)
        else:
            current_message = HumanMessage(content=contexto + mensagem_expandida)

        # 4. Montar estado inicial
        all_messages = list(previous_messages) + [current_message]
        
        initial_state = {
            "messages": all_messages,
            "current_agent": "orchestrator",
            "intent": "unknown",
            "phone": telefone,
            "final_response": ""
        }
        
        logger.info(f"📨 Enviando {len(all_messages)} mensagens para o grafo")
        
        config = {"configurable": {"thread_id": telefone}}
        
        # 5. Executar o grafo
        result = graph.invoke(initial_state, config)
        
        # 6. Extrair resposta final
        output = result.get("final_response", "")
        
        if not output or not output.strip():
            logger.warning("⚠️ Resposta vazia, tentando extrair das mensagens")
            output = _extract_response({"messages": result.get("messages", [])})
        
        if not output or not output.strip():
            output = "Desculpe, tive um problema ao processar. Pode repetir por favor?"
        
        logger.info(f"✅ [MULTI-AGENT] Resposta: {output[:200]}...")
        
        # 7. Salvar histórico (IA)
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

# Alias para compatibilidade
run_agent = run_agent_langgraph
