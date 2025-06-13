# main.py (VERSÃO ASSÍNCRONA FINAL com Flask)
import os
import json
import logging
import pytz
from datetime import datetime

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
        print("ℹ️ ATENDENTE: Recebida tag 'salvar_dados_voo_no_notion'. Criando tarefa...")
        
        service_url = os.getenv("SERVICE_URL")
        if not all([service_url, PROJECT_ID, LOCATION_ID, QUEUE_ID, SERVICE_ACCOUNT_EMAIL]):
            print("❌ ATENDENTE: Faltando variáveis de ambiente para o Cloud Tasks.")
            texto_resposta = "Ocorreu um erro interno de configuração para processar sua solicitação."
        else:
            # Garante que a URL sempre use HTTPS
            worker_url = service_url.replace("http://", "https://", 1) + "/processar-tarefa"
            
            payload_para_tarefa = request.get_data()
            queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)

            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": worker_url, # Aponta para a nova porta do trabalhador
                    "headers": {"Content-type": "application/json"},
                    "body": payload_para_tarefa,
                    "oidc_token": {"service_account_email": SERVICE_ACCOUNT_EMAIL}
                }
            }
            try:
                tasks_client.create_task(parent=queue_path, task=task)
                print("✅ ATENDENTE: Tarefa criada com sucesso na fila.")
                texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviará a proposta em breve aqui mesmo. Obrigado! 😊"
            except Exception as e:
                logger.exception("❌ ATENDENTE: Falha ao criar tarefa no Cloud Tasks: %s", e)
                texto_resposta = "Tive um problema ao iniciar o registro da sua solicitação. Nossa equipe já foi notificada."

        return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})
    
    # Se nenhuma tag corresponder, pode adicionar um retorno padrão aqui
    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": ["Não entendi o que preciso fazer."]}}]}})


# --- PORTA DE ENTRADA 2: Rota para o Trabalhador do Cloud Tasks ---
@app.route('/processar-tarefa', methods=['POST'])
def processar_tarefa():
    """
    Função "TRABALHADOR": Chamada APENAS pelo Cloud Tasks.
    Executa a lógica demorada de salvar no Notion.
    """
    print("👷 TRABALHADOR: Tarefa recebida do Cloud Tasks. Começando a processar...")
    
    task_payload = request.get_json(silent=True)
    if not task_payload:
        print("🚨 TRABALHADOR: Corpo da requisição da tarefa ausente ou inválido.")
        return "Corpo da tarefa inválido.", 400

    # Extrai todos os dados do payload da tarefa (que é o JSON original do Dialogflow)
    parametros = task_payload.get('sessionInfo', {}).get('parameters', {})
    numero_cliente_com_prefixo = task_payload.get('sessionInfo', {}).get('session', '').split('/')[-1]
    numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
    if numero_cliente.startswith('55'):
        numero_cliente = f"+{numero_cliente}"

    nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

    data_ida_str, data_volta_str = None, None
    data_ida_obj = parametros.get('data_ida', {})
    if isinstance(data_ida_obj, dict):
        data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):02d}-{int(data_ida_obj.get('day')):02d}"
    
    data_volta_obj = parametros.get('data_volta')
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
    
    print(f"📄 TRABALHADOR: Enviando para o Notion: {dados_para_notion}")
    
    _, status_code = create_notion_page(dados_para_notion)
    
    if 200 <= status_code < 300:
        print("✅ TRABALHADOR: Tarefa concluída. Página criada no Notion.")
        return "OK", 200
    else:
        print(f"🚨 TRABALHADOR: Falha ao criar página no Notion. Status: {status_code}.")
        # Retorna um erro 500 para que o Cloud Tasks possa tentar novamente se configurado.
        return "Erro ao criar página no Notion", 500