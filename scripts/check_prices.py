import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from tools.db_vector_search import search_products_vector
from tools.http_tools import estoque_preco
import json

def check_prices():
    products = ["tomate", "laranja", "pão carioquinha"]
    
    print(f"🔍 Investigating Product Prices...")
    
    for term in products:
        print(f"\n--- Searching for: {term} ---")
        # 1. Vector Search to get EANs
        vectors = search_products_vector(term, limit=5)
        
        # Parse EANs (simple extraction)
        try:
            # Vectors returns a string list of EANs usually
            # But relying on the tool output format
            print(f"Vector Result: {vectors[:200]}...") 
        except:
            pass
            
        # Manually verify the top hits if possible or just rely on what the analista would do.
        # Ideally, I would call analista_produtos_tool directly but that runs the LLM agent.
        # Let's just run the vector search + price check for the TOP result manually to see variability.
        
if __name__ == "__main__":
    # Better approach: Run the actual search tool to see what it picks TODAY.
    from tools.search_agent import analista_produtos_tool
    
    query = "tomate, laranja, pao carioquinha"
    print(f"🚀 Running Analysis for: {query}")
    result = analista_produtos_tool(query, telefone="DEBUG_PRICE")
    print("\n✅ RESULTADO DO AGENTE:")
    print(result)
