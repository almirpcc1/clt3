#!/bin/bash

# Cores para saída
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===== Testando restrição de domínio =====\n${NC}"

# URL base para teste - use a URL do seu ambiente
if [ -z "$1" ]; then
  BASE_URL="http://127.0.0.1:5000"
else
  BASE_URL="$1"
fi

echo -e "${BLUE}Testando URL: ${BASE_URL}${NC}\n"

# Teste 1: Sem referer
echo -e "${BLUE}Teste 1: Requisição sem referer${NC}"
response=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/")
if [ "$response" == "200" ]; then
  echo -e "${GREEN}✓ Acesso permitido (código: ${response})${NC}"
else
  echo -e "${RED}✗ Acesso bloqueado (código: ${response})${NC}"
fi

# Teste 2: Com referer autorizado
echo -e "\n${BLUE}Teste 2: Requisição com referer autorizado${NC}"
response=$(curl -s -o /dev/null -w "%{http_code}" -H "Referer: https://globo.noticiario-plantao.com/noticia" "${BASE_URL}/")
if [ "$response" == "200" ]; then
  echo -e "${GREEN}✓ Acesso permitido (código: ${response})${NC}"
else
  echo -e "${RED}✗ Acesso bloqueado (código: ${response})${NC}"
fi

# Teste 3: Com referer não autorizado
echo -e "\n${BLUE}Teste 3: Requisição com referer não autorizado${NC}"
response=$(curl -s -o /dev/null -w "%{http_code}" -H "Referer: https://google.com" "${BASE_URL}/")
if [ "$response" == "200" ]; then
  echo -e "${GREEN}✓ Acesso permitido (código: ${response})${NC}"
else
  echo -e "${RED}✗ Acesso bloqueado (código: ${response})${NC}"
fi

# Instruções para testes em produção
echo -e "\n${BLUE}Para testar simulando ambiente de produção:${NC}"
echo -e "FORCE_DOMAIN_CHECK=True python app.py"
echo -e "# Em outra janela de terminal:"
echo -e "bash $0 http://127.0.0.1:5000"