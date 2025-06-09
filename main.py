import os
import psycopg2
import functions_framework
from flask import jsonify

# --- Configuração do Banco de Dados ---
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# --- Lógica de Conexão Otimizada ---
conn = None

def get_db_connection():
    """Retorna uma conexão com o banco de dados, criando uma se não existir."""
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
            print("🟢 Conexão com o PostgreSQL estabelecida.")
        except Exception as e:
            print(f"❌ Erro CRÍTICO ao conectar ao PostgreSQL: {e}")
            conn = None
    return conn

# Inicializa a conexão na primeira execução
get_db_connection()


@functions_framework.http
def identificar_cliente(request):
    """
    Função final: acionada pelo Dialogflow, verifica se o cliente é recorrente
    no banco de dados e retorna a saudação apropriada.
    """
    texto_resposta = "" # Variável para armazenar nossa resposta final
    
    try:
        # Pega o número de telefone do payload enviado pelo Dialogflow
        session_path = request.get_json(silent=True).get('sessionInfo', {}).get('session', '')
        numero_cliente_com_prefixo = session_path.split('/')[-1]
        
        # Limpa o número para consulta no banco
        numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
        if numero_cliente.startswith('55'): # Lógica para formatar para o padrão E.164
            numero_cliente = f"+{numero_cliente}"

        print(f"🔎 Verificando cliente para o número: {numero_cliente}")

        db_conn = get_db_connection()
        if db_conn:
            cur = db_conn.cursor()
            # Busca o nome do cliente mais recente para este número
            cur.execute(
                "SELECT nome_cliente FROM conversas WHERE numero_cliente = %s AND nome_cliente IS NOT NULL ORDER BY data_inicio DESC LIMIT 1",
                (numero_cliente,)
            )
            resultado = cur.fetchone()
            cur.close()

            if resultado and resultado[0]:
                nome_cliente = resultado[0]
                print(f"✅ Cliente encontrado: {nome_cliente}")
                texto_resposta = f"Olá, {nome_cliente}! Que bom te ver de volta aqui na Viaje Fácil Brasil 😊 Como posso te ajudar a planejar sua próxima viagem?"
            else:
                print("⚠️ Cliente não encontrado no banco. Usando saudação padrão.")
                texto_resposta = "Olá! Que bom te ver por aqui 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"
        else:
            # Fallback caso a conexão com o banco tenha falhado na inicialização
            print("⚠️ Conexão com o banco indisponível. Usando saudação de fallback.")
            texto_resposta = "Olá! Eu sou a Vivi, sua consultora de viagens virtual. Como posso te ajudar?"

    except Exception as e:
        print(f"❌ Erro inesperado na execução da função: {e}")
        texto_resposta = "Olá! Sou a Vivi. Parece que estou com um pequeno problema em meus sistemas, mas me diga, como posso te ajudar hoje?"

    # Monta a resposta final no formato que o Dialogflow espera
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