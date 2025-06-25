# main.py (VERSÃO FINAL DE PRODUÇÃO - SÍNCRONA E VALIDADA)
import os
import json
import logging
import pytz
from datetime import datetime, timezone # Importamos 'timezone'

from flask import Flask, request, jsonify
from twilio.rest import Client

from notion_utils import create_notion_page

# --- Configurações Iniciais ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# --- Função que contém a lógica de negócio ---
def executar_logica_negocio(dados_dialogflow):
    """
    Executa toda a lógica de negócio: formata dados, salva no Notion e notifica via Twilio.
    """
    logger.info("👷‍♂️ LÓGICA DE NEGÓCIO: Execução iniciada...")
    try:
        parametros = dados_dialogflow.get("sessionInfo", {}).get("parameters", {})
        tag = dados_dialogflow.get('fulfillmentInfo', {}).get('tag', '')
        
        # ... (lógica para pegar numero_cliente e formatar datas de viagem permanece a mesma) ...
        # --- LÓGICA DE CONVERSÃO DE DATAS DE VIAGEM ---
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

        # =============================================================================
        # ▼▼▼ BLOCO DE DATA/HORA CORRIGIDO COM FUSO HORÁRIO ▼▼▼
        # =============================================================================
        data_hora_obj = parametros.get("data_hora_confirmacao")
        data_contato_iso = None

        if data_hora_obj:
            logger.info(f"...Processando data_hora_confirmacao (UTC): {data_hora_obj}")
            try:
                # 1. Cria um objeto datetime "naive" (sem fuso)
                naive_dt = datetime(
                    year=int(data_hora_obj.get("year")),
                    month=int(data_hora_obj.get("month")),
                    day=int(data_hora_obj.get("day")),
                    hour=int(data_hora_obj.get("hours")),
                    minute=int(data_hora_obj.get("minutes")),
                    second=int(data_hora_obj.get("seconds")),
                )

                # 2. Define os fusos horários de origem (UTC) e destino (São Paulo)
                utc_tz = pytz.utc
                local_tz = pytz.timezone('America/Sao_Paulo')

                # 3. Transforma o datetime naive em um datetime ciente do fuso UTC
                utc_dt = utc_tz.localize(naive_dt)

                # 4. Converte o datetime de UTC para o fuso local
                local_dt = utc_dt.astimezone(local_tz)

                # 5. Formata a data/hora LOCAL para o padrão ISO 8601
                data_contato_iso = local_dt.isoformat()
                logger.info(f"...Data e hora convertida para fuso local: {data_contato_iso}")

            except Exception as e:
                logger.error(f"Erro ao formatar data_hora_confirmacao com timezone: {e}")
                data_contato_iso = None
        # =============================================================================

        if tag == 'salvar_dados_voo_no_notion':
            
            # 1. SALVAR NO NOTION
            logger.info("...Preparando dados para o Notion...")
            dados_notion = {
                # ... (outros campos) ...
                "data_contato": data_contato_iso 
            }
            create_notion_page(dados_notion)

            # 2. ENVIAR ALERTA VIA WHATSAPP
            # ... (lógica do Twilio) ...

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