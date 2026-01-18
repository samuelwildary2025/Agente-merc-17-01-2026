"""
Script de Teste de Quota do Gemini (Versão Simples)
Executa várias requisições rápidas para detectar o limite real (15 ou 1.000 RPM)
"""
import time
import requests
from datetime import datetime
import os

# Pegar API key do .env ou usar a nova fornecida
GOOGLE_API_KEY = "AIzaSyAxJAJNtMJxMWLHNl8v5Ah2ZrIYtMV1Wvs"
MODEL = "gemini-2.5-flash"

def test_gemini_quota():
    """
    Testa quantas requisições conseguimos fazer em 1 minuto.
    """
    print("=" * 60)
    print("🧪 TESTE DE QUOTA DO GEMINI API")
    print("=" * 60)
    print(f"⏰ Início: {datetime.now().strftime('%H:%M:%S')}")
    print(f"🔑 API Key: {GOOGLE_API_KEY[:20]}...")
    print(f"🤖 Modelo: {MODEL}")
    print()
    
    successful_requests = 0
    failed_requests = 0
    error_429_at = None
    
    start_time = time.time()
    max_duration = 60  # 1 minuto
    
    print("🚀 Iniciando teste (máximo 60 segundos)...")
    print("   Enviando requisições rápidas...\n")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GOOGLE_API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [{"text": "Diga apenas: OK"}]
        }]
    }
    
    try:
        while (time.time() - start_time) < max_duration:
            try:
                response = requests.post(url, json=payload, timeout=10)
                
                if response.status_code == 200:
                    successful_requests += 1
                    
                    # Progresso visual
                    if successful_requests % 5 == 0:
                        elapsed = time.time() - start_time
                        rate = successful_requests / (elapsed / 60)
                        print(f"✅ {successful_requests} requisições | Taxa: {rate:.1f} RPM")
                
                elif response.status_code == 429:
                    failed_requests += 1
                    if error_429_at is None:
                        error_429_at = successful_requests
                        elapsed = time.time() - start_time
                        print(f"\n❌ ERRO 429 DETECTADO após {successful_requests} requisições!")
                        print(f"   Tempo decorrido: {elapsed:.1f}s")
                        print(f"   Taxa no momento do erro: {(successful_requests / (elapsed / 60)):.1f} RPM")
                        break
                else:
                    print(f"⚠️ Erro HTTP {response.status_code}: {response.text[:100]}")
                    break
                    
            except requests.exceptions.Timeout:
                print("⏱️ Timeout - servidor demorou demais")
                break
            except Exception as e:
                print(f"⚠️ Erro: {str(e)[:100]}")
                break
    
    except KeyboardInterrupt:
        print("\n\n⏸️ Teste interrompido pelo usuário")
    
    # Resultados
    elapsed_total = time.time() - start_time
    rpm_achieved = (successful_requests / (elapsed_total / 60)) if elapsed_total > 0 else 0
    
    print("\n" + "=" * 60)
    print("📊 RESULTADOS DO TESTE")
    print("=" * 60)
    print(f"✅ Requisições bem-sucedidas: {successful_requests}")
    print(f"❌ Requisições falhadas: {failed_requests}")
    print(f"⏱️  Tempo total: {elapsed_total:.1f}s")
    print(f"📈 Taxa alcançada: {rpm_achieved:.1f} RPM")
    print()
    
    # Diagnóstico
    print("🔍 DIAGNÓSTICO:")
    if error_429_at is not None:
        if error_429_at < 20:
            print("   ⚠️  BILLING NÃO ATIVO ou NÃO VINCULADO")
            print("   📊 Limite detectado: ~15 RPM (Free Tier)")
            print()
            print("   💡 Ações recomendadas:")
            print("      1. Verificar se billing está vinculado ao projeto")
            print("      2. Acessar: https://console.cloud.google.com/billing")
            print("      3. Vincular conta de faturamento ao projeto da API")
        else:
            print("   ❓ Erro inesperado - quota intermediária detectada")
            print(f"      Falhou em: {error_429_at} requisições")
    else:
        if rpm_achieved > 100:
            print("   ✅ BILLING ATIVO E FUNCIONANDO!")
            print(f"   📊 Limite real: ~{int(rpm_achieved)} RPM ou mais")
            print()
            print("   💡 Você pode aumentar WORKERS_MAX_JOBS para 20+")
        elif rpm_achieved > 15:
            print("   🟡 Possível billing ativo, mas com limitação")
            print(f"   📊 Limite: ~{int(rpm_achieved)} RPM")
        else:
            print("   ⚠️  Free Tier detectado")
            print("   📊 Limite: ~15 RPM")
            print("   💡 Mantenha WORKERS_MAX_JOBS=5")
    
    print("=" * 60)
    print()


if __name__ == "__main__":
    test_gemini_quota()
