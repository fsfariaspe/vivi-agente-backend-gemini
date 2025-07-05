const express = require('express');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');
// --- MUDANÇA 1: Importando a biblioteca correta ---
const { VertexAI } = require('@google-cloud/vertexai');
const MessagingResponse = require('twilio').twiml.MessagingResponse;
const path = require('path');
const bodyParser = require('body-parser');

// --- Configurações Iniciais ---
const ENV_FILE = path.join(__dirname, '.env');
require('dotenv').config({ path: ENV_FILE });

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

// --- Clientes das APIs ---
const dialogflowClient = new SessionsClient({ apiEndpoint: `${process.env.LOCATION}-dialogflow.googleapis.com` });

// --- MUDANÇA 2: Inicializando o cliente Vertex AI (sem chave de API!) ---
const vertex_ai = new VertexAI({ project: process.env.PROJECT_ID, location: 'us-central1' });
const model = 'gemini-1.5-flash-001';

const generativeModel = vertex_ai.getGenerativeModel({
  model: model,
});

// --- Armazenamento do Histórico da Conversa (Simples, em memória) ---
const conversationHistory = {};

// --- PROMPT ATUALIZADO PARA O NOVO MODELO ---
const mainPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável, proativa e prestativa.
Seu objetivo é conversar com o usuário, entender suas necessidades e dar sugestões.

**Regras de Decisão:**
1.  **Converse Naturalmente:** Responda às perguntas do usuário de forma natural. Se pedirem sugestões de viagem ou promoções, seja criativa.
2.  **Identifique a Hora de Coletar Dados:** Quando você tiver informações suficientes e o usuário confirmar que quer uma cotação, você DEVE parar a conversa e retornar um JSON especial para acionar um fluxo de coleta de dados.
3.  **Formato do JSON de Ação:** O JSON deve ter a estrutura:
    {
      "action": "NOME_DA_ACAO",
      "response": "A frase que você dirá ao usuário para iniciar a coleta."
    }
4.  **Nomes de Ação Válidos:** "iniciar_cotacao_passagem" ou "iniciar_cotacao_cruzeiro".

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
async function triggerDialogflowEvent(eventName, sessionId, produto) {
  const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
    process.env.PROJECT_ID, process.env.LOCATION, process.env.AGENT_ID, sessionId
  );

  // Monta os parâmetros que serão enviados com o evento
  const queryParams = {
    parameters: {
      fields: {
        produto_escolhido: {
          stringValue: produto,
          kind: 'stringValue'
        }
      }
    }
  };

  const request = {
    session: sessionPath,
    queryInput: {
      event: { event: eventName, languageCode: process.env.LANGUAGE_CODE },
    },
    queryParams: queryParams // Adiciona os parâmetros aqui
  };

  console.log(`Disparando evento: ${eventName} com produto: ${produto}`);
  const [response] = await dialogflowClient.detectIntent(request);
  return response;
}

// --- ROTA PRINCIPAL COM LOGS DETALHADOS ---
app.post('/', async (req, res) => {
  const userInput = req.body.Body;
  const sessionId = req.body.From.replace('whatsapp:', '');
  console.log(`[${sessionId}] Mensagem recebida: "${userInput}"`);

  // Inicializa o histórico se for a primeira vez
  if (!conversationHistory[sessionId]) {
    conversationHistory[sessionId] = [];
  }

  // Adiciona a mensagem do usuário ao histórico
  conversationHistory[sessionId].push({ role: "user", parts: [{ text: userInput }] });

  // Detecta se a intenção é entrar em um fluxo estruturado
  const detectActionPrompt = `Analise a última mensagem do usuário: "${userInput}". O usuário quer iniciar uma cotação de "passagem" ou "cruzeiro"? Se sim, responda com o JSON de ação correspondente. Se não, responda com "conversar".`;

  try {
    const actionModel = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });
    const actionResult = await actionModel.generateContent(detectActionPrompt);
    const actionResponseText = (await actionResult.response).text();

    let actionJson = null;
    try {
      actionJson = JSON.parse(actionResponseText);
    } catch (e) {
      // Não é um JSON, continua a conversa normal
    }

    if (actionJson && actionJson.action) {
      console.log(`Ação detectada pela IA: ${actionJson.action}`);

      let produto = actionJson.action === 'iniciar_cotacao_passagem' ? 'passagem' : 'cruzeiro';

      // Dispara o evento correspondente no Dialogflow COM O PARÂMETRO
      const dialogflowResponse = await triggerDialogflowEvent("iniciar_cotacao", sessionId, produto);
      const twimlResponse = detectIntentToTwilio(dialogflowResponse);

      // Envia a primeira mensagem do fluxo
      return res.type('text/xml').send(twimlResponse.toString());
    }

    // Se nenhuma ação for detectada, continua a conversa generativa
    console.log('Nenhuma ação detectada, continuando conversa com o Gemini.');
    const chat = model.startChat({ history: conversationHistory[sessionId] });
    const result = await chat.sendMessage(userInput);
    const geminiText = (await result.response).text();

    conversationHistory[sessionId].push({ role: "model", parts: [{ text: geminiText }] });

    const twiml = new MessagingResponse();
    twiml.message(geminiText);
    return res.type('text/xml').send(twiml.toString());

  } catch (error) {
    console.error('ERRO GERAL NO WEBHOOK:', error);
    const errorTwiml = new MessagingResponse();
    errorTwiml.message('Ocorreu um erro inesperado. Por favor, tente novamente.');
    res.status(500).type('text/xml').send(errorTwiml.toString());
  }

  console.log('Nenhuma ação detectada, continuando conversa com o Gemini.');
  const fullPrompt = `${mainPrompt}\n---\nUsuário: ${userInput}\nVivi:`;

  try {
    // --- MUDANÇA 3: Usando o método correto para a nova biblioteca ---
    const result = await generativeModel.generateContent(fullPrompt);
    const response = await result.response;
    const geminiText = response.candidates[0].part.text;

    console.log(`Texto da IA: ${geminiText}`);

    const twiml = new MessagingResponse();
    twiml.message(geminiText);
    return res.type('text/xml').send(twiml.toString());

  } catch (error) {
    console.error('--- ERRO CAPTURADO NA CHAMADA DO VERTEX AI ---');
    console.error('MENSAGEM:', error.message);
    console.error('STACK TRACE:', error.stack);

    const errorTwiml = new MessagingResponse();
    errorTwiml.message('Desculpe, estou com um problema para me conectar à minha inteligência. Tente novamente em um instante.');
    res.status(500).type('text/xml').send(errorTwiml.toString());
  }
});

const listener = app.listen(process.env.PORT || 8080, () => {
  console.log(`Seu servidor está a ouvir na porta ${listener.address().port}`);
});