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

# 🔧 Atualiza categorias automaticamente com base no destino
def atualizar_categoria_links(uid):
    try:
        links = db.collection("links_encurtados") \
            .where("uid", "==", uid).stream()
        for doc in links:
            dados = doc.to_dict()
            url = dados.get("url_destino", "")
            categoria_atual = dados.get("categoria", "")
            nova_categoria = "outro"

            if "whatsapp.com" in url:
                nova_categoria = "grupo"
            elif "shopee.com.br" in url:
                nova_categoria = "produto"

            if categoria_atual != nova_categoria:
                doc.reference.update({"categoria": nova_categoria})
    except Exception as e:
        print(f"Erro ao atualizar categorias automaticamente: {e}")

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

    atualizar_categoria_links(uid)

    # LINKS GERADOS HOJE
    hoje = datetime.now().date().isoformat()
    links_hoje = db.collection("links_encurtados") \
        .where("uid", "==", uid) \
        .where("criado_em", ">=", hoje) \
        .stream()
    total_links_hoje = sum(1 for _ in links_hoje)

    # CLIQUES NO MÊS
    agora = datetime.now()
    inicio_mes = agora.replace(day=1).isoformat()
    cliques_mes = sum(1 for _ in db.collection("logs_cliques")
                      .where("data", ">=", inicio_mes)
                      .where("uid", "==", uid)
                      .stream())

    # PRODUTO MAIS CLICADO
    try:
        produtos = db.collection("links_encurtados") \
            .where("uid", "==", uid) \
            .where("categoria", "==", "produto") \
            .order_by("cliques", direction=firestore.Query.DESCENDING) \
            .limit(1).stream()
        produto_mais_clicado = next(produtos, None)
        nome_produto = produto_mais_clicado.to_dict().get("titulo", "Sem nome") if produto_mais_clicado else "Nenhum"
    except Exception as e:
        print("Erro ao buscar produto mais clicado:", e)
        nome_produto = "Nenhum"

    # GRUPO MAIS CLICADO
    try:
        grupos = db.collection("links_encurtados") \
            .where("uid", "==", uid) \
            .where("categoria", "==", "grupo") \
            .order_by("cliques", direction=firestore.Query.DESCENDING) \
            .limit(1).stream()
        grupo_mais_clicado = next(grupos, None)
        nome_grupo = grupo_mais_clicado.to_dict().get("titulo", "Sem nome") if grupo_mais_clicado else "Nenhum"
    except Exception as e:
        print("Erro ao buscar grupo mais clicado:", e)
        nome_grupo = "Nenhum"

    # LINKS RECENTES
    links_recentes = db.collection("links_encurtados") \
        .where("uid", "==", uid) \
        .order_by("criado_em", direction=firestore.Query.DESCENDING) \
        .limit(4).stream()

    links_formatados = []
    for doc in links_recentes:
        dados = doc.to_dict()
        links_formatados.append({
            "slug": dados.get("slug"),
            "titulo": dados.get("titulo", ""),
            "cliques": dados.get("cliques", 0),
            "categoria": dados.get("categoria", "indefinido")
        })

    return render_template("dashboard_clickdivulga.html",
        links_hoje=total_links_hoje,
        cliques_mes=cliques_mes,
        produto_mais_clicado=nome_produto,
        grupo_mais_clicado=nome_grupo,
        links_recentes=links_formatados
    )

@app.route("/criar-link", methods=["GET", "POST"])
@verificar_login
def criar_link():
    if request.method == "POST":
        slug = request.form.get("slug").strip()
        destino = request.form.get("url_destino").strip()
        uid = session["usuario"]["uid"]

        categoria = "outro"
        if "whatsapp" in destino:
            categoria = "grupo"
        elif "shopee.com.br" in destino:
            categoria = "produto"

        doc_ref = db.collection("links_encurtados").document(slug)
        if doc_ref.get().exists:
            return "Slug já está em uso. Escolha outro.", 400

        doc_ref.set({
            "slug": slug,
            "url_destino": destino,
            "uid": uid,
            "cliques": 0,
            "categoria": categoria,
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
            "uid": dados.get("uid", ""),
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

@app.route("/atualizar-categorias")
def atualizar_categorias_links():
    try:
        links = db.collection("links_encurtados").stream()
        atualizados = 0

        for doc in links:
            dados = doc.to_dict()
            url = dados.get("url_destino", "")
            categoria = dados.get("categoria", "")

            nova_categoria = "outro"
            if "whatsapp" in url:
                nova_categoria = "grupo"
            elif "shopee.com.br" in url:
                nova_categoria = "produto"

            if categoria != nova_categoria:
                doc.reference.update({"categoria": nova_categoria})
                atualizados += 1

        return f"✅ Categorias atualizadas com sucesso. Total alterados: {atualizados}"
    
    except Exception as e:
        return f"❌ Erro ao atualizar categorias: {e}"

if __name__ == "__main__":
    app.run(debug=True)
