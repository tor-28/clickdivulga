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
    docs = db.collection("links_encurtados").where("uid", "==", uid).stream()
    links = [d.to_dict() for d in docs]

    links_hoje = sum(1 for l in links if l.get("criado_em", "").startswith(datetime.now().strftime("%Y-%m-%d")))
    cliques_mes = sum(l.get("cliques", 0) for l in links if datetime.now().strftime("%Y-%m") in l.get("criado_em", ""))
    produto_mais_clicado = max(links, key=lambda x: x.get("cliques", 0), default={}).get("titulo", "-")

    return render_template("dashboard_clickdivulga.html",
        links_hoje=links_hoje,
        cliques_mes=cliques_mes,
        produto_mais_clicado=produto_mais_clicado,
        links_recentes=sorted(links, key=lambda x: x.get("criado_em", ""), reverse=True)[:6]
    )

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
