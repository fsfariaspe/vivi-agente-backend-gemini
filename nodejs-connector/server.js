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

const dialogflowClient = new SessionsClient({ apiEndpoint: `us-central1-dialogflow.googleapis.com` });
const vertex_ai = new VertexAI({ project: process.env.PROJECT_ID, location: 'us-central1' });
const generativeModel = vertex_ai.getGenerativeModel({ model: 'gemini-2.5-flash' });

const mainPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável, proativa e extremamente prestativa.
Seu objetivo é conversar com o usuário para entender suas necessidades de viagem. Você pode dar sugestões, falar sobre pacotes promocionais e responder a perguntas gerais.

Quando você identificar que o usuário está pronto para fazer uma cotação e você precisa coletar informações estruturadas (como origem, destino, datas, etc.), sua tarefa é avisá-lo que você vai iniciar a coleta de dados e, em seguida, retornar um comando especial para o sistema.

**Regras de Resposta:**
1.  **Conversa Natural:** Converse normalmente com o usuário.
2.  **Identificar a Hora de Coletar Dados:** Quando a conversa chegar a um ponto onde você precisa de detalhes para uma cotação, você DEVE parar de conversar e retornar um JSON especial.
3.  **Formato do JSON de Ação:** O JSON deve ser a **ÚNICA COISA** na sua resposta. A estrutura deve ser:
    {
      "action": "NOME_DA_ACAO",
      "response": "A frase que você dirá ao usuário para iniciar a coleta."
    }
4.  **Nomes de Ação Válidos:** "iniciar_cotacao_passagem", "iniciar_cotacao_cruzeiro".

**Exemplos de Interação:**

EXEMPLO 1 (Consulta Aberta):
Usuário: Oi, tem alguma promoção de pacote de viagem?
Vivi: Olá! Temos sim! 🎉 Temos um pacote incrível para a Patagônia em setembro, com tudo incluso. Também temos uma super promoção para resorts em família no nordeste. Você tem interesse em algum desses ou prefere outro tipo de viagem?

EXEMPLO 2 (Decidindo Iniciar o Fluxo):
Usuário: Gostei da ideia do nordeste. Pode cotar para mim?
Vivi: (RETORNA APENAS O JSON ABAIXO)
\`\`\`json
{
  "action": "iniciar_cotacao_passagem",
  "response": "Com certeza! Para te passar os melhores valores para o nordeste, vou iniciar nosso assistente de cotação. É bem rapidinho!"
}
\`\`\`
`;

// --- Armazenamento do Histórico da Conversa ---
const conversationHistory = {};

// Função para chamar o Dialogflow com um evento e um parâmetro
async function triggerDialogflowEvent(eventName, sessionId, produto) {
    const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
        process.env.PROJECT_ID, 'us-central1', process.env.AGENT_ID, sessionId
    );
    const queryParams = {
        parameters: {
            fields: {
                produto_escolhido: { stringValue: produto, kind: 'stringValue' }
            }
        }
    };
    const request = {
        session: sessionPath,
        queryInput: {
            event: { event: eventName, languageCode: process.env.LANGUAGE_CODE },
        },
        queryParams: queryParams
    };
    console.log(`Disparando evento: ${eventName} com produto: ${produto}`);
    const [response] = await dialogflowClient.detectIntent(request);
    return response;
}

// --- ROTA PRINCIPAL CORRIGIDA ---
app.post('/', async (req, res) => {
    const userInput = req.body.Body;
    const sessionId = req.body.From.replace('whatsapp:', '');

    if (!conversationHistory[sessionId]) {
        conversationHistory[sessionId] = [];
    }

    try {
        const requestPayload = {
            contents: [...conversationHistory[sessionId], { role: 'user', parts: [{ text: userInput }] }],
            systemInstruction: {
                role: 'system',
                parts: [{ text: mainPrompt }]
            },
        };

        const result = await generativeModel.generateContent(requestPayload);
        const response = await result.response;
        const geminiResponseText = response.candidates[0].content.parts[0].text;

        let actionJson = null;
        let responseToSend = geminiResponseText;

        const jsonMatch = geminiResponseText.match(/\{[\s\S]*\}/);
        if (jsonMatch && jsonMatch[0]) {
            try {
                actionJson = JSON.parse(jsonMatch[0]);
            } catch (e) {
                console.error("Falha ao analisar o JSON extraído:", e);
            }
        }

        if (actionJson && actionJson.action && actionJson.response) {
            console.log(`Ação detectada: ${actionJson.action}`);
            responseToSend = actionJson.response;

            let produto = actionJson.action === 'iniciar_cotacao_passagem' ? 'passagem' : 'cruzeiro';

            triggerDialogflowEvent(actionJson.action, sessionId, produto)
                .catch(err => console.error("Erro ao disparar evento no Dialogflow:", err));
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