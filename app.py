import os
import random
import hashlib
import datetime
import requests
from flask import Flask, render_template, request, redirect, url_for, session, abort
from flask_sqlalchemy import SQLAlchemy

# ---------------- CONFIG ----------------
API_KEY = os.environ.get("NEWS_API_KEY")   # set this on Render (and locally for testing)
SECRET_KEY = os.environ.get("SECRET_KEY", "change_this_secret_for_prod")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")  # 👈 set admin email in Render

TOP_NEWS_URL = "https://newsapi.org/v2/top-headlines"
SEARCH_URL = "https://newsapi.org/v2/everything"

app = Flask(__name__)
app.secret_key = SECRET_KEY

# DB
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///news.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- MODELS ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))
    interests = db.Column(db.String(255))  # "technology,ai,sports"

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    article_title = db.Column(db.String(300))
    time = db.Column(db.DateTime, default=datetime.datetime.utcnow)

# ---------------- HELPERS ----------------
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _safe_articles(items):
    cleaned = []
    seen = set()
    for a in items or []:
        url = a.get("url")
        title = a.get("title")
        if not url or not title: 
            continue
        if url in seen: 
            continue
        seen.add(url)
        cleaned.append(a)
    return cleaned

def fetch_top_headlines(country="us", page_size=12, page=1):
    if not API_KEY:
        return []
    params = {"apiKey": API_KEY, "country": country, "pageSize": page_size, "page": page}
    try:
        r = requests.get(TOP_NEWS_URL, params=params, timeout=15)
        data = r.json()
        if data.get("status") == "ok":
            return _safe_articles(data.get("articles", []))
    except Exception as e:
        print("Top headlines error:", e)
    return []

def fetch_news_for_topic(topic, page_size=10, page=1):
    if not API_KEY:
        return []
    params = {"apiKey": API_KEY, "q": topic, "language": "en", "sortBy": "publishedAt", "pageSize": page_size, "page": page}
    try:
        r = requests.get(SEARCH_URL, params=params, timeout=15)
        data = r.json()
        if data.get("status") == "ok":
            return _safe_articles(data.get("articles", []))
    except Exception as e:
        print(f"Search error for '{topic}':", e)
    return []

def merge_shuffle_limit(list_of_lists, limit=18):
    merged = []
    for lst in list_of_lists:
        merged.extend(lst)
    random.shuffle(merged)
    return merged[:limit]

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    user = None
    articles = []
    personalized = False
    used_topics = []

    if "user_id" in session:
        user = db.session.get(User, session["user_id"])

    if user and user.interests:
        topics = [t.strip() for t in user.interests.split(",") if t.strip()]
        if not topics:
            topics = ["technology", "science", "sports"]
        used_topics = topics[:5]
        topic_feeds = []
        for t in used_topics:
            page = random.randint(1, 3)
            topic_feeds.append(fetch_news_for_topic(t, page_size=10, page=page))
        articles = merge_shuffle_limit(topic_feeds, limit=18)
        personalized = True
    else:
        page = random.randint(1, 3)
        articles = fetch_top_headlines(country="us", page_size=12, page=page)
        personalized = False

    return render_template("index.html", articles=articles, user=user, personalized=personalized, topics=used_topics)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = hash_password(request.form["password"])
        interests = request.form.get("interests", "").strip()

        if User.query.filter_by(email=email).first():
            return "Email already registered. Try logging in."
        new_user = User(name=name, email=email, password_hash=password, interests=interests)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = hash_password(request.form["password"])
        user = User.query.filter_by(email=email, password_hash=password).first()
        if user:
            session["user_id"] = user.id
            session["email"] = user.email  # store email for admin check
            return redirect(url_for("home"))
        return "Invalid credentials"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("email", None)
    return redirect(url_for("home"))

@app.route("/article/<string:title>")
def article(title):
    if "user_id" not in session:
        return redirect(url_for("login"))
    db.session.add(Activity(user_id=session["user_id"], article_title=title))
    db.session.commit()
    return f"<h1>{title}</h1><p>Open source link from the card to read full story.</p>"

# ---------------- ADMIN ROUTES ----------------
def admin_required():
    """Check if logged-in user is admin"""
    if session.get("email") != ADMIN_EMAIL:
        abort(403)

@app.route("/admin/users")
def show_users():
    admin_required()
    users = User.query.all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/usercount")
def user_count():
    admin_required()
    count = User.query.count()
    return render_template("admin_usercount.html", count=count)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0")
