import os
import json
import logging
import pytz
from datetime import datetime

import functions_framework
from flask import jsonify
import psycopg2

from google.cloud import tasks_v2
from notion_utils import create_notion_page
from db import salvar_conversa, buscar_nome_cliente

# Cloud Tasks configuration
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION_ID = os.getenv("GCP_LOCATION_ID") 
QUEUE_ID = os.getenv("CLOUD_TASKS_QUEUE_ID")

tasks_client = tasks_v2.CloudTasksClient()

logger = logging.getLogger(__name__)

# Main entry point for Dialogflow
@functions_framework.http
def vivi_webhook(request):
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
        texto_resposta = f"Olá, {nome_existente}! Que bom te ver de volta! Como posso te ajudar?" if nome_existente else "Olá! 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"

    elif tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        salvar_conversa(numero_cliente, f"O cliente informou o nome: {nome_cliente}.", nome_cliente)
        return jsonify({})

    elif tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Tag 'salvar_dados_voo_no_notion' recebida. Criando tarefa assíncrona...")
        
        service_url = os.getenv("SERVICE_URL")
        if not service_url:
            texto_resposta = "Ocorreu um erro interno de configuração (URL_SERVICE_MISSING)."
        else:
            worker_url = f"{service_url}"
            payload_para_tarefa = {"numero_cliente": numero_cliente, "parametros": parametros}
            queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)
            task = { "http_request": { "http_method": tasks_v2.HttpMethod.POST, "url": worker_url, "headers": {"Content-type": "application/json", "X-Cloud-Tasks-Target": "processar_tarefa"}, "body": json.dumps(payload_para_tarefa).encode() } }
            
            try:
                tasks_client.create_task(parent=queue_path, task=task)
                texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviar a proposta em breve aqui mesmo. Obrigado! 😊"
            except Exception as e:
                logger.exception("❌ Falha ao criar tarefa no Cloud Tasks: %s", e)
                texto_resposta = "Consegui coletar todas as informações, mas tive um problema ao iniciar o registro da sua solicitação. Nossa equipe já foi notificada."
        
    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer."

    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})

# Worker entry point for Cloud Tasks
@functions_framework.http
def processar_tarefa(request):
    if "X-Cloud-Tasks-Target" not in request.headers or request.headers["X-Cloud-Tasks-Target"] != "processar_tarefa":
        return "Chamada não autorizada.", 403

    task_payload = request.get_json(silent=True)
    if not task_payload:
        return "Corpo da requisição ausente ou inválido.", 400
        
    print(f"👷 Worker recebeu uma tarefa: {task_payload}")
    
    parametros = task_payload.get('parametros', {})
    numero_cliente = task_payload.get('numero_cliente')
    
    nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

    # --- LÓGICA DE FORMATAÇÃO FINAL E CORRIGIDA ---
    data_ida_str, data_volta_str = None, None
    data_ida_obj = parametros.get('data_ida', {})
    if isinstance(data_ida_obj, dict):
        data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):02d}-{int(data_ida_obj.get('day')):02d}"
    
    data_volta_obj = parametros.get('data_volta')
    # AQUI ESTÁ A VERIFICAÇÃO QUE FALTAVA
    if isinstance(data_volta_obj, dict):
        data_volta_str = f"{int(data_volta_obj.get('year'))}-{int(data_volta_obj.get('month')):02d}-{int(data_volta_obj.get('day')):02d}"
    
    timestamp_contato = datetime.now(pytz.timezone("America/Recife")).isoformat()
    
    origem_nome = parametros.get('origem', {}).get('original', '')
    destino_nome = parametros.get('destino', {}).get('original', '')

    dados_para_notion = {
        "data_contato": timestamp_contato, "nome_cliente": nome_cliente, "whatsapp_cliente": numero_cliente,
        "tipo_viagem": "Passagem Aérea", "origem_destino": f"{origem_nome} → {destino_nome}",
        "data_ida": data_ida_str, "data_volta": data_volta_str, "qtd_passageiros": str(parametros.get('passageiros', '')),
        "perfil_viagem": parametros.get('perfil_viagem', ''), "preferencias": parametros.get('preferencias', '')
    }
    
    print(f"📄 Enviando para o Notion: {dados_para_notion}")
    
    notion_response, status_code = create_notion_page(dados_para_notion)
    
    if 200 <= status_code < 300:
        print("✅ Tarefa concluída. Página criada no Notion.")
        return "OK", 200
    else:
        print(f"🚨 Falha ao processar tarefa. Status do Notion: {status_code}.")
        return "Erro ao criar página no Notion", 500