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

// --- LOG DE DIAGNÓSTICO 1: Verificando a Chave de API ---
console.log("--- DIAGNÓSTICO DE INICIALIZAÇÃO ---");
if (process.env.GEMINI_API_KEY) {
  console.log("Variável GEMINI_API_KEY encontrada.");
} else {
  console.error("ERRO CRÍTICO: Variável de ambiente GEMINI_API_KEY não foi encontrada!");
}
console.log("------------------------------------");

// --- Clientes das APIs (Corrigido) ---
const dialogflowClient = new SessionsClient({ apiEndpoint: `${process.env.LOCATION}-dialogflow.googleapis.com` });

// Inicialização do cliente VertexAI (autenticação via ambiente)
const vertex_ai = new VertexAI({ project: process.env.PROJECT_ID, location: 'us-central1' });
const model = 'gemini-2.5-flash';

const generativeModel = vertex_ai.getGenerativeModel({
  model: model,
});

const mainPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável, proativa e extremamente prestativa.
Seu objetivo é conversar com o usuário para entender suas necessidades de viagem. Você pode dar sugestões, falar sobre pacotes promocionais e responder a perguntas gerais.

Quando você identificar que o usuário está pronto para fazer uma cotação e você precisa coletar informações estruturadas (como origem, destino, datas, etc.), sua tarefa é avisá-lo que você vai iniciar a coleta de dados e, em seguida, retornar um comando especial para o sistema.

**Regras de Resposta:**
1.  **Conversa Natural:** Converse normalmente com o usuário, seja proativa e dê sugestões.
2.  **Seja Decisiva:** Se o usuário expressar um desejo claro de obter uma cotação (usando palavras como "cotar", "quanto custa", "ver preço", "pode ver pra mim?"), você **DEVE** parar a conversa e retornar o JSON de ação imediatamente, sem fazer mais perguntas de confirmação.
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
{
  "action": "iniciar_cotacao_passagem",
  "response": "Com certeza! Para te passar os melhores valores para o nordeste, vou iniciar nosso assistente de cotação. É bem rapidinho!"
}

EXEMPLO 3 (Pergunta Aleatória):
Usuário: qual a capital da França?
Vivi: A capital da França é Paris, a cidade luz! ✨ Falando em luz, já pensou em ver a Torre Eiffel de perto? Se quiser, podemos cotar uma viagem!
`;

// --- FUNÇÕES AUXILIARES (Mantidas conforme seu código) ---

// 1. Sua função de converter a requisição para o Dialogflow.
const twilioToDetectIntent = (req, text) => {
  const sessionId = req.body.From.replace('whatsapp:', '');
  const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
    process.env.PROJECT_ID, process.env.LOCATION, process.env.AGENT_ID, sessionId
  );
  const request = {
    session: sessionPath,
    queryInput: {
      text: { text: text || req.body.Body },
      languageCode: process.env.LANGUAGE_CODE,
    },
    queryParams: {
      parameters: {
        fields: { source: { stringValue: 'WHATSAPP', kind: 'stringValue' } }
      }
    }
  };
  return request;
};

// 2. Sua função de formatar a resposta do Dialogflow.
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
const conversationHistory = {};

async function triggerDialogflowEvent(eventName, sessionId, produto) {
  const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
    process.env.PROJECT_ID, process.env.LOCATION, process.env.AGENT_ID, sessionId
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

  const chat = generativeModel.startChat({
    history: conversationHistory[sessionId],
    systemInstruction: { role: 'system', parts: [{ text: mainPrompt }] }
  });
  const result = await chat.sendMessage(userInput);
  const response = await result.response;
  const geminiResponseText = response.candidates[0].content.parts[0].text;

  let actionJson = null;
  let responseToSend = geminiResponseText;

  // ▼▼▼ LÓGICA DE PARSING MAIS ROBUSTA ▼▼▼
  try {
    // Tenta encontrar e extrair um objeto JSON da string
    const jsonMatch = geminiResponseText.match(/\{[\s\S]*\}/);
    if (jsonMatch && jsonMatch[0]) {
      actionJson = JSON.parse(jsonMatch[0]);
    }
  } catch (e) {
    console.error("Não foi possível analisar a resposta como JSON, tratando como texto normal.", e);
    actionJson = null; // Garante que não prossiga se o JSON for inválido
  }

  // Se um JSON de ação válido foi encontrado
  if (actionJson && actionJson.action && actionJson.response) {
    console.log(`Ação detectada: ${actionJson.action}`);
    responseToSend = actionJson.response; // Usa apenas a frase de resposta

    // Dispara o evento para iniciar o fluxo no Dialogflow
    triggerDialogflowEvent(actionJson.action, sessionId)
      .catch(err => console.error("Erro ao disparar evento no Dialogflow:", err));
  }

  // Atualiza o histórico com a interação
  conversationHistory[sessionId].push({ role: "user", parts: [{ text: userInput }] });
  conversationHistory[sessionId].push({ role: "model", parts: [{ text: responseToSend }] });

  const twiml = new MessagingResponse();
  twiml.message(responseToSend);
  res.type('text/xml').send(twiml.toString());
});

const listener = app.listen(process.env.PORT || 8080, () => {
  console.log(`Seu servidor está a ouvir na porta ${listener.address().port}`);
});