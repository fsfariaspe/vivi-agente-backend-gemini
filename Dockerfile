# Usa a imagem oficial do Python 3.12 como base.
FROM python:3.12-slim

# Define o diretório de trabalho dentro do contêiner.
WORKDIR /app

# ATUALIZA o sistema e INSTALA a dependência de sistema 'libpq-dev'.
# Esta é a etapa que corrige o nosso erro 'libpq.so.5 not found'.
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copia o arquivo de dependências do Python e instala usando pip.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código da nossa aplicação (o main.py).
COPY . .

# Comando para iniciar a aplicação. O Cloud Run vai injetar a variável de ambiente PORT.
# O functions-framework vai escutar nessa porta automaticamente.
CMD ["functions-framework", "--target=identificar_cliente", "--port=8080"]