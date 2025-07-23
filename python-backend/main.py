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
    """
    Executa toda a lógica de negócio: formata dados, salva no Notion e notifica via Twilio.
    """
    logger.info("👷‍♂️ LÓGICA DE NEGÓCIO: Execução iniciada...")
    try:
        parametros = dados_dialogflow.get("sessionInfo", {}).get("parameters", {})
        tag = dados_dialogflow.get('fulfillmentInfo', {}).get('tag', '')
        
        # =============================================================================
        # ▼▼▼ LÓGICA CORRIGIDA PARA O NÚMERO DO CLIENTE ▼▼▼
        # =============================================================================
        
        # Primeiro, tentamos pegar o número que o usuário digitou na página 'coletar_whatsapp'.
        numero_coletado = parametros.get("whatsapp_cliente")

        if numero_coletado:
            logger.info(f"Usando número de WhatsApp coletado no formulário: {numero_coletado}")
            numero_cliente_final = numero_coletado
        else:
            # Se não houver número coletado (veio direto do WhatsApp), pegamos da sessão.
            logger.info("Número não coletado no formulário, extraindo da sessão...")
            session_id_completo = dados_dialogflow.get("sessionInfo", {}).get("session", "")
            numero_cliente_final = session_id_completo.split('/')[-1] if '/' in session_id_completo else session_id_completo

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
            
            origem = parametros.get('origem')
            origem_texto = origem.get('city') if isinstance(origem, dict) else origem

            destino = parametros.get('destino')
            destino_texto = destino.get('city') if isinstance(destino, dict) else destino
            
            dados_notion = {
                "nome_cliente": parametros.get("person"),
                "whatsapp_cliente": numero_cliente_final,
                "tipo_viagem": "Passagem Aérea",
                "origem_destino": f"{origem_texto} → {destino_texto}",
                "periodo_desejado": f"P_Ida: {parametros.get('periodo_voo_ida') or 'N/A'}, P_Volta: {parametros.get('periodo_voo_volta') or 'N/A'}",
                "data_ida": data_ida_formatada,
                "data_volta": data_volta_formatada,
                "qtd_passageiros": f"{parametros.get('adultos_voo') or 0} adulto(s), {parametros.get('numero_criancas') or 0} criança(s)",
                "idade_crianca": parametros.get('idade_crianca'),
                "perfil_viagem": parametros.get('perfil_viagem'),
                "preferencias": parametros.get('preferencias'),
                "status": "Teste Externo",
                "data_contato": data_contato_iso
            }
            create_notion_page(dados_notion) # Ação do Notion

            # --- LÓGICA CONDICIONAL PARA O TEMPLATE ---
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

            # Verifica se existe data_ida para decidir qual template usar
            if dados_notion.get('data_ida'):
                template_sid = os.getenv("TEMPLATE_SID") # SID para template com datas
                variaveis_template = {
                    '1': dados_notion.get('nome_cliente', 'N/A'),
                    '2': dados_notion.get('tipo_viagem', 'N/A'),
                    '3': dados_notion.get('origem_destino', 'N/A'),
                    '4': parametros.get('data_ida', 'N/A'),
                    '5': parametros.get('data_volta') or 'Só ida',
                    '6': dados_notion.get('qtd_passageiros', 'N/A')
                }
            else:
                # Se não tem data_ida, usa o template novo para período
                template_sid = os.getenv("TEMPLATE_SID_VOO_COM_PERIODO") # << SEU NOVO TEMPLATE SID
                variaveis_template = {
                    '1': dados_notion.get('nome_cliente', 'N/A'),
                    '2': dados_notion.get('tipo_viagem', 'N/A'),
                    '3': dados_notion.get('origem_destino', 'N/A'),
                    '4': dados_notion.get('periodo_desejado', 'N/A'), # << VARIÁVEL DO PERÍODO
                    '5': dados_notion.get('qtd_passageiros', 'N/A')
                    # Adapte os números e variáveis conforme seu novo template
                }

            # Dispara a mensagem com o template e variáveis corretos
            message = client.messages.create(
                content_sid=template_sid, 
                from_=os.getenv("TWILIO_WHATSAPP_FROM"),
                to=os.getenv("MEU_WHATSAPP_TO"), 
                content_variables=json.dumps(variaveis_template)
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
                "whatsapp_cliente": numero_cliente_final,
                "tipo_viagem": "Cruzeiro",
                "destino_cruzeiro": parametros.get('destino_cruzeiro'),
                "periodo_desejado": parametros.get('periodo_cruzeiro'),
                "qtd_passageiros": f"{parametros.get('adultos_cruzeiro') or 0} adulto(s), {parametros.get('numero_criancas') or 0} criança(s)",
                "preferencias": obs_adicionais,
                "idade_crianca": parametros.get('idade_crianca', 'N/A'),
                "idade_senior": parametros.get('idade_senior', 'N/A'),
                "status": "Teste",
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
                '6': numero_cliente_final
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

    texto_resposta = "Atendimento encerrado"

    # ▼▼▼ CORREÇÃO APLICADA AQUI ▼▼▼
    # Adicionando o "sinal secreto" ao lado da mensagem de texto
    payload_final = {
        "flow_status": "finished"
    }

    # Montando a resposta completa para o Dialogflow
    response_data = {
        "fulfillment_response": {
            "messages": [
                {"text": {"text": [texto_resposta]}},
                {"payload": payload_final} 
            ]
        }
    }
    return jsonify(response_data)