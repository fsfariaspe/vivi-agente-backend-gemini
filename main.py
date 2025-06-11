import os
import psycopg2
import functions_framework
from flask import jsonify
from datetime import datetime
import pytz  # Importa a biblioteca de fusos horários

# Importa nossas funções de utilidade
from db import salvar_conversa, buscar_nome_cliente
from notion_utils import create_notion_page

@functions_framework.http
def identificar_cliente(request):
    """
    Função principal que lida com todas as chamadas do webhook do Dialogflow.
    """
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    parametros = request_json.get('sessionInfo', {}).get('parameters', {})
    
    # Extrai o número de telefone do cliente da sessão
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

    # AÇÃO 2: Salvar o nome e deixar o Dialogflow fazer a próxima pergunta
    elif tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        
        mensagem_completa = f"O cliente informou o nome: {nome_cliente}."
        salvar_conversa(numero_cliente, mensagem_completa, nome_cliente)

        print(f"✅ Nome '{nome_cliente}' salvo para o número {numero_cliente}. Deixando o Dialogflow continuar o fluxo.")
        
        # Retorna uma resposta vazia para permitir que a transição de página no Dialogflow aconteça
        return jsonify({})

    # AÇÃO 3: Receber dados do formulário e salvar no Notion
    elif tag == 'salvar_dados_voo_no_notion':
        print(f"ℹ️ Recebida tag 'salvar_dados_voo_no_notion'. Parâmetros: {parametros}")
        
        nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

        # Formata a data de ida com segurança
        data_ida_str = None
        data_ida_obj = parametros.get('data_ida', {})
        if isinstance(data_ida_obj, dict):
            data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):02d}-{int(data_ida_obj.get('day')):02d}"

        # Formata a data de volta com segurança, verificando se é um objeto de data
        data_volta_str = None
        data_volta_obj = parametros.get('data_volta')
        if isinstance(data_volta_obj, dict):
            data_volta_str = f"{int(data_volta_obj.get('year'))}-{int(data_volta_obj.get('month')):02d}-{int(data_volta_obj.get('day')):02d}"
        
        # Gera o timestamp com fuso horário
        fuso_horario_recife = pytz.timezone("America/Recife") 
        timestamp_contato = datetime.now(fuso_horario_recife).isoformat()
        
        # Extrai os nomes dos locais de forma segura
        origem_nome = parametros.get('origem', {}).get('original', '')
        destino_nome = parametros.get('destino', {}).get('original', '')

        # Monta o dicionário de dados para a função do Notion
        dados_para_notion = {
            "data_contato": timestamp_contato,
            "nome_cliente": nome_cliente,
            "whatsapp_cliente": numero_cliente,
            "tipo_viagem": "Passagem Aérea",
            "origem_destino": f"{origem_nome} → {destino_nome}",
            "data_ida": data_ida_str,
            "data_volta": data_volta_str,
            "qtd_passageiros": parametros.get('passageiros', ''),
            "perfil_viagem": parametros.get('perfil_viagem', ''),
            "preferencias": parametros.get('preferencias', '')
        }
        
        print(f"📄 Tentando criar página no Notion com os dados: {dados_para_notion}")
        
        # Chama a função para criar a página e captura a resposta
        notion_response, status_code = create_notion_page(dados_para_notion)
        
        # Verifica se a operação no Notion foi um sucesso
        if 200 <= status_code < 300:
            texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas irá analisar os melhores preços e opções e te enviará a proposta em breve aqui mesmo. Obrigado! 😊"
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