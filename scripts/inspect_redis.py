import sys
import os
import redis
import json
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from config.settings import settings

def inspect_redis():
    phone = "558587520060"
    key = f"session:memory:{phone}"
    
    print(f"🔍 Inspecting Session: {phone}")
    print(f"🔑 Redis Key: {key}")
    print(f"🔧 URL: {settings.redis_url}")
    
    try:
        r = redis.from_url(settings.redis_url, decode_responses=True)
        
        # Check type
        ktype = r.type(key)
        print(f"📦 Key Type: {ktype}")
        
        if ktype == "none":
            print("❌ Key does not exist (Session Expired or Empty)")
            return
            
        # Get content
        items = r.lrange(key, 0, -1)
        print(f"📚 Items Count: {len(items)}")
        
        for i, item in enumerate(items):
            print(f"\n[Item {i}]")
            try:
                data = json.loads(item)
                print(json.dumps(data, indent=2, ensure_ascii=False))
            except:
                print(f"RAW (Not JSON): {item}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_redis()
