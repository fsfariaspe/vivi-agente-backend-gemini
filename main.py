# main.py (VERSÃO ASSÍNCRONA FINAL com Flask e Twilio)
import os
import json
import logging
import pytz
from datetime import datetime

from flask import Flask, request, jsonify
from google.cloud import tasks_v2
from twilio.rest import Client
import psycopg2

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
WORKER_URL = os.getenv("WORKER_URL") # URL do nosso próprio serviço, configurada no Cloud Run

tasks_client = tasks_v2.CloudTasksClient()

# --- PORTA DE ENTRADA 1: Webhook para o Dialogflow ---
@app.route('/', methods=['POST'])
def vivi_webhook():
    """
    Função "ATENDENTE": Chamada APENAS pelo Dialogflow.
    Responde rápido e delega o trabalho demorado.
    """
    request_json = request.get_json(silent=True)
    if not request_json:
        logger.error("Requisição sem corpo JSON ou malformado.")
        return jsonify({"error": "Invalid JSON"}), 400

    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    parametros = request_json.get('sessionInfo', {}).get('parameters', {})
    
    numero_cliente_com_prefixo = request_json.get('sessionInfo', {}).get('session', '').split('/')[-1]
    numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
    if numero_cliente.startswith('55'):
        numero_cliente = f"+{numero_cliente}"
    
    # --- Lógica para salvar o nome (continua síncrona e rápida) ---
    if tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        salvar_conversa(numero_cliente, f"O cliente informou o nome: {nome_cliente}.", nome_cliente)
        print(f"✅ Nome '{nome_cliente}' salvo para o número {numero_cliente}.")
        return jsonify({})

    # --- Lógica para criar a tarefa assíncrona ---
    elif tag == 'salvar_dados_voo_no_notion': # A tag continua com o mesmo nome, mas a ação agora é outra
        print("ℹ️ ATENDENTE: Recebida tag 'salvar_dados_voo_no_notion'. Criando tarefa para notificação...")
        
        if not WORKER_URL:
            texto_resposta = "Ocorreu um erro de configuração (WORKER_URL não definida)."
        else:
            payload_para_tarefa = request.get_data()
            queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)

            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": WORKER_URL,
                    "headers": {"Content-type": "application/json"},
                    "body": payload_para_tarefa,
                    "oidc_token": {"service_account_email": SERVICE_ACCOUNT_EMAIL}
                }
            }
            try:
                tasks_client.create_task(parent=queue_path, task=task)
                print("✅ ATENDENTE: Tarefa de notificação criada com sucesso na fila.")
                texto_resposta = "Sua solicitação foi registrada com sucesso! Em instantes, um de nossos especialistas entrará em contato para te enviar a proposta. Obrigado! 😊"
            except Exception as e:
                logger.exception("❌ ATENDENTE: Falha ao criar tarefa no Cloud Tasks: %s", e)
                texto_resposta = "Tive um problema ao iniciar o registro da sua solicitação. Nossa equipe já foi notificada."
        
        return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})

    # --- Resposta padrão para outras tags ---
    texto_resposta = "Desculpe, não entendi o que preciso fazer."
    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})


# --- PORTA DE ENTRADA 2: Rota para o Trabalhador do Cloud Tasks ---
@app.route('/processar-tarefa', methods=['POST'])
def processar_tarefa():
    """
    Função "TRABALHADOR": Chamada pelo Cloud Tasks para enviar a notificação.
    """
    print("👷 TRABALHADOR: Tarefa recebida do Cloud Tasks. Preparando para enviar WhatsApp...")
    
    task_payload = request.get_json(silent=True)
    if not task_payload:
        print("🚨 TRABALHADOR: Corpo da tarefa inválido.")
        return "Corpo da tarefa inválido.", 400

    parametros = task_payload.get('sessionInfo', {}).get('parameters', {})
    
    # Prepara as variáveis para o template do WhatsApp
    nome_cliente = parametros.get('person', {}).get('name', 'Não informado')
    origem = parametros.get('origem', {}).get('original', 'N/D')
    destino = parametros.get('destino', {}).get('original', 'N/D')
    detalhes_viagem = f"{origem} → {destino}"

    content_variables = json.dumps({
        '1': nome_cliente,
        '2': "Passagem Aérea",
        '3': detalhes_viagem
    })

    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        twilio_client = Client(account_sid, auth_token)

        # IMPORTANTE: Substitua pelo SID do seu template aprovado!
        template_sid = "HXcae96a3b4d4f7c754df1d850be70038e" 

        message = twilio_client.messages.create(
            content_sid=template_sid,
            from_=os.getenv("TWILIO_WHATSAPP_FROM"),
            content_variables=content_variables,
            to=os.getenv("MEU_WHATSAPP_TO")
        )
        print(f"✅ Notificação por WhatsApp enviada com sucesso! SID: {message.sid}")
        return "OK", 200

    except Exception as e:
        logger.exception("🚨 TRABALHADOR: Falha ao enviar notificação via Twilio: %s", e)
        return "Erro ao enviar WhatsApp", 500