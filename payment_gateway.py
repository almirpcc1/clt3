import os
from novaerapayments import NovaEraPaymentsAPI, create_payment_api as create_novaera_api
from for4payments import For4PaymentsAPI, create_payment_api as create_for4_api
from typing import Union

def get_payment_gateway() -> Union[NovaEraPaymentsAPI, For4PaymentsAPI]:
    """Factory function to create the appropriate payment gateway instance based on GATEWAY_CHOICE"""
    gateway_choice = os.environ.get("GATEWAY_CHOICE", "FOR4").upper()
    
    if gateway_choice == "NOVAERA":
        return create_novaera_api()
    elif gateway_choice == "FOR4":
        return create_for4_api()
    else:
        raise ValueError("GATEWAY_CHOICE must be either 'NOVAERA' or 'FOR4'")
