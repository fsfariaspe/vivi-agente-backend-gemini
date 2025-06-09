# Substitua a função identificar_cliente inteira por esta versão corrigida:

@functions_framework.http
def identificar_cliente(request):
    """Função "canivete suíço" que lida com diferentes ações do Dialogflow."""
    request_json = request.get_json(silent=True)
    tag = request_json.get('fulfillmentInfo', {}).get('tag', '')
    
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

    # AÇÃO 2: Salvar o nome e fazer a próxima pergunta
    elif tag == 'salvar_nome_e_perguntar_produto':
        parametros = request_json.get('sessionInfo', {}).get('parameters', {})
        # LINHA CORRIGIDA ABAIXO:
        nome_cliente = parametros.get('person', {}).get('resolvedValue', 'Cliente')
        
        # Salva a informação no banco
        mensagem_completa = f"O cliente informou o nome: {nome_cliente}"
        salvar_conversa_no_banco(numero_cliente, mensagem_completa, nome_cliente)

        # Define a próxima pergunta do fluxo
        texto_resposta = (
            f"Prazer em te conhecer, {nome_cliente}! ✨\n"
            "Pra gente começar, me diz com o que você precisa de ajuda hoje:\n\n"
            "a) Passagens Aéreas\n"
            "b) Cruzeiros\n"
            "c) Pacote completo (aéreo + hotel + translado)\n"
            "d) Outra opção"
        )

    else:
        texto_resposta = "Desculpe, não entendi o que preciso fazer. Pode tentar de novo?"

    # Monta a resposta final
    response_payload = {
        "fulfillment_response": {
            "messages": [{"text": {"text": [texto_resposta]}}]
        }
    }
    return jsonify(response_payload)