# main.py (VERSÃO SÍNCRONA, COMPLETA E FINAL)
import os
import json
import logging
import pytz
from datetime import datetime

import functions_framework
from flask import jsonify # O functions-framework usa o Flask por baixo dos panos
import psycopg2

from notion_utils import create_notion_page
from db import salvar_conversa, buscar_nome_cliente

logger = logging.getLogger(__name__)

@functions_framework.http
def vivi_webhook(request):
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

    texto_resposta = ""

    if tag == 'identificar_cliente':
        nome_existente = buscar_nome_cliente(numero_cliente)
        texto_resposta = f"Olá, {nome_existente}! Que bom te ver de volta! Como posso te ajudar?" if nome_existente else "Olá! 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"

    elif tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        salvar_conversa(numero_cliente, f"O cliente informou o nome: {nome_cliente}.", nome_cliente)
        return jsonify({})

    elif tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Tag 'salvar_dados_voo_no_notion' recebida. Processando...")

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
            "data_contato": timestamp_contato,
            "nome_cliente": nome_cliente,
            "whatsapp_cliente": numero_cliente,
            "tipo_viagem": "Passagem Aérea",
            "origem_destino": f"{origem_nome} → {destino_nome}",
            "data_ida": data_ida_str,
            "data_volta": data_volta_str,
            "qtd_passageiros": str(parametros.get('passageiros', '')),
            "perfil_viagem": parametros.get('perfil_viagem', ''),
            "preferencias": parametros.get('preferencias', '')
        }

        print(f"📄 Enviando para o Notion: {dados_para_notion}")

        _, status_code = create_notion_page(dados_para_notion)

        if 200 <= status_code < 300:
            print("✅ Página criada no Notion com sucesso.")
            texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviará a proposta em breve aqui mesmo. Obrigado! 😊"
        else:
            print(f"🚨 Falha ao criar página no Notion. Status: {status_code}.")
            texto_resposta = "Consegui coletar todas as informações, mas tive um problema ao registrar sua solicitação. Nossa equipe já foi notificada."

    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer."

    return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})