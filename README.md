# Sports Adda67 — Live Cricket Overlay

A **Railway-deployable** live cricket score overlay that auto-polls ESPN Cricinfo every 20 seconds and serves a broadcast-quality HTML overlay that updates every 2.5 seconds.

## Features

- 🏏 **Auto-detects live matches** from ESPN Cricinfo
- 📸 **Player photos** pulled automatically from ESPN CDN
- 🏴 **Team logos** from ESPN CDN
- ⚡ **Real-time data**: scores, overs, CRR, RRR, target, partnership
- 🎯 **Bowler stats**: figures, economy, wides, maidens
- 🏏 **Batsman stats**: runs, balls, 4s, 6s, SR, minutes on crease
- ⚾ **This over balls**: animated ball-by-ball display
- 📋 **Playing XI**: full squad with photos and roles
- 📍 **Venue + Toss + Format** info strip
- 🎬 **SIX / FOUR / WICKET** celebration animations
- ✏️ **Manual override** panel for when API is slow
- 🔄 **Hot-swap match** via Admin panel or URL

---

## Deploy on Railway

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "Sports Adda67 overlay"
git remote add origin https://github.com/YOUR_USER/cricket-overlay.git
git push -u origin main
```

### Step 2 — Create Railway Project
1. Go to [railway.app](https://railway.app)
2. Click **New Project → Deploy from GitHub repo**
3. Select your repo

### Step 3 — Set Environment Variables (optional)
In Railway dashboard → **Variables**:

| Variable | Description | Default |
|---|---|---|
| `MATCH_ID` | ESPN match objectId (leave 0 to auto-detect live) | `0` |
| `SERIES_ID` | ESPN series objectId | `0` |
| `POLL_SEC` | How often to poll ESPN (seconds) | `20` |

> If `MATCH_ID=0`, the server auto-picks the first currently live match.

### Step 4 — Done!
Your overlay will be live at `https://your-app.railway.app`

---

## Usage in OBS / Streamlabs

1. Add a **Browser Source**
2. Set URL to your Railway URL
3. Set Width: **1280**, Height: **720**
4. Enable "Shutdown source when not visible" for performance

---

## Admin Panel

Press **Ctrl+S** or click the ⚙️ button (bottom right) to open the Admin Panel.

### Admin Features:
- **📡 Browse Live Matches** — auto-fetches live ESPN matches, click to switch
- **Set Match** — enter Match ID + Series ID manually
- **🔄 Force Refresh** — immediately re-poll ESPN
- **Flag Images** — upload custom team flags/logos
- **Manual Override** — override any field if ESPN data is stale
- **Test Animations** — trigger SIX/FOUR/WICKET effects

### Find Match IDs:
Visit any ESPN Cricinfo match page URL:
```
https://www.espncricinfo.com/series/series-name-SERIESID/team-vs-team-MATCHID/live-cricket-score
```
Extract the numbers at the end.

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Serve the overlay HTML |
| `GET /data.json` | Current match data as JSON |
| `GET /live-matches` | List of currently live ESPN matches |
| `GET /set-match?match_id=X&series_id=Y` | Switch to a different match |
| `GET /force-refresh` | Trigger immediate ESPN poll |

---

## Local Development

```bash
pip install -r requirements.txt
python server.py
# Open http://localhost:8080
```

---

## Data Structure (`data.json`)

```json
{
  "team1": {"name": "IND", "full_name": "India", "score": "205-4", "overs": "18.2", "flag_img": "...", "playing11": [...]},
  "team2": {"name": "PAK", "full_name": "Pakistan", "score": "---", "flag_img": "...", "playing11": [...]},
  "crr": "11.18", "rrr": "9.50",
  "target": "220", "partnership": "68(42)",
  "last_wicket": "Rohit b Shaheen 45(28)",
  "match_status": "India need 15 off 10 balls",
  "need": "Need 15 off 10 balls",
  "venue": {"name": "Wankhede Stadium", "city": "Mumbai"},
  "toss": "India won toss, chose to bat",
  "match_format": "T20I",
  "innings_num": 2,
  "last_over_balls": ["1","0","6","4","W","2"],
  "current_over": 18,
  "current_ball": "2",
  "last_updated": "14:32:11 UTC",
  "yet_to_bat": "Pant, Hardik, Bumrah",
  "batsman1": {"name": "Kohli", "runs": 78, "balls": 52, "fours": 6, "sixes": 4, "sr": "150.00", "on_strike": true, "photo": "...", "minutes": 58},
  "batsman2": {"name": "Jadeja", "runs": 32, "balls": 20, "fours": 2, "sixes": 2, "sr": "160.00", "on_strike": false, "photo": "..."},
  "bowler": {"name": "Shaheen", "wickets": 2, "runs": 38, "overs": "3.2", "maidens": 0, "economy": "11.45", "wides": 3, "photo": "..."}
}
```
