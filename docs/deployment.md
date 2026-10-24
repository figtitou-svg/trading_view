# Deployment / Déploiement

## English

The bots are designed to run 24/7 on a small Linux server (any VPS, or a free-tier cloud VM). Everything is simulated: no broker credentials are needed.

1. Copy the project to the server and create `.env` from `.env.example` (Telegram token and FRED key are optional).
2. From the project directory on the server, run `bash deploy/install.sh`. It installs Python and the dependencies in `.venv`, renders the systemd units (`__DIR__` and `__USER__` placeholders) and starts three services:
   - `trading-forex` — forex paper-trading runner (`python -m forex.paper.runner`)
   - `trading-dashboard` — web dashboard on port 8000 (`uvicorn main:app`)
   - `trading-copytrading` — simulated copy-trading mirror (`python -m copytrading.runner`)
3. Optional weekly self-tuning: render `deploy/trading-forex-learning.service` and `deploy/trading-forex-learning.timer` the same way as `install.sh` does (`sed "s|__DIR__|$PWD|g; s|__USER__|$USER|g"`), copy them to `/etc/systemd/system/`, then `sudo systemctl enable --now trading-forex-learning.timer` (runs Sundays 18:00 UTC).
4. Logs: `sudo journalctl -u trading-forex -f`.

**The dashboard has no authentication.** Do not expose port 8000 to the internet: reach it through a private network such as Tailscale (`http://<tailscale-ip>:8000/dashboard`) or an SSH tunnel.

## Français

Les bots sont prévus pour tourner 24h/24 sur un petit serveur Linux (n'importe quel VPS, ou une VM cloud gratuite). Tout est simulé : aucun identifiant de broker n'est nécessaire.

1. Copie le projet sur le serveur et crée `.env` à partir de `.env.example` (le jeton Telegram et la clé FRED sont facultatifs).
2. Depuis le dossier du projet sur le serveur, lance `bash deploy/install.sh`. Il installe Python et les dépendances dans `.venv`, génère les unités systemd (placeholders `__DIR__` et `__USER__`) et démarre trois services :
   - `trading-forex` — runner de paper trading forex (`python -m forex.paper.runner`)
   - `trading-dashboard` — dashboard web sur le port 8000 (`uvicorn main:app`)
   - `trading-copytrading` — miroir de copy trading simulé (`python -m copytrading.runner`)
3. Auto-réglage hebdomadaire (facultatif) : génère `deploy/trading-forex-learning.service` et `deploy/trading-forex-learning.timer` comme le fait `install.sh` (`sed "s|__DIR__|$PWD|g; s|__USER__|$USER|g"`), copie-les dans `/etc/systemd/system/`, puis `sudo systemctl enable --now trading-forex-learning.timer` (dimanche 18:00 UTC).
4. Journaux : `sudo journalctl -u trading-forex -f`.

**Le dashboard n'a pas d'authentification.** N'expose pas le port 8000 sur Internet : passe par un réseau privé comme Tailscale (`http://<ip-tailscale>:8000/dashboard`) ou un tunnel SSH.
