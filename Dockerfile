# Usa a imagem oficial do Python 3.12 como base.
FROM python:3.12-slim

# Define o diretório de trabalho dentro do contêiner.
WORKDIR /app

# ATUALIZA o sistema e INSTALA a dependência de sistema 'libpq-dev'.
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências do Python e instala usando pip.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código da nossa aplicação (main.py, notion_utils.py).
COPY . .

# --- CORREÇÃO CRUCIAL ABAIXO ---
# Comando para iniciar a aplicação, apontando para a nova função principal 'vivi_webhook'
CMD ["functions-framework", "--target=vivi_webhook", "--port=8080"]