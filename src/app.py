from quart import Quart, g, jsonify, request
from model import Config, GlobalStats, Player, PlayerInferState, User
import json
import os
import time

app = Quart(__name__)

COOLDOWN_TIME = 12 * 60 * 60  # 12 hours
# COOLDOWN_TIME = 10 * 60  # 10 minutes (for testing)

# Enforce only one worker
worker_count = os.environ.get("HYPERCORN_WORKER_ID")
if worker_count is not None:
    if int(worker_count) != 0:
        raise RuntimeError("This app must be run with exactly one worker (HYPERCORN_WORKER_ID != 0)")

def check_permissions(*perms):
    def w1(f):
        async def w2(*args, **kwargs):
            key = request.headers.get("X-Api-Key")
            if not key:
                return jsonify({"error": 401, "message": "unauthorized (api key missing)"}), 401
            for user in User.ALL:
                if user.key == key:
                    break
            else:
                return jsonify({"error": 401, "message": "unauthorized"}), 401
            g.user = user
            for needed in perms:
                if not user.has_perm(needed):
                    return jsonify({"error": 403, "message": f"forbidden {needed}"}), 403
            return await f(*args, **kwargs)
        w2.__name__ = f.__name__
        return w2
    return w1

def verify_uuid_username(f):
    async def w(uuid, username, *args, **kwargs):
        uuid = uuid.replace("-", "").lower()
        if len(uuid) != 32 or len(username) < 2 or len(username) > 16:
            return jsonify({
                "error": 400,
                "message": "invalid uuid/username",
            }), 400
        return await f(uuid=uuid, username=username, *args, **kwargs)
    w.__name__ = f.__name__
    return w

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

@app.post("/allowlist/<uuid>/<username>")
@check_permissions("allowlist")
@verify_uuid_username
async def allowlist(uuid, username):
    reason = await request.get_data()
    reason = reason.decode("utf-8").strip()[:128]

    if uuid in Player.ALL:
        player = Player.ALL[uuid]
        player.last_name = username
    else:
        player = Player(uuid, {"last_name": username})
        Player.ALL[uuid] = player

    player.infer_state = PlayerInferState.ALLOWLIST
    player.language = "german"
    player.infer_reason = reason
    print(f"[GDA] {uuid} ({username}): Added to allow list: '{reason}'")
    return jsonify({"success": True})

@app.post("/blocklist/<uuid>/<username>")
@check_permissions("blocklist")
@verify_uuid_username
async def blocklist(uuid, username):
    reason = await request.get_data()
    reason = reason.decode("utf-8").strip()[:128]

    if uuid in Player.ALL:
        player = Player.ALL[uuid]
        player.last_name = username
    else:
        player = Player(uuid, {"last_name": username})
        Player.ALL[uuid] = player

    player.infer_state = PlayerInferState.BLOCKLIST
    player.language = "unknown"
    player.infer_reason = reason
    print(f"[GDA] {uuid} ({username}): Added to block list: '{reason}'")
    return jsonify({"success": True})

@app.route("/check/<uuid>/<username>")
@check_permissions()
@verify_uuid_username
async def check(uuid, username):
    first_check = False
    if uuid in Player.ALL:
        player = Player.ALL[uuid]
        if player.last_name != username:
            print(f"[GDA] {uuid} ({username}): Old name {player.last_name}")
            player.last_name = username
            try:
                await player.infer_language(g.user)
            except Exception as e:
                print(f"[GDA] Error inferring language for {username}: {e}")
                return jsonify({
                    "error": 500,
                    "message": "Could not infer language",
                }), 500
    else:
        print(f"[GDA] {uuid} ({username}): First check")
        first_check = True
        GlobalStats.total_checks += 1
        g.user.total_checks += 1

        player = Player(uuid, {"last_name": username})
        Player.ALL[uuid] = player
        try:
            await player.infer_language(g.user)
        except Exception as e:
            print(f"[GDA] Error inferring language for {username}: {e}")
            return jsonify({
                "error": 500,
                "message": "Could not infer language",
            }), 500

    if player.language != "german":
        print(f"[GDA] {uuid} ({username}): Non-German: {player.language}")
        return jsonify({
            "language": {
                "verdict": player.language,
                "source": player.language_source(),
                "reason": player.infer_reason,
            },
            "first_check": first_check,
        })

    try:
        is_banned = await player.is_banned(g.user)
    except Exception as e:
        print(f"[GDA] Error checking ban status for {username}: {e}")
        return jsonify({
            "error": 500,
            "message": "Could not check ban status",
        }), 500
    if is_banned:
        print(f"[GDA] {uuid} ({username}): Banned")
        return jsonify({
            "language": {
                "verdict": player.language,
                "source": player.language_source(),
                "reason": player.infer_reason,
            },
            "banned": True,
            "first_check": first_check,
        })

    now = int(time.time())
    if now - player.cooldown_since < COOLDOWN_TIME:
        print(f"[GDA] {uuid} ({username}): On Cooldown")
        return jsonify({
            "language": {
                "verdict": player.language,
                "source": player.language_source(),
                "reason": player.infer_reason,
            },
            "banned": False,
            "cooldown": player.cooldown_since + COOLDOWN_TIME - now,
            "first_check": first_check,
        })
    player.cooldown_since = now

    print(f"[GDA] {uuid} ({username}): OK")
    return jsonify({
            "language": {
                "verdict": player.language,
                "source": player.language_source(),
                "reason": player.infer_reason,
            },
            "banned": False,
            "cooldown": 0,
            "first_check": first_check,
    })

@app.before_serving
async def create_runtime():
    Config.load()
    GlobalStats.load_stats()
    Player.load_players()
    User.load_users()
    print(f"[GDA] Loaded {len(User.ALL)} users, {len(Player.ALL)} players")
    print("[GDA] Runtime created")

@app.after_serving
async def destroy_runtime():
    print("[GDA] Destroying runtime...")
    User.save_users()
    Player.save_players()
    GlobalStats.save_stats()
    Config.save()
    print("[GDA] Shutdown!")
