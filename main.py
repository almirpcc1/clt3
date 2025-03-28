from dotenv import load_dotenv
import os

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
