# Rapport d'Analyse du Projet Billiard Tracker

**Date du rapport :** 19 novembre 2025
**Version de l'application :** 1.0.0
**Analyste :** Claude (Assistant IA)

---

## 📋 Résumé Exécutif

Billiard Tracker est une Progressive Web App (PWA) full-stack développée pour gérer un système de classement ELO pour parties de billard en environnement de bureau. L'application fonctionne sur un Raspberry Pi Zero 2 W et offre une interface mobile-first avec support offline.

### Points Forts
- ✅ Architecture bien structurée (séparation backend/frontend claire)
- ✅ Système ELO sophistiqué avec anti-farming et inflation
- ✅ Support multi-formats (1v1, 2v2, 3v3, 1v2, 2v3)
- ✅ PWA avec capacités offline
- ✅ Interface utilisateur intuitive et responsive
- ✅ Documentation en français complète

### Points Critiques
- ⚠️ Aucun test automatisé
- ⚠️ Sécurité à renforcer (tokens en query string, CORS ouvert)
- ⚠️ Base de données SQLite peut avoir des limites de concurrence
- ⚠️ Pas de système de migration de base de données

---

## 🏗️ Architecture Technique

### Stack Technologique

**Backend**
- Framework : FastAPI 0.116.1
- Serveur ASGI : Uvicorn 0.35.0
- ORM : SQLAlchemy 2.0.43
- Base de données : SQLite
- Langage : Python 3

**Frontend**
- Type : Progressive Web App (PWA)
- Framework : Vanilla JavaScript (pas de framework)
- Architecture : Single Page Application
- Service Worker pour support offline

**Infrastructure**
- Plateforme cible : Raspberry Pi Zero 2 W
- OS : Raspberry Pi OS Lite (64-bit)
- Reverse Proxy : Nginx
- Service Discovery : Avahi (mDNS - billiard.local)
- Gestion des processus : systemd

### Structure du Projet

```
billiard-tracker/
├── backend/
│   └── app/
│       ├── main.py          # API principale (667 lignes)
│       ├── models.py        # Modèles SQLAlchemy
│       ├── schemas.py       # Schémas Pydantic
│       ├── elo.py          # Moteur de calcul ELO
│       ├── database.py     # Configuration DB
│       └── routers/        # (vide, routes dans main.py)
├── frontend/
│   ├── index.html          # SPA complète (1400+ lignes)
│   ├── manifest.json       # Manifest PWA
│   └── service-worker.js   # Support offline
├── scripts/
│   └── install.sh          # Installation automatisée
└── data/                   # Base de données (gitignore)
```

---

## 🔍 Erreurs Corrigées

### 1. Validation du Format 1v2 (CRITIQUE)
**Fichier :** `backend/app/main.py:140-145`
**Problème :** Double validation confuse pour le format 1v2
**Impact :** Validation incorrecte des matchs 1v2
**Solution :** Simplification de la logique de validation

```python
# AVANT (problématique)
if len(match_data.players_a) != expected_a or len(match_data.players_b) != expected_b:
    if match_data.format != "1v2" or (len(match_data.players_a) != 2 or len(match_data.players_b) != 1):
        raise HTTPException(...)

# APRÈS (corrigé)
if len(match_data.players_a) != expected_a or len(match_data.players_b) != expected_b:
    raise HTTPException(...)
```

### 2. Méthode Pydantic Obsolète (MAJEUR)
**Fichier :** `backend/app/main.py:573`
**Problème :** Utilisation de `.dict()` déprécié dans Pydantic v2
**Impact :** Warnings et compatibilité future
**Solution :** Remplacement par `.model_dump()`

```python
# AVANT
for key, value in settings.dict(exclude_unset=True).items():

# APRÈS
for key, value in settings.model_dump(exclude_unset=True).items():
```

### 3. Paramètres par Défaut Manquants (MAJEUR)
**Fichier :** `backend/app/main.py:648-657`
**Problème :** Les paramètres `inflation` et `win_bonus` n'étaient pas initialisés
**Impact :** Valeurs NULL en base de données, erreurs potentielles
**Solution :** Ajout des valeurs par défaut

```python
defaults = {
    "k_base": "24",
    "alpha": "0.5",
    "beta": "0.5",
    "delta": "400",
    "initial_rating": "1000",
    "team_2v2_seed": "1000",
    "inflation": "2.0",      # AJOUTÉ
    "win_bonus": "1.0"       # AJOUTÉ
}
```

### 4. Fonction exportData Manquante (BLOQUANT)
**Fichier :** `frontend/index.html:683`
**Problème :** Bouton "Exporter les données" appelait une fonction inexistante
**Impact :** Erreur JavaScript, fonctionnalité indisponible
**Solution :**
- Création de l'endpoint `/admin/export` (backend)
- Implémentation de la fonction `exportData()` (frontend)
- Export JSON avec téléchargement automatique

### 5. Chargement des Paramètres Admin (MINEUR)
**Problème :** Le panel admin n'affichait pas les valeurs actuelles des paramètres
**Impact :** Mauvaise expérience utilisateur
**Solution :**
- Création de l'endpoint `/admin/settings` GET
- Fonction `loadAdminSettings()` pour pré-remplir les champs
- Appel automatique lors de la connexion admin

---

## 🔐 Problèmes de Sécurité Identifiés

### 1. Token Admin en Query String (CRITIQUE)
**Localisation :** Multiples endpoints
**Problème :** Le token admin est passé en paramètre URL (`?token=...`)
**Risque :**
- Exposition dans les logs serveur
- Historique du navigateur
- Logs de proxy/reverse proxy

**Recommandation :** Utiliser un header HTTP (Authorization: Bearer)

```python
# ACTUEL (non sécurisé)
@app.delete("/admin/matches/{match_id}")
def delete_match(match_id: int, token: str, db: Session = Depends(get_db)):

# RECOMMANDÉ
from fastapi import Header

@app.delete("/admin/matches/{match_id}")
def delete_match(
    match_id: int,
    authorization: str = Header(...),
    db: Session = Depends(get_db)
):
    token = authorization.replace("Bearer ", "")
    check_admin(token)
```

### 2. Hachage PIN Faible (MAJEUR)
**Localisation :** `backend/app/main.py:544-552`
**Problème :** SHA-256 utilisé pour le PIN (vulnérable aux rainbow tables)
**Recommandation :** Utiliser bcrypt ou argon2

```python
# ACTUEL
hashed = hashlib.sha256(login.pin.encode()).hexdigest()

# RECOMMANDÉ
from passlib.hash import argon2
hashed = argon2.hash(login.pin)
```

### 3. CORS Ouvert (MAJEUR)
**Localisation :** `backend/app/main.py:22-28`
**Problème :** `allow_origins=["*"]` accepte toutes les origines
**Recommandation :** Restreindre aux origines autorisées

```python
# ACTUEL
allow_origins=["*"]

# RECOMMANDÉ
allow_origins=["http://billiard.local", "http://192.168.1.X"]
```

### 4. Pas de HTTPS
**Problème :** Configuration HTTP uniquement
**Recommandation :** Configurer Let's Encrypt ou certificat auto-signé pour le LAN

### 5. Sessions en Mémoire
**Problème :** Les sessions admin sont perdues au redémarrage
**Recommandation :** Utiliser Redis ou base de données

---

## 🐛 Bugs et Limitations

### 1. Recherche dans l'Historique Non Fonctionnelle
**Fichier :** `frontend/index.html:584`
**Problème :** Champ de recherche présent mais sans implémentation
**Impact :** Fonctionnalité promise mais inactive

### 2. Concurrence SQLite
**Problème :** SQLite en mode fichier a des limites de concurrence
**Impact :** Problèmes potentiels avec plusieurs utilisateurs simultanés
**Recommandation :**
- Pour <10 utilisateurs : OK
- Pour >10 utilisateurs : Migrer vers PostgreSQL

### 3. Pas de Système de Migration
**Problème :** Pas d'outil de migration de schéma (Alembic non configuré)
**Impact :** Difficultés pour les mises à jour de structure DB
**Recommandation :** Intégrer Alembic

### 4. Gestion des Erreurs Limitée
**Problème :** Peu de messages d'erreur détaillés pour l'utilisateur
**Exemple :** `alert('Erreur lors de l\'enregistrement')` sans détails

### 5. Pas de Logs d'Audit
**Problème :** Table `AuditLog` définie mais jamais utilisée
**Impact :** Impossibilité de tracer les actions administratives

---

## 📊 Analyse du Système ELO

### Fonctionnalités Implémentées

#### 1. Calcul de Base
- Formule ELO standard : `E = 1 / (1 + 10^((R_b - R_a) / 400))`
- K-factor configurable (défaut: 24)
- Rating initial : 1000

#### 2. Margin of Victory (MoV)
- Facteur Alpha (défaut: 0.5)
- Formule : `factor = 1 + alpha * (balls_remaining / 7)`
- Impact : Récompense les victoires dominantes

#### 3. Anti-Farm
- Facteur Beta (défaut: 0.5)
- Delta threshold (défaut: 400 points)
- Réduction du K quand un joueur fort bat un joueur faible
- Formule : `K_eff = K_base * (1 - beta * (diff / delta))`

#### 4. Inflation ELO
- Ajout de points constants à chaque match
- Défaut : +2 points pour les deux joueurs/équipes
- Objectif : Éviter la stagnation des ratings

#### 5. Win Bonus
- Bonus minimum garanti au vainqueur
- Défaut : +1 point
- Empêche les victoires sans gain de points

### Points Forts du Système
- ✅ Système sophistiqué et bien pensé
- ✅ Protection anti-abuse
- ✅ Paramètres configurables via interface admin
- ✅ Rebuild complet possible en cas de modification

### Améliorations Possibles
- 📈 Historique des évolutions de rating
- 📈 Graphiques de progression
- 📈 Prédiction de victoire basée sur les ELO
- 📈 Système de saisons (reset périodique)

---

## 🎯 Points d'Amélioration Prioritaires

### 🔴 Priorité CRITIQUE

1. **Sécurité des Tokens**
   - Passer les tokens en headers HTTP
   - Implémenter HTTPS
   - Utiliser bcrypt/argon2 pour le PIN

2. **Tests Automatisés**
   - Tests unitaires pour le calcul ELO
   - Tests d'intégration pour les endpoints API
   - Tests E2E pour les flux utilisateur critiques

### 🟠 Priorité HAUTE

3. **Gestion des Erreurs**
   - Messages d'erreur détaillés pour l'utilisateur
   - Logging centralisé
   - Utilisation de la table AuditLog

4. **Migration de Base de Données**
   - Intégrer Alembic
   - Scripts de migration versionnés

5. **Recherche dans l'Historique**
   - Implémentation de la recherche par joueur
   - Filtres par date, format

### 🟡 Priorité MOYENNE

6. **Visualisations**
   - Graphiques d'évolution des ratings
   - Statistiques détaillées par joueur
   - Heatmap des confrontations

7. **Performance**
   - Mise en cache du leaderboard global
   - Index supplémentaires sur la base de données
   - Pagination sur tous les endpoints

8. **Code Quality**
   - Séparer les routes dans des modules dédiés
   - Modulariser le frontend (composants)
   - Ajouter TypeScript

### 🟢 Priorité BASSE

9. **Fonctionnalités Additionnelles**
   - Import de données
   - Édition de matchs (actuellement seulement suppression)
   - Mode tournoi
   - Notifications push PWA

10. **Documentation**
    - Documentation API (Swagger auto-généré par FastAPI)
    - Guide de contribution
    - Architecture Decision Records (ADR)

---

## 📈 Métriques du Projet

### Taille du Code
- **Backend Python :** ~1100 lignes
- **Frontend HTML/CSS/JS :** ~1400 lignes
- **Total :** ~2500 lignes

### Complexité
- **Modèles de données :** 8 tables SQL
- **Endpoints API :** 18 routes
- **Pages frontend :** 6 pages SPA

### Couverture de Tests
- **Tests unitaires :** 0% ❌
- **Tests d'intégration :** 0% ❌
- **Tests E2E :** 0% ❌

### Dépendances
- **Backend :** 5 packages Python
- **Frontend :** 0 dépendance (vanilla JS)
- **Risque de dépendances :** Faible

---

## 🚀 Recommandations de Déploiement

### Pour Production

1. **Sécurité**
   ```bash
   # Installer certbot pour HTTPS
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d billiard.local
   ```

2. **Backup Automatique**
   ```bash
   # Le script install.sh configure déjà un backup quotidien
   # Vérifier : /etc/cron.d/billiard-backup
   ```

3. **Monitoring**
   ```bash
   # Installer monitoring basique
   sudo apt install prometheus-node-exporter
   # Configurer logs centralisés
   sudo journalctl -u billiard-tracker -f
   ```

4. **Limites de Ressources**
   ```ini
   # Modifier /etc/systemd/system/billiard-tracker.service
   [Service]
   MemoryLimit=256M
   CPUQuota=50%
   ```

### Pour Développement

1. **Environnement de Dev**
   ```bash
   # Backend
   cd backend
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install pytest pytest-cov black flake8  # Dev tools

   # Lancer en mode dev
   uvicorn app.main:app --reload
   ```

2. **Tests**
   ```bash
   # À créer
   pytest tests/ --cov=app --cov-report=html
   ```

---

## 🎓 Évaluation Globale

### Note Technique : 7.5/10

**Points Positifs :**
- Architecture solide et bien organisée
- Système ELO sophistiqué
- Interface utilisateur intuitive
- Documentation complète en français
- Installation automatisée

**Points Négatifs :**
- Sécurité à améliorer
- Absence totale de tests
- Pas de système de migration
- Quelques bugs mineurs

### Recommandation

Le projet est **PRÊT POUR DÉPLOIEMENT EN ENVIRONNEMENT DE BUREAU** avec les réserves suivantes :
- ✅ Acceptable pour usage interne (<10 utilisateurs)
- ⚠️ Nécessite durcissement sécurité pour internet
- ⚠️ Ajout de tests recommandé avant évolution majeure

---

## 📝 Changelog des Corrections

### Version 1.0.1 (19 Nov 2025)

**Corrections Critiques :**
- ✅ Fix validation format 1v2 dans création de match
- ✅ Remplacement .dict() par .model_dump() (Pydantic v2)
- ✅ Ajout paramètres par défaut manquants (inflation, win_bonus)

**Nouvelles Fonctionnalités :**
- ✅ Endpoint GET /admin/settings pour récupérer paramètres
- ✅ Endpoint GET /admin/export pour exporter données JSON
- ✅ Fonction exportData() frontend avec téléchargement
- ✅ Chargement automatique des paramètres dans panel admin

**Améliorations UX :**
- ✅ Pré-remplissage des champs admin avec valeurs actuelles
- ✅ Détection session admin existante

---

## 📞 Contact et Support

Pour toute question ou contribution au projet :
- **Repository :** (à définir)
- **Issues :** GitHub Issues
- **Documentation :** README.md et ce rapport

---

**Rapport généré par Claude (Anthropic) le 19 novembre 2025**
