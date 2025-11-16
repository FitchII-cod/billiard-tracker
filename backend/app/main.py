from fastapi import FastAPI, Depends, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
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

def rebuild_ratings(db: Session):
    """Recalcule tous les ELO depuis l'historique après une suppression/modification."""
    # 1) Remise à zéro des ratings individuels et d'équipes
    db.query(models.Rating).delete()
    db.query(models.TeamRating).delete()
    db.commit()

    # 2) Rejouer les matchs classés par date
    matches = (
        db.query(models.Match)
        .order_by(models.Match.played_at.asc(), models.Match.id.asc())
        .all()
    )
    elo_calc = EloCalculator(db)

    for m in matches:
        if not m.ranked:
            continue

        # récupérer les joueurs par côté
        players_a = [mp.player_id for mp in m.players if mp.side == "A"]
        players_b = [mp.player_id for mp in m.players if mp.side == "B"]

        if m.format == "1v1" and len(players_a) == 1 and len(players_b) == 1:
            winner_id = players_a[0] if m.winner_side == "A" else players_b[0]
            elo_calc.update_1v1_ratings(
                players_a[0], players_b[0],
                winner_id,
                m.balls_remaining
            )
        elif m.format == "2v2" and len(players_a) == 2 and len(players_b) == 2:
            # retrouver/créer les équipes comme lors de la création
            team_a_id = elo_calc.get_or_create_team(players_a)
            team_b_id = elo_calc.get_or_create_team(players_b)
            winner_team_id = team_a_id if m.winner_side == "A" else team_b_id
            elo_calc.update_2v2_ratings(
                team_a_id, team_b_id, winner_team_id, m.balls_remaining
            )

    db.commit()

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
        "1v2": (1, 2),
        "2v3": (2, 3)
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

@app.get("/players/{player_id}/summary")
def get_player_summary(player_id: int, db: Session = Depends(get_db)):
    player = db.query(models.Player).filter_by(id=player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur non trouvé")

    # Rating 1v1 s'il existe
    rating = db.query(models.Rating).filter_by(player_id=player_id, format="1v1").first()

    # Équipes du joueur
    teams = (
        db.query(models.Team)
        .join(models.TeamMember, models.TeamMember.team_id == models.Team.id)
        .filter(models.TeamMember.player_id == player_id)
        .all()
    )

    # Derniers matchs (tous formats)
    recent_links = (
        db.query(models.MatchPlayer)
        .filter(models.MatchPlayer.player_id == player_id)
        .all()
    )
    match_ids = [ml.match_id for ml in recent_links]
    recent_matches = []
    if match_ids:
        matches = (
            db.query(models.Match)
            .filter(models.Match.id.in_(match_ids))
            .order_by(models.Match.played_at.desc())
            .limit(20)
            .all()
        )
        for m in matches:
            players_a = [mp.player for mp in m.players if mp.side == "A"]
            players_b = [mp.player for mp in m.players if mp.side == "B"]
            recent_matches.append(
                schemas.MatchResponse(
                    id=m.id, format=m.format, played_at=m.played_at,
                    balls_remaining=m.balls_remaining, winner_side=m.winner_side,
                    foul_black=m.foul_black, ranked=m.ranked,
                    players_a=players_a, players_b=players_b,
                    team_a=m.team_a if m.team_id_a else None,
                    team_b=m.team_b if m.team_id_b else None
                )
            )

    return {
        "player": schemas.Player.from_orm(player),
        "rating_1v1": schemas.RatingResponse.from_orm(rating) if rating else None,
        "teams": [schemas.Team.from_orm(t) for t in teams],
        "recent_matches": recent_matches
    }

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
        # Classement global : prend en compte TOUS les matchs du joueur
        from sqlalchemy import func

        # Récupérer tous les joueurs
        all_players = db.query(models.Player).all()

        for player in all_players:
            # Récupérer tous les matchs du joueur via MatchPlayer
            match_participations = (
                db.query(models.MatchPlayer)
                .filter(models.MatchPlayer.player_id == player.id)
                .all()
            )

            if not match_participations:
                continue

            # Statistiques globales
            total_games = 0
            total_wins = 0
            total_losses = 0
            last_played = None

            # Parcourir tous les matchs
            for mp in match_participations:
                match = db.query(models.Match).filter_by(id=mp.match_id).first()
                if not match or not match.ranked:
                    continue

                total_games += 1

                # Vérifier si le joueur a gagné
                if mp.side == match.winner_side:
                    total_wins += 1
                else:
                    total_losses += 1

                # Dernière partie jouée
                if last_played is None or match.played_at > last_played:
                    last_played = match.played_at

            if total_games == 0:
                continue

            # Calculer le rating global : moyenne de tous les ratings du joueur
            ratings_sum = 0.0
            ratings_count = 0

            # Ratings individuels (1v1, 1v2, 2v3, 3v3)
            individual_ratings = db.query(models.Rating).filter_by(player_id=player.id).all()
            for rating in individual_ratings:
                if (rating.games or 0) > 0:
                    ratings_sum += rating.rating
                    ratings_count += 1

            # Ratings d'équipes (2v2)
            team_memberships = (
                db.query(models.TeamMember)
                .filter(models.TeamMember.player_id == player.id)
                .all()
            )
            for tm in team_memberships:
                team_ratings = (
                    db.query(models.TeamRating)
                    .filter(models.TeamRating.team_id == tm.team_id)
                    .all()
                )
                for tr in team_ratings:
                    if (tr.games or 0) > 0:
                        ratings_sum += tr.rating
                        ratings_count += 1

            # Rating global = moyenne de tous les ratings
            if ratings_count > 0:
                global_rating = ratings_sum / ratings_count
            else:
                # Si pas de ratings, utiliser le rating initial
                global_rating = 1000.0

            win_rate = (total_wins / total_games * 100) if total_games > 0 else 0

            leaderboard.append(schemas.LeaderboardEntry(
                rank=0,
                entity_name=player.name,
                entity_id=player.id,
                entity_type="player",
                rating=global_rating,
                games=total_games,
                wins=total_wins,
                losses=total_losses,
                win_rate=win_rate,
                streak=0,
                last_played=last_played
            ))

        # Trier par rating décroissant
        leaderboard.sort(key=lambda x: x.rating, reverse=True)

        # Mettre à jour les rangs et limiter
        for idx, entry in enumerate(leaderboard[:limit], 1):
            entry.rank = idx

        leaderboard = leaderboard[:limit]
    
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
    payload: dict = Body(...),
    db: Session = Depends(get_db)
):
    format = payload.get("format")
    players_a = payload.get("players_a", [])
    players_b = payload.get("players_b", [])
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

@app.delete("/admin/matches/{match_id}")
def delete_match(match_id: int, token: str, db: Session = Depends(get_db)):
    """Supprimer un match (admin) puis recalculer les ELO."""
    check_admin(token)

    match = db.query(models.Match).filter_by(id=match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match introuvable")

    # Supprime le match (MatchPlayer en cascade)
    db.delete(match)
    db.commit()

    # Recalcul global
    rebuild_ratings(db)
    return {"status": "ok", "message": "Match supprimé et ELO recalculés"}

@app.post("/admin/rebuild-ratings")
def rebuild_ratings_endpoint(token: str, db: Session = Depends(get_db)):
    """Reconstruire tous les ratings ELO (admin)"""
    check_admin(token)
    rebuild_ratings(db)
    return {"status": "ok", "message": "Ratings recalculés avec succès"}

@app.delete("/admin/players/{player_id}")
def delete_player(player_id: int, token: str, db: Session = Depends(get_db)):
    """Supprimer un joueur (admin) : matches impliqués + ratings + équipes si orphelines."""
    check_admin(token)

    player = db.query(models.Player).filter_by(id=player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Joueur introuvable")

    # 1) supprimer tous les matchs où il figure
    link_rows = db.query(models.MatchPlayer).filter_by(player_id=player_id).all()
    match_ids = {r.match_id for r in link_rows}
    if match_ids:
        db.query(models.Match).filter(models.Match.id.in_(match_ids)).delete(synchronize_session=False)

    # 2) supprimer le joueur (ratings + memberships en cascade)
    db.delete(player)

    # 3) optionnel: supprimer équipes 2v2 devenues orphelines
    # (si une équipe n'a plus 2 membres, on la supprime)
    lone_teams = (
        db.query(models.Team)
        .outerjoin(models.TeamMember, models.Team.id == models.TeamMember.team_id)
        .group_by(models.Team.id)
        .having(func.count(models.TeamMember.player_id) < 2)
        .all()
    )
    for t in lone_teams:
        db.delete(t)

    db.commit()

    # 4) rebuild ELO
    rebuild_ratings(db)
    return {"status": "ok", "message": "Joueur supprimé et ELO recalculés"}

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