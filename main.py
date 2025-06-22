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
logging.basicConfig(level=logging.INFO) # Habilita logging detalhado
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
        logger.info(f"ℹ️ ATENDENTE: Recebida tag '{tag}'. Criando tarefa...")
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
    """
    Função "TRABALHADOR": Executa a lógica pesada de forma assíncrona.
    VERSÃO FINAL COM TEMPLATE TWILIO.
    """
    logger.info("👷 TRABALHADOR: Tarefa recebida...")
    try:
        dados_dialogflow = request.get_json(silent=True)
        parametros = dados_dialogflow.get("sessionInfo", {}).get("parameters", {})
        tag = dados_dialogflow.get('fulfillmentInfo', {}).get('tag', '')
        
        numero_cliente_completo = dados_dialogflow.get("sessionInfo", {}).get("session", "")
        numero_cliente = numero_cliente_completo.split('/')[-1] if '/' in numero_cliente_completo else numero_cliente_completo

        # --- LÓGICA DE CONVERSÃO DE DATA ---
        # Inicializa as variáveis de data formatada como None
        data_ida_formatada = None
        data_volta_formatada = None

        data_ida_str = parametros.get("data_ida")
        if data_ida_str and isinstance(data_ida_str, str):
            data_ida_obj = datetime.strptime(data_ida_str, '%d/%m/%Y')
            data_ida_formatada = data_ida_obj.strftime('%Y-%m-%d')
        
        data_volta_str = parametros.get("data_volta")
        if data_volta_str and isinstance(data_volta_str, str):
            data_volta_obj = datetime.strptime(data_volta_str, '%d/%m/%Y')
            data_volta_formatada = data_volta_obj.strftime('%Y-%m-%d')

        if tag == 'salvar_dados_voo_no_notion':
            
            # 1. SALVAR NO NOTION
            logger.info("👷 TRABALHADOR: Preparando dados para o Notion...")
            dados_notion = {
                "nome_cliente": parametros.get("person"),
                "whatsapp_cliente": numero_cliente,
                "tipo_viagem": "Passagem Aérea",
                "origem_destino": f"{parametros.get('origem')} → {parametros.get('destino')}",
                "data_ida": data_ida_formatada,
                "data_volta": data_volta_formatada,
                "qtd_passageiros": str(parametros.get('passageiros')),
                "perfil_viagem": parametros.get('perfil_viagem'),
                "preferencias": parametros.get('preferencias'),
                "status": "Aguardando Pesquisa"
            }
            create_notion_page(dados_notion)

            # 2. ENVIAR ALERTA VIA WHATSAPP (TWILIO) USANDO TEMPLATE
            logger.info("👷 TRABALHADOR: Preparando para enviar WhatsApp com Template...")
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            
            numero_admin = os.getenv("MEU_WHATSAPP_TO")
            template_sid = os.getenv("TEMPLATE_SID")

            if not template_sid:
                logger.error("❌ TRABALHADOR: Variável de ambiente TEMPLATE_SID não configurada!")
            else:
                variaveis_conteudo = {
                    '1': dados_notion.get('nome_cliente', 'Não informado'),
                    '2': dados_notion.get('whatsapp_cliente', 'Não informado'),
                    '3': dados_notion.get('origem_destino', ''),
                    '4': parametros.get('data_ida', ''),
                    '5': parametros.get('data_volta') or 'Só ida',
                    '6': dados_notion.get('qtd_passageiros', '')
                }
                
                message = client.messages.create(
                                content_sid=template_sid,
                                from_=os.getenv("TWILIO_WHATSAPP_FROM"),
                                to=numero_admin,
                                content_variables=json.dumps(variaveis_conteudo)
                            )
                logger.info(f"✅ TRABALHADOR: Alerta WhatsApp (via Template) enviado! SID: {message.sid}")

        logger.info("✅ TRABALHADOR: Tarefa processada com sucesso!")
        return "OK", 200

    except Exception as e:
        logger.exception(f"❌ TRABALHADOR: Erro fatal ao processar tarefa: {e}")
        return "Erro no processamento", 500
