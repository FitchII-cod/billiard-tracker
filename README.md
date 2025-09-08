# Billiard Tracker - Système de suivi ELO pour billard

## 📋 Description

Billiard Tracker est une application web PWA (Progressive Web App) conçue pour gérer et suivre les parties de billard dans un environnement de bureau. Elle fonctionne sur un Raspberry Pi Zero 2 W et offre un système de classement ELO sophistiqué avec gestion des équipes.

### Fonctionnalités principales

- **Formats multiples** : Support 1v1, 2v2, 3v3, et 1v2
- **Système ELO avancé** : 
  - Calcul séparé par format
  - Pondération selon les boules restantes
  - Protection anti-farm avec K effectif adaptatif
- **Gestion des équipes** : Création automatique et persistance des duos en 2v2
- **Head-to-Head** : Statistiques de confrontation en temps réel
- **PWA mobile-first** : Interface optimisée pour smartphones
- **Mode offline** : File d'attente pour synchronisation ultérieure
- **Administration** : Interface protégée par PIN pour les réglages

## 🔧 Prérequis matériels

- **Raspberry Pi Zero 2 W** (ou supérieur)
- Carte micro-SD 16 Go minimum (Class 10 / A1)
- Alimentation 5V 2.5A
- Connexion au réseau Wi-Fi du bureau

## 📦 Installation sur Raspberry Pi

### 1. Préparation du Raspberry Pi

```bash
# Flasher Raspberry Pi OS Lite (64-bit) sur la carte SD
# Activer SSH et configurer le Wi-Fi via Raspberry Pi Imager

# Se connecter en SSH
ssh pi@raspberrypi.local
```

### 2. Installation automatique

```bash
# Télécharger et exécuter le script d'installation
wget https://raw.githubusercontent.com/[votre-repo]/billiard-tracker/main/scripts/install.sh
chmod +x install.sh
./install.sh
```

### 3. Installation manuelle

Si vous préférez une installation manuelle :

```bash
# Mise à jour système
sudo apt update && sudo apt upgrade -y

# Dépendances
sudo apt install -y python3 python3-pip python3-venv git nginx avahi-daemon sqlite3

# Cloner le projet
cd /home/pi
git clone https://github.com/[votre-repo]/billiard-tracker.git
cd billiard-tracker

# Environnement Python
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# Démarrer l'application
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

## 🚀 Utilisation

### Accès à l'application

Une fois installée, l'application est accessible via :
- **http://billiard.local** (depuis n'importe quel appareil du réseau)
- **http://[IP-du-raspberry]** (remplacer par l'IP réelle)

### Installation sur smartphone (PWA)

1. Ouvrir l'URL dans Chrome/Safari
2. Menu → "Ajouter à l'écran d'accueil"
3. L'application s'installe comme une app native

### Workflow type d'une partie

1. **Sélection du format** (1v1, 2v2, etc.)
2. **Sélection des joueurs** 
   - Tap sur les tuiles pour sélectionner
   - Bleu = Équipe A, Jaune = Équipe B
3. **Consultation H2H** (affichage automatique)
4. **Saisie du résultat**
   - Sélectionner le vainqueur
   - Ajuster les boules restantes
   - Cocher "Faute sur la noire" si applicable
5. **Validation** → Mise à jour automatique des classements

## 📊 Système ELO

### Calcul de base

```
ΔElo = K_eff × f_mov × (Score - Expected)
```

Où :
- **K_eff** : K de base modulé par l'écart de rating (anti-farm)
- **f_mov** : Facteur d'ampleur basé sur les boules restantes
- **Score** : 1 pour victoire, 0 pour défaite
- **Expected** : Probabilité de victoire selon la formule ELO standard

### Paramètres par défaut

- **K_base** : 24
- **α** (margin of victory) : 0.5
- **β** (anti-farm) : 0.5
- **Δ** (seuil anti-farm) : 400
- **ELO initial** : 1000

### Formats éligibles

- **1v1** : ELO individuel par joueur
- **2v2** : ELO par équipe (duo persistant)
- **3v3, 1v2** : Non classés (stats uniquement)

## 🔐 Administration

### Accès admin

1. Aller dans l'onglet Admin
2. Entrer le PIN (défini lors du premier accès)
3. Accès aux fonctionnalités :
   - Modification des paramètres ELO
   - Édition/suppression de matchs
   - Fusion de joueurs
   - Export des données

### Paramètres modifiables

- Constantes ELO (K, α, β, Δ)
- Pondérations pour le classement global
- Règles d'éligibilité par format
- Gestion des joueurs invités

## 💾 Sauvegarde et restauration

### Sauvegardes automatiques

- **Fréquence** : Quotidienne à 2h du matin
- **Rétention** : 30 jours
- **Emplacement** : `/home/pi/billiard-tracker/data/backups/`

### Sauvegarde manuelle

```bash
cd /home/pi/billiard-tracker
./scripts/backup.sh
```

### Restauration

```bash
# Arrêter le service
sudo systemctl stop billiard-tracker

# Restaurer la base
cp /home/pi/billiard-tracker/data/backups/billiard-YYYY-MM-DD.db /home/pi/billiard-tracker/data/billiard.db

# Redémarrer
sudo systemctl start billiard-tracker
```

### Export CSV

Via l'interface admin, exporter :
- Liste des joueurs
- Historique des matchs
- Classements ELO

## 🐛 Dépannage

### Vérifier les services

```bash
# Status de l'API
sudo systemctl status billiard-tracker

# Status de Nginx
sudo systemctl status nginx

# Logs de l'API
sudo journalctl -u billiard-tracker -f
```

### Problèmes courants

**L'application n'est pas accessible**
- Vérifier la connexion Wi-Fi : `ping billiard.local`
- Vérifier les services : `sudo systemctl status billiard-tracker nginx`
- Vérifier le firewall : `sudo ufw status`

**Erreur 502 Bad Gateway**
- L'API n'est pas démarrée : `sudo systemctl restart billiard-tracker`
- Vérifier les logs : `sudo journalctl -u billiard-tracker -n 50`

**Les modifications ne sont pas sauvegardées**
- Vérifier les permissions : `ls -la /home/pi/billiard-tracker/data/`
- Vérifier l'espace disque : `df -h`

**Le mDNS ne fonctionne pas**
- Redémarrer Avahi : `sudo systemctl restart avahi-daemon`
- Utiliser l'IP directement : `hostname -I`

## 📱 Mode offline

L'application fonctionne en mode offline grâce au Service Worker :

- **Cache des ressources** : HTML, CSS, JS
- **File d'attente** : Les matchs sont stockés localement
- **Synchronisation** : Automatique au retour de la connexion

## 🔄 Mises à jour

```bash
cd /home/pi/billiard-tracker
git pull origin main
source venv/bin/activate
pip install -r backend/requirements.txt
sudo systemctl restart billiard-tracker
sudo systemctl restart nginx
```

## 📈 Performances

### Optimisations implémentées

- **Index SQLite** sur les colonnes fréquemment requêtées
- **Cache Nginx** pour les ressources statiques
- **Lazy loading** des historiques
- **Debounce** sur les recherches
- **Compression gzip** activée

### Limites connues

- ~100 matchs/jour sans impact performance
- ~20 joueurs simultanés recommandés
- Base de données jusqu'à 1 Go testée

## 🤝 Contribution

Les contributions sont bienvenues ! Merci de :

1. Fork le projet
2. Créer une branche feature (`git checkout -b feature/AmazingFeature`)
3. Commit les changements (`git commit -m 'Add AmazingFeature'`)
4. Push la branche (`git push origin feature/AmazingFeature`)
5. Ouvrir une Pull Request

## 📄 Licence

Ce projet est sous licence MIT. Voir le fichier `LICENSE` pour plus de détails.

## 🙏 Remerciements

- FastAPI pour le framework backend performant
- SQLAlchemy pour l'ORM robuste
- L'équipe du bureau pour les tests et retours

## 📞 Support

Pour toute question ou problème :
- Ouvrir une issue sur GitHub
- Contact : [bastianniszczota@gmail.com]

---

**Version** : 1.0.0  
**Dernière mise à jour** : Septembre 2025