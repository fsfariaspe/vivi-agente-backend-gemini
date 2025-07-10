const express = require('express');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');
const { VertexAI } = require('@google-cloud/vertexai');
const MessagingResponse = require('twilio').twiml.MessagingResponse;
const path = require('path');
const bodyParser = require('body-parser');

require('dotenv').config();

const app = express();
app.use(bodyParser.urlencoded({ extended: false }));
app.use(bodyParser.json());

// --- Clientes das APIs ---
const dialogflowClient = new SessionsClient({ apiEndpoint: `us-central1-dialogflow.googleapis.com` });
const vertex_ai = new VertexAI({ project: process.env.PROJECT_ID, location: 'us-central1' });
const generativeModel = vertex_ai.getGenerativeModel({ model: 'gemini-2.5-flash' });

// --- Armazenamento de Histórico e Estado da Conversa ---
const conversationHistory = {};
const conversationState = {}; // Objeto para guardar o estado de cada conversa

const mainPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável, proativa e extremamente prestativa.
Seu objetivo é conversar com o usuário para entender suas necessidades de viagem. Você pode dar sugestões, falar sobre pacotes promocionais e responder a perguntas gerais.

Quando você identificar que o usuário está pronto para fazer uma cotação e você precisa coletar informações estruturadas (como origem, destino, datas, etc.), sua tarefa é avisá-lo que você vai iniciar a coleta de dados e, em seguida, retornar um comando especial para o sistema.

**Regras de Resposta:**
1.  **Conversa Natural:** Converse normalmente com o usuário.
2.  **Identificar Hora de Cotar:** Quando o usuário pedir para cotar, você DEVE retornar o JSON de ação.
3.  **Extrair Parâmetros:** Analise a frase do usuário e extraia qualquer informação que corresponda aos seguintes parâmetros: 
    - Passagens Aéreas: person, origem, destino, data_ida, data_volta, passageiros, perfil_viagem, preferencias.
    - Cruzeiros: person, destino_cruzeiro, porto_embarque, periodo_cruzeiro, adultos_cruzeiro, numero_criancas, idade_crianca, companhia_cruzeiro, acessibilidade_cruzeiro, status_tarifa_senior.
4.  **Formato do JSON de Ação:** O JSON deve ser a **ÚNICA COISA** na sua resposta. A estrutura é:
    {
      "action": "NOME_DA_ACAO",
      "response": "Sua frase de transição.",
      "parameters": { // Campo opcional com os parâmetros extraídos
        "nome_do_parametro": "valor_extraido"
      }
    }
5.  **Nomes de Ação Válidos:** "iniciar_cotacao_passagem", "iniciar_cotacao_cruzeiro".

**Exemplos de Interação:**

EXEMPLO 1 (Consulta Aberta):
Usuário: Oi, tem alguma promoção de pacote de viagem?
Vivi: Olá! Temos sim! 🎉 Temos um pacote incrível para a Patagônia em setembro, com tudo incluso. Também temos uma super promoção para resorts em família no nordeste. Você tem interesse em algum desses ou prefere outro tipo de viagem?

EXEMPLO 2 (Decidindo Iniciar o Fluxo):
Usuário: Gostei da ideia do nordeste. Pode cotar para mim?

EXEMPLO 3
Usuário: queria cotar uma passagem pra Fortaleza em Dezembro
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_passagem",
  "response": "Com certeza! Fortaleza em Dezembro é uma ótima pedida! Para te ajudar, vou iniciar nosso assistente de cotação.",
  "parameters": {
    "destino": "Fortaleza",
    "data_ida": "15/3/2025" 
  }
}
\`\`\`
`;

// --- FUNÇÕES AUXILIARES (CORRIGIDAS E PRESENTES) ---

const twilioToDetectIntent = (req) => {
    const sessionId = req.body.From.replace('whatsapp:', '');
    const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
        process.env.PROJECT_ID, 'us-central1', process.env.AGENT_ID, sessionId
    );

    const request = {
        session: sessionPath,
        queryInput: {
            text: { text: req.body.Body },
            languageCode: process.env.LANGUAGE_CODE,
        },
        // ▼▼▼ GARANTINDO QUE O PARÂMETRO DE ORIGEM SEJA ENVIADO ▼▼▼
        queryParams: {
            parameters: {
                fields: {
                    source: {
                        stringValue: 'WHATSAPP',
                        kind: 'stringValue'
                    }
                }
            }
        }
    };
    return request;
};

const detectIntentToTwilio = (dialogflowResponse) => {
    const replies = dialogflowResponse.queryResult.responseMessages
        .filter(responseMessage => responseMessage.text)
        .map(responseMessage => responseMessage.text.text.join('\n'))
        .join('\n');

    const twiml = new MessagingResponse();
    if (replies) {
        twiml.message(replies);
    }
    return twiml;
};

// Função para chamar o Dialogflow com um evento e um parâmetro
async function triggerDialogflowEvent(eventName, sessionId, produto, params = {}) {
    const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
        process.env.PROJECT_ID, 'us-central1', process.env.AGENT_ID, sessionId
    );

    // ▼▼▼ CORREÇÃO APLICADA AQUI ▼▼▼
    // Adiciona o produto aos outros parâmetros antes de construir o objeto final
    params.produto_escolhido = produto;

    const fields = {};
    for (const key in params) {
        if (params[key]) {
            fields[key] = { stringValue: params[key], kind: 'stringValue' };
        }
    }

    const queryParams = { parameters: { fields } };

    const request = {
        session: sessionPath,
        queryInput: {
            event: { event: eventName },
            languageCode: process.env.LANGUAGE_CODE
        },
        queryParams: queryParams
    };

    console.log(`Disparando evento: ${eventName} com produto: ${produto} e com parâmetros:`, params);
    console.log('DEBUG: Enviando os seguintes queryParams:', JSON.stringify(request.queryParams, null, 2));
    const [response] = await dialogflowClient.detectIntent(request);
    return response;
}

// --- ROTA PRINCIPAL CORRIGIDA ---
// --- ROTA PRINCIPAL COMPLETA E CORRIGIDA ---
app.post('/', async (req, res) => {
    const userInput = req.body.Body;
    const sessionId = req.body.From.replace('whatsapp:', '');

    if (!conversationHistory[sessionId]) {
        conversationHistory[sessionId] = [];
    }

    try {
        // VERIFICA SE O USUÁRIO JÁ ESTÁ EM UM FLUXO
        if (conversationState[sessionId] === 'IN_FLOW') {
            console.log('Usuário está em um fluxo. Enviando para o Dialogflow...');
            const dialogflowRequest = twilioToDetectIntent(req);
            const [dialogflowResponse] = await dialogflowClient.detectIntent(dialogflowRequest);

            console.log('DEBUG: Parâmetros atuais na sessão do Dialogflow:', JSON.stringify(dialogflowResponse.queryResult.parameters, null, 2));

            // ▼▼▼ LÓGICA ATUALIZADA PARA FIM DE FLUXO OU CANCELAMENTO ▼▼▼
            // Procura pelo nosso "sinal secreto" (Custom Payload) na resposta
            const customPayload = dialogflowResponse.queryResult.responseMessages.find(
                msg => msg.payload && msg.payload.fields && msg.payload.fields.flow_status
            );

            // Se o sinal for encontrado e for "finished" ou "cancelled_by_user", reseta o estado
            if (customPayload) {
                const flowStatus = customPayload.payload.fields.flow_status.stringValue;
                if (flowStatus === 'finished' || flowStatus === 'cancelled_by_user') {
                    console.log(`Sinal de '${flowStatus}' detectado. Resetando estado para IA Generativa.`);
                    delete conversationState[sessionId];
                    delete conversationHistory[sessionId];
                }
            }

            const twimlResponse = detectIntentToTwilio(dialogflowResponse);
            res.type('text/xml').send(twimlResponse.toString());
            return;
        }

        // SE NÃO ESTIVER EM FLUXO, USA A IA GENERATIVA
        console.log('Iniciando conversa com o Gemini...');
        const chat = generativeModel.startChat({
            history: conversationHistory[sessionId],
            systemInstruction: { role: 'system', parts: [{ text: mainPrompt }] }
        });
        const result = await chat.sendMessage(userInput);
        const response = result.response;
        const geminiResponseText = response.candidates[0].content.parts[0].text;

        let actionJson = null;
        let responseToSend = geminiResponseText;

        const jsonMatch = geminiResponseText.match(/\{[\s\S]*\}/);
        if (jsonMatch && jsonMatch[0]) {
            try {
                actionJson = JSON.parse(jsonMatch[0]);
            } catch (e) {
                console.error("Não foi possível analisar a resposta como JSON, tratando como texto normal.", e);
            }
        }

        if (actionJson && actionJson.action) {
            console.log(`Ação detectada: ${actionJson.action}`);

            const transitionMessage = actionJson.response || "Ok, vamos começar!";
            const parameters = actionJson.parameters || {};
            const produto = actionJson.action.includes('passagem') ? 'passagem' : 'cruzeiro';

            // Anota na "memória" que o usuário agora está em um fluxo
            conversationState[sessionId] = 'IN_FLOW';
            console.log(`Estado para ${sessionId} alterado para IN_FLOW.`);

            // Dispara o evento e passa TODOS os parâmetros que a IA extraiu
            triggerDialogflowEvent('iniciar_cotacao', sessionId, produto, parameters)
                .catch(err => console.error("Erro ao disparar evento no Dialogflow:", err));

            // Envia APENAS a mensagem de transição da IA para o usuário
            responseToSend = transitionMessage;
        }

        conversationHistory[sessionId].push({ role: "user", parts: [{ text: userInput }] });
        conversationHistory[sessionId].push({ role: "model", parts: [{ text: responseToSend }] });

        const twiml = new MessagingResponse();
        twiml.message(responseToSend);
        res.type('text/xml').send(twiml.toString());

    } catch (error) {
        console.error('ERRO GERAL NO WEBHOOK:', error);
        const errorTwiml = new MessagingResponse();
        errorTwiml.message('Desculpe, ocorreu um problema e não consigo responder agora.');
        res.status(500).type('text/xml').send(errorTwiml.toString());
    }
});

const listener = app.listen(process.env.PORT || 8080, () => {
    console.log(`Seu servidor está a ouvir na porta ${listener.address().port}`);
});