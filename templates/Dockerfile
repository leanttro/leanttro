# 1. Use uma imagem oficial do Python
FROM python:3.10-slim

# 2. Defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# 3. Copie o arquivo de dependências PRIMEIRO
COPY requirements.txt .

# 4. Instale as dependências
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copie TODO o resto do seu projeto para o contêiner
COPY . .

# 6. Defina o comando para iniciar seu servidor
# O Cloud Run envia tráfego para a porta 8080.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]