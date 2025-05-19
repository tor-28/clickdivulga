from flask import Flask, render_template, request, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, auth, firestore
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clickdivulga-super-secret")

# Inicializar Firebase
if not firebase_admin._apps:
    cred_path = os.getenv("FIREBASE_CREDENTIALS", "firebase_key.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Middleware para verificar login ativo
def verificar_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# Rota inicial → redireciona para login
@app.route("/")
def index():
    return redirect(url_for("login"))

# Rota de login
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
        except:
            return "Token inválido ou expirado", 401
    return render_template("login_clickdivulga.html")

# Painel principal
@app.route("/painel")
@verificar_login
def painel():
    return render_template("meus_links_clickdivulga.html")

# Criar novo link
@app.route("/criar-link")
@verificar_login
def criar_link():
    return render_template("criar_link_clickdivulga.html")

# Estatísticas
@app.route("/estatisticas")
@verificar_login
def estatisticas():
    return render_template("estatisticas_clickdivulga.html")

# Telegram Automático
@app.route("/telegram")
@verificar_login
def telegram():
    return render_template("telegram_clickdivulga.html")

# Instagram Automático
@app.route("/instagram")
@verificar_login
def instagram():
    return render_template("instagram_clickdivulga.html")

# Painel Administrativo
@app.route("/admin")
@verificar_login
def admin():
    return render_template("admin_clickdivulga.html")

# Logout
@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))

# Iniciar servidor local
if __name__ == "__main__":
    app.run(debug=True)
