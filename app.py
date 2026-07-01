# -*- coding: utf-8 -*-
"""Painel de validacao de emails da Casa da Midia. Flask + SQLite.
Validacao em background com barra de progresso. Persistencia em DATA_DIR."""
import os, csv, uuid, sqlite3, datetime, threading
from flask import Flask, request, redirect, url_for, send_file, abort, jsonify, render_template_string
import validator

DATA_DIR = os.environ.get("DATA_DIR", "/data")
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
DB_PATH = os.path.join(DATA_DIR, "panel.db")
os.makedirs(JOBS_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

BR_TZ = datetime.timezone(datetime.timedelta(hours=-3))  # Brasilia (sem horario de verao desde 2019)
def agora_br():
    return datetime.datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")

def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        cols = [r[1] for r in c.execute("PRAGMA table_info(jobs)").fetchall()]
        if cols and "status" not in cols:   # schema antigo -> recria (so tinha jobs de teste)
            c.execute("DROP TABLE jobs")
        c.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, created_at TEXT, arquivos TEXT, status TEXT,
            total INTEGER DEFAULT 0, done INTEGER DEFAULT 0,
            enviar INTEGER DEFAULT 0, arriscado INTEGER DEFAULT 0, invalido INTEGER DEFAULT 0,
            smtp INTEGER DEFAULT 0, erro TEXT DEFAULT '')""")
init_db()

# ---------- worker em background ----------
def run_job(jid, emails, smtp):
    try:
        def progress(done, total):
            with db() as c:
                c.execute("UPDATE jobs SET done=?, total=? WHERE id=?", (done, total, jid))
        recs, smtp_used = validator.validate(emails, smtp=smtp, progress=progress)
        buckets = {"enviar": [], "arriscado": [], "invalido": []}
        for r in recs: buckets[r["status"]].append(r)
        jdir = os.path.join(JOBS_DIR, jid); os.makedirs(jdir, exist_ok=True)
        for b, rows in buckets.items():
            with open(os.path.join(jdir, f"{b}.csv"), "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh); w.writerow(["email","status","motivo","mx","score"])
                for r in rows: w.writerow([r["email"],r["status"],r.get("motivo",""),r.get("mx",""),r.get("score",0)])
        with db() as c:
            c.execute("""UPDATE jobs SET status='concluido', total=?, done=?,
                         enviar=?, arriscado=?, invalido=?, smtp=? WHERE id=?""",
                      (len(recs), len(recs), len(buckets["enviar"]), len(buckets["arriscado"]),
                       len(buckets["invalido"]), int(smtp_used), jid))
    except Exception as e:
        with db() as c:
            c.execute("UPDATE jobs SET status='erro', erro=? WHERE id=?", (str(e)[:500], jid))

# ---------- HTML ----------
PAGE = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Validador de Emails | Casa da Midia</title>
<style>
:root{--orange:#FF5A1F;--ink:#111;--bg:#F4F1EA;--card:#fff;--mut:#6b7280}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,Arial,sans-serif;background:var(--bg);color:var(--ink)}
.wrap{max-width:920px;margin:0 auto;padding:28px 18px}
h1{font-size:24px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 22px}
.card{background:var(--card);border:1px solid #e7e3da;border-radius:14px;padding:20px;margin-bottom:18px}
.btn{background:var(--ink);color:#fff;border:0;border-radius:10px;padding:11px 16px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
.btn.orange{background:var(--orange)}
input[type=file]{padding:10px;border:1px dashed #c9c3b6;border-radius:10px;width:100%;background:#fafafa}
label.chk{display:flex;gap:8px;align-items:center;color:var(--mut);font-size:14px;margin:12px 0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eee}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600}
.b-enviar{background:#e7f7ec;color:#1a7f37}.b-arriscado{background:#fef6e0;color:#9a6700}.b-invalido{background:#fdeaea;color:#b42318}
.kpi{display:flex;gap:14px;flex-wrap:wrap}.kpi .box{flex:1;min-width:120px;background:#fafafa;border:1px solid #eee;border-radius:10px;padding:14px}
.kpi .n{font-size:26px;font-weight:700}.kpi .l{color:var(--mut);font-size:13px}
a{color:var(--orange)}.muted{color:var(--mut);font-size:13px}
.bar{height:22px;background:#eee;border-radius:999px;overflow:hidden}
.bar>i{display:block;height:100%;width:0;background:var(--orange);transition:width .4s}
</style></head><body><div class=wrap>
<h1>Validador de Emails</h1><p class=sub>Casa da Midia &middot; suba a lista, baixe os emails bons, com historico salvo.</p>
{{ body|safe }}
</div></body></html>"""

HOME = """
<div class=card>
  <form method=post action="{{ url_for('upload') }}" enctype=multipart/form-data>
    <input type=file name=files accept=".csv,.xlsx" multiple required>
    <label class=chk><input type=checkbox name=smtp value=1> Verificar caixa por SMTP (mais lento, mais preciso)</label>
    <button class="btn orange" type=submit>Validar lista</button>
    <span class=muted>CSV ou Excel. A coluna de email e detectada sozinha.</span>
  </form>
</div>
<div class=card>
  <h3 style="margin:0 0 12px">Historico</h3>
  {% if jobs %}
  <table><tr><th>Data</th><th>Arquivos</th><th>Status</th><th>Total</th><th>Enviar</th><th>Arriscado</th><th>Invalido</th><th></th></tr>
  {% for j in jobs %}
  <tr><td>{{ j['created_at'] }}</td><td class=muted>{{ j['arquivos'] }}</td>
    <td>{% if j['status']=='concluido' %}ok{% elif j['status']=='erro' %}<span style="color:#b42318">erro</span>{% else %}processando{% endif %}</td>
    <td>{{ j['total'] }}</td>
    <td><span class="badge b-enviar">{{ j['enviar'] }}</span></td>
    <td><span class="badge b-arriscado">{{ j['arriscado'] }}</span></td>
    <td><span class="badge b-invalido">{{ j['invalido'] }}</span></td>
    <td><a href="{{ url_for('job', job_id=j['id']) }}">abrir</a></td></tr>
  {% endfor %}</table>
  {% else %}<p class=muted>Nenhuma validacao ainda.</p>{% endif %}
</div>"""

PROGRESS = """
<p><a href="{{ url_for('home') }}">&larr; voltar</a></p>
<div class=card>
  <h3 style="margin:0 0 6px">Validando...</h3>
  <p class=muted id=lbl>Preparando...</p>
  <div class=bar><i id=fill></i></div>
  <p class=muted style="margin-top:10px">Pode deixar essa aba aberta. Listas grandes com SMTP demoram.</p>
</div>
<script>
const jid="{{ j['id'] }}";
async function poll(){
  try{
    const r=await fetch("{{ url_for('status', job_id=j['id']) }}");
    const d=await r.json();
    if(d.status==='concluido'||d.status==='erro'){location.reload();return;}
    const pct=d.total>0?Math.floor(d.done*100/d.total):0;
    document.getElementById('fill').style.width=pct+'%';
    document.getElementById('lbl').textContent=pct+'%  ('+d.done+' de '+d.total+')';
  }catch(e){}
  setTimeout(poll,1500);
}
poll();
</script>"""

JOB = """
<p><a href="{{ url_for('home') }}">&larr; voltar</a></p>
<div class=card>
  <h3 style="margin:0 0 14px">Resultado &middot; {{ j['created_at'] }}</h3>
  <p class=muted>Arquivos: {{ j['arquivos'] }} {% if j['smtp'] %}&middot; SMTP: ativo{% else %}&middot; SMTP: nao usado{% endif %}</p>
  {% if j['status']=='erro' %}<p style="color:#b42318">Erro: {{ j['erro'] }}</p>{% endif %}
  <div class=kpi>
    <div class=box><div class="n">{{ j['total'] }}</div><div class=l>Total</div></div>
    <div class=box><div class="n" style="color:#1a7f37">{{ j['enviar'] }}</div><div class=l>Enviar</div></div>
    <div class=box><div class="n" style="color:#9a6700">{{ j['arriscado'] }}</div><div class=l>Arriscado</div></div>
    <div class=box><div class="n" style="color:#b42318">{{ j['invalido'] }}</div><div class=l>Invalido</div></div>
  </div>
  <p style="margin-top:18px">
    <a class="btn orange" href="{{ url_for('download', job_id=j['id'], bucket='enviar') }}">Baixar emails bons (enviar)</a>
    <a class="btn" href="{{ url_for('download', job_id=j['id'], bucket='arriscado') }}">Arriscado</a>
    <a class="btn" href="{{ url_for('download', job_id=j['id'], bucket='invalido') }}">Invalido</a>
  </p>
  <p class=muted>Mande os de "enviar". "Arriscado" = role/catch-all/nao verificado. "Invalido" = nao envie.</p>
</div>"""

def render(body, **kw):
    return render_template_string(PAGE, body=render_template_string(body, **kw))

@app.route("/")
def home():
    with db() as c:
        jobs = c.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT 100").fetchall()
    return render(HOME, jobs=jobs)

@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    if not files: return redirect(url_for("home"))
    smtp = request.form.get("smtp") == "1"
    emails, names = [], []
    for f in files:
        if not f.filename: continue
        names.append(f.filename)
        emails += validator.extract_emails_from_bytes(f.filename, f.read())
    jid = uuid.uuid4().hex[:12]
    with db() as c:
        c.execute("INSERT INTO jobs(id,created_at,arquivos,status,total,done,smtp) VALUES(?,?,?,?,?,?,?)",
                  (jid, agora_br(),
                   ", ".join(names)[:300], "processando", len(emails), 0, int(smtp)))
    threading.Thread(target=run_job, args=(jid, emails, smtp), daemon=True).start()
    return redirect(url_for("job", job_id=jid))

@app.route("/job/<job_id>")
def job(job_id):
    with db() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j: abort(404)
    if j["status"] == "processando":
        return render(PROGRESS, j=j)
    return render(JOB, j=j)

@app.route("/job/<job_id>/status")
def status(job_id):
    with db() as c:
        j = c.execute("SELECT status,total,done FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j: abort(404)
    return jsonify({"status": j["status"], "total": j["total"], "done": j["done"]})

@app.route("/download/<job_id>/<bucket>")
def download(job_id, bucket):
    if bucket not in ("enviar","arriscado","invalido"): abort(404)
    path = os.path.join(JOBS_DIR, job_id, f"{bucket}.csv")
    if not os.path.exists(path): abort(404)
    return send_file(path, as_attachment=True, download_name=f"{bucket}-{job_id}.csv")

@app.route("/health")
def health(): return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
