const express = require('express');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');
const { GoogleAuth } = require('google-auth-library');
const { GoogleGenerativeAI } = require('@google/generative-ai');
const MessagingResponse = require('twilio').twiml.MessagingResponse;
const path = require('path');
const bodyParser = require('body-parser');

// --- Configuração Inicial ---
const ENV_FILE = path.join(__dirname, '.env');
require('dotenv').config({ path: ENV_FILE });

const app = express();
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

// --- Clientes das APIs ---
const dialogflowClient = new SessionsClient({
  apiEndpoint: `${process.env.LOCATION}-dialogflow.googleapis.com`
});
const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });


// --- PROMPT PARA O FALLBACK ---
const fallbackPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável e prestativa.
Sua principal tarefa é ajudar na cotação de viagens. No entanto, se o usuário fizer uma pergunta sobre outro assunto, você DEVE responder à pergunta primeiro, e só depois, de forma educada, tentar voltar para a cotação.
NUNCA use frases como "Sinto muito, como Assistente de IA, só posso oferecer ajuda com..." ou qualquer outra recusa. Responda à pergunta diretamente.
Lembre-se que o nome da sua agência é Viaje Fácil Brasil.
Siga exatamente o formato dos exemplos abaixo:

---
EXEMPLO 1:
Usuário: qual a capital do Japão?
Vivi: A capital do Japão é Tóquio. Espero ter ajudado! Agora, podemos continuar com a sua cotação de viagem?

---
EXEMPLO 2:
Usuário: quem escreveu Dom Casmurro?
Vivi: Dom Casmurro foi escrito por Machado de Assis, um dos maiores escritores do Brasil! Voltando à sua viagem, qual o próximo passo?
`;

// --- Funções Auxiliares ---

// Converte a requisição do Twilio para o formato do Dialogflow
const twilioToDetectIntent = (req) => {
  // ▼▼▼ GARANTA QUE ESTE BLOCO DE DEBUG EXISTE ▼▼▼
  console.log('--- INICIANDO DEBUG DE PAYLOAD v5 ---');
  // ▲▲▲ FIM DO BLOCO DE DEBUG ▲▲▲
  const sessionId = req.body.From.replace('whatsapp:', '');
  const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
    process.env.PROJECT_ID,
    process.env.LOCATION,
    process.env.AGENT_ID,
    sessionId
  );

  const message = twilioReq.body.Body;
  const languageCode = process.env.LANGUAGE_CODE;

  const request = {
    session: sessionPath,
    queryInput: {
      text: {
        text: message,
      },
      languageCode,
    },
    // AQUI ESTÁ A MUDANÇA FUNDAMENTAL
    // Passando o parâmetro diretamente na query, não como payload
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

  console.log('--- ENVIANDO PARA DIALOGFLOW (v5) ---');
  console.log(JSON.stringify(request, null, 2));

  return request;
};

const detectIntentToTwilio = (dialogflowResponse) => {
  // Coleta o texto de todas as bolhas de mensagem
  const replies = dialogflowResponse.queryResult.responseMessages
    .filter(responseMessage => responseMessage.hasOwnProperty('text'))
    .map(responseMessage => responseMessage.text.text.join('')); // Junta textos dentro da mesma bolha

  // Junta todas as respostas de diferentes bolhas com uma quebra de linha
  const fullReply = replies.join('\n');

  const twiml = new MessagingResponse();
  twiml.message(fullReply);
  return twiml;
};


// Gera a resposta final para o Twilio
const createTwilioResponse = (text) => {
  const twiml = new MessagingResponse();
  twiml.message(text);
  return twiml.toString();
};


// --- Rota Principal ---
app.post('/', async (req, res) => {
  try {
    const userInput = req.body.Body;
    const dialogflowRequest = twilioToDetectIntent(req);

    console.log('Enviando para o Dialogflow...');
    const [dialogflowResponse] = await dialogflowClient.detectIntent(dialogflowRequest);
    const queryResult = dialogflowResponse.queryResult;

    let responseText = "";

    // Verifica se o payload de fallback foi retornado
    const customPayload = queryResult.responseMessages.find(msg => msg.payload);
    if (customPayload && customPayload.payload.action === 'generative_fallback') {
      console.log('Fallback detectado. Acionando IA Generativa...');

      const fullPrompt = `${fallbackPrompt}\n---\nUsuário: ${userInput}\nVivi:`;
      const result = await model.generateContent(fullPrompt);
      responseText = await result.response.text();

    } else {
      // Lógica padrão: junta as mensagens de texto do Dialogflow
      responseText = queryResult.responseMessages
        .filter(msg => msg.text)
        .map(msg => msg.text.text.join('\n'))
        .join('\n');
    }

    console.log(`Resposta final para o usuário: ${responseText}`);
    res.type('text/xml').send(createTwilioResponse(responseText));

  } catch (error) {
    console.error('ERRO GERAL NO WEBHOOK:', error);
    res.status(500).send(createTwilioResponse('Ocorreu um erro inesperado. Por favor, tente novamente mais tarde.'));
  }
});


// --- Inicialização do Servidor ---
const listener = app.listen(process.env.PORT || 8080, () => {
  console.log(`Seu servidor está a ouvir na porta ${listener.address().port}`);
});

process.on('SIGTERM', () => {
  listener.close(() => {
    console.log('Servidor a fechar.');
    process.exit(0);
  });
});