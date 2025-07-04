const express = require('express');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');
const { GoogleAuth } = require('google-auth-library');
const { GoogleGenerativeAI } = require('@google/generative-ai');
const MessagingResponse = require('twilio').twiml.MessagingResponse;
const path = require('path');
const bodyParser = require('body-parser');

const ENV_FILE = path.join(__dirname, '.env');
require('dotenv').config({ path: ENV_FILE });

const app = express();
app.use(bodyParser.json());
app.use(bodyParser.urlencoded({ extended: true }));

const dialogflowClient = new SessionsClient({ apiEndpoint: `${process.env.LOCATION}-dialogflow.googleapis.com` });
const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({ model: "gemini-1.5-flash" });

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

// --- SUAS FUNÇÕES PRESERVADAS ---

// 1. Sua função de converter a requisição para o Dialogflow, incluindo os queryParams.
const twilioToDetectIntent = (req) => {
  const sessionId = req.body.From.replace('whatsapp:', '');
  const sessionPath = dialogflowClient.projectLocationAgentSessionPath(
    process.env.PROJECT_ID, process.env.LOCATION, process.env.AGENT_ID, sessionId
  );
  const request = {
    session: sessionPath,
    queryInput: {
      text: { text: req.body.Body },
      languageCode: process.env.LANGUAGE_CODE,
    },
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

// 2. Sua função de formatar a resposta do Dialogflow para TwiML.
const detectIntentToTwilio = (dialogflowResponse) => {
  const replies = dialogflowResponse.queryResult.responseMessages
    .filter(responseMessage => responseMessage.hasOwnProperty('text'))
    .map(responseMessage => responseMessage.text.text.join(''))
    .join('\n');

  const twiml = new MessagingResponse();
  if (replies) {
    twiml.message(replies);
  }
  return twiml;
};

// Função para verificar se a entrada é uma pergunta genérica
function isGenericQuestion(text) {
  const questionWords = ['quem', 'qual', 'quais', 'onde', 'quando', 'como', 'por que', 'o que', 'me diga', 'me conte'];
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

// --- ROTA PRINCIPAL ATUALIZADA ---
app.post('/', async (req, res) => {
  try {
    const userInput = req.body.Body;
    console.log(`Mensagem recebida: "${userInput}"`);

    // NOVA LÓGICA: Verifica se é uma pergunta genérica PRIMEIRO.
    if (isGenericQuestion(userInput)) {
      console.log('Pergunta genérica detectada. Acionando IA Generativa diretamente...');

      const fullPrompt = `${fallbackPrompt}\n---\nUsuário: ${userInput}\nVivi:`;
      const result = await model.generateContent(fullPrompt);
      const response = await result.response;
      const geminiText = response.text();

      const twiml = new MessagingResponse();
      twiml.message(geminiText);

      console.log(`Resposta da IA: ${geminiText}`);
      return res.type('text/xml').send(twiml.toString());
    }

    // LÓGICA ANTIGA: Se não for uma pergunta, segue o fluxo normal do Dialogflow.
    console.log('Enviando para o Dialogflow...');
    const dialogflowRequest = twilioToDetectIntent(req);
    const [dialogflowResponse] = await dialogflowClient.detectIntent(dialogflowRequest);

    // Usa a SUA função para formatar a resposta
    const twimlResponse = detectIntentToTwilio(dialogflowResponse);

    console.log(`Resposta do Dialogflow: ${twimlResponse.toString()}`);
    res.type('text/xml').send(twimlResponse.toString());

  } catch (error) {
    console.error('ERRO GERAL NO WEBHOOK:', error);
    const errorTwiml = new MessagingResponse();
    errorTwiml.message('Ocorreu um erro inesperado. Por favor, tente novamente.');
    res.status(500).type('text/xml').send(errorTwiml.toString());
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