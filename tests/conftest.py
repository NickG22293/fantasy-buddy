"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def nhl_player_landing():
    """Minimal valid NHL /v1/player/{id}/landing response."""
    return {
        "playerId": 8478402,
        "firstName": {"default": "Connor"},
        "lastName": {"default": "McDavid"},
        "currentTeamAbbrev": "EDM",
        "position": "C",
        "sweaterNumber": 97,
        "featuredStats": {
            "regularSeasonStatsObj": {
                "season": {
                    "gamesPlayed": 58,
                    "goals": 32,
                    "assists": 62,
                    "points": 94,
                    "plusMinus": 22,
                    "pim": 24,
                    "powerPlayPoints": 28,
                    "shots": 178,
                    "shootingPctg": 0.180,
                    "avgToi": "21:34",
                },
                "career": {
                    "gamesPlayed": 630,
                    "goals": 312,
                    "assists": 678,
                    "points": 990,
                },
            }
        },
        "last5Games": [
            {
                "gameDate": "2025-03-20",
                "opponentAbbrev": "CGY",
                "goals": 1,
                "assists": 2,
                "points": 3,
                "toi": "22:10",
            }
        ],
    }


@pytest.fixture
def nhl_search_results():
    return [
        {
            "playerId": 8478402,
            "name": "Connor McDavid",
            "positionCode": "C",
            "teamAbbrev": "EDM",
            "active": True,
        }
    ]
