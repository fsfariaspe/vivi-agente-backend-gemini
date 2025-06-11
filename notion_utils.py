# notion_utils.py
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

# Mapeamento dos nomes das colunas no Notion
NOTION_PROPERTY_MAP = {
    "nome_cliente": "Nome do Cliente",
    "status": "Status",
    "tipo_viagem": "Tipo de Viagem",
    "origem_destino": "Origem → Destino",
    "data_ida": "Data de Ida",
    "data_volta": "Data de Volta (se houver)",
    "qtd_passageiros": "Qtd. de Passageiros",
    "preferencias": "Preferências",
    "perfil_viagem": "Perfil de Viagem",
    "whatsapp_cliente": "WhatsApp Cliente",
}

def create_notion_page(data: dict) -> tuple[Response, int]:
    """Cria uma página no Notion com os dados fornecidos."""

    # Constrói o corpo da requisição para a API do Notion
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            NOTION_PROPERTY_MAP["nome_cliente"]: {
                "title": [{"text": {"content": data.get("nome_cliente", "")}}]
            },
            NOTION_PROPERTY_MAP["status"]: {
                "select": {"name": data.get("status", "Aguardando Pesquisa")}
            },
            NOTION_PROPERTY_MAP["tipo_viagem"]: {
                "select": {"name": data.get("tipo_viagem", "Passagem Aérea")}
            },
            NOTION_PROPERTY_MAP["origem_destino"]: {
                "rich_text": [{"text": {"content": data.get("origem_destino", "")}}]
            },
            NOTION_PROPERTY_MAP["data_ida"]: {
                "date": {"start": data.get("data_ida")} if data.get("data_ida") else None
            },
            NOTION_PROPERTY_MAP["data_volta"]: {
                "date": {"start": data.get("data_volta")} if data.get("data_volta") else None
            },
            NOTION_PROPERTY_MAP["qtd_passageiros"]: {
                "rich_text": [{"text": {"content": str(data.get("qtd_passageiros", ""))}}]
            },
            NOTION_PROPERTY_MAP["preferencias"]: {
                "rich_text": [{"text": {"content": data.get("preferencias", "")}}]
            },
            NOTION_PROPERTY_MAP["perfil_viagem"]: {
                "select": {"name": data.get("perfil_viagem", "Não informado")} if data.get("perfil_viagem") else None
            },
            NOTION_PROPERTY_MAP["whatsapp_cliente"]: {
                "rich_text": [{"text": {"content": data.get("whatsapp_cliente", "")}}]
            },
        }
    }

    # Remove propriedades que não foram preenchidas para não enviar valores nulos
    payload["properties"] = {k: v for k, v in payload["properties"].items() if v is not None}

    try:
        response = requests.post(NOTION_API_URL, headers=HEADERS, json=payload)
        response.raise_for_status() # Lança um erro para status codes 4xx/5xx
        logger.info("✅ Página criada no Notion com sucesso!")
        return jsonify({"status": "Sucesso", "notion_response": response.json()}), response.status_code
    except requests.exceptions.RequestException as e:
        logger.exception("❌ Erro ao enviar para o Notion: %s", e.response.text if e.response else e)
        return jsonify({"erro": "Erro ao enviar para o Notion"}), 500