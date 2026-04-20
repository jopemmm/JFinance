"""
J-Finance - Aplicação Flask principal.
Notícias premium de matemática + plataforma de aulas com acesso restrito.
"""

import os
import re
import unicodedata
from datetime import datetime, timedelta
from functools import wraps

import bleach
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

# Carrega variáveis de ambiente do arquivo .env PRIMEIRO
load_dotenv()

# Importa a inicialização do Firebase
from firebase_config.firebase_init import auth_client, db

# Importa traduções
from translations import get_translation, TRANSLATIONS
from firebase_admin import auth as firebase_auth
from google.cloud import firestore

# Detecta modo de desenvolvimento
is_debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"

# Inicializa a aplicação Flask
app = Flask(__name__)

# Configuração de segurança da sessão
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = not is_debug  # False em dev local (HTTP)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)

# Inicializa o Flask-Limiter para rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
)

# Inicializa o Flask-Talisman para headers de segurança
Talisman(
    app,
    force_https=not is_debug,  # False em dev local (HTTP)
    content_security_policy={
        "default-src": "'self'",
        "script-src": [
            "'self'",
            "'unsafe-inline'",
            "https://cdn.quilljs.com",
            "https://cdn.jsdelivr.net",
            "https://www.gstatic.com",
            "https://fonts.googleapis.com",
        ],
        "style-src": [
            "'self'",
            "'unsafe-inline'",
            "https://cdn.quilljs.com",
            "https://cdn.jsdelivr.net",
            "https://fonts.googleapis.com",
        ],
        "font-src": [
            "'self'",
            "https://fonts.gstatic.com",
        ],
        "img-src": ["'self'", "data:", "https:"],
        "connect-src": [
            "'self'",
            "https://*.googleapis.com",
            "https://*.firebaseio.com",
            "https://*.firebaseapp.com",
            "https://*.gstatic.com",
        ],
        "frame-src": ["https://www.youtube.com", "https://youtube.com"],
    },
)

# Email do administrador (do .env)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")


# ============================================================================
# DECORADORES PERSONALIZADOS
# ============================================================================

def login_obrigatorio(f):
    """
    Decorador que exige que o usuário esteja logado.
    Se não estiver, redireciona para a página de login.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            # Salva a URL atual para redirecionar após o login
            next_url = request.path
            return redirect(url_for("login", next=next_url))
        return f(*args, **kwargs)
    return decorated_function


def apenas_admin(f):
    """
    Decorador que restringe o acesso apenas ao administrador.
    Verifica se o email do usuário logado é igual ao ADMIN_EMAIL.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_email = session.get("email")
        if user_email != ADMIN_EMAIL:
            return render_template("errors/403.html"), 403
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def sanitize_html(content):
    """
    Sanitiza o conteúdo HTML usando bleach.
    Permite apenas tags e atributos seguros.
    """
    tags_permitidas = [
        "p", "br", "strong", "b", "em", "i", "u", "h1", "h2", "h3",
        "h4", "h5", "h6", "blockquote", "ul", "ol", "li", "a", "img",
        "code", "pre", "span", "div"
    ]
    atributos_permitidos = {
        "a": ["href", "title"],
        "img": ["src", "alt", "title"],
        "*": ["class"]
    }
    return bleach.clean(
        content,
        tags=tags_permitidas,
        attributes=atributos_permitidos,
        strip=True
    )


def validar_slug(slug):
    """
    Valida se o slug contém apenas caracteres permitidos:
    letras minúsculas, números e hífens.
    """
    padrao = re.compile(r"^[a-z0-9-]+$")
    return bool(padrao.match(slug))


def gerar_slug(titulo):
    """
    Gera um slug a partir do título do post.
    """
    slug = titulo.lower()
    # Remove acentos
    slug = unicodedata.normalize("NFD", slug).encode("ascii", "ignore").decode("utf-8")
    # Remove caracteres especiais
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    # Substitui espaços por hífens
    slug = slug.strip().replace(" ", "-")
    # Remove hífens múltiplos
    slug = re.sub(r"-+", "-", slug)
    return slug


def formatar_data_brasil(data):
    """
    Formata uma data no padrão brasileiro (DD/MM/AAAA).
    """
    if isinstance(data, datetime):
        return data.strftime("%d/%m/%Y")
    elif isinstance(data, dict) and "_seconds" in data:
        # Converte timestamp do Firestore
        dt = datetime.fromtimestamp(data["_seconds"])
        return dt.strftime("%d/%m/%Y")
    return ""


# ============================================================================
# FILTROS JINJA E CONTEXT PROCESSORS
# ============================================================================

@app.template_filter("timestamp_to_date")
def timestamp_to_date(value):
    """
    Converte um timestamp Unix (segundos) para data formatada em pt-BR.
    Uso nos templates: {{ valor | timestamp_to_date }}
    """
    try:
        if isinstance(value, (int, float)) and value > 0:
            dt = datetime.fromtimestamp(value)
            return dt.strftime("%d/%m/%Y")
        return ""
    except (ValueError, TypeError, OSError):
        return ""


def get_current_lang():
    """
    Retorna o idioma atual da sessão ou 'pt' como padrão.
    """
    return session.get('lang', 'pt')


@app.context_processor
def inject_globals():
    """
    Injeta variáveis globais no contexto de todos os templates.
    """
    lang = 'pt'
    return {
        "config": {
            "ADMIN_EMAIL": ADMIN_EMAIL,
        },
        "lang": lang,
        "t": lambda key: get_translation(key, lang),
    }


@app.route("/lang/<lang_code>")
def set_language(lang_code):
    """
    Altera o idioma da aplicação.
    Atualmente o site está disponível apenas em português.
    """
    session['lang'] = 'pt'
    # Redireciona para a página anterior ou para a home
    next_page = request.args.get('next') or request.referrer or url_for('index')
    return redirect(next_page)


# ============================================================================
# ROTAS PÚBLICAS
# ============================================================================

@app.route("/")
def index():
    """
    Página inicial.
    Exibe os 6 posts mais recentes e os 3 cursos mais recentes.
    """
    # Busca os últimos 6 posts publicados
    posts_ref = (
        db.collection("posts")
        .where("published", "==", True)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(6)
        .stream()
    )
    posts = [{"id": p.id, **p.to_dict()} for p in posts_ref]

    # Busca os últimos 3 cursos publicados
    cursos_ref = (
        db.collection("courses")
        .where("published", "==", True)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(3)
        .stream()
    )
    cursos = [{"id": c.id, **c.to_dict()} for c in cursos_ref]

    return render_template("index.html", posts=posts, courses=cursos)


@app.route("/blog")
def blog_list():
    """
    Lista todos os posts do blog com paginação e busca.
    """
    # Parâmetros de paginação
    pagina = request.args.get("page", 1, type=int)
    busca = request.args.get("q", "").strip().lower()
    tag_filtro = request.args.get("tag", "").strip()

    # Busca todos os posts publicados
    posts_ref = (
        db.collection("posts")
        .where("published", "==", True)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    posts = [{"id": p.id, **p.to_dict()} for p in posts_ref]

    # Filtra por busca de texto (título)
    if busca:
        posts = [p for p in posts if busca in p.get("title", "").lower()]

    # Filtra por tag
    if tag_filtro:
        posts = [
            p for p in posts
            if tag_filtro in p.get("tags", [])
        ]

    # Paginação (10 posts por página)
    posts_por_pagina = 10
    total_posts = len(posts)
    total_paginas = (total_posts + posts_por_pagina - 1) // posts_por_pagina

    inicio = (pagina - 1) * posts_por_pagina
    fim = inicio + posts_por_pagina
    posts_paginados = posts[inicio:fim]

    return render_template(
        "blog/list.html",
        posts=posts_paginados,
        pagina=pagina,
        total_paginas=total_paginas,
        busca=busca,
        tag_filtro=tag_filtro,
        total_posts=total_posts
    )


@app.route("/post/<slug>")
def blog_post(slug):
    """
    Exibe um post individual do blog.
    Incrementa o contador de visualizações.
    """
    # Busca o post pelo slug
    posts_ref = db.collection("posts").where("slug", "==", slug).limit(1).stream()
    post = None
    for p in posts_ref:
        post = {"id": p.id, **p.to_dict()}
        break

    if not post:
        return render_template("errors/404.html"), 404

    # Incrementa o contador de visualizações
    db.collection("posts").document(post["id"]).update(
        {"views": firestore.Increment(1)}
    )

    # Busca posts relacionados (mesma tag ou mais recentes)
    tags = post.get("tags", [])
    if tags:
        relacionados_ref = (
            db.collection("posts")
            .where("published", "==", True)
            .where("tags", "array_contains", tags[0])
            .limit(4)
            .stream()
        )
    else:
        relacionados_ref = (
            db.collection("posts")
            .where("published", "==", True)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(4)
            .stream()
        )

    relacionados = [{"id": r.id, **r.to_dict()} for r in relacionados_ref]
    # Remove o post atual da lista de relacionados
    relacionados = [r for r in relacionados if r["id"] != post["id"]][:3]

    return render_template("blog/post.html", post=post, relacionados=relacionados)


@app.route("/cursos")
def courses_list():
    """
    Lista todos os cursos disponíveis.
    O conteúdo só é acessível após login.
    """
    cursos_ref = (
        db.collection("courses")
        .where("published", "==", True)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    cursos = [{"id": c.id, **c.to_dict()} for c in cursos_ref]

    return render_template("courses/list.html", courses=cursos)


@app.route("/curso/<course_id>")
@login_obrigatorio
def course_detail(course_id):
    """
    Página de detalhes de um curso.
    Requer login.
    """
    # Busca o curso
    curso_doc = db.collection("courses").document(course_id).get()
    if not curso_doc.exists:
        return render_template("errors/404.html"), 404

    curso = {"id": curso_doc.id, **curso_doc.to_dict()}

    # Busca os módulos do curso
    modulos_ref = (
        db.collection("courses")
        .document(course_id)
        .collection("modules")
        .order_by("order")
        .stream()
    )
    modulos = []
    for m in modulos_ref:
        modulo = {"id": m.id, **m.to_dict()}
        # Busca as aulas de cada módulo
        aulas_ref = (
            db.collection("courses")
            .document(course_id)
            .collection("modules")
            .document(m.id)
            .collection("lessons")
            .order_by("order")
            .stream()
        )
        modulo["lessons"] = [{"id": a.id, **a.to_dict()} for a in aulas_ref]
        modulos.append(modulo)

    curso["modules"] = modulos

    # Busca o progresso do usuário
    user_id = session.get("user_id")
    user_doc = db.collection("users").document(user_id).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}

    # Calcula o progresso
    inscricoes = user_data.get("enrolled_courses", {})
    inscricao = inscricoes.get(course_id, {})
    progresso = inscricao.get("progress", 0)

    return render_template(
        "courses/detail.html",
        course=curso,
        progress=progresso,
        enrollment=inscricao
    )


@app.route("/aula/<course_id>/<module_id>/<lesson_id>")
@login_obrigatorio
def lesson_detail(course_id, module_id, lesson_id):
    """
    Página de uma aula específica.
    Requer login.
    """
    # Busca a aula
    aula_doc = (
        db.collection("courses")
        .document(course_id)
        .collection("modules")
        .document(module_id)
        .collection("lessons")
        .document(lesson_id)
        .get()
    )

    if not aula_doc.exists:
        return render_template("errors/404.html"), 404

    aula = {"id": aula_doc.id, **aula_doc.to_dict()}

    # Busca todas as aulas do curso para navegação
    todas_aulas = []
    modulos_ref = (
        db.collection("courses")
        .document(course_id)
        .collection("modules")
        .order_by("order")
        .stream()
    )

    for m in modulos_ref:
        aulas_ref = (
            db.collection("courses")
            .document(course_id)
            .collection("modules")
            .document(m.id)
            .collection("lessons")
            .order_by("order")
            .stream()
        )
        for a in aulas_ref:
            todas_aulas.append({
                "id": a.id,
                "module_id": m.id,
                **a.to_dict()
            })

    # Encontra a aula anterior e próxima
    aula_anterior = None
    proxima_aula = None

    for i, a in enumerate(todas_aulas):
        if a["id"] == lesson_id:
            if i > 0:
                aula_anterior = todas_aulas[i - 1]
            if i < len(todas_aulas) - 1:
                proxima_aula = todas_aulas[i + 1]
            break

    # Busca o curso para o título
    curso_doc = db.collection("courses").document(course_id).get()
    curso = {"id": curso_doc.id, **curso_doc.to_dict()} if curso_doc.exists else {}

    # Busca todos os módulos para a sidebar
    modulos_ref = (
        db.collection("courses")
        .document(course_id)
        .collection("modules")
        .order_by("order")
        .stream()
    )
    modulos = []
    for m in modulos_ref:
        modulo = {"id": m.id, **m.to_dict()}
        aulas_ref = (
            db.collection("courses")
            .document(course_id)
            .collection("modules")
            .document(m.id)
            .collection("lessons")
            .order_by("order")
            .stream()
        )
        modulo["lessons"] = [{"id": a.id, **a.to_dict()} for a in aulas_ref]
        modulos.append(modulo)

    # Atualiza o progresso do usuário
    user_id = session.get("user_id")
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if user_doc.exists:
        user_data = user_doc.to_dict()
        inscricoes = user_data.get("enrolled_courses", {})
        if course_id not in inscricoes:
            inscricoes[course_id] = {
                "enrolled_at": firestore.SERVER_TIMESTAMP,
                "completed_lessons": [],
                "progress": 0
            }

        # Marca a aula como concluída
        if lesson_id not in inscricoes[course_id].get("completed_lessons", []):
            inscricoes[course_id]["completed_lessons"].append(lesson_id)

        # Calcula o novo progresso
        total_aulas = len(todas_aulas)
        aulas_concluidas = len(inscricoes[course_id]["completed_lessons"])
        progresso = int((aulas_concluidas / total_aulas) * 100) if total_aulas > 0 else 0
        inscricoes[course_id]["progress"] = progresso

        user_ref.update({"enrolled_courses": inscricoes})

    return render_template(
        "courses/lesson.html",
        lesson=aula,
        course=curso,
        modules=modulos,
        current_module_id=module_id,
        current_lesson_id=lesson_id,
        previous_lesson=aula_anterior,
        next_lesson=proxima_aula
    )


# ============================================================================
# FERRAMENTAS (TOOLS) - Dados e Rotas
# ============================================================================

TOOLS = [
    {
        "slug": "distribuicao-normal",
        "title": "Distribuição Normal",
        "description": "Visualize a curva gaussiana, calcule probabilidades a partir de Z-scores e explore PDF/CDF interativamente.",
        "category": "distributions",
        "icon": "bell",
    },
    {
        "slug": "monte-carlo",
        "title": "Simulação Monte Carlo",
        "description": "Simule trajetórias de preços de ativos usando Movimento Browniano Geométrico (GBM).",
        "category": "simulation",
        "icon": "shuffle",
    },
    {
        "slug": "fronteira-eficiente",
        "title": "Fronteira Eficiente & Sharpe",
        "description": "Construa a fronteira eficiente de Markowitz e encontre o portfólio ótimo para um dado nível de risco.",
        "category": "portfolio",
        "icon": "target",
    },
    {
        "slug": "garch",
        "title": "Modelo GARCH(1,1)",
        "description": "Modele a volatilidade condicional de retornos financeiros com o modelo GARCH(1,1).",
        "category": "timeseries",
        "icon": "activity",
    },
    {
        "slug": "black-scholes",
        "title": "Black-Scholes",
        "description": "Precifique opções europeias (Call/Put) e calcule as Greeks (Δ, Γ, Θ, ν, ρ).",
        "category": "simulation",
        "icon": "trending-up",
    },
    {
        "slug": "teste-hipotese",
        "title": "Teste de Hipótese",
        "description": "Realize testes t e z, calcule p-values e visualize regiões de rejeição.",
        "category": "hypothesis",
        "icon": "check-circle",
    },
    {
        "slug": "matriz-correlacao",
        "title": "Matriz de Correlação",
        "description": "Calcule e visualize a matriz de correlação de Pearson para múltiplos ativos.",
        "category": "portfolio",
        "icon": "grid",
    },
    {
        "slug": "juros-compostos",
        "title": "Juros Compostos",
        "description": "Calcule o valor futuro com capitalização discreta ou contínua e visualize o crescimento.",
        "category": "fundamental",
        "icon": "dollar-sign",
    },
    {
        "slug": "bayesiano",
        "title": "Atualização Bayesiana",
        "description": "Atualize crenças com evidência nova usando o modelo Beta-Binomial conjugado.",
        "category": "fundamental",
        "icon": "refresh-cw",
    },
    {
        "slug": "kalman",
        "title": "Filtro de Kalman",
        "description": "Estime dinamicamente o estado de um sistema a partir de observações ruidosas.",
        "category": "timeseries",
        "icon": "filter",
    },
]

TOOL_CATEGORIES = [
    {"key": "distributions", "translation_key": "tools_cat_distributions"},
    {"key": "hypothesis", "translation_key": "tools_cat_hypothesis"},
    {"key": "simulation", "translation_key": "tools_cat_simulation"},
    {"key": "portfolio", "translation_key": "tools_cat_portfolio"},
    {"key": "timeseries", "translation_key": "tools_cat_timeseries"},
    {"key": "fundamental", "translation_key": "tools_cat_fundamental"},
]


@app.route("/ferramentas")
def ferramentas_list():
    """
    Página de catálogo de ferramentas quantitativas.
    Exibe todas as ferramentas organizadas por categoria,
    com suporte a busca por texto e filtro por categoria.
    """
    busca = request.args.get("q", "").strip().lower()
    cat_filtro = request.args.get("cat", "").strip()

    filtered_tools = TOOLS
    if busca:
        filtered_tools = [
            t for t in filtered_tools
            if busca in t["title"].lower() or busca in t["description"].lower()
        ]
    if cat_filtro:
        filtered_tools = [t for t in filtered_tools if t["category"] == cat_filtro]

    return render_template(
        "ferramentas/list.html",
        tools=filtered_tools,
        categories=TOOL_CATEGORIES,
        busca=request.args.get("q", ""),
        cat_filtro=cat_filtro
    )


@app.route("/ferramentas/<slug>")
@login_obrigatorio
def ferramenta_detail(slug):
    """
    Página de uma ferramenta individual com calculadora interativa.
    """
    tool = next((t for t in TOOLS if t["slug"] == slug), None)
    if not tool:
        return render_template("errors/404.html"), 404

    return render_template(
        f"ferramentas/tools/{slug}.html",
        tool=tool
    )


# ============================================================================
# ROTAS DE AUTENTICAÇÃO
# ============================================================================

@app.route("/login", methods=["GET"])
def login():
    """
    Página de login.
    """
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("auth/login.html")


@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login_post():
    """
    Processa o login via Firebase ID Token.
    Rate limit: 5 tentativas por minuto.
    """
    dados = request.get_json()
    id_token = dados.get("id_token")

    if not id_token:
        return jsonify({"success": False, "error": "Token não fornecido"}), 400

    try:
        # Verifica o token no servidor com tolerância para diferença de relógio
        decoded_token = firebase_auth.verify_id_token(id_token, clock_skew_seconds=10)
        uid = decoded_token["uid"]
        email = decoded_token.get("email", "")

        # Busca ou cria o documento do usuário
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            nome = user_data.get("name", email.split("@")[0])
        else:
            # Cria novo usuário
            nome = email.split("@")[0]
            user_ref.set({
                "name": nome,
                "email": email,
                "role": "user",
                "enrolled_courses": {},
                "created_at": firestore.SERVER_TIMESTAMP
            })

        # Define a sessão
        session.permanent = True
        session["user_id"] = uid
        session["email"] = email
        session["name"] = nome

        # Determina o redirecionamento
        next_url = request.args.get("next", "/")

        return jsonify({"success": True, "redirect": next_url})

    except firebase_auth.InvalidIdTokenError as e:
        print("Erro de Token Inválido:", e)
        return jsonify({"success": False, "error": "Token inválido"}), 401
    except Exception as e:
        print("Erro Inesperado no Login:", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/cadastro", methods=["GET"])
def register():
    """
    Página de cadastro.
    """
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("auth/register.html")


@app.route("/cadastro", methods=["POST"])
@limiter.limit("3 per minute")
def register_post():
    """
    Processa o cadastro via Firebase ID Token.
    Rate limit: 3 tentativas por minuto.
    """
    dados = request.get_json()
    id_token = dados.get("id_token")
    nome = dados.get("name", "").strip()

    if not id_token:
        return jsonify({"success": False, "error": "Token não fornecido"}), 400

    if not nome:
        return jsonify({"success": False, "error": "Nome é obrigatório"}), 400

    try:
        # Verifica o token no servidor
        decoded_token = firebase_auth.verify_id_token(id_token)
        uid = decoded_token["uid"]
        email = decoded_token.get("email", "")

        # Cria o documento do usuário
        user_ref = db.collection("users").document(uid)
        user_ref.set({
            "name": nome,
            "email": email,
            "role": "user",
            "enrolled_courses": {},
            "created_at": firestore.SERVER_TIMESTAMP
        })

        # Define a sessão
        session.permanent = True
        session["user_id"] = uid
        session["email"] = email
        session["name"] = nome

        return jsonify({"success": True})

    except firebase_auth.InvalidIdTokenError:
        return jsonify({"success": False, "error": "Token inválido"}), 401
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/logout")
def logout():
    """
    Faz logout do usuário.
    """
    session.clear()
    return redirect(url_for("index"))


# ============================================================================
# API PARA CONFIGURAÇÃO DO FIREBASE (FRONTEND)
# ============================================================================

@app.route("/api/firebase-config")
def firebase_config():
    """
    Retorna a configuração pública do Firebase para o frontend.
    """
    return jsonify({
        "apiKey": os.getenv("FIREBASE_API_KEY"),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.getenv("FIREBASE_APP_ID")
    })


# ============================================================================
# ROTAS DO ADMIN
# ============================================================================

@app.route("/admin")
@login_obrigatorio
@apenas_admin
def admin_dashboard():
    """
    Painel administrativo.
    Exibe estatísticas e listas de posts e cursos.
    """
    # Contagem de posts
    posts_ref = db.collection("posts").stream()
    posts = [{"id": p.id, **p.to_dict()} for p in posts_ref]
    total_posts = len(posts)

    # Contagem de cursos
    cursos_ref = db.collection("courses").stream()
    cursos = [{"id": c.id, **c.to_dict()} for c in cursos_ref]
    total_cursos = len(cursos)

    # Contagem de usuários
    users_ref = db.collection("users").stream()
    total_users = len(list(users_ref))

    # Últimos 10 posts
    ultimos_posts = sorted(
        posts,
        key=lambda x: x.get("created_at", datetime.min),
        reverse=True
    )[:10]

    # Últimos 5 cursos
    ultimos_cursos = sorted(
        cursos,
        key=lambda x: x.get("created_at", datetime.min),
        reverse=True
    )[:5]

    return render_template(
        "admin/dashboard.html",
        total_posts=total_posts,
        total_courses=total_cursos,
        total_users=total_users,
        posts=ultimos_posts,
        courses=ultimos_cursos
    )


@app.route("/admin/post/novo", methods=["GET"])
@login_obrigatorio
@apenas_admin
def admin_post_new():
    """
    Página para criar novo post.
    """
    return render_template("admin/post_editor.html", post=None)


@app.route("/admin/post/novo", methods=["POST"])
@login_obrigatorio
@apenas_admin
def admin_post_new_post():
    """
    Salva um novo post no Firestore.
    """
    titulo = request.form.get("title", "").strip()
    slug = request.form.get("slug", "").strip()
    resumo = request.form.get("summary", "").strip()
    tags_str = request.form.get("tags", "").strip()
    cover_image = request.form.get("cover_image", "").strip()
    conteudo = request.form.get("content", "").strip()
    publicado = request.form.get("published") == "on"

    # Validações
    if not titulo:
        flash("Título é obrigatório", "error")
        return redirect(url_for("admin_post_new"))

    if not slug:
        slug = gerar_slug(titulo)

    if not validar_slug(slug):
        flash("Slug inválido. Use apenas letras minúsculas, números e hífens.", "error")
        return redirect(url_for("admin_post_new"))

    # Sanitiza o conteúdo HTML
    conteudo_limpo = sanitize_html(conteudo)

    # Processa as tags
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]

    # Cria o documento
    post_data = {
        "title": titulo,
        "slug": slug,
        "summary": resumo,
        "tags": tags,
        "cover_image": cover_image,
        "content": conteudo_limpo,
        "published": publicado,
        "views": 0,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    db.collection("posts").add(post_data)
    flash("Notícia criada com sucesso!", "success")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/post/editar/<post_id>", methods=["GET"])
@login_obrigatorio
@apenas_admin
def admin_post_edit(post_id):
    """
    Página para editar um post existente.
    """
    post_doc = db.collection("posts").document(post_id).get()
    if not post_doc.exists:
        return render_template("errors/404.html"), 404

    post = {"id": post_doc.id, **post_doc.to_dict()}
    return render_template("admin/post_editor.html", post=post)


@app.route("/admin/post/editar/<post_id>", methods=["POST"])
@login_obrigatorio
@apenas_admin
def admin_post_edit_post(post_id):
    """
    Atualiza um post existente no Firestore.
    """
    titulo = request.form.get("title", "").strip()
    slug = request.form.get("slug", "").strip()
    resumo = request.form.get("summary", "").strip()
    tags_str = request.form.get("tags", "").strip()
    cover_image = request.form.get("cover_image", "").strip()
    conteudo = request.form.get("content", "").strip()
    publicado = request.form.get("published") == "on"

    # Validações
    if not titulo:
        flash("Título é obrigatório", "error")
        return redirect(url_for("admin_post_edit", post_id=post_id))

    if not slug:
        slug = gerar_slug(titulo)

    if not validar_slug(slug):
        flash("Slug inválido. Use apenas letras minúsculas, números e hífens.", "error")
        return redirect(url_for("admin_post_edit", post_id=post_id))

    # Sanitiza o conteúdo HTML
    conteudo_limpo = sanitize_html(conteudo)

    # Processa as tags
    tags = [t.strip() for t in tags_str.split(",") if t.strip()]

    # Atualiza o documento
    post_data = {
        "title": titulo,
        "slug": slug,
        "summary": resumo,
        "tags": tags,
        "cover_image": cover_image,
        "content": conteudo_limpo,
        "published": publicado,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    db.collection("posts").document(post_id).update(post_data)
    flash("Notícia atualizada com sucesso!", "success")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/post/deletar/<post_id>", methods=["POST"])
@login_obrigatorio
@apenas_admin
def admin_post_delete(post_id):
    """
    Deleta um post do Firestore.
    """
    try:
        db.collection("posts").document(post_id).delete()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/admin/curso/novo", methods=["GET"])
@login_obrigatorio
@apenas_admin
def admin_course_new():
    """
    Página para criar novo curso.
    """
    return render_template("admin/course_editor.html", course=None)


@app.route("/admin/curso/novo", methods=["POST"])
@login_obrigatorio
@apenas_admin
def admin_course_new_post():
    """
    Salva um novo curso no Firestore.
    """
    titulo = request.form.get("title", "").strip()
    descricao = request.form.get("description", "").strip()
    thumbnail = request.form.get("thumbnail", "").strip()
    highlights_str = request.form.get("highlights", "").strip()
    publicado = request.form.get("published") == "on"

    # Validações
    if not titulo:
        flash("Título é obrigatório", "error")
        return redirect(url_for("admin_course_new"))

    # Processa os destaques
    highlights = [h.strip() for h in highlights_str.split("\n") if h.strip()]

    # Cria o documento
    course_data = {
        "title": titulo,
        "description": descricao,
        "thumbnail": thumbnail,
        "highlights": highlights,
        "published": publicado,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    db.collection("courses").add(course_data)
    flash("Aula criada com sucesso!", "success")

    return redirect(url_for("admin_dashboard"))


# ============================================================================
# HANDLERS DE ERRO
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    """
    Handler para erro 404 (página não encontrada).
    """
    return render_template("errors/404.html"), 404


@app.errorhandler(403)
def forbidden(error):
    """
    Handler para erro 403 (acesso negado).
    """
    return render_template("errors/403.html"), 403


@app.errorhandler(429)
def rate_limit(error):
    """
    Handler para erro 429 (muitas requisições).
    """
    return jsonify({
        "success": False,
        "error": "Muitas requisições. Tente novamente mais tarde."
    }), 429


# ============================================================================
# INICIALIZAÇÃO
# ============================================================================

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
