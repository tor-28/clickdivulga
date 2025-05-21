from flask import Flask, render_template, request, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os
import base64
import tempfile
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import requests


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
        dados = doc.to_dict()
        slug = dados.get("slug")

        # 1. Exclui o link
        doc_ref.delete()

        # 2. Exclui todos os logs de cliques com o mesmo slug e uid
        logs = db.collection("logs_cliques") \
            .where("slug", "==", slug) \
            .where("uid", "==", uid) \
            .stream()
        for log in logs:
            log.reference.delete()

        flash(f"Link e cliques do grupo '{slug}' excluídos com sucesso!", "success")
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
        doc_ref = db.collection("links_encurtados") \
            .where("uid", "==", uid) \
            .where("slug", "==", slug) \
            .limit(1).stream()
        doc = next(doc_ref, None)
        if doc:
            doc.reference.update({"entradas": entradas})
        return redirect("/grupos")

    # Filtros
    filtro_data = request.args.get("filtro", "todos")
    filtro_tipo = request.args.get("tipo", "grupo")
    dias = int(filtro_data) if filtro_data.isdigit() else None
    data_limite = datetime.now() - timedelta(days=dias) if dias else None

    # Coleta dos grupos filtrados
    grupos_query = db.collection("links_encurtados").where("uid", "==", uid)
    if filtro_tipo != "todos":
        grupos_query = grupos_query.where("categoria", "==", filtro_tipo)
    grupos_ref = grupos_query.stream()

    grupos, comparativo_labels, comparativo_data = [], [], []
    total_cliques = 0

    for doc in grupos_ref:
        dados = doc.to_dict()
        slug = dados.get("slug")
        criado_em = dados.get("criado_em", "")
        try:
            dt_criado = datetime.fromisoformat(criado_em) if isinstance(criado_em, str) else criado_em
            if data_limite and dt_criado < data_limite:
                continue
        except:
            continue

        cliques = int(dados.get("cliques", 0))
        entradas = int(dados.get("entradas", 0))
        conversao = round((entradas / cliques) * 100, 2) if cliques > 0 else 0

        # Etiquetas visuais
        etiquetas = []
        if conversao >= 70:
            etiquetas.append("🟢 Alta Conversão")
        if cliques < 10:
            etiquetas.append("🟡 Baixo Tráfego")
        if entradas == 0:
            etiquetas.append("🔴 Sem Entrada")

        grupos.append({
            "slug": slug,
            "cliques": cliques,
            "entradas": entradas,
            "conversao": conversao,
            "etiquetas": etiquetas
        })

        comparativo_labels.append(slug)
        comparativo_data.append(cliques)
        total_cliques += cliques

    # Resumo
    total_grupos = len(grupos)
    media_cliques = round(total_cliques / total_grupos, 2) if total_grupos else 0
    mais_clicado = max(grupos, key=lambda g: g["cliques"])["slug"] if grupos else "Nenhum"

    resumo = {
        "total_cliques": total_cliques,
        "total_grupos": total_grupos,
        "media_cliques": media_cliques,
        "mais_clicado": mais_clicado
    }

    # Cliques por hora (gráfico)
    cliques_por_hora = [0] * 24
    logs = db.collection("logs_cliques").where("uid", "==", uid).stream()
    for doc in logs:
        dados = doc.to_dict()
        data = dados.get("data")
        try:
            dt = datetime.fromisoformat(data) if isinstance(data, str) else data
            if data_limite and dt < data_limite:
                continue
            cliques_por_hora[dt.hour] += 1
        except:
            continue

    # Rankings
    ranking_cliques = sorted(grupos, key=lambda g: g["cliques"], reverse=True)[:5]
    ranking_conversao = sorted(grupos, key=lambda g: g["conversao"], reverse=True)[:5]
    ranking_entradas = sorted(grupos, key=lambda g: g["entradas"], reverse=True)[:5]

    # Recomendações inteligentes
    recomendacoes = []
    for g in grupos:
        if g["conversao"] >= 80 and g["cliques"] >= 30:
            recomendacoes.append(f"🔥 O grupo *{g['slug']}* está com alta conversão ({g['conversao']}%)")
        if g["cliques"] >= 50 and g["entradas"] == 0:
            recomendacoes.append(f"⚠️ O grupo *{g['slug']}* teve muitos cliques mas nenhuma entrada.")
        if g["cliques"] <= 5:
            recomendacoes.append(f"📉 O grupo *{g['slug']}* teve poucos cliques. Avalie sua divulgação.")

    return render_template("desempenho_de_grupos.html",
        grupos=grupos,
        filtro=filtro_data,
        tipo=filtro_tipo,
        resumo=resumo,
        cliques=cliques_por_hora,
        ranking_cliques=ranking_cliques,
        ranking_conversao=ranking_conversao,
        ranking_entradas=ranking_entradas,
        comparativo_labels=comparativo_labels,
        comparativo_data=comparativo_data,
        recomendacoes=recomendacoes
    )

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


@app.route("/buscar-produto", methods=["POST"])
@verificar_login
def buscar_produto():
    import re
    import time
    import hmac
    import hashlib
    import requests

    uid = session["usuario"]["uid"]
    url = request.form.get("url")

    match = re.search(r"-i\.(\d+)\.(\d+)", url)
    if not match:
        flash("URL inválida. Não foi possível extrair shop_id e item_id.", "error")
        return redirect("/produtos")

    shop_id, item_id = match.groups()

    # Buscar App ID e Secret do afiliado
    doc = db.collection("api_shopee").document(uid).get()
    if not doc.exists:
        flash("Você precisa cadastrar sua API Shopee antes de buscar produtos.", "error")
        return redirect("/minha-api")

    cred = doc.to_dict()
    app_id = cred.get("app_id") or cred.get("client_id")
    app_secret = cred.get("app_secret") or cred.get("client_secret")

    if not app_id or not app_secret:
        flash("App ID ou App Secret não encontrados. Verifique sua API cadastrada.", "error")
        return redirect("/minha-api")

    timestamp = str(int(time.time() * 1000))
    base_string = app_id + timestamp
    sign = hmac.new(app_secret.encode(), base_string.encode(), hashlib.sha256).hexdigest()

    headers = {
        "AppId": app_id,
        "Timestamp": timestamp,
        "Authorization": sign,
        "Content-Type": "application/json"
    }

    body = {
        "products": [
            {"shop_id": int(shop_id), "item_id": int(item_id)}
        ]
    }

    try:
        response = requests.post("https://affiliate.shopee.com.br/api/v1/product/info", headers=headers, json=body)

        print("🔁 Resposta da Shopee:")
        print(response.status_code)
        print(response.text)

        if response.status_code == 200:
            result = response.json().get("data", [])
            produtos = []
            for produto in result:
                produtos.append({
                    "titulo": produto.get("name"),
                    "imagem": produto.get("image"),
                    "preco": produto.get("price"),
                    "estoque": produto.get("stock"),
                    "comissao": produto.get("commission", 0),
                    "loja": produto.get("shop_name", "")
                })
            return render_template("produtos_clickdivulga.html", produtos=produtos)
        else:
            flash(f"Erro {response.status_code}: {response.text}", "error")
            return redirect("/produtos")

    except Exception as e:
        flash(f"Erro na requisição: {str(e)}", "error")
        return redirect("/produtos")

@app.route("/minha-api", methods=["GET", "POST"])
@verificar_login
def minha_api():
    uid = session["usuario"]["uid"]
    doc_ref = db.collection("api_shopee").document(uid)
    doc = doc_ref.get()

    if request.method == "POST":
        data = {
            "app_id": request.form.get("app_id"),
            "app_secret": request.form.get("app_secret"),
            "atualizado_em": datetime.now().isoformat()
        }
        doc_ref.set(data)
        flash("Credenciais da API Shopee atualizadas com sucesso!", "success")
        return redirect("/minha-api")

    dados = doc.to_dict() if doc.exists else {}
    return render_template("minha_api.html", dados=dados)

def buscar_produtos_agendado():
    termos = ["ring light", "bermuda", "cama pet"]
    print("🔁 Buscando produtos da Shopee com credenciais dos afiliados...")

    usuarios_api = db.collection("api_shopee").stream()
    usuarios = [u for u in usuarios_api]

    for i, termo in enumerate(termos):
        try:
            if not usuarios:
                print("⚠️ Nenhum afiliado com API cadastrada.")
                break
            user = usuarios[i % len(usuarios)]
            cred = user.to_dict()
            headers = {"Authorization": f"Bearer {cred['access_token']}"}
            response = requests.get(f"https://api.shopee.com.br/search?query={termo}", headers=headers)

            if response.status_code == 200:
                produtos = response.json().get("items", [])[:50]
                for produto in produtos:
                    db.collection("produtos_sugestoes").add({
                        "titulo": produto.get("name"),
                        "imagem": produto.get("image_url"),
                        "preco": produto.get("price"),
                        "estoque": produto.get("stock"),
                        "comissao": produto.get("commission", 0),
                        "loja": produto.get("shop_name", ""),
                        "uid_api": user.id,
                        "buscado_em": datetime.now().isoformat()
                    })
        except Exception as e:
            print(f"Erro ao consultar para termo '{termo}': {e}")

scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
scheduler.add_job(buscar_produtos_agendado, 'cron', hour=0, minute=1)
scheduler.add_job(buscar_produtos_agendado, 'cron', hour=8, minute=1)
scheduler.add_job(buscar_produtos_agendado, 'cron', hour=12, minute=1)
scheduler.add_job(buscar_produtos_agendado, 'cron', hour=20, minute=1)
scheduler.start()
