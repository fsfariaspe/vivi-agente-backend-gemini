# notion_utils.py (versão corrigida) 
import os
import requests
import logging
from flask import jsonify, Response

NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_API_URL = "https://api.notion.com/v1/pages"
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION
}

logger = logging.getLogger(__name__)

NOTION_PROPERTY_MAP = {
    "nome_cliente": "Nome do Cliente",
    "status": "Status",
    "tipo_viagem": "Tipo de Viagem",
    "origem_destino": "Origem → Destino",
    "data_ida": "Data de Ida",
    "data_volta": "Data de Volta (se houver)",
    "qtd_passageiros": "Qtd. de Passageiros",
    "idade_crianca": "Idade Crianças",
    "preferencias": "Preferências",
    "perfil_viagem": "Perfil de Viagem",
    "whatsapp_cliente": "WhatsApp",
    "data_contato": "Data de Criação",
    # --- PROPRIEDADES PARA CRUZEIROS ---
    "destino_cruzeiro": "Região Desejada",
    "periodo_desejado": "Período Desejado",
    "observacoes_adicionais": "Observações Adicionais",
    "idade_senior": "Idade Sênior",
}

def create_notion_page(data: dict) -> tuple[Response, int]:
    """Cria uma página no Notion com os dados fornecidos."""

    properties = {
        NOTION_PROPERTY_MAP["nome_cliente"]: {
            "title": [{"text": {"content": data.get("nome_cliente", "Não informado")}}]
        },
        NOTION_PROPERTY_MAP["origem_destino"]: {
            "rich_text": [{"text": {"content": data.get("origem_destino", "")}}]
        },
        NOTION_PROPERTY_MAP["qtd_passageiros"]: {
            "rich_text": [{"text": {"content": str(data.get("qtd_passageiros", ""))}}]
        },
        NOTION_PROPERTY_MAP["idade_crianca"]: {
            "rich_text": [{"text": {"content": data.get("idade_crianca", "")}}]
        },
        NOTION_PROPERTY_MAP["preferencias"]: {
            "rich_text": [{"text": {"content": data.get("preferencias", "")}}]
        },
        NOTION_PROPERTY_MAP["whatsapp_cliente"]: {
            "rich_text": [{"text": {"content": data.get("whatsapp_cliente", "")}}]
        },
    }

    status = data.get("status", "Aguardando Pesquisa")
    if status:
        properties[NOTION_PROPERTY_MAP["status"]] = {"select": {"name": status}}

    tipo_viagem = data.get("tipo_viagem", "Não especificado")
    if tipo_viagem:
        properties[NOTION_PROPERTY_MAP["tipo_viagem"]] = {"select": {"name": tipo_viagem}}

    perfil_viagem = data.get("perfil_viagem")
    if perfil_viagem:
        properties[NOTION_PROPERTY_MAP["perfil_viagem"]] = {"select": {"name": perfil_viagem}}

    if data.get("data_ida"):
        properties[NOTION_PROPERTY_MAP["data_ida"]] = {"date": {"start": data.get("data_ida")}}

    if data.get("data_volta"):
        properties[NOTION_PROPERTY_MAP["data_volta"]] = {"date": {"start": data.get("data_volta")}}
    
    # =============================================================================
    # ▼▼▼ LINHAS ADICIONADAS PARA CORRIGIR O PROBLEMA ▼▼▼
    # =============================================================================
    data_contato = data.get("data_contato")
    if data_contato:
        properties[NOTION_PROPERTY_MAP["data_contato"]] = {"date": {"start": data_contato}}
    # =============================================================================

    destino_cruzeiro = data.get("destino_cruzeiro")
    if destino_cruzeiro:
        properties[NOTION_PROPERTY_MAP["destino_cruzeiro"]] = {
            "rich_text": [{"text": {"content": destino_cruzeiro}}]
        }
    
    periodo_desejado = data.get("periodo_desejado")
    if periodo_desejado:
        properties[NOTION_PROPERTY_MAP["periodo_desejado"]] = {
            "rich_text": [{"text": {"content": periodo_desejado}}]
        }

    observacoes_adicionais = data.get("observacoes_adicionais")
    if observacoes_adicionais:
        properties[NOTION_PROPERTY_MAP["observacoes_adicionais"]] = {
            "rich_text": [{"text": {"content": observacoes_adicionais}}]
        }
    
    idade_senior = data.get("idade_senior")
    if idade_senior:
        properties[NOTION_PROPERTY_MAP["idade_senior"]] = {
            "rich_text": [{"text": {"content": idade_senior}}]
        }
    
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties
    }

    try:
        response = requests.post(NOTION_API_URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            logger.error("NOTION ERROR RESPONSE: %s", response.text)
        response.raise_for_status()
        logger.info("✅ Página criada no Notion com sucesso!")
        return jsonify(response.json()), response.status_code
    except requests.exceptions.RequestException as e:
        logger.exception("❌ Erro ao enviar para o Notion: %s", e)
        return jsonify({"erro": str(e)}), e.response.status_code if e.response else 500