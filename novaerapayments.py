import os
import requests
from typing import Dict, Any, Optional
from datetime import datetime
import random
import string
from flask import current_app


class NovaEraPaymentsAPI:
    API_URL = "https://api.novaera-pagamentos.com/api/v1"

    def __init__(self, authorization_token: str):
        self.authorization_token = authorization_token

    def _get_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Basic {self.authorization_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def _generate_random_email(self, name: str) -> str:
        clean_name = ''.join(e.lower() for e in name if e.isalnum())
        random_num = ''.join(random.choices(string.digits, k=4))
        domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
        domain = random.choice(domains)
        return f"{clean_name}{random_num}@{domain}"

    def _generate_random_phone(self) -> str:
        ddd = str(random.randint(11, 99))
        number = ''.join(random.choices(string.digits, k=8))
        return f"{ddd}{number}"

    def create_pix_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a PIX payment request"""
        if not self.authorization_token or len(self.authorization_token) < 10:
            raise ValueError("Token de autenticação inválido")

        required_fields = ['name', 'email', 'cpf', 'amount']
        for field in required_fields:
            if field not in data or not data[field]:
                raise ValueError(f"Campo obrigatório ausente: {field}")

        try:
            amount_in_cents = int(float(data['amount']) * 100)
            if amount_in_cents <= 0:
                raise ValueError("Valor do pagamento deve ser maior que zero")

            cpf = ''.join(filter(str.isdigit, data['cpf']))
            if len(cpf) != 11:
                raise ValueError("CPF inválido")

            email = data.get('email')
            if not email or '@' not in email:
                email = self._generate_random_email(data['name'])

            # Use the provided phone number if it exists, otherwise generate random
            phone = data.get('phone')
            if not phone or len(phone.strip()) < 10:
                phone = self._generate_random_phone()
                current_app.logger.info(f"Telefone não fornecido ou inválido, gerando aleatório: {phone}")
            else:
                # Remove any non-digit characters from the phone
                phone = ''.join(filter(str.isdigit, phone))
                current_app.logger.info(f"Usando telefone fornecido pelo usuário: {phone}")

            payment_data = {
                "customer": {
                    "name": data['name'],
                    "email": email,
                    "phone": phone,
                    "document": {
                        "type": "cpf",
                        "number": cpf
                    }
                },
                "shipping": {
                    "fee": 0,
                    "address": {
                        "street": "Rua Ângelo Pessotti",
                        "streetNumber": "1",
                        "neighborhood": "Segato",
                        "city": "Aracruz",
                        "state": "ES",
                        "zipCode": "70655054",
                        "complement": "32"
                    }
                },
                "pix": {
                    "expiresInDays": 30
                },
                "amount": amount_in_cents,
                "paymentMethod": "pix",
                "items": [{
                    "tangible": True,
                    "title": "Limpa Nome",
                    "unitPrice": amount_in_cents,
                    "quantity": 1
                }]
            }

            # Envia a requisição para a API Nova Era
            try:
                response = requests.post(
                    f"{self.API_URL}/transactions",
                    json=payment_data,
                    headers=self._get_headers(),
                    timeout=30
                )

                if response.status_code == 200:
                    response_data = response.json()
                    return {
                        'id': response_data['data']['id'],
                        'status': response_data['data']['status'],
                        'amount': response_data['data']['amount'],
                        'pix_qr_code': f"https://api.qrserver.com/v1/create-qr-code/?data={response_data['data']['pix']['qrcode']}&size=300x300",
                        'pix_code': response_data['data']['pix']['qrcode'],
                        'expires_at': response_data['data']['pix']['expirationDate'],
                        'secure_url': response_data['data']['secureUrl']
                    }
                else:
                    raise ValueError(f"Erro ao processar pagamento: {response.status_code} - {response.text}")

            except requests.exceptions.RequestException as e:
                raise ValueError(f"Erro de conexão com o serviço de pagamento. Tente novamente. Detalhes: {str(e)}")

        except ValueError as e:
            raise ValueError(f"Erro de validação: {str(e)}")
        except Exception as e:
            raise ValueError(f"Erro inesperado ao processar pagamento: {str(e)}")

    def check_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Check the status of a payment"""
        try:
            response = requests.get(
                f"{self.API_URL}/transactions/{payment_id}",
                headers=self._get_headers(),
                timeout=30
            )

            if response.status_code == 200:
                payment_data = response.json()
                return {
                    'status': payment_data['data']['status'],
                    'pix_qr_code': payment_data['data']['pix']['qrcode'],
                    'pix_code': payment_data['data']['pix']['qrcode']
                }
            else:
                return {'status': 'pending'}

        except Exception:
            return {'status': 'pending'}


def create_payment_api(authorization_token: Optional[str] = None) -> NovaEraPaymentsAPI:
    """Factory function to create NovaEraPaymentsAPI instance"""
    if authorization_token is None:
        authorization_token = os.environ.get("NOVAERA_PAYMENT_TOKEN")
        if not authorization_token:
            raise ValueError("NOVAERA_PAYMENT_TOKEN não configurado no ambiente")
    return NovaEraPaymentsAPI(authorization_token)