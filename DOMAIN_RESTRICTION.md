# Guia de Restrição de Domínio

Este documento explica como configurar e testar a funcionalidade de restrição de domínio na aplicação PIX Payment System.

## Como Funciona

A aplicação implementa uma proteção por referrer (origem da requisição), permitindo que apenas requisições vindas de domínios autorizados possam acessar o sistema. Atualmente, o único domínio autorizado é:

```
https://g1globo.noticiario-plantao.com/noticia
```

## Configuração

A funcionalidade é controlada por um decorator `check_referer` que verifica a origem (referer) de cada requisição HTTP.

### Variáveis de Ambiente

- `FORCE_DOMAIN_CHECK`: Quando definido como `True`, força a verificação de domínio mesmo em ambientes de desenvolvimento. Por padrão, esta verificação é desabilitada em ambiente de desenvolvimento local (Replit).

### Configuração para Produção

O arquivo `Procfile` já está configurado para ativar automaticamente a verificação em ambiente de produção:

```
web: FORCE_DOMAIN_CHECK=True gunicorn app:app
```

### Testando Localmente

Para testar a funcionalidade localmente (no ambiente Replit):

1. **Modo de Desenvolvimento (padrão)**: O sistema permite qualquer acesso para facilitar o desenvolvimento.

2. **Simular Modo de Produção**: Para testar a proteção como se estivesse em produção, defina a variável de ambiente:
   ```bash
   FORCE_DOMAIN_CHECK=True python app.py
   ```

## Script de Teste

Use o script `test_referer.py` para verificar o comportamento da restrição:

```bash
python test_referer.py [URL_BASE]
```

O script testa três cenários:
1. Requisição sem referer
2. Requisição com referer autorizado
3. Requisição com referer não autorizado

## Comportamento Esperado

- **Em Produção**: Somente requisições de `https://g1globo.noticiario-plantao.com/noticia` serão aceitas.
- **Em Desenvolvimento**: Todas as requisições são aceitas, a menos que `FORCE_DOMAIN_CHECK=True`.

## Solução de Problemas

Se o site estiver bloqueando incorretamente o acesso em produção:

1. Verifique os logs para confirmar se a restrição está ativada
2. Verifique se o cabeçalho Referer está sendo enviado corretamente
3. Confirme que o domínio autorizado é exatamente o esperado

Se precisar desativar temporariamente a restrição em produção, remova a variável `FORCE_DOMAIN_CHECK` do Procfile.