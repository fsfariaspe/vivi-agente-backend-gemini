import os
import psycopg2
import functions_framework
from flask import jsonify

# --- Configuração do Banco de Dados ---
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# --- Lógica de Conexão ---
conn = None

def get_db_connection():
    global conn
    if conn is None or conn.closed:
        try:
            conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port="5432",
                sslmode="require"
            )
        except Exception as e:
            print(f"❌ Erro CRÍTICO ao conectar ao PostgreSQL: {e}")
            conn = None
    return conn

# Tentamos conectar ao banco assim que a função "acorda"
get_db_connection()


@functions_framework.http
def identificar_cliente(request):
    if conn and not conn.closed:
        texto_resposta = "VITÓRIA! A função iniciou e conseguiu se conectar ao banco de dados!"
    else:
        texto_resposta = "FALHA: A função iniciou, mas a conexão com o banco não foi estabelecida. Verifique os logs."

    response_payload = {
        "fulfillment_response": {
            "messages": [
                {
                    "text": {
                        "text": [texto_resposta]
                    }
                }
            ]
        }
    }
    return jsonify(response_payload)