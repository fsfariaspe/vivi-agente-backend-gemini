# main.py (VERSÃO ASSÍNCRONA FINAL com Flask)
import os
import json
import logging
import pytz
from datetime import datetime
from twilio.rest import Client

from flask import Flask, request, jsonify
from google.cloud import tasks_v2
import psycopg2

from notion_utils import create_notion_page
from db import salvar_conversa, buscar_nome_cliente

# --- Configurações Iniciais ---
logger = logging.getLogger(__name__)

# 1. Inicializa a aplicação Flask
app = Flask(__name__)

# 2. Configurações do Google Cloud
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION_ID = os.getenv("GCP_LOCATION_ID")
QUEUE_ID = os.getenv("CLOUD_TASKS_QUEUE_ID")
SERVICE_ACCOUNT_EMAIL = os.getenv("GCP_SERVICE_ACCOUNT_EMAIL")
tasks_client = tasks_v2.CloudTasksClient()


# --- PORTA DE ENTRADA 1: Webhook para o Dialogflow ---
@app.route('/', methods=['POST'])
def vivi_webhook():
    """
    Função "ATENDENTE": Chamada APENAS pelo Dialogflow.
    Responde rápido e delega o trabalho demorado.
    """
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    
    # ... (A lógica para 'identificar_cliente' e 'salvar_nome' continua a mesma) ...
    
    if tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Tag 'salvar_dados_voo_no_notion' recebida. Criando tarefa assíncrona...")

        # --- MUDANÇA AQUI: URL FIXA (HARDCODED) ---
        # SUBSTITUA PELA URL COMPLETA DO SEU SERVIÇO CLOUD RUN
        service_url = "https://vivi-agente-backend-gemini-zh35efzi7a-rj.a.run.app"
        worker_url = service_url.replace("http://", "https://", 1) # Garante HTTPS

        # Adicionamos o caminho para a rota do worker
        if not worker_url.endswith('/processar-tarefa'):
            worker_url += "/processar-tarefa"

        payload_para_tarefa = request.get_data()
        queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)

        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": worker_url,
                "headers": {"Content-type": "application/json"},
                "body": payload_para_tarefa,
                "oidc_token": {"service_account_email": SERVICE_ACCOUNT_EMAIL}
            }
        }

        try:
            tasks_client.create_task(parent=queue_path, task=task)
            print("✅ Tarefa criada com sucesso na fila.")
            texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviará a proposta em breve aqui mesmo. Obrigado! 😊"
        except Exception as e:
            logger.exception("❌ Falha ao criar tarefa no Cloud Tasks: %s", e)
            texto_resposta = "Consegui coletar todas as informações, mas tive um problema ao iniciar o registro da sua solicitação. Nossa equipe já foi notificada."

        return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})
    
    # Se nenhuma tag corresponder, pode adicionar um retorno padrão aqui
    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": ["Não entendi o que preciso fazer."]}}]}})


# --- PORTA DE ENTRADA 2: Rota para o Trabalhador do Cloud Tasks ---
@functions_framework.http
def processar_tarefa(request):
    """
    Função "TRABALHADOR": agora vai enviar uma notificação por WhatsApp.
    """
    # Verificação de segurança para garantir que a chamada veio do Cloud Tasks
    if "X-Cloud-Tasks-Target" not in request.headers or request.headers["X-Cloud-Tasks-Target"] != "processar_tarefa":
        print("⚠️ Chamada não autorizada para o worker. Ignorando.")
        return "Chamada não autorizada.", 403

    task_payload = request.get_json(silent=True)
    if not task_payload:
        print("🚨 TRABALHADOR: Corpo da requisição da tarefa ausente ou inválido.")
        return "Corpo da tarefa inválido.", 400
        
    print(f"👷 Worker recebeu uma tarefa para enviar WhatsApp: {task_payload}")
    
    # Extrai os dados que queremos enviar na notificação
    parametros = task_payload.get('sessionInfo', {}).get('parameters', {})
    
    # Monta uma mensagem de notificação clara
    nome_cliente = parametros.get('person', {}).get('name', 'Não informado')
    origem = parametros.get('origem', {}).get('original', 'N/D')
    destino = parametros.get('destino', {}).get('original', 'N/D')
    
    data_ida_str = "N/D"
    data_ida_obj = parametros.get('data_ida', {})
    if isinstance(data_ida_obj, dict):
        data_ida_str = f"{int(data_ida_obj.get('day'))}/{int(data_ida_obj.get('month'))}"

    mensagem_notificacao = (
        f"🔔 *Novo Lead Recebido pela Vivi!* 🔔\n\n"
        f"*Cliente:* {nome_cliente}\n"
        f"*Trecho:* {origem} → {destino}\n"
        f"*Data de Ida:* {data_ida_str}\n\n"
        f"Entrar em contato para continuar o atendimento."
    )
    
    # Configura e envia a mensagem via Twilio
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        twilio_client = Client(account_sid, auth_token)

        message = twilio_client.messages.create(
            from_=os.getenv("TWILIO_WHATSAPP_FROM"),
            body=mensagem_notificacao,
            to=os.getenv("MEU_WHATSAPP_TO")
        )
        print(f"✅ Notificação por WhatsApp enviada com sucesso! SID: {message.sid}")
        return "OK", 200 # Informa ao Cloud Tasks que a tarefa foi um sucesso

    except Exception as e:
        logger.exception("🚨 Falha ao enviar notificação por WhatsApp via Twilio: %s", e)
        # Retorna um erro para que o Cloud Tasks possa tentar novamente (se configurado na fila)
        return "Erro ao enviar WhatsApp", 500