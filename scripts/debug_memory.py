import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import settings
from memory.redis_memory import RedisChatMessageHistory
from memory.hybrid_memory import HybridChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage

def test_memory():
    phone = "558599999999" # Test phone
    print(f"🧪 Testing Memory for session: {phone}")
    print(f"🔧 Redis URL: {settings.redis_url}")

    # 1. Test RedisChatMessageHistory Directly
    print("\n--- Testing RedisChatMessageHistory ---")
    redis_mem = RedisChatMessageHistory(session_id=phone, ttl=60)
    
    # Clear first
    redis_mem.clear()
    messages = redis_mem.messages
    print(f"Expected 0 messages, got: {len(messages)}")

    # Add message
    msg1 = HumanMessage(content="Teste 1")
    redis_mem.add_message(msg1)
    print("Added HumanMessage('Teste 1')")

    # Read back
    messages = redis_mem.messages
    print(f"Read back {len(messages)} messages")
    if len(messages) > 0:
        print(f"Content: {messages[0].content}")
    else:
        print("❌ FAILED to read back from Redis!")

    # 2. Test HybridChatMessageHistory
    print("\n--- Testing HybridChatMessageHistory ---")
    hybrid = HybridChatMessageHistory(session_id=phone, redis_ttl=60)
    
    # Clear (clears Redis only)
    hybrid.clear()
    
    # Add messages
    hybrid.add_message(HumanMessage(content="Hybrid Test User"))
    hybrid.add_message(AIMessage(content="Hybrid Test AI"))
    print("Added Hybrid User+AI messages")
    
    # Read back
    msgs = hybrid.messages
    print(f"Read back {len(msgs)} messages from Hybrid")
    for m in msgs:
        print(f" - {m.type}: {m.content}")

    if len(msgs) == 2:
        print("✅ Hybrid Memory working correctly.")
    else:
        print("❌ Hybrid Memory FAILED.")

if __name__ == "__main__":
    test_memory()
