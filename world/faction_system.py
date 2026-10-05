"""
游戏内NPC社会关系与阵营系统 - 核心模块

五大子系统：
- social_graph()       社会关系图：NPC之间的关系，带类型（朋友/敌人/家人/师徒）和强度
- faction_management() 阵营管理：阵营成员与层级（职位和权力）
- reputation()         声望：数值、等级（中立/友好/尊敬/崇拜）与随时间衰减
- diplomacy()          外交：阵营之间的关系（结盟/宣战）与外交事件
- npc_alignment()      NPC立场：可变化（背叛/跳槽），并处理个人与阵营的利益冲突
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# 社会关系类型：朋友、敌人、家人、师徒
RELATIONSHIP_TYPES = ("friend", "enemy", "family", "mentor")

# 阵营层级（权力由低到高）
RANKS = ("member", "officer", "elite", "leader")
RANK_POWER = {rank: index for index, rank in enumerate(RANKS)}

# 阵营间外交关系
DIPLOMATIC_RELATIONS = ("allied", "friendly", "neutral", "hostile", "war")

# 声望数值范围
REPUTATION_MIN = -100.0
REPUTATION_MAX = 100.0

# 声望等级阈值（下限, 等级名），从高到低匹配
REPUTATION_LEVELS = (
    (70.0, "崇拜"),
    (40.0, "尊敬"),
    (10.0, "友好"),
    (-10.0, "中立"),
    (-50.0, "冷淡"),
    (float("-inf"), "敌对"),
)


def reputation_level(value: float) -> str:
    """根据声望数值返回声望等级。"""
    for threshold, level in REPUTATION_LEVELS:
        if value >= threshold:
            return level
    return "敌对"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class Config:
    pass


class FactionSystem:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        # 声望每秒向中立（0）衰减的速率
        self._decay_rate = float(self.config.get("reputation_decay_rate", 1.0))
        # 触发个人/阵营利益冲突的关系强度阈值
        self._conflict_threshold = float(self.config.get("conflict_threshold", 50.0))
        self._time = 0.0
        self._state = {}
        self._npcs: Dict[str, Dict] = {}
        self._relationships: Dict[Tuple[str, str], Dict] = {}
        self._factions: Dict[str, Dict] = {}
        self._reputation: Dict[Tuple[str, str], float] = {}
        self._diplomacy: Dict[frozenset, str] = {}
        self._events: List[Dict] = []
        self._history: List[Dict] = []

    # ------------------------------------------------------------------
    # 基础注册
    # ------------------------------------------------------------------
    def add_npc(self, npc_id: str, name: Optional[str] = None,
                faction_id: Optional[str] = None, loyalty: float = 50.0) -> Dict:
        """注册NPC，可同时指定所属阵营与忠诚度。"""
        npc = {
            "npc_id": npc_id,
            "name": name or npc_id,
            "faction_id": None,
            "loyalty": _clamp(float(loyalty), 0.0, 100.0),
        }
        self._npcs[npc_id] = npc
        if faction_id is not None:
            self.add_member(faction_id, npc_id)
        return npc

    def create_faction(self, faction_id: str, name: Optional[str] = None) -> Dict:
        """创建阵营。"""
        faction = self._factions.get(faction_id)
        if faction is None:
            faction = {
                "faction_id": faction_id,
                "name": name or faction_id,
                "members": {},  # npc_id -> rank
            }
            self._factions[faction_id] = faction
        return faction

    # ------------------------------------------------------------------
    # 社会关系图：关系有类型（朋友/敌人/家人/师徒）和强度
    # ------------------------------------------------------------------
    def add_relationship(self, npc_a: str, npc_b: str,
                         rel_type: str, strength: float = 50.0) -> Dict:
        """建立从 npc_a 到 npc_b 的有向社会关系。"""
        if rel_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"未知关系类型: {rel_type}")
        for npc_id in (npc_a, npc_b):
            if npc_id not in self._npcs:
                self.add_npc(npc_id)
        rel = {
            "from": npc_a,
            "to": npc_b,
            "type": rel_type,
            "strength": _clamp(float(strength), 0.0, 100.0),
        }
        self._relationships[(npc_a, npc_b)] = rel
        return rel

    def get_relationship(self, npc_a: str, npc_b: str) -> Optional[Dict]:
        """查询 npc_a 对 npc_b 的关系，不存在时返回 None。"""
        return self._relationships.get((npc_a, npc_b))

    def update_relationship(self, npc_a: str, npc_b: str, delta: float) -> Optional[Dict]:
        """调整关系强度（正数变好，负数变坏），强度限制在 [0, 100]。"""
        rel = self._relationships.get((npc_a, npc_b))
        if rel is None:
            return None
        rel["strength"] = _clamp(rel["strength"] + float(delta), 0.0, 100.0)
        return rel

    def social_graph(self, npc_id: Optional[str] = None) -> Dict:
        """返回社会关系图。

        指定 npc_id 时返回该NPC的全部关系 {对方: {type, strength}}；
        否则返回整张图 {npc: {对方: {type, strength}}}。
        """
        graph: Dict[str, Dict[str, Dict]] = {}
        for (a, b), rel in self._relationships.items():
            graph.setdefault(a, {})[b] = {"type": rel["type"], "strength": rel["strength"]}
        if npc_id is not None:
            return graph.get(npc_id, {})
        return graph

    # ------------------------------------------------------------------
    # 阵营管理：阵营有成员和层级（职位与权力）
    # ------------------------------------------------------------------
    def add_member(self, faction_id: str, npc_id: str, rank: str = "member") -> Dict:
        """将NPC加入阵营并指定职位（NPC同时只能属于一个阵营）。"""
        if rank not in RANKS:
            raise ValueError(f"未知职位: {rank}")
        faction = self._factions.get(faction_id) or self.create_faction(faction_id)
        if npc_id not in self._npcs:
            self.add_npc(npc_id)
        old_faction = self._npcs[npc_id]["faction_id"]
        if old_faction and old_faction in self._factions:
            self._factions[old_faction]["members"].pop(npc_id, None)
        faction["members"][npc_id] = rank
        self._npcs[npc_id]["faction_id"] = faction_id
        return faction

    def set_rank(self, faction_id: str, npc_id: str, rank: str) -> None:
        """调整阵营内成员的职位。"""
        if rank not in RANKS:
            raise ValueError(f"未知职位: {rank}")
        faction = self._factions[faction_id]
        if npc_id not in faction["members"]:
            raise KeyError(f"{npc_id} 不属于阵营 {faction_id}")
        faction["members"][npc_id] = rank

    def faction_management(self, faction_id: Optional[str] = None) -> Dict:
        """返回阵营管理信息：成员列表与层级结构（按权力排序）。"""
        def describe(fid: str) -> Dict:
            faction = self._factions[fid]
            hierarchy: Dict[str, List[str]] = {rank: [] for rank in RANKS}
            for member_id, rank in faction["members"].items():
                hierarchy[rank].append(member_id)
            leader = hierarchy["leader"][0] if hierarchy["leader"] else None
            return {
                "faction_id": fid,
                "name": faction["name"],
                "members": sorted(faction["members"].keys()),
                "ranks": dict(faction["members"]),
                "hierarchy": hierarchy,
                "leader": leader,
                "rank_power": dict(RANK_POWER),
            }

        if faction_id is not None:
            return describe(faction_id)
        return {fid: describe(fid) for fid in self._factions}

    # ------------------------------------------------------------------
    # 声望：有数值、等级和随时间衰减
    # ------------------------------------------------------------------
    def reputation(self, entity_id: str, faction_id: str) -> Dict:
        """查询某实体（玩家或NPC）在某阵营的声望数值与等级。"""
        value = self._reputation.get((entity_id, faction_id), 0.0)
        return {
            "entity_id": entity_id,
            "faction_id": faction_id,
            "value": value,
            "level": reputation_level(value),
        }

    def change_reputation(self, entity_id: str, faction_id: str,
                          amount: float, reason: str = "") -> Dict:
        """改变声望（如完成任务），数值限制在 [-100, 100]。"""
        key = (entity_id, faction_id)
        value = _clamp(self._reputation.get(key, 0.0) + float(amount),
                       REPUTATION_MIN, REPUTATION_MAX)
        self._reputation[key] = value
        return self.reputation(entity_id, faction_id)

    # ------------------------------------------------------------------
    # 外交：阵营之间有关系（结盟/宣战）和事件
    # ------------------------------------------------------------------
    @staticmethod
    def _diplomacy_key(faction_a: str, faction_b: str) -> frozenset:
        return frozenset((faction_a, faction_b))

    def set_diplomacy(self, faction_a: str, faction_b: str, relation: str) -> Dict:
        """设置两个阵营之间的外交关系，并记录外交事件。"""
        if relation not in DIPLOMATIC_RELATIONS:
            raise ValueError(f"未知外交关系: {relation}")
        if faction_a == faction_b:
            raise ValueError("阵营不能与自己建立外交关系")
        key = self._diplomacy_key(faction_a, faction_b)
        old = self._diplomacy.get(key, "neutral")
        self._diplomacy[key] = relation
        if relation != old:
            if relation == "war":
                event_type = "conflict"      # 冲突事件
            elif relation == "allied":
                event_type = "cooperation"   # 合作事件
            else:
                event_type = "relation_change"
            self._events.append({
                "type": event_type,
                "factions": sorted((faction_a, faction_b)),
                "from": old,
                "to": relation,
                "time": self._time,
            })
        return {"factions": sorted((faction_a, faction_b)), "relation": relation}

    def declare_war(self, faction_a: str, faction_b: str) -> Dict:
        """宣战。"""
        return self.set_diplomacy(faction_a, faction_b, "war")

    def form_alliance(self, faction_a: str, faction_b: str) -> Dict:
        """结盟。"""
        return self.set_diplomacy(faction_a, faction_b, "allied")

    def diplomacy(self, faction_a: Optional[str] = None,
                  faction_b: Optional[str] = None):
        """查询外交关系。

        给定两个阵营返回关系字符串；给定一个阵营返回其全部对外关系；
        都不给则返回所有阵营间关系。
        """
        if faction_a is not None and faction_b is not None:
            return self._diplomacy.get(
                self._diplomacy_key(faction_a, faction_b), "neutral")
        if faction_a is not None:
            result = {}
            for key, relation in self._diplomacy.items():
                if faction_a in key:
                    other = next(fid for fid in key if fid != faction_a)
                    result[other] = relation
            return result
        return {tuple(sorted(key)): relation
                for key, relation in self._diplomacy.items()}

    def diplomacy_events(self) -> List[Dict]:
        """返回已发生的外交事件（冲突、合作、关系变化）。"""
        return list(self._events)

    # ------------------------------------------------------------------
    # NPC立场：可变化（背叛/跳槽），并处理个人与阵营的利益冲突
    # ------------------------------------------------------------------
    def npc_alignment(self, npc_id: str) -> Dict:
        """查询NPC当前立场（所属阵营与忠诚度）。"""
        npc = self._npcs[npc_id]
        return {
            "npc_id": npc_id,
            "faction_id": npc["faction_id"],
            "loyalty": npc["loyalty"],
        }

    def set_loyalty(self, npc_id: str, loyalty: float) -> None:
        """设置NPC对当前阵营的忠诚度。"""
        self._npcs[npc_id]["loyalty"] = _clamp(float(loyalty), 0.0, 100.0)

    def change_alignment(self, npc_id: str, new_faction_id: str,
                         reason: str = "") -> Dict:
        """NPC改变立场（背叛/跳槽），加入新阵营并记录历史。"""
        npc = self._npcs[npc_id]
        old_faction = npc["faction_id"]
        if new_faction_id not in self._factions:
            self.create_faction(new_faction_id)
        self.add_member(new_faction_id, npc_id)
        entry = {
            "npc_id": npc_id,
            "from": old_faction,
            "to": new_faction_id,
            "reason": reason,
            "time": self._time,
        }
        self._history.append(entry)
        return entry

    def alignment_history(self, npc_id: Optional[str] = None) -> List[Dict]:
        """返回立场变化历史。"""
        if npc_id is None:
            return list(self._history)
        return [e for e in self._history if e["npc_id"] == npc_id]

    def evaluate_alignment_conflict(self, npc_id: str) -> Dict:
        """评估NPC个人利益（强社会关系）与阵营利益（外交敌对）的冲突。

        当NPC与敌对阵营（hostile/war）成员存在足够强的朋友/家人/师徒
        关系时，视为个人利益与阵营利益冲突。
        """
        npc = self._npcs[npc_id]
        faction_id = npc["faction_id"]
        conflicts = []
        if faction_id is not None:
            for other_id, rel in self.social_graph(npc_id).items():
                if rel["type"] not in ("friend", "family", "mentor"):
                    continue
                if rel["strength"] < self._conflict_threshold:
                    continue
                other = self._npcs.get(other_id)
                if not other or not other["faction_id"] \
                        or other["faction_id"] == faction_id:
                    continue
                relation = self.diplomacy(faction_id, other["faction_id"])
                if relation in ("hostile", "war"):
                    conflicts.append({
                        "other": other_id,
                        "bond_type": rel["type"],
                        "strength": rel["strength"],
                        "other_faction": other["faction_id"],
                        "diplomacy": relation,
                    })
        return {
            "npc_id": npc_id,
            "faction_id": faction_id,
            "loyalty": npc["loyalty"],
            "has_conflict": bool(conflicts),
            "conflicts": conflicts,
        }

    def resolve_alignment_conflict(self, npc_id: str) -> Dict:
        """处理立场冲突：个人纽带强于忠诚度则背叛跳槽，否则留守并疏远对方。"""
        evaluation = self.evaluate_alignment_conflict(npc_id)
        if not evaluation["has_conflict"]:
            return {"npc_id": npc_id, "action": "stay", "reason": "no_conflict"}
        strongest = max(evaluation["conflicts"], key=lambda c: c["strength"])
        if strongest["strength"] > evaluation["loyalty"]:
            self.change_alignment(npc_id, strongest["other_faction"],
                                  reason="personal_bond_over_loyalty")
            return {
                "npc_id": npc_id,
                "action": "defect",
                "to": strongest["other_faction"],
                "bond": strongest,
            }
        # 忠诚度压过个人纽带：留守，但个人关系被削弱
        self.update_relationship(npc_id, strongest["other"],
                                 -strongest["strength"] / 2)
        return {
            "npc_id": npc_id,
            "action": "stay",
            "reason": "loyalty_over_bond",
            "bond": strongest,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def update(self, dt: float):
        """推进时间：声望随时间向中立（0）衰减。"""
        dt = float(dt)
        if dt <= 0:
            return
        self._time += dt
        decay = self._decay_rate * dt
        for key, value in list(self._reputation.items()):
            if value > 0:
                self._reputation[key] = max(0.0, value - decay)
            elif value < 0:
                self._reputation[key] = min(0.0, value + decay)

    def reset(self):
        self._state = {}
        self._npcs = {}
        self._relationships = {}
        self._factions = {}
        self._reputation = {}
        self._diplomacy = {}
        self._events = []
        self._history = []
        self._time = 0.0
