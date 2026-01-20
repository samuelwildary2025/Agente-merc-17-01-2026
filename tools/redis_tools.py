"""
Ferramentas Redis para buffer de mensagens e cooldown
Apenas funcionalidades essenciais mantidas
"""
import redis
from typing import Optional, Dict, List, Tuple
from config.settings import settings
from config.logger import setup_logger

logger = setup_logger(__name__)

# Conexão global com Redis
_redis_client: Optional[redis.Redis] = None
# Buffer local em memória (fallback quando Redis não está disponível)
_local_buffer: Dict[str, List[str]] = {}


def get_redis_client() -> Optional[redis.Redis]:
    """
    Retorna a conexão com o Redis (singleton)
    """
    global _redis_client
    
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                db=settings.redis_db,
                password=settings.redis_password if settings.redis_password else None,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Testar conexão
            _redis_client.ping()
            logger.info(f"Conectado ao Redis: {settings.redis_host}:{settings.redis_port}")
        
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Erro ao conectar ao Redis: {e}")
            _redis_client = None
        
        except Exception as e:
            logger.error(f"Erro inesperado ao conectar ao Redis: {e}")
            _redis_client = None
    
    return _redis_client


# ============================================
# Buffer de mensagens (concatenação por janela)
# ============================================

def buffer_key(telefone: str) -> str:
    """Retorna a chave da lista de buffer de mensagens no Redis."""
    return f"msgbuf:{telefone}"


def push_message_to_buffer(telefone: str, mensagem: str, message_id: str = None, ttl_seconds: int = 300) -> bool:
    """
    Empilha a mensagem recebida em uma lista no Redis para o telefone.
    Salva como JSON {"text": "...", "mid": "..."} para preservar o ID.
    """
    client = get_redis_client()
    import json
    
    # Payload seguro
    payload = json.dumps({"text": mensagem, "mid": message_id})

    if client is None:
        # Fallback em memória
        msgs = _local_buffer.get(telefone)
        if msgs is None:
            _local_buffer[telefone] = [payload]
        else:
            msgs.append(payload)
        logger.info(f"[fallback] Mensagem empilhada em memória para {telefone}")
        return True

    key = buffer_key(telefone)
    try:
        client.rpush(key, payload)
        if client.ttl(key) in (-1, -2):
            client.expire(key, ttl_seconds)
        logger.info(f"Mensagem empilhada no buffer: {key}")
        return True
    except redis.exceptions.RedisError as e:
        logger.error(f"Erro ao empilhar mensagem no Redis: {e}")
        return False


def get_buffer_length(telefone: str) -> int:
    """Retorna o tamanho atual do buffer de mensagens para o telefone."""
    client = get_redis_client()
    if client is None:
        # Fallback em memória
        msgs = _local_buffer.get(telefone) or []
        return len(msgs)
    try:
        return int(client.llen(buffer_key(telefone)))
    except redis.exceptions.RedisError as e:
        logger.error(f"Erro ao consultar tamanho do buffer: {e}")
        return 0


def pop_all_messages(telefone: str) -> Tuple[List[str], Optional[str]]:
    """
    Obtém todas as mensagens do buffer e limpa a chave.
    Retorna (lista_de_textos, lista_de_mids).
    """
    client = get_redis_client()
    import json
    
    texts = []
    # mids (plural) para marcar todos como lidos
    
    if client is None:
        # Fallback em memória
        msgs_raw = _local_buffer.get(telefone) or []
        _local_buffer.pop(telefone, None)
    else:
        key = buffer_key(telefone)
        try:
            pipe = client.pipeline()
            pipe.lrange(key, 0, -1)
            pipe.delete(key)
            result = pipe.execute()
            msgs_raw = result[0] if result else []
        except redis.exceptions.RedisError as e:
            logger.error(f"Erro ao consumir buffer: {e}")
            return [], None

    mids = []
    
    # Processar payloads
    for raw in msgs_raw:
        try:
            # Tenta ler como JSON novo
            data = json.loads(raw)
            if isinstance(data, dict):
                txt = data.get("text", "")
                mid = data.get("mid")
                if txt: texts.append(txt)
                if mid: mids.append(mid)
            else:
                # String antiga ou inválida
                texts.append(str(raw))
        except:
            # Não é JSON, assume texto puro (retrocompatibilidade)
            texts.append(str(raw))
            
    logger.info(f"Buffer consumido para {telefone}: {len(texts)} mensagens. MIDs: {len(mids)}")
    return texts, mids


# ============================================
# Cooldown do agente (pausa de automação)
# ============================================

def cooldown_key(telefone: str) -> str:
    """Chave do cooldown no Redis."""
    return f"cooldown:{telefone}"


def set_agent_cooldown(telefone: str, ttl_seconds: int = 60) -> bool:
    """
    Define uma chave de cooldown para o telefone, pausando a automação.

    - Armazena valor "1" com TTL (padrão 60s).
    """
    client = get_redis_client()
    if client is None:
        # Fallback: não há persistência real, apenas log
        logger.warning(f"[fallback] Cooldown não persistido (Redis indisponível) para {telefone}")
        return False
    try:
        key = cooldown_key(telefone)
        client.set(key, "1", ex=ttl_seconds)
        logger.info(f"Cooldown definido para {telefone} por {ttl_seconds}s")
        return True
    except redis.exceptions.RedisError as e:
        logger.error(f"Erro ao definir cooldown: {e}")
        return False


def is_agent_in_cooldown(telefone: str) -> Tuple[bool, int]:
    """
    Verifica se há cooldown ativo e retorna (ativo, ttl_restante).
    """
    client = get_redis_client()
    if client is None:
        return (False, -1)
    try:
        key = cooldown_key(telefone)
        val = client.get(key)
        if val is None:
            return (False, -1)
        ttl = client.ttl(key)
        ttl = ttl if isinstance(ttl, int) else -1
        return (True, ttl)
    except redis.exceptions.RedisError as e:
        logger.error(f"Erro ao consultar cooldown: {e}")
        return (False, -1)


# ============================================
# Gerenciamento de Sessão de Pedidos
# ============================================

import json
from datetime import datetime

# Constantes de tempo (em segundos)
SESSION_TTL = 40 * 60  # 40 minutos para montar pedido
MODIFICATION_TTL = 15 * 60  # 15 minutos para alterar após envio


def order_session_key(telefone: str) -> str:
    """Chave da sessão de pedido no Redis."""
    return f"order_session:{telefone}"


def get_order_session(telefone: str) -> Optional[Dict]:
    """
    Retorna a sessão de pedido atual do cliente.
    
    Returns:
        Dict com campos:
        - status: 'building' (montando) ou 'sent' (enviado)
        - started_at: timestamp de início
        - sent_at: timestamp de envio (se enviado)
        - order_id: ID do pedido (se enviado)
    """
    client = get_redis_client()
    if client is None:
        return None
    
    try:
        key = order_session_key(telefone)
        data = client.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        logger.error(f"Erro ao obter sessão de pedido: {e}")
        return None


def start_order_session(telefone: str) -> bool:
    """
    Inicia uma nova sessão de pedido (status: building).
    TTL de 40 minutos.
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        key = order_session_key(telefone)
        session = {
            "status": "building",
            "started_at": datetime.now().isoformat(),
            "sent_at": None,
            "order_id": None
        }
        client.set(key, json.dumps(session), ex=SESSION_TTL)
        logger.info(f"📦 Nova sessão de pedido iniciada para {telefone} (TTL: {SESSION_TTL//60}min)")
        return True
    except Exception as e:
        logger.error(f"Erro ao iniciar sessão de pedido: {e}")
        return False


def mark_order_sent(telefone: str, order_id: str = None) -> bool:
    """
    Marca o pedido como enviado. 
    Atualiza TTL para 15 minutos (janela de alteração).
    Também marca flag de pedido completado (2h TTL) para evitar mensagem de "não finalizado".
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        key = order_session_key(telefone)
        session = get_order_session(telefone)
        
        if session is None:
            session = {"started_at": datetime.now().isoformat()}
        
        session["status"] = "sent"
        session["sent_at"] = datetime.now().isoformat()
        session["order_id"] = order_id
        
        client.set(key, json.dumps(session), ex=MODIFICATION_TTL)
        
        # Marcar que pedido foi completado (TTL 2 horas)
        # Isso evita a mensagem "pedido não finalizado" quando cliente voltar
        completed_key = f"order_completed:{telefone}"
        client.set(completed_key, "1", ex=7200)  # 2 horas
        
        logger.info(f"✅ Pedido marcado como enviado para {telefone} (TTL modificação: {MODIFICATION_TTL//60}min)")
        return True
    except Exception as e:
        logger.error(f"Erro ao marcar pedido como enviado: {e}")
        return False


def clear_order_session(telefone: str) -> bool:
    """Remove a sessão de pedido."""
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        client.delete(order_session_key(telefone))
        logger.info(f"🗑️ Sessão de pedido removida para {telefone}")
        return True
    except Exception as e:
        logger.error(f"Erro ao limpar sessão de pedido: {e}")
        return False


def get_order_context(telefone: str, mensagem: str = "") -> str:
    """
    Retorna o contexto de pedido para injetar no agente.
    
    Args:
        telefone: Número do cliente
        mensagem: Mensagem atual do cliente (para detectar saudações)
    
    Returns:
        String com instrução para o agente baseada no estado da sessão.
    """
    client = get_redis_client()
    session = get_order_session(telefone)
    
    # Detectar se é uma saudação/novo atendimento
    saudacoes = [
        "boa tarde", "boa noite", "bom dia", "boa", "olá", "ola", "oi", 
        "eae", "eai", "e ai", "oii", "oiee", "hello", "hi", "hey",
        "opa", "opaa", "fala", "salve", "blz", "beleza"
    ]
    msg_lower = mensagem.strip().lower()
    is_greeting = any(msg_lower.startswith(s) or msg_lower == s for s in saudacoes)
    
    # Chave para rastrear se o ÚLTIMO pedido foi finalizado
    completed_key = f"order_completed:{telefone}"
    
    if session is None:
        # Verificar se o último pedido foi finalizado
        was_completed = False
        if client:
            try:
                was_completed = client.get(completed_key) is not None
            except:
                pass
        
        # Iniciar nova sessão
        start_order_session(telefone)
        
        # Limpar flag de pedido completado para próximo ciclo
        if client and was_completed:
            try:
                client.delete(completed_key)
            except:
                pass
        
        if was_completed:
            # Pedido anterior FOI finalizado - iniciar novo normalmente
            return "[SESSÃO] Novo pedido iniciado. Cliente já fez pedido anteriormente."
        else:
            # Conversa nova ou sessão expirou SEM finalizar
            return "[SESSÃO] Nova conversa. Monte o pedido normalmente."
    
    status = session.get("status", "building")
    
    if status == "building":
        # Ainda montando pedido - renovar TTL
        refresh_session_ttl(telefone)
        return ""
    
    elif status == "sent":
        # Pedido já foi enviado - está na janela de modificação (15min)
        # MAS se cliente mandou saudação, ele quer NOVO pedido!
        if is_greeting:
            logger.info(f"🔄 Saudação detectada para {telefone} - iniciando NOVO pedido (limpando sessão anterior)")
            # Limpar sessão antiga e carrinho
            clear_order_session(telefone)
            clear_cart(telefone)
            start_order_session(telefone)
            return "[SESSÃO] Novo pedido iniciado. Cliente iniciou nova conversa com saudação."
        
        return "[SESSÃO] Pedido já enviado. Se cliente quiser adicionar algo, use alterar_tool."
    
    return ""


def check_can_modify_order(telefone: str) -> Tuple[bool, str]:
    """
    Verifica se o cliente pode modificar o pedido.
    
    Returns:
        (pode_modificar, mensagem_explicativa)
    """
    session = get_order_session(telefone)
    
    if session is None:
        return (False, "Nenhum pedido ativo. Será criado um novo.")
    
    status = session.get("status", "building")
    
    if status == "building":
        return (True, "Pedido ainda em montagem.")
    
    elif status == "sent":
        # Está na janela de 15min (Redis ainda tem a chave)
        return (True, "Pedido enviado recentemente. Pode alterar com alterar_tool.")
    
    return (False, "Sessão expirada. Novo pedido será criado.")


def refresh_session_ttl(telefone: str) -> bool:
    """
    Renova o TTL da sessão quando o cliente interage (se ainda em building).
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        session = get_order_session(telefone)
        if session and session.get("status") == "building":
            key = order_session_key(telefone)
            client.expire(key, SESSION_TTL)
            logger.debug(f"TTL da sessão renovado para {telefone}")
            return True
        return False
    except Exception as e:
        logger.error(f"Erro ao renovar TTL da sessão: {e}")
        return False


# ============================================
# Carrinho de Compras (Redis List)
# ============================================

def cart_key(telefone: str) -> str:
    """Chave da lista de itens do carrinho no Redis."""
    return f"cart:{telefone}"


def add_item_to_cart(telefone: str, item_json: str) -> bool:
    """
    Adiciona um item (JSON string) ao carrinho.
    Inicia sessão se não existir e renova TTL (40min).
    """
    client = get_redis_client()
    if client is None:
        return False

    try:
        # Garante que existe sessão ativa
        session = get_order_session(telefone)
        if not session or session.get("status") != "building":
            start_order_session(telefone)

        key = cart_key(telefone)
        # RPUSH adiciona ao final da lista
        client.rpush(key, item_json)
        
        # Renova TTL do carrinho e da sessão para 40min
        client.expire(key, SESSION_TTL)
        refresh_session_ttl(telefone)
        
        logger.info(f"🛒 Item adicionado ao carrinho de {telefone}")
        return True
    except Exception as e:
        logger.error(f"Erro ao adicionar item ao carrinho: {e}")
        return False


def get_cart_items(telefone: str) -> List[Dict]:
    """
    Retorna todos os itens do carrinho como lista de dicionários.
    """
    client = get_redis_client()
    if client is None:
        return []

    try:
        key = cart_key(telefone)
        # LRANGE 0 -1 pega toda a lista
        items_raw = client.lrange(key, 0, -1)
        
        items = []
        for raw in items_raw:
            try:
                if isinstance(raw, str):
                    items.append(json.loads(raw))
            except:
                continue
                
        return items
    except Exception as e:
        logger.error(f"Erro ao ler carrinho: {e}")
        return []


def remove_item_from_cart(telefone: str, index: int) -> bool:
    """
    Remove item pelo índice (0-based).
    NOTA: Redis Lists não são ideais para remover por índice concorrente, 
    mas para este caso de uso simples (1 usuário), funciona usando LSET + LREM 
    ou apenas recriando a lista.
    
    Abordagem segura: Ler tudo, remover no python, reescrever.
    """
    client = get_redis_client()
    if client is None:
        return False

    try:
        key = cart_key(telefone)
        items = client.lrange(key, 0, -1)
        
        if 0 <= index < len(items):
            # Elemento placeholder para marcar remoção
            deleted_marker = "__DELETED__"
            client.lset(key, index, deleted_marker)
            client.lrem(key, 0, deleted_marker)
            return True
            
        return False
    except Exception as e:
        logger.error(f"Erro ao remover item do carrinho: {e}")
        return False


def clear_cart(telefone: str) -> bool:
    """Remove todo o carrinho."""
    client = get_redis_client()
    if client is None:
        return False

    try:
        client.delete(cart_key(telefone))
        logger.info(f"🛒 Carrinho limpo para {telefone}")
        return True
    except Exception as e:
        logger.error(f"Erro ao limpar carrinho: {e}")
        return False


# ============================================
# Comprovante PIX (Receipt URL Storage)
# ============================================

def comprovante_key(telefone: str) -> str:
    """Chave para armazenar URL do comprovante PIX."""
    return f"comprovante:{telefone}"


def set_comprovante(telefone: str, url: str) -> bool:
    """
    Salva a URL do comprovante PIX do cliente.
    TTL de 2 horas (mesmo período que sessão de pedido).
    
    Args:
        telefone: Número do cliente
        url: URL da imagem do comprovante
    
    Returns:
        True se salvo com sucesso
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        key = comprovante_key(telefone)
        client.set(key, url, ex=7200)  # 2 horas
        logger.info(f"🧾 Comprovante PIX salvo para {telefone}: {url[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar comprovante: {e}")
        return False


def get_comprovante(telefone: str) -> Optional[str]:
    """
    Recupera a URL do comprovante PIX do cliente.
    
    Returns:
        URL do comprovante ou None
    """
    client = get_redis_client()
    if client is None:
        return None
    
    try:
        key = comprovante_key(telefone)
        url = client.get(key)
        if url:
            logger.info(f"🧾 Comprovante recuperado para {telefone}")
        return url
    except Exception as e:
        logger.error(f"Erro ao recuperar comprovante: {e}")
        return None


def clear_comprovante(telefone: str) -> bool:
    """Remove o comprovante do cliente (após finalizar pedido)."""
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        client.delete(comprovante_key(telefone))
        logger.info(f"🧾 Comprovante limpo para {telefone}")
        return True
        return False

# ============================================
# Endereço do Cliente (Persistence)
# ============================================

def address_key(telefone: str) -> str:
    """Chave para armazenar endereço do cliente temporariamente."""
    return f"address:{telefone}"


def set_address(telefone: str, endereco: str) -> bool:
    """
    Salva o endereço do cliente.
    TTL de 2 horas.
    """
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        key = address_key(telefone)
        client.set(key, endereco, ex=7200)  # 2 horas
        logger.info(f"🏠 Endereço salvo para {telefone}: {endereco[:50]}...")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar endereço: {e}")
        return False


def get_address(telefone: str) -> Optional[str]:
    """Recupera o endereço salvo do cliente."""
    client = get_redis_client()
    if client is None:
        return None
    
    try:
        key = address_key(telefone)
        addr = client.get(key)
        if addr:
            logger.info(f"🏠 Endereço recuperado para {telefone}")
        return addr
    except Exception as e:
        logger.error(f"Erro ao recuperar endereço: {e}")
        return None


def clear_address(telefone: str) -> bool:
    """Remove o endereço salvo."""
    client = get_redis_client()
    if client is None:
        return False
    
    try:
        client.delete(address_key(telefone))
        logger.info(f"🏠 Endereço limpo para {telefone}")
        return True
    except Exception as e:
        logger.error(f"Erro ao limpar endereço: {e}")
        return False