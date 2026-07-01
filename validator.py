# -*- coding: utf-8 -*-
"""Nucleo de validacao de emails (portavel). MX via dnspython, SMTP/catch-all opcional."""
import re, csv, io, socket, random, string, time
from collections import defaultdict

try:
    import dns.resolver
    _HAS_DNS = True
except Exception:
    _HAS_DNS = False

EMAIL_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
                      r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")

ROLE_LOCALPARTS = {
    "info","contato","contact","sac","vendas","comercial","financeiro","admin","administrativo",
    "suporte","support","atendimento","faleconosco","marketing","rh","compras","noreply","no-reply",
    "naoresponda","postmaster","webmaster","abuse","hello","ola","ouvidoria","cobranca","diretoria",
}
DISPOSABLE_DOMAINS = {
    "mailinator.com","yopmail.com","guerrillamail.com","10minutemail.com","tempmail.com","temp-mail.org",
    "trashmail.com","throwawaymail.com","getnada.com","sharklasers.com","grr.la","dispostable.com",
    "maildrop.cc","fakeinbox.com","mailnesia.com","mohmal.com","emailondeck.com","tempr.email",
    "spamgourmet.com","mintemail.com","mailcatch.com","tempinbox.com","33mail.com","mvrht.net",
}

# ---------- leitura de planilhas ----------
def extract_emails_from_bytes(filename, data):
    name = filename.lower()
    rows = []
    if name.endswith(".xlsx"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            for r in ws.iter_rows(values_only=True):
                rows.append(["" if c is None else str(c) for c in r])
        except Exception:
            return []
    else:  # csv
        text = None
        for enc in ("utf-8-sig","latin-1"):
            try: text = data.decode(enc); break
            except Exception: continue
        if text is None: return []
        delim = ";" if text[:4096].count(";") > text[:4096].count(",") else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return _emails_from_rows(rows)

def _emails_from_rows(rows):
    if not rows: return []
    header = rows[0]
    col = None
    for i,h in enumerate(header):
        if re.search(r"e-?mail", str(h).strip().lower()): col = i; break
    body = rows[1:]
    if col is None:
        ncol = max(len(r) for r in rows)
        best,bc = 0,-1
        for i in range(ncol):
            c = sum(1 for r in rows if i < len(r) and "@" in str(r[i]))
            if c > bc: best,bc = i,c
        col = best
        if "@" in str(header[col]) if col < len(header) else False: body = rows
    out = []
    for r in body:
        if col < len(r):
            e = str(r[col]).strip().lower()
            if e: out.append(e)
    return out

# ---------- MX ----------
_mx_cache = {}
def mx_records(domain):
    if domain in _mx_cache: return _mx_cache[domain]
    hosts = []
    if _HAS_DNS:
        try:
            ans = dns.resolver.resolve(domain, "MX", lifetime=6)
            hosts = [str(r.exchange).rstrip(".") for r in sorted(ans, key=lambda x: x.preference)]
        except Exception:
            hosts = []
    if not hosts:
        try:
            socket.gethostbyname(domain); hosts = [domain]  # fallback A
        except Exception:
            hosts = []
    _mx_cache[domain] = hosts
    return hosts

# ---------- SMTP ----------
def port25_open():
    try:
        s = socket.create_connection(("gmail-smtp-in.l.google.com", 25), timeout=8); s.close(); return True
    except Exception:
        return False

def smtp_probe(domain, addresses, mail_from):
    import smtplib
    result = {a: "unknown" for a in addresses}
    hosts = mx_records(domain)
    if not hosts: return result, False
    try:
        srv = smtplib.SMTP(timeout=12); srv.connect(hosts[0], 25)
        srv.helo(mail_from.split("@")[-1]); srv.mail(mail_from)
        rnd = "".join(random.choice(string.ascii_lowercase) for _ in range(12)) + "@" + domain
        code,_ = srv.rcpt(rnd)
        if code in (250,251):
            srv.quit(); return result, True  # catch-all
        for a in addresses:
            try:
                code,_ = srv.rcpt(a)
                result[a] = "valid" if code in (250,251) else ("invalid" if 500<=code<600 else "unknown")
            except Exception:
                result[a] = "unknown"
            time.sleep(0.25)
        srv.quit()
    except Exception:
        pass
    return result, False

# ---------- pipeline ----------
def validate(emails, smtp=False, mail_from="validador@casadamidia.com", progress=None):
    seen, uniq = set(), []
    for e in emails:
        if e and e not in seen: seen.add(e); uniq.append(e)
    pre = {}
    by_domain = defaultdict(list)
    smtp_on = bool(smtp) and port25_open()
    total = len(uniq) + (0 if not smtp_on else 0)  # ajustado abaixo p/ fase SMTP
    done = 0
    def tick():
        nonlocal done
        done += 1
        if progress and (done % 5 == 0 or done == total):
            try: progress(done, total)
            except Exception: pass
    for email in uniq:
        rec = {"email": email, "status": None, "motivo": "", "mx": "", "score": 0}
        if not EMAIL_RE.match(email):
            rec.update(status="invalido", motivo="sintaxe"); pre[email]=rec; tick(); continue
        local, domain = email.split("@",1)
        if domain in DISPOSABLE_DOMAINS:
            rec.update(status="invalido", motivo="descartavel"); pre[email]=rec; tick(); continue
        hosts = mx_records(domain)
        if not hosts:
            rec.update(status="invalido", motivo="sem-servidor-de-email"); pre[email]=rec; tick(); continue
        rec["mx"] = "mx"
        if local in ROLE_LOCALPARTS:
            rec["motivo"]="role-based"; rec["score"]=50
        pre[email]=rec; by_domain[domain].append(email); tick()

    smtp_used = False
    if smtp_on:
        smtp_used = True
        doms = [d for d in by_domain if any(pre[a]["status"] is None for a in by_domain[d])]
        total = len(uniq) + len(doms)
        if progress:
            try: progress(done, total)
            except Exception: pass
        for d in doms:
            pend = [a for a in by_domain[d] if pre[a]["status"] is None]
            res, catch = smtp_probe(d, pend, mail_from)
            for a in pend:
                if catch: pre[a]["smtp"]="catch-all"; pre[a]["motivo"]=(pre[a]["motivo"]+"+catch-all").strip("+")
                else: pre[a]["smtp"]=res.get(a,"unknown")
            done += 1
            if progress and (done % 3 == 0 or done == total):
                try: progress(done, total)
                except Exception: pass

    for email, rec in pre.items():
        if rec["status"]: continue
        motivo, smtp_r = rec.get("motivo",""), rec.get("smtp")
        if smtp_r == "invalid":
            rec.update(status="invalido", motivo="smtp-rejeitou", score=100)
        elif smtp_r == "valid" and "role" not in motivo:
            rec.update(status="enviar", motivo="smtp-confirmado", score=0)
        elif motivo.startswith("role") or "catch-all" in motivo or smtp_r == "catch-all":
            # role-based ou dominio catch-all: incerteza real
            rec.update(status="arriscado", motivo=(motivo or "catch-all"),
                       score=max(rec.get("score",0),40))
        else:
            # inclui smtp 'unknown' (nao deu pra verificar): trata como mx-ok, nao pune
            note = "mx-ok (caixa nao verificada)" if smtp_r is None else "mx-ok (smtp nao conclusivo)"
            rec.update(status="enviar", motivo=note, score=10)
    if progress:
        try: progress(max(total,1), max(total,1))
        except Exception: pass
    return list(pre.values()), smtp_used
