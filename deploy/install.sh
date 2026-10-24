#!/usr/bin/env bash
# ============================================================
# install.sh — Installation du bot sur un serveur Ubuntu
# (Oracle Cloud Always Free ou n'importe quel VPS).
#
# À lancer DEPUIS le dossier du projet sur le serveur :
#     bash deploy/install.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
USER_NAME="$(whoami)"

echo "── Installation dans : $PROJECT_DIR (utilisateur : $USER_NAME)"

# 1. Vérifier la présence du .env (contient token Telegram, config…)
if [ ! -f .env ]; then
    echo "❌ Fichier .env introuvable !"
    echo "   Copie-le depuis ton PC (voir docs/deployment.md)."
    exit 1
fi

# 2. Dépendances système
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip

# 3. Environnement virtuel Python + dépendances du projet
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "✅ Python et dépendances installés"

# 4. Services systemd (démarrage auto + redémarrage en cas de crash)
for svc in trading-forex trading-dashboard trading-copytrading; do
    sed "s|__DIR__|$PROJECT_DIR|g; s|__USER__|$USER_NAME|g" \
        "deploy/$svc.service" | sudo tee "/etc/systemd/system/$svc.service" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now trading-forex trading-dashboard trading-copytrading
echo "✅ Services démarrés"

echo
echo "── État des services ──────────────────────────────────"
systemctl --no-pager --lines=0 status trading-forex trading-dashboard trading-copytrading || true
echo
echo "🎉 Terminé !"
echo "   Logs du bot   : sudo journalctl -u trading-forex -f"
echo "   Dashboard     : http://<ip-tailscale-du-serveur>:8000/dashboard"
