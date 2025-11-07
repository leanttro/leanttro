import os
import psycopg2
import psycopg2.extras
from flask import Flask, jsonify, request, send_from_directory, render_template, abort
from dotenv import load_dotenv
from flask_cors import CORS
import datetime
import decimal
import json
import traceback

# --- [NOVO] IMPORTAÇÕES PARA O FUNIL ---
import requests
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
# --- FIM DA IMPORTAÇÃO ---

# Carrega variáveis de ambiente (para rodar localmente)
load_dotenv()

# --- CONFIGURAÇÃO DAS APIS (Render vai injetar) ---
DATABASE_URL = os.getenv('DATABASE_URL')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PAGESPEED_API_KEY = os.getenv('PAGESPEED_API_KEY') # API Key do Google PageSpeed
# --- FIM DA CONFIGURAÇÃO ---

# --- INICIALIZAÇÃO DO FLASK ---
app = Flask(__name__, template_folder='.', static_folder='.')
CORS(app) 

# --- [NOVO] FUNÇÃO DE SETUP DO BANCO DE DADOS ---
def setup_database():
    """
    Garante que TODAS as 3 tabelas (`leanttro_blog`, `leanttro_leads`, `leanttro_orcar`)
    existam no banco de dados ANTES de o servidor iniciar.
    Este código é 100% SEGURO e não apaga nada.
    """
    if not DATABASE_URL:
        print("❌ ERRO CRÍTICO: DATABASE_URL não encontrada. Setup do banco falhou.")
        return

    # SQL para Tabela 1: leanttro_blog
    CREATE_BLOG_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS leanttro_blog (
        id SERIAL PRIMARY KEY,
        titulo TEXT NOT NULL,
        subtitulo TEXT,
        imagem_url TEXT,
        conteudo_html TEXT NOT NULL,
        autor VARCHAR(100) DEFAULT 'Leandro Andrade',
        data_publicacao DATE DEFAULT CURRENT_DATE,
        slug TEXT UNIQUE NOT NULL,
        publicado BOOLEAN DEFAULT false
    );
    """
    
    # SQL para Tabela 2: leanttro_leads
    CREATE_LEADS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS leanttro_leads (
        id SERIAL PRIMARY KEY,
        data_captura TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        url_analisada TEXT NOT NULL,
        score_seo INTEGER,
        origem VARCHAR(100) DEFAULT 'SEO_DIAGNOSTICO',
        status_analise VARCHAR(50) DEFAULT 'PENDENTE'
    );
    """
    
    # SQL para Tabela 3: leanttro_orcar
    CREATE_ORCAR_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS leanttro_orcar (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER REFERENCES leanttro_leads(id),
        data_orcamento TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        nome_contato VARCHAR(255),
        email_ou_whatsapp VARCHAR(255),
        interesse_servico TEXT,
        detalhes_projeto TEXT,
        orcamento_estimado VARCHAR(100),
        status_orcamento VARCHAR(50) DEFAULT 'PENDENTE'
    );
    """
    
    conn = None
    try:
        print("ℹ️  [DB Setup] Conectando ao banco para verificar tabelas...")
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        print("ℹ️  [DB Setup] Verificando tabela 'leanttro_blog'...")
        cur.execute(CREATE_BLOG_TABLE_SQL)
        
        print("ℹ️  [DB Setup] Verificando tabela 'leanttro_leads'...")
        cur.execute(CREATE_LEADS_TABLE_SQL)
        
        print("ℹ️  [DB Setup] Verificando tabela 'leanttro_orcar'...")
        cur.execute(CREATE_ORCAR_TABLE_SQL)
        
        conn.commit()
        cur.close()
        print("✅  [DB Setup] Todas as tabelas foram verificadas/criadas com sucesso.")
        
    except Exception as e:
        print(f"❌ ERRO CRÍTICO [DB Setup]: Falha ao criar tabelas: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
# --- FIM DO SETUP DO BANCO ---


# --- CONFIGURAÇÃO DO GEMINI ---
chat_model = None
try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # PROMPT DE SISTEMA PARA O "LÊ-IA" (Q&A de Recrutador)
        SYSTEM_PROMPT_LEIA = """
        Você é o "LÊ-IA", o assistente de IA pessoal de Leandro Andrade (apelido "Leanttro").
        Seu propósito é responder perguntas de recrutadores e potenciais clientes de forma profissional, amigável e baseada ESTRITAMENTE nos fatos abaixo.

        REGRAS:
        1.  **NÃO ALUCINE:** Se a informação não estiver abaixo, diga "Essa é uma ótima pergunta, mas não tenho essa informação no meu banco de dados. Você pode perguntar diretamente ao Leandro."
        2.  **PERSONA:** Você é amigável, confiante e técnico.
        3.  **FOCO:** Responda apenas sobre Leandro. Recuse educadamente outros assuntos.
        4.  **DIRECIONAMENTO (IMPORTANTE):**
            - Se perguntarem sobre "orçamento", "preço", "custo" ou "contratar", direcione-os para a seção de diagnóstico de SEO no site.
            - Resposta para orçamento: "O Leandro pode analisar seu projeto! A melhor forma de começar é usando o formulário 'Diagnóstico de SEO' na página principal. Ele receberá sua solicitação e eu (LÊ-IA) iniciarei o processo de orçamento."

        --- BASE DE CONHECIMENTO (CURRÍCULO DO LEANDRO) ---

        **TÍTULO PROFISSIONAL:**
        Engenheiro de Dados & Desenvolvedor Full Stack.

        **PERFIL HÍBRIDO:**
        Leandro tem uma combinação rara: ele é um desenvolvedor técnico (Python, GCP, SQL) com um forte background em Marketing, Design e Comercial. Isso permite que ele entenda a dor do negócio (vendas, marketing) e construa a solução técnica (automação, dados).

        **HABILIDADES TÉCNICAS (HARD SKILLS):**
        * **Engenharia de Dados & Cloud:** Python (Avançado), SQL (Avançado), Google Cloud Platform (GCP), Google BigQuery, Pipelines de ETL/ELT.
        * **Business Intelligence (BI):** Power BI (Avançado), DAX, Análise de Dados (Pandas).
        * **Automação:** N8N (Nível Expert), Docker, API REST, Flask.
        * **Machine Learning:** Scikit-Learn, Sistemas de Recomendação.
        * **Desenvolvimento Web:** HTML, CSS, JavaScript, Flask.

        **PROJETOS PRINCIPAIS:**
        1.  **Feiras de Rua (www.feirasderua.com.br):**
            * **O que é:** Um portal completo (produto digital) para encontrar feiras em São Paulo.
            * **Tecnologias:** É um projeto Full-Stack com Backend em Python (Flask), API REST, banco de dados PostgreSQL (no Render).
            * **Destaque de IA:** O chatbot deste site (o "Feirinha") usa RAG (Retrieval-Augmented Generation), buscando dados AO VIVO do banco de dados para alimentar a API do Gemini e dar respostas precisas.
        2.  **Pipeline de Dados (NYC Taxi):**
            * **O que é:** Um projeto de ML de ponta a ponta para prever tarifas de táxi.
            * **Tecnologias:** Demonstra um pipeline de dados completo na GCP, treinamento de modelo e deploy em Hugging Face.
        3.  **Dashboard de Risco de Crédito (Power BI):**
            * **O que é:** Um dashboard de BI para um banco digital, analisando risco de crédito.
            * **Tecnologias:** Demonstra limpeza de dados (Pandas) e criação de KPIs complexos no Power BI.

        **COMO RESPONDER (EXEMPLOS):**
        * **Usuário:** "O Leandro sabe Python?"
        * **Você:** "Sim! Python é uma das suas habilidades principais (nível avançado). Ele usa Python extensivamente para pipelines de dados, backend com Flask e em projetos de Machine Learning."
        * **Usuário:** "Quanto custa um site?"
        * **Você:** "O Leandro pode analisar seu projeto! A melhor forma de começar é usando o formulário 'Diagnóstico de SEO' na página principal. Ele receberá sua solicitação e eu (LÊ-IA) iniciarei o processo de orçamento."
        --- FIM DA BASE DE CONHECIMENTO ---
        """

        # Modelo para o Q&A LÊ-IA
        chat_model = genai.GenerativeModel(
            'gemini-2.5-flash-preview-09-2025',
            system_instruction=SYSTEM_PROMPT_LEIA
        )
        
        # Modelo para a "ISCA" de SEO (sem prompt de sistema, será enviado em cada chamada)
        diag_model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        
        print("✅  [Gemini] Modelos de Chat (LÊ-IA) e Diagnóstico (ISCA) inicializados.")
    else:
        chat_model = None
        diag_model = None
        print("❌ ERRO: GEMINI_API_KEY não encontrada. Os Chatbots não funcionarão.")
except Exception as e:
    chat_model = None
    diag_model = None
    print(f"❌ Erro ao inicializar os modelos Gemini: {e}")
# --- FIM DA CONFIGURAÇÃO DO GEMINI ---


# --- FUNÇÕES DE BANCO DE DADOS (Inalteradas) ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def format_db_data(data_dict):
    if not isinstance(data_dict, dict):
        return data_dict
    for key, value in data_dict.items():
        if isinstance(value, (datetime.datetime, datetime.date)):
            data_dict[key] = value.isoformat()
        elif isinstance(value, decimal.Decimal):
            data_dict[key] = float(value)
    return data_dict

# --- [NOVO] HELPER FUNCTIONS DO PAGESPEED (Copiadas do app-elo.py) ---
def fetch_full_pagespeed_json(url_to_check, api_key):
    """
    Função helper que chama a API PageSpeed e retorna o JSON completo.
    """
    print(f"ℹ️  [PageSpeed] Iniciando análise para: {url_to_check}")
    categories = "category=SEO&category=PERFORMANCE"
    api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url_to_check}&key={api_key}&{categories}&strategy=MOBILE"
    
    try:
        response = requests.get(api_url, timeout=45) 
        response.raise_for_status() 
        results = response.json()
        print(f"✅  [PageSpeed] Análise de {url_to_check} concluída.")
        return results, None
    except requests.exceptions.HTTPError as http_err:
        print(f"❌ ERRO HTTP [PageSpeed]: {http_err}")
        error_details = "Erro desconhecido"
        try:
            error_details = http_err.response.json().get('error', {}).get('message', 'Verifique a URL')
        except:
            pass
        return None, f"Erro: A API do Google falhou ({error_details})."
    except Exception as e:
        print(f"❌ ERRO Inesperado [PageSpeed]: {e}")
        return None, "Erro: Não foi possível analisar essa URL."

def extract_failing_audits(report_json):
    """
    Extrai uma lista de auditorias que falharam (score != 1).
    """
    audits = report_json.get('lighthouseResult', {}).get('audits', {})
    failed_audits = []
    
    for audit_key, audit_details in audits.items():
        if audit_details.get('scoreDisplayMode') != 'informative' and audit_details.get('score') is not None and audit_details.get('score') < 1:
            failed_audits.append({
                "title": audit_details.get('title'),
                "description": audit_details.get('description'),
                "score": audit_details.get('score')
            })
    print(f"ℹ️  [Parser] Extraídas {len(failed_audits)} auditorias com falha.")
    return failed_audits
# --- FIM DOS HELPERS DO PAGESPEED ---

# --- ENDPOINTS DE API (RETORNAM JSON) ---

@app.route('/api/leanttro_blog', methods=['GET'])
def get_blog_posts():
    """
    API para o carrossel de blog na home page.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, titulo, subtitulo, imagem_url, slug, data_publicacao "
            "FROM leanttro_blog "
            "WHERE publicado = true "
            "ORDER BY data_publicacao DESC "
            "LIMIT 5;"
        )
        posts_raw = cur.fetchall()
        cur.close()
        posts = [format_db_data(dict(post)) for post in posts_raw]
        return jsonify(posts)
    except Exception as e:
        print(f"ERRO no endpoint /api/leanttro_blog: {e}")
        return jsonify({'error': 'Erro interno ao buscar posts.'}), 500
    finally:
        if conn: conn.close()

# --- [MODIFICADO] ENDPOINT DE DIAGNÓSTICO DE SEO (LÓGICA DO 'FLUXO') ---
@app.route('/api/diagnostico_seo', methods=['POST'])
def handle_diagnostico_e_isca():
    """
    API para a barra de "Diagnóstico de SEO".
    1. Recebe a URL.
    2. Chama a API do PageSpeed.
    3. Salva o URL e o Score na tabela `leanttro_leads` e obtém o `new_lead_id`.
    4. Chama o Gemini para criar uma "ISCA" (teaser) de diagnóstico.
    5. Retorna a "ISCA" e o `lead_id` para o frontend.
    """
    print("\n--- [FUNIL-ETAPA-1] Recebido trigger para /api/diagnostico_seo ---")
    
    if not PAGESPEED_API_KEY or not diag_model:
        print("❌ ERRO: PAGESPEED_API_KEY ou diag_model (Gemini) não definidos.")
        return jsonify({"error": "Erro: O servidor não está configurado para o diagnóstico de IA."}), 500

    data = request.json
    url_analisada = data.get('url_analisada')
    if not url_analisada:
        return jsonify({'error': 'URL é obrigatória'}), 400

    conn = None
    try:
        # 1. Chamar PageSpeed
        user_report, user_error = fetch_full_pagespeed_json(url_analisada, PAGESPEED_API_KEY)
        if user_error:
            return jsonify({"error": user_error}), 502
            
        user_seo_score = (user_report.get('lighthouseResult', {}).get('categories', {}).get('seo', {}).get('score', 0)) * 100
        user_seo_score_int = int(user_seo_score)

        # 2. Salvar na Tabela 'leanttro_leads'
        print(f"ℹ️  [DB] Salvando lead frio para: {url_analisada} (Score: {user_seo_score_int})")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO leanttro_leads (url_analisada, score_seo, status_analise) "
            "VALUES (%s, %s, 'DIAGNOSTICADO') "
            "RETURNING id;",
            (url_analisada, user_seo_score_int)
        )
        new_lead_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close() # Fecha a conexão após salvar
        print(f"✅  [DB] Lead frio salvo com ID: {new_lead_id}")

        # 3. Chamar Gemini para criar a "ISCA" (baseado no app-elo.py)
        user_failing_audits = extract_failing_audits(user_report)
        
        # PROMPT DA ISCA (do app-elo.py)
        system_prompt_isca = f"""
        Você é o "Analista de Ouro", um especialista sênior em SEO.
        Sua missão é dar um DIAGNÓSTICO-ISCA para um usuário que enviou a URL do site dele.

        REGRAS:
        1.  **Tom de Voz:** Profissional, especialista, mas com senso de urgência. Use 🚀 e 💡.
        2.  **NÃO DÊ A SOLUÇÃO:** Seu objetivo NÃO é dar o diagnóstico completo, mas sim provar que você o encontrou e que ele é valioso.
        3.  **A ISCA:** Seu trabalho é analisar a lista de 'Auditorias com Falha' e o 'Score' do usuário e gerar um texto curto (2-3 parágrafos) que:
            a. Confirma a nota (ex: "💡 Certo, analisei o {url_analisada} e a nota de SEO mobile é {user_seo_score:.0f}/100.").
            b. Menciona a *quantidade* de falhas (ex: "Identifiquei **{len(user_failing_audits)} falhas técnicas** que estão impedindo seu site de performar melhor...").
            c. Cita 1 ou 2 *exemplos* de falhas (ex: "...incluindo problemas com `meta descriptions` e imagens não otimizadas.").
            d. **O GANCHO (IMPORTANTE):** Termine induzindo o usuário a fornecer os dados para receber a análise completa.
        4.  **FORMULÁRIO DE CAPTURA:** O seu texto DEVE terminar exatamente com o comando para o frontend exibir o formulário. Use a tag especial: [FORMULARIO_LEAD]

        EXEMPLO DE RESPOSTA PERFEITA:
        "💡 Certo, analisei o {url_analisada} e a nota de SEO mobile é **{user_seo_score:.0f}/100**.

        Identifiquei **{len(user_failing_audits)} falhas técnicas** que estão impedindo seu site de alcançar a nota 100/100, incluindo problemas com `meta descriptions` e imagens que não estão otimizadas para mobile.

        Eu preparei um relatório detalhado com o "como corrigir" para cada um desses {len(user_failing_audits)} pontos. Por favor, preencha os campos abaixo para eu enviar a análise completa para você:
        [FORMULARIO_LEAD]"
        
        ---
        ANÁLISE DO SITE DO USUÁRIO ({url_analisada}):
        - Score Geral de SEO: {user_seo_score:.0f}/100
        - Auditorias com Falha: {json.dumps(user_failing_audits, ensure_ascii=False)}
        ---
        
        DIAGNÓSTICO-ISCA (comece aqui):
        """
        
        print("ℹ️  [Gemini-ISCA] Gerando diagnóstico-isca...")
        chat_session = diag_model.start_chat(history=[]) # Usa o 'diag_model'
        response = chat_session.send_message(
            system_prompt_isca,
            generation_config=genai.types.GenerationConfig(temperature=0.3),
            safety_settings={'HATE': 'BLOCK_NONE', 'HARASSMENT': 'BLOCK_NONE', 'SEXUAL' : 'BLOCK_NONE', 'DANGEROUS' : 'BLOCK_NONE'}
        )
        print(f"✅  [Gemini-ISCA] Diagnóstico-isca gerado: {response.text[:50]}...")

        # 4. Retornar o ID do Lead + a Resposta da IA (a isca)
        return jsonify({
            'success': True, 
            'lead_id': new_lead_id,
            'diagnosis': response.text,
            'seo_score': user_seo_score_int
        }), 200

    except Exception as e:
        print(f"❌ ERRO CRÍTICO no endpoint /api/diagnostico_seo: {e}")
        traceback.print_exc()
        if conn: conn.rollback()
        return jsonify({'error': 'Erro interno ao processar o diagnóstico.'}), 500
    finally:
        if conn and not conn.closed: conn.close()
# --- FIM DO ENDPOINT DE DIAGNÓSTICO ---


@app.route('/api/orcar', methods=['POST'])
def handle_orcamento():
    """
    API para o chatbot salvar um pedido de orçamento (lead quente).
    Recebe os dados e salva na tabela 'leanttro_orcar'.
    """
    print("\n--- [FUNIL-ETAPA-2] Recebido trigger para /api/orcar ---")
    data = request.json
    lead_id = data.get('lead_id')
    nome = data.get('nome_contato')
    contato = data.get('email_ou_whatsapp')
    interesse = data.get('interesse_servico')
    detalhes = data.get('detalhes_projeto')
    orcamento = data.get('orcamento_estimado')

    if not lead_id or not nome or not contato or not detalhes:
        return jsonify({'error': 'Dados incompletos para orçamento.'}), 400

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        print(f"ℹ️  [DB] Salvando lead quente (orçamento) para Lead ID: {lead_id}")
        cur.execute(
            "INSERT INTO leanttro_orcar (lead_id, nome_contato, email_ou_whatsapp, interesse_servico, detalhes_projeto, orcamento_estimado, status_orcamento) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'PENDENTE');",
            (lead_id, nome, contato, interesse, detalhes, orcamento)
        )
        conn.commit()
        cur.close()
        print(f"✅  [DB] Lead quente (orçamento) salvo com sucesso.")
        return jsonify({'success': True, 'message': 'Solicitação de orçamento recebida!'}), 201
    except Exception as e:
        print(f"❌ ERRO no endpoint /api/orcar: {e}")
        if conn: conn.rollback()
        return jsonify({'error': 'Erro interno ao salvar orçamento.'}), 500
    finally:
        if conn: conn.close()


@app.route('/api/chat', methods=['POST'])
def handle_chat():
    """
    Endpoint para o chatbot LÊ-IA (Q&A sobre o Leandro).
    """
    print("\n--- [Q&A-CHAT] Recebido trigger para /api/chat ---")
    
    if not chat_model:
        print("❌ ERRO: O chat_model (LÊ-IA) não foi inicializado.")
        return jsonify({'error': 'Serviço de IA não está disponível.'}), 503

    try:
        data = request.json
        history = data.get('conversationHistory', [])
        
        gemini_history = []
        for message in history:
            role = 'user' if message['role'] == 'user' else 'model'
            gemini_history.append({'role': role, 'parts': [{'text': message['text']}]})
            
        chat_session = chat_model.start_chat(history=gemini_history)
        user_message = history[-1]['text'] if history and history[-1]['role'] == 'user' else "Olá"

        print(f"ℹ️  [LÊ-IA] Recebida pergunta: '{user_message}'")
        response = chat_session.send_message(
            user_message,
            generation_config=genai.types.GenerationConfig(temperature=0.7),
            safety_settings={
                 'HATE': 'BLOCK_NONE', 'HARASSMENT': 'BLOCK_NONE',
                 'SEXUAL' : 'BLOCK_NONE', 'DANGEROUS' : 'BLOCK_NONE'
            }
        )
        print(f"✅  [LÊ-IA] Resposta da IA gerada.")
        return jsonify({'reply': response.text})

    except genai.types.generation_types.StopCandidateException as stop_ex:
        print(f"❌ API BLOQUEOU a resposta por segurança: {stop_ex}")
        return jsonify({'reply': "Desculpe, não posso gerar uma resposta para essa solicitação. Mas posso te ajudar com outra pergunta sobre o Leandro!"})
    
    except Exception as e:
        print(f"❌ ERRO no endpoint /api/chat (LÊ-IA): {e}")
        traceback.print_exc()
        return jsonify({'error': 'Ocorreu um erro ao processar sua mensagem.'}), 503

# --- ENDPOINTS DE PÁGINA (RETORNAM HTML) ---

@app.route('/blog/<slug>')
def get_post_detalhe(slug):
    """
    Renderiza a página 'post-detalhe.html'.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM leanttro_blog "
            "WHERE slug = %s AND publicado = true;",
            (slug,)
        )
        post_raw = cur.fetchone()
        cur.close()

        if post_raw:
            post_data = format_db_data(dict(post_raw))
            return render_template('post-detalhe.html', post=post_data)
        else:
            abort(404, description="Post não encontrado")
            
    except Exception as e:
        print(f"ERRO na rota /blog/{slug}: {e}")
        return "Erro ao carregar a página do post", 500
    finally:
        if conn: conn.close()

# --- ROTAS ESTÁTICAS (DEVE VIR POR ÚLTIMO) ---

@app.route('/')
def index_route():
    """Serve o 'index.html' como a página raiz."""
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static_files(path):
    """
    Serve arquivos estáticos (chatbot.css, imagens, etc.) da pasta raiz.
    """
    if '.' not in os.path.basename(path):
        abort(404, description="Caminho inválido")
        
    if os.path.exists(os.path.join('.', path)):
        return send_from_directory('.', path)
    else:
        abort(404, description="Arquivo não encontrado")

# --- EXECUÇÃO DO SERVIDOR ---
if __name__ == '__main__':
    # Roda o setup do banco de dados na inicialização
    setup_database() 
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)