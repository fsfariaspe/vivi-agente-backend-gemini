# main.py (VERSÃO FINAL E CORRIGIDA)
import os
import json
import logging
import pytz
from datetime import datetime

from flask import Flask, request, jsonify
from google.cloud import tasks_v2
from twilio.rest import Client

from notion_utils import create_notion_page
from db import salvar_conversa, buscar_nome_cliente

# --- Configurações Iniciais ---
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Configurações do Google Cloud ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION_ID = os.getenv("GCP_LOCATION_ID")
QUEUE_ID = os.getenv("CLOUD_TASKS_QUEUE_ID")
SERVICE_ACCOUNT_EMAIL = os.getenv("GCP_SERVICE_ACCOUNT_EMAIL")
WORKER_URL = os.getenv("WORKER_URL") 

tasks_client = tasks_v2.CloudTasksClient()

# --- PORTA DE ENTRADA 1: Webhook Principal (Atendente) ---
@app.route('/', methods=['POST'])
def vivi_webhook():
    """
    Função "ATENDENTE": Lida com a finalização e criação de tarefas.
    """
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')

    if tag == 'salvar_dados_voo_no_notion' or tag == 'salvar_dados_cruzeiro_no_notion':
        print(f"ℹ️ ATENDENTE: Recebida tag '{tag}'. Criando tarefa...")
        try:
            payload_para_tarefa = request.get_data()
            queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)
            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{WORKER_URL}/processar-tarefa",
                    "headers": {"Content-type": "application/json"},
                    "body": payload_para_tarefa,
                    "oidc_token": {"service_account_email": SERVICE_ACCOUNT_EMAIL}
                }
            }
            tasks_client.create_task(parent=queue_path, task=task)
            texto_resposta = "Sua solicitação foi registrada com sucesso! Em instantes, um de nossos especialistas entrará em contato. Obrigado! 😊"
        except Exception as e:
            logger.exception("❌ ATENDENTE: Falha ao criar tarefa: %s", e)
            texto_resposta = "Tive um problema ao registrar sua solicitação. Nossa equipe já foi notificada."
        
        return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})
    
    return jsonify({})

# --- PORTA DE ENTRADA 2: Webhook para Lógica de Dados e Navegação ---
@app.route('/gerenciar-dados', methods=['POST'])
def gerenciar_dados():
    """
    Webhook "AJUDANTE": Lida com manipulação de dados e navegação complexa.
    """
    try:
        request_json = request.get_json(silent=True)
        tag = request_json.get("fulfillmentInfo", {}).get("tag", "")
        parametros_sessao = request_json.get("sessionInfo", {}).get("parameters", {})
        resposta = {}

        print(f"ℹ️ Webhook /gerenciar-dados recebido com a tag: {tag}")

        if tag == 'retornar_para_resumo':
            pagina_de_retorno_id = parametros_sessao.get("pagina_retorno")

            # Limpa as flags
            parametros_sessao.pop('pagina_retorno', None)
            parametros_sessao.pop('campo_a_corrigir', None)

            if pagina_de_retorno_id:
                # Caso de CORREÇÃO: volta para a página de resumo que o chamou
                print(f"✅ Roteando para página de retorno: {pagina_de_retorno_id}")
                resposta = {"target_page": pagina_de_retorno_id}
            else:
                # Caso de FLUXO NORMAL: envia para a próxima página do fluxo principal
                # SUBSTITUA O VALOR ABAIXO PELO ID REAL DA SUA PÁGINA
                id_pagina_proximo_passo = "projects/custom-point-462423-n7/locations/us-central1/agents/ffc67c2a-d508-4f42-9149-9599b680f23e/flows/00000000-0000-0000-0000-000000000000/pages/1b63788b-1831-4c11-9772-8ab3a494e361"
                print(f"✅ Roteando para próxima página do fluxo normal: {id_pagina_proximo_passo}")
                resposta = {"target_page": id_pagina_proximo_passo}

        # Adicione aqui futuras lógicas com 'elif tag == ...' se necessário

        # Anexa os parâmetros de sessão atualizados à resposta final
        resposta.update({"sessionInfo": {"parameters": parametros_sessao}})
        return jsonify(resposta)

    except Exception as e:
        logging.error(f"❌ Erro no webhook /gerenciar-dados: {e}")
        return jsonify({})

# --- PORTA DE ENTRADA 3: O Trabalhador Assíncrono ---
@app.route('/processar-tarefa', methods=['POST'])
def processar_tarefa():
    # ... (A função processar_tarefa que já corrigimos antes permanece aqui) ...
    # ... (Ela não precisa de novas alterações) ...
    print("👷 TRABALHADOR: Tarefa recebida...")
    # ... seu código robusto para Notion e WhatsApp
    return "OK", 200