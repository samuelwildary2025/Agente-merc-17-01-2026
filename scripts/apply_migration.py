import os
import psycopg2
from pathlib import Path

# Use the vector DB connection    # Try to load from .env file manually if needed, or use the one seen in settings.py
CONN_STR = "postgres://postgres:Theo2023...@31.97.252.6:2022/projeto_queiroz?sslmode=disable"

def apply_migration():
    print("🚀 Applying database migration...")
    
    # Locate the SQL file
    base_dir = Path(__file__).parent
    sql_path = base_dir / "setup_vector_db.sql"
    
    if not sql_path.exists():
        print(f"❌ SQL file not found: {sql_path}")
        return

    sql_content = sql_path.read_text(encoding="utf-8")
    
    try:
        with psycopg2.connect(CONN_STR) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_content)
                conn.commit()
                print("✅ Migration applied successfully! Function 'hybrid_search_v2' created.")
                
    except Exception as e:
        print(f"❌ Error applying migration: {e}")

if __name__ == "__main__":
    apply_migration()
