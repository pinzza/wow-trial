#!/usr/bin/env python3
"""P1 档案加载器单元测试"""

import os
import tempfile
import unittest
from pathlib import Path

from core.profile_loader import Profile, load_profile, resolve_progress_db_path


class TestProfileLoader(unittest.TestCase):
    """Profile 加载与校验测试"""

    @classmethod
    def setUpClass(cls):
        """创建临时 profiles 目录，写入三个真实档案的副本"""
        cls.temp_dir = Path(tempfile.mkdtemp())
        cls._write_profile(cls.temp_dir, "dongrou", DONGROU_YAML)
        cls._write_profile(cls.temp_dir, "taozi", TAOZI_YAML)
        cls._write_profile(cls.temp_dir, "meishu", MEISHU_YAML)

    @classmethod
    def _write_profile(cls, base_dir: Path, profile_id: str, content: str):
        path = base_dir / f"{profile_id}.yaml"
        path.write_text(content, encoding="utf-8")

    def test_load_dongrou_profile(self):
        """加载示例学员档案，校验 role=dps, benchmark_char=qingxingood, wiki_prefix=qingxin"""
        p = load_profile("dongrou", self.temp_dir)
        self.assertEqual(p.id, "dongrou")
        self.assertEqual(p.name, "示例学员")
        self.assertEqual(p.role, "dps")
        self.assertEqual(p.spec, "冰法")
        self.assertEqual(p.benchmark_char, "qingxingood")
        self.assertEqual(p.wiki_prefix, "qingxin")
        self.assertEqual(p.function, "coaching")
        self.assertEqual(p.comparison, "benchmark")

    def test_load_meishu_profile(self):
        """加载梅叔档案，校验 role=tank, benchmark_char=硬玩复仇绿色"""
        p = load_profile("meishu", self.temp_dir)
        self.assertEqual(p.id, "meishu")
        self.assertEqual(p.name, "梅夫三拳")
        self.assertEqual(p.display_name, "梅叔")
        self.assertEqual(p.role, "tank")
        self.assertEqual(p.spec, "酒仙")
        self.assertEqual(p.benchmark_char, "硬玩复仇绿色")
        self.assertEqual(p.progress_db, "data/meishu/progress.db")
        self.assertEqual(p.tracker_module, "meishu_tracker")

    def test_load_taozi_profile(self):
        """加载桃子档案，校验 role=healer, benchmark_char=绿绿月光"""
        p = load_profile("taozi", self.temp_dir)
        self.assertEqual(p.id, "taozi")
        self.assertEqual(p.name, "桃子")
        self.assertEqual(p.display_name, "示例学员")
        self.assertEqual(p.role, "healer")
        self.assertEqual(p.spec, "织雾")
        self.assertEqual(p.benchmark_char, "绿绿月光")
        self.assertEqual(p.benchmark_fight, 102)

    def test_missing_profile_id_raises(self):
        """缺少 profile.id 报 ValueError"""
        tmp = Path(tempfile.mkdtemp())
        yaml_content = """
profile:
  id: ""
  name: 无名
role: dps
spec: 冰法
"""
        self._write_profile(tmp, "bad", yaml_content)
        with self.assertRaises(ValueError) as ctx:
            load_profile("bad", tmp)
        self.assertIn("profile.id", str(ctx.exception))

    def test_missing_role_raises(self):
        """role 缺失报 ValueError"""
        tmp = Path(tempfile.mkdtemp())
        yaml_content = """
profile:
  id: test_role
  name: 测试
role: ""
spec: 冰法
"""
        self._write_profile(tmp, "test_role", yaml_content)
        with self.assertRaises(ValueError) as ctx:
            load_profile("test_role", tmp)
        self.assertIn("role", str(ctx.exception))

    def test_invalid_role_raises(self):
        """role 不在枚举报 ValueError"""
        tmp = Path(tempfile.mkdtemp())
        yaml_content = """
profile:
  id: test_inv
  name: 测试
role: invalid_role
spec: 冰法
"""
        self._write_profile(tmp, "test_inv", yaml_content)
        with self.assertRaises(ValueError) as ctx:
            load_profile("test_inv", tmp)
        self.assertIn("role", str(ctx.exception))

    def test_standalone_no_benchmark_ok(self):
        """comparison=standalone 时 benchmark 不报错"""
        tmp = Path(tempfile.mkdtemp())
        yaml_content = """
profile:
  id: test_std
  name: 独立用户
role: dps
spec: 冰法
function: coaching
comparison: standalone
knowledge:
  wiki_prefix: qingxin
"""
        self._write_profile(tmp, "test_std", yaml_content)
        p = load_profile("test_std", tmp)
        self.assertEqual(p.comparison, "standalone")
        self.assertEqual(p.benchmark_char, "")  # 不报错

    def test_cli_overrides_benchmark_report(self):
        """CLI 覆盖 benchmark_report"""
        p = load_profile("dongrou", self.temp_dir)
        p.apply_cli_overrides(benchmark_report="CUSTOM_REPORT", benchmark_fight=99)
        self.assertEqual(p.benchmark_report, "CUSTOM_REPORT")
        self.assertEqual(p.benchmark_fight, 99)

    def test_cli_does_not_override_unrelated(self):
        """CLI 覆盖不污染未传字段"""
        p = load_profile("dongrou", self.temp_dir)
        original_name = p.name
        p.apply_cli_overrides(benchmark_report="CUSTOM")
        # benchmark_report 变了
        self.assertEqual(p.benchmark_report, "CUSTOM")
        # name 不变
        self.assertEqual(p.name, original_name)

    def test_profiles_dir_custom_path(self):
        """传入自定义 profiles_dir 路径"""
        tmp = Path(tempfile.mkdtemp())
        yaml_content = """
profile:
  id: custom
  name: 自定义
role: dps
spec: 冰法
function: coaching
comparison: benchmark
benchmark:
  character: 对标选手
  default_report: TEST
  default_fight: 1
knowledge:
  wiki_prefix: test
"""
        self._write_profile(tmp, "custom", yaml_content)
        p = load_profile("custom", tmp)
        self.assertEqual(p.id, "custom")

    def test_file_not_found_raises(self):
        """不存在的档案报错"""
        with self.assertRaises(ValueError) as ctx:
            load_profile("nonexistent", self.temp_dir)
        self.assertIn("不存在", str(ctx.exception))

    def test_from_yaml_empty_profile(self):
        """空 YAML 也能成功解析（部分字段缺失）"""
        tmp = Path(tempfile.mkdtemp())
        yaml_content = "role: dps\nspec: 冰法\n"
        self._write_profile(tmp, "minimal", yaml_content)
        p = Profile.from_yaml(tmp / "minimal.yaml")
        self.assertEqual(p.role, "dps")

    def test_resolve_progress_db_default(self):
        """resolve_progress_db_path 相对路径解析"""
        result = resolve_progress_db_path("data/xiaoxue/progress.db")
        self.assertTrue(str(result).endswith("data/xiaoxue/progress.db"))
        # 包含 data/ 前缀，以 cwd 为基准
        self.assertEqual(result, Path(os.getcwd()) / "data/xiaoxue/progress.db")

    def test_resolve_progress_db_absolute(self):
        """绝对路径直接返回"""
        result = resolve_progress_db_path("/tmp/test.db")
        self.assertEqual(result, Path("/tmp/test.db"))


# ── YAML 档案内容 ──

DONGROU_YAML = """profile:
  id: dongrou
  name: 示例学员
  server: 主宰之剑
scenario: mplus
role: dps
spec: 冰法
hero_talent: 疾咒师
build: 射线流
function: coaching
comparison: benchmark
benchmark:
  character: qingxingood
  server: 冰风岗
  role: dps
  spec: 冰法
  default_report: AmZagypBXc9rb2jD
  default_fight: 5
  dungeon_reports:
    节点希纳斯: { code: AmZagypBXc9rb2jD, fight: 5, level: 20 }
    风行者之塔: { code: xChHgJR6XBr9mYtN, fight: 3, level: 19 }
    魔导师平台: { code: pNfk3tv86PnxTrVW, fight: 52, level: 20 }
knowledge:
  wiki_prefix: qingxin
  bilibili:
    name: 示例UP主
    uid: 30864419
  card_count: 5
progress:
  db: data/xiaoxue/progress.db
  tracker_module: xiaoxue_tracker
persona:
  style: qingxin
  greeting: 示例学员
  sign_off: 清心
"""

TAOZI_YAML = """profile:
  id: taozi
  name: 桃子
  server: ""
  display_name: 示例学员
scenario: mplus
role: healer
spec: 织雾
hero_talent: 祥和宗师
build: 鹤僧
function: coaching
comparison: benchmark
benchmark:
  character: 绿绿月光
  server: 伊森利恩
  role: healer
  spec: 织雾
  default_report: DLQHbFkqyX14dvgr
  default_fight: 102
  dungeon_reports:
    艾杰斯亚: { code: DLQHbFkqyX14dvgr, fight: 92, level: 21 }
    执政团之座: { code: DLQHbFkqyX14dvgr, fight: 102, level: 22 }
knowledge:
  wiki_prefix: sunqingyun
  bilibili:
    name: 孙青云
    uid: 0
  card_count: 5
progress:
  db: data/taozhi/taozhi.db
  tracker_module: taozhi_tracker
persona:
  style: sunqingyun
  greeting: 桃子
  sign_off: 孙青云
"""

MEISHU_YAML = """profile:
  id: meishu
  name: 梅夫三拳
  server: ""
  display_name: 梅叔
scenario: mplus
role: tank
spec: 酒仙
hero_talent: 祥和宗师
build: ""
function: coaching
comparison: benchmark
benchmark:
  character: 硬玩复仇绿色
  server: 白银之手
  role: tank
  spec: 酒仙
  default_report: Jv7tMG3rcjdXm1FN
  default_fight: 11
  dungeon_reports: {}
knowledge:
  wiki_prefix: yingwan
  bilibili:
    name: 硬玩复仇
    uid: 259140665
  card_count: 5
progress:
  db: data/meishu/progress.db
  tracker_module: meishu_tracker
persona:
  style: yingwan
  greeting: 梅叔
  sign_off: 硬玩复仇
"""


if __name__ == "__main__":
    unittest.main()
