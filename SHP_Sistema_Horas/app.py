import os
import sqlite3
from datetime import date, datetime
from io import BytesIO
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from werkzeug.utils import secure_filename
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

app = Flask(__name__)
app.secret_key = os.environ.get("SHP_SECRET_KEY", "cambiar-esta-clave-en-produccion")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "shp.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
os.makedirs(UPLOAD_DIR, exist_ok=True)

DEFAULT_CATALOG = [
    ("Apoyo académico", "Académica", "Apoyo en actividades de aprendizaje y tutorías."),
    ("Actividad cultural", "Cultural", "Participación en actividades culturales universitarias."),
    ("Actividad deportiva", "Deportiva", "Participación en actividades deportivas."),
    ("Voluntariado", "Social", "Apoyo comunitario y actividades de voluntariado."),
    ("Representación estudiantil", "Institucional", "Participación en actividades de representación."),
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL CHECK(role IN ('Estudiante','Coordinador')),
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            category TEXT NOT NULL,
            target_hours REAL NOT NULL CHECK(target_hours > 0),
            period TEXT NOT NULL,
            UNIQUE(user_id, category, period)
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            activity_date TEXT DEFAULT '',
            location TEXT DEFAULT '',
            body TEXT NOT NULL,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            catalog_id INTEGER NOT NULL REFERENCES catalog(id),
            activity_date TEXT NOT NULL,
            hours REAL NOT NULL CHECK(hours > 0),
            description TEXT DEFAULT '',
            evidence TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pendiente'
                CHECK(status IN ('Pendiente','Validada','Rechazada')),
            coordinator_note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """)
        if db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 0:
            db.executemany("INSERT INTO catalog(name,category,description) VALUES(?,?,?)", DEFAULT_CATALOG)
        db.commit()

def current_user():
    if "user_id" not in session:
        return None
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE id=? AND active=1", (session["user_id"],)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def coordinator_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if user["role"] != "Coordinador":
            flash("Esta sección está disponible únicamente para el coordinador.", "warning")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapper

def period_now():
    today = date.today()
    semester = "I" if today.month <= 6 else "II"
    return f"{today.year}-{semester}"

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_progress(db, user_id, period):
    goals = db.execute("SELECT * FROM goals WHERE user_id=? AND period=? ORDER BY category", (user_id, period)).fetchall()
    result = []
    for goal in goals:
        hours = db.execute("""
            SELECT COALESCE(SUM(a.hours),0) FROM activities a
            JOIN catalog c ON c.id=a.catalog_id
            WHERE a.user_id=? AND c.category=? AND substr(a.activity_date,1,4)=?
        """, (user_id, goal["category"], period[:4])).fetchone()[0]
        percent = min(100, round((hours / goal["target_hours"]) * 100, 1)) if goal["target_hours"] else 0
        result.append({"category": goal["category"], "target": goal["target_hours"], "hours": round(hours, 2), "percent": percent})
    return result

@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "Estudiante")
        if not name or not email or "@" not in email:
            flash("Escribe tu nombre y un correo válido.", "danger")
            return render_template("login.html")
        # Validación del dominio institucional en el servidor.
        # Se compara el dominio completo para rechazar direcciones como usuario@uamv.edu.ni.otro.com.
        email_domain = email.rsplit("@", 1)[1]
        if email_domain != "uamv.edu.ni":
            flash("Debes ingresar con tu correo institucional terminado en @uamv.edu.ni.", "danger")
            return render_template("login.html")
        if role not in ("Estudiante", "Coordinador"):
            role = "Estudiante"
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user:
                db.execute("UPDATE users SET name=?, role=?, active=1 WHERE id=?", (name, role, user["id"]))
                user_id = user["id"]
            else:
                cur = db.execute("INSERT INTO users(name,email,role) VALUES(?,?,?)", (name, email, role))
                user_id = cur.lastrowid
            db.commit()
        session["user_id"] = user_id
        session["display_name"] = name
        session["display_role"] = role
        flash("Sesión de demostración iniciada. La autenticación UAM real debe configurarse antes de producción.", "info")
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    period = request.args.get("period", period_now())
    with get_db() as db:
        if user["role"] == "Coordinador":
            activities = db.execute("""
                SELECT a.*, u.name AS user_name, u.email, c.name AS activity_name, c.category
                FROM activities a JOIN users u ON u.id=a.user_id JOIN catalog c ON c.id=a.catalog_id
                ORDER BY a.created_at DESC LIMIT 8
            """).fetchall()
            pending = db.execute("SELECT COUNT(*) FROM activities WHERE 1=0").fetchone()[0]
            valid_hours = db.execute("SELECT COALESCE(SUM(hours),0) FROM activities").fetchone()[0]
            total_activities = db.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
            progress = []
        else:
            activities = db.execute("""
                SELECT a.*, c.name AS activity_name, c.category FROM activities a
                JOIN catalog c ON c.id=a.catalog_id WHERE a.user_id=?
                ORDER BY a.activity_date DESC, a.id DESC LIMIT 8
            """, (user["id"],)).fetchall()
            pending = db.execute("SELECT COUNT(*) FROM activities WHERE user_id=? AND 1=0", (user["id"],)).fetchone()[0]
            valid_hours = db.execute("SELECT COALESCE(SUM(hours),0) FROM activities WHERE user_id=?", (user["id"],)).fetchone()[0]
            total_activities = db.execute("SELECT COUNT(*) FROM activities WHERE user_id=?", (user["id"],)).fetchone()[0]
            progress = get_progress(db, user["id"], period)
        catalog_count = db.execute("SELECT COUNT(*) FROM catalog WHERE active=1").fetchone()[0]
    return render_template("dashboard.html", user=user, activities=activities, pending=pending,
                           valid_hours=round(valid_hours,2), total_activities=total_activities,
                           progress=progress, period=period, catalog_count=catalog_count)

@app.route("/activities/new", methods=["GET", "POST"])
@login_required
def new_activity():
    user = current_user()
    with get_db() as db:
        catalog = db.execute("SELECT * FROM catalog WHERE active=1 ORDER BY category,name").fetchall()
        if request.method == "POST":
            catalog_id = request.form.get("catalog_id", type=int)
            activity_date = request.form.get("activity_date", "")
            hours = request.form.get("hours", type=float)
            description = request.form.get("description", "").strip()
            evidence_name = ""
            file = request.files.get("evidence")
            if file and file.filename:
                if not allowed_file(file.filename):
                    flash("La evidencia debe ser PDF, PNG o JPG.", "danger")
                    return render_template("activity_form.html", catalog=catalog, today=date.today().isoformat())
                evidence_name = secure_filename(f"{user['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(UPLOAD_DIR, evidence_name))
            catalog_item = db.execute("SELECT * FROM catalog WHERE id=? AND active=1", (catalog_id,)).fetchone()
            if not catalog_item or not activity_date or not hours or hours <= 0:
                flash("Completa los campos obligatorios. Las horas deben ser mayores que cero.", "danger")
                return render_template("activity_form.html", catalog=catalog, today=date.today().isoformat())
            try:
                datetime.strptime(activity_date, "%Y-%m-%d")
            except ValueError:
                flash("La fecha no es válida.", "danger")
                return render_template("activity_form.html", catalog=catalog, today=date.today().isoformat())
            db.execute("""INSERT INTO activities(user_id,catalog_id,activity_date,hours,description,evidence,status,created_at)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (user["id"], catalog_id, activity_date, hours, description, evidence_name, "Pendiente", datetime.now().isoformat(timespec="seconds")))
            db.commit()
            flash("Actividad registrada correctamente.", "success")
            return redirect(url_for("history"))
    return render_template("activity_form.html", catalog=catalog, today=date.today().isoformat())

@app.route("/goals", methods=["GET", "POST"])
@login_required
def goals():
    user = current_user()
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        target = request.form.get("target_hours", type=float)
        period = request.form.get("period", "").strip()
        if not category or not target or target <= 0 or not period:
            flash("Completa todos los campos y usa una meta mayor que cero.", "danger")
            return redirect(url_for("goals"))
        with get_db() as db:
            db.execute("""INSERT INTO goals(user_id,category,target_hours,period) VALUES(?,?,?,?)
                          ON CONFLICT(user_id,category,period) DO UPDATE SET target_hours=excluded.target_hours""",
                       (user["id"], category, target, period))
            db.commit()
        flash("Meta guardada correctamente.", "success")
        return redirect(url_for("goals"))
    with get_db() as db:
        categories = db.execute("SELECT DISTINCT category FROM catalog WHERE active=1 ORDER BY category").fetchall()
        all_goals = db.execute("SELECT * FROM goals WHERE user_id=? ORDER BY period DESC, category", (user["id"],)).fetchall()
    return render_template("goals.html", categories=categories, goals=all_goals, period=period_now())

@app.route("/goals/<int:goal_id>/edit", methods=["POST"])
@login_required
def edit_goal(goal_id):
    user = current_user()
    target = request.form.get("target_hours", type=float)
    with get_db() as db:
        goal = db.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (goal_id, user["id"])).fetchone()
        if not goal:
            abort(404)
        if not target or target <= 0:
            flash("La meta debe ser mayor que cero.", "danger")
        else:
            db.execute("UPDATE goals SET target_hours=? WHERE id=?", (target, goal_id))
            db.commit()
            flash("Meta actualizada correctamente.", "success")
    return redirect(url_for("goals"))

@app.route("/goals/<int:goal_id>/delete", methods=["POST"])
@login_required
def delete_goal(goal_id):
    user = current_user()
    with get_db() as db:
        db.execute("DELETE FROM goals WHERE id=? AND user_id=?", (goal_id, user["id"]))
        db.commit()
    flash("Meta eliminada.", "success")
    return redirect(url_for("goals"))

@app.route("/announcements", methods=["GET", "POST"])
@login_required
def announcements():
    user = current_user()
    if request.method == "POST":
        if user["role"] != "Coordinador":
            abort(403)
        title = request.form.get("title", "").strip()
        activity_date = request.form.get("activity_date", "").strip()
        location = request.form.get("location", "").strip()
        body = request.form.get("body", "").strip()
        if not title or not body:
            flash("El título y la descripción son obligatorios.", "danger")
        else:
            with get_db() as db:
                db.execute("INSERT INTO announcements(title,activity_date,location,body,created_by,created_at) VALUES(?,?,?,?,?,?)",
                           (title, activity_date, location, body, user["id"], datetime.now().isoformat(timespec="seconds")))
                db.commit()
            flash("Anuncio publicado.", "success")
        return redirect(url_for("announcements"))
    with get_db() as db:
        items = db.execute("""SELECT an.*, u.name AS author FROM announcements an
                              LEFT JOIN users u ON u.id=an.created_by
                              ORDER BY CASE WHEN an.activity_date='' THEN 1 ELSE 0 END, an.activity_date, an.created_at DESC""").fetchall()
    return render_template("announcements.html", announcements=items, user=user)

@app.route("/announcements/<int:announcement_id>/delete", methods=["POST"])
@login_required
@coordinator_required
def delete_announcement(announcement_id):
    with get_db() as db:
        db.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))
        db.commit()
    flash("Anuncio eliminado.", "success")
    return redirect(url_for("announcements"))

@app.route("/history")
@login_required
def history():
    user = current_user()
    period = request.args.get("period", "")
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    with get_db() as db:
        query = """SELECT a.*, c.name AS activity_name, c.category, u.name AS user_name
                   FROM activities a JOIN catalog c ON c.id=a.catalog_id JOIN users u ON u.id=a.user_id"""
        clauses, params = [], []
        if user["role"] != "Coordinador":
            clauses.append("a.user_id=?"); params.append(user["id"])
        if period:
            clauses.append("substr(a.activity_date,1,7)=?"); params.append(period)
        if category:
            clauses.append("c.category=?"); params.append(category)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY a.activity_date DESC, a.id DESC"
        activities = db.execute(query, params).fetchall()
        categories = db.execute("SELECT DISTINCT category FROM catalog ORDER BY category").fetchall()
    return render_template("history.html", activities=activities, user=user, period=period, status=status, category=category, categories=categories)

@app.route("/review/<int:activity_id>", methods=["POST"])
@login_required
@coordinator_required
def review_activity(activity_id):
    status = request.form.get("status")
    note = request.form.get("coordinator_note", "").strip()
    if status not in ("Validada", "Rechazada", "Pendiente"):
        abort(400)
    with get_db() as db:
        activity = db.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
        if not activity:
            abort(404)
        db.execute("UPDATE activities SET status=?, coordinator_note=? WHERE id=?", (status, note, activity_id))
        db.commit()
    flash(f"Registro actualizado: {status.lower()}.", "success")
    return redirect(request.referrer or url_for("history"))

@app.route("/catalog", methods=["GET", "POST"])
@login_required
@coordinator_required
def catalog():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        if not name or not category:
            flash("Nombre y categoría son obligatorios.", "danger")
        else:
            with get_db() as db:
                db.execute("INSERT INTO catalog(name,category,description) VALUES(?,?,?)", (name,category,description))
                db.commit()
            flash("Actividad añadida al catálogo.", "success")
        return redirect(url_for("catalog"))
    with get_db() as db:
        items = db.execute("SELECT * FROM catalog ORDER BY active DESC, category, name").fetchall()
    return render_template("catalog.html", items=items)

@app.route("/catalog/<int:item_id>/toggle", methods=["POST"])
@login_required
@coordinator_required
def toggle_catalog(item_id):
    with get_db() as db:
        db.execute("UPDATE catalog SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (item_id,))
        db.commit()
    flash("Estado del elemento actualizado.", "success")
    return redirect(url_for("catalog"))

@app.route("/evidence/<int:activity_id>")
@login_required
def evidence(activity_id):
    user = current_user()
    with get_db() as db:
        row = db.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not row or not row["evidence"]:
        abort(404)
    if user["role"] != "Coordinador" and row["user_id"] != user["id"]:
        abort(403)
    path = os.path.join(UPLOAD_DIR, row["evidence"])
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=row["evidence"])

@app.route("/report.pdf")
@login_required
def report_pdf():
    user = current_user()
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    period = request.args.get("period", "")
    if period:
        start = start or (period + "-01")
        if not end:
            import calendar
            year, month = map(int, period.split("-"))
            end = f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    with get_db() as db:
        query = """SELECT a.activity_date, c.name, c.category, a.hours, u.name AS user_name, u.email
                   FROM activities a JOIN catalog c ON c.id=a.catalog_id JOIN users u ON u.id=a.user_id"""
        clauses, params = [], []
        if user["role"] != "Coordinador":
            clauses.append("a.user_id=?"); params.append(user["id"])
        if start:
            clauses.append("a.activity_date>=?"); params.append(start)
        if end:
            clauses.append("a.activity_date<=?"); params.append(end)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY a.activity_date DESC"
        rows = db.execute(query, params).fetchall()
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = [Paragraph("SHP — Sistema de Horas Personales", styles["Title"]),
             Paragraph("Reporte de actividades y progreso", styles["Heading2"]),
             Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Usuario: {user['name']} ({user['role']})", styles["Normal"]),
             Paragraph(f"Periodo consultado: {start or 'Inicio'} — {end or 'Actualidad'}", styles["Normal"]), Spacer(1, 14)]
    data = [["Fecha", "Usuario", "Actividad", "Categoría", "Horas"]]
    for r in rows:
        data.append([r["activity_date"], r["user_name"], r["name"], r["category"], str(r["hours"])])
    if len(data) == 1:
        data.append(["—", "Sin registros", "—", "—", "0"])
    table = Table(data, repeatRows=1, colWidths=[90, 145, 210, 120, 60])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#16345b")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Registros incluidos: {len(rows)} | Total de horas registradas: {sum(float(r['hours']) for r in rows):.2f}", styles["Normal"]))
    doc.build(story)
    output.seek(0)
    return send_file(output, mimetype="application/pdf", as_attachment=True, download_name="reporte_shp.pdf")

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="No tienes permiso para ver este recurso."), 403

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="No se encontró el recurso solicitado."), 404

init_db()

if __name__ == "__main__":
    app.run(debug=True)
