"""
Ferramentas HTTP para interação com a API do Supermercado
"""
import requests
import json
from typing import Dict, Any
from config.settings import settings
from config.logger import setup_logger
from .db_vector_search import search_products_vector

logger = setup_logger(__name__)


def get_auth_headers() -> Dict[str, str]:
    """Retorna os headers de autenticação para as requisições"""
    token = settings.supermercado_auth_token or ""
    
    # Fallback: Tentar ler TOKEN_SUPERMERCADO direto do environment caso o settings esteja vazio
    # (Caso o usuário tenha nomeado diferente no .env)
    if not token or len(token) < 10:
        import os
        from dotenv import load_dotenv
        
        # FORÇAR recarregamento do .env para pegar mudanças sem reiniciar servidor
        load_dotenv(override=True)
        
        token_env = os.getenv("TOKEN_SUPERMERCADO", "")
        if token_env:
            logger.info("⚠️ Usando TOKEN_SUPERMERCADO do env (fallback reload)")
            token = token_env
        else:
             # Tentar SUPERMERCADO_AUTH_TOKEN direto também
            token = os.getenv("SUPERMERCADO_AUTH_TOKEN", token)

    # Garantir que o token tenha o prefixo Bearer se não tiver
    if token and not token.strip().lower().startswith("bearer"):
        token = f"Bearer {token.strip()}"
    
    # DEBUG: Verificar formato do token (mascarado)
    safe_token = f"{token[:15]}...{token[-5:]}" if len(token) > 20 else "CURTO/VAZIO"
    logger.info(f"🔑 Auth Header gerado: {safe_token}")
        
    return {
        "Authorization": token,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }


def estoque(url: str) -> str:
    """
    Consulta o estoque e preço de produtos no sistema do supermercado.
    
    Args:
        url: URL completa para consulta (ex: .../api/produtos/consulta?nome=arroz)
    
    Returns:
        JSON string com informações do produto ou mensagem de erro
    """
    logger.info(f"Consultando estoque: {url}")
    
    try:
        response = requests.get(
            url,
            headers=get_auth_headers(),
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        
        # OTIMIZAÇÃO DE TOKENS: Filtrar apenas campos essenciais
        # A API retorna muitos dados inúteis (impostos, ncm, ids internos)
        # que gastam tokens desnecessariamente.
        def _filter_product(prod: Dict[str, Any]) -> Dict[str, Any]:
            keys_to_keep = [
                "id", "produto", "nome", "descricao", 
                "preco", "preco_venda", "valor", "valor_unitario",
                "estoque", "quantidade", "saldo", "disponivel"
            ]
            clean = {}
            for k, v in prod.items():
                if k.lower() in keys_to_keep or any(x in k.lower() for x in ["preco", "valor", "estoque"]):
                     # Ignora campos de imposto/fiscal mesmo se tiver palavras chave
                    if any(x in k.lower() for x in ["trib", "ncm", "fiscal", "custo", "margem"]):
                        continue
                    clean[k] = v
            return clean

        if isinstance(data, list):
            filtered_data = [_filter_product(p) for p in data]
        elif isinstance(data, dict):
            filtered_data = _filter_product(data)
        else:
            filtered_data = data
            
        logger.info(f"Estoque consultado com sucesso: {len(data) if isinstance(data, list) else 1} produto(s)")
        
        return json.dumps(filtered_data, indent=2, ensure_ascii=False)
    
    except requests.exceptions.Timeout:
        error_msg = "Erro: Timeout ao consultar estoque. Tente novamente."
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.HTTPError as e:
        error_msg = f"Erro HTTP ao consultar estoque: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Erro ao consultar estoque: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    except json.JSONDecodeError:
        error_msg = "Erro: Resposta da API não é um JSON válido."
        logger.error(error_msg)
        return error_msg


def pedidos(json_body: str) -> str:
    """
    Envia um pedido finalizado para o painel dos funcionários (dashboard).
    
    Args:
        json_body: JSON string com os detalhes do pedido
                   Exemplo: '{"cliente": "João", "itens": [{"produto": "Arroz", "quantidade": 1}]}'
    
    Returns:
        Mensagem de sucesso com resposta do servidor ou mensagem de erro
    """
    # Remove trailing slashed from base and from endpoint to ensure correct path
    base = settings.supermercado_base_url.rstrip("/")
    url = f"{base}/pedidos/"  # Barra final necessária para FastAPI
    logger.info(f"Enviando pedido para: {url}")
    
    # DEBUG: Log token being used (only first/last 4 chars for security)
    token = settings.supermercado_auth_token or ""
    token_preview = f"{token[:12]}...{token[-4:]}" if len(token) > 16 else token
    logger.info(f"🔑 Token usado: {token_preview}")
    
    try:
        # Validar JSON
        data = json.loads(json_body)
        logger.debug(f"Dados do pedido: {data}")
        
        response = requests.post(
            url,
            headers=get_auth_headers(),
            json=data,
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        success_msg = f"✅ Pedido enviado com sucesso!\n\nResposta do servidor:\n{json.dumps(result, indent=2, ensure_ascii=False)}"
        logger.info("Pedido enviado com sucesso")
        
        return success_msg
    
    except json.JSONDecodeError:
        error_msg = "Erro: O corpo da requisição não é um JSON válido."
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.Timeout:
        error_msg = "Erro: Timeout ao enviar pedido. Tente novamente."
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.HTTPError as e:
        error_msg = f"Erro HTTP ao enviar pedido: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Erro ao enviar pedido: {str(e)}"
        logger.error(error_msg)
        return error_msg


def alterar(telefone: str, json_body: str) -> str:
    """
    Atualiza um pedido existente no painel dos funcionários (dashboard).
    
    Args:
        telefone: Telefone do cliente para identificar o pedido
        json_body: JSON string com os dados a serem atualizados
    
    Returns:
        Mensagem de sucesso com resposta do servidor ou mensagem de erro
    """
    # Remove caracteres não numéricos do telefone
    telefone_limpo = "".join(filter(str.isdigit, telefone))
    url = f"{settings.supermercado_base_url}/pedidos/telefone/{telefone_limpo}"
    
    logger.info(f"Atualizando pedido para telefone: {telefone_limpo}")
    
    try:
        # Validar JSON
        data = json.loads(json_body)
        logger.debug(f"Dados de atualização: {data}")
        
        response = requests.put(
            url,
            headers=get_auth_headers(),
            json=data,
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        success_msg = f"✅ Pedido atualizado com sucesso!\n\nResposta do servidor:\n{json.dumps(result, indent=2, ensure_ascii=False)}"
        logger.info("Pedido atualizado com sucesso")
        
        return success_msg
    
    except json.JSONDecodeError:
        error_msg = "Erro: O corpo da requisição não é um JSON válido."
        logger.error(error_msg)
        return error_msg


def ean_lookup(query: str) -> str:
    """
    Busca informações/EAN do produto via busca vetorial (pgvector + OpenAI embeddings).

    Args:
        query: Texto com o nome/descrição do produto ou entrada de chat.

    Returns:
        String com lista de EANs encontrados ou mensagem de erro.
    """
    logger.info(f"🔍 [VECTOR] Consultando pgvector: query='{query}'")
    return search_products_vector(query)



def estoque_preco(ean: str) -> str:
    """
    Consulta preço e disponibilidade pelo EAN.

    Monta a URL completa concatenando o EAN ao final de settings.estoque_ean_base_url.
    Exemplo: {base}/7891149103300

    Args:
        ean: Código EAN do produto (apenas dígitos).

    Returns:
        JSON string com informações do produto ou mensagem de erro amigável.
    """
    base = (settings.estoque_ean_base_url or "").strip().rstrip("/")
    if not base:
        msg = "Erro: ESTOQUE_EAN_BASE_URL não configurado no .env"
        logger.error(msg)
        return msg

    # manter apenas dígitos no EAN
    ean_digits = "".join(ch for ch in ean if ch.isdigit())
    if not ean_digits:
        msg = "Erro: EAN inválido. Informe apenas números."
        logger.error(msg)
        return msg

    url = f"{base}/{ean_digits}"
    logger.info(f"Consultando estoque_preco por EAN: {url}")

    headers = {
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()

        # resposta esperada: lista de objetos
        try:
            items = resp.json()
        except json.JSONDecodeError:
            txt = resp.text
            logger.warning("Resposta não é JSON válido; retornando texto bruto")
            return txt

        # Se vier um único objeto, normalizar para lista
        items = items if isinstance(items, list) else ([items] if isinstance(items, dict) else [])

        # Heurística de extração de preço
        PRICE_KEYS = (
            "vl_produto",
            "vl_produto_normal",
            "preco",
            "preco_venda",
            "valor",
            "valor_unitario",
            "preco_unitario",
            "atacadoPreco",
        )

        # Chaves de quantidade em ordem de prioridade
        STOCK_QTY_KEYS = [
            "qtd_produto",  # Chave principal do sistema
            "qtd_movimentacao", # FALLBACK: Muitas vezes o estoque real vem aqui neste sistema
            "estoque", "qtd", "qtde", "qtd_estoque", "quantidade", "quantidade_disponivel",
            "quantidadeDisponivel", "qtdDisponivel", "qtdEstoque", "estoqueAtual", "saldo",
            "qty", "quantity", "stock", "amount"
        ]

        # Possíveis indicadores de disponibilidade
        STATUS_KEYS = ("situacao", "situacaoEstoque", "status", "statusEstoque")

        def _parse_float(val) -> float | None:
            try:
                s = str(val).strip()
                if not s:
                    return None
                # aceita formato brasileiro
                s = s.replace(".", "").replace(",", ".") if s.count(",") == 1 and s.count(".") > 1 else s.replace(",", ".")
                return float(s)
            except Exception:
                return None

        def _has_positive_qty(d: Dict[str, Any]) -> bool:
            # Tenta encontrar qualquer chave que tenha valor > 0
            for k in STOCK_QTY_KEYS:
                if k in d:
                    v = d.get(k)
                    try:
                        n = float(str(v).replace(",", "."))
                        if n > 0:
                            return True
                    except Exception:
                        # ignore não numérico
                        pass
            return False

        def _is_available(d: Dict[str, Any]) -> bool:
            # 1. Verificar se está ativo (se a flag existir)
            # Se 'ativo' não existir, assume True por padrão
            is_active = d.get("ativo", True)
            if not is_active:
                logger.debug(f"Item filtrado: ativo=False")
                return False

            # 2. Verificar Estoque
            qty = _extract_qty(d)
            
            # Categorias que NÃO verificam estoque (produção própria ou pesagem)
            # PADARIA: produtos feitos na hora, não têm controle de quantidade
            # FRIGORIFICO/AÇOUGUE: vendem antes de dar entrada na nota
            # HORTI/LEGUMES: idem, produção variável
            cat = str(d.get("classificacao01", "")).upper()
            ignora_estoque = any(x in cat for x in [
                "PADARIA",  # Pães, bolos - feitos na hora
                "FRIGORIFICO", "HORTI", "AÇOUGUE", "ACOUGUE", 
                "LEGUMES", "VERDURAS", "AVES", "CARNES"
            ])
            
            if ignora_estoque:
                # Regra de Exceção: Setor INDUSTRIAL (ex: Padaria Industrial)
                # Produtos industrializados/embalados DEVEM respeitar o estoque do sistema
                if "INDUSTRIAL" in cat:
                    logger.debug(f"Item de {cat}: Setor Industrial detectado, forçando verificação de estoque.")
                    # Continua para o check de quantidade lá embaixo...
                else:
                    # Se não for industrial (ex: Padaria própria, Açougue), libera geral
                    logger.debug(f"Item de {cat}: ignorando verificação de estoque (ativo={is_active})")
                    return True

            # Para os demais (Mercearia, Bebidas, INDUSTRIAL, etc), estoque deve ser POSITIVO
            if qty is not None and qty > 0:
                return True
            
            # Se chegou aqui, ou é 0, ou é negativo em categoria que não pode
            logger.debug(f"Item filtrado: quantidade={qty} (Categoria: {cat})")
            return False

        def _extract_qty(d: Dict[str, Any]) -> float | None:
            best_qty = None
            for k in STOCK_QTY_KEYS:
                if k in d:
                    try:
                        val = float(str(d.get(k)).replace(',', '.'))
                        if val > 0:
                            return val # Achou estoque positivo!
                        if best_qty is None:
                            best_qty = val # Guarda o primeiro (ex: 0.0) como fallback se nada for > 0
                    except Exception:
                        pass
            return best_qty

        def _extract_price(d: Dict[str, Any]) -> float | None:
            for k in PRICE_KEYS:
                if k in d:
                    val = _parse_float(d.get(k))
                    if val is not None:
                        return val
            return None

        # [OTIMIZAÇÃO] Filtro estrito para saída
        sanitized: list[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if not _is_available(it):
                continue  # manter apenas itens com estoque/disponibilidade

            # Cria dict limpo apenas com campos essenciais
            clean = {}
            
            # Copiar apenas identificadores básicos se existirem
            for k in ["produto", "nome", "descricao", "id", "ean", "cod_barra"]:
                if k in it: clean[k] = it[k]

            # Normalizar disponibilidade (se passou no _is_available, é True)
            clean["disponibilidade"] = True

            # Normalizar preço em campo unificado
            price = _extract_price(it)
            if price is not None:
                clean["preco"] = price

            qty = _extract_qty(it)
            if qty is not None:
                clean["quantidade"] = qty

            sanitized.append(clean)

        logger.info(f"EAN {ean_digits}: {len(sanitized)} item(s) disponíveis após filtragem")

        return json.dumps(sanitized, indent=2, ensure_ascii=False)

    except requests.exceptions.Timeout:
        msg = "Erro: Timeout ao consultar preço/estoque por EAN. Tente novamente."
        logger.error(msg)
        return msg
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", "?")
        body = getattr(e.response, "text", "")
        msg = f"Erro HTTP ao consultar EAN: {status} - {body}"
        logger.error(msg)
        return msg
    except requests.exceptions.RequestException as e:
        msg = f"Erro ao consultar EAN: {str(e)}"
        logger.error(msg)
        return msg

    # [Cleanup] Removido bloco duplicado de ean_lookup antigo fora de função


# ============================================
# BUSCA EM LOTE (PARALELA)
# ============================================

def busca_lote_produtos(produtos: list[str]) -> str:
    """
    Busca múltiplos produtos em PARALELO para otimizar performance.
    
    Em vez de buscar sequencialmente (10s × N produtos), busca todos ao mesmo tempo.
    
    Args:
        produtos: Lista de nomes de produtos para buscar
        
    Returns:
        String formatada com todos os produtos encontrados e seus preços
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time
    
    start_time = time.time()
    logger.info(f"🚀 Iniciando busca em lote para {len(produtos)} produtos")
    
    # Pesos médios para produtos vendidos por kg (para calcular preço estimado)
    PESO_UNITARIO = {
        # Padaria
        "pao frances": 0.050, "pão francês": 0.050, "carioquinha": 0.050, "pao carioquinha": 0.050,
        "pao sovado": 0.060, "pão sovado": 0.060, "massa fina": 0.060,
        "mini bolinha": 0.016, "mini coxinha": 0.016,
        # Hortfruti - Legumes
        "tomate": 0.150, "cebola": 0.150, "batata": 0.150,
        "cenoura": 0.100, "pepino": 0.200, "pimentao": 0.150, "pimentão": 0.150,
        # Carnes e Embutidos
        "frango inteiro": 2.200, "frango abatido": 2.200,
        "calabresa": 0.250, "paio": 0.250, "linguica": 0.250, "linguiça": 0.250, "bacon": 0.300,
        # Frutas
        "limao": 0.100, "limão": 0.100, "banana": 0.100, "maca": 0.100, "maçã": 0.100,
        "laranja": 0.200, "mamao": 1.500, "mamão": 1.500, "melancia": 2.000, "abacate": 0.600
    }
    
    # Mapeamento direto de produtos conhecidos que a busca vetorial não encontra bem
    # Formato: termo_busca → (ean, nome_produto)
    PRODUTOS_CONHECIDOS = {
        # Pães
        "pao carioquinha": ("802", "PAO FRANCES kg"),
        "carioquinha": ("802", "PAO FRANCES kg"),
        "carioquinhas": ("802", "PAO FRANCES kg"),
        "pao frances": ("802", "PAO FRANCES kg"),
        "pão francês": ("802", "PAO FRANCES kg"),
        # Salgados de Padaria (prioridade sobre congelados)
        "coxinha": ("816", "MINI COXINHA PANNEMIX FRANGO kg"),
        "coxinha de frango": ("816", "MINI COXINHA PANNEMIX FRANGO kg"),
        "mini coxinha": ("816", "MINI COXINHA PANNEMIX FRANGO kg"),
        "enroladinho": ("827", "ENROLADINHO SALSICHA"),
        "enroladinho de salsicha": ("827", "ENROLADINHO SALSICHA"),
        # Feijão e Café (Garantindo básicos)
        "feijao": ("7898933603084", "FEIJAO CARIOCA YAN 1kg"),
        "feijão": ("7898933603084", "FEIJAO CARIOCA YAN 1kg"),
        "feijao carioca": ("7898933603084", "FEIJAO CARIOCA YAN 1kg"),
        "feijao de corda": ("7896406001009", "FEIJAO CORDA KI-CALDO 1kg"),
        "cafe": ("7898286200374", "CAFE PURO 250g"),
        "café": ("7898286200374", "CAFE PURO 250g"),
        # Arroz (Garantindo básicos)
        "arroz": ("7898236717129", "ARROZ BRANCO 101 1kg"),
        "arroz branco": ("7898236717129", "ARROZ BRANCO 101 1kg"),
        "arroz tipo 1": ("7898236717129", "ARROZ BRANCO 101 1kg"),
        "arroz parboilizado": ("7898236717167", "ARROZ PARBOILIZADO 101 1KG"),
        # Frutas Hortifruti
        "laranja": ("126", "LARANJA LIMA kg"),
        "laranjas": ("126", "LARANJA LIMA kg"),
        # Refrigerantes
        "coca-cola 2l": ("7894900027013", "REFRIG COCA COLA PET 2L"),
        "coca-cola 2 litros": ("7894900027013", "REFRIG COCA COLA PET 2L"),
        "coca cola 2l": ("7894900027013", "REFRIG COCA COLA PET 2L"),
        "coca cola 2 litros": ("7894900027013", "REFRIG COCA COLA PET 2L"),
    }
    
    def buscar_produto_completo(produto: str) -> dict:
        """Busca EAN e depois preço de um produto (pode incluir quantidade: '5 tomates')"""
        try:
            import re
            
            # Extrair quantidade da string (ex: "5 tomates" → quantidade=5, produto="tomates")
            produto_limpo = produto.strip()
            quantidade = None
            match = re.match(r'^([\d]+)\s+(.+)$', produto_limpo)
            if match:
                quantidade = int(match.group(1))
                produto_limpo = match.group(2)
                logger.info(f"📊 Quantidade detectada: {quantidade}x {produto_limpo}")
            
            produto_lower = produto_limpo.lower().strip()
            
            # 0. SHORTCUT: Verificar se é um produto conhecido
            if produto_lower in PRODUTOS_CONHECIDOS:
                ean, nome = PRODUTOS_CONHECIDOS[produto_lower]
                logger.info(f"⚡ [SHORTCUT] Produto conhecido: '{produto}' → EAN {ean}")
                preco_result = estoque_preco(ean)
                try:
                    preco_data = json.loads(preco_result)
                    if preco_data and isinstance(preco_data, list) and len(preco_data) > 0:
                        item = preco_data[0]
                        preco = item.get("preco", 0)
                        logger.info(f"✅ [SHORTCUT] Sucesso: {nome} (R$ {preco})")
                        return {"produto": nome, "erro": None, "preco": preco, "ean": ean, "quantidade": quantidade}
                except Exception as e:
                    logger.warning(f"⚠️ [SHORTCUT] Erro ao consultar preço: {e}")
            
            # 1. Buscar EAN (Postgres)
            # IMPORTANTE: ean_lookup retorna uma string formatada (EANS_ENCONTRADOS: ...)
            ean_result = ean_lookup(produto)
            
            # Se a busca no banco falhou ou não achou nada
            if "EANS_ENCONTRADOS" not in ean_result:
                logger.warning(f"❌ [BUSCA LOTE] Banco não retornou resultados para '{produto}'")
                return {"produto": produto, "erro": "Não encontrado", "preco": None}
            
            # 2. Parse da string de retorno do ean_lookup para extrair lista de dicts
            # Formato esperado: "EANS_ENCONTRADOS:\n1) 123 - PRODUTO A\n2) 456 - PRODUTO B"
            import re
            
            linhas = ean_result.split('\n')
            candidatos = []
            
            for linha in linhas:
                # Procurar padrão: número) EAN - NOME
                # Regex flexível para pegar "1) 123 - NOME"
                match = re.match(r'\d+\)\s*(\d+)\s*-\s*(.+)', linha.strip())
                if match:
                    ean = match.group(1)
                    nome = match.group(2).strip()
                    candidatos.append({"ean": ean, "nome": nome})
            
            if not candidatos:
                logger.warning(f"❌ [BUSCA LOTE] Falha ao fazer parse dos candidatos para '{produto}'. Texto: {ean_result[:50]}...")
                return {"produto": produto, "erro": "EAN não extraído", "preco": None}
            
            # 3. Encontrar os melhores candidatos (Ranking)
            PREFERENCIAS = {
                "frango": ["abatido"],
                "leite": ["liquido"],
                "arroz": ["tipo 1"],
                "acucar": ["cristal"],
                "feijao": ["carioca", "corda", "branco", "preto"],
                "oleo": ["soja"],
                "tomate": ["tomate kg"],
                "cebola": ["cebola branca", "cebola kg"],  # Prioriza branca
                "batata": ["batata kg"],
                "calabresa": ["calabresa kg"],
                # Padaria - NOVO
                "pao": ["pao frances", "frances kg"],
                "carioquinha": ["pao frances", "frances kg"],
                "frances": ["pao frances", "frances kg"],
                # Refrigerantes - NOVO
                "coca": ["coca cola", "coca-cola"],
                "coca-cola": ["coca cola pet", "coca-cola pet"],
                "guarana": ["guarana antarctica"],
            }
            
            produto_lower = produto.lower()
            
            # Termos de preferência para este produto (se houver)
            termos_preferidos = []
            for chave, termos in PREFERENCIAS.items():
                if chave in produto_lower:
                    termos_preferidos = termos
                    break

            candidatos_pontuados = []

            for c in candidatos:
                nome_lower = c["nome"].lower()
                score = 0
                
                # 1. Match de palavras da busca (Base)
                score += sum(2 for palavra in produto_lower.split() if palavra in nome_lower)
                
                # 2. Bonus por match exato da frase
                if produto_lower in nome_lower:
                    score += 5
                
                # 3. Bonus por Preferências
                for i, termo in enumerate(termos_preferidos):
                    if termo in nome_lower:
                        score += (20 - i)  # Bônus maior (20 em vez de 10)
                        break
                
                # 4. Penalidades para termos que o cliente geralmente não quer por padrão (se a busca for genérica)
                # Se o usuário NÃO digitou "descaf", mas o produto é descaf, penaliza.
                PALAVRAS_EVITAR = ["descaf", "soluvel", "desnatado", "condensado", "creme de leite"]
                if "leite" in produto_lower and "po" not in produto_lower:
                    PALAVRAS_EVITAR.append(" po ") # Evita leite em pó se a busca for "leite"
                    PALAVRAS_EVITAR.append(" em pó")
                
                if "cafe" in produto_lower or "café" in produto_lower:
                    PALAVRAS_EVITAR.extend(["curto", "maquina", "expresso", "nespresso", "capsula"])

                if "feijao" in produto_lower:
                    PALAVRAS_EVITAR.extend(["branco", "preto", "fradinho"])
                
                for palavra in PALAVRAS_EVITAR:
                    if palavra in nome_lower and palavra not in produto_lower:
                        score -= 20  # Penalidade forte para não sugerir descaf/branco por engano
                
                # 5. Penalidade por tamanho (manter baixa para não matar nomes descritivos)
                score -= len(nome_lower) * 0.02
                
                candidatos_pontuados.append((score, c))
            
            # Ordenar por score (maior para menor)
            candidatos_pontuados.sort(key=lambda x: x[0], reverse=True)
            
            # 4. Tentar buscar preço nos Top 15 candidatos (Retry Logic aumentado)
            for score, candidato in candidatos_pontuados[:15]:
                ean = candidato["ean"]
                nome_candidato = candidato["nome"]
                logger.info(f"👉 [BUSCA LOTE] Tentando: '{nome_candidato}' (EAN: {ean}) | Score: {score:.2f}")
                
                preco_result = estoque_preco(ean)
                
                try:
                    preco_data = json.loads(preco_result)
                    if preco_data and isinstance(preco_data, list) and len(preco_data) > 0:
                        item = preco_data[0]
                        nome = item.get("produto", item.get("nome", produto))
                        preco = item.get("preco", 0)
                        logger.info(f"✅ [BUSCA LOTE] Sucesso com '{nome}' (R$ {preco})")
                        return {"produto": nome, "erro": None, "preco": preco, "ean": ean, "quantidade": quantidade}
                    else:
                        logger.info(f"⚠️ [BUSCA LOTE] '{nome_candidato}' sem estoque/preço. Tentando próximo...")
                except Exception as e:
                    logger.warning(f"Erro ao processar retorno de preço para {ean}: {e}")
            
            logger.warning(f"❌ [BUSCA LOTE] Nenhum dos top 3 candidatos para '{produto}' tinha estoque.")
            return {"produto": produto, "erro": "Indisponível (sem estoque)", "preco": None}
            
        except Exception as e:
            logger.error(f"Erro ao buscar {produto}: {e}")
            return {"produto": produto, "erro": str(e), "preco": None}
    
    # Executar buscas em paralelo (máximo 5 threads para não sobrecarregar)
    resultados = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(buscar_produto_completo, p): p for p in produtos}
        
        for future in as_completed(futures):
            resultado = future.result()
            resultados.append(resultado)
    
    elapsed = time.time() - start_time
    logger.info(f"✅ Busca em lote concluída em {elapsed:.2f}s para {len(produtos)} produtos")
    
    # Formatar resposta (com cálculo de preço estimado para produtos de peso)
    encontrados = []
    nao_encontrados = []
    
    for r in resultados:
        if r["preco"] is not None:
            nome = r['produto']
            preco_kg = r['preco']
            quantidade = r.get('quantidade')
            
            # Verificar se é produto vendido por peso (kg) e se tem quantidade
            if quantidade and quantidade > 0:
                # Tentar encontrar peso unitário para este produto
                nome_lower = nome.lower()
                peso_unit = None
                
                for chave, peso in PESO_UNITARIO.items():
                    if chave in nome_lower:
                        peso_unit = peso
                        break
                
                # Se encontrou peso, calcular preço estimado
                if peso_unit:
                    peso_total = quantidade * peso_unit
                    preco_estimado = peso_total * preco_kg
                    # Formato: "5 Tomates (~750g) - R$ 4,12"
                    encontrados.append(f"• {quantidade} {nome.replace(' kg', '').replace(' KG', '')} (~{int(peso_total*1000)}g) - R$ {preco_estimado:.2f}")
                    logger.info(f"💰 Cálculo: {quantidade}x {nome} × {peso_unit}kg × R${preco_kg:.2f}/kg = R${preco_estimado:.2f}")
                else:
                    # Produto de peso mas sem regra de peso unitário - mostrar só quantidade
                    encontrados.append(f"• {quantidade}x {nome} - R$ {preco_kg:.2f}/kg")
            else:
                # Produto unitário normal ou sem quantidade especificada
                encontrados.append(f"• {nome} - R$ {preco_kg:.2f}")
        else:
            nao_encontrados.append(r['produto'])
    
    resposta = []
    if encontrados:
        resposta.append("PRODUTOS_ENCONTRADOS:")
        resposta.extend(encontrados)
    
    if nao_encontrados:
        resposta.append(f"\nNÃO_ENCONTRADOS: {', '.join(nao_encontrados)}")
    
    return "\n".join(resposta) if resposta else "Nenhum produto encontrado."


def consultar_encarte() -> str:
    """
    Consulta o encarte atual do supermercado.
    Suporta múltiplos encartes via campo active_encartes_urls.
    
    Returns:
        JSON string com a URL (ou lista de URLs) do encarte ou mensagem de erro.
    """
    # Remove trailing slash from base to ensure correct path
    base = settings.supermercado_base_url.rstrip("/")
    url = f"{base}/encarte/"
    
    logger.info(f"Consultando encarte: {url}")
    
    try:
        response = requests.get(
            url,
            headers=get_auth_headers(),
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"Encarte obtido com sucesso: {data}")
        
        domain = "https://app.aimerc.com.br"
        
        def _fix_url(u: str) -> str:
            if not u: return u
            if u.startswith("/"):
                u = f"{domain}{u}"
            elif "supermercadoqueiroz.com.br" in u:
                u = u.replace("https://supermercadoqueiroz.com.br", domain).replace("http://supermercadoqueiroz.com.br", domain)
            return u

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
            
        return json.dumps(data, indent=2, ensure_ascii=False)
        
    except requests.exceptions.Timeout:
        error_msg = "Erro: Timeout ao consultar encarte. Tente novamente."
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.HTTPError as e:
        error_msg = f"Erro HTTP ao consultar encarte: {e.response.status_code} - {e.response.text}"
        logger.error(error_msg)
        return error_msg
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Erro ao consultar encarte: {str(e)}"
        logger.error(error_msg)
        return error_msg
    
    except json.JSONDecodeError:
        error_msg = "Erro: Resposta do encarte não é um JSON válido."
        logger.error(error_msg)
        return error_msg
