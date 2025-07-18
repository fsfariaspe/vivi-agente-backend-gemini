# main.py (VERSÃO FINAL REATORADA - SÍNCRONA E COMPLETA)
import os
import json
import logging
import pytz
from datetime import datetime

from flask import Flask, request, jsonify
from twilio.rest import Client

from notion_utils import create_notion_page

# --- Configurações Iniciais ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Função que contém a lógica de negócio ---
def executar_logica_negocio(dados_dialogflow):
    logger.info("👷‍♂️ LÓGICA DE NEGÓCIO: Execução iniciada...")
    try:
        parametros = dados_dialogflow.get("sessionInfo", {}).get("parameters", {})
        tag = dados_dialogflow.get('fulfillmentInfo', {}).get('tag', '')
        
        numero_cliente_completo = dados_dialogflow.get("sessionInfo", {}).get("session", "")
        numero_cliente = numero_cliente_completo.split('/')[-1] if '/' in numero_cliente_completo else numero_cliente_completo

        # --- LÓGICA DE DATA/HORA DA CONFIRMAÇÃO ---
        data_hora_obj = parametros.get("data_hora_confirmacao")
        data_contato_iso = None
        if data_hora_obj:
            try:
                naive_dt = datetime(
                    year=int(data_hora_obj.get("year")), month=int(data_hora_obj.get("month")),
                    day=int(data_hora_obj.get("day")), hour=int(data_hora_obj.get("hours")),
                    minute=int(data_hora_obj.get("minutes")), second=int(data_hora_obj.get("seconds")),
                )
                utc_tz = pytz.utc
                local_tz = pytz.timezone('America/Sao_Paulo')
                utc_dt = utc_tz.localize(naive_dt)
                local_dt = utc_dt.astimezone(local_tz)
                data_contato_iso = local_dt.isoformat()
            except Exception as e:
                logger.error(f"Erro ao formatar data_hora_confirmacao: {e}")

        # =============================================================================
        # ▼▼▼ LÓGICA REATORADA ▼▼▼
        # =============================================================================

        if tag == 'salvar_dados_voo_no_notion':
            logger.info("...Processando lead de PASSAGEM AÉREA...")
            data_ida_formatada = datetime.strptime(parametros.get("data_ida"), '%d/%m/%Y').strftime('%Y-%m-%d') if parametros.get("data_ida") else None
            data_volta_formatada = datetime.strptime(parametros.get("data_volta"), '%d/%m/%Y').strftime('%Y-%m-%d') if parametros.get("data_volta") else None
            origem_texto = parametros.get('origem', {}).get('city', parametros.get('origem'))
            destino_texto = parametros.get('destino', {}).get('city', parametros.get('destino'))
            
            dados_notion = {
                "nome_cliente": parametros.get("person"),
                "whatsapp_cliente": numero_cliente,
                "tipo_viagem": "Passagem Aérea",
                "origem_destino": f"{origem_texto} → {destino_texto}",
                "data_ida": data_ida_formatada,
                "data_volta": data_volta_formatada,
                "qtd_passageiros": str(parametros.get('passageiros')),
                "perfil_viagem": parametros.get('perfil_viagem'),
                "preferencias": parametros.get('preferencias'),
                "status": "Aguardando Pesquisa",
                "data_contato": data_contato_iso
            }
            create_notion_page(dados_notion) # Ação do Notion
            
            template_sid = os.getenv("TEMPLATE_SID")
            variaveis_template = {
                '1': dados_notion.get('nome_cliente', 'N/A'),
                '2': dados_notion.get('tipo_viagem', 'N/A'),
                '3': dados_notion.get('origem_destino', 'N/A'),
                '4': parametros.get('data_ida', 'N/A'),
                '5': parametros.get('data_volta') or 'Só ida',
                '6': dados_notion.get('qtd_passageiros', 'N/A')
            }
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            message = client.messages.create(
                content_sid=template_sid, from_=os.getenv("TWILIO_WHATSAPP_FROM"),
                to=os.getenv("MEU_WHATSAPP_TO"), content_variables=json.dumps(variaveis_template)
            )
            logger.info(f"✅ Alerta de VOO enviado! SID: {message.sid}")

        elif tag == 'salvar_dados_cruzeiro_no_notion':
            logger.info("...Processando lead de CRUZEIRO...")
            
            obs_adicionais = (
                f"Companhia Preferida: {parametros.get('companhia_cruzeiro', 'N/A')}. "
                f"Acessibilidade: {parametros.get('acessibilidade_cruzeiro', 'N/A')}. "
                f"Tarifa Sênior: {parametros.get('status_tarifa_senior', 'N/A')}."
            )
            
            dados_notion = {
                "nome_cliente": parametros.get("person"),
                "whatsapp_cliente": numero_cliente,
                "tipo_viagem": "Cruzeiro",
                "destino_cruzeiro": parametros.get('destino_cruzeiro'),
                "periodo_desejado": parametros.get('periodo_cruzeiro'),
                "qtd_passageiros": f"{parametros.get('adultos_cruzeiro') or 0} adulto(s), {parametros.get('numero_criancas') or 0} criança(s)",
                "preferencias": obs_adicionais,
                "idade_crianca": parametros.get('idade_crianca', 'N/A'),
                "idade_senior": parametros.get('idade_senior', 'N/A'),
                "status": "Aguardando Pesquisa",
                "data_contato": data_contato_iso
            }
            create_notion_page(dados_notion) # Ação do Notion
            
            template_sid = os.getenv("TEMPLATE_CRUZEIRO_SID")
            variaveis_template = {
                '1': dados_notion.get('nome_cliente', 'N/A'),
                '2': dados_notion.get('destino_cruzeiro', 'N/A'),
                '3': dados_notion.get('periodo_desejado', 'N/A'),
                '4': dados_notion.get('qtd_passageiros', 'N/A'),
                '5': parametros.get('porto_embarque', 'N/A'),
                '6': numero_cliente
            }
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            message = client.messages.create(
                content_sid=template_sid, from_=os.getenv("TWILIO_WHATSAPP_FROM"),
                to=os.getenv("MEU_WHATSAPP_TO"), content_variables=json.dumps(variaveis_template)
            )
            logger.info(f"✅ Alerta de CRUZEIRO enviado! SID: {message.sid}")
            
        else:
            logger.warning(f"Tag '{tag}' recebida, mas sem lógica de processamento definida.")

        logger.info("✅ LÓGICA DE NEGÓCIO: Finalizada com sucesso!")

    except Exception as e:
        logger.exception(f"❌ ERRO FATAL NA LÓGICA DE NEGÓCIO: {e}")

# --- Rota Principal Única ---
@app.route('/', methods=['POST'])
def webhook_principal():
    request_json = request.get_json(silent=True)
    logger.info("--- CHAMADA WEBHOOK RECEBIDA ---")
    executar_logica_negocio(request_json)
    texto_resposta = "Sua solicitação foi registrada com sucesso! Em instantes, um de nossos especialistas entrará em contato. Obrigado! 😊"
    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})