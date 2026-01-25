"""Sub-subagente focado exclusivamente em busca vetorial."""

import json
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from config.logger import setup_logger
from tools.db_vector_search import search_products_vector


logger = setup_logger(__name__)


VECTOR_SEARCH_AGENT_PROMPT = """
Você é o AGENTE BANCO VETORIAL do Mercadinho Queiroz.

Sua única responsabilidade é executar uma busca no banco vetorial usando a ferramenta `vector_search`.

REGRAS:
- Sempre use `vector_search`.
- Nunca invente produtos, EANs ou preços.
- Retorne apenas o resultado bruto da ferramenta, sem reformatar.
""".strip()


def _get_fast_llm():
    model_name = getattr(settings, "llm_model", "gemini-2.5-flash")
    temp = 0.0

    if settings.llm_provider == "openai" and "gpt" in model_name:
        if "x.ai" not in str(settings.openai_api_base):
            model_name = "gpt-4o-mini"

    if settings.llm_provider == "google":
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.google_api_key,
            temperature=temp,
        )

    client_kwargs = {}
    if settings.openai_api_base:
        client_kwargs["base_url"] = settings.openai_api_base

    return ChatOpenAI(
        model=model_name,
        api_key=settings.openai_api_key,
        temperature=temp,
        **client_kwargs,
    )


@tool("vector_search")
def vector_search_tool(query: str, limit: int = 10) -> str:
    return search_products_vector(query, limit=limit)


def run_vector_search_subagent(query: str, limit: int = 10, thread_id: Optional[str] = None) -> str:
    q = (query or "").strip()
    if not q:
        return "Nenhum produto encontrado."

    logger.info(f"🧩 [SUB-SUB-AGENT][VETORIAL] Buscando: '{q}' (limit={limit})")

    llm = _get_fast_llm()
    agent = create_react_agent(llm, [vector_search_tool], prompt=VECTOR_SEARCH_AGENT_PROMPT)

    config = {"recursion_limit": 6}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}

    result = agent.invoke(
        {
            "messages": [
                HumanMessage(
                    content=json.dumps(
                        {"query": q, "limit": int(limit)}, ensure_ascii=False
                    )
                )
            ]
        },
        config,
    )

    messages = result.get("messages", []) if isinstance(result, dict) else []
    tool_outputs = [
        m.content
        for m in messages
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "vector_search"
    ]
    if tool_outputs:
        return tool_outputs[-1]

    for m in reversed(messages):
        if getattr(m, "type", None) == "ai":
            content = m.content if isinstance(m.content, str) else str(m.content)
            if content and content.strip():
                return content

    logger.warning("Resposta vazia do sub-subagente vetorial")
    return "Nenhum produto encontrado."
