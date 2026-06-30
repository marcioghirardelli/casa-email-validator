# Casa da Midia - Validador de Emails (painel web)

Painel para subir listas (CSV/Excel), validar emails e baixar so os bons, com historico salvo.

## Stack
Flask + gunicorn. Validacao: sintaxe, descartaveis, role-based, MX (dnspython) e SMTP/catch-all opcional.
Persistencia em SQLite + arquivos em `DATA_DIR` (volume `/data` no Easypanel).

## Rodar local
```
pip install -r requirements.txt
DATA_DIR=./data python app.py
# abre em http://localhost:3000
```

## Deploy (Easypanel)
- Build: Nixpacks (detecta requirements.txt + Procfile).
- Porta interna: 3000.
- Volume persistente montado em `/data`.
- Variavel `DATA_DIR=/data`.
- Acesso protegido por Basic Auth no proprio Easypanel.

## Baldes do resultado
- **enviar**: pode mandar (sintaxe + dominio com servidor de email).
- **arriscado**: role-based / catch-all / nao verificado.
- **invalido**: nao envie (sintaxe ruim, dominio morto, descartavel).
