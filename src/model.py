from __future__ import annotations
from enum import Enum
from typing import Dict, List
import aiohttp
import json
import os

class Config:
    CONFIG_FILE = "/app/config/config.secret.json"

    ban_api: str = "https://api.example.com/check/"

    @classmethod
    def load(cls) -> None:
        if not os.path.exists(cls.CONFIG_FILE):
            cls.save()
        else:
            with open(cls.CONFIG_FILE, "r") as f:
                data = json.load(f)
                cls.ban_api = data.get("ban_api", "")

    @classmethod
    def save(cls) -> None:
        data = {
            "ban_api": cls.ban_api,
        }
        with open(cls.CONFIG_FILE, "w") as f:
            json.dump(data, f)

class PlayerInferState(Enum):
    INFER = 0
    ALLOWLIST = 1
    BLOCKLIST = 2

class GlobalStats:
    STATS_FILE = "/app/config/global_stats.json"

    total_checks: int = 0
    total_german: int = 0
    total_banned: int = 0
    total_cost: int = 0

    @classmethod
    def load_stats(cls) -> None:
        if not os.path.exists(cls.STATS_FILE):
            cls.save_stats()
        else:
            with open(cls.STATS_FILE, "r") as f:
                data = json.load(f)
                cls.total_checks = data.get("checks", 0)
                cls.total_german = data.get("german", 0)
                cls.total_banned = data.get("banned", 0)
                cls.total_cost = data.get("cost", 0)

    @classmethod
    def save_stats(cls) -> None:
        data = {
            "checks": cls.total_checks,
            "german": cls.total_german,
            "banned": cls.total_banned,
            "cost": cls.total_cost,
        }
        with open(cls.STATS_FILE, "w") as f:
            json.dump(data, f)

class Player:
    PLAYER_STORAGE = "/app/config/players.json"
    ALL: Dict[str, Player] = {}

    uuid: str
    last_name: str

    infer_state: int
    language: str
    infer_reason: str
    cooldown_since: int

    # Only used for preventing double-counting of stats
    was_banned: bool

    def __init__(self, uuid: str, profile) -> None:
        self.uuid = uuid
        self.last_name = profile.get("last_name", "")
        self.infer_state = profile.get("infer_state", PlayerInferState.INFER)
        self.language = profile.get("language", "unknown")
        self.infer_reason = profile.get("infer_reason", "")
        self.cooldown_since = profile.get("cooldown_since", 0)
        self.was_banned = profile.get("was_banned", False)

    def language_source(self) -> str:
        if self.infer_state == PlayerInferState.ALLOWLIST:
            return "database"
        elif self.infer_state == PlayerInferState.BLOCKLIST:
            return "blocklist"
        else:
            return "infer"

    async def is_banned(self, checker: User) -> bool:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{Config.ban_api}{self.uuid}") as resp:
                data = await resp.json()
        if data != []:
            if not self.was_banned:
                GlobalStats.total_banned += 1
                checker.total_banned += 1
            self.was_banned = True
            return True
        return False

    async def infer_language(self, checker: User) -> None:
        # TODO inc global stats & user stats
        self.language = "german"
        self.infer_reason = "weil ich es sage wallah"
        pass # TODO

    def dump(self):
        return {
            "last_name": self.last_name,
            "infer_state": self.infer_state,
            "language": self.language,
            "infer_reason": self.infer_reason,
            "cooldown_since": self.cooldown_since,
            "was_banned": self.was_banned,
        }

    @classmethod
    def load_players(cls) -> None:
        if not os.path.exists(cls.PLAYER_STORAGE):
            cls.save_players()
        else:
            with open(cls.PLAYER_STORAGE, "r") as f:
                data = json.load(f)
                cls.ALL = {}
                for uuid, prof in data.items():
                    cls.ALL[uuid] = Player(uuid, prof)

    @classmethod
    def save_players(cls) -> None:
        data = {}
        for uuid, player in cls.ALL.items():
            data[uuid] = player.dump()
        with open(cls.PLAYER_STORAGE, "w") as f:
            json.dump(data, f)

class User:
    USERS_FILE = "/app/config/users.json"
    ALL: List[User] = []

    name: str
    perms: List[str]
    key: str

    total_checks: int
    total_german: int
    total_banned: int
    total_cost: int

    def __init__(self, profile) -> None:
        self.name = profile.get("name", "<unknown>")
        self.perms = profile.get("permissions", [])
        self.key = profile.get("key", "")
        stats = profile.get("stats", {})
        self.total_checks = stats.get("checks", 0)
        self.total_german = stats.get("german", 0)
        self.total_banned = stats.get("banned", 0)
        self.total_cost = stats.get("cost", 0)

    def has_perm(self, needed: str) -> bool:
        return needed in self.perms

    def dump(self, include_secrets: bool):
        res = {
            "name": self.name,
            "permissions": self.perms,
            "stats": {
                "checks": self.total_checks,
                "german": self.total_german,
                "banned": self.total_banned,
                "cost": self.total_cost,
            },
        }
        if include_secrets:
            res["key"] = self.key
        return res

    @classmethod
    def load_users(cls) -> None:
        if not os.path.exists(cls.USERS_FILE):
            raise Exception("no users.json")
        with open(cls.USERS_FILE, "r") as f:
            data = json.load(f)
            cls.ALL = []
            for prof in data:
                cls.ALL.append(User(prof))

    @classmethod
    def save_users(cls) -> None:
        data = []
        for user in cls.ALL:
            data.append(user.dump(include_secrets=True))
        with open(cls.USERS_FILE, "w") as f:
            json.dump(data, f)
