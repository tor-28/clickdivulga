# 🔧 Flask e dependências
from flask import Flask, render_template, request, redirect, url_for, session, flash

# 🔐 Firebase
import firebase_admin
from firebase_admin import credentials, auth, firestore

# 📦 Utilitários
import os
import base64
import tempfile
import json
import random
import re
import requests
import time
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup

# 🤖 Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ✅ Geração de descrições e benefícios (IA simplificada)
def gerar_descricao(titulo):
    frases = [
        f"Oportunidade única com {titulo.split()[0]}!",
        "Qualidade e economia em destaque.",
        "Destaque entre os mais vendidos.",
        "Toque de sofisticação no seu dia a dia.",
        "A escolha ideal para você!",
        f"{titulo.split()[0]} com ótima reputação."
    ]
    return random.choice(frases)

def gerar_beneficio(titulo):
    return random.choice([
        "Entrega rápida e bem avaliado na Shopee.",
        "Excelente custo-benefício.",
        "Favorito entre os compradores.",
        "Alta qualidade e ótimo acabamento.",
        "Marca com reputação excelente.",
        "Design moderno e funcional."
    ])

def gerar_beneficio_extra(titulo):
    return random.choice([
        "Estoque limitado, aproveite já!",
        "Recomendado por outros compradores.",
        "Combina praticidade e elegância.",
        "Ideal para presentear.",
        "Com avaliações incríveis!",
        "Garanta antes que acabe!"
    ])

# ✅ Função do agendador com logs de depuração
def verificar_envio_agendado():
    print("🔄 Verificando envios agendados...")

    usuarios_ref = db.collection("telegram_config").stream()
    hora_atual = datetime.now().hour

    for user_doc in usuarios_ref:
        uid = user_doc.id
        bots_ref = db.collection("telegram_config").document(uid).collection("bots").stream()

        for bot_doc in bots_ref:
            bot_id = bot_doc.id
            bot_config = bot_doc.to_dict()
            for grupo in ["2", "3"]:
                produtos = bot_config.get(f"produtos_grupo_{grupo}", [])
                print(f"\n🔍 UID: {uid} | Bot: {bot_id} | Grupo: {grupo}")
                print(f"➡️ Produtos configurados: {len(produtos)}")

                if not produtos:
                    print("🚫 Nenhum produto configurado para esse grupo. Pulando...")
                    continue

                try:
                    hora_inicio = int(bot_config.get(f"hora_inicio_grupo_{grupo}", 0))
                    hora_fim = int(bot_config.get(f"hora_fim_grupo_{grupo}", 23))
                    intervalo = bot_config.get(f"intervalo_grupo_{grupo}", "10 min").replace(" min", "")
                    intervalo = int(intervalo) if intervalo.isdigit() else 10
                    mensagens_por_minuto = int(bot_config.get(f"msg_grupo_{grupo}", 1))
                    ultimo_envio_str = bot_config.get(f"ultimo_envio_grupo_{grupo}")
                    ultimo_envio = datetime.fromisoformat(ultimo_envio_str) if ultimo_envio_str else None
                    agora = datetime.now()

                    print(f"🕓 Hora atual: {agora.hour} | Janela permitida: {hora_inicio} até {hora_fim}")
                    print(f"🔁 Intervalo entre envios: {intervalo} min")
                    print(f"📤 Último envio registrado: {ultimo_envio_str if ultimo_envio_str else 'N/A'}")

                    if not (hora_inicio <= agora.hour <= hora_fim):
                        print("⏱️ Fora do horário permitido. Pulando...")
                        continue
                    if ultimo_envio and (agora - ultimo_envio).total_seconds() < intervalo * 60:
                        print("⏳ Ainda dentro do intervalo de espera. Pulando...")
                        continue

                    dados_api = db.collection("api_shopee").document(uid).get().to_dict()
                    bot_token = dados_api.get(f"bot_token_{bot_id}")
                    grupo_id = dados_api.get(f"grupo_{grupo}_{bot_id}")

                    print(f"🔐 Token: {'✅' if bot_token else '❌'} | Grupo ID: {'✅' if grupo_id else '❌'}")

                    if not bot_token or not grupo_id:
                        print("❌ Bot token ou grupo_id ausente. Pulando envio.")
                        continue

                    termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
                    produtos_salvos = []
                    for doc in termos_ref:
                        termo = doc.to_dict()
                        produtos_salvos.extend(termo.get("produtos", []))

                    enviados = 0
                    for p in produtos_salvos:
                        if enviados >= mensagens_por_minuto:
                            break

                        titulo_salvo = (p.get("titulo") or "").strip().lower()
                        produtos_normalizados = [t.strip().lower() for t in produtos]
                        if titulo_salvo not in produtos_normalizados:
                            continue

                        logs_ref = db.collection("telegram_logs").document(uid).collection(bot_id)
                        enviados_recentemente = logs_ref.where("enviado_em", ">=", (agora - timedelta(hours=48)).isoformat())\
                            .where("titulo", "==", p.get("titulo", "")).stream()
                        if any(True for _ in enviados_recentemente):
                            print(f"⏭️ Produto '{p.get('titulo')}' já enviado nas últimas 48h para UID: {uid}")
                            continue

                        preco = p.get("preco", "0")
                        preco_de = p.get("preco_original") or "0"
                        link = p.get("link") or p.get("url") or "https://shopee.com.br"
                        imagem = p.get("imagem") or p.get("image")
                        if not imagem:
                            print(f"⚠️ Produto '{p.get('titulo')}' sem imagem. Pulando...")
                            continue

                        modo_texto = bot_config.get(f"modo_texto_grupo_{grupo}", "manual")
                        texto_manual = bot_config.get(f"texto_grupo_{grupo}", "").strip()

                        corpo = texto_manual if modo_texto == "manual" and texto_manual else (
                            f"✨ {gerar_descricao(p.get('titulo'))}\n"
                            f"✔️ {gerar_beneficio(p.get('titulo'))}\n"
                            f"✔️ {gerar_beneficio_extra(p.get('titulo'))}"
                        )

                        linha_preco_de = f"❌ R$ {preco_de}" if preco_de and preco_de != "0" else ""
                        legenda = f"🔥 {p.get('titulo')}\n"
                        if linha_preco_de:
                            legenda += f"\n{linha_preco_de}"
                        legenda += f"\n💵 R$ {preco}\n\n{corpo}\n\n🔗 {link}\n\n📦 Ofertas diárias Shopee para você aproveitar\n⚠️ Preço sujeito a alteração."

                        try:
                            response = requests.post(
                                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                                data={
                                    "chat_id": grupo_id,
                                    "photo": imagem,
                                    "caption": legenda,
                                    "parse_mode": "HTML"
                                }
                            )

                            if response.status_code == 200:
                                print(f"✅ Enviado com sucesso: {p.get('titulo')}")
                            else:
                                print(f"❌ Falha HTTP {response.status_code} ao enviar: {p.get('titulo')}")

                            enviados += 1
                            db.collection("telegram_logs").document(uid).collection(bot_id).add({
                                "enviado_em": agora.isoformat(),
                                "grupo": grupo,
                                "titulo": p.get("titulo"),
                                "legenda": legenda,
                                "status": f"Enviado agendado: {p.get('titulo')}"
                            })

                        except Exception as e:
                            print(f"❌ Erro ao enviar produto '{p.get('titulo')}': {e}")
                            db.collection("telegram_logs").document(uid).collection(bot_id).add({
                                "enviado_em": agora.isoformat(),
                                "grupo": grupo,
                                "titulo": p.get("titulo"),
                                "erro": str(e),
                                "status": f"Erro agendado: {p.get('titulo')}: {e}"
                            })

                    bot_doc.reference.set({f"ultimo_envio_grupo_{grupo}": agora.isoformat()}, merge=True)
                except Exception as erro:
                    print(f"❌ Erro geral no grupo {grupo} do bot {bot_id}: {erro}")

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

# ✅ Agendador de envio automático (a cada minuto)
scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
scheduler.add_job(verificar_envio_agendado, 'interval', minutes=1)
try:
    scheduler.start()
    print("✅ Scheduler iniciado com sucesso.")
except Exception as e:
    print(f"❌ Erro ao iniciar o scheduler: {e}")

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

@app.route("/forcar-envio", methods=["GET"])
def forcar_envio():
    print("\n🚨 ROTA DE ENVIO FORÇADO ACIONADA (IGNORANDO FILTROS)")

    try:
        usuarios_ref = db.collection("telegram_config").stream()
        agora = datetime.now()

        for user_doc in usuarios_ref:
            uid = user_doc.id
            print(f"👤 Verificando UID: {uid}")
            bots_ref = db.collection("telegram_config").document(uid).collection("bots").stream()

            for bot_doc in bots_ref:
                bot_id = bot_doc.id
                bot_config = bot_doc.to_dict()
                print(f"🤖 Bot ID: {bot_id} | Config: {bot_config is not None}")

                produtos = bot_config.get("produtos_grupo_2", [])
                print(f"➡️ Produtos selecionados: {len(produtos)}")
                if not produtos:
                    print("⚠️ Nenhum produto selecionado. Pulando...")
                    continue

                dados_api = db.collection("api_shopee").document(uid).get().to_dict()
                if not dados_api:
                    print("❌ Dados da API Shopee não encontrados. Pulando...")
                    continue
                bot_token = dados_api.get(f"bot_token_{bot_id}")
                grupo_id = dados_api.get(f"grupo_2_{bot_id}")

                print(f"🔐 Bot Token: {'SIM' if bot_token else 'NÃO'} | Grupo ID: {'SIM' if grupo_id else 'NÃO'}")
                if not bot_token or not grupo_id:
                    print("❌ Token ou Grupo ID ausente. Pulando...")
                    continue

                termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
                produtos_salvos = []
                for doc in termos_ref:
                    termo = doc.to_dict()
                    lista = termo.get("produtos", [])
                    produtos_salvos.extend(lista)
                print(f"🛍️ Produtos salvos no Firestore: {len(produtos_salvos)}")

                enviados = 0
                for p in produtos_salvos:
                    if p.get("titulo") not in produtos:
                        continue

                    titulo = p.get("titulo", "")
                    imagem = p.get("imagem") or p.get("image")
                    preco = p.get("preco", "0")
                    link = p.get("link") or p.get("url") or "https://shopee.com.br"

                    if not imagem:
                        print(f"⚠️ Produto '{titulo}' sem imagem. Pulando...")
                        continue

                    legenda = f"🔥 {titulo}\n💵 R$ {preco}\n🔗 {link}"

                    print(f"➡️ Tentando enviar: {titulo}")
                    try:
                        response = requests.post(
                            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                            data={
                                "chat_id": grupo_id,
                                "photo": imagem,
                                "caption": legenda,
                                "parse_mode": "HTML"
                            }
                        )
                        print(f"✅ Enviado: {titulo} | Status Code: {response.status_code}")
                    except Exception as e:
                        print(f"❌ ERRO AO ENVIAR: {e}")
        return "✅ Teste de envio manual executado"
    except Exception as erro:
        print(f"🔥 ERRO GERAL: {erro}")
        return "❌ Erro ao executar envio manual"

@app.route("/teste-agendador")
def teste_agendador():
    try:
        print("🚨 ROTA DE TESTE MANUAL DO AGENDADOR ACIONADA")
        verificar_envio_agendado()
        return "✅ Agendador executado manualmente com sucesso!", 200
    except Exception as e:
        print(f"❌ Erro ao executar agendador manualmente: {e}")
        return f"Erro: {e}", 500

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

    # 🔹 LINKS GERADOS HOJE (usando timestamp real)
    hoje = datetime.combine(datetime.today(), datetime.min.time())
    links_hoje = db.collection("links_encurtados") \
        .where("uid", "==", uid) \
        .where("criado_em", ">=", hoje) \
        .stream()
    total_links_hoje = sum(1 for _ in links_hoje)

    # 🔹 CLIQUES NO MÊS (limitado para evitar travamento)
    inicio_mes = datetime.now().replace(day=1)
    cliques_mes = sum(1 for _ in db.collection("logs_cliques")
                      .where("uid", "==", uid)
                      .where("data", ">=", inicio_mes)
                      .limit(5000)  # proteção de memória
                      .stream())

    # 🔹 PRODUTO MAIS CLICADO
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

    # 🔹 GRUPO MAIS CLICADO
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

    # 🔹 LINKS RECENTES
    links_recentes = db.collection("links_encurtados") \
        .where("uid", "==", uid) \
        .order_by("criado_em", direction=firestore.Query.DESCENDING) \
        .limit(4).stream()

    links_formatados = []
    for doc in links_recentes:
        dados = doc.to_dict()
        links_formatados.append({
            "slug": dados.get("slug"),
            "titulo": dados.get("titulo", "Sem título"),
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

@app.route('/buscar-meli', methods=['GET', 'POST'])
def buscar_meli():
    print("✅ Acessando rota /buscar-meli")
    print("📦 Sessão atual:", session)

    if 'usuario' not in session or 'uid' not in session['usuario']:
        print("⛔ Sessão inválida ou UID ausente. Redirecionando para login.")
        return redirect('/login')

    uid = session['usuario']['uid']
    print(f"👤 UID identificado: {uid}")

    if request.method == 'POST':
        url = request.form.get('url_meli')
        print(f"🔗 Link recebido: {url}")

        if not url:
            flash('Link não informado.', 'erro')
            return render_template('produtos_meli.html', produto=None)

        try:
            # 🔄 Corrigido para usar GET + endpoint /extrair-meli
            vps_url = os.getenv('VPS_MELI_ENDPOINT', 'http://89.117.32.226:5005/extrair-meli')
            print(f"🌐 Fazendo requisição para a VPS: {vps_url}")

            # Envia via GET com parâmetro na URL
            response = requests.get(vps_url, params={'link': url}, timeout=30)

            if response.status_code == 200:
                dados = response.json()
                print(f"✅ Produto retornado pela VPS: {dados}")
                return render_template('produtos_meli.html', produto=dados)
            else:
                print(f"⚠️ Erro ao buscar produto. Status code: {response.status_code}")
                flash('Erro ao buscar produto. Verifique o link.', 'erro')
                return render_template('produtos_meli.html', produto=None)

        except Exception as e:
            print(f"❌ Erro durante requisição à VPS: {str(e)}")
            flash('Erro interno ao buscar o produto.', 'erro')
            return render_template('produtos_meli.html', produto=None)

    return render_template('produtos_meli.html', produto=None)


@app.route('/enviar-meli', methods=['POST'])
def enviar_meli():
    print("✅ Rota /enviar-meli acessada")
    print("📦 Sessão atual:", session)

    # 🔐 Validação de sessão moderna (ClickDivulga)
    if 'usuario' not in session or 'uid' not in session['usuario']:
        print("⛔ Sessão inválida ou UID ausente. Redirecionando para login.")
        return redirect('/login')

    uid = session['usuario']['uid']
    print(f"👤 UID identificado: {uid}")

    # 📦 Dados do formulário
    titulo = request.form.get('titulo')
    imagem = request.form.get('imagem')
    preco = request.form.get('preco')
    link = request.form.get('link')

    print(f"📝 Dados recebidos: título={titulo}, imagem={imagem}, preco={preco}, link={link}")

    if not all([titulo, imagem, preco, link]):
        flash('Todos os campos são obrigatórios.', 'erro')
        print("⚠️ Campos obrigatórios ausentes.")
        return redirect('/buscar-meli')

    try:
        # 🔍 Buscar dados do Firestore (bot do afiliado)
        config_ref = db.reference(f'usuarios/{uid}/bots/bot1')
        config = config_ref.get()

        if not config or 'token' not in config or 'grupo1' not in config:
            flash('Bot do Telegram não configurado corretamente.', 'erro')
            print(f"⚠️ Bot ou grupo não encontrado para UID: {uid}")
            return redirect('/buscar-meli')

        bot_token = config['token']
        chat_id = config['grupo1']

        # ✨ Mensagem para o grupo 1 (figurinhas/templates)
        mensagem = f"""
🟡 *{titulo}*

💰 De: ~R$ XXX~
🔥 Por: *R$ {preco}*

🔗 [Compre agora]({link})
"""

        telegram_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        payload = {
            'chat_id': chat_id,
            'photo': imagem,
            'caption': mensagem,
            'parse_mode': 'Markdown'
        }

        r = requests.post(telegram_url, data=payload)

        if r.status_code == 200:
            flash('Produto enviado com sucesso para o Telegram!', 'sucesso')
            print("✅ Mensagem enviada com sucesso.")
        else:
            flash(f'Erro ao enviar para o Telegram: {r.text}', 'erro')
            print(f"❌ Erro do Telegram: {r.text}")

    except Exception as e:
        flash(f'Erro ao enviar para o Telegram: {str(e)}', 'erro')
        print(f"❌ Exceção ao enviar: {str(e)}")

    return redirect('/buscar-meli')

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

@app.route("/config-bot/<bot_id>", methods=["POST"])
@verificar_login
def salvar_config_bot(bot_id):
    from datetime import datetime

    uid = session["usuario"]["uid"]
    grupo = request.form.get("grupo")

    if grupo not in ["2", "3"]:
        flash("❌ Grupo inválido.", "error")
        return redirect(f"/config-bot/{bot_id}")

    bot_config_ref = db.collection("telegram_config").document(uid).collection("bots").document(bot_id)
    bot_config_doc = bot_config_ref.get()
    config_data = bot_config_doc.to_dict() if bot_config_doc.exists else {}

    config_data[f"lojas_grupo_{grupo}"] = request.form.getlist(f"lojas_grupo_{grupo}")
    config_data[f"palavra_grupo_{grupo}"] = request.form.get(f"palavra_grupo_{grupo}", "")
    config_data[f"produtos_grupo_{grupo}"] = request.form.getlist(f"produtos_grupo_{grupo}")
    config_data[f"msg_grupo_{grupo}"] = int(request.form.get(f"msg_grupo_{grupo}", 1))
    config_data[f"intervalo_grupo_{grupo}"] = request.form.get(f"intervalo_grupo_{grupo}", "10 min")
    config_data[f"hora_inicio_grupo_{grupo}"] = int(request.form.get(f"hora_inicio_grupo_{grupo}", 0))
    config_data[f"hora_fim_grupo_{grupo}"] = int(request.form.get(f"hora_fim_grupo_{grupo}", 23))
    config_data[f"modo_texto_grupo_{grupo}"] = request.form.get(f"modo_texto_grupo_{grupo}", "manual")
    config_data[f"texto_grupo_{grupo}"] = request.form.get(f"texto_grupo_{grupo}", "")
    config_data["atualizado_em"] = datetime.now().isoformat()

    print(">> CONFIG DATA SALVA:", config_data)
    bot_config_ref.set(config_data, merge=True)

    flash(f"✅ Configuração do Grupo {grupo} salva com sucesso!", "success")
    return redirect(f"/config-bot/{bot_id}")

@app.route("/config-bot")
@verificar_login
def redirecionar_config_bot():
    return redirect("/config-bot/1")

@app.route("/config-bot/<bot_id>", methods=["GET"])
@verificar_login
def config_bot(bot_id):
    from google.cloud import firestore

    uid = session["usuario"]["uid"]
    print(f"📥 Acessando painel de configuração do bot {bot_id} para UID: {uid}")

    # Carrega dados da API do usuário (nome do bot)
    doc_ref = db.collection("api_shopee").document(uid)
    doc = doc_ref.get()
    dados = doc.to_dict() if doc.exists else {}

    bot_nome = dados.get(f"bot_nome_{bot_id}", f"Bot {bot_id}")
    bot_config_ref = db.collection("telegram_config").document(uid).collection("bots").document(bot_id)
    bot_config_doc = bot_config_ref.get()
    bot_config = bot_config_doc.to_dict() if bot_config_doc.exists else {}

    # 🧠 Lógica para ignorar filtros ao carregar pela primeira vez
    acao = request.args.get("acao")
    grupo_aplicando = request.args.get("grupo")

    if not acao or not grupo_aplicando:
        for g in ["2", "3"]:
            print(f"🔄 Resetando filtros visuais do grupo {g}")
            bot_config[f"lojas_grupo_{g}"] = []
            bot_config[f"palavra_grupo_{g}"] = ""

    # 📦 Carrega produtos disponíveis
    lojas = set()
    produtos_disponiveis = []
    termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
    for doc in termos_ref:
        termo = doc.to_dict()
        for p in termo.get("produtos", []):
            produtos_disponiveis.append(p)
            if p.get("loja"):
                lojas.add(p["loja"])

    print(f"🛍️ {len(produtos_disponiveis)} produtos carregados para exibição")
    print(f"🏪 Lojas únicas detectadas: {sorted(lojas)}")

    # Logs de envio (últimos 10)
    logs_ref = db.collection("telegram_logs").document(uid).collection(bot_id).order_by("enviado_em", direction=firestore.Query.DESCENDING).limit(10)
    logs = [log.to_dict() for log in logs_ref.stream()]

    return render_template("config-telegram.html",
        bot_id=bot_id,
        nome_bot=bot_nome,
        bot_config=bot_config,
        lojas_disponiveis=sorted(lojas),
        produtos_disponiveis=produtos_disponiveis,
        logs=logs
    )

@app.route("/enviar-bot/<bot_id>")
@verificar_login
def enviar_bot(bot_id):
    from datetime import datetime
    import requests
    import random

    uid = session["usuario"]["uid"]
    grupo = request.args.get("grupo")

    if grupo not in ["2", "3"]:
        flash("❌ Grupo inválido para envio manual.", "error")
        return redirect(f"/config-bot/{bot_id}")

    dados_api = db.collection("api_shopee").document(uid).get().to_dict()
    bot_token = dados_api.get(f"bot_token_{bot_id}")
    grupo_id = dados_api.get(f"grupo_{grupo}_{bot_id}")

    if not bot_token or not grupo_id:
        flash("❌ Token do bot ou grupo não configurado.", "error")
        return redirect(f"/config-bot/{bot_id}")

    bot_config_ref = db.collection("telegram_config").document(uid).collection("bots").document(bot_id)
    bot_config = bot_config_ref.get().to_dict() if bot_config_ref.get().exists else {}

    produtos = bot_config.get(f"produtos_grupo_{grupo}", [])
    modo_texto = bot_config.get(f"modo_texto_grupo_{grupo}", "manual")
    texto_manual = bot_config.get(f"texto_grupo_{grupo}", "").strip()

    if not produtos:
        flash("❌ Nenhum produto selecionado para esse grupo.", "error")
        return redirect(f"/config-bot/{bot_id}")

    termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
    produtos_salvos = []
    for doc in termos_ref:
        termo = doc.to_dict()
        produtos_salvos.extend(termo.get("produtos", []))

    for p in produtos_salvos:
        if p.get("titulo") not in produtos:
            continue

        titulo = p.get("titulo", "")
        preco = p.get("preco", "0")
        preco_de = p.get("preco_original") or "0"
        link = p.get("link") or p.get("url") or "https://shopee.com.br"
        imagem = p.get("imagem") or p.get("image")

        if not imagem:
            continue

        corpo = ""
        if modo_texto == "manual" and texto_manual:
            corpo = texto_manual.strip()
        else:
            descricao = f"✨ {gerar_descricao(titulo)}"
            vantagem1 = f"✔️ {gerar_beneficio(titulo)}"
            vantagem2 = f"✔️ {gerar_beneficio_extra(titulo)}"
            corpo = f"{descricao}\n{vantagem1}\n{vantagem2}"

        linha_preco_de = f"❌ R$ {preco_de}" if preco_de and preco_de != "0" else ""

        legenda = f"🔥 {titulo}\n"
        if linha_preco_de:
            legenda += f"\n{linha_preco_de}"
        legenda += f"\n💵 R$ {preco}\n\n{corpo}\n\n🔗 {link}\n\n📦 Ofertas diárias Shopee para você aproveitar\n⚠️ Preço sujeito a alteração."

        try:
            send_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
            payload = {
                "chat_id": grupo_id,
                "photo": imagem,
                "caption": legenda,
                "parse_mode": "HTML"
            }
            requests.post(send_url, data=payload)

            db.collection("telegram_logs").document(uid).collection(bot_id).add({
                "enviado_em": datetime.now().isoformat(),
                "grupo": grupo,
                "status": f"Enviado: {titulo}"
            })

        except Exception as e:
            db.collection("telegram_logs").document(uid).collection(bot_id).add({
                "enviado_em": datetime.now().isoformat(),
                "grupo": grupo,
                "status": f"Erro ao enviar {titulo}: {e}"
            })

    flash(f"✅ Mensagens enviadas com sucesso para o Grupo {grupo}!", "success")
    return redirect(f"/config-bot/{bot_id}")


def gerar_descricao(titulo):
    frases = [
        f"Aproveite uma oportunidade única com este produto incrível.",
        f"Pensado para quem valoriza qualidade e praticidade.",
        f"Ideal para seu dia a dia com conforto e estilo.",
        f"Oferta exclusiva para transformar sua rotina.",
        f"Um toque especial para quem quer mais.",
        f"{titulo.split()[0]} com excelente custo-benefício."
    ]
    return random.choice(frases)

def gerar_beneficio(titulo):
    frases = [
        "Produto com excelente reputação e entrega rápida.",
        "Altamente recomendado por milhares de compradores.",
        "Avaliações positivas e ótimo desempenho na Shopee.",
        "Popular entre os mais vendidos da categoria.",
        "Ótimo custo-benefício para seu bolso.",
        "Marca confiável e reconhecida pelos consumidores."
    ]
    return random.choice(frases)

def gerar_beneficio_extra(titulo):
    frases = [
        "Estoque limitado com preço promocional.",
        "Design moderno e funcional para o dia a dia.",
        "Produto bem embalado e com envio rápido.",
        "Ideal para presentear ou uso próprio.",
        "Combina praticidade com ótimo acabamento.",
        "Aproveite agora, antes que acabe!"
    ]
    return random.choice(frases)

@app.route("/enviar-produto/<bot_id>")
@verificar_login
def enviar_produto_individual(bot_id):
    from datetime import datetime
    import requests
    import random

    uid = session["usuario"]["uid"]
    grupo = request.args.get("grupo")
    titulo_param = request.args.get("titulo", "").strip()

    if grupo not in ["2", "3"] or not titulo_param:
        flash("❌ Parâmetros inválidos.", "error")
        return redirect(f"/config-bot/{bot_id}")

    dados_api = db.collection("api_shopee").document(uid).get().to_dict()
    bot_token = dados_api.get(f"bot_token_{bot_id}")
    grupo_id = dados_api.get(f"grupo_{grupo}_{bot_id}")

    if not bot_token or not grupo_id:
        flash("❌ Token do bot ou grupo não configurado.", "error")
        return redirect(f"/config-bot/{bot_id}")

    bot_config_ref = db.collection("telegram_config").document(uid).collection("bots").document(bot_id)
    bot_config = bot_config_ref.get().to_dict() if bot_config_ref.get().exists else {}

    modo_texto = bot_config.get(f"modo_texto_grupo_{grupo}", "manual")
    texto_manual = bot_config.get(f"texto_grupo_{grupo}", "").strip()

    # Buscar o produto específico com base no título
    produto = None
    termos_ref = db.collection("resultados_busca").document(uid).collection("termos").stream()
    for doc in termos_ref:
        termo = doc.to_dict()
        for p in termo.get("produtos", []):
            if p.get("titulo") == titulo_param:
                produto = p
                break
        if produto:
            break

    if not produto:
        flash("❌ Produto não encontrado.", "error")
        return redirect(f"/config-bot/{bot_id}")

    titulo = produto.get("titulo", "")
    preco = produto.get("preco", "0")
    preco_de = produto.get("preco_original") or "0"
    link = produto.get("link") or produto.get("url") or "https://shopee.com.br"
    imagem = produto.get("imagem") or produto.get("image")

    if not imagem:
        flash("❌ Produto sem imagem.", "error")
        return redirect(f"/config-bot/{bot_id}")

    if modo_texto == "manual" and texto_manual:
        corpo = texto_manual.strip()
    else:
        descricao = f"✨ {gerar_descricao(titulo)}"
        vantagem1 = f"✔️ {gerar_beneficio(titulo)}"
        vantagem2 = f"✔️ {gerar_beneficio_extra(titulo)}"
        corpo = f"{descricao}\n{vantagem1}\n{vantagem2}"

    linha_preco_de = f"❌ R$ {preco_de}" if preco_de and preco_de != "0" else ""

    legenda = f"🔥 {titulo}\n"
    if linha_preco_de:
        legenda += f"\n{linha_preco_de}"
    legenda += f"\n💵 R$ {preco}\n\n{corpo}\n\n🔗 {link}\n\n📦 Ofertas diárias Shopee para você aproveitar\n⚠️ Preço sujeito a alteração."

    try:
        send_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        payload = {
            "chat_id": grupo_id,
            "photo": imagem,
            "caption": legenda,
            "parse_mode": "HTML"
        }
        requests.post(send_url, data=payload)

        db.collection("telegram_logs").document(uid).collection(bot_id).add({
            "enviado_em": datetime.now().isoformat(),
            "grupo": grupo,
            "status": f"Enviado individual: {titulo}"
        })

        flash(f"✅ Produto enviado com sucesso para o Grupo {grupo}!", "success")
    except Exception as e:
        db.collection("telegram_logs").document(uid).collection(bot_id).add({
            "enviado_em": datetime.now().isoformat(),
            "grupo": grupo,
            "status": f"Erro ao enviar individual {titulo}: {e}"
        })
        flash("❌ Erro ao enviar o produto individual.", "error")

    return redirect(f"/config-bot/{bot_id}")
