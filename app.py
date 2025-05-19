
from flask import Flask, render_template, request, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os
import base64
import tempfile
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clickdivulga-default")

# Log de inicialização
print("🔐 Iniciando aplicação ClickDivulga...")

# Firebase Admin via base64
firebase_b64 = os.getenv("FIREBASE_KEY_B64")
if not firebase_b64:
    raise ValueError("❌ FIREBASE_KEY_B64 não configurado no .env")

print("📦 Decodificando chave do Firebase...")
decoded = base64.b64decode(firebase_b64)
with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
    temp_file.write(decoded)
    temp_file.flush()
    cred = credentials.Certificate(temp_file.name)
    firebase_admin.initialize_app(cred)

print("✅ Firebase inicializado com sucesso.")
db = firestore.client()

# Middleware para rotas protegidas
def verificar_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario" not in session:
            print("🔒 Acesso negado. Sessão não encontrada.")
            return redirect(url_for("login"))
        print(f"✅ Sessão detectada para UID: {session['usuario']['uid']}")
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        id_token = request.form.get("idToken")
        print("📩 Token recebido:", id_token[:30] + "..." if id_token else "Nenhum")
        try:
            decoded_token = auth.verify_id_token(id_token)
            session["usuario"] = {
                "uid": decoded_token["uid"],
                "email": decoded_token.get("email", "")
            }
            print(f"✅ Login bem-sucedido: {decoded_token.get('email')}")
            return redirect(url_for("painel"))
        except Exception as e:
            print("❌ Erro ao verificar token:", e)
            return "Token inválido ou expirado", 401
    return render_template("login_clickdivulga.html")

@app.route("/logout")
def logout():
    print(f"🔓 Logout: {session.get('usuario', {}).get('email', 'desconhecido')}")
    session.pop("usuario", None)
    return redirect(url_for("login"))

@app.route("/painel")
@verificar_login
def painel():
    uid = session["usuario"]["uid"]
    email = session["usuario"]["email"]
    print(f"📊 Carregando dashboard para UID: {uid}")

    hoje = datetime.now().date()
    inicio_mes = hoje.replace(day=1)

    links_hoje = 0
    cliques_mes = 0
    produtos = {}

    docs = db.collection("links_encurtados").where("uid", "==", uid).stream()
    for doc in docs:
        d = doc.to_dict()
        criado_em = datetime.fromisoformat(d.get("criado_em"))
        if criado_em.date() == hoje:
            links_hoje += 1
        if criado_em.date() >= inicio_mes:
            cliques_mes += d.get("cliques", 0)

        nome = d.get("slug")  # usar slug como nome simbólico por enquanto
        produtos[nome] = produtos.get(nome, 0) + d.get("cliques", 0)

    produto_mais_clicado = max(produtos, key=produtos.get) if produtos else "Nenhum"
    produtos_ordenados = sorted(produtos.items(), key=lambda x: x[1], reverse=True)[:5]
    produtos_quentes = [{"nome": nome, "cliques": cliques, "slug": nome} for nome, cliques in produtos_ordenados]

    return render_template("dashboard_clickdivulga.html",
                           links_hoje=links_hoje,
                           cliques_mes=cliques_mes,
                           produto_mais_clicado=produto_mais_clicado,
                           produtos_quentes=produtos_quentes)


@app.route("/criar-link", methods=["GET", "POST"])
@verificar_login
def criar_link():
    if request.method == "POST":
        slug = request.form.get("slug").strip()
        destino = request.form.get("url_destino").strip()
        uid = session["usuario"]["uid"]

        print(f"🆕 Criando link '{slug}' para {destino}")
        doc_ref = db.collection("links_encurtados").document(slug)
        if doc_ref.get().exists:
            print("⚠️ Slug já em uso:", slug)
            return "Slug já está em uso. Escolha outro.", 400

        doc_ref.set({
            "slug": slug,
            "url_destino": destino,
            "uid": uid,
            "cliques": 0,
            "criado_em": datetime.now().isoformat()
        })
        print("✅ Link criado com sucesso.")
        return redirect(url_for("painel"))
    return render_template("criar_link_clickdivulga.html")

@app.route("/r/<slug>")
def redirecionar(slug):
    print(f"🔁 Redirecionamento requisitado: /r/{slug}")
    doc = db.collection("links_encurtados").document(slug).get()
    if doc.exists:
        dados = doc.to_dict()
        db.collection("links_encurtados").document(slug).update({
            "cliques": firestore.Increment(1)
        })
        db.collection("logs_cliques").add({
            "slug": slug,
            "data": datetime.now().isoformat(),
            "ip": request.remote_addr
        })
        print(f"➡️ Redirecionando para: {dados['url_destino']}")
        return redirect(dados["url_destino"])
    print("❌ Slug não encontrado:", slug)
    return "Link não encontrado", 404

if __name__ == "__main__":
    app.run(debug=True)
