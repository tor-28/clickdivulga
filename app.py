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

@app.route("/produtos")
@verificar_login
def produtos():
    from pytz import timezone
    from datetime import datetime

    uid = session["usuario"]["uid"]
    firestore_client = firestore.client()

    produtos = []  # Produtos encontrados (não salvos)
    resultados = []
    lojas_disponiveis = set()
    palavras_disponiveis = set()
    todos_produtos = []

    try:
        termos_ref = firestore_client.collection("resultados_busca").document(uid).collection("termos").stream()
        for doc in termos_ref:
            dados = doc.to_dict()
            atualizado_em = dados.get("atualizado_em")

            for p in dados.get("produtos", []):
                if p.get("loja"):
                    lojas_disponiveis.add(p.get("loja"))
                if dados.get("termo"):
                    palavras_disponiveis.add(dados.get("termo").lower())

                p["atualizado_em"] = atualizado_em
                todos_produtos.append(p)

            resultados.append({
                "termo": dados.get("termo"),
                "tipo": dados.get("tipo"),
                "atualizado_em": atualizado_em,
                "produtos": dados.get("produtos", [])
            })
    except Exception as e:
        print(f"Erro ao carregar resultados salvos: {e}")

    # Limita a 400 produtos por afiliado (mantém os mais recentes)
    todos_produtos = sorted(todos_produtos, key=lambda x: x.get("atualizado_em", ""), reverse=True)[:400]

    filtro_loja = request.args.get("filtro_loja", "").strip()
    filtro_termo = request.args.get("filtro_termo", "").strip().lower()

    produtos_filtrados = []
    for p in todos_produtos:
        if filtro_loja and p.get("loja") != filtro_loja:
            continue
        if filtro_termo and filtro_termo not in p.get("titulo", "").lower():
            continue
        produtos_filtrados.append(p)

    produtos_ordenados = sorted(produtos_filtrados, key=lambda x: x.get("atualizado_em", ""), reverse=True)

    pagina = int(request.args.get("pagina", 1))
    inicio = (pagina - 1) * 20
    fim = inicio + 20
    total_paginas = (len(produtos_ordenados) // 20) + (1 if len(produtos_ordenados) % 20 > 0 else 0)

    for p in produtos_ordenados:
        try:
            if p.get("atualizado_em"):
                dt = datetime.fromisoformat(p["atualizado_em"].replace("Z", "+00:00"))
                p["atualizado_em"] = dt.astimezone(timezone("America/Sao_Paulo")).strftime("%Y/%m/%d às %H:%M")
        except:
            p["atualizado_em"] = "Data inválida"

    return render_template("produtos_clickdivulga.html",
        produtos=produtos,
        resultados=resultados,
        produtos_ordenados=produtos_ordenados,
        lojas_unicas=sorted(lojas_disponiveis),
        palavras_disponiveis=sorted(palavras_disponiveis),
        pagina=pagina,
        inicio=inicio,
        fim=fim,
        total_paginas=total_paginas
    )

@app.route("/buscar-produto", methods=["POST"])
@verificar_login
def buscar_produto():
    import re, time, hashlib, requests, json
    from datetime import datetime

    uid = session["usuario"]["uid"]
    keyword = request.form.get("keyword", "").strip()
    url = request.form.get("url", "").strip()
    category_id = request.form.get("categoria") or ""
    entrada = url if url else keyword
    match = re.search(r"-i\.(\d+)\.(\d+)", entrada)
    usar_palavra_chave = not match

    termo_final = keyword if usar_palavra_chave else entrada
    termo_id = termo_final.lower().replace(" ", "-").replace(".", "").replace("/", "")

    termo_doc = db.collection("resultados_busca").document(uid).collection("termos").document(termo_id).get()
    if termo_doc.exists:
        dados = termo_doc.to_dict()
        atualizado_em = dados.get("atualizado_em")
        if atualizado_em:
            dt = datetime.fromisoformat(atualizado_em)
            if (datetime.now() - dt).total_seconds() < 43200:
                flash("⚠️ Você já buscou esse termo nas últimas 12 horas.", "warning")
                return redirect("/produtos")

    hoje = datetime.now().date().isoformat()
    contador_ref = db.collection("api_contador").document(uid)
    contador_doc = contador_ref.get()
    contador = contador_doc.to_dict() if contador_doc.exists else {}

    if contador.get("data") != hoje:
        contador = {"data": hoje, "uso_afiliado": 0, "uso_base": 0}
    if contador["uso_afiliado"] >= 25000:
        flash("🚫 Limite de uso diário atingido para hoje (25.000 requisições).", "error")
        return redirect("/produtos")

    doc = db.collection("api_shopee").document(uid).get()
    if not doc.exists:
        flash("⚠️ Cadastre sua API Shopee antes de buscar produtos.", "error")
        return redirect("/minha-api")

    cred = doc.to_dict()
    app_id = cred.get("app_id") or cred.get("client_id")
    app_secret = cred.get("app_secret") or cred.get("client_secret")
    if not app_id or not app_secret:
        flash("❌ App ID ou Secret não encontrados.", "error")
        return redirect("/minha-api")

    if usar_palavra_chave:
        if not keyword:
            flash("❌ Digite uma palavra-chave ou link válido.", "error")
            return redirect("/produtos")
        category_param = f'productCatId: {category_id},' if category_id else ''
        query_dict = {
            "query": f"""
            query {{
              productOfferV2(keyword: \"{keyword}\", {category_param} sortType: 2, page: 1, limit: 10) {{
                nodes {{
                  productName
                  imageUrl
                  priceMin
                  commissionRate
                  shopName
                  productLink
                  offerLink
                }}
              }}
            }}
            """
        }
    else:
        shop_id, item_id = match.groups()
        query_dict = {
            "query": f"""
            query {{
              productOfferV2(shopId: {shop_id}, itemId: {item_id}, page: 1, limit: 1) {{
                nodes {{
                  productName
                  imageUrl
                  priceMin
                  commissionRate
                  shopName
                  productLink
                  offerLink
                }}
              }}
            }}
            """
        }

    payload_str = json.dumps(query_dict, separators=(',', ':'))
    timestamp = str(int(time.time()) + 20)
    base_string = app_id + timestamp + payload_str + app_secret
    signature = hashlib.sha256(base_string.encode()).hexdigest()
    headers = {
        "Authorization": f"SHA256 Credential={app_id}, Signature={signature}, Timestamp={timestamp}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post("https://open-api.affiliate.shopee.com.br/graphql", headers=headers, data=payload_str)
        if response.status_code == 200:
            nodes = response.json().get("data", {}).get("productOfferV2", {}).get("nodes", [])
            produtos = []
            for p in nodes:
                preco = float(p.get("priceMin", 0))
                taxa_total = float(p.get("commissionRate") or 0) * 100
                taxa_loja = max(taxa_total - 3, 0)
                comissao_live = round(preco * ((10 + taxa_loja) / 100), 2)
                comissao_redes = round(preco * ((3 + taxa_loja) / 100), 2)
                produtos.append({
                    "titulo": p.get("productName"),
                    "imagem": p.get("imageUrl"),
                    "preco": preco,
                    "comissao": taxa_loja,
                    "comissao_live": comissao_live,
                    "comissao_redes": comissao_redes,
                    "loja": p.get("shopName"),
                    "link": p.get("offerLink") or p.get("productLink")
                })

            # 🔁 Verifica e remove excesso
            termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
            todos_termos = sorted([d for d in termos_ref], key=lambda x: x.to_dict().get("atualizado_em"))
            total_produtos = sum(len(d.to_dict().get("produtos", [])) for d in todos_termos)
            while total_produtos + len(produtos) > 400 and todos_termos:
                mais_antigo = todos_termos.pop(0)
                qtd = len(mais_antigo.to_dict().get("produtos", []))
                mais_antigo.reference.delete()
                total_produtos -= qtd

            db.collection("buscas").document(uid).collection("registros").add({
                "tipo": "produto",
                "termo": termo_final,
                "data": datetime.now().isoformat()
            })
            db.collection("resultados_busca").document(uid).collection("termos").document(termo_id).set({
                "tipo": "produto",
                "termo": termo_final,
                "atualizado_em": datetime.now().isoformat(),
                "produtos": produtos
            })

            contador["uso_afiliado"] += 1
            db.collection("api_contador").document(uid).set(contador)

            return redirect("/produtos")

        flash("❌ Erro ao buscar produto na Shopee", "error")
        return redirect("/produtos")

    except Exception as e:
        print("❌ Erro:", e)
        flash(f"Erro inesperado: {e}", "error")
        return redirect("/produtos")

@app.route("/buscar-loja", methods=["POST"])
@verificar_login
def buscar_loja():
    import re, time, hashlib, requests, json
    from datetime import datetime

    uid = session["usuario"]["uid"]
    loja_input = request.form.get("loja", "").strip()
    preco_min = request.form.get("preco_min", "").strip()
    preco_max = request.form.get("preco_max", "").strip()

    if not loja_input:
        flash("❌ Digite o nome ou link da loja.", "error")
        return redirect("/produtos")

    match = re.search(r'/shop/(\d+)', loja_input) or re.search(r'i\.(\d+)\.', loja_input)
    shop_id = match.group(1) if match else None
    if not shop_id:
        flash("⚠️ Link da loja inválido.", "error")
        return redirect("/produtos")

    termo_id = loja_input.lower().replace(" ", "-").replace(".", "").replace("/", "")

    termo_doc = db.collection("resultados_busca").document(uid).collection("termos").document(termo_id).get()
    if termo_doc.exists:
        dados = termo_doc.to_dict()
        atualizado_em = dados.get("atualizado_em")
        if atualizado_em:
            dt = datetime.fromisoformat(atualizado_em)
            if (datetime.now() - dt).total_seconds() < 43200:
                flash("⚠️ Essa loja já foi buscada nas últimas 12 horas.", "warning")
                return redirect("/produtos")

    hoje = datetime.now().date().isoformat()
    contador_ref = db.collection("api_contador").document(uid)
    contador_doc = contador_ref.get()
    contador = contador_doc.to_dict() if contador_doc.exists else {}

    if contador.get("data") != hoje:
        contador = {"data": hoje, "uso_afiliado": 0, "uso_base": 0}
    if contador["uso_afiliado"] >= 25000:
        flash("🚫 Limite de uso diário atingido para hoje (25.000 requisições).", "error")
        return redirect("/produtos")

    doc = db.collection("api_shopee").document(uid).get()
    if not doc.exists:
        flash("⚠️ Cadastre sua API Shopee antes de buscar.", "error")
        return redirect("/minha-api")

    cred = doc.to_dict()
    app_id = cred.get("app_id")
    app_secret = cred.get("app_secret")

    query_dict = {
        "query": f"""
        query {{
          productOfferV2(shopId: {shop_id}, sortType: 2, page: 1, limit: 10) {{
            nodes {{
              productName
              imageUrl
              priceMin
              commissionRate
              shopName
              productLink
              offerLink
            }}
          }}
        }}
        """
    }

    payload_str = json.dumps(query_dict, separators=(',', ':'))
    timestamp = str(int(time.time()) + 20)
    base_string = app_id + timestamp + payload_str + app_secret
    signature = hashlib.sha256(base_string.encode()).hexdigest()
    headers = {
        "Authorization": f"SHA256 Credential={app_id}, Signature={signature}, Timestamp={timestamp}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post("https://open-api.affiliate.shopee.com.br/graphql", headers=headers, data=payload_str)
        if response.status_code == 200:
            nodes = response.json().get("data", {}).get("productOfferV2", {}).get("nodes", [])
            produtos = []
            min_val = float(preco_min.replace(",", ".")) if preco_min else 0
            max_val = float(preco_max.replace(",", ".")) if preco_max else float("inf")

            for p in nodes:
                preco = float(p.get("priceMin", 0))
                if min_val <= preco <= max_val:
                    taxa_total = float(p.get("commissionRate") or 0) * 100
                    taxa_loja = max(taxa_total - 3, 0)
                    comissao_live = round(preco * ((10 + taxa_loja) / 100), 2)
                    comissao_redes = round(preco * ((3 + taxa_loja) / 100), 2)
                    produtos.append({
                        "titulo": p.get("productName"),
                        "imagem": p.get("imageUrl"),
                        "preco": preco,
                        "comissao": taxa_loja,
                        "comissao_live": comissao_live,
                        "comissao_redes": comissao_redes,
                        "loja": p.get("shopName"),
                        "link": p.get("offerLink") or p.get("productLink")
                    })

            # 🧹 Limita total de produtos salvos por afiliado (max: 400)
            termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
            todos_termos = sorted([
                (d.id, d.to_dict()) for d in termos_ref if d.to_dict().get("produtos")
            ], key=lambda x: x[1].get("atualizado_em"))

            total_atual = sum(len(t[1]["produtos"]) for t in todos_termos)
            while total_atual + len(produtos) > 400 and todos_termos:
                termo_antigo_id, termo_antigo = todos_termos.pop(0)
                db.collection("resultados_busca").document(uid).collection("termos").document(termo_antigo_id).delete()
                total_atual -= len(termo_antigo.get("produtos", []))

            db.collection("buscas").document(uid).collection("registros").add({
                "tipo": "loja",
                "termo": loja_input,
                "data": datetime.now().isoformat()
            })
            db.collection("resultados_busca").document(uid).collection("termos").document(termo_id).set({
                "tipo": "loja",
                "termo": loja_input,
                "atualizado_em": datetime.now().isoformat(),
                "produtos": produtos
            })

            contador["uso_afiliado"] += 1
            db.collection("api_contador").document(uid).set(contador)

            return redirect("/produtos")

        flash("❌ Erro ao buscar loja.", "error")
        return redirect("/produtos")

    except Exception as e:
        print("❌ Erro:", e)
        flash(f"Erro ao buscar loja: {e}", "error")
        return redirect("/produtos")

@app.route("/atualizar-buscas")
def atualizar_buscas():
    import time, hashlib, requests, json, re
    from datetime import datetime

    print("🔄 Iniciando atualização de buscas salvas...")

    db_firestore = db
    colecao_buscas = db_firestore.collection("buscas").stream()
    total_atualizadas = 0

    for doc_uid in colecao_buscas:
        uid = doc_uid.id
        print(f"👤 Atualizando buscas de: {uid}")

        registros_ref = db_firestore.collection("buscas").document(uid).collection("registros").stream()
        doc_api = db.collection("api_shopee").document(uid).get()
        if not doc_api.exists:
            print(f"⚠️ API não cadastrada para UID: {uid}")
            continue

        cred = doc_api.to_dict()
        app_id = cred.get("app_id") or cred.get("client_id")
        app_secret = cred.get("app_secret") or cred.get("client_secret")

        # 🔄 Limite de uso para base
        hoje = datetime.now().date().isoformat()
        contador_ref = db.collection("api_contador").document(uid)
        contador_doc = contador_ref.get()
        contador = contador_doc.to_dict() if contador_doc.exists else {}
        if contador.get("data") != hoje:
            contador = {"data": hoje, "uso_afiliado": 0, "uso_base": 0}

        if contador["uso_base"] >= 25000:
            print(f"🚫 UID {uid} atingiu limite de uso da base.")
            continue

        for r in registros_ref:
            dados = r.to_dict()
            tipo = dados.get("tipo")
            termo = dados.get("termo", "")
            termo_id = termo.lower().replace(" ", "-").replace(".", "").replace("/", "")

            print(f"🔁 Atualizando: {termo} ({tipo})")

            if tipo == "produto":
                query_dict = {
                    "query": f"""
                    query {{
                      productOfferV2(keyword: "{termo}", sortType: 2, page: 1, limit: 10) {{
                        nodes {{
                          productName
                          imageUrl
                          priceMin
                          commissionRate
                          shopName
                          productLink
                          offerLink
                        }}
                      }}
                    }}
                    """
                }
            elif tipo == "loja":
                shop_id_match = re.search(r'/shop/(\d+)', termo) or re.search(r'i\.(\d+)\.', termo)
                if not shop_id_match:
                    print(f"⚠️ Termo inválido para loja: {termo}")
                    continue
                shop_id = shop_id_match.group(1)
                query_dict = {
                    "query": f"""
                    query {{
                      productOfferV2(shopId: {shop_id}, sortType: 2, page: 1, limit: 10) {{
                        nodes {{
                          productName
                          imageUrl
                          priceMin
                          commissionRate
                          shopName
                          productLink
                          offerLink
                        }}
                      }}
                    }}
                    """
                }
            else:
                continue

            payload_str = json.dumps(query_dict, separators=(',', ':'))
            timestamp = str(int(time.time()) + 20)
            base_string = app_id + timestamp + payload_str + app_secret
            signature = hashlib.sha256(base_string.encode()).hexdigest()
            headers = {
                "Authorization": f"SHA256 Credential={app_id}, Signature={signature}, Timestamp={timestamp}",
                "Content-Type": "application/json"
            }

            try:
                response = requests.post("https://open-api.affiliate.shopee.com.br/graphql", headers=headers, data=payload_str)
                if response.status_code == 200:
                    nodes = response.json().get("data", {}).get("productOfferV2", {}).get("nodes", [])
                    produtos = []
                    for p in nodes:
                        preco = float(p.get("priceMin", 0))
                        taxa_total = float(p.get("commissionRate") or 0) * 100
                        taxa_loja = max(taxa_total - 3, 0)
                        comissao_live = round(preco * ((10 + taxa_loja) / 100), 2)
                        comissao_redes = round(preco * ((3 + taxa_loja) / 100), 2)

                        produtos.append({
                            "titulo": p.get("productName"),
                            "imagem": p.get("imageUrl"),
                            "preco": preco,
                            "comissao": taxa_loja,
                            "comissao_live": comissao_live,
                            "comissao_redes": comissao_redes,
                            "loja": p.get("shopName"),
                            "link": p.get("offerLink") or p.get("productLink")
                        })

                    # 🔐 Atualiza resultados
                    db_firestore.collection("resultados_busca").document(uid).collection("termos").document(termo_id).set({
                        "tipo": tipo,
                        "termo": termo,
                        "atualizado_em": datetime.now().isoformat(),
                        "produtos": produtos
                    })

                    # 📝 Log
                    db_firestore.collection("logs_atualizacao").document(uid).collection("execucoes").add({
                        "termo": termo,
                        "tipo": tipo,
                        "qtd_produtos": len(produtos),
                        "atualizado_em": datetime.now().isoformat()
                    })

                    contador["uso_base"] += 1
                    total_atualizadas += 1
                    if contador["uso_base"] >= 25000:
                        print(f"⛔ Limite de base atingido para {uid}. Parando...")
                        break
                else:
                    print(f"⚠️ Erro HTTP {response.status_code} ao buscar {termo}")

            except Exception as e:
                print(f"❌ Erro ao atualizar {termo}: {e}")

        db.collection("api_contador").document(uid).set(contador)

    print(f"✅ Atualização concluída. Total: {total_atualizadas}")
    return f"✅ Atualização concluída. Total: {total_atualizadas}", 200

@app.route("/excluir-produto", methods=["POST"])
@verificar_login
def excluir_produto():
    from datetime import datetime

    uid = session["usuario"]["uid"]
    termo_id = request.form.get("termo_id", "").strip()
    titulo_produto = request.form.get("titulo", "").strip()

    if not titulo_produto:
        flash("❌ Produto inválido para exclusão.", "error")
        return redirect("/produtos")

    # Se termo_id não for enviado corretamente, tenta identificar o termo correspondente
    if not termo_id:
        # Percorre todos os termos do usuário buscando pelo produto
        termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
        for doc in termos_ref:
            dados = doc.to_dict()
            produtos = dados.get("produtos", [])
            for p in produtos:
                if p.get("titulo") == titulo_produto:
                    termo_id = doc.id
                    break
            if termo_id:
                break

    if not termo_id:
        flash("❌ Não foi possível localizar o termo do produto.", "error")
        return redirect("/produtos")

    # Continua com a exclusão
    termo_ref = db.collection("resultados_busca").document(uid).collection("termos").document(termo_id)
    termo_doc = termo_ref.get()

    if not termo_doc.exists:
        flash("❌ Termo não encontrado.", "error")
        return redirect("/produtos")

    dados = termo_doc.to_dict()
    produtos = dados.get("produtos", [])
    produtos_filtrados = [p for p in produtos if p.get("titulo") != titulo_produto]

    termo_ref.update({
        "produtos": produtos_filtrados,
        "atualizado_em": datetime.now().isoformat()
    })

    # 🔐 Loga a exclusão
    db.collection("logs_exclusao").add({
        "uid": uid,
        "termo_id": termo_id,
        "titulo": titulo_produto,
        "data": datetime.now().isoformat()
    })

    flash("✅ Produto removido com sucesso!", "success")
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
