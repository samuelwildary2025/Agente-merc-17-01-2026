import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from tools.http_tools import estoque_preco

def check_specific_eans():
    # Candidates based on previous vector search output
    eans_to_check = {
        "Tomate kg (Standard)": "229",
        "Tomate Caja": "231",
        "Tomate Cereja": "221",
        "Laranja Bahia (Possible Premium)": "318",
        # Assuming there might be a "Laranja Pera" or similar that didn't show up in top 10 or needs specific search
        "Laranja Comum (Hypothesis)": "144" # Guessing EAN or need to find it
    }
    
    # Let's search for "Laranja Pera" specifically to see if we find another EAN
    from tools.db_vector_search import search_products_vector
    
    print("--- Searching for specific 'Laranja Pera' to find common EAN ---")
    pera_res = search_products_vector("laranja pera", limit=3)
    print(pera_res)
    
    print("\n--- Checking Prices for Candidates ---")
    
    for name, ean in eans_to_check.items():
        try:
            res = estoque_preco(ean)
            print(f"📦 {name} (EAN {ean}): {res}")
        except Exception as e:
            print(f"❌ Error checking {name}: {e}")

if __name__ == "__main__":
    check_specific_eans()
