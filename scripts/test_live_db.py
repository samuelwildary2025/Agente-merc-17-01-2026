
import os
import sys
import psycopg2
import json
from psycopg2.extras import RealDictCursor
from openai import OpenAI

# Force credentials provided by user
CONN_STR = "postgres://postgres:Theo2023...@31.97.252.6:2022/projeto_queiroz?sslmode=disable"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

def generate_embedding(text):
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding

def test_search(query):
    print(f"🔎 Testing search for: '{query}'")
    
    try:
        # 1. Generate embedding
        print("   Generating embedding...")
        embedding = generate_embedding(query)
        embedding_str = f"[{','.join(map(str, embedding))}]"
        
        # 2. Connect to DB
        print("   Connecting to DB...")
        conn = psycopg2.connect(CONN_STR)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 3. Call hybrid_search_v2
        print("   Executing SQL query...")
        sql = """
            SELECT text, score, rank 
            FROM hybrid_search_v2(
                %s, %s::vector, 10, 1.0, 1.0, 0.5, 50
            )
        """
        cur.execute(sql, (query, embedding_str))
        results = cur.fetchall()
        
        print(f"✅ Found {len(results)} results:")
        for r in results[:3]:
            print(f"   [{r['score']:.4f}] {r['text'][:60]}...")
            
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY not found in environment")
        sys.exit(1)
        
    test_search("arroz")
    test_search("cafe pilao")
