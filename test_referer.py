import requests
import sys

def test_domain_restriction(url, referer=None):
    """Teste para verificar se a restrição de domínio está funcionando corretamente."""
    headers = {}
    if referer:
        headers['Referer'] = referer
    
    response = requests.get(url, headers=headers)
    print(f"URL: {url}")
    print(f"Referer: {referer}")
    print(f"Status code: {response.status_code}")
    
    if response.status_code == 200:
        print("Acesso permitido!")
    else:
        print("Acesso bloqueado! Código de resposta:", response.status_code)
    
    return response.status_code

if __name__ == "__main__":
    # URL base para teste
    base_url = "http://127.0.0.1:5000"
    
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    
    # 1. Teste sem referer (deve bloquear em produção)
    test_domain_restriction(f"{base_url}/")
    
    # 2. Teste com referer autorizado (deve permitir)
    test_domain_restriction(f"{base_url}/", "https://g1globo.noticiario-plantao.com/noticia")
    
    # 3. Teste com referer não autorizado (deve bloquear)
    test_domain_restriction(f"{base_url}/", "https://google.com")