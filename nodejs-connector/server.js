const express = require('express');
const { SessionsClient } = require('@google-cloud/dialogflow-cx');
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

// --- Clientes das APIs (Corrigido) ---
const dialogflowClient = new SessionsClient({ apiEndpoint: `${process.env.LOCATION}-dialogflow.googleapis.com` });

// Inicialização do cliente VertexAI (autenticação via ambiente)
const vertex_ai = new VertexAI({ project: process.env.PROJECT_ID, location: 'southamerica-east1' });
const model = 'gemini-1.5-flash';

const generativeModel = vertex_ai.getGenerativeModel({
  model: model,
});

// --- Armazenamento do Histórico da Conversa (Simples, em memória) ---
const conversationHistory = {};


const mainPrompt = `
Você é a Vivi, uma assistente de viagens virtual da agência 'Viaje Fácil Brasil'. Sua personalidade é amigável, proativa e extremamente prestativa.
Seu objetivo é conversar com o usuário para entender suas necessidades de viagem. Você pode dar sugestões, falar sobre pacotes promocionais e responder a perguntas gerais.

Quando você identificar que o usuário está pronto para fazer uma cotação e você precisa coletar informações estruturadas (como origem, destino, datas, etc.), sua tarefa é avisá-lo que você vai iniciar a coleta de dados e, em seguida, retornar um comando especial para o sistema.

**Regras de Resposta:**
1.  **Conversa Natural:** Converse normalmente com o usuário. Se ele perguntar sobre pacotes, dê sugestões criativas. Se ele fizer uma pergunta geral, responda-a.
2.  **Identificar a Hora de Coletar Dados:** Quando a conversa chegar a um ponto onde você precisa de detalhes para uma cotação, você DEVE parar de conversar e retornar um JSON especial.
3.  **Formato do JSON de Ação:** O JSON deve ter a seguinte estrutura:
    {
      "action": "NOME_DA_ACAO",
      "response": "Frase que você quer que o sistema diga ao usuário antes de iniciar a coleta."
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

// Rota principal (corrigida)
app.post('/', async (req, res) => {
  const userInput = req.body.Body;
  const sessionId = req.body.From.replace('whatsapp:', '');
  console.log(`[${sessionId}] Mensagem recebida: "${userInput}"`);

  try {
    // Lógica para detectar se deve iniciar um fluxo (pode ser ajustada)
    const isStartingFlow = userInput.toLowerCase().includes('passagem') || userInput.toLowerCase().includes('cruzeiro');

    if (isStartingFlow) {
      // ... (sua lógica para chamar triggerDialogflowEvent e iniciar um fluxo) ...
    } else {
      // Conversa generativa padrão
      console.log('Continuando conversa com o Gemini via Vertex AI.');
      const fullPrompt = `${mainPrompt}\n---\nUsuário: ${userInput}\nVivi:`;

      const result = await generativeModel.generateContent(fullPrompt);
      const response = await result.response;
      const geminiText = response.candidates[0].content.parts[0].text;

      console.log(`Texto da IA: ${geminiText}`);

      const twiml = new MessagingResponse();
      twiml.message(geminiText);
      return res.type('text/xml').send(twiml.toString());
    }
  } catch (error) {
    console.error('--- ERRO CAPTURADO NO WEBHOOK ---');
    console.error('MENSAGEM:', error.message);
    if (error.response) {
      console.error('RESPOSTA DO ERRO:', JSON.stringify(error.response, null, 2));
    }
    console.error('STACK TRACE:', error.stack);

    const errorTwiml = new MessagingResponse();
    errorTwiml.message('Desculpe, estou com um problema para me conectar à minha inteligência. Por favor, tente novamente em um instante.');
    res.status(500).type('text/xml').send(errorTwiml.toString());
  }
});

const listener = app.listen(process.env.PORT || 8080, () => {
  console.log(`Seu servidor está a ouvir na porta ${listener.address().port}`);
});