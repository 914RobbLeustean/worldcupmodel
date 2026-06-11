"""ESPN summary parsing on synthetic payloads — no network."""

from typing import Any

import pytest

from wc26.data.espn import TOURNAMENTS, _is_extra_time, _parse_summary


def _payload(
    *,
    state: str = "post",
    status_name: str = "STATUS_FULL_TIME",
    detail: str = "FT",
    home: str = "Argentina",
    away: str = "France",
    home_score: int = 3,
    away_score: int = 3,
) -> dict[str, Any]:
    def competitor(side: str, name: str, score: int) -> dict[str, Any]:
        return {"homeAway": side, "score": score, "team": {"displayName": name}}

    def box(name: str, corners: str, yellows: str) -> dict[str, Any]:
        return {
            "team": {"displayName": name},
            "statistics": [
                {"name": "wonCorners", "displayValue": corners},
                {"name": "yellowCards", "displayValue": yellows},
                {"name": "redCards", "displayValue": "0"},
                {"name": "foulsCommitted", "displayValue": "20"},
            ],
        }

    return {
        "header": {
            "competitions": [
                {
                    "id": "633850",
                    "date": "2022-12-18T15:00Z",
                    "status": {"type": {"state": state, "name": status_name, "detail": detail}},
                    "competitors": [
                        competitor("home", home, home_score),
                        competitor("away", away, away_score),
                    ],
                }
            ]
        },
        "boxscore": {"teams": [box(home, "6", "5"), box(away, "5", "3")]},
        "gameInfo": {
            "officials": [{"fullName": "Szymon Marciniak", "position": {"displayName": "Referee"}}]
        },
    }


def test_parse_regular_match() -> None:
    row = _parse_summary(_payload(), TOURNAMENTS["wc2022"])
    assert row is not None
    assert (row["home_id"], row["away_id"]) == ("argentina", "france")
    assert (row["home_score"], row["away_score"]) == (3, 3)
    assert row["extra_time"] is False
    assert row["corners_home"] == 6.0
    assert row["yellows_away"] == 3.0
    assert row["referee"] == "Szymon Marciniak"


def test_parse_skips_unfinished() -> None:
    assert _parse_summary(_payload(state="in"), TOURNAMENTS["wc2026"]) is None


def test_extra_time_flagging() -> None:
    pens = _payload(status_name="STATUS_FINAL_PEN", detail="FT-Pens")
    row = _parse_summary(pens, TOURNAMENTS["wc2022"])
    assert row is not None and row["extra_time"] is True
    with pytest.raises(ValueError, match="unrecognized final status"):
        _is_extra_time({"name": "STATUS_SOMETHING_NEW", "detail": "??"}, "x")


def test_boxscore_team_mismatch_raises() -> None:
    payload = _payload()
    payload["boxscore"]["teams"][0]["team"]["displayName"] = "Atlantis"
    with pytest.raises(ValueError, match="matches neither"):
        _parse_summary(payload, TOURNAMENTS["wc2022"])
