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
    return psycopg2.connect(DATABASE_URL)

@app.route('/submit', methods=['POST'])
def submit():
    try:
        # Recebe os dados do formulário do index.html
        nome = request.form.get("name")
        email = request.form.get("email")
        local = request.form.get("source") # O campo 'source' do HTML corresponde à coluna 'local' no banco

        # Validação básica
        if not nome or not email:
            return jsonify({"success": False, "message": "Nome e E-mail são obrigatórios."}), 400
        
        # Salva na tabela 'portfolio'
        with get_db_connection() as conn:
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
        # --- Alteração: Removemos o retorno de erro para o frontend. ---
        # A transação precisa de um rollback para o próximo uso.
        conn.rollback()
        print(f"AVISO (IntegrityError): Tentativa de inserir e-mail duplicado ({email}). O registro foi ignorado, mas o status de sucesso é retornado para o frontend. Erro detalhado: {e}")
        
        # O frontend ainda receberá sucesso para não travar seus testes
        return jsonify({"success": True, "message": "Obrigado! Seu guia será enviado em breve. Agradeço sua visita!"})
        
    except Exception as e:
        # Trata outros erros
        print(f"ERRO INTERNO: {e}")
        # Certifica-se de fazer o rollback para outros erros também
        if 'conn' in locals() and conn:
            conn.rollback()
            
        return jsonify({"success": False, "message": "Ocorreu um erro interno no servidor ao salvar os dados."}), 500

@app.route('/', methods=['GET'])
def home():
    # Renderiza o index.html que está na pasta 'templates'
    return render_template('index.html')

if __name__ == '__main__':
    # O Render gerencia a porta
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
