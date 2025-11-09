import os
import psycopg2
import psycopg2.extras
from psycopg2 import sql # Importação necessária para updates seguros
from flask import Flask, jsonify, request, send_from_directory, render_template, abort
from dotenv import load_dotenv
from flask_cors import CORS
import datetime
import decimal
import json
import traceback

# --- IMPORTAÇÕES PARA O FUNIL ---
import requests
import google.generativeai as genai
# --- FIM DA IMPORTAÇÃO ---

# Carrega variáveis de ambiente (para rodar localmente)
load_dotenv()

# --- CONFIGURAÇÃO DAS APIS (Render vai injetar) ---
DATABASE_URL = os.getenv('DATABASE_URL')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
PAGESPEED_API_KEY = os.getenv('PAGESPEED_API_KEY') # API Key do Google PageSpeed
# --- FIM DA CONFIGURAÇÃO ---

# --- INICIALIZAÇÃO DO FLASK ---
app = Flask(__name__, template_folder='templates', static_folder='.')
CORS(app) 

# --- FUNÇÃO DE SETUP DO BANCO DE DADOS ---
# (Garante que as tabelas existam na inicialização)
def setup_database():
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
    
    # SQL para Tabela 4: leanttro_projetos
    CREATE_PROJETOS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS leanttro_projetos (
        id SERIAL PRIMARY KEY,
        ordem INTEGER DEFAULT 0,
        titulo TEXT NOT NULL,
        short_title TEXT,
        long_description TEXT,
        skills TEXT[],
        github_link TEXT,
        live_link TEXT,
        live_link_text TEXT,
        disclaimer TEXT,
        image_src TEXT,
        case_study_link TEXT,
        publicado BOOLEAN DEFAULT true
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
        
        print("ℹ️  [DB Setup] Verificando tabela 'leanttro_projetos'...")
        cur.execute(CREATE_PROJETOS_TABLE_SQL)
        
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
diag_model = None
try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # --- [PROMPT ATUALIZADO V2] ---
        SYSTEM_PROMPT_LEIA = """
        Você é o "LÊ-IA", o assistente de IA pessoal de Leandro Andrade (apelido "Leanttro").
        Seu propósito é responder perguntas de recrutadores e potenciais clientes de forma profissional, amigável e baseada ESTRITAMENTE nos fatos abaixo.

        REGRAS DE OURO:
        1.  **NÃO ALUCINE:** Se a informação não estiver abaixo, diga "Essa é uma ótima pergunta, mas não tenho essa informação no meu banco de dados. Você pode perguntar diretamente ao Leandro."
        2.  **PERSONA:** Você é amigável, confiante e técnico.
        3.  **FOCO:** Responda apenas sobre Leandro. Recuse educadamente outros assuntos.
        4.  **DIRECIONAMENTO DE VENDAS (IMPORTANTE):**
            - Se perguntarem sobre "orçamento", "preço", "custo" ou "contratar", sua resposta DEVE seguir este script:
            - "O Leandro pode analisar seu projeto! A melhor forma de começar é usando o formulário 'Diagnóstico de SEO' na página principal, caso você já tenha um site. Se não tiver, não tem problema! Podemos começar a coleta de informações para o orçamento por aqui mesmo. [INICIAR_ORCAMENTO_MANUAL]"
            - (A tag [INICIAR_ORCAMENTO_MANUAL] é um comando secreto que o frontend vai entender para iniciar o funil de orçamento.)

        --- BASE DE CONHECIMENTO (CURRÍCULO DO LEANDRO - V2) ---

        **TÍTULO PROFISSIONAL:**
        Analista e Engenheiro de Soluções | Automação | Dados | BI.
        (Ele também atua como Desenvolvedor Full Stack e Engenheiro de Dados).

        **PERFIL HÍBRIDO (O GRANDE DIFERENCIAL):**
        Leandro tem uma combinação rara: ele é um profissional de dados e automação com "mentalidade de arquiteto", focado em construir sistemas end-to-end. Ele possui experiência sólida em pipelines de dados, orquestração (N8N, Docker) e IA (GCP, Gemini).
        Ele une isso a um forte background em Marketing, Design e Análise Comercial (de 2015-2025), o que permite que ele entenda a dor do negócio (vendas, marketing) e construa a solução técnica (automação, dados) que resolve o problema.

        **HABILIDADES TÉCNICAS (HARD SKILLS):**
        * **Automação & Orquestração:** N8N (Nível Expert), Docker, CI/CD, FinOps, Webhooks, APIs REST.
        * **Engenharia de Dados & Cloud:** Python (Avançado, com Pandas, Scikit-learn), SQL (Avançado), Google Cloud Platform (GCP), Google BigQuery, Pipelines de ETL/ELT, Arquitetura de Dados (Silver/Gold).
        * **Business Intelligence (BI):** Power BI (Avançado), DAX, Power Query, Visualização de Dados, Análise Exploratória (EDA).
        * **Desenvolvimento Web:** Flask (Python), HTML, CSS, JavaScript.
        * **Banco de Dados:** PostgreSQL, MySQL, SQLite.

        **EXPERIÊNCIA PROFISSIONAL:**
        * **Engenheiro de Automação e Dados (Freelance) @ Feiras de Rua SP (Jan/2025 - O momento):**
            * Ele arquitetou e implementou o pipeline de automação da plataforma (feirasderua.com.br).
            * Ele usa N8N para orquestrar o deploy contínuo (CI/CD) e monitorar a aplicação no Render, garantindo 100% de uptime com custo zero de infraestrutura (FinOps).
            * No mesmo projeto, ele atua como Desenvolvedor Full Stack, gerenciando o backend em Flask, o banco de dados PostgreSQL, a API REST e o chatbot "Feirinha" (que usa RAG e Gemini).
        * **Engenheiro de Soluções (Autônomo/Portfólio):**
            * Desenvolveu um sistema E2E (End-to-End) de classificação de leads com IA (usando N8N) e um front-end live. A automação envia leads qualificados ao Power BI e nutre os demais.
        * **Experiências Anteriores (2015-2025):**
            * Atuou em empresas como Corum, Arte Rox e Oceano, com foco em marketing digital, design e análise comercial.

        **PROJETOS DE DESTAQUE (Links no GitHub: github.com/leanttro):**
        1.  **Case: Análise de Risco de Crédito (Data Science & BI):** Conduziu um case completo para um banco digital, desde a Análise Exploratória (EDA) e modelagem de Machine Learning (Risco) até a arquitetura de dados na GCP (Silver/Gold) e a entrega de um dashboard final em Power BI.
        2.  **Pipeline de Dados Cloud (NYC Taxi):** Construiu um pipeline de dados na GCP (BigQuery) e desenvolveu um front-end interativo para consumir os dados processados.
        3.  **Pipeline de BI E-commerce (Olist):** Criou um pipeline ponta a ponta (MySQL para GCP), aplicando ETL com Python/Pandas e estruturando um Data Warehouse no BigQuery.
        4.  **Sistema de Recomendação de Produtos (ML):** Desenvolveu um sistema de recomendação (filtragem colaborativa) com Python (Pandas, Scikit-Learn).

        **FORMAÇÃO E CURSOS (Resumo):**
        * **Graduação:** Tecnologia em Inteligência Artificial | Universidade Cruzeiro do Sul (Cursando, 2025-2027).
        * **Graduação Anterior:** Marketing | Universidade Anhembi Morumbi (2014 - 2016).
        * **Especializações (SENAI):** Power BI, Python para Data Science, Bancos de Dados (MySQL), IoT e IA Generativa.
        --- FIM DA BASE DE CONHECIMENTO ---
        """

        # Modelo para o Q&A LÊ-IA
        chat_model = genai.GenerativeModel(
            'gemini-2.5-flash-preview-09-2025',
            system_instruction=SYSTEM_PROMPT_LEIA
        )
        
        # Modelo para a "ISCA" de SEO
        diag_model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        
        print("✅  [Gemini] Modelos de Chat (LÊ-IA V2) e Diagnóstico (ISCA) inicializados.")
    else:
        print("❌ ERRO: GEMINI_API_KEY não encontrada. Os Chatbots não funcionarão.")
except Exception as e:
    chat_model = None
    diag_model = None
    print(f"❌ Erro ao inicializar os modelos Gemini: {e}")
# --- FIM DA CONFIGURAÇÃO DO GEMINI ---


# --- FUNÇÕES DE BANCO DE DADOS ---
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

# --- HELPER FUNCTIONS DO PAGESPEED ---
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
        score_val = audit_details.get('score')
        if audit_details.get('scoreDisplayMode') != 'informative' and score_val is not None and score_val < 1:
            failed_audits.append({
                "title": audit_details.get('title'),
                "description": audit_details.get('description'),
                "score": score_val
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

@app.route('/api/leanttro_projetos', methods=['GET'])
def get_projetos():
    """
    API para o carrossel de projetos (dinâmico).
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute(
            "SELECT "
            "    id, "
            "    titulo AS title, "
            "    short_title AS shortTitle, "
            "    long_description AS longDescription, "
            "    skills, "
            "    github_link AS githubLink, "
            "    live_link AS liveLink, "
            "    live_link_text AS liveLinkText, "
            "    disclaimer, "
            "    image_src AS imagem_url, " # --- ALTERAÇÃO AQUI --- (de imageSrc para imagem_url)
            "    case_study_link AS caseStudyLink "
            "FROM leanttro_projetos "
            "WHERE publicado = true "
            "ORDER BY ordem ASC;"
        )
        projetos_raw = cur.fetchall()
        cur.close()
        
        projetos = [format_db_data(dict(proj)) for proj in projetos_raw]
        return jsonify(projetos)
        
    except Exception as e:
        print(f"ERRO no endpoint /api/leanttro_projetos: {e}")
        return jsonify({'error': 'Erro interno ao buscar projetos.'}), 500
    finally:
        if conn: conn.close()


# --- ENDPOINT DE DIAGNÓSTICO DE SEO ---
@app.route('/api/diagnostico_seo', methods=['POST'])
def handle_diagnostico_e_isca():
    """
    API para a barra de "Diagnóstico de SEO".
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

        # 2. Salvar na Tabela 'leanttro_leads' (Lead Frio)
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
        conn.close()
        print(f"✅  [DB] Lead frio salvo com ID: {new_lead_id}")

        # 3. Chamar Gemini para criar a "ISCA V2"
        user_failing_audits = extract_failing_audits(user_report)
        num_falhas = len(user_failing_audits)
        
        # --- PROMPT DA ISCA V2 ---
        system_prompt_isca_v2 = f"""
        Você é o "Analista de Ouro", um especialista sênior em SEO.
        Sua missão é dar um DIAGNÓSTICO-ISCA para um usuário que enviou a URL do site dele.

        REGRAS:
        1.  **Tom de Voz:** Profissional, especialista, mas com senso de urgência. Use 🚀 e 💡.
        2.  **NÃO DÊ A SOLUÇÃO:** Seu objetivo NÃO é dar o diagnóstico completo, mas sim provar que você o encontrou e que ele é valioso.
        3.  **A ISCA (Nova Lógica):** Seu trabalho é analisar a *quantidade* de falhas e o *Score* do usuário e gerar um texto curto (2-3 parágrafos) que:
            a. Confirma a nota (ex: "💡 Certo, analisei o {url_analisada} e a nota de SEO mobile é {user_seo_score:.0f}/100.").
            b. Menciona a *quantidade* de falhas (ex: "Identifiquei **{num_falhas} falhas técnicas** que estão impedindo seu site de performar melhor...").
            c. **NÃO CITE AS FALHAS!** Não diga "problemas com meta description" ou "imagens". Apenas o número.
            d. **O GANCHO (IMPORTANTE):** Termine induzindo o usuário a fornecer os dados para receber a análise completa.
        4.  **FORMULÁRIO DE CAPTURA:** O seu texto DEVE terminar exatamente com o comando para o frontend exibir o formulário. Use a tag especial: [FORMULARIO_LEAD]

        EXEMPLO DE RESPOSTA PERFEITA (com {num_falhas} falhas):
        "💡 Certo, analisei o {url_analisada} e a nota de SEO mobile é **{user_seo_score:.0f}/100**.

        Identifiquei **{num_falhas} falhas técnicas** que estão impedindo seu site de alcançar a nota 100/100 e de se posicionar melhor no Google.

        Eu preparei um relatório detalhado e gratuito com o "como corrigir" para cada um desses {num_falhas} pontos. 
        [FORMULARIO_LEAD]"
        
        ---
        ANÁLISE DO SITE DO USUÁRIO ({url_analisada}):
        - Score Geral de SEO: {user_seo_score:.0f}/100
        - Número de Auditorias com Falha: {num_falhas}
        ---
        
        DIAGNÓSTICO-ISCA V2 (comece aqui):
        """
        
        print("ℹ️  [Gemini-ISCA V2] Gerando diagnóstico-isca (sem detalhes)...")
        chat_session = diag_model.start_chat(history=[])
        response = chat_session.send_message(
            system_prompt_isca_v2,
            generation_config=genai.types.GenerationConfig(temperature=0.3),
            safety_settings={'HATE': 'BLOCK_NONE', 'HARASSMENT': 'BLOCK_NONE', 'SEXUAL' : 'BLOCK_NONE', 'DANGEROUS' : 'BLOCK_NONE'}
        )
        print(f"✅  [Gemini-ISCA V2] Diagnóstico-isca gerado: {response.text[:50]}...")

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


# --- /api/orcar (CREATE) ---
@app.route('/api/orcar', methods=['POST'])
def handle_orcamento_create():
    """
    API para o chatbot CRIAR um pedido de orçamento (lead quente).
    """
    print("\n--- [FUNIL-ETAPA-2] Recebido trigger para /api/orcar (CREATE) ---")
    data = request.json
    
    lead_id = data.get('lead_id') 
    nome = data.get('nome_contato')
    contato = data.get('email_ou_whatsapp')
    detalhes = data.get('detalhes_projeto')
    orcamento = data.get('orcamento_estimado')
    
    perfil = data.get('perfil_lead', 'Cliente') 
    tem_site = data.get('tem_site', 'Não Informado') 
    interesse = f"Perfil: {perfil} | Tem Site: {tem_site}"

    url_analisada = data.get('url_analisada', 'N/A - Orçamento Manual')
    seo_score = data.get('seo_score') 
    origem_lead = 'CHATBOT_MANUAL' if not lead_id else 'SEO_DIAGNOSTICO'

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if not lead_id:
            print(f"ℹ️  [DB] lead_id NULO. Criando novo 'Lead Frio' (Manual)...")
            cur.execute(
                "INSERT INTO leanttro_leads (url_analisada, score_seo, origem, status_analise) "
                "VALUES (%s, %s, %s, 'PENDENTE') "
                "RETURNING id;",
                (url_analisada, seo_score, origem_lead)
            )
            lead_id = cur.fetchone()[0] 
            conn.commit() 
            print(f"✅  [DB] Novo lead frio (Manual) criado com ID: {lead_id}")
        else:
            print(f"ℹ️  [DB] Usando lead_id existente (SEO): {lead_id}")

        print(f"ℹ️  [DB] Criando lead quente (orçamento) para Lead ID: {lead_id}")
        
        cur.execute(
            "INSERT INTO leanttro_orcar (lead_id, nome_contato, email_ou_whatsapp, interesse_servico, detalhes_projeto, orcamento_estimado, status_orcamento) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'PENDENTE') "
            "RETURNING id;",
            (lead_id, nome, contato, interesse, detalhes, orcamento)
        )
        
        new_orcamento_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        print(f"✅  [DB] Lead quente (orçamento) CRIADO com ID: {new_orcamento_id}.")
        
        return jsonify({
            'success': True, 
            'message': 'Solicitação de orçamento iniciada!',
            'orcamento_id': new_orcamento_id
        }), 201
        
    except Exception as e:
        print(f"❌ ERRO no endpoint /api/orcar (CREATE): {e}")
        traceback.print_exc()
        if conn: conn.rollback()
        return jsonify({'error': 'Erro interno ao salvar orçamento.'}), 500
    finally:
        if conn: conn.close()


# --- API PARA ATUALIZAR ORÇAMENTO ---
ALLOWED_ORCAR_COLUMNS = [
    'nome_contato',
    'email_ou_whatsapp',
    'detalhes_projeto',
    'orcamento_estimado',
    'interesse_servico'
]

@app.route('/api/orcar/update', methods=['POST'])
def handle_orcamento_update():
    """
    API para o chatbot ATUALIZAR um pedido de orçamento passo-a-passo.
    """
    print("\n--- [FUNIL-ETAPA-3] Recebido trigger para /api/orcar/update ---")
    data = request.json
    
    orcamento_id = data.get('orcamento_id')
    campo = data.get('campo')
    valor = data.get('valor')

    if not orcamento_id or not campo or valor is None:
        return jsonify({'error': 'Dados incompletos'}), 400

    if campo not in ALLOWED_ORCAR_COLUMNS:
        print(f"❌ ERRO: Tentativa de update em campo NÃO PERMITIDO: {campo}")
        return jsonify({'error': 'Operação não permitida.'}), 403

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        update_query = sql.SQL("UPDATE leanttro_orcar SET {col} = %s WHERE id = %s").format(
            col=sql.Identifier(campo)
        )

        print(f"ℹ️  [DB] Executando UPDATE: SET {campo} = (valor) no orcamento_id {orcamento_id}")
        cur.execute(update_query, (valor, orcamento_id))
        
        conn.commit()
        cur.close()
        
        print(f"✅  [DB] Campo {campo} atualizado.")
        return jsonify({'success': True, 'message': f'Campo {campo} atualizado.'}), 200

    except Exception as e:
        print(f"❌ ERRO no endpoint /api/orcar/update: {e}")
        traceback.print_exc()
        if conn: conn.rollback()
        return jsonify({'error': 'Erro interno ao atualizar orçamento.'}), 500
    finally:
        if conn: conn.close()


# --- ENDPOINT DO CHATBOT LÊ-IA ---
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

        print(f"ℹ️  [LÊ-IA V2] Recebida pergunta: '{user_message}'")
        response = chat_session.send_message(
            user_message,
            generation_config=genai.types.GenerationConfig(temperature=0.7),
            safety_settings={
                 'HATE': 'BLOCK_NONE', 'HARASSMENT': 'BLOCK_NONE',
                 'SEXUAL' : 'BLOCK_NONE', 'DANGEROUS' : 'BLOCK_NONE'
            }
        )
        print(f"✅  [LÊ-IA V2] Resposta da IA gerada.")
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

# --- [NOVO] ROTA PARA DETALHES DO PROJETO ---
@app.route('/projeto/<int:projeto_id>')
def get_projeto_detalhe(projeto_id):
    """
    Renderiza a página 'projeto-detalhe.html' com dados do banco.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Busca o projeto pelo ID, garantindo que esteja publicado
        cur.execute(
            "SELECT * FROM leanttro_projetos WHERE id = %s AND publicado = true;",
            (projeto_id,)
        )
        projeto_raw = cur.fetchone()
        cur.close()

        if projeto_raw:
            projeto_data = format_db_data(dict(projeto_raw))
            return render_template('projeto-detalhe.html', projeto=projeto_data)
        else:
            abort(404, description="Projeto não encontrado ou não publicado")
            
    except Exception as e:
        print(f"ERRO na rota /projeto/{projeto_id}: {e}")
        return "Erro ao carregar a página do projeto", 500
    finally:
        if conn: conn.close()
# --- FIM DA NOVA ROTA ---

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
        
    if '..' in path:
        abort(400, description="Caminho malicioso detectado")
        
    if os.path.exists(os.path.join('.', path)):
        return send_from_directory('.', path)
    else:
        abort(404, description="Arquivo não encontrado")

# -- EXECUÇÃO DO SERVIDOR 
if __name__ == '__main__':
    setup_database() 
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)