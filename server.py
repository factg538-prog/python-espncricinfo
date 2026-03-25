"""
Sports Adda67 — Live Cricket Overlay Server
Polls ESPN Cricinfo consumer API every 30s and serves data.json
"""

import os
import json
import time
import threading
import logging
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, Response
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("overlay")

app = Flask(__name__, static_folder="static")

# ─── CONFIG (set via Railway env vars) ───────────────────────────────────────
MATCH_ID   = int(os.getenv("MATCH_ID",   "0"))   # ESPN match objectId
SERIES_ID  = int(os.getenv("SERIES_ID",  "0"))   # ESPN series objectId
POLL_SEC   = int(os.getenv("POLL_SEC",   "20"))   # how often to refresh
PORT       = int(os.getenv("PORT",       "8080"))

# ─── ESPN HEADERS ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espncricinfo.com/",
    "Origin": "https://www.espncricinfo.com",
}

# Photo CDN helpers
def player_photo(pid):
    if pid:
        return f"https://p.espncdn.com/i/headshots/cricket/players/full/{pid}.png"
    return ""

def team_logo(tid):
    if tid:
        return f"https://p.espncdn.com/i/teamlogos/cricket/500/{tid}.png"
    return ""

# ─── ESPN API CALLS ────────────────────────────────────────────────────────────

def espn_get(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"ESPN fetch error {url}: {e}")
        return None


def get_live_matches():
    """Return list of {series_id, match_id, description} for currently live matches."""
    url = "https://hs-consumer-api.espncricinfo.com/v1/pages/home/matches?lang=en&matchType=live"
    data = espn_get(url)
    results = []
    try:
        for match in data["content"]["matches"]:
            try:
                results.append({
                    "match_id":   match["objectId"],
                    "series_id":  match["series"]["objectId"],
                    "description": match.get("description", ""),
                    "status":     match.get("statusText", ""),
                })
            except Exception:
                pass
    except Exception:
        pass
    return results


def get_match_home(series_id, match_id):
    url = (
        f"https://hs-consumer-api.espncricinfo.com/v1/pages/match/home"
        f"?lang=en&seriesId={series_id}&matchId={match_id}"
    )
    return espn_get(url)


def get_match_live(series_id, match_id):
    url = (
        f"https://hs-consumer-api.espncricinfo.com/v1/pages/match/live"
        f"?lang=en&seriesId={series_id}&matchId={match_id}"
    )
    return espn_get(url)


def get_match_comments(series_id, match_id, innings=1):
    url = (
        f"https://hs-consumer-api.espncricinfo.com/v1/pages/match/comments"
        f"?lang=en&seriesId={series_id}&matchId={match_id}"
        f"&innings={innings}&commentType=ALL&fromInningOver=-1&pageSize=10"
    )
    return espn_get(url)


def get_scorecard(series_id, match_id):
    url = (
        f"https://hs-consumer-api.espncricinfo.com/v1/pages/match/scorecard"
        f"?lang=en&seriesId={series_id}&matchId={match_id}"
    )
    return espn_get(url)


# ─── PARSER ───────────────────────────────────────────────────────────────────

def fmt_sr(val):
    try:
        return f"{float(val):.2f}"
    except Exception:
        return "0.00"

def fmt_rate(val):
    try:
        return f"{float(val):.2f}"
    except Exception:
        return "---"

def parse_match(series_id, match_id):
    """
    Pull all available ESPN data for a match and return the overlay data dict.
    """
    home_data  = get_match_home(series_id, match_id)
    live_data  = get_match_live(series_id, match_id)

    if not home_data and not live_data:
        return None

    result = {
        "match_id": match_id,
        "series_id": series_id,
        "team1": {},
        "team2": {},
        "crr": "---",
        "rrr": "---",
        "target": "---",
        "partnership": "0(0)",
        "last_wicket": "---",
        "match_status": "LIVE",
        "need": "",
        "venue": {},
        "last_over_balls": [],
        "current_over": 0,
        "current_ball": "",
        "last_updated": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "yet_to_bat": "---",
        "match_format": "T20",
        "batsman1": {},
        "batsman2": {},
        "bowler": {},
        "toss": "",
        "match_title": "",
        "innings_num": 1,
    }

    # ── HOME DATA (teams, venue, format, playing XI) ──────────────────────────
    try:
        match_info = home_data.get("match", {}) or {}
        series_info = home_data.get("series", {}) or {}
        content = home_data.get("content", {}) or {}

        # Format
        fmt = (match_info.get("internationalClassCard") or
               match_info.get("format") or "T20")
        result["match_format"] = str(fmt).upper()

        # Match title
        result["match_title"] = (
            content.get("cmsContent", {}).get("title", "") or
            match_info.get("title", "")
        )

        # Toss
        toss_text = match_info.get("tossText", "") or match_info.get("toss", "") or ""
        result["toss"] = toss_text

        # Venue
        ground = match_info.get("ground", {}) or {}
        result["venue"] = {
            "name": ground.get("longName", ground.get("name", "")),
            "city": (ground.get("town") or {}).get("name", ""),
        }

        # Status
        status_txt = match_info.get("statusText", "") or match_info.get("status", "")
        if status_txt:
            result["match_status"] = status_txt

        # Teams
        teams_raw = match_info.get("teams", []) or []
        team_players_raw = (
            content.get("matchPlayers", {}).get("teamPlayers", []) or []
        )

        # Build players-by-team lookup
        players_by_team = {}
        for tp in team_players_raw:
            oid = str(tp["team"]["objectId"])
            players_by_team[oid] = tp.get("players", [])

        def build_team_obj(t_raw):
            team = t_raw.get("team", {})
            oid  = str(team.get("objectId", ""))
            tid  = team.get("id")
            players_raw = players_by_team.get(oid, [])

            # Build playing XI
            p11 = []
            for p in players_raw:
                player = p.get("player", {})
                pid = player.get("objectId")
                role_map = {
                    "bat": "BATSMAN", "bowl": "BOWLER",
                    "all": "ALL-ROUNDER", "wk": "WICKET-KEEPER"
                }
                role_raw = (p.get("playerRoleType") or "").lower()
                role = role_map.get(role_raw, role_raw.upper() or "PLAYER")
                p11.append({
                    "name":             player.get("name", ""),
                    "full_name":        player.get("longName", ""),
                    "player_id":        pid,
                    "role":             role,
                    "photo":            player_photo(pid),
                    "is_captain":       bool(p.get("isCaptain")),
                    "is_wicketkeeper":  bool(p.get("isWicketKeeper")),
                })

            return {
                "name":      team.get("abbreviation") or team.get("name", "TM"),
                "full_name": team.get("longName") or team.get("name", "Team"),
                "team_id":   oid,
                "flag_img":  team_logo(oid),
                "score":     "---",
                "overs":     "",
                "playing11": p11,
            }

        if len(teams_raw) >= 2:
            result["team1"] = build_team_obj(teams_raw[0])
            result["team2"] = build_team_obj(teams_raw[1])
        elif len(teams_raw) == 1:
            result["team1"] = build_team_obj(teams_raw[0])

    except Exception as e:
        log.warning(f"Home data parse error: {e}")

    # ── LIVE DATA (scores, batsmen, bowler, over balls) ────────────────────────
    try:
        live_match  = live_data.get("match", {}) or {}
        live_content = live_data.get("content", {}) or {}

        # Update status from live
        live_status = live_match.get("statusText", "")
        if live_status:
            result["match_status"] = live_status

        # Innings list
        innings_list = live_content.get("innings", []) or []

        # Current / latest innings
        current_inn = None
        batting_inn_num = 0
        for i, inn in enumerate(innings_list, 1):
            if not inn.get("isCompleted", True) or i == len(innings_list):
                current_inn = inn
                batting_inn_num = i

        if current_inn is None and innings_list:
            current_inn = innings_list[-1]
            batting_inn_num = len(innings_list)

        result["innings_num"] = batting_inn_num

        if current_inn:
            runs     = current_inn.get("runs", 0) or 0
            wickets  = current_inn.get("wickets", 0) or 0
            overs    = current_inn.get("overs")
            crr      = current_inn.get("runRate") or current_inn.get("currentRunRate")
            rrr      = current_inn.get("requiredRunRate")
            target   = current_inn.get("target")
            extras   = current_inn.get("extras")

            # Score for the batting team
            score_str = f"{runs}-{wickets}"
            if overs is not None:
                overs_str = str(overs)
            else:
                overs_str = ""

            # Figure out which team is batting
            batting_oid = str((current_inn.get("team") or {}).get("objectId", ""))
            t1_oid = result["team1"].get("team_id", "")

            if batting_oid == t1_oid:
                result["team1"]["score"] = score_str
                result["team1"]["overs"] = overs_str
            else:
                result["team2"]["score"] = score_str
                result["team2"]["overs"] = overs_str

            # Previous innings score for the other team
            if batting_inn_num == 2 and len(innings_list) >= 1:
                prev = innings_list[0]
                prev_runs    = prev.get("runs", 0) or 0
                prev_wickets = prev.get("wickets", 0) or 0
                prev_overs   = prev.get("overs", "")
                prev_oid     = str((prev.get("team") or {}).get("objectId", ""))
                prev_score   = f"{prev_runs}-{prev_wickets}"
                if prev_oid == t1_oid:
                    result["team1"]["score"] = prev_score
                    result["team1"]["overs"] = str(prev_overs)
                else:
                    result["team2"]["score"] = prev_score
                    result["team2"]["overs"] = str(prev_overs)

            # CRR / RRR
            if crr is not None:
                result["crr"] = fmt_rate(crr)
            if rrr is not None:
                result["rrr"] = fmt_rate(rrr)
            if target:
                result["target"] = str(target)

            # Need (balls left + runs needed)
            if target and rrr:
                try:
                    runs_needed = int(target) - runs
                    overs_done  = float(overs or 0)
                    sched       = 20  # default T20; adjust for ODI
                    balls_left  = max(0, int((sched - overs_done) * 6))
                    if runs_needed > 0 and balls_left > 0:
                        result["need"] = f"Need {runs_needed} off {balls_left} balls"
                except Exception:
                    pass

            # Current batsmen
            batsmen_raw = current_inn.get("inningBatsmen", []) or []
            on_crease = [b for b in batsmen_raw if b.get("battedType") == "yes" and not b.get("isOut")]
            if not on_crease:
                on_crease = [b for b in batsmen_raw if not b.get("isOut")][:2]

            def build_bat(b):
                player = b.get("player") or {}
                pid    = player.get("objectId")
                return {
                    "name":      player.get("name", "BATSMAN"),
                    "full_name": player.get("longName", ""),
                    "player_id": pid,
                    "photo":     player_photo(pid),
                    "runs":      b.get("runs", 0),
                    "balls":     b.get("balls", 0),
                    "fours":     b.get("fours", 0),
                    "sixes":     b.get("sixes", 0),
                    "sr":        fmt_sr(b.get("strikerate")),
                    "on_strike": bool(b.get("isStriker") or b.get("onStrike")),
                    "minutes":   b.get("minutes", 0),
                }

            if len(on_crease) >= 1:
                b1 = build_bat(on_crease[0])
                b2 = build_bat(on_crease[1]) if len(on_crease) >= 2 else {}
                # Ensure striker is batsman1
                if b2 and b2.get("on_strike"):
                    b1, b2 = b2, b1
                result["batsman1"] = b1
                result["batsman2"] = b2

            # Partnership
            partnership = live_content.get("partnership") or current_inn.get("currentPartnership", {})
            if isinstance(partnership, dict):
                p_runs  = partnership.get("runs", 0) or 0
                p_balls = partnership.get("balls", 0) or 0
                result["partnership"] = f"{p_runs}({p_balls})"
            elif isinstance(partnership, str) and partnership:
                result["partnership"] = partnership

            # Current bowler
            bowlers_raw = current_inn.get("inningBowlers", []) or []
            # Current bowler is the last one who hasn't finished an over or has highest recent over
            cur_bowler = None
            for bw in reversed(bowlers_raw):
                if bw.get("isCurrent") or bw.get("isCurrentBowler"):
                    cur_bowler = bw
                    break
            if not cur_bowler and bowlers_raw:
                cur_bowler = bowlers_raw[-1]

            if cur_bowler:
                player = cur_bowler.get("player") or {}
                pid    = player.get("objectId")
                overs_b = cur_bowler.get("overs")
                result["bowler"] = {
                    "name":      player.get("name", "BOWLER"),
                    "full_name": player.get("longName", ""),
                    "player_id": pid,
                    "photo":     player_photo(pid),
                    "wickets":   cur_bowler.get("wickets", 0),
                    "runs":      cur_bowler.get("conceded", cur_bowler.get("runs", 0)),
                    "overs":     str(overs_b) if overs_b is not None else "0",
                    "maidens":   cur_bowler.get("maidens", 0),
                    "economy":   fmt_sr(cur_bowler.get("economy")),
                    "wides":     cur_bowler.get("wides", 0),
                    "no_balls":  cur_bowler.get("noballs", 0),
                }

            # Fall of wickets → last wicket
            fow = current_inn.get("inningFallOfWickets", []) or []
            if fow:
                last_fw = fow[-1]
                fw_name  = (last_fw.get("player") or {}).get("name", "")
                fw_runs  = last_fw.get("runs", "")
                fw_balls = last_fw.get("balls", "")
                fw_over  = last_fw.get("overs", "")
                if fw_name:
                    result["last_wicket"] = f"{fw_name} {fw_runs}({fw_balls}) ov {fw_over}"

            # Yet to bat
            yet_raw = [
                b for b in batsmen_raw
                if b.get("battedType") == "no" or not b.get("battedType")
            ]
            if yet_raw:
                result["yet_to_bat"] = ", ".join(
                    (b.get("player") or {}).get("name", "")
                    for b in yet_raw if (b.get("player") or {}).get("name")
                )

        # ── THIS OVER BALLS from live commentary ──────────────────────────────
        try:
            live_over = live_content.get("liveInning", {}) or {}
            over_data = live_over.get("thisOver", []) or []
            if not over_data:
                # Alternative path
                over_data = live_content.get("thisOver", []) or []

            balls_out = []
            for delivery in over_data:
                ev = delivery.get("event", delivery.get("shortText", ""))
                if ev is None:
                    ev = ""
                ev = str(ev).strip()
                # Map to display code
                if ev.upper() in ("W", "WICKET"):
                    balls_out.append("W")
                elif ev.upper() in ("WD", "WIDE"):
                    balls_out.append("WD")
                elif ev.upper() in ("NB", "NO BALL", "NOBALL"):
                    balls_out.append("NB")
                elif ev.isdigit():
                    balls_out.append(ev)
                else:
                    # Try runs field
                    r = delivery.get("runs", delivery.get("batsmanRuns"))
                    balls_out.append(str(r) if r is not None else "0")

            result["last_over_balls"] = balls_out
            if balls_out:
                result["current_ball"] = balls_out[-1]

            # Current over number
            over_num = (
                live_over.get("overNumber") or
                live_content.get("currentOver") or
                (current_inn.get("overs", 0) if current_inn else 0)
            )
            try:
                result["current_over"] = int(float(str(over_num).split(".")[0]))
            except Exception:
                pass

        except Exception as e:
            log.debug(f"Over balls parse: {e}")

    except Exception as e:
        log.warning(f"Live data parse error: {e}")

    # ── Populate previous innings if not already done ─────────────────────────
    try:
        if innings_list and len(innings_list) >= 2:
            for i, inn in enumerate(innings_list):
                inn_oid = str((inn.get("team") or {}).get("objectId", ""))
                r = inn.get("runs", 0) or 0
                w = inn.get("wickets", 0) or 0
                ov = inn.get("overs", "")
                score_s = f"{r}-{w}"
                is_completed = inn.get("isCompleted", False)
                if not is_completed:
                    continue
                t1_oid = result["team1"].get("team_id", "")
                if inn_oid == t1_oid:
                    if result["team1"]["score"] == "---":
                        result["team1"]["score"] = score_s
                        result["team1"]["overs"] = str(ov)
                else:
                    if result["team2"]["score"] == "---":
                        result["team2"]["score"] = score_s
                        result["team2"]["overs"] = str(ov)
    except Exception:
        pass

    result["last_updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    return result


# ─── STATE ────────────────────────────────────────────────────────────────────

_state = {
    "data": {},
    "lock": threading.Lock(),
    "match_id":  MATCH_ID,
    "series_id": SERIES_ID,
    "last_fetch": 0,
    "live_matches": [],
    "live_list_ts": 0,
}


def refresh_live_list():
    """Refresh the list of live matches every 5 minutes."""
    now = time.time()
    if now - _state["live_list_ts"] < 300:
        return
    matches = get_live_matches()
    if matches:
        _state["live_matches"] = matches
        _state["live_list_ts"] = now
        log.info(f"Live matches found: {len(matches)}")
        for m in matches:
            log.info(f"  [{m['match_id']}] {m['description']} — {m['status']}")


def do_poll():
    """Single poll cycle."""
    # If no match configured, find the first live match
    if not _state["match_id"]:
        refresh_live_list()
        if _state["live_matches"]:
            lm = _state["live_matches"][0]
            _state["match_id"]  = lm["match_id"]
            _state["series_id"] = lm["series_id"]
            log.info(f"Auto-selected match {lm['match_id']}")

    mid = _state["match_id"]
    sid = _state["series_id"]
    if not mid or not sid:
        log.warning("No match_id/series_id configured yet")
        return

    parsed = parse_match(sid, mid)
    if parsed:
        with _state["lock"]:
            _state["data"] = parsed
        log.info(
            f"Updated: {parsed.get('team1',{}).get('name','')} "
            f"{parsed.get('team1',{}).get('score','')} vs "
            f"{parsed.get('team2',{}).get('name','')} "
            f"{parsed.get('team2',{}).get('score','')}"
        )
    else:
        log.warning(f"parse_match returned None for {mid}/{sid}")


def background_poll():
    """Background thread that polls on interval."""
    while True:
        try:
            do_poll()
        except Exception as e:
            log.error(f"Poll exception: {e}")
        time.sleep(POLL_SEC)


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/data.json")
def data_json():
    with _state["lock"]:
        d = dict(_state["data"])
    resp = Response(
        json.dumps(d, ensure_ascii=False),
        mimetype="application/json"
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/live-matches")
def live_matches_route():
    refresh_live_list()
    return jsonify(_state["live_matches"])


@app.route("/set-match")
def set_match():
    """Hot-swap match: /set-match?match_id=xxx&series_id=yyy"""
    from flask import request
    mid = request.args.get("match_id", type=int)
    sid = request.args.get("series_id", type=int)
    if mid and sid:
        _state["match_id"]  = mid
        _state["series_id"] = sid
        _state["data"]      = {}
        do_poll()
        return jsonify({"status": "ok", "match_id": mid, "series_id": sid})
    return jsonify({"error": "provide match_id and series_id"}), 400


@app.route("/force-refresh")
def force_refresh():
    do_poll()
    return jsonify({"status": "refreshed"})


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


# ─── STARTUP ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Initial fetch before serving
    log.info(f"Starting — MATCH_ID={MATCH_ID} SERIES_ID={SERIES_ID} POLL={POLL_SEC}s")
    try:
        do_poll()
    except Exception as e:
        log.warning(f"Initial poll failed: {e}")

    # Start background poller
    t = threading.Thread(target=background_poll, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
