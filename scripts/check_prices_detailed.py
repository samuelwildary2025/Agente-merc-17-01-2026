import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from tools.db_vector_search import search_products_vector
from tools.http_tools import estoque_preco
import json

def check_prices():
    products = ["tomate", "laranja", "pão carioquinha"]
    
    print(f"🔍 Investigating ALL Candidates to find EANs...")
    
    for term in products:
        print(f"\n--- Searching for: {term} ---")
        # 1. Vector Search to get detailed candidates
        # We need the vector tool to return the RAW list or we assume the function returns a string list
        # Let's use the underlying function directly if possible, or just parse the tool output.
        
        # Actually, let's use search_products_vector from db_vector_search directly which returns list of dicts potentially?
        # verification: tools/db_vector_search.py lines...
        
        results = search_products_vector(term, limit=10)
        
        # results might be a list of strings if RERANK is on, or a list of dicts.
        # tools/db_vector_search.py usually returns a list of results.
        
        if isinstance(results, list):
            for res in results:
                # Assuming res is a dict or string
                print(f"Candidate: {res}")
                
                # If we can extract EAN, let's check price
                # If res is a Dict with 'ean', good.
                ean = res.get('ean') if isinstance(res, dict) else None
                nome = res.get('nome') if isinstance(res, dict) else None
                
                if ean:
                    try:
                        price_data = estoque_preco(ean)
                        print(f"   💲 Price Check ({ean}): {price_data}")
                    except:
                        pass
        else:
            print(f"Result type: {type(results)}")
            print(results)

if __name__ == "__main__":
    check_prices()
