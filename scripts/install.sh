# install.sh - Script d'installation pour Raspberry Pi Zero 2 W

set -e

echo "==================================="
echo "Installation de Billard Tracker"
echo "==================================="

# Mise à jour du système
echo "Mise à jour du système..."
sudo apt update
sudo apt upgrade -y

# Installation des dépendances système
echo "Installation des dépendances..."
sudo apt install -y python3 python3-pip python3-venv git nginx avahi-daemon sqlite3

# Création de l'utilisateur et du répertoire
echo "Configuration de l'environnement..."
cd /home/pi
mkdir -p billiard-tracker
cd billiard-tracker

# Création de l'environnement virtuel Python
echo "Création de l'environnement Python..."
python3 -m venv venv
source venv/bin/activate

# Installation des dépendances Python
echo "Installation des dépendances Python..."
cat > requirements.txt << EOF
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
python-multipart==0.0.6
aiofiles==23.2.1
EOF

pip install -r requirements.txt

# Copie des fichiers de l'application
echo "Copie des fichiers de l'application..."
mkdir -p backend frontend data scripts

# Création du service systemd
echo "Configuration du service systemd..."
sudo tee /etc/systemd/system/billiard-tracker.service > /dev/null << EOF
[Unit]
Description=Billiard Tracker API
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/billiard-tracker
Environment="PATH=/home/pi/billiard-tracker/venv/bin"
ExecStart=/home/pi/billiard-tracker/venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Configuration de Nginx
echo "Configuration de Nginx..."
sudo tee /etc/nginx/sites-available/billiard-tracker > /dev/null << 'EOF'
server {
    listen 80;
    server_name billiard.local;
    
    root /home/pi/billiard-tracker/frontend;
    index index.html;
    
    # Frontend PWA
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }
    
    # API Backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # Manifest et Service Worker
    location /manifest.json {
        add_header Cache-Control "no-cache";
        add_header Content-Type "application/manifest+json";
    }
    
    location /service-worker.js {
        add_header Cache-Control "no-cache";
        add_header Content-Type "application/javascript";
    }
}
EOF

# Activer le site
sudo ln -sf /etc/nginx/sites-available/billiard-tracker /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# Configuration mDNS (Avahi)
echo "Configuration mDNS..."
sudo tee /etc/avahi/services/billiard.service > /dev/null << EOF
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name>Billiard Tracker</name>
  <service>
    <type>_http._tcp</type>
    <port>80</port>
    <txt-record>path=/</txt-record>
  </service>
</service-group>
EOF

# Script de sauvegarde automatique
echo "Configuration des sauvegardes..."
cat > /home/pi/billiard-tracker/scripts/backup.sh << 'EOF'
#!/bin/bash
# Script de sauvegarde quotidienne

BACKUP_DIR="/home/pi/billiard-tracker/data/backups"
DB_FILE="/home/pi/billiard-tracker/data/billiard.db"
DATE=$(date +%Y-%m-%d)
BACKUP_FILE="$BACKUP_DIR/billiard-$DATE.db"

# Créer le répertoire de sauvegarde s'il n'existe pas
mkdir -p $BACKUP_DIR

# Copier la base de données
if [ -f "$DB_FILE" ]; then
    cp $DB_FILE $BACKUP_FILE
    echo "Sauvegarde créée: $BACKUP_FILE"
    
    # Supprimer les sauvegardes de plus de 30 jours
    find $BACKUP_DIR -name "billiard-*.db" -mtime +30 -delete
    echo "Anciennes sauvegardes supprimées"
else
    echo "Base de données non trouvée!"
fi
EOF

chmod +x /home/pi/billiard-tracker/scripts/backup.sh

# Ajouter la tâche cron pour la sauvegarde quotidienne
(crontab -l 2>/dev/null; echo "0 2 * * * /home/pi/billiard-tracker/scripts/backup.sh") | crontab -

# Activation et démarrage des services
echo "Activation des services..."
sudo systemctl daemon-reload
sudo systemctl enable billiard-tracker
sudo systemctl start billiard-tracker
sudo systemctl restart avahi-daemon

# Vérification de l'installation
echo ""
echo "==================================="
echo "Installation terminée!"
echo "==================================="
echo ""
echo "L'application est accessible à:"
echo "  http://billiard.local"
echo "  http://$(hostname -I | cut -d' ' -f1)"
echo ""
echo "Status des services:"
sudo systemctl status billiard-tracker --no-pager
echo ""
echo "Pour voir les logs:"
echo "  sudo journalctl -u billiard-tracker -f"
echo ""