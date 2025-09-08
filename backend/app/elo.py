from typing import Tuple, Optional
from sqlalchemy.orm import Session
from backend.app.models import Rating, TeamRating, Setting
import math

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
        
        # Récupérer ou créer les ratings
        rating_a = self.db.query(Rating).filter_by(
            player_id=player_a_id, format='1v1'
        ).first()
        
        if not rating_a:
            rating_a = Rating(
                player_id=player_a_id,
                format='1v1',
                rating=self.INITIAL_RATING
            )
            self.db.add(rating_a)
        
        rating_b = self.db.query(Rating).filter_by(
            player_id=player_b_id, format='1v1'
        ).first()
        
        if not rating_b:
            rating_b = Rating(
                player_id=player_b_id,
                format='1v1',
                rating=self.INITIAL_RATING
            )
            self.db.add(rating_b)
        
        # Calculs ELO
        old_rating_a = rating_a.rating
        old_rating_b = rating_b.rating
        
        expected_a = self.calculate_expected_score(old_rating_a, old_rating_b)
        expected_b = 1 - expected_a
        
        score_a = 1.0 if winner_id == player_a_id else 0.0
        score_b = 1.0 - score_a
        
        margin_factor = self.calculate_margin_factor(balls_remaining)
        
        # K effectif pour chaque joueur
        k_eff_a = self.calculate_k_effective(old_rating_a, old_rating_b, score_a == 1.0)
        k_eff_b = self.calculate_k_effective(old_rating_b, old_rating_a, score_b == 1.0)
        
        # Mise à jour des ratings
        delta_a = k_eff_a * margin_factor * (score_a - expected_a)
        delta_b = k_eff_b * margin_factor * (score_b - expected_b)
        
        rating_a.rating = old_rating_a + delta_a
        rating_b.rating = old_rating_b + delta_b
        
        # Mise à jour des stats
        rating_a.games += 1
        rating_b.games += 1
        
        if score_a == 1.0:
            rating_a.wins += 1
            rating_b.losses += 1
            rating_a.streak = max(1, rating_a.streak + 1) if rating_a.streak >= 0 else 1
            rating_b.streak = min(-1, rating_b.streak - 1) if rating_b.streak <= 0 else -1
        else:
            rating_a.losses += 1
            rating_b.wins += 1
            rating_a.streak = min(-1, rating_a.streak - 1) if rating_a.streak <= 0 else -1
            rating_b.streak = max(1, rating_b.streak + 1) if rating_b.streak >= 0 else 1
        
        return delta_a, delta_b
    
    def update_2v2_ratings(
        self,
        team_a_id: int,
        team_b_id: int,
        winner_team_id: int,
        balls_remaining: int
    ) -> Tuple[float, float]:
        """Met à jour les ratings ELO pour un match 2v2 (par équipe)"""
        
        # Récupérer ou créer les ratings d'équipe
        rating_a = self.db.query(TeamRating).filter_by(
            team_id=team_a_id, format='2v2'
        ).first()
        
        if not rating_a:
            rating_a = TeamRating(
                team_id=team_a_id,
                format='2v2',
                rating=self.TEAM_2V2_SEED
            )
            self.db.add(rating_a)
        
        rating_b = self.db.query(TeamRating).filter_by(
            team_id=team_b_id, format='2v2'
        ).first()
        
        if not rating_b:
            rating_b = TeamRating(
                team_id=team_b_id,
                format='2v2',
                rating=self.TEAM_2V2_SEED
            )
            self.db.add(rating_b)
        
        # Calculs ELO (similaire au 1v1 mais avec les ratings d'équipe)
        old_rating_a = rating_a.rating
        old_rating_b = rating_b.rating
        
        expected_a = self.calculate_expected_score(old_rating_a, old_rating_b)
        expected_b = 1 - expected_a
        
        score_a = 1.0 if winner_team_id == team_a_id else 0.0
        score_b = 1.0 - score_a
        
        margin_factor = self.calculate_margin_factor(balls_remaining)
        
        k_eff_a = self.calculate_k_effective(old_rating_a, old_rating_b, score_a == 1.0)
        k_eff_b = self.calculate_k_effective(old_rating_b, old_rating_a, score_b == 1.0)
        
        delta_a = k_eff_a * margin_factor * (score_a - expected_a)
        delta_b = k_eff_b * margin_factor * (score_b - expected_b)
        
        rating_a.rating = old_rating_a + delta_a
        rating_b.rating = old_rating_b + delta_b
        
        # Mise à jour des stats
        rating_a.games += 1
        rating_b.games += 1
        
        if score_a == 1.0:
            rating_a.wins += 1
            rating_b.losses += 1
            rating_a.streak = max(1, rating_a.streak + 1) if rating_a.streak >= 0 else 1
            rating_b.streak = min(-1, rating_b.streak - 1) if rating_b.streak <= 0 else -1
        else:
            rating_a.losses += 1
            rating_b.wins += 1
            rating_a.streak = min(-1, rating_a.streak - 1) if rating_a.streak <= 0 else -1
            rating_b.streak = max(1, rating_b.streak + 1) if rating_b.streak >= 0 else 1
        
        return delta_a, delta_b
    
    def get_or_create_team(self, player_ids: list) -> Optional[int]:
        """Trouve ou crée une équipe basée sur les IDs des joueurs"""
        if len(player_ids) != 2:
            return None
        
        # Canonicalisation de la clé
        sorted_ids = sorted(player_ids)
        team_key = f"{sorted_ids[0]}-{sorted_ids[1]}"
        
        from models import Team, TeamMember, Player
        
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