import os
import psycopg2
import functions_framework
from flask import jsonify
from notion_utils import create_notion_page # Importamos a nossa nova função

# --- Configuração do Banco de Dados ---
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# --- Lógica de Conexão Otimizada ---
conn = None

def get_db_connection():
    """Retorna uma conexão com o banco de dados, criando uma se não existir."""
    global conn
    if conn is None or conn.closed:
        try:
            conn = psycopg2.connect(
                dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
                host=DB_HOST, port="5432", sslmode="require"
            )
        except Exception as e:
            print(f"❌ Erro CRÍTICO ao conectar ao PostgreSQL: {e}")
            conn = None
    return conn

# --- Funções de Lógica de Negócio ---
def salvar_conversa_no_banco(numero_cliente, mensagem, nome_cliente, thread_id=None):
    """Salva uma única mensagem no banco de dados."""
    db_conn = get_db_connection()
    if not db_conn:
        print("⚠️ Conexão com o banco indisponível. Não foi possível salvar a conversa.")
        return

    try:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversas (numero_cliente, nome_cliente, mensagem_inicial, openai_thread_id)
                VALUES (%s, %s, %s, %s)
                """,
                (numero_cliente, nome_cliente, mensagem, thread_id)
            )
            db_conn.commit()
            print(f"💾 Conversa salva para o cliente: {nome_cliente}")
    except Exception as e:
        print(f"❌ Erro ao salvar conversa no banco: {e}")
        db_conn.rollback()

# Inicializa a conexão na primeira execução
get_db_connection()

@functions_framework.http
def identificar_cliente(request):
    """Função "canivete suíço" que lida com diferentes ações do Dialogflow."""
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
        db_conn = get_db_connection()
        if db_conn:
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT nome_cliente FROM conversas WHERE numero_cliente = %s AND nome_cliente IS NOT NULL ORDER BY data_inicio DESC LIMIT 1",
                    (numero_cliente,)
                )
                resultado = cur.fetchone()
            if resultado and resultado[0]:
                texto_resposta = f"Olá, {resultado[0]}! Que bom te ver de volta! Como posso te ajudar a planejar sua próxima viagem?"
            else:
                texto_resposta = "Olá! 😊 Eu sou a Vivi, sua consultora de viagens virtual. Para um atendimento mais atencioso, pode me dizer seu nome, por favor?"
        else:
            texto_resposta = "Olá! Eu sou a Vivi, sua consultora de viagens. Como posso te ajudar?"

        # AÇÃO 2: Salvar o nome (a resposta de texto foi removida)
    elif tag == 'salvar_nome_e_perguntar_produto':
        parametros = request_json.get('sessionInfo', {}).get('parameters', {})
        nome_cliente = parametros.get('person', {}).get('name', 'Cliente')

        # Salva a informação no banco
        mensagem_completa = f"O cliente informou o nome: {nome_cliente}. Nome capturado com sucesso."
        salvar_conversa_no_banco(numero_cliente, mensagem_completa, nome_cliente)

        print(f"✅ Nome '{nome_cliente}' salvo para o número {numero_cliente}. Deixando o Dialogflow continuar o fluxo.")

        # Retorna uma resposta vazia para permitir que a transição de página no Dialogflow aconteça
        # e a nova página faça a próxima pergunta.
        return jsonify({})

    # AÇÃO 3 (VERSÃO FINAL): Receber dados, formatar e salvar no Notion
    elif tag == 'salvar_dados_voo_no_notion':
        print("ℹ️ Recebida tag 'salvar_dados_voo_no_notion'. Formatando dados para o Notion...")
        
        # Formata as datas que vêm como objetos do Dialogflow para o formato AAAA-MM-DD
        data_ida_obj = parametros.get('data_ida', {})
        data_ida_str = f"{int(data_ida_obj.get('year', 0))}-{int(data_ida_obj.get('month', 0)):02d}-{int(data_ida_obj.get('day', 0)):02d}" if data_ida_obj else None

        data_volta_obj = parametros.get('data_volta', {})
        data_volta_str = f"{int(data_volta_obj.get('year', 0))}-{int(data_volta_obj.get('month', 0)):02d}-{int(data_volta_obj.get('day', 0)):02d}" if data_volta_obj else None

        # Monta o dicionário de dados para enviar para a função do Notion
        dados_para_notion = {
            "nome_cliente": parametros.get('person', {}).get('name', 'Não informado'),
            "whatsapp_cliente": numero_cliente,
            "tipo_viagem": "Passagem Aérea", # Fixo por enquanto, pois estamos no fluxo de voo
            "origem_destino": f"{parametros.get('origem').get('business-name', parametros.get('origem').get('original', ''))} → {parametros.get('destino').get('city', parametros.get('destino').get('original', ''))}",
            "data_ida": data_ida_str,
            "data_volta": data_volta_str,
            "qtd_passageiros": parametros.get('passageiros', ''),
            "perfil_viagem": parametros.get('perfil_viagem', ''),
            "preferencias": parametros.get('preferencias', '')
        }
        
        print(f"📄 Dados formatados para o Notion: {dados_para_notion}")
        
        # Chama a função para criar a página no Notion
        create_notion_page(dados_para_notion)
        
        texto_resposta = "Sua solicitação foi registrada com sucesso! Um de nossos especialistas em viagens irá analisar e te enviar a proposta em breve aqui mesmo. Obrigado! 😊"

    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer. Pode tentar de novo?"

    # Monta a resposta final para o Dialogflow
    response_payload = {
        "fulfillment_response": {
            "messages": [{"text": {"text": [texto_resposta]}}]
        }
    }
    return jsonify(response_payload)