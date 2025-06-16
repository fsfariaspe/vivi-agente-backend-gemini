# main.py (VERSÃO ASSÍNCRONA FINAL com Flask e Twilio)
import os
import json
import logging
import pytz
from datetime import datetime

from flask import Flask, request, jsonify
from google.cloud import tasks_v2
from twilio.rest import Client
import psycopg2

from notion_utils import create_notion_page
from db import salvar_conversa, buscar_nome_cliente

# --- Configurações Iniciais ---
logger = logging.getLogger(__name__)

# 1. Inicializa a aplicação Flask
app = Flask(__name__)

# 2. Configurações do Google Cloud
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
LOCATION_ID = os.getenv("GCP_LOCATION_ID")
QUEUE_ID = os.getenv("CLOUD_TASKS_QUEUE_ID")
SERVICE_ACCOUNT_EMAIL = os.getenv("GCP_SERVICE_ACCOUNT_EMAIL")
WORKER_URL = os.getenv("WORKER_URL") # URL do nosso próprio serviço, configurada no Cloud Run

tasks_client = tasks_v2.CloudTasksClient()

# --- PORTA DE ENTRADA 1: Webhook para o Dialogflow ---
@app.route('/', methods=['POST'])
def vivi_webhook():
    """
    Função "ATENDENTE": Chamada APENAS pelo Dialogflow.
    Responde rápido e delega o trabalho demorado.
    """
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
    
    # --- Lógica para salvar o nome (continua síncrona e rápida) ---
    if tag == 'salvar_nome_e_perguntar_produto':
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')
        salvar_conversa(numero_cliente, f"O cliente informou o nome: {nome_cliente}.", nome_cliente)
        print(f"✅ Nome '{nome_cliente}' salvo para o número {numero_cliente}.")
        return jsonify({})

    elif tag == 'definir_data':
        print("ℹ️ ATENDENTE: Recebida tag 'definir_data'. Processando correção de data...")
        
        # Pega o parâmetro 'data_capturada' que vem da intent
        data_capturada = request_json.get('fulfillmentInfo', {}).get('parameters', {}).get('data_capturada', {})
        
        # Pega o parâmetro de sessão que nos diz qual data corrigir (usando a variável correta 'parametros')
        campo_para_corrigir = parametros.get('campo_em_correcao', '')

        if data_capturada and 'year' in data_capturada and campo_para_corrigir in ['data_ida', 'data_volta']:
            # Prepara o objeto de data completo
            date_object = {
                "day": data_capturada.get("day"),
                "month": data_capturada.get("month"),
                "year": data_capturada.get("year")
            }
            # Atualiza o campo correto na sessão (usando a variável correta 'parametros')
            parametros[campo_para_corrigir] = date_object
            print(f"✅ Webhook: Parâmetro '{campo_para_corrigir}' atualizado para {date_object}")
        
        # Limpa as flags de correção (usando a variável correta 'parametros')
        parametros.pop('modo_correcao', None)
        parametros.pop('campo_em_correcao', None)
        
        # Monta a resposta para o Dialogflow, devolvendo os parâmetros atualizados
        response = {
            "sessionInfo": {
                "parameters": parametros
            }
        }
        return jsonify(response)

    # --- Lógica para criar a tarefa assíncrona ---
    elif tag == 'salvar_dados_voo_no_notion': # A tag continua com o mesmo nome, mas a ação agora é outra
        print("ℹ️ ATENDENTE: Recebida tag 'salvar_dados_voo_no_notion'. Criando tarefa para notificação...")
        
        if not WORKER_URL:
            texto_resposta = "Ocorreu um erro de configuração (WORKER_URL não definida)."
        else:
            payload_para_tarefa = request.get_data()
            queue_path = tasks_client.queue_path(PROJECT_ID, LOCATION_ID, QUEUE_ID)

            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": WORKER_URL,
                    "headers": {"Content-type": "application/json"},
                    "body": payload_para_tarefa,
                    "oidc_token": {"service_account_email": SERVICE_ACCOUNT_EMAIL}
                }
            }
            try:
                tasks_client.create_task(parent=queue_path, task=task)
                print("✅ ATENDENTE: Tarefa de notificação criada com sucesso na fila.")
                texto_resposta = "Sua solicitação foi registrada com sucesso! Em instantes, um de nossos especialistas entrará em contato para te enviar a proposta. Obrigado! 😊"
            except Exception as e:
                logger.exception("❌ ATENDENTE: Falha ao criar tarefa no Cloud Tasks: %s", e)
                texto_resposta = "Tive um problema ao iniciar o registro da sua solicitação. Nossa equipe já foi notificada."
        
        return jsonify({"fulfillment_response": {"messages": [{"text": {"text": [texto_resposta]}}]}})

    elif tag == 'atualizar_nome_cliente':
        print("ℹ️ ATENDENTE: Recebida tag 'atualizar_nome_cliente'.")
        nome_corrigido = parametros.get('person', {}).get('name')
        if nome_corrigido:
            # A função salvar_conversa já atualiza o nome se o número existir
            salvar_conversa(numero_cliente, f"O cliente corrigiu o nome para: {nome_corrigido}.", nome_corrigido)
            print(f"✅ Nome corrigido para '{nome_corrigido}' no banco de dados.")
        # Retorna uma resposta vazia para que o Dialogflow use a fala definida na própria rota.
        return jsonify({})


# --- PORTA DE ENTRADA 2: Rota para o Trabalhador do Cloud Tasks ---
@app.route('/processar-tarefa', methods=['POST'])
def processar_tarefa():
    """
    Função "TRABALHADOR": agora vai salvar no Notion E enviar a notificação por WhatsApp.
    """
    print("👷 TRABALHADOR: Tarefa recebida. Iniciando processamento completo...")

    task_payload = request.get_json(silent=True)
    if not task_payload:
        print("🚨 TRABALHADOR: Corpo da tarefa inválido.")
        return "Corpo da tarefa inválido.", 400

    parametros = task_payload.get('sessionInfo', {}).get('parameters', {})

    # --- Mova a extração de variáveis para cá e defina valores padrão ---
    origem_nome = parametros.get('origem', {}).get('original', 'Não informado')
    destino_nome = parametros.get('destino', {}).get('original', 'Não informado')
    nome_cliente = 'Não informado' # Valor padrão

    # --- 1. Lógica do NOTION ---
    try:
        print("📄 Etapa 1: Preparando dados para o Notion...")

        numero_cliente_com_prefixo = task_payload.get('sessionInfo', {}).get('session', '').split('/')[-1]
        numero_cliente = ''.join(filter(str.isdigit, numero_cliente_com_prefixo))
        if numero_cliente.startswith('55'):
            numero_cliente = f"+{numero_cliente}"

        nome_cliente = buscar_nome_cliente(numero_cliente) or parametros.get('person', {}).get('name', 'Não informado')

        data_ida_str, data_volta_str = None, None
        
        # --- Verificação de segurança para data_ida ---
        data_ida_obj = parametros.get('data_ida', {})
        if isinstance(data_ida_obj, dict) and all(k in data_ida_obj for k in ['year', 'month', 'day']):
            data_ida_str = f"{int(data_ida_obj.get('year'))}-{int(data_ida_obj.get('month')):02d}-{int(data_ida_obj.get('day')):02d}"

        # --- Verificação de segurança para data_volta ---
        data_volta_obj = parametros.get('data_volta')
        if isinstance(data_volta_obj, dict) and all(k in data_volta_obj for k in ['year', 'month', 'day']):
            data_volta_str = f"{int(data_volta_obj.get('year'))}-{int(data_volta_obj.get('month')):02d}-{int(data_volta_obj.get('day')):02d}"

        timestamp_contato = datetime.now(pytz.timezone("America/Recife")).isoformat()

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

        if not (200 <= status_code < 300):
            print(f"⚠️ Falha ao criar página no Notion. Status: {status_code}. Continuando para o WhatsApp...")
        else:
            print("✅ Página criada no Notion com sucesso.")

    except Exception as e:
        logger.exception("🚨 TRABALHADOR: Falha CRÍTICA na etapa do Notion: %s", e)
        # Mesmo com erro no Notion, tentamos notificar

    # --- 2. Lógica do WHATSAPP ---
    try:
        print("📱 Etapa 2: Preparando notificação do WhatsApp...")

        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")

        if not all([account_sid, auth_token]):
            raise ValueError("Credenciais do Twilio (SID ou TOKEN) não encontradas.")

        twilio_client = Client(account_sid, auth_token)

        template_sid = os.getenv("TEMPLATE_SID")
        from_number = os.getenv("TWILIO_WHATSAPP_FROM")
        to_number = os.getenv("MEU_WHATSAPP_TO")

        if not all([template_sid, from_number, to_number]):
            raise ValueError("Variáveis de envio do Twilio (SID, FROM, TO) não encontradas.")

        content_variables = json.dumps({
            '1': nome_cliente,
            '2': "Passagem Aérea",
            '3': f"{origem_nome} → {destino_nome}"
        })

        message = twilio_client.messages.create(
            content_sid=template_sid,
            from_=from_number,
            content_variables=content_variables,
            to=to_number
        )
        print(f"✅ Notificação por WhatsApp enviada com sucesso! SID: {message.sid}")

    except Exception as e:
        logger.exception("🚨 TRABALHADOR: Falha CRÍTICA na etapa do WhatsApp: %s", e)
        return "Erro no processo do trabalhador", 500

    # Se tudo correu bem, retorna OK para o Cloud Tasks
    return "OK", 200

# --- NOVA PORTA DE ENTRADA 3: Webhook para Lógica de Dados ---
@app.route('/gerenciar-dados', methods=['POST'])
def gerenciar_dados():
    """
    Webhook para manipular a lógica de dados que é complexa
    para ser feita com presets no Dialogflow CX, como a atribuição de datas.
    """
    try:
        request_json = request.get_json(silent=True)
        tag = request_json.get("fulfillmentInfo", {}).get("tag", "")
        parametros_sessao = request_json.get("sessionInfo", {}).get("parameters", {})

        print(f"ℹ️ Webhook /gerenciar-dados recebido com a tag: {tag}")

        # As tags agora nos dizem exatamente o que fazer
        if tag in ["definir_data_ida", "definir_data_volta"]:
            
            data_capturada = request_json.get("fulfillmentInfo", {}).get("parameters", {}).get("data_capturada", {})

            if data_capturada and 'year' in data_capturada:
                # Prepara o objeto de data completo que será salvo na sessão
                objeto_data = {
                    "day": data_capturada.get("day"),
                    "month": data_capturada.get("month"),
                    "year": data_capturada.get("year")
                }
                
                # Atualiza o campo correto com base na tag
                if tag == "definir_data_ida":
                    parametros_sessao["data_ida"] = objeto_data
                    print(f"✅ Webhook: Parâmetro 'data_ida' atualizado para {objeto_data}")
                elif tag == "definir_data_volta":
                    parametros_sessao["data_volta"] = objeto_data
                    print(f"✅ Webhook: Parâmetro 'data_volta' atualizado para {objeto_data}")

        # Monta a resposta para o Dialogflow, devolvendo os parâmetros atualizados
        resposta = {
            "sessionInfo": {
                "parameters": parametros_sessao
            }
        }
        return jsonify(resposta)

    except Exception as e:
        logging.error(f"❌ Erro no webhook /gerenciar-dados: {e}")
        # Em caso de erro, retorna uma resposta vazia para não quebrar a conversa
        return jsonify({})