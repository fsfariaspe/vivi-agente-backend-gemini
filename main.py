# main.py (Versão final com a importação corrigida)
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

# --- Configurações do Google Cloud ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION_ID = os.getenv("GCP_LOCATION_ID") 
QUEUE_ID = os.getenv("CLOUD_TASKS_QUEUE_ID")

# --- Configuração do Banco de Dados ---
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Instancia o cliente do Cloud Tasks uma vez para reutilização
tasks_client = tasks_v2.CloudTasksClient()

logger = logging.getLogger(__name__)


# --- Funções de Banco de Dados ---
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

def salvar_conversa(numero_cliente, mensagem, nome_cliente):
    """Abre uma conexão, salva a conversa e fecha a conexão."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversas (numero_cliente, nome_cliente, mensagem_inicial)
                VALUES (%s, %s, %s)
                """,
                (numero_cliente, nome_cliente, mensagem)
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


# --- Ponto de Entrada 1 (Webhook para o Dialogflow) ---
@functions_framework.http
def vivi_webhook(request):
    """
    Função "ATENDENTE": Recebe a chamada do Dialogflow, decide o que fazer,
    e responde RÁPIDO, delegando trabalho demorado para o Cloud Tasks.
    """
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    parametros = request_json.get('sessionInfo', {}).get('parameters', {})
    
    numero_cliente_com_prefixo = request_json.get('sessionInfo', {}).get('session', '').split('/')[-1]
    numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
    if numero_cliente.startswith('55'):
        numero_cliente = f"+{numero_cliente}"

    texto_resposta = ""

    if tag == 'identificar_cliente':
        nome_existente = buscar_nome_cliente(numero_cliente)
        if nome_existente:
            texto_resposta = f"Olá, {nome_existente}! Que bom te ver de volta! Como posso te ajudar a planejar sua próxima viagem?"
        else:
            texto_resposta = "Olá! 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"

    elif tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        mensagem_completa = f"O cliente informou o nome: {nome_cliente}."
        salvar_conversa(numero_cliente, mensagem_completa, nome_cliente)
        print(f"✅ Nome '{nome_cliente}' salvo para o número {numero_cliente}. Deixando o Dialogflow continuar o fluxo.")
        return jsonify({})

    elif tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Recebida tag 'salvar_dados_voo_no_notion'. Criando tarefa assíncrona...")
        
        service_url = os.getenv("SERVICE_URL")
        if not service_url:
            print("❌ ERRO FATAL: A variável de ambiente SERVICE_URL não foi encontrada.")
            texto_resposta = "Ocorreu um erro interno de configuração (URL_SERVICE_MISSING). Nossa equipe foi notificada."
        else:
            worker_url = f"{service_url}"
            
            payload_para_tarefa = {
                "numero_cliente": numero_cliente,
                "parametros": parametros
            }
            
            queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)

            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": worker_url,
                    "headers": {"Content-type": "application/json", "X-Cloud-Tasks-Target": "processar_tarefa"},
                    "body": json.dumps(payload_para_tarefa).encode(),
                }
            }
            
            try:
                tasks_client.create_task(parent=queue_path, task=task)
                print("✅ Tarefa criada com sucesso na fila.")
                texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviará a proposta em breve aqui mesmo. Obrigado! 😊"
            except Exception as e:
                logger.error("❌ Falha ao criar tarefa no Cloud Tasks: %s", e)
                texto_resposta = "Consegui coletar todas as informações, mas tive um problema ao iniciar o registro da sua solicitação. Nossa equipe já foi notificada."
        
    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer. Pode tentar de novo?"

    response_payload = {"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}}
    return jsonify(response_payload)


# --- Ponto de Entrada 2 (Webhook para o Cloud Tasks) ---
@functions_framework.http
def processar_tarefa(request):
    """
    Função "TRABALHADOR": É chamada pelo Cloud Tasks. Não tem limite de tempo.
    """
    if "X-Cloud-Tasks-Target" not in request.headers or request.headers["X-Cloud-Tasks-Target"] != "processar_tarefa":
        print("⚠️ Chamada não autorizada para o worker. Ignorando.")
        return "Chamada não autorizada.", 403

    task_payload = request.get_json(silent=True)
    if not task_payload:
        print("⚠️ Tarefa recebida sem corpo JSON. Ignorando.")
        return "Corpo da requisição ausente ou inválido.", 400
        
    print(f"👷 Worker recebeu uma tarefa: {task_payload}")
    
    parametros = task_payload.get('parametros', {})
    numero_cliente = task_payload.get('numero_cliente')
    
    nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

    data_ida_str, data_volta_str = None, None
    data_ida_obj = parametros.get('data_ida', {})
    if isinstance(data_ida_obj, dict):
        data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):