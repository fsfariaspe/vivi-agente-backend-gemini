# vivi-agente-backend-gemini
Repositório destinado a manter a vivi dentro da estrutura do Google-Gemini

# Vivi - Agente de Viagens com IA

**Vivi** é um agente de conversação inteligente, construído com Google Dialogflow CX e um backend em Python/Flask, projetado para automatizar a cotação de produtos de viagem, capturar leads e notificar a equipe de vendas em tempo real.

**Versão Atual:** v1.2-stable

## Resumo do Projeto

O objetivo principal deste projeto é desenvolver um agente de IA (Vivi) capaz de interagir com clientes para coletar informações detalhadas sobre suas necessidades de viagem. O sistema guia o usuário através de um fluxo de perguntas, confirma os dados coletados e, após a confirmação, salva o lead em uma base de dados no Notion e envia um alerta via WhatsApp para a equipe de vendas.

Atualmente, o agente está treinado para lidar com dois produtos: **Passagens Aéreas** e **Cruzeiros**.

## Funcionalidades Implementadas

- **Fluxos de Produtos Independentes:** Arquitetura robusta com fluxos de coleta de dados separados e autocontidos para cada produto (Passagens Aéreas e Cruzeiros).
- **Onboarding de Cliente:** Coleta e confirmação do nome do cliente no início da interação.
- **Roteador de Produtos:** Uma página de seleção direciona o cliente para o fluxo de cotação desejado.
- **Fluxo de Correção Dinâmico:** O usuário pode, a qualquer momento na fase de resumo, solicitar a correção de qualquer dado informado (origem, destino, datas, etc.), e o agente o guiará de volta para a etapa correta, retornando ao resumo em seguida.
- **Integração com Notion:** Após a confirmação do usuário, todos os dados da cotação são salvos automaticamente em uma base de dados do Notion.
- **Notificações em Tempo Real:** Simultaneamente ao salvamento no Notion, um alerta personalizado é enviado via WhatsApp (usando a API da Twilio) para o número de um vendedor/administrador.
- **Timestamping de Leads:** O sistema captura e salva a data e hora exatas (com fuso horário local de Recife) em que o cliente confirmou a solicitação, permitindo um melhor controle e análise dos leads.

## Arquitetura do Sistema

A arquitetura foi projetada para ser simples e robusta, priorizando a clareza e a facilidade de manutenção.

### 1. Dialogflow CX (Frontend Conversacional)

A estrutura no Dialogflow é dividida em fluxos independentes:

- **Default Start Flow:** Responsável unicamente pelo onboarding, coletando o nome do cliente.
- **Flow - Selecao de Produto:** Atua como um roteador central, perguntando ao cliente qual produto ele deseja cotar.
- **Flow - Passagens Aereas:** Um fluxo completo e autocontido para a coleta de todos os dados de uma cotação de voo.
- **Flow - Cotação de Cruzeiros:** Um fluxo completo e autocontido para a coleta de todos os dados de uma cotação de cruzeiro.

### 2. Python/Flask (Backend)

O backend é uma aplicação Flask rodando no Google Cloud Run.

- **Execução Síncrona:** Após uma fase de depuração, optamos por uma arquitetura síncrona para maior simplicidade e facilidade de diagnóstico. A chamada do Dialogflow aciona a execução completa da lógica de negócio.
- **Endpoint Principal (`/`):** Recebe a chamada final do Dialogflow (após o "sim" do cliente), identifica a `tag` para determinar o tipo de produto e chama a lógica de negócio principal.
- **Módulos Utilitários:**
    - `notion_utils.py`: Contém toda a lógica para interagir com a API do Notion.
    - `twilio`: A biblioteca oficial é usada para a integração com a API do WhatsApp.

## Tech Stack

- **Plataforma Conversacional:** Google Dialogflow CX
- **Backend:** Python 3, Flask
- **Hospedagem:** Google Cloud Run
- **Base de Leads:** Notion
- **Notificações:** Twilio WhatsApp API
- **Banco de Dados (Opcional):** PostgreSQL (módulo `db.py` preparado para futuras implementações)
- **CI/CD:** Google Cloud Build

## Configuração e Variáveis de Ambiente

Para executar o projeto, as seguintes variáveis de ambiente devem ser configuradas no ambiente do Cloud Run:

```
# Notion
NOTION_API_KEY=
NOTION_DATABASE_ID=

# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=   # Ex: whatsapp:+14155238886
MEU_WHATSAPP_TO=        # Ex: whatsapp:+5581999998888
TEMPLATE_SID=           # SID do template para Passagens Aéreas
TEMPLATE_CRUZEIRO_SID=  # SID do template para Cruzeiros

# Google Cloud (se usar a arquitetura assíncrona novamente)
GCP_PROJECT_ID=
GCP_LOCATION_ID=
GCP_SERVICE_ACCOUNT_EMAIL=
CLOUD_TASKS_QUEUE_ID=
WORKER_URL=
```

## Próximos Passos

- Promover as alterações da branch de desenvolvimento para a branch `main`.
- Fazer o deploy da versão final na `main` para o serviço de produção (`vivi-agente-backend-gemini`).
- Atualizar a URL do webhook no Dialogflow para apontar para o serviço de produção.
- Desenvolver novos fluxos para outros produtos (ex: Hotéis, Aluguel de Carro).
