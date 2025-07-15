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
const flowContext = {}; // Guarda o contexto do fluxo pausado (ex: a última pergunta)

const mainPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável, proativa e extremamente prestativa.
Seu objetivo é conversar com o usuário para entender suas necessidades de viagem. Você pode dar sugestões, falar sobre pacotes promocionais e responder a perguntas gerais.

Quando você identificar que o usuário está pronto para fazer uma cotação e você precisa coletar informações estruturadas (como origem, destino, datas, etc.), sua tarefa é avisá-lo que você vai iniciar a coleta de dados e, em seguida, retornar um comando especial para o sistema.

**Regras de Resposta:**
1.  **Conversa Natural:** Converse normalmente com o usuário.
2.  **Seja Decisiva:** Se o usuário expressar um desejo claro de obter uma cotação (usando palavras como "cotar", "preço", "quanto custa"), você DEVE retornar o JSON de ação imediatamente.
3.  **Extrair Parâmetros:** Analise a frase do usuário e extraia qualquer informação que corresponda aos seguintes parâmetros: 
    - Passagens Aéreas: person, origem, destino, data_ida, data_volta, passageiros, perfil_viagem, preferencias.
    - Cruzeiros: person, destino_cruzeiro, porto_embarque, periodo, adultos_cruzeiro, numero_criancas, idade_crianca, companhia_cruzeiro, acessibilidade_cruzeiro, status_tarifa_senior.
4.  **Priorize o Nome:** Se o usuário se apresentar (ex: "meu nome é...", "sou o...", "me chamo..."), você DEVE obrigatoriamente extrair o nome dele e incluí-lo no parâmetro "person".
5.  **Formato do JSON de Ação:** O JSON deve ser a **ÚNICA COISA** na sua resposta. A estrutura é:
    {
      "action": "NOME_DA_ACAO",
      "response": "Sua frase de transição.",
      "parameters": { // Campo opcional com os parâmetros extraídos
        "nome_do_parametro": "valor_extraido"
      }
    }
6.  **Nomes de Ação Válidos:** "iniciar_cotacao_passagem", "iniciar_cotacao_cruzeiro".

**Exemplos de Interação:**

EXEMPLO 1 (Passagem Simples):
Usuário: queria cotar uma passagem pra Fortaleza
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_passagem",
  "response": "Com certeza! Fortaleza é um destino maravilhoso! Para te ajudar a encontrar as melhores passagens, vou iniciar nosso assistente de cotação. É bem rapidinho! Para confirmar digite (Sim)",
  "parameters": {
    "destino": "Fortaleza"
  }
}
\`\`\`

EXEMPLO 2 (Passagem com Nome e Data):
Usuário: Oi, meu nome é Eduardo e eu queria ver o preço de um voo para o Rio de Janeiro saindo dia 10 de maio.
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_passagem",
  "response": "Olá, Eduardo! Claro, vamos cotar sua passagem para o Rio. Vou iniciar nosso assistente para coletar os últimos detalhes. Para confirmar digite (Sim)",
  "parameters": {
    "person": "Eduardo",
    "destino": "Rio de Janeiro",
    "data_ida": "10/05/2025"
  }
}
\`\`\`

EXEMPLO 3 (Passagem com Nome e Período):
Usuário: Oi, meu nome é Eduardo e eu queria ver o preço de um voo para o Rio de Janeiro saindo no melhor valor em maio.
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_passagem",
  "response": "Olá, Eduardo! Claro, vamos cotar sua passagem para o Rio. Vou iniciar nosso assistente para coletar os últimos detalhes. Para confirmar digite (Sim)",
  "parameters": {
    "person": "Eduardo",
    "destino": "Rio de Janeiro",
    "periodo": "melhor valor em maio"
  }
}
\`\`\`

EXEMPLO 4 (Cruzeiro com Detalhes):
Usuário: Queria saber o preço de um cruzeiro pela costa brasileira para 2 adultos, saindo de Santos.
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_cruzeiro",
  "response": "Ótima ideia! Um cruzeiro pela nossa costa é incrível. Vou iniciar o assistente para montarmos a viagem perfeita para vocês! Para confirmar digite (Sim)",
  "parameters": {
    "destino_cruzeiro": "Costa Brasileira",
    "adultos_cruzeiro": "2",
    "porto_embarque": "Santos"
  }
}
\`\`\`

EXEMPLO 5 (Cruzeiro com Detalhes e Período):
Usuário: Queria saber o preço de um cruzeiro pela costa brasileira para 2 adultos, saindo de Santos em fevereiro do próximo ano.
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_cruzeiro",
  "response": "Ótima ideia! Um cruzeiro pela nossa costa é incrível. Vou iniciar o assistente para montarmos a viagem perfeita para vocês! Para confirmar digite (Sim)",
  "parameters": {
    "destino_cruzeiro": "Costa Brasileira",
    "adultos_cruzeiro": "2",
    "porto_embarque": "Santos",
    "periodo": "fevereiro do próximo ano"
  }
}
\`\`\`

EXEMPLO 6 (Consulta Aberta):
Usuário: Oi, tem alguma promoção de pacote de viagem?
Vivi: Olá! Temos sim! 🎉 Temos um pacote incrível para a Patagônia em setembro, com tudo incluso. Também temos uma super promoção para resorts em família no nordeste. Você tem interesse em algum desses ou prefere outro tipo de viagem?
`;

// ▼▼▼ ADICIONE ESTA FUNÇÃO ▼▼▼
function isGenericQuestion(text) {
    const questionWords = ['quem', 'qual', 'quais', 'onde', 'quando', 'como', 'por que', 'porque', 'o que', 'me diga', 'me conte', 'queria saber', 'poderia me dizer', 'você sabe', 'você pode me contar', 'gostaria de saber', 'você conhece', 'você tem informações sobre', 'veja', 'olha', 'escuta', 'escute', 'me fale', 'me fale sobre'];
    if (!text) return false;
    const lowerCaseText = text.toLowerCase().trim();

    // Se terminar com '?', é uma pergunta.
    if (lowerCaseText.endsWith('?')) {
        return true;
    }

    const words = lowerCaseText.split(' ');
    // Se a primeira palavra for de pergunta, é uma pergunta.
    if (questionWords.includes(words[0])) {
        return true;
    }

    // Se a segunda palavra for de pergunta (para casos como "e quem...", "mas qual..."), é uma pergunta.
    if (words.length > 1 && questionWords.includes(words[1])) {
        return true;
    }

    return false;
}

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

    // ▼▼▼ CORREÇÃO APLICADA AQUI ▼▼▼
    // Adiciona o parâmetro 'source' junto com os outros parâmetros da IA
    fields.source = { stringValue: 'WHATSAPP', kind: 'stringValue' };

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

// --- ROTA PRINCIPAL ---
app.post('/', async (req, res) => {
    const userInput = req.body.Body;
    const sessionId = req.body.From.replace('whatsapp:', '');

    if (!conversationHistory[sessionId]) conversationHistory[sessionId] = [];
    if (!conversationState[sessionId]) conversationState[sessionId] = 'ia';

    let responseToSend = "";
    const twiml = new MessagingResponse();

    try {
        if (conversationState[sessionId] === 'AWAITING_FLOW_CONFIRMATION') {
            // Verifica se o usuário disse "sim" E se o contexto do fluxo existe
            if (userInput.toLowerCase().trim() === 'sim' && flowContext[sessionId]) {
                console.log('Usuário confirmou o início do fluxo.');

                const { action, parameters } = flowContext[sessionId];
                const produto = action.includes('passagem') ? 'passagem' : 'cruzeiro';

                conversationState[sessionId] = 'in_flow';
                const dialogflowResponse = await triggerDialogflowEvent('iniciar_cotacao', sessionId, produto, parameters);

                responseToSend = (dialogflowResponse.queryResult.responseMessages || [])
                    .filter(m => m.text && m.text.text.length > 0)
                    .map(m => m.text.text.join('\n'))
                    .join('\n');

                if (responseToSend) {
                    flowContext[sessionId].lastBotQuestion = responseToSend;
                }

            } else {
                console.log('Usuário não confirmou ou contexto perdido. Voltando para a IA.');
                delete conversationState[sessionId];

                const chat = generativeModel.startChat({ history: conversationHistory[sessionId] });
                const result = await chat.sendMessage("Ok, não vou iniciar a cotação agora. Como posso te ajudar então?");
                responseToSend = (await result.response).candidates[0].content.parts[0].text;
            }

            // ESTADO: PAUSADO - Aguardando 'sim' para retornar ao fluxo
        } else if (conversationState[sessionId] === 'paused') {
            if (userInput.toLowerCase().trim() === 'sim') {
                console.log('Usuário confirmou o retorno ao fluxo.');
                conversationState[sessionId] = 'in_flow';
                responseToSend = flowContext[sessionId]?.lastBotQuestion || "Ok, continuando... Qual era a informação que você ia me passar?";
            } else {
                console.log('IA responde enquanto fluxo está pausado...');
                const result = await generativeModel.generateContent({ contents: [{ role: 'user', parts: [{ text: userInput }] }] });
                const geminiText = (await result.response).candidates[0].content.parts[0].text;
                responseToSend = `${geminiText}\n\nQuando quiser, me diga 'sim' para continuarmos a cotação.`;
            }

            // ESTADO: EM FLUXO - Interagindo com o Dialogflow
        } else if (conversationState[sessionId] === 'in_flow') {
            if (isGenericQuestion(userInput)) {
                console.log('Pergunta genérica detectada. Pausando fluxo...');
                conversationState[sessionId] = 'paused';
                const result = await generativeModel.generateContent({ contents: [{ role: 'user', parts: [{ text: userInput }] }] });
                const geminiText = (await result.response).candidates[0].content.parts[0].text;
                responseToSend = `${geminiText}\n\nPodemos voltar para a sua cotação agora? (responda 'sim' para continuar)`;
            } else {
                console.log('Não é pergunta genérica. Enviando para o Dialogflow...');
                const dialogflowRequest = twilioToDetectIntent(req);
                const [dialogflowResponse] = await dialogflowClient.detectIntent(dialogflowRequest);
                const twimlResponse = detectIntentToTwilio(dialogflowResponse);
                responseToSend = (dialogflowResponse.queryResult.responseMessages || [])
                    .filter(m => m.text && m.text.text.length > 0)
                    .map(m => m.text.text.join('\n'))
                    .join('\n');

                if (responseToSend) {
                    flowContext[sessionId] = { lastBotQuestion: responseToSend };
                }

                const customPayload = dialogflowResponse.queryResult.responseMessages.find(m => m.payload?.fields?.flow_status);
                if (customPayload) {
                    const flowStatus = customPayload.payload.fields.flow_status.stringValue;
                    if (flowStatus === 'finished' || flowStatus === 'cancelled_by_user') {
                        console.log(`Sinal de '${flowStatus}' detectado. Resetando estado e histórico.`);
                        delete conversationState[sessionId];
                        delete conversationHistory[sessionId];
                        delete flowContext[sessionId];
                    }
                }
            }

            // ESTADO: IA - Conversa aberta, decidindo o que fazer
        } else {
            console.log('IA no controle. Verificando intenção...');
            const chat = generativeModel.startChat({
                history: conversationHistory[sessionId],
                systemInstruction: { role: 'system', parts: [{ text: mainPrompt }] }
            });
            const result = await chat.sendMessage(userInput);
            const geminiResponseText = (await result.response).candidates[0].content.parts[0].text;

            let actionJson = null;
            try {
                const jsonMatch = geminiResponseText.match(/\{[\s\S]*\}/);
                if (jsonMatch) actionJson = JSON.parse(jsonMatch[0]);
            } catch (e) { }

            if (actionJson && actionJson.action) {
                console.log(`Ação detectada: ${actionJson.action}`);
                conversationState[sessionId] = 'IN_FLOW';
                const transitionMessage = actionJson.response || "Ok, vamos começar!";
                const parameters = actionJson.parameters || {};
                const produto = actionJson.action.includes('passagem') ? 'passagem' : 'cruzeiro';

                const dialogflowResponse = await triggerDialogflowEvent('iniciar_cotacao', sessionId, produto, parameters);
                const flowFirstMessage = (dialogflowResponse.queryResult.responseMessages || [])
                    .filter(m => m.text && m.text.text.length > 0)
                    .map(m => m.text.text.join('\n'))
                    .join('\n');

                // Envia a mensagem de transição e a primeira pergunta em balões separados
                twiml.message(transitionMessage);
                conversationState[sessionId] = 'AWAITING_FLOW_CONFIRMATION';
                /*
                if (flowFirstMessage) {
                    twiml.message(flowFirstMessage);
                }*/
                flowContext[sessionId] = {
                    action: actionJson.action,
                    parameters: parameters,
                    lastBotQuestion: flowFirstMessage
                };

                console.log(`Status da conversationState: ${conversationState[sessionId]}`);

                return res.type('text/xml').send(twiml.toString());
            } else {
                responseToSend = geminiResponseText;
            }
        }

        conversationHistory[sessionId].push({ role: "user", parts: [{ text: userInput }] });
        conversationHistory[sessionId].push({ role: "model", parts: [{ text: responseToSend }] });

        if (responseToSend) {
            twiml.message(responseToSend);
        }

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