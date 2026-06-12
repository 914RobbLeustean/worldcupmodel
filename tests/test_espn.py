"""ESPN summary parsing on synthetic payloads + stats-patch overlay (D027) —
no network."""

from pathlib import Path
from typing import Any

import pandas as pd
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
    winner: str | None = None,
) -> dict[str, Any]:
    def competitor(side: str, name: str, score: int) -> dict[str, Any]:
        row: dict[str, Any] = {"homeAway": side, "score": score, "team": {"displayName": name}}
        if winner is not None:
            row["winner"] = name == winner
        return row

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
    pens = _payload(status_name="STATUS_FINAL_PEN", detail="FT-Pens", winner="Argentina")
    row = _parse_summary(pens, TOURNAMENTS["wc2022"])
    assert row is not None and row["extra_time"] is True
    assert row["shootout_winner_id"] == "argentina"
    aet = _payload(status_name="STATUS_FINAL_AET", detail="AET", winner="Argentina")
    row_aet = _parse_summary(aet, TOURNAMENTS["wc2022"])
    assert row_aet is not None and row_aet["extra_time"] is True
    assert row_aet["shootout_winner_id"] is None  # decided in ET, not pens
    with pytest.raises(ValueError, match="unrecognized final status"):
        _is_extra_time({"name": "STATUS_SOMETHING_NEW", "detail": "??"}, "x")


def test_shootout_without_winner_flag_raises() -> None:
    pens = _payload(status_name="STATUS_FINAL_PEN", detail="FT-Pens")
    with pytest.raises(ValueError, match="penalty shootout"):
        _parse_summary(pens, TOURNAMENTS["wc2022"])


def test_boxscore_team_mismatch_raises() -> None:
    payload = _payload()
    payload["boxscore"]["teams"][0]["team"]["displayName"] = "Atlantis"
    with pytest.raises(ValueError, match="matches neither"):
        _parse_summary(payload, TOURNAMENTS["wc2022"])


# ------------------------------------------------ stats patch overlay (D027)


def _espn_frame() -> "pd.DataFrame":
    import pandas as pd

    from wc26.data.espn import MATCH_STATS_SCHEMA

    row: dict[str, object] = {
        "date": pd.Timestamp("2026-06-29"),  # ESPN UTC date
        "tournament": "FIFA World Cup",
        "event_id": "700001",
        "home_id": "argentina",
        "away_id": "mexico",
        "home_score": 1,
        "away_score": 1,
        "extra_time": True,
        "shootout_winner_id": None,
        "referee": "Ref A",
        **{
            f"{stat}_{side}": 5.0
            for stat in (
                "corners",
                "yellows",
                "reds",
                "fouls",
                "shots",
                "shots_on_target",
                "possession",
            )
            for side in ("home", "away")
        },
    }
    return MATCH_STATS_SCHEMA.validate(pd.DataFrame([row]))


def _write_patch(path: "Path", rows: list[str]) -> None:
    from wc26.data.manual import STATS_PATCH_COLUMNS

    path.write_text(",".join(STATS_PATCH_COLUMNS) + "\n" + "\n".join(rows) + "\n")


def test_patch_overrides_with_date_drift(tmp_path: "Path", monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch row dated one day off ESPN (D013) overrides fields, no duplicate."""
    from wc26.data import espn

    patch = tmp_path / "stats_patch.csv"
    # local date 06-28 vs ESPN 06-29; fills the missing shootout winner only
    _write_patch(
        patch,
        [
            "2026-06-28,argentina,mexico,FIFA World Cup,-1,-1,TRUE,argentina,"
            "-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,"
        ],
    )
    monkeypatch.setattr(espn, "STATS_PATCH", patch)
    out = espn._apply_stats_patch(_espn_frame())
    assert len(out) == 1
    assert out.iloc[0]["shootout_winner_id"] == "argentina"
    assert out.iloc[0]["corners_home"] == 5.0  # -1 never erases ESPN data
    assert out.iloc[0]["referee"] == "Ref A"


def test_patch_flipped_orientation_flips_sides(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    from wc26.data import espn

    patch = tmp_path / "stats_patch.csv"
    # entered as mexico v argentina: mexico 9 corners -> argentina side stays 5
    _write_patch(
        patch,
        ["2026-06-29,mexico,argentina,FIFA World Cup,-1,-1,,,9,4,-1,-1,-1,-1,-1,-1,-1,-1,"],
    )
    monkeypatch.setattr(espn, "STATS_PATCH", patch)
    out = espn._apply_stats_patch(_espn_frame())
    assert len(out) == 1
    assert out.iloc[0]["corners_away"] == 9.0  # mexico is ESPN's away side
    assert out.iloc[0]["corners_home"] == 4.0


def test_patch_appends_standalone_row_when_espn_never_served_it(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    from wc26.data import espn
    from wc26.data.espn import MATCH_STATS_SCHEMA

    patch = tmp_path / "stats_patch.csv"
    _write_patch(
        patch,
        ["2026-06-30,france,ghana,FIFA World Cup,2,2,TRUE,france,6,3,2,4,0,0,11,17,13,8,Ref B"],
    )
    monkeypatch.setattr(espn, "STATS_PATCH", patch)
    out = MATCH_STATS_SCHEMA.validate(espn._apply_stats_patch(_espn_frame()))
    assert len(out) == 2
    row = out[out["event_id"] == "manual:2026-06-30:france:ghana"].iloc[0]
    assert row["home_score"] == 2 and bool(row["extra_time"]) is True
    assert row["shootout_winner_id"] == "france"
    assert row["corners_home"] == 6.0 and row["shots_away"] == 8.0
    assert row["referee"] == "Ref B"


def test_standalone_patch_row_without_score_refused(
    tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
) -> None:
    from wc26.data import espn

    patch = tmp_path / "stats_patch.csv"
    _write_patch(
        patch,
        ["2026-06-30,france,ghana,FIFA World Cup,-1,-1,,,6,3,-1,-1,-1,-1,-1,-1,-1,-1,"],
    )
    monkeypatch.setattr(espn, "STATS_PATCH", patch)
    with pytest.raises(ValueError, match="standalone rows must carry the score"):
        espn._apply_stats_patch(_espn_frame())


def test_patch_with_old_header_refused(tmp_path: "Path", monkeypatch: pytest.MonkeyPatch) -> None:
    from wc26.data import espn

    patch = tmp_path / "stats_patch.csv"
    patch.write_text(
        "date,home_id,away_id,corners_home,corners_away,yellows_home,"
        "yellows_away,reds_home,reds_away,referee\n"
        "2026-06-29,argentina,mexico,7,3,2,3,0,1,Ref A\n"
    )
    monkeypatch.setattr(espn, "STATS_PATCH", patch)
    with pytest.raises(ValueError, match="columns must be"):
        espn._apply_stats_patch(_espn_frame())
