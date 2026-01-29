import requests
import json
import re
from typing import Optional, Dict, Any
from config.settings import settings
from config.logger import setup_logger

logger = setup_logger(__name__)

class WhatsAppAPI:
    def __init__(self):
        self.base_url = (settings.whatsapp_api_base_url or "").rstrip("/")
        self.token = settings.whatsapp_instance_token
        
        if not self.base_url:
            logger.warning("WHATSAPP_API_BASE_URL não configurado!")
            
    def _get_headers(self):
        return {
            "Content-Type": "application/json",
            "apikey": self.token,
            "token": self.token,
            "Authorization": f"Bearer {self.token}",
            "X-Instance-Token": self.token
        }

    def _clean_number(self, phone: str) -> str:
        """Remove caracteres não numéricos"""
        return re.sub(r"\D", "", str(phone))

    def send_media(self, to: str, media_url: str = None, caption: str = "", base64_data: str = None, mimetype: str = "image/jpeg") -> bool:
        """
        Envia mensagem de mídia (Imagem/Vídeo/PDF) conforme DOC oficial
        POST /send/media
        Required: number, type, file
        Optional: text (caption)
        """
        if not self.base_url: return False
        
        url = f"{self.base_url}/send/media"
        clean_num = self._clean_number(to)
        
        # Determinar Type
        type_val = "image" # Default
        if mimetype:
            if "video" in mimetype: type_val = "video"
            elif "audio" in mimetype: type_val = "audio" 
            elif "application" in mimetype or "text" in mimetype or "pdf" in mimetype: type_val = "document"
        elif media_url:
            # Tentar inferir por extensão se mimetype não fornecido
            lower_url = media_url.lower()
            if any(ext in lower_url for ext in ['.mp4']): type_val = "video"
            elif any(ext in lower_url for ext in ['.mp3', '.ogg', '.wav']): type_val = "audio"
            elif any(ext in lower_url for ext in ['.pdf', '.doc', '.xls', '.txt', '.csv']): type_val = "document"

        # Montar Payload
        payload = {
            "number": clean_num,
            "type": type_val,
            "text": caption or ""
        }
        
        if base64_data:
            # DOC diz "file": "URL ou base64 do arquivo"
            # Geralmente base64 precisa do prefixo data URI scheme para APIs modernas
            payload["file"] = f"data:{mimetype};base64,{base64_data}"
        elif media_url:
            payload["file"] = media_url
            
        # Se for document, pode precisar de docName (opcional, mas bom ter)
        if type_val == "document" and media_url:
            payload["docName"] = media_url.split("/")[-1] or "documento.pdf"
            
        logger.info(f"📷 Enviando mídia para {clean_num} (Type: {type_val}) via Uazapi")
        
        try:
            resp = requests.post(url, headers=self._get_headers(), json=payload, timeout=60) # Timeout maior para media
            
            if resp.status_code not in [200, 201]:
                logger.error(f"❌ Erro envio mídia ({resp.status_code}): {resp.text[:200]}")
                return False
            else:
                logger.info("✅ Mídia enviada com sucesso")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao enviar mídia: {e}")
            return False

    def send_text(self, to: str, text: str) -> bool:
        """
        Envia mensagem de texto simples
        POST /send/text
        """
        if not self.base_url: 
            logger.error("❌ WHATSAPP_API_BASE_URL não configurado! Mensagem NÃO enviada.")
            return False
            
        if "<BREAK>" in text:
            parts = text.split("<BREAK>")
            logger.info(f"🔄 Mensagem multi-parte detectada! Dividindo em {len(parts)} mensagens.")
            import time
            success_all = True
            for index, part in enumerate(parts):
                part = part.strip()
                if not part: continue
                if index > 0: time.sleep(3.0)
                if not self.send_text(to, part): success_all = False
            return success_all
        
        url = f"{self.base_url}/send/text"
        
        clean_num = self._clean_number(to)
        
        payload = {
            "number": clean_num,
            "text": text,
            "delay": 1200, # Simula digitando
            "linkPreview": True
        }
        
        logger.info(f"📤 Enviando mensagem para {clean_num}: {text[:50]}...")
        
        try:
            resp = requests.post(url, headers=self._get_headers(), json=payload, timeout=15)
            
            if resp.status_code not in [200, 201]:
                logger.error(f"❌ Erro API WhatsApp ({resp.status_code}): {resp.text[:500]}")
                return False
            else:
                logger.info(f"✅ Mensagem enviada com sucesso para {clean_num}")
                return True
        except Exception as e:
            logger.error(f"❌ Erro ao enviar mensagem WhatsApp para {to}: {e}")
            return False

    def send_presence(self, to: str, presence: str = "composing") -> bool:
        """
        Envia presence
        POST /send/presence (Deduzido)
        """
        if not self.base_url: return False
        
        # Endpoint provável
        url = f"{self.base_url}/send/presence" # Check se existe ou é /chat/presence
        payload = {
            "number": self._clean_number(to),
            "presence": presence 
        }
        
        try:
            requests.post(url, headers=self._get_headers(), json=payload, timeout=5)
            return True
        except Exception:
            return False

    def mark_as_read(self, chat_id: str, message_id: str = None) -> bool:
        """
        Marca o chat como lido
        POST /chats/mark-read (Deduzido, muitos usam esse padrão)
        Ou tenta usar option no sendText se não houver endpoint isolado.
        """
        if not self.base_url or not chat_id: return False
        
        # Tentativa de endpoint provável
        url = f"{self.base_url}/chats/mark-read"
        
        clean_num = self._clean_number(chat_id)
        
        # Algumas APIs pedem lista de chats
        payload = {
            "chats": [clean_num],
            "readmessages": True
        }
        
        try:
            resp = requests.post(url, headers=self._get_headers(), json=payload, timeout=5)
            if resp.status_code == 404:
                # Tenta singular
                url = f"{self.base_url}/chat/mark-read"
                payload = {"number": clean_num}
                requests.post(url, headers=self._get_headers(), json=payload, timeout=5)
            
            return True
        except Exception:
            return False

    def get_media_base64(self, message_id: str) -> Optional[Dict[str, str]]:
        """
        Obtém mídia em Base64
        POST /message/download (Talvez ainda funcione se for endpoint legado ou compatível)
        """
        if not self.base_url: return None
        
        url = f"{self.base_url}/message/download"
        payload = {
            "messageId": message_id,
            "returnBase64": True
        }
        
        # Uazapi pode usar /chat/download-media ou similar
        # Por enquanto mantemos o antigo e logamos erro se falhar
        
        try:
            resp = requests.post(url, headers=self._get_headers(), json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if "base64" in data: return data
                if "data" in data and "base64" in data["data"]: return data["data"]
            
        except Exception as e:
            logger.error(f"Erro ao obter mídia WhatsApp ({message_id}): {e}")
            
        return None

# Instância global
whatsapp = WhatsAppAPI()
