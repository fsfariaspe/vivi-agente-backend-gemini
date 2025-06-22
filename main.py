# main.py (VERSÃO FINAL DE DEPURAÇÃO SÍNCRONA)
import os
import json
import logging
from datetime import datetime

from flask import Flask, request, jsonify
from twilio.rest import Client

from notion_utils import create_notion_page

# --- Configurações Iniciais ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Função de Lógica Principal ---
def executar_logica_negocio(dados_dialogflow):
    logger.info("👷‍♂️ LÓGICA DE NEGÓCIO (Síncrono): Execução iniciada...")
    try:
        parametros = dados_dialogflow.get("sessionInfo", {}).get("parameters", {})
        tag = dados_dialogflow.get('fulfillmentInfo', {}).get('tag', '')
        
        numero_cliente_completo = dados_dialogflow.get("sessionInfo", {}).get("session", "")
        numero_cliente = numero_cliente_completo.split('/')[-1] if '/' in numero_cliente_completo else numero_cliente_completo

        # --- LÓGICA DE CONVERSÃO DE DATA ---
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
            logger.info("...Preparando dados para o Notion...")
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
            logger.info("...Preparando para enviar WhatsApp com Template...")
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            
            numero_admin = os.getenv("MEU_WHATSAPP_TO")
            template_sid = os.getenv("TEMPLATE_SID")

            if not template_sid:
                logger.error("❌ A variável de ambiente TEMPLATE_SID não está configurada!")
            else:
                variaveis_conteudo = {
                    '1': dados_notion.get('nome_cliente', 'Não informado'),
                    '2': dados_notion.get('tipo_viagem', 'Não informado'),
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
                logger.info(f"✅ Alerta WhatsApp (via Template) enviado! SID: {message.sid}")

        logger.info("✅ LÓGICA DE NEGÓCIO (Síncrono): Finalizada com sucesso!")

    except Exception as e:
        logger.exception(f"❌ ERRO FATAL NA LÓGICA DE NEGÓCIO: {e}")

# --- Rota Principal Única para Depuração Síncrona ---
@app.route('/', methods=['POST'])
def webhook_principal():
    request_json = request.get_json(silent=True)
    logger.info("--- CHAMADA WEBHOOK RECEBIDA ---")
    
    # Executa a lógica de negócio diretamente
    executar_logica_negocio(request_json)
    
    # Responde para o Dialogflow
    texto_resposta = "Sua solicitação foi processada. Obrigado! 😊"
    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})