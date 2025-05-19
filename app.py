
from flask import Flask, render_template, request, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, auth, firestore
from functools import wraps
import os
import base64
import tempfile
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "clickdivulga-default-secret")

# Inicializar Firebase com base64 da key
firebase_b64 = os.getenv("FIREBASE_KEY_B64")
if firebase_b64:
    decoded = base64.b64decode(firebase_b64)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
        temp_file.write(decoded)
        temp_file.flush()
        cred = credentials.Certificate(temp_file.name)
        firebase_admin.initialize_app(cred)
else:
    raise Exception("FIREBASE_KEY_B64 não configurado no ambiente")

db = firestore.client()

# Middleware de verificação de login
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
        except:
            return "Token inválido ou expirado", 401
    return render_template("login_clickdivulga.html")

@app.route("/painel")
@verificar_login
def painel():
    return render_template("meus_links_clickdivulga.html")

@app.route("/criar-link")
@verificar_login
def criar_link():
    return render_template("criar_link_clickdivulga.html")

@app.route("/estatisticas")
@verificar_login
def estatisticas():
    return render_template("estatisticas_clickdivulga.html")

@app.route("/telegram")
@verificar_login
def telegram():
    return render_template("telegram_clickdivulga.html")

@app.route("/instagram")
@verificar_login
def instagram():
    return render_template("instagram_clickdivulga.html")

@app.route("/admin")
@verificar_login
def admin():
    return render_template("admin_clickdivulga.html")

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
