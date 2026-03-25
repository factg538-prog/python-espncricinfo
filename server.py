"""
Sports Adda67 — Live Cricket Overlay Server
Scrapes Cricbuzz for live data — no API key needed, unlimited & free.
"""

import os
import json
import time
import threading
import logging
import re
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, Response, request
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("overlay")

app = Flask(__name__, static_folder="static")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
POLL_SEC  = int(os.getenv("POLL_SEC",  "6"))
PORT      = int(os.getenv("PORT",      "8080"))
MATCH_URL = os.getenv("MATCH_URL", "")   # full cricbuzz match URL e.g. https://www.cricbuzz.com/live-cricket-scores/12345/...

# ─── HEADERS ──────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cricbuzz.com/",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def cb_get(url, timeout=15):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning(f"Fetch error {url}: {e}")
        return None


def extract_match_id(url):
    """Extract numeric match ID from cricbuzz URL."""
    m = re.search(r'/live-cricket-scores/(\d+)', url)
    return m.group(1) if m else None


def get_live_matches():
    """Scrape cricbuzz homepage for live matches."""
    html = cb_get("https://www.cricbuzz.com/cricket-match/live-scores")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    for a in soup.select("a[href*='/live-cricket-scores/']"):
        href = a.get("href", "")
        mid = extract_match_id(href)
        if mid and href not in [m["url"] for m in matches]:
            title = a.get_text(strip=True)
            if title:
                matches.append({
                    "match_id": mid,
                    "url": "https://www.cricbuzz.com" + href if href.startswith("/") else href,
                    "title": title,
                })
    # deduplicate by match_id
    seen = set()
    unique = []
    for m in matches:
        if m["match_id"] not in seen:
            seen.add(m["match_id"])
            unique.append(m)
    return unique


def parse_score_text(text):
    """Parse '123/4 (20.0 Ov)' style strings."""
    if not text:
        return "---", ""
    text = text.strip()
    ov_match = re.search(r'\(([^)]+Ov[^)]*)\)', text, re.IGNORECASE)
    overs = ov_match.group(1) if ov_match else ""
    score = re.sub(r'\s*\([^)]*Ov[^)]*\)', '', text).strip()
    return score or "---", overs


def scrape_match(match_url):
    """Scrape a cricbuzz live scores page and return overlay data."""
    html = cb_get(match_url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    result = {
        "match_id":       extract_match_id(match_url) or "",
        "match_url":      match_url,
        "team1":          {"name": "---", "full_name": "---", "score": "---", "overs": "", "flag_img": "", "playing11": []},
        "team2":          {"name": "---", "full_name": "---", "score": "---", "overs": "", "flag_img": "", "playing11": []},
        "crr":            "---",
        "rrr":            "---",
        "target":         "---",
        "partnership":    "0(0)",
        "last_wicket":    "---",
        "match_status":   "LIVE",
        "need":           "",
        "venue":          {"name": "", "city": ""},
        "last_over_balls": [],
        "current_over":   0,
        "current_ball":   "",
        "last_updated":   datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
        "yet_to_bat":     "---",
        "match_format":   "T20",
        "batsman1":       {},
        "batsman2":       {},
        "bowler":         {},
        "toss":           "",
        "match_title":    "",
        "innings_num":    1,
    }

    # ── Match title ──────────────────────────────────────────────────────────
    title_el = soup.select_one("h1.cb-nav-hdr") or soup.select_one(".cb-mtch-info-tm") or soup.select_one("title")
    if title_el:
        result["match_title"] = title_el.get_text(strip=True).replace(" - Cricbuzz.com", "")

    # ── Status text ──────────────────────────────────────────────────────────
    status_el = soup.select_one(".cb-text-live") or soup.select_one(".cb-text-complete") or soup.select_one(".cb-text-inprogress")
    if status_el:
        result["match_status"] = status_el.get_text(strip=True)

    # ── Teams & scores ────────────────────────────────────────────────────────
    # Cricbuzz scorecard block
    score_blocks = soup.select(".cb-lv-scrs-well")
    team_els = soup.select(".cb-hmscg-tm-nm")
    score_els = soup.select(".cb-hmscg-tm-scr")

    # Try another selector
    if not team_els:
        team_els = soup.select(".cb-lv-scrs-well .cb-lv-tm-nm")
    if not score_els:
        score_els = soup.select(".cb-lv-scrs-well .cb-lv-scrs")

    teams_found = []
    for i, t in enumerate(team_els[:2]):
        name = t.get_text(strip=True)
        score_text = score_els[i].get_text(strip=True) if i < len(score_els) else "---"
        score, overs = parse_score_text(score_text)
        teams_found.append({"name": name[:3].upper() if len(name) > 3 else name.upper(),
                             "full_name": name, "score": score, "overs": overs,
                             "flag_img": "", "playing11": []})

    if len(teams_found) >= 1:
        result["team1"] = teams_found[0]
    if len(teams_found) >= 2:
        result["team2"] = teams_found[1]

    # ── CRR / RRR ─────────────────────────────────────────────────────────────
    crr_el = soup.find(string=re.compile(r'CRR\s*:', re.I))
    if crr_el:
        m = re.search(r'CRR\s*:\s*([\d.]+)', str(crr_el), re.I)
        if m:
            result["crr"] = m.group(1)

    rrr_el = soup.find(string=re.compile(r'RRR\s*:', re.I))
    if rrr_el:
        m = re.search(r'RRR\s*:\s*([\d.]+)', str(rrr_el), re.I)
        if m:
            result["rrr"] = m.group(1)

    # Try combined run rate block
    rr_block = soup.select_one(".cb-lv-run-rate")
    if rr_block:
        txt = rr_block.get_text()
        crr_m = re.search(r'CRR\s*:\s*([\d.]+)', txt, re.I)
        rrr_m = re.search(r'RRR\s*:\s*([\d.]+)', txt, re.I)
        if crr_m:
            result["crr"] = crr_m.group(1)
        if rrr_m:
            result["rrr"] = rrr_m.group(1)

    # ── Batsmen ───────────────────────────────────────────────────────────────
    bat_rows = soup.select(".cb-lv-bat-card tr") or soup.select(".cb-ltst-wgt-hdr + div tr")
    batters = []
    for row in bat_rows:
        cells = row.select("td")
        if len(cells) >= 5:
            name = cells[0].get_text(strip=True)
            if name and name not in ("Batter", "Batsmen", "DNB", "Yet to bat"):
                try:
                    batters.append({
                        "name":      name,
                        "full_name": name,
                        "runs":      int(cells[1].get_text(strip=True) or 0),
                        "balls":     int(cells[2].get_text(strip=True) or 0),
                        "fours":     int(cells[3].get_text(strip=True) or 0),
                        "sixes":     int(cells[4].get_text(strip=True) or 0),
                        "sr":        cells[5].get_text(strip=True) if len(cells) > 5 else "0.00",
                        "on_strike": "*" in cells[0].get_text(),
                        "photo":     "",
                        "player_id": "",
                        "minutes":   0,
                    })
                except Exception:
                    pass

    if len(batters) >= 1:
        result["batsman1"] = batters[0]
    if len(batters) >= 2:
        result["batsman2"] = batters[1]

    # ── Bowler ────────────────────────────────────────────────────────────────
    bowl_rows = soup.select(".cb-lv-bowl-card tr") or []
    bowlers = []
    for row in bowl_rows:
        cells = row.select("td")
        if len(cells) >= 5:
            name = cells[0].get_text(strip=True)
            if name and name not in ("Bowler", "Bowlers"):
                try:
                    bowlers.append({
                        "name":      name,
                        "full_name": name,
                        "overs":     cells[1].get_text(strip=True),
                        "maidens":   int(cells[2].get_text(strip=True) or 0),
                        "runs":      int(cells[3].get_text(strip=True) or 0),
                        "wickets":   int(cells[4].get_text(strip=True) or 0),
                        "economy":   cells[5].get_text(strip=True) if len(cells) > 5 else "0.00",
                        "wides":     0,
                        "no_balls":  0,
                        "photo":     "",
                        "player_id": "",
                    })
                except Exception:
                    pass
    if bowlers:
        result["bowler"] = bowlers[-1]

    # ── This over balls ───────────────────────────────────────────────────────
    over_el = soup.select_one(".cb-lv-lgnd-col") or soup.select_one(".cb-col-100.cb-col.cb-ltst-wgt-hdr")
    if over_el:
        balls = []
        for span in over_el.select("span, div.cb-lv-ball-txt"):
            txt = span.get_text(strip=True)
            if txt in ("0","1","2","3","4","6","W","Wd","Nb","•") or txt.isdigit():
                balls.append(txt.replace("Wd","WD").replace("Nb","NB"))
        if balls:
            result["last_over_balls"] = balls
            result["current_ball"] = balls[-1]

    # ── Partnership ───────────────────────────────────────────────────────────
    prtn_el = soup.find(string=re.compile(r'Partnership', re.I))
    if prtn_el:
        m = re.search(r'(\d+)\s*\((\d+)', str(prtn_el.parent))
        if m:
            result["partnership"] = f"{m.group(1)}({m.group(2)})"

    # ── Venue ─────────────────────────────────────────────────────────────────
    venue_el = soup.select_one(".cb-mtch-info-itm")
    if venue_el:
        result["venue"]["name"] = venue_el.get_text(strip=True)

    result["last_updated"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    return result


# ─── STATE ────────────────────────────────────────────────────────────────────
_state = {
    "data":         {},
    "lock":         threading.Lock(),
    "match_url":    MATCH_URL,
    "live_matches": [],
    "live_list_ts": 0,
}


def refresh_live_list():
    now = time.time()
    if now - _state["live_list_ts"] < 300:
        return
    matches = get_live_matches()
    if matches:
        _state["live_matches"] = matches
        _state["live_list_ts"] = now
        log.info(f"Live matches: {len(matches)}")
        for m in matches:
            log.info(f"  [{m['match_id']}] {m['title']} — {m['url']}")


def do_poll():
    if not _state["match_url"]:
        refresh_live_list()
        if _state["live_matches"]:
            _state["match_url"] = _state["live_matches"][0]["url"]
            log.info(f"Auto-selected: {_state['match_url']}")

    url = _state["match_url"]
    if not url:
        log.warning("No match URL configured yet")
        return

    parsed = scrape_match(url)
    if parsed:
        with _state["lock"]:
            _state["data"] = parsed
        log.info(
            f"Updated: {parsed['team1']['name']} {parsed['team1']['score']} "
            f"vs {parsed['team2']['name']} {parsed['team2']['score']} | "
            f"CRR:{parsed['crr']}"
        )
    else:
        log.warning(f"scrape_match returned None for {url}")


def background_poll():
    while True:
        try:
            do_poll()
        except Exception as e:
            log.error(f"Poll error: {e}")
        time.sleep(POLL_SEC)


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/data.json")
def data_json():
    with _state["lock"]:
        d = dict(_state["data"])
    resp = Response(json.dumps(d, ensure_ascii=False), mimetype="application/json")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/live-matches")
def live_matches_route():
    refresh_live_list()
    return jsonify(_state["live_matches"])


@app.route("/set-match")
def set_match():
    url = request.args.get("url", "")
    if url:
        _state["match_url"] = url
        _state["data"] = {}
        do_poll()
        return jsonify({"status": "ok", "url": url})
    return jsonify({"error": "provide url param"}), 400


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
    log.info(f"Starting — MATCH_URL={MATCH_URL} POLL={POLL_SEC}s")
    try:
        do_poll()
    except Exception as e:
        log.warning(f"Initial poll failed: {e}")
    t = threading.Thread(target=background_poll, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
