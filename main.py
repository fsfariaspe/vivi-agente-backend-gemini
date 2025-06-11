# main.py (versão final com Notion)
import os
import functions_framework
from flask import jsonify
from datetime import datetime

# Importa nossas funções de utilidade
from db import salvar_conversa, buscar_nome_cliente
from notion_utils import create_notion_page

@functions_framework.http
def identificar_cliente(request):
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    parametros = request_json.get('sessionInfo', {}).get('parameters', {})
    
    numero_cliente_com_prefixo = request_json.get('sessionInfo', {}).get('session', '').split('/')[-1]
    numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
    if numero_cliente.startswith('55'):
        numero_cliente = f"+{numero_cliente}"

    texto_resposta = ""

    # AÇÃO 1: Identificar o cliente no início da conversa
    if tag == 'identificar_cliente':
        nome_existente = buscar_nome_cliente(numero_cliente)
        if nome_existente:
            texto_resposta = f"Olá, {nome_existente}! Que bom te ver de volta! Como posso te ajudar a planejar sua próxima viagem?"
        else:
            texto_resposta = "Olá! 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"

    # AÇÃO 2: Salvar o nome e fazer a próxima pergunta
    elif tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        mensagem_completa = f"O cliente informou o nome: {nome_cliente}."
        salvar_conversa(numero_cliente, mensagem_completa, nome_cliente)
        
        # A resposta agora está no Dialogflow, então retornamos vazio
        return jsonify({})

    # AÇÃO 3 (FINAL): Receber dados do formulário e salvar no Notion
    elif tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Recebida tag 'salvar_dados_voo_no_notion'. Formatando dados para o Notion...")
        
        # Busca o nome mais recente do cliente no banco
        nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

        # Formata as datas
        data_ida_obj = parametros.get('data_ida', {})
        data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):02d}-{int(data_ida_obj.get('day')):02d}" if data_ida_obj else None
        
        data_volta_str = None
        if 'data_volta' in parametros and parametros['data_volta']:
            data_volta_obj = parametros.get('data_volta', {})
            data_volta_str = f"{int(data_volta_obj.get('year'))}-{int(data_volta_obj.get('month')):02d}-{int(data_volta_obj.get('day')):02d}"

        dados_para_notion = {
            "nome_cliente": nome_cliente,
            "whatsapp_cliente": numero_cliente,
            "tipo_viagem": "Passagem Aérea",
            "origem_destino": f"{parametros.get('origem').get('original', '')} → {parametros.get('destino').get('original', '')}",
            "data_ida": data_ida_str,
            "data_volta": data_volta_str,
            "qtd_passageiros": parametros.get('passageiros', ''),
            "perfil_viagem": parametros.get('perfil_viagem', ''),
            "preferencias": parametros.get('preferencias', '')
        }
        
        print(f"📄 Tentando criar página no Notion com os dados: {dados_para_notion}")
        
        # Chama a função para criar a página e captura a resposta
        notion_response, status_code = create_notion_page(dados_para_notion)
        
        if 200 <= status_code < 300:
            texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar e te enviar a proposta em breve aqui mesmo. Obrigado! 😊"
        else:
            texto_resposta = "Consegui coletar todas as informações, mas tive um problema ao registrar sua solicitação em nosso sistema. Nossa equipe humana já foi notificada do erro e cuidará do seu pedido. Não se preocupe!"

    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer. Pode tentar de novo?"

    # Monta a resposta final para o Dialogflow
    response_payload = {
        "fulfillment_response": {
            "messages": [{"text": {"text": [texto_resposta]}}]
        }
    }
    return jsonify(response_payload)