from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from backend.app.database import Base

class Player(Base):
    __tablename__ = "players"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    is_guest = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    ratings = relationship("Rating", back_populates="player", cascade="all, delete-orphan")
    team_memberships = relationship("TeamMember", back_populates="player")
    match_participations = relationship("MatchPlayer", back_populates="player")

class Team(Base):
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)  # Format: "12-34" (IDs triés)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relations
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    ratings = relationship("TeamRating", back_populates="team", cascade="all, delete-orphan")
    matches_as_a = relationship("Match", foreign_keys="Match.team_id_a", back_populates="team_a")
    matches_as_b = relationship("Match", foreign_keys="Match.team_id_b", back_populates="team_b")

class TeamMember(Base):
    __tablename__ = "team_members"
    
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    
    # Relations
    team = relationship("Team", back_populates="members")
    player = relationship("Player", back_populates="team_memberships")
    
    __table_args__ = (
        Index('idx_team_members_team', 'team_id'),
        Index('idx_team_members_player', 'player_id'),
    )

class Match(Base):
    __tablename__ = "matches"
    
    id = Column(Integer, primary_key=True, index=True)
    format = Column(String, nullable=False)  # '1v1', '2v2', '3v3', '1v2'
    played_at = Column(DateTime, nullable=False, index=True)
    balls_remaining = Column(Integer, nullable=False)  # 0-7
    winner_side = Column(String, nullable=False)  # 'A' ou 'B'
    foul_black = Column(Boolean, default=False)
    ranked = Column(Boolean, default=True)
    
    # Pour 2v2 uniquement
    team_id_a = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    team_id_b = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    team_a = relationship("Team", foreign_keys=[team_id_a], back_populates="matches_as_a")
    team_b = relationship("Team", foreign_keys=[team_id_b], back_populates="matches_as_b")
    players = relationship("MatchPlayer", back_populates="match", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_matches_teams', 'team_id_a', 'team_id_b'),
    )

class MatchPlayer(Base):
    __tablename__ = "match_players"
    
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    side = Column(String, nullable=False)  # 'A' ou 'B'
    
    # Relations
    match = relationship("Match", back_populates="players")
    player = relationship("Player", back_populates="match_participations")

class Rating(Base):
    __tablename__ = "ratings"
    
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)
    format = Column(String, primary_key=True)  # '1v1'
    rating = Column(Float, default=1000.0)
    games = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    streak = Column(Integer, default=0)  # Positif = victoires, Négatif = défaites
    last_played = Column(DateTime, nullable=True)
    
    # Relations
    player = relationship("Player", back_populates="ratings")
    
    __table_args__ = (
        UniqueConstraint('player_id', 'format', name='uq_player_format'),
    )

class TeamRating(Base):
    __tablename__ = "team_ratings"
    
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    format = Column(String, primary_key=True)  # '2v2'
    rating = Column(Float, default=1000.0)
    games = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    last_played = Column(DateTime, nullable=True)
    
    # Relations
    team = relationship("Team", back_populates="ratings")
    
    __table_args__ = (
        UniqueConstraint('team_id', 'format', name='uq_team_format'),
    )

class Setting(Base):
    __tablename__ = "settings"
    
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)  # 'create', 'update', 'delete'
    entity_type = Column(String, nullable=False)  # 'match', 'player', etc.
    entity_id = Column(Integer, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    user_info = Column(String, nullable=True)  # IP ou session info
    created_at = Column(DateTime, default=datetime.utcnow, index=True)