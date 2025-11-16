from quart import Quart, g, jsonify, request
from model import GlobalStats, User
import json
import os

app = Quart(__name__)

# Enforce only one worker
worker_count = os.environ.get("HYPERCORN_WORKER_ID")
if worker_count is not None:
    if int(worker_count) != 0:
        raise RuntimeError("This app must be run with exactly one worker (HYPERCORN_WORKER_ID != 0)")

def check_permissions(*args):
    def w1(f):
        def w2(*args, **kwargs):
            key = request.headers.get("X-Api-Key")
            if not key:
                return jsonify({"error": 401, "message": "unauthorized (api key missing)"}), 401
            for user in User.ALL:
                if user.key == key:
                    break
            else:
                return jsonify({"error": 401, "message": "unauthorized"}), 401
            g.user = user
            for needed in args:
                if not user.has_perm(needed):
                    return jsonify({"error": 403, "message": f"forbidden {needed}"}), 403
            return f(*args, **kwargs)
        w2.__name__ = f.__name__
        return w2
    return w1

@app.route("/")
async def index():
    return "https://www.youtube.com/watch?v=3X-iqFRGqbc"

@app.route("/whoami")
@check_permissions()
async def whoami():
    return jsonify(g.user.dump(include_secrets=False))

@app.route("/stats")
@check_permissions()
async def stats():
    return jsonify({
        "personal": {
            "checks": {
                "total": g.user.total_checks,
                "german": g.user.total_german,
                "banned": g.user.total_banned,
            },
            "cost": g.user.total_cost,
        },
        "global": {
            "checks": {
                "total": GlobalStats.total_checks,
                "german": GlobalStats.total_german,
                "banned": GlobalStats.total_banned,
            },
            "cost": GlobalStats.total_cost,
        },
    })

@app.route("/check/<uuid>/<username>")
@check_permissions()
async def check(uuid, username):
    if username == "TheRat":
        return jsonify({
            "language": {
                "verdict": "english",
                "source": "llm",
                "reason": "Das Wort 'Rat' beschreibt den Inhalt dieses Moduls. Hihi :)",
            },
            "banned": False,
            "cooldown": 139,
            "guild": "BaaDz9",
        })
    elif username == "DieRatte":
        return jsonify({
            "language": {
                "verdict": "german",
                "source": "database",
                "reason": "Gesehen auf: deutscher-server.mc:25565",
            },
            "banned": False,
            "cooldown": 0,
            "guild": None,
        })
    elif username == "BoeserBube":
        return jsonify({
            "language": {
                "verdict": "german",
                "source": "database",
                "reason": "Verifiziert auf GooDz-Discord",
            },
            "banned": True,
            "cooldown": 0,
            "guild": None,
        })
    elif username == "arrayen":
        return jsonify({
            "language": {
                "verdict": "unknown",
                "source": "database",
                "reason": "Manueller Eintrag (Blacklist)",
            },
            "banned": False,
            "cooldown": 0,
            "guild": "GooDz4",
        })
    else:
        return jsonify({
            "error": 404,
            "message": "Spieler nicht gefunden",
        }), 404

@app.before_serving
async def create_runtime():
    User.load_users()
    print(f"[GDA] Loaded {len(User.ALL)} users")
    print("[GDA] Runtime created")
