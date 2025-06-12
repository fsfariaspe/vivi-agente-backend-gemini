import os
import json
import logging
import pytz
from datetime import datetime

import functions_framework
from flask import jsonify
import psycopg2

# Importa a biblioteca do Cloud Tasks
from google.cloud import tasks_v2

# Importa nossa função de utilidade do Notion
from notion_utils import create_notion_page


# --- Configuração do Banco de Dados ---
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# --- Configurações do Cloud Tasks ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION_ID = os.getenv("GCP_LOCATION_ID") # ex: southamerica-east1
QUEUE_ID = os.getenv("CLOUD_TASKS_QUEUE_ID") # ex: fila-notion

# Instancia o cliente do Cloud Tasks uma vez para reutilização
tasks_client = tasks_v2.CloudTasksClient()
# Monta o caminho completo da fila
queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)

logger = logging.getLogger(__name__)


# --- Funções de Banco de Dados (Agora dentro do main.py) ---

def get_db_connection():
    """Cria e retorna uma nova conexão com o banco de dados."""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
            host=DB_HOST, port="5432", sslmode="require"
        )
        return conn
    except Exception as e:
        logger.error(f"❌ Erro ao criar conexão com o banco de dados: {e}")
        return None

def salvar_conversa(numero_cliente, mensagem, nome_cliente, thread_id=None):
    """Abre uma conexão, salva a conversa e fecha a conexão."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversas (numero_cliente, nome_cliente, mensagem_inicial, openai_thread_id)
                VALUES (%s, %s, %s, %s)
                """,
                (numero_cliente, nome_cliente, mensagem, thread_id)
            )
            conn.commit()
            logger.info("💾 Conversa salva para o cliente: %s", nome_cliente)
    except Exception as e:
        logger.error(f"❌ Erro ao salvar conversa no banco: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()

def buscar_nome_cliente(numero_cliente):
    """Abre uma conexão, busca o nome mais recente e fecha a conexão."""
    conn = get_db_connection()
    if not conn:
        return None
    nome = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nome_cliente FROM conversas WHERE numero_cliente = %s AND nome_cliente IS NOT NULL ORDER BY data_inicio DESC LIMIT 1",
                (numero_cliente,)
            )
            resultado = cur.fetchone()
            if resultado:
                nome = resultado[0]
    except Exception as e:
        logger.error(f"❌ Erro ao buscar nome do cliente: {e}")
    finally:
        if conn:
            conn.close()
    return nome


# --- Ponto de Entrada Principal (Webhook para o Dialogflow) ---

@functions_framework.http
def vivi_webhook(request):
    """
    Função "ATENDENTE": Recebe a chamada do Dialogflow, decide o que fazer,
    e responde RÁPIDO.
    """
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    parametros = request_json.get('sessionInfo', {}).get('parameters', {})
    
    numero_cliente_com_prefixo = request_json.get('sessionInfo', {}).get('session', '').split('/')[-1]
    numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
    if numero_cliente.startswith('55'):
        numero_cliente = f"+{numero_cliente}"

    texto_resposta = ""

    # AÇÃO 1: Identificar o cliente no início da conversa
    if tag == 'identificar_cliente':
        nome_existente = buscar_nome_cliente(numero_cliente)
        if nome_existente:
            texto_resposta = f"Olá, {nome_existente}! Que bom te ver de volta! Como posso te ajudar a planejar sua próxima viagem?"
        else:
            texto_resposta = "Olá! 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"

    # AÇÃO 2: Salvar o nome e deixar o Dialogflow fazer a próxima pergunta
    elif tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        mensagem_completa = f"O cliente informou o nome: {nome_cliente}."
        salvar_conversa(numero_cliente, mensagem_completa, nome_cliente)
        print(f"✅ Nome '{nome_cliente}' salvo para o número {numero_cliente}. Deixando o Dialogflow continuar o fluxo.")
        return jsonify({})

    # AÇÃO 3 (AGORA ASSÍNCRONA): Recebe os dados e CRIA UMA TAREFA
    elif tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Recebida tag 'salvar_dados_voo_no_notion'. Criando tarefa assíncrona...")
        
        # O Google Cloud define esta variável automaticamente com o URL do nosso serviço.
        # Adicionamos o caminho para a nossa função 'worker'.
        service_url = os.getenv("SERVICE_URL")
        worker_url = f"{service_url}/processar_tarefa"
        
        # O corpo da tarefa será o JSON completo dos parâmetros que o Dialogflow coletou
        payload = {
            "numero_cliente": numero_cliente,
            "parametros": parametros
        }

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": worker_url,
                "headers": {"Content-type": "application/json"},
                "body": json.dumps(payload).encode(),
            }
        }
        
        try:
            tasks_client.create_task(parent=queue_path, task=task)
            print("✅ Tarefa criada com sucesso na fila.")
        except Exception as e:
            logger.error("❌ Falha ao criar tarefa no Cloud Tasks: %s", e)

        # Responde IMEDIATAMENTE para o Dialogflow, sem esperar o Notion
        texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviará a proposta em breve aqui mesmo. Obrigado! 😊"

    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer. Pode tentar de novo?"

    response_payload = {
        "fulfillment_response": {
            "messages": [{"text": {"text": [texto_resposta]}}]
        }
    }
    return jsonify(response_payload)


# --- Ponto de Entrada SECUNDÁRIO (Webhook para o Cloud Tasks) ---

@functions_framework.http
def processar_tarefa(request):
    """
    Função "TRABALHADOR": É chamada pelo Cloud Tasks. Não tem limite de tempo.
    Recebe os dados de uma tarefa e executa o trabalho demorado.
    """
    if request.method != "POST":
        return "Método não permitido", 405

    task_payload = request.get_json(silent=True)
    print(f"👷 Worker recebeu uma tarefa: {task_payload}")
    
    parametros = task_payload.get('parametros', {})
    numero_cliente = task_payload.get('numero_cliente')
    
    nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

    # Formata as datas com segurança
    data_ida_str = None
    data_ida_obj = parametros.get('data_ida', {})
    if isinstance(data_ida_obj, dict):
        data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):02d}-{int(data_ida_obj.get('day')):02d}"

    data_volta_str = None
    data_volta_obj = parametros.get('data_volta')
    if isinstance(data_volta_obj, dict):
        data_volta_str = f"{int(data_volta_obj.get('year'))}-{int(data_volta_obj.get('month')):02d}-{int(data_volta_obj.get('day')):02d}"
    
    fuso_horario_recife = pytz.timezone("America/Recife") 
    timestamp_contato = datetime.now(fuso_horario_recife).isoformat()
    
    origem_nome = parametros.get('origem', {}).get('original', '')
    destino_nome = parametros.get('destino', {}).get('original', '')

    dados_para_notion = {
        "data_contato": timestamp_contato,
        "nome_cliente": nome_cliente,
        "whatsapp_cliente": numero_cliente,
        "tipo_viagem": "Passagem Aérea",
        "origem_destino": f"{origem_nome} → {destino_nome}",
        "data_ida": data_ida_str,
        "data_volta": data_volta_str,
        "qtd_passageiros": parametros.get('passageiros', ''),
        "perfil_viagem": parametros.get('perfil_viagem', ''),
        "preferencias": parametros.get('preferencias', '')
    }
    
    print(f"📄 Enviando para o Notion: {dados_para_notion}")
    
    create_notion_page(dados_para_notion)
    
    # Retorna uma resposta 200 OK para o Cloud Tasks saber que a tarefa foi concluída.
    return "OK", 200