"""
游戏内NPC社会关系与阵营系统 - 验收测试
运行方式：python -m pytest tests/test_faction_system.py -q
共 15 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world.faction_system import FactionSystem


class TestFactionSystem:
    def setup_method(self):
        self.system = FactionSystem()

    # ---------------- 社会关系图：有类型和强度 ----------------
    def test_case_01(self):
        # NPC之间可以建立关系，且关系带类型
        s = self.system
        s.add_relationship("npc_a", "npc_b", "friend", 80)
        rel = s.get_relationship("npc_a", "npc_b")
        assert rel is not None
        assert rel["type"] == "friend"

    def test_case_02(self):
        # 支持朋友、敌人、家人、师徒四种关系类型
        s = self.system
        s.add_relationship("npc_a", "npc_b", "friend", 60)
        s.add_relationship("npc_a", "npc_c", "enemy", 70)
        s.add_relationship("npc_a", "npc_d", "family", 90)
        s.add_relationship("npc_a", "npc_e", "mentor", 50)
        graph = s.social_graph("npc_a")
        assert graph["npc_b"]["type"] == "friend"
        assert graph["npc_c"]["type"] == "enemy"
        assert graph["npc_d"]["type"] == "family"
        assert graph["npc_e"]["type"] == "mentor"

    def test_case_03(self):
        # 关系有强度，关系好和关系坏可以区分
        s = self.system
        s.add_relationship("npc_a", "npc_b", "friend", 90)
        s.add_relationship("npc_a", "npc_c", "friend", 20)
        graph = s.social_graph("npc_a")
        assert graph["npc_b"]["strength"] > graph["npc_c"]["strength"]
        s.update_relationship("npc_a", "npc_c", 50)
        assert s.get_relationship("npc_a", "npc_c")["strength"] == 70

    # ---------------- 阵营管理：有成员和层级 ----------------
    def test_case_04(self):
        # 阵营有成员，能知道哪些NPC属于哪个阵营
        s = self.system
        s.create_faction("faction_red", "赤焰军")
        s.add_npc("npc_a", faction_id="faction_red")
        s.add_npc("npc_b", faction_id="faction_red")
        info = s.faction_management("faction_red")
        assert set(info["members"]) == {"npc_a", "npc_b"}
        assert s.npc_alignment("npc_a")["faction_id"] == "faction_red"

    def test_case_05(self):
        # 阵营有层级，阵营内有职位
        s = self.system
        s.create_faction("faction_red")
        s.add_npc("npc_a", faction_id="faction_red")
        s.add_npc("npc_b", faction_id="faction_red")
        s.set_rank("faction_red", "npc_a", "leader")
        s.set_rank("faction_red", "npc_b", "officer")
        info = s.faction_management("faction_red")
        assert info["leader"] == "npc_a"
        assert info["ranks"]["npc_b"] == "officer"
        assert info["hierarchy"]["leader"] == ["npc_a"]

    def test_case_06(self):
        # 层级有权力大小，职位权力严格递增
        s = self.system
        s.create_faction("faction_red")
        info = s.faction_management("faction_red")
        power = info["rank_power"]
        assert power["member"] < power["officer"] < power["elite"] < power["leader"]

    # ---------------- 声望：有等级和衰减 ----------------
    def test_case_07(self):
        # 做任务后声望会变化
        s = self.system
        s.create_faction("faction_red")
        before = s.reputation("player", "faction_red")["value"]
        s.change_reputation("player", "faction_red", 30, reason="完成任务")
        after = s.reputation("player", "faction_red")["value"]
        assert after == before + 30

    def test_case_08(self):
        # 声望有等级：中立、友好、尊敬、崇拜
        s = self.system
        s.create_faction("faction_red")
        assert s.reputation("player", "faction_red")["level"] == "中立"
        s.change_reputation("player", "faction_red", 20)
        assert s.reputation("player", "faction_red")["level"] == "友好"
        s.change_reputation("player", "faction_red", 30)
        assert s.reputation("player", "faction_red")["level"] == "尊敬"
        s.change_reputation("player", "faction_red", 30)
        assert s.reputation("player", "faction_red")["level"] == "崇拜"

    def test_case_09(self):
        # 声望有衰减，很久不做任务声望会下降
        s = self.system
        s.create_faction("faction_red")
        s.change_reputation("player", "faction_red", 50)
        s.update(10.0)
        value = s.reputation("player", "faction_red")["value"]
        assert 0 < value < 50

    # ---------------- 外交：有关系和事件 ----------------
    def test_case_10(self):
        # 阵营之间可以宣战
        s = self.system
        s.create_faction("faction_red")
        s.create_faction("faction_blue")
        s.declare_war("faction_red", "faction_blue")
        assert s.diplomacy("faction_red", "faction_blue") == "war"
        assert s.diplomacy("faction_blue", "faction_red") == "war"

    def test_case_11(self):
        # 阵营之间可以结盟，且外交关系可查询
        s = self.system
        s.create_faction("faction_red")
        s.create_faction("faction_blue")
        s.form_alliance("faction_red", "faction_blue")
        assert s.diplomacy("faction_red", "faction_blue") == "allied"
        relations = s.diplomacy("faction_red")
        assert relations["faction_blue"] == "allied"

    def test_case_12(self):
        # 外交有事件：宣战产生冲突事件，结盟产生合作事件
        s = self.system
        s.create_faction("faction_red")
        s.create_faction("faction_blue")
        s.create_faction("faction_green")
        s.declare_war("faction_red", "faction_blue")
        s.form_alliance("faction_red", "faction_green")
        events = s.diplomacy_events()
        types = {(e["type"], tuple(e["factions"])) for e in events}
        assert ("conflict", ("faction_blue", "faction_red")) in types
        assert ("cooperation", ("faction_green", "faction_red")) in types

    # ---------------- NPC立场：有变化和冲突 ----------------
    def test_case_13(self):
        # NPC立场可以变化：NPC会背叛或跳槽
        s = self.system
        s.create_faction("faction_red")
        s.create_faction("faction_blue")
        s.add_npc("npc_a", faction_id="faction_red")
        s.change_alignment("npc_a", "faction_blue", reason="背叛")
        assert s.npc_alignment("npc_a")["faction_id"] == "faction_blue"
        assert "npc_a" not in s.faction_management("faction_red")["members"]
        assert "npc_a" in s.faction_management("faction_blue")["members"]

    def test_case_14(self):
        # 立场变化会被记录，且可检测个人与阵营的利益冲突
        s = self.system
        s.create_faction("faction_red")
        s.create_faction("faction_blue")
        s.add_npc("npc_a", faction_id="faction_red", loyalty=30)
        s.add_npc("npc_b", faction_id="faction_blue")
        s.add_relationship("npc_a", "npc_b", "family", 90)
        s.declare_war("faction_red", "faction_blue")
        conflict = s.evaluate_alignment_conflict("npc_a")
        assert conflict["has_conflict"] is True
        assert conflict["conflicts"][0]["other"] == "npc_b"
        s.change_alignment("npc_a", "faction_blue", reason="投奔家人")
        history = s.alignment_history("npc_a")
        assert len(history) == 1
        assert history[0]["from"] == "faction_red"
        assert history[0]["to"] == "faction_blue"

    def test_case_15(self):
        # 立场冲突会被处理：个人纽带强于忠诚则跳槽，忠诚强则留守
        s = self.system
        s.create_faction("faction_red")
        s.create_faction("faction_blue")
        # 纽带(90) > 忠诚(30)：背叛跳槽
        s.add_npc("npc_a", faction_id="faction_red", loyalty=30)
        s.add_npc("npc_b", faction_id="faction_blue")
        s.add_relationship("npc_a", "npc_b", "family", 90)
        s.declare_war("faction_red", "faction_blue")
        result = s.resolve_alignment_conflict("npc_a")
        assert result["action"] == "defect"
        assert s.npc_alignment("npc_a")["faction_id"] == "faction_blue"
        # 忠诚(95) > 纽带(60)：留守
        s.add_npc("npc_c", faction_id="faction_red", loyalty=95)
        s.add_npc("npc_d", faction_id="faction_blue")
        s.add_relationship("npc_c", "npc_d", "friend", 60)
        result = s.resolve_alignment_conflict("npc_c")
        assert result["action"] == "stay"
        assert s.npc_alignment("npc_c")["faction_id"] == "faction_red"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
