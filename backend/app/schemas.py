from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import List, Optional, Literal
from enum import Enum

class MatchFormat(str, Enum):
    ONE_V_ONE = "1v1"
    TWO_V_TWO = "2v2"
    THREE_V_THREE = "3v3"
    ONE_V_TWO = "1v2"
    TWO_V_THREE = "2v3"

class PlayerBase(BaseModel):
    name: str
    is_guest: bool = False

class PlayerCreate(PlayerBase):
    pass

class PlayerUpdate(BaseModel):
    name: Optional[str] = None
    is_guest: Optional[bool] = None

class Player(PlayerBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class TeamBase(BaseModel):
    name: str

class Team(TeamBase):
    id: int
    key: str
    created_at: datetime
    members: List[Player] = []
    
    class Config:
        from_attributes = True

class MatchCreate(BaseModel):
    format: MatchFormat
    players_a: List[int]
    players_b: List[int]
    winner_side: Literal["A", "B"]
    balls_remaining: int = Field(ge=0, le=7)
    foul_black: bool = False
    ranked: bool = True
    played_at: Optional[datetime] = None
    
    @validator('players_a', 'players_b')
    def validate_players(cls, v, values):
        if not v:
            raise ValueError("Au moins un joueur requis par équipe")
        return v

class MatchResponse(BaseModel):
    id: int
    format: str
    played_at: datetime
    balls_remaining: int
    winner_side: str
    foul_black: bool
    ranked: bool
    players_a: List[Player]
    players_b: List[Player]
    team_a: Optional[Team] = None
    team_b: Optional[Team] = None
    
    class Config:
        from_attributes = True

class RatingResponse(BaseModel):
    player_id: Optional[int] = None
    team_id: Optional[int] = None
    format: str
    rating: float
    games: int
    wins: int
    losses: int
    streak: int
    last_played: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class LeaderboardEntry(BaseModel):
    rank: int
    entity_name: str
    entity_id: int
    entity_type: Literal["player", "team"]
    rating: float
    games: int
    wins: int
    losses: int
    win_rate: float
    streak: int
    last_played: Optional[datetime] = None

class HeadToHeadStats(BaseModel):
    total_games: int
    side_a_wins: int
    side_b_wins: int
    last_5_results: List[str]  # ['W', 'L', 'W', 'W', 'L']
    avg_balls_remaining: float
    last_match_date: Optional[datetime] = None

class AdminLogin(BaseModel):
    pin: str

class AdminSettings(BaseModel):
    k_base: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    delta: Optional[float] = None
    initial_rating: Optional[float] = None
    team_2v2_seed: Optional[float] = None
    win_bonus: Optional[float] = None
    inflation: Optional[float] = None