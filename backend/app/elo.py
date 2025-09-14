from typing import Tuple, Optional
from sqlalchemy.orm import Session
from backend.app.models import Rating, TeamRating, Setting
from datetime import datetime, timezone
from backend.app import models
import math


def _inc(x, by=1):
    return (x or 0) + by

def _ensure_rating(db, player_id: int, fmt: str, initial: float):
    r = db.query(models.Rating).filter_by(player_id=player_id, format=fmt).first()
    if not r:
        r = models.Rating(
            player_id=player_id, format=fmt, rating=initial,
            games=0, wins=0, losses=0, streak=0
        )
        db.add(r)
        db.flush()
    else:
        # “filet de sécu” si des anciennes lignes ont des NULL
        r.games   = 0 if r.games   is None else r.games
        r.wins    = 0 if r.wins    is None else r.wins
        r.losses  = 0 if r.losses  is None else r.losses
        r.streak  = 0 if r.streak  is None else r.streak
    return r

def _ensure_team_rating(db, team_id: int, fmt: str, initial: float):
    tr = db.query(models.TeamRating).filter_by(team_id=team_id, format=fmt).first()
    if not tr:
        tr = models.TeamRating(
            team_id=team_id, format=fmt, rating=initial,
            games=0, wins=0, losses=0, streak=0
        )
        db.add(tr)
        db.flush()
    else:
        tr.games  = 0 if tr.games  is None else tr.games
        tr.wins   = 0 if tr.wins   is None else tr.wins
        tr.losses = 0 if tr.losses is None else tr.losses
        tr.streak = 0 if tr.streak is None else tr.streak
    return tr

class EloCalculator:
    def __init__(self, db: Session):
        self.db = db
        self._load_settings()
    
    def _load_settings(self):
        """Charge les paramètres depuis la base de données"""
        settings = {s.key: s.value for s in self.db.query(Setting).all()}
        
        self.K_BASE = float(settings.get('k_base', '24'))
        self.ALPHA = float(settings.get('alpha', '0.5'))  # Pour margin of victory
        self.BETA = float(settings.get('beta', '0.5'))   # Pour anti-farm
        self.DELTA = float(settings.get('delta', '400'))  # Pour anti-farm
        self.INITIAL_RATING = float(settings.get('initial_rating', '1000'))
        self.TEAM_2V2_SEED = float(settings.get('team_2v2_seed', '1000'))
        self.WIN_BONUS = float(settings.get('win_bonus', '1'))
    
    def calculate_expected_score(self, rating_a: float, rating_b: float) -> float:
        """Calcule le score attendu selon la formule ELO standard"""
        return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    
    def calculate_k_effective(self, rating_winner: float, rating_loser: float, is_winner: bool) -> float:
        """Calcule le K effectif avec anti-farm"""
        rating_diff = rating_winner - rating_loser if is_winner else rating_loser - rating_winner
        
        # Anti-farm : réduction du K si l'écart est grand et qu'on est favori
        if rating_diff > 0:  # Si on est favori
            reduction = min(rating_diff / self.DELTA, 1.0)
            k_eff = self.K_BASE * (1 - self.BETA * reduction)
        else:
            k_eff = self.K_BASE
        
        return k_eff
    
    def calculate_margin_factor(self, balls_remaining: int) -> float:
        """Calcule le facteur d'ampleur basé sur les boules restantes"""
        return 1 + self.ALPHA * (balls_remaining / 7)
    
    def update_1v1_ratings(
        self, 
        player_a_id: int, 
        player_b_id: int, 
        winner_id: int,
        balls_remaining: int
    ) -> Tuple[float, float]:
        """Met à jour les ratings ELO pour un match 1v1"""

        # Ratings garantis (compteurs à 0 si nouveaux / NULL corrigés)
        rating_a = _ensure_rating(self.db, player_a_id, '1v1', self.INITIAL_RATING)
        rating_b = _ensure_rating(self.db, player_b_id, '1v1', self.INITIAL_RATING)

        # Calculs ELO
        old_rating_a = rating_a.rating
        old_rating_b = rating_b.rating

        expected_a = self.calculate_expected_score(old_rating_a, old_rating_b)
        expected_b = 1 - expected_a

        score_a = 1.0 if winner_id == player_a_id else 0.0
        score_b = 1.0 - score_a

        # Sécurise au cas où balls_remaining soit None
        margin_factor = self.calculate_margin_factor(balls_remaining or 0)

        # K effectif pour chaque joueur
        k_eff_a = self.calculate_k_effective(old_rating_a, old_rating_b, score_a == 1.0)
        k_eff_b = self.calculate_k_effective(old_rating_b, old_rating_a, score_b == 1.0)

        # Mise à jour des ratings
        delta_a = k_eff_a * margin_factor * (score_a - expected_a)
        delta_b = k_eff_b * margin_factor * (score_b - expected_b)

        # BONUS minimum au vainqueur (paramétrable via settings.win_bonus)
        if score_a == 1.0:
            delta_a += self.WIN_BONUS
        else:
            delta_b += self.WIN_BONUS

        rating_a.rating = old_rating_a + delta_a
        rating_b.rating = old_rating_b + delta_b

        # Horodatage UTC moderne (évite le warning d’utcnow())
        now = datetime.now(timezone.utc)
        rating_a.last_played = now
        rating_b.last_played = now

        # Compteurs robustes (NULL -> 0)
        rating_a.games = _inc(rating_a.games)
        rating_b.games = _inc(rating_b.games)
        if score_a == 1.0:
            rating_a.wins   = _inc(rating_a.wins)
            rating_b.losses = _inc(rating_b.losses)
            rating_a.streak = max(1, (rating_a.streak or 0) + 1) if (rating_a.streak or 0) >= 0 else 1
            rating_b.streak = min(-1, (rating_b.streak or 0) - 1) if (rating_b.streak or 0) <= 0 else -1
        else:
            rating_a.losses = _inc(rating_a.losses)
            rating_b.wins   = _inc(rating_b.wins)
            rating_a.streak = min(-1, (rating_a.streak or 0) - 1) if (rating_a.streak or 0) <= 0 else -1
            rating_b.streak = max(1, (rating_b.streak or 0) + 1) if (rating_b.streak or 0) >= 0 else 1

        return delta_a, delta_b

    
    def update_2v2_ratings(
        self,
        team_a_id: int,
        team_b_id: int,
        winner_team_id: int,
        balls_remaining: int
    ) -> Tuple[float, float]:
        """Met à jour les ratings ELO pour un match 2v2 (par équipe)"""

        # Ratings d'équipe garantis
        rating_a = _ensure_team_rating(self.db, team_a_id, '2v2', self.TEAM_2V2_SEED)
        rating_b = _ensure_team_rating(self.db, team_b_id, '2v2', self.TEAM_2V2_SEED)

        old_rating_a = rating_a.rating
        old_rating_b = rating_b.rating

        expected_a = self.calculate_expected_score(old_rating_a, old_rating_b)
        expected_b = 1 - expected_a

        score_a = 1.0 if winner_team_id == team_a_id else 0.0
        score_b = 1.0 - score_a

        margin_factor = self.calculate_margin_factor(balls_remaining or 0)

        k_eff_a = self.calculate_k_effective(old_rating_a, old_rating_b, score_a == 1.0)
        k_eff_b = self.calculate_k_effective(old_rating_b, old_rating_a, score_b == 1.0)

        delta_a = k_eff_a * margin_factor * (score_a - expected_a)
        delta_b = k_eff_b * margin_factor * (score_b - expected_b)

        if score_a == 1.0:
            delta_a += self.WIN_BONUS
        else:
            delta_b += self.WIN_BONUS

        rating_a.rating = old_rating_a + delta_a
        rating_b.rating = old_rating_b + delta_b

        now = datetime.now(timezone.utc)
        rating_a.last_played = now
        rating_b.last_played = now

        rating_a.games = _inc(rating_a.games)
        rating_b.games = _inc(rating_b.games)
        if score_a == 1.0:
            rating_a.wins   = _inc(rating_a.wins)
            rating_b.losses = _inc(rating_b.losses)
            rating_a.streak = max(1, (rating_a.streak or 0) + 1) if (rating_a.streak or 0) >= 0 else 1
            rating_b.streak = min(-1, (rating_b.streak or 0) - 1) if (rating_b.streak or 0) <= 0 else -1
        else:
            rating_a.losses = _inc(rating_a.losses)
            rating_b.wins   = _inc(rating_b.wins)
            rating_a.streak = min(-1, (rating_a.streak or 0) - 1) if (rating_a.streak or 0) <= 0 else -1
            rating_b.streak = max(1, (rating_b.streak or 0) + 1) if (rating_b.streak or 0) >= 0 else 1

        return delta_a, delta_b

    
    def get_or_create_team(self, player_ids: list) -> Optional[int]:
        """Trouve ou crée une équipe basée sur les IDs des joueurs"""
        if len(player_ids) != 2:
            return None
        
        # Canonicalisation de la clé
        sorted_ids = sorted(player_ids)
        team_key = f"{sorted_ids[0]}-{sorted_ids[1]}"
        
        from backend.app.models import Team, TeamMember, Player
        
        # Rechercher l'équipe existante
        team = self.db.query(Team).filter_by(key=team_key).first()
        
        if not team:
            # Créer la nouvelle équipe
            players = self.db.query(Player).filter(Player.id.in_(player_ids)).all()
            if len(players) != 2:
                return None
            
            # Nom automatique
            team_name = f"{players[0].name} + {players[1].name}"
            
            team = Team(key=team_key, name=team_name)
            self.db.add(team)
            self.db.flush()  # Pour obtenir l'ID
            
            # Ajouter les membres
            for player_id in player_ids:
                member = TeamMember(team_id=team.id, player_id=player_id)
                self.db.add(member)
        
        return team.id