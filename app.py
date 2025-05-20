from flask import Flask, render_template, request, redirect, url_for, session, flash
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

firebase_b64 = os.getenv("FIREBASE_KEY_B64")
if not firebase_b64:
    raise ValueError("FIREBASE_KEY_B64 não configurado no .env")

decoded = base64.b64decode(firebase_b64)
with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
    temp_file.write(decoded)
    temp_file.flush()
    cred = credentials.Certificate(temp_file.name)
    firebase_admin.initialize_app(cred)

db = firestore.client()

def verificar_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        id_token = request.form.get("idToken")
        try:
            decoded_token = auth.verify_id_token(id_token)
            session["usuario"] = {
                "uid": decoded_token["uid"],
                "email": decoded_token.get("email", "")
            }
            return redirect(url_for("painel"))
        except Exception as e:
            print("Erro ao verificar token:", e)
            return "Token inválido ou expirado", 401
    return render_template("login_clickdivulga.html")

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))

@app.route("/painel")
@verificar_login
def painel():
    uid = session["usuario"]["uid"]
    print(f"📊 Carregando dashboard para UID: {uid}")

    try:
        # Consulta geral dos links do usuário
        docs = db.collection("links_encurtados").where("uid", "==", uid).stream()

        links = []
        cliques_total = 0
        cliques_por_dia = {}
        grupo_mais_clicado = {"slug": "", "cliques": 0}
        produto_mais_clicado = {"slug": "", "cliques": 0}
        links_recentes = []

        for doc in docs:
            data = doc.to_dict()
            data["slug"] = doc.id
            links.append(data)
            cliques_total += data.get("cliques", 0)

            # Agrupar por categoria
            categoria = data.get("categoria", "")
            if categoria == "grupo" and data.get("cliques", 0) > grupo_mais_clicado["cliques"]:
                grupo_mais_clicado = {"slug": data["slug"], "cliques": data["cliques"]}
            elif categoria == "produto" and data.get("cliques", 0) > produto_mais_clicado["cliques"]:
                produto_mais_clicado = {"slug": data["slug"], "cliques": data["cliques"]}

        # Links ordenados por data (recente primeiro)
        links_ordenados = sorted(links, key=lambda x: x.get("criado_em", ""), reverse=True)
        links_recentes = links_ordenados[:4]

        # Contar links criados hoje
        hoje = datetime.now().date()
        links_hoje = sum(1 for l in links if "criado_em" in l and datetime.fromisoformat(l["criado_em"]).date() == hoje)

        return render_template("dashboard_clickdivulga.html",
                               links_hoje=links_hoje,
                               cliques_mes=cliques_total,
                               produto_mais_clicado=produto_mais_clicado["slug"] or "N/A",
                               grupo_mais_clicado=grupo_mais_clicado["slug"] or "N/A",
                               links_recentes=links_recentes)
    except Exception as e:
        print("❌ Erro ao carregar painel:", e)
        return "Erro ao carregar painel", 500

@app.route("/criar-link", methods=["GET", "POST"])
@verificar_login
def criar_link():
    if request.method == "POST":
        slug = request.form.get("slug").strip()
        destino = request.form.get("url_destino").strip()
        tipo = request.form.get("tipo", "produto")
        uid = session["usuario"]["uid"]

        doc_ref = db.collection("links_encurtados").document(slug)
        if doc_ref.get().exists:
            return "Slug já está em uso. Escolha outro.", 400

        doc_ref.set({
            "slug": slug,
            "url_destino": destino,
            "uid": uid,
            "tipo": tipo,
            "cliques": 0,
            "criado_em": datetime.now().isoformat()
        })
        return redirect(url_for("painel"))
    return render_template("criar_link_clickdivulga.html")

@app.route("/r/<slug>")
def redirecionar(slug):
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

        if dados.get("tipo") == "contador":
            return render_template("contador_clicks.html", slug=slug)

        return redirect(dados["url_destino"])
    return "Link não encontrado", 404

@app.route("/grupos")
@verificar_login
def grupos():
    uid = session["usuario"]["uid"]
    docs = db.collection("links_encurtados").where("uid", "==", uid).stream()

    grupos = []
    for doc in docs:
        dados = doc.to_dict()
        url = dados.get("url_destino", "")
        if "whatsapp.com" in url:
            slug = dados.get("slug")
            cliques = dados.get("cliques", 0)
            entradas = dados.get("entradas", 0)
            conversao = 0
            if cliques > 0:
                conversao = round((entradas / cliques) * 100, 2)
            grupos.append({
                "slug": slug,
                "url": url,
                "cliques": cliques,
                "entradas": entradas,
                "conversao": conversao
            })

    return render_template("desempenho_de_grupos.html", grupos=grupos)

@app.route("/atualizar-entradas", methods=["POST"])
@verificar_login
def atualizar_entradas():
    slug = request.form.get("slug")
    entradas = int(request.form.get("entradas", 0))

    try:
        db.collection("links_encurtados").document(slug).update({
            "entradas": entradas
        })
        flash("Entradas atualizadas com sucesso!", "success")
    except Exception as e:
        print("Erro ao atualizar entradas:", e)
        flash("Erro ao atualizar entradas.", "error")

    return redirect(url_for("grupos"))
