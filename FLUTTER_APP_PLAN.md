# Plan de transposition — Flutter Multi-Game Tracker

## Vision

Transformer le Billiard Tracker (web PWA) en une **application Flutter native** capable de suivre les scores et classements ELO pour **plusieurs jeux de bar/bureau** : billard, fléchettes, ping-pong, baby-foot, pétanque, etc.

L'app conserve la philosophie actuelle (simple, rapide, fun entre amis) tout en s'ouvrant à un catalogue de jeux et à une légère monétisation.

---

## 1. Architecture technique

### 1.1 Stack proposé

| Couche | Technologie | Justification |
|--------|-------------|---------------|
| **Frontend** | Flutter (Dart) | Multiplateforme iOS/Android, UI riche, performance native |
| **State management** | Riverpod | Léger, testable, adapté aux apps moyennes |
| **Base locale** | Drift (SQLite) | Fonctionne offline, migration facile depuis le schéma actuel |
| **Backend distant** (optionnel, v2) | Supabase ou Firebase | Auth, sync cloud, temps réel — gratuit au démarrage |
| **Pub/monétisation** | Google AdMob + RevenueCat | Bannières, interstitiels, achats in-app |

### 1.2 Offline-first

L'app **fonctionne 100% en local** sans connexion internet (comme aujourd'hui). Le cloud est une option future pour la synchronisation multi-appareils.

```
┌─────────────────────────────┐
│       Flutter App           │
│  ┌───────┐   ┌───────────┐  │
│  │  UI   │◄──│ Riverpod  │  │
│  │ Pages │   │ Providers │  │
│  └───────┘   └─────┬─────┘  │
│                    │        │
│         ┌──────────▼──────┐ │
│         │  ELO Engine     │ │
│         │  (Dart pur)     │ │
│         └──────────┬──────┘ │
│                    │        │
│         ┌──────────▼──────┐ │
│         │  Drift (SQLite) │ │
│         └─────────────────┘ │
└─────────────────────────────┘
         ▲ (optionnel v2)
         │  Sync
┌────────▼────────┐
│  Supabase/Fire  │
│  (cloud sync)   │
└─────────────────┘
```

---

## 2. Modèle de données (généralisé)

Le schéma actuel est spécifique au billard. On le généralise pour supporter N jeux.

### 2.1 Nouvelles tables

```
┌──────────────────────────────────────────────┐
│ games (catalogue de jeux)                    │
├──────────────────────────────────────────────┤
│ id            TEXT PK     ("pool", "darts")  │
│ name          TEXT        ("Billard 8-pool") │
│ icon          TEXT        (emoji ou asset)   │
│ description   TEXT                           │
│ min_players   INT         (2)                │
│ max_players   INT         (6)                │
│ has_teams     BOOL        (true/false)       │
│ team_sizes    TEXT JSON   ("[2,3]")           │
│ score_type    TEXT        (voir 2.2)         │
│ score_config  TEXT JSON   (config spécifique)│
│ default_elo   JSON        (params ELO)       │
│ is_premium    BOOL        (false)            │
│ created_at    DATETIME                       │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ players (inchangé)                           │
├──────────────────────────────────────────────┤
│ id            INT PK                         │
│ name          TEXT UNIQUE                    │
│ avatar_url    TEXT NULL                      │
│ is_guest      BOOL                           │
│ created_at    DATETIME                       │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ matches (généralisé)                         │
├──────────────────────────────────────────────┤
│ id            INT PK                         │
│ game_id       TEXT FK → games                │
│ format        TEXT        ("1v1", "2v2"...)  │
│ played_at     DATETIME                       │
│ winner_side   TEXT        ("A" ou "B")       │
│ score_data    TEXT JSON   (spécifique au jeu)│
│ ranked        BOOL                           │
│ team_id_a     INT FK NULL                    │
│ team_id_b     INT FK NULL                    │
│ created_at    DATETIME                       │
└──────────────────────────────────────────────┘

│ ratings       → ajouter game_id à la clé composite      │
│ team_ratings  → ajouter game_id à la clé composite      │
│ teams         → inchangé (partagées entre jeux)          │
│ settings      → scope par game_id (elo params par jeu)   │
```

### 2.2 Score spécifique par jeu (`score_data` JSON)

Chaque jeu a ses propres métriques stockées dans un champ JSON flexible :

| Jeu | `score_type` | Contenu de `score_data` |
|-----|--------------|-------------------------|
| **Billard 8-pool** | `balls_remaining` | `{"balls": 5, "foul_black": false}` |
| **Fléchettes (301/501)** | `points_margin` | `{"score_a": 0, "score_b": 87, "checkout": "double_16"}` |
| **Ping-pong** | `sets` | `{"sets_a": 3, "sets_b": 1, "set_scores": ["11-7","9-11","11-5","11-3"]}` |
| **Baby-foot** | `goals` | `{"goals_a": 10, "goals_b": 6}` |
| **Pétanque** | `points` | `{"points_a": 13, "points_b": 8}` |
| **Échecs** | `result` | `{"result": "checkmate", "moves": 34}` |

Le **margin of victory** pour le calcul ELO est dérivé de ces données via une fonction spécifique à chaque jeu.

---

## 3. Système ELO — transposition

### 3.1 Formule conservée

On garde la formule actuelle qui fonctionne bien :

```
ΔElo = K_eff × f_mov × (Score - Expected) + win_bonus + inflation
```

Avec :
- **K_eff** = K_base × (1 - β × min(diff_rating / δ, 1)) — anti-farm
- **f_mov** = 1 + α × margin_normalized — bonus domination
- **Expected** = 1 / (1 + 10^((R_opp - R_player) / δ))
- **inflation** = points ajoutés aux deux joueurs par match
- **win_bonus** = gain minimum garanti

### 3.2 Margin of Victory par jeu

Chaque jeu définit comment normaliser la marge de victoire sur [0, 1] :

```dart
abstract class GameScorer {
  /// Retourne un score entre 0.0 (victoire serrée) et 1.0 (domination)
  double marginOfVictory(Map<String, dynamic> scoreData);

  /// Widget pour saisir le score
  Widget scoreInputWidget();

  /// Résumé textuel du score
  String scoreSummary(Map<String, dynamic> scoreData);
}

class PoolScorer extends GameScorer {
  @override
  double marginOfVictory(Map<String, dynamic> scoreData) {
    int balls = scoreData['balls'] ?? 0;
    return balls / 7.0; // 0 à 7 boules → 0.0 à 1.0
  }
}

class DartsScorer extends GameScorer {
  @override
  double marginOfVictory(Map<String, dynamic> scoreData) {
    int remaining = scoreData['score_b'] ?? 0; // score restant du perdant
    int target = scoreData['target'] ?? 301;
    return remaining / target; // plus il reste, plus c'est dominé
  }
}

class PingPongScorer extends GameScorer {
  @override
  double marginOfVictory(Map<String, dynamic> scoreData) {
    int setsA = scoreData['sets_a'] ?? 0;
    int setsB = scoreData['sets_b'] ?? 0;
    int totalSets = setsA + setsB;
    return totalSets > 0 ? (setsA - setsB).abs() / totalSets : 0.0;
  }
}
```

### 3.3 Paramètres ELO configurables par jeu

Chaque jeu a ses propres valeurs par défaut (modifiables en admin) :

| Paramètre | Billard | Fléchettes | Ping-pong | Baby-foot |
|-----------|---------|------------|-----------|-----------|
| K base | 24 | 20 | 24 | 28 |
| Alpha (MoV) | 0.5 | 0.3 | 0.4 | 0.5 |
| Beta (anti-farm) | 0.5 | 0.5 | 0.5 | 0.5 |
| Delta | 400 | 400 | 400 | 400 |
| Inflation | 2.0 | 1.5 | 2.0 | 2.5 |
| Win bonus | 1.0 | 1.0 | 1.0 | 1.0 |

---

## 4. Navigation et pages Flutter

### 4.1 Arborescence des écrans

```
App
├── 🏠 HomeScreen
│   ├── Liste des jeux (catalogue)
│   └── Dernières parties (tous jeux)
│
├── 🎮 GameScreen(gameId)
│   ├── Jouer (enregistrer un match)
│   ├── Classement (leaderboard du jeu)
│   ├── Historique (matchs du jeu)
│   └── H2H (confrontations)
│
├── 👤 PlayerProfileScreen(playerId)
│   ├── Stats globales (tous jeux)
│   ├── Stats par jeu (onglets)
│   ├── Équipes
│   └── Derniers matchs
│
├── 👥 PlayersListScreen
│   ├── Liste des joueurs
│   └── Ajout joueur
│
├── ⚙️ SettingsScreen
│   ├── Paramètres ELO par jeu
│   ├── Admin PIN
│   ├── Export/Import données
│   ├── Thème et langue
│   └── Gérer l'abonnement
│
└── 📊 StatsScreen (premium)
    ├── Graphes d'évolution ELO
    ├── Statistiques avancées
    └── Comparateur de joueurs
```

### 4.2 Navigation principale

```
BottomNavigationBar (4 onglets)
┌──────────┬────────────┬──────────┬──────────┐
│  Accueil │    Jeux    │ Joueurs  │ Réglages │
│    🏠    │     🎮     │    👥    │    ⚙️    │
└──────────┴────────────┴──────────┴──────────┘
```

---

## 5. Catalogue de jeux — phase 1

### Jeux inclus au lancement (gratuits)

| Jeu | Format | Score | Icone |
|-----|--------|-------|-------|
| **Billard 8-pool** | 1v1, 2v2 | Boules restantes (0-7) + faute noire | 🎱 |
| **Fléchettes** | 1v1 | Score final (301/501) | 🎯 |
| **Ping-pong** | 1v1 | Sets gagnés | 🏓 |
| **Baby-foot** | 1v1, 2v2 | Score (buts) | ⚽ |

### Jeux futurs (ajoutés par mise à jour ou premium)

| Jeu | Potentiel | Note |
|-----|-----------|------|
| Pétanque | Bon | Populaire en France, formats 1v1/2v2/3v3 |
| Shuffleboard | Moyen | Niche mais bar-gaming en croissance |
| Beer-pong | Bon | Public jeune, convivial |
| Échecs | Bon | Suivi ELO déjà répandu |
| Air hockey | Moyen | Arcades/bars |
| Cornhole | Moyen | En croissance (US/EU) |

### Ajouter un nouveau jeu = une config

L'ajout d'un jeu ne nécessite pas de code spécifique autre que :
1. Un `GameScorer` (calcul de marge de victoire)
2. Un widget de saisie de score
3. Une config JSON (nom, formats, icône, params ELO)

---

## 6. Stratégie de monétisation

### 6.1 Modèle Freemium + Publicité

L'objectif est une **monétisation très légère** qui ne gêne pas l'expérience.

```
┌─────────────────────────────────────────────────────────┐
│                    VERSION GRATUITE                      │
├─────────────────────────────────────────────────────────┤
│  ✅ 4 jeux de base (billard, fléchettes, pong, baby)   │
│  ✅ Matchs illimités                                    │
│  ✅ Classements et profils                              │
│  ✅ Historique (50 derniers matchs)                     │
│  ✅ Export JSON                                         │
│  ⚠️ Pub bannière en bas (non-intrusive)                │
│  ⚠️ Interstitiel 1x après chaque 5 matchs enregistrés │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               VERSION PREMIUM ("Pro")                   │
│               2,99€/mois ou 19,99€/an                   │
├─────────────────────────────────────────────────────────┤
│  ✅ Tout le gratuit, sans aucune pub                    │
│  ✅ Jeux supplémentaires (pétanque, échecs, ...)       │
│  ✅ Historique illimité                                 │
│  ✅ Graphes d'évolution ELO dans le temps              │
│  ✅ Statistiques avancées (meilleur jour, winrate/h)   │
│  ✅ Comparateur de joueurs côte-à-côte                 │
│  ✅ Thèmes personnalisés (couleurs, mode sombre)       │
│  ✅ Sauvegarde cloud (sync multi-appareils)            │
│  ✅ Import de données (restauration)                   │
│  ✅ Badge "Pro" sur le profil                           │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Placement des publicités

| Emplacement | Type | Fréquence | Intrusivité |
|-------------|------|-----------|-------------|
| Bas de l'écran accueil | Bannière (320x50) | Permanent | Faible |
| Après enregistrement match | Interstitiel | 1 sur 5 matchs | Moyenne |
| Écran classement | Bannière (320x50) | Permanent | Faible |
| Jamais pendant la saisie | — | — | Aucune |

**Règles clés :**
- **Jamais** de pub pendant qu'on enregistre un match (moment critique)
- **Jamais** de pub vidéo forcée
- Interstitiel uniquement après l'action (pas avant)
- Toujours pouvoir fermer en < 2 secondes

### 6.3 Revenus estimés (conservateur)

| Métrique | Valeur estimée |
|----------|---------------|
| DAU (Daily Active Users) après 6 mois | ~500 |
| Impressions bannières/jour | ~2 000 |
| eCPM bannières (France) | ~1,50€ |
| Revenu bannières/mois | ~90€ |
| Interstitiels/jour | ~200 |
| eCPM interstitiels | ~5€ |
| Revenu interstitiels/mois | ~30€ |
| **Taux conversion Premium** | **3-5%** |
| Abonnés Premium (sur 500 DAU) | ~20 |
| Revenu Premium/mois | ~60€ |
| **Revenu total estimé/mois** | **~180€** |

> Ces chiffres sont conservateurs. Avec 5 000 DAU, on atteint ~1 500€/mois.

### 6.4 Alternatives de monétisation à considérer

- **Tip jar** : bouton "offrir un café" (achat unique 1-3€)
- **Packs de jeux** : acheter un jeu supplémentaire à l'unité (0,99€)
- **Tournois sponsorisés** : partenariat avec des bars (v2+)

---

## 7. Implémentation Flutter — Structure du projet

### 7.1 Organisation des fichiers

```
lib/
├── main.dart
├── app.dart
│
├── core/
│   ├── elo/
│   │   ├── elo_calculator.dart      ← Port depuis elo.py
│   │   └── elo_settings.dart
│   ├── database/
│   │   ├── app_database.dart        ← Drift schema
│   │   ├── daos/                    ← Data access objects
│   │   │   ├── player_dao.dart
│   │   │   ├── match_dao.dart
│   │   │   ├── rating_dao.dart
│   │   │   └── game_dao.dart
│   │   └── migrations/
│   └── models/
│       ├── player.dart
│       ├── match.dart
│       ├── rating.dart
│       ├── team.dart
│       └── game.dart
│
├── features/
│   ├── home/
│   │   ├── home_screen.dart
│   │   └── widgets/
│   ├── game/
│   │   ├── game_screen.dart          ← Onglets par jeu
│   │   ├── play_tab.dart             ← Enregistrer un match
│   │   ├── leaderboard_tab.dart
│   │   ├── history_tab.dart
│   │   └── scorers/                  ← Widgets de score par jeu
│   │       ├── game_scorer.dart      ← Interface abstraite
│   │       ├── pool_scorer.dart
│   │       ├── darts_scorer.dart
│   │       ├── ping_pong_scorer.dart
│   │       └── foosball_scorer.dart
│   ├── profile/
│   │   └── player_profile_screen.dart
│   ├── players/
│   │   └── players_list_screen.dart
│   ├── settings/
│   │   ├── settings_screen.dart
│   │   └── elo_settings_screen.dart
│   └── stats/                        ← Premium
│       ├── elo_chart_screen.dart
│       └── comparison_screen.dart
│
├── providers/
│   ├── player_provider.dart
│   ├── match_provider.dart
│   ├── game_provider.dart
│   ├── premium_provider.dart
│   └── ad_provider.dart
│
├── widgets/
│   ├── player_tile.dart
│   ├── match_card.dart
│   ├── leaderboard_table.dart
│   ├── stat_card.dart
│   └── ad_banner.dart
│
└── theme/
    ├── app_theme.dart
    └── game_themes.dart              ← Couleur par jeu
```

### 7.2 Dépendances pubspec.yaml (principales)

```yaml
dependencies:
  flutter:
    sdk: flutter
  flutter_riverpod: ^2.0.0
  drift: ^2.0.0
  sqlite3_flutter_libs: ^0.5.0
  path_provider: ^2.0.0
  path: ^1.8.0
  google_mobile_ads: ^5.0.0
  purchases_flutter: ^7.0.0         # RevenueCat
  fl_chart: ^0.68.0                 # Graphes ELO (premium)
  share_plus: ^9.0.0                # Export/partage
  intl: ^0.19.0                     # Dates/langues

dev_dependencies:
  drift_dev: ^2.0.0
  build_runner: ^2.0.0
  flutter_test:
    sdk: flutter
```

---

## 8. Migration depuis le projet actuel

### 8.1 Ce qu'on réutilise tel quel

| Élément | Source | Cible Flutter |
|---------|--------|---------------|
| Formule ELO complète | `elo.py` | `elo_calculator.dart` (port Dart) |
| Schéma DB (base) | `models.py` | Drift schema (étendu avec `game_id`) |
| Logique anti-farm | `elo.py` | Identique |
| Logique rebuild ratings | `main.py` | `rating_service.dart` |
| Params par défaut | Settings table | Même structure |

### 8.2 Ce qu'on améliore

| Aspect | Web actuel | Flutter |
|--------|-----------|---------|
| Auth admin | PIN SHA-256 en query string | PIN hashé Argon2 + stockage sécurisé |
| Navigation profil | Pas de bouton retour (corrigé) | Navigation native Flutter avec back |
| Recherche historique | Filtrage local JS | Requête DB avec index |
| UI/UX | HTML monolithique 1500 lignes | Widgets composables |
| Offline | PWA basique | SQLite natif, vrai offline-first |
| Performance | Latence réseau (API) | Accès DB local instantané |

### 8.3 Import des données existantes

Prévoir un **écran d'import** qui accepte le JSON exporté par la version web :

```dart
Future<void> importFromWebExport(Map<String, dynamic> data) async {
  // 1. Importer les joueurs
  // 2. Importer les matchs (en les rattachant au jeu "pool")
  // 3. Recalculer les ratings
}
```

---

## 9. Roadmap de développement

### Phase 1 — MVP (6-8 semaines)

- [ ] Setup projet Flutter + Drift + Riverpod
- [ ] Port du moteur ELO en Dart
- [ ] CRUD joueurs
- [ ] Enregistrement de matchs (billard uniquement)
- [ ] Classement 1v1 et 2v2
- [ ] Profil joueur basique
- [ ] Historique des matchs
- [ ] Import depuis la version web
- [ ] Publication Play Store (beta fermée)

### Phase 2 — Multi-jeux + Pub (4-6 semaines)

- [ ] Architecture GameScorer
- [ ] Ajout fléchettes, ping-pong, baby-foot
- [ ] Intégration AdMob (bannières + interstitiels)
- [ ] Écran d'accueil multi-jeux
- [ ] Recherche et filtres avancés
- [ ] Publication App Store + Play Store

### Phase 3 — Premium (4-6 semaines)

- [ ] Intégration RevenueCat (abonnements)
- [ ] Graphes d'évolution ELO (fl_chart)
- [ ] Statistiques avancées
- [ ] Comparateur de joueurs
- [ ] Thèmes personnalisables
- [ ] Jeux supplémentaires premium

### Phase 4 — Cloud et social (8+ semaines)

- [ ] Sync cloud (Supabase/Firebase)
- [ ] Mode tournoi
- [ ] Partage de résultats
- [ ] Notifications
- [ ] Système de saisons

---

## 10. Résumé

| Aspect | Décision |
|--------|----------|
| **Framework** | Flutter (iOS + Android) |
| **Base de données** | SQLite local (Drift), cloud optionnel plus tard |
| **ELO** | Même formule que le web, avec GameScorer par jeu |
| **Jeux au lancement** | Billard, fléchettes, ping-pong, baby-foot |
| **Monétisation** | Bannières + interstitiels légers + abonnement Pro 2,99€/mois |
| **Stratégie pub** | Non-intrusive, jamais pendant la saisie de match |
| **Cible** | Groupes d'amis, bars, clubs amateurs |
| **Timeline MVP** | ~8 semaines |
