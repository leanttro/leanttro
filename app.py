# app.py (AJUSTADO PARA SALVAR NA TABELA 'PORTFOLIO')

import os
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, render_template
from dotenv import load_dotenv
import requests

# Carrega variáveis do .env
load_dotenv()

# Indica ao Flask onde estão suas pastas (templates e static)
app = Flask(__name__, template_folder='templates', static_folder='static')

# Configurações do banco de dados
DATABASE_URL = os.getenv("DATABASE_URL")
# Removendo WEBHOOK_URL para focar na funcionalidade de contato do portfólio, 
# mas você pode reintroduzi-la se necessário.

def get_db_connection():
    # Verifica se a URL de conexão está disponível
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL não configurada nas variáveis de ambiente.")
    # Adiciona a lógica de conexão com o Render
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
        # Eleva a exceção para ser capturada no bloco try/except da rota submit
        raise

@app.route('/submit', methods=['POST'])
def submit():
    conn = None # Inicializa conn fora do try para garantir que esteja acessível no except
    try:
        # Recebe os dados do formulário do index.html
        nome = request.form.get("name")
        email = request.form.get("email")
        local = request.form.get("source") # O campo 'source' do HTML corresponde à coluna 'local' no banco

        # Validação básica
        if not nome or not email:
            return jsonify({"success": False, "message": "Nome e E-mail são obrigatórios."}), 400
        
        # Salva na tabela 'portfolio'
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # O comando SQL foi alterado para inserir em 'portfolio' com as colunas corretas
            cur.execute("""
                INSERT INTO portfolio (nome, email, local)
                VALUES (%s, %s, %s)
            """, (nome, email, local))
            conn.commit()

        # Resposta de sucesso para o frontend
        return jsonify({"success": True, "message": "Obrigado! Seu guia será enviado em breve. Agradeço sua visita!"})

    except psycopg2.IntegrityError as e:
        # --- Tratamento de e-mail duplicado/IntegrityError (Não exibe erro ao usuário) ---
        if conn:
             conn.rollback() # A transação precisa de um rollback.
        print(f"AVISO (IntegrityError): Tentativa de inserir e-mail duplicado ({email}). O registro foi ignorado, mas o status de sucesso é retornado para o frontend. Erro detalhado: {e}")
        
        # O frontend ainda receberá sucesso para não travar seus testes
        return jsonify({"success": True, "message": "Obrigado! Seu guia será enviado em breve. Agradeço sua visita!"})
        
    except Exception as e:
        # Trata outros erros, incluindo falha de conexão (ValueError/psycopg2.Error do get_db_connection)
        print(f"ERRO INTERNO: {e}")
        
        if conn:
            conn.rollback()
            conn.close() # Garante o fechamento da conexão em caso de erro

        return jsonify({"success": False, "message": "Ocorreu um erro interno no servidor ao salvar os dados."}), 500
    
    finally:
        if conn:
            # Certifica-se de fechar a conexão no final
            conn.close()


@app.route('/', methods=['GET'])
def home():
    # Renderiza o index.html que está na pasta 'templates'
    return render_template('index.html')

if __name__ == '__main__':
    # O Render gerencia a porta
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
