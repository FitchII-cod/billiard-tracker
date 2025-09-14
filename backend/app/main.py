from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import hashlib
import secrets
import json

from backend.app import models, schemas
from backend.app.database import SessionLocal, engine, get_db, Base
from backend.app.elo import EloCalculator

# Créer les tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Billiard Tracker API", version="1.0.0")

# CORS pour PWA
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifier l'origine exacte
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sessions admin (simple, en mémoire pour ce POC)
admin_sessions = {}

def check_admin(token: str = None):
    """Vérifie si le token admin est valide"""
    if not token or token not in admin_sessions:
        raise HTTPException(status_code=401, detail="Non autorisé")
    
    # Vérifier expiration (30 minutes)
    if datetime.utcnow() > admin_sessions[token]['expires']:
        del admin_sessions[token]
        raise HTTPException(status_code=401, detail="Session expirée")
    
    return admin_sessions[token]

# Routes principales

@app.get("/")
def read_root():
    return {"message": "Billiard Tracker API", "version": "1.0.0"}

@app.post("/players", response_model=schemas.Player)
def create_player(player: schemas.PlayerCreate, db: Session = Depends(get_db)):
    """Créer un nouveau joueur"""
    # Vérifier l'unicité du nom
    existing = db.query(models.Player).filter_by(name=player.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce nom existe déjà")
    
    db_player = models.Player(**player.model_dump())
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    return db_player

@app.get("/players", response_model=List[schemas.Player])
def get_players(
    include_guests: bool = True,
    db: Session = Depends(get_db)
):
    """Récupérer tous les joueurs"""
    query = db.query(models.Player)
    if not include_guests:
        query = query.filter_by(is_guest=False)
    return query.order_by(models.Player.name).all()

@app.get("/players/{player_id}", response_model=schemas.Player)
def get_player(player_id: int, db: Session = Depends(get_db)):
    """Récupérer un joueur spécifique"""
    player = db.query(models.Player).filter_by(id=player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")
    return player

@app.post("/matches", response_model=schemas.MatchResponse)
def create_match(match_data: schemas.MatchCreate, db: Session = Depends(get_db)):
    """Créer un nouveau match"""
    
    # Validation du format et du nombre de joueurs
    format_players = {
        "1v1": (1, 1),
        "2v2": (2, 2),
        "3v3": (3, 3),
        "1v2": (1, 2)
    }
    
    expected_a, expected_b = format_players.get(match_data.format, (0, 0))
    
    if len(match_data.players_a) != expected_a or len(match_data.players_b) != expected_b:
        if match_data.format != "1v2" or (len(match_data.players_a) != 2 or len(match_data.players_b) != 1):
            raise HTTPException(
                status_code=400, 
                detail=f"Format {match_data.format} requiert {expected_a} joueur(s) côté A et {expected_b} côté B"
            )
    
    # Date par défaut = maintenant
    played_at = match_data.played_at or datetime.utcnow()
    
    # Créer le match
    db_match = models.Match(
        format=match_data.format,
        played_at=played_at,
        balls_remaining=match_data.balls_remaining,
        winner_side=match_data.winner_side,
        foul_black=match_data.foul_black,
        ranked=match_data.ranked
    )
    
    # Gestion spéciale pour 2v2 : créer/trouver les équipes
    elo_calc = EloCalculator(db)
    
    if match_data.format == "2v2":
        team_a_id = elo_calc.get_or_create_team(match_data.players_a)
        team_b_id = elo_calc.get_or_create_team(match_data.players_b)
        db_match.team_id_a = team_a_id
        db_match.team_id_b = team_b_id
    
    db.add(db_match)
    db.flush()  # Pour obtenir l'ID
    
    # Ajouter les joueurs au match
    for player_id in match_data.players_a:
        mp = models.MatchPlayer(match_id=db_match.id, player_id=player_id, side="A")
        db.add(mp)
    
    for player_id in match_data.players_b:
        mp = models.MatchPlayer(match_id=db_match.id, player_id=player_id, side="B")
        db.add(mp)
    
    # Mise à jour ELO si match classé
    if match_data.ranked:
        if match_data.format == "1v1":
            # Déterminer le gagnant
            winner_id = match_data.players_a[0] if match_data.winner_side == "A" else match_data.players_b[0]
            elo_calc.update_1v1_ratings(
                match_data.players_a[0],
                match_data.players_b[0],
                winner_id,
                match_data.balls_remaining
            )
        elif match_data.format == "2v2":
            winner_team_id = team_a_id if match_data.winner_side == "A" else team_b_id
            elo_calc.update_2v2_ratings(
                team_a_id,
                team_b_id,
                winner_team_id,
                match_data.balls_remaining
            )
    
    db.commit()
    db.refresh(db_match)
    
    # Préparer la réponse
    players_a = db.query(models.Player).filter(models.Player.id.in_(match_data.players_a)).all()
    players_b = db.query(models.Player).filter(models.Player.id.in_(match_data.players_b)).all()
    
    response = schemas.MatchResponse(
        id=db_match.id,
        format=db_match.format,
        played_at=db_match.played_at,
        balls_remaining=db_match.balls_remaining,
        winner_side=db_match.winner_side,
        foul_black=db_match.foul_black,
        ranked=db_match.ranked,
        players_a=players_a,
        players_b=players_b
    )
    
    if db_match.team_id_a:
        response.team_a = db.query(models.Team).filter_by(id=db_match.team_id_a).first()
    if db_match.team_id_b:
        response.team_b = db.query(models.Team).filter_by(id=db_match.team_id_b).first()
    
    return response

@app.get("/leaderboard/{format}")
def get_leaderboard(
    format: str,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Récupérer le classement pour un format donné"""
    leaderboard = []
    
    if format == "1v1":
        # Classement individuel
        ratings = db.query(models.Rating).filter_by(format="1v1").order_by(models.Rating.rating.desc()).limit(limit).all()
        
        for idx, rating in enumerate(ratings, 1):
            player = rating.player
            win_rate = (rating.wins / rating.games * 100) if rating.games > 0 else 0
            
            leaderboard.append(schemas.LeaderboardEntry(
                rank=idx,
                entity_name=player.name,
                entity_id=player.id,
                entity_type="player",
                rating=rating.rating,
                games=rating.games,
                wins=rating.wins,
                losses=rating.losses,
                win_rate=win_rate,
                streak=rating.streak,
                last_played=rating.last_played
            ))
    
    elif format == "2v2":
        # Classement par équipe
        ratings = db.query(models.TeamRating).filter_by(format="2v2").order_by(models.TeamRating.rating.desc()).limit(limit).all()
        
        for idx, rating in enumerate(ratings, 1):
            team = rating.team
            win_rate = (rating.wins / rating.games * 100) if rating.games > 0 else 0
            
            leaderboard.append(schemas.LeaderboardEntry(
                rank=idx,
                entity_name=team.name,
                entity_id=team.id,
                entity_type="team",
                rating=rating.rating,
                games=rating.games,
                wins=rating.wins,
                losses=rating.losses,
                win_rate=win_rate,
                streak=rating.streak,
                last_played=rating.last_played
            ))
    
    elif format == "global":
        # Classement global agrégé (à implémenter selon les pondérations)
        # Pour l'instant, on retourne le 1v1
        return get_leaderboard("1v1", limit, db)
    
    return leaderboard

@app.get("/history")
def get_match_history(
    format: Optional[str] = None,
    player_id: Optional[int] = None,
    team_id: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Récupérer l'historique des matchs avec filtres"""
    query = db.query(models.Match)
    
    if format:
        query = query.filter(models.Match.format == format)
    
    if player_id:
        query = query.join(models.MatchPlayer).filter(models.MatchPlayer.player_id == player_id)
    
    if team_id:
        query = query.filter((models.Match.team_id_a == team_id) | (models.Match.team_id_b == team_id))
    
    total = query.count()
    matches = query.order_by(models.Match.played_at.desc()).offset(offset).limit(limit).all()
    
    results = []
    for match in matches:
        # Récupérer les joueurs
        players_a = [mp.player for mp in match.players if mp.side == "A"]
        players_b = [mp.player for mp in match.players if mp.side == "B"]
        
        result = schemas.MatchResponse(
            id=match.id,
            format=match.format,
            played_at=match.played_at,
            balls_remaining=match.balls_remaining,
            winner_side=match.winner_side,
            foul_black=match.foul_black,
            ranked=match.ranked,
            players_a=players_a,
            players_b=players_b
        )
        
        if match.team_id_a:
            result.team_a = match.team_a
        if match.team_id_b:
            result.team_b = match.team_b
        
        results.append(result)
    
    return {
        "total": total,
        "matches": results
    }

@app.post("/head-to-head")
def get_head_to_head(
    format: str,
    players_a: List[int],
    players_b: List[int],
    db: Session = Depends(get_db)
):
    """Calculer les statistiques head-to-head entre deux équipes"""
    
    # Canonicaliser les équipes
    set_a = set(players_a)
    set_b = set(players_b)
    
    # Rechercher tous les matchs entre ces équipes
    all_matches = db.query(models.Match).filter(models.Match.format == format).all()
    
    relevant_matches = []
    for match in all_matches:
        match_players_a = {mp.player_id for mp in match.players if mp.side == "A"}
        match_players_b = {mp.player_id for mp in match.players if mp.side == "B"}
        
        # Vérifier si c'est un match entre ces équipes (peu importe l'ordre)
        if (match_players_a == set_a and match_players_b == set_b) or \
           (match_players_a == set_b and match_players_b == set_a):
            relevant_matches.append(match)
    
    if not relevant_matches:
        return schemas.HeadToHeadStats(
            total_games=0,
            side_a_wins=0,
            side_b_wins=0,
            last_5_results=[],
            avg_balls_remaining=0,
            last_match_date=None
        )
    
    # Calculer les stats
    side_a_wins = 0
    total_balls = 0
    last_5 = []
    
    for match in sorted(relevant_matches, key=lambda m: m.played_at, reverse=True)[:5]:
        match_players_a = {mp.player_id for mp in match.players if mp.side == "A"}
        
        # Déterminer si l'équipe A actuelle était côté A ou B dans ce match
        if match_players_a == set_a:
            # L'équipe A actuelle était côté A
            if match.winner_side == "A":
                last_5.append("W")
            else:
                last_5.append("L")
        else:
            # L'équipe A actuelle était côté B
            if match.winner_side == "B":
                last_5.append("W")
            else:
                last_5.append("L")
    
    for match in relevant_matches:
        match_players_a = {mp.player_id for mp in match.players if mp.side == "A"}
        
        if match_players_a == set_a:
            if match.winner_side == "A":
                side_a_wins += 1
        else:
            if match.winner_side == "B":
                side_a_wins += 1
        
        total_balls += match.balls_remaining
    
    avg_balls = total_balls / len(relevant_matches) if relevant_matches else 0
    
    return schemas.HeadToHeadStats(
        total_games=len(relevant_matches),
        side_a_wins=side_a_wins,
        side_b_wins=len(relevant_matches) - side_a_wins,
        last_5_results=last_5,
        avg_balls_remaining=round(avg_balls, 2),
        last_match_date=relevant_matches[0].played_at if relevant_matches else None
    )

@app.post("/admin/login")
def admin_login(login: schemas.AdminLogin, db: Session = Depends(get_db)):
    """Connexion admin avec PIN"""
    # Récupérer le hash du PIN depuis les settings
    pin_setting = db.query(models.Setting).filter_by(key="admin_pin_hash").first()
    
    if not pin_setting:
        # Premier login : créer le PIN
        hashed = hashlib.sha256(login.pin.encode()).hexdigest()
        new_setting = models.Setting(key="admin_pin_hash", value=hashed)
        db.add(new_setting)
        db.commit()
        pin_setting = new_setting
    
    # Vérifier le PIN
    hashed_input = hashlib.sha256(login.pin.encode()).hexdigest()
    if hashed_input != pin_setting.value:
        raise HTTPException(status_code=401, detail="PIN incorrect")
    
    # Créer une session
    token = secrets.token_urlsafe(32)
    admin_sessions[token] = {
        "created": datetime.utcnow(),
        "expires": datetime.utcnow() + timedelta(minutes=30)
    }
    
    return {"token": token, "expires_in": 1800}

@app.post("/admin/settings")
def update_settings(
    settings: schemas.AdminSettings,
    token: str,
    db: Session = Depends(get_db)
):
    """Mettre à jour les paramètres admin"""
    check_admin(token)
    
    for key, value in settings.dict(exclude_unset=True).items():
        setting = db.query(models.Setting).filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = models.Setting(key=key, value=str(value))
            db.add(setting)
    
    db.commit()
    return {"status": "success"}

# Initialisation des paramètres par défaut
@app.on_event("startup")
def init_default_settings():
    db = SessionLocal()
    
    defaults = {
        "k_base": "24",
        "alpha": "0.5",
        "beta": "0.5",
        "delta": "400",
        "initial_rating": "1000",
        "team_2v2_seed": "1000"
    }
    
    for key, value in defaults.items():
        if not db.query(models.Setting).filter_by(key=key).first():
            setting = models.Setting(key=key, value=value)
            db.add(setting)
    
    db.commit()
    db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)