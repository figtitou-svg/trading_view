"""
main.py — Point d'entrée uvicorn (shim). L'app vit dans le package api/
(routeurs par domaine + agrégateur v2). Conserve `main:app` pour les
services systemd et les tests existants.

Lancer :
    uvicorn main:app --port 8000
"""
from api import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
