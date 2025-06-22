# main.py (VERSÃO DE DEPURAÇÃO SÍNCRONA)
import os
import json
import logging
from datetime import datetime

from flask import Flask, request, jsonify
# from google.cloud import tasks_v2 # Não precisamos mais para este teste
from twilio.rest import Client

from notion_utils import create_notion_page
# from db import salvar_conversa, buscar_nome_cliente # Comentado se não estiver em uso

# --- Configurações Iniciais ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Comentamos as configurações do Cloud Tasks por enquanto ---
# PROJECT_ID = os.getenv("GCP_PROJECT_ID")
# ...

# Função que contém a lógica do trabalhador
def executar_logica_trabalhador(dados_dialogflow):
    logger.info("👷 TRABALHADOR (Síncrono): Lógica iniciada...")
    try:
        parametros = dados_dialogflow.get("sessionInfo", {}).get("parameters", {})
        tag = dados_dialogflow.get('fulfillmentInfo', {}).get('tag', '')
        
        numero_cliente_completo = dados_dialogflow.get("sessionInfo", {}).get("session", "")
        numero_cliente = numero_cliente_completo.split('/')[-1] if '/' in numero_cliente_completo else numero_cliente_completo

        data_ida_str = parametros.get("data_ida")
        if data_ida_str and isinstance(data_ida_str, str):
            data_ida_obj = datetime.strptime(data_ida_str, '%d/%m/%Y')
            parametros['data_ida_formatada'] = data_ida_obj.strftime('%Y-%m-%d')
        
        data_volta_str = parametros.get("data_volta")
        if data_volta_str and isinstance(data_volta_str, str):
            data_volta_obj = datetime.strptime(data_volta_str, '%d/%m/%Y')
            parametros['data_volta_formatada'] = data_volta_obj.strftime('%Y-%m-%d')

        if tag == 'salvar_dados_voo_no_notion':
            logger.info("👷 TRABALHADOR (Síncrono): Preparando dados para o Notion...")
            dados_notion = {
                "nome_cliente": parametros.get("person"),
                "whatsapp_cliente": numero_cliente,
                "tipo_viagem": "Passagem Aérea",
                "origem_destino": f"{parametros.get('origem')} → {parametros.get('destino')}",
                "data_ida": parametros.get('data_ida_formatada'),
                "data_volta": parametros.get('data_volta_formatada'),
                "qtd_passageiros": str(parametros.get('passageiros')),
                "perfil_viagem": parametros.get('perfil_viagem'),
                "preferencias": parametros.get('preferencias'),
                "status": "Aguardando Pesquisa"
            }
            create_notion_page(dados_notion)

            logger.info("👷 TRABALHADOR (Síncrono): Preparando para enviar WhatsApp...")
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            numero_admin = os.getenv("MEU_WHATSAPP_TO") 
            
            mensagem_alerta = f"🚨 Novo Lead de Passagem Aérea: {dados_notion['nome_cliente']}..." # Mensagem simplificada
            
            message = client.messages.create(
                            body=mensagem_alerta,
                            from_=os.getenv("TWILIO_WHATSAPP_FROM"),
                            to=numero_admin
                        )
            logger.info(f"✅ TRABALHADOR (Síncrono): Alerta WhatsApp enviado! SID: {message.sid}")

        logger.info("✅ TRABALHADOR (Síncrono): Lógica finalizada com sucesso!")

    except Exception as e:
        logger.exception(f"❌ TRABALHADOR (Síncrono): Erro fatal: {e}")


# --- Rota Principal Modificada para Execução Síncrona ---
@app.route('/', methods=['POST'])
def vivi_webhook_sincrono():
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')

    if tag == 'salvar_dados_voo_no_notion' or tag == 'salvar_dados_cruzeiro_no_notion':
        logger.info(f"ℹ️ ATENDENTE (Síncrono): Recebida tag '{tag}'. Executando lógica diretamente...")
        
        # Chamada direta para a lógica do trabalhador
        executar_logica_trabalhador(request_json)
        
        # Resposta para o Dialogflow
        texto_resposta = "Sua solicitação foi registrada. Nosso especialista entrará em contato. Obrigado! 😊"
        return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})
    
    return jsonify({})

# As outras rotas não são mais necessárias para este teste
# @app.route('/gerenciar-dados', methods=['POST'])
# ...
# @app.route('/processar-tarefa', methods=['POST'])
# ...