import sys
from unittest.mock import MagicMock, patch

# Mock settings and logger
sys.modules['config.settings'] = MagicMock()
sys.modules['config.logger'] = MagicMock()
sys.modules['tools.whatsapp_api'] = MagicMock()
sys.modules['tools.redis_tools'] = MagicMock()
sys.modules['agent_langgraph_simple'] = MagicMock()
sys.modules['arq'] = MagicMock()
sys.modules['arq.connections'] = MagicMock()

# Mock dependencies
with patch('config.settings.settings') as mock_settings:
    mock_settings.google_api_key = "fake_key"
    
    # Import server functions (will need to import partially or mock what's missing)
    # Since server.py has many imports, it's safer to import after mocking
    try:
        from server import _extract_incoming
        from tools.redis_tools import set_comprovante
        
        # Test Case 1: PDF with Base64 in payload (Webhook v2)
        payload = {
            "event": "message",
            "data": {
                "message": {
                    "key": {"remoteJid": "5511999999999@s.whatsapp.net"},
                    "messageType": "documentMessage",
                    "mimetype": "application/pdf",
                    "caption": "Segue o comprovante do pix",
                    "mediaBase64": "JVBERi0xLjQKJeLjz9MKN..." # Fake PDF header
                }
            }
        }
        
        print("\n--- Test 1: PDF via Webhook Payload ---")
        result = _extract_incoming(payload)
        print(f"Result Msg: {result.get('mensagem_texto')}")
        
        # Verify set_comprovante was called
        if set_comprovante.called:
            print("✅ set_comprovante called!")
            args = set_comprovante.call_args[0]
            print(f"Phone: {args[0]}")
            print(f"Data URI prefix: {args[1][:30]}...")
        else:
            print("❌ set_comprovante NOT called")

        # Test Case 2: PDF via API Download (No Base64 in payload)
        # We need to mock process_pdf since we can't really download
        pass 
        
    except ImportError as e:
        print(f"Import Error: {e}")
    except Exception as e:
        print(f"Error: {e}")
