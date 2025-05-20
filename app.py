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

    # CLIQUES NO MÊS (agora com timestamp real)
    inicio_mes = datetime.now().replace(day=1)
    cliques_mes = sum(1 for _ in db.collection("logs_cliques")
                      .where("uid", "==", uid)
                      .where("data", ">=", inicio_mes)
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
    uid = session["usuario"]["uid"]
    
    if request.method == "POST":
        slug = request.form["slug"].strip()
        url_destino = request.form["url_destino"].strip()
        tipo = request.form["tipo"]

        # Verifica se o slug já existe
        existente = db.collection("links_encurtados").where("slug", "==", slug).get()
        if existente:
            flash("Esse slug já está em uso. Escolha outro.", "error")
            return redirect("/criar-link")

        dados = {
            "slug": slug,
            "url_destino": url_destino,
            "categoria": tipo,
            "uid": uid,
            "cliques": 0,
            "criado_em": datetime.now().isoformat()
        }

        db.collection("links_encurtados").add(dados)
        flash("Link criado com sucesso!", "success")
        return redirect("/criar-link")

    # Recupera todos os links do usuário
    links_ref = db.collection("links_encurtados").where("uid", "==", uid).order_by("criado_em", direction=firestore.Query.DESCENDING)
    links_docs = links_ref.stream()

    links = []
    for doc in links_docs:
        dados = doc.to_dict()
        dados["id"] = doc.id
        links.append({
            "id": doc.id,
            "slug": dados.get("slug"),
            "cliques": dados.get("cliques", 0),
            "categoria": dados.get("categoria", "indefinido")
        })

    return render_template("criar_link_clickdivulga.html", links=links)

@app.route("/excluir-link/<id>")
@verificar_login
def excluir_link(id):
    uid = session["usuario"]["uid"]

    doc_ref = db.collection("links_encurtados").document(id)
    doc = doc_ref.get()

    if doc.exists and doc.to_dict().get("uid") == uid:
        doc_ref.delete()
        flash("Link excluído com sucesso!", "success")
    else:
        flash("Ação não autorizada ou link inexistente.", "error")

    return redirect("/criar-link")

@app.route("/editar-link/<id>", methods=["GET", "POST"])
@verificar_login
def editar_link(id):
    uid = session["usuario"]["uid"]
    doc_ref = db.collection("links_encurtados").document(id)
    doc = doc_ref.get()

    if not doc.exists or doc.to_dict().get("uid") != uid:
        flash("Link não encontrado ou acesso não autorizado.", "error")
        return redirect("/criar-link")

    if request.method == "POST":
        slug = request.form["slug"].strip()
        url_destino = request.form["url_destino"].strip()
        tipo = request.form["tipo"]

        doc_ref.update({
            "slug": slug,
            "url_destino": url_destino,
            "categoria": tipo,
        })

        flash("Link atualizado com sucesso!", "success")
        return redirect("/criar-link")

    dados = doc.to_dict()

    return render_template("editar_link.html", link={
        "id": id,
        "slug": dados.get("slug"),
        "url_destino": dados.get("url_destino"),
        "categoria": dados.get("categoria")
    })

@app.route("/r/<slug>")
def redirecionar(slug):
    # Busca por slug via where (já que os docs não usam slug como ID)
    doc_ref = db.collection("links_encurtados").where("slug", "==", slug).limit(1).stream()
    doc = next(doc_ref, None)

    if doc:
        dados = doc.to_dict()

        # Atualiza contador
        doc.reference.update({
            "cliques": firestore.Increment(1)
        })

        # Salva clique com timestamp real
        db.collection("logs_cliques").add({
            "slug": slug,
            "uid": dados.get("uid", ""),
            "categoria": dados.get("categoria", ""),
            "data": datetime.now(),  # agora é timestamp
            "ip": request.remote_addr,
            "user_agent": request.headers.get("User-Agent")
        })

        # Se for um link do tipo contador, não redireciona
        if dados.get("categoria") == "contador":
            return render_template("contador_clicks.html", slug=slug)

        return redirect(dados.get("url_destino", "/"))

    return "Link não encontrado", 404

@app.route("/grupos", methods=["GET", "POST"])
@verificar_login
def grupos():
    uid = session["usuario"]["uid"]

    if request.method == "POST":
        slug = request.form["slug"]
        entradas = int(request.form.get("entradas", 0))

        # Busca segura por slug + uid
        ref = db.collection("links_encurtados") \
            .where("uid", "==", uid) \
            .where("slug", "==", slug) \
            .limit(1).stream()

        doc = next(ref, None)
        if doc:
            doc.reference.update({"entradas": entradas})

        return redirect("/grupos")

    grupos_ref = db.collection("links_encurtados") \
        .where("uid", "==", uid) \
        .where("categoria", "==", "grupo") \
        .stream()

    grupos = []
    for doc in grupos_ref:
        dados = doc.to_dict()
        slug = dados.get("slug")
        cliques = int(dados.get("cliques", 0))
        entradas = int(dados.get("entradas", 0))
        conversao = round((entradas / cliques) * 100, 2) if cliques > 0 else 0

        grupos.append({
            "slug": slug,
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
    uid = session["usuario"]["uid"]

    try:
        ref = db.collection("links_encurtados") \
            .where("uid", "==", uid) \
            .where("slug", "==", slug) \
            .limit(1).stream()

        doc = next(ref, None)
        if doc:
            doc.reference.update({"entradas": entradas})
            flash("Entradas atualizadas com sucesso!", "success")
        else:
            flash("Link não encontrado.", "error")

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
