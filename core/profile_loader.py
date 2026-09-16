#!/usr/bin/env python3
"""
用户档案加载器 (profile_loader.py)

从 data/profiles/{profile_id}.yaml 加载用户档案，
扁平化 YAML 嵌套结构为 Profile dataclass。

Usage:
    from core.profile_loader import load_profile
    profile = load_profile("dongrou")
    print(profile.role)  # "dps"
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


PROFILES_DIR: Path = Path("data/profiles/")


@dataclass
class Profile:
    """用户档案的完整数据模型"""

    # ── 档案元数据 ──
    id: str = ""
    name: str = ""
    server: str = ""
    display_name: str = ""

    # ── 四维参数 ──
    scenario: str = "mplus"
    role: str = ""
    spec: str = ""
    hero_talent: str = ""
    build: str = ""

    # ── 功能与对比 ──
    function: str = "coaching"
    comparison: str = "benchmark"

    # ── 基准配置（嵌套扁平化） ──
    benchmark_char: str = ""
    benchmark_server: str = ""
    benchmark_role: str = ""
    benchmark_spec: str = ""
    benchmark_report: str = ""
    benchmark_fight: int = 0
    benchmark_dungeon_reports: dict = field(default_factory=dict)

    # ── 知识来源 ──
    wiki_prefix: str = ""
    bilibili_name: str = ""
    bilibili_uid: int = 0
    card_count: int = 0

    # ── 进度追踪 ──
    progress_db: str = ""
    tracker_module: str = ""

    # ── 报告口吻 ──
    persona_style: str = "default"
    persona_greeting: str = ""
    persona_sign_off: str = ""

    def validate(self) -> list[str]:
        """校验必填字段，返回错误消息列表。空列表=合法。"""
        errors = []

        if not self.id:
            errors.append("profile.id 必填")
        if self.role not in ("dps", "tank", "healer"):
            errors.append(f"role 非法: {self.role}")
        if not self.spec:
            errors.append("spec 必填")
        if self.function not in ("coaching", "team", "top_tier"):
            errors.append(f"function 非法: {self.function}")
        if self.comparison not in ("benchmark", "standalone"):
            errors.append(f"comparison 非法: {self.comparison}")

        # function=coaching 且 comparison=benchmark → benchmark 字段必填
        if self.function == "coaching" and self.comparison == "benchmark":
            if not self.benchmark_char:
                errors.append("benchmark.character 必填")
            if not self.benchmark_report:
                errors.append("benchmark.default_report 必填")
            if self.benchmark_fight <= 0:
                errors.append("benchmark.default_fight 必填且 >0")

        # function=coaching → wiki_prefix 必填
        if self.function == "coaching" and not self.wiki_prefix:
            errors.append("knowledge.wiki_prefix 必填")

        return errors

    def apply_cli_overrides(self, **kwargs) -> None:
        """CLI 参数覆盖档案默认值，只覆盖传了的字段。"""
        for key, value in kwargs.items():
            if value is not None and hasattr(self, key):
                setattr(self, key, value)

    @classmethod
    def from_yaml(cls, path: Path) -> "Profile":
        """从 YAML 文件解析并转为扁平化 Profile 对象。"""
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)

        profile = cls()

        # 从 YAML 嵌套结构中提取值
        p = data.get("profile", {})
        profile.id = p.get("id", "")
        profile.name = p.get("name", "")
        profile.server = p.get("server", "")
        profile.display_name = p.get("display_name", "") or p.get("name", "")

        profile.scenario = data.get("scenario", "mplus")
        profile.role = data.get("role", "")
        profile.spec = data.get("spec", "")
        profile.hero_talent = data.get("hero_talent", "")
        profile.build = data.get("build", "")

        profile.function = data.get("function", "coaching")
        profile.comparison = data.get("comparison", "benchmark")

        # benchmark 嵌套结构扁平化
        bm = data.get("benchmark", {})
        if bm:
            profile.benchmark_char = bm.get("character", "")
            profile.benchmark_server = bm.get("server", "")
            profile.benchmark_role = bm.get("role", "")
            profile.benchmark_spec = bm.get("spec", "")
            profile.benchmark_report = bm.get("default_report", "")
            profile.benchmark_fight = bm.get("default_fight", 0)
            profile.benchmark_dungeon_reports = bm.get("dungeon_reports", {})
            if profile.benchmark_dungeon_reports is None:
                profile.benchmark_dungeon_reports = {}

        # knowledge 嵌套结构扁平化
        kw = data.get("knowledge", {})
        if kw:
            profile.wiki_prefix = kw.get("wiki_prefix", "")
            bb = kw.get("bilibili", {})
            if bb:
                profile.bilibili_name = bb.get("name", "")
                profile.bilibili_uid = bb.get("uid", 0) or 0
            profile.card_count = kw.get("card_count", 0) or 0

        # progress 嵌套结构扁平化
        pr = data.get("progress", {})
        if pr:
            profile.progress_db = pr.get("db", "")
            profile.tracker_module = pr.get("tracker_module", "")

        # persona 嵌套结构扁平化
        ps = data.get("persona", {})
        if ps:
            profile.persona_style = ps.get("style", "default")
            profile.persona_greeting = ps.get("greeting", "")
            profile.persona_sign_off = ps.get("sign_off", "")

        return profile


def load_profile(profile_id: str, profiles_dir: Optional[Path] = None) -> Profile:
    """加载用户档案。

    参数:
        profile_id: 档案 ID（如 dongrou/taozi/meishu）
        profiles_dir: 档案目录（默认 data/profiles/）

    返回:
        Profile 对象

    抛出:
        ValueError: 文件不存在或校验失败
    """
    if profiles_dir is None:
        profiles_dir = PROFILES_DIR

    filepath = profiles_dir / f"{profile_id}.yaml"
    if not filepath.exists():
        raise ValueError(f"档案文件不存在: {filepath}")

    try:
        profile = Profile.from_yaml(filepath)
    except Exception as e:
        raise ValueError(f"档案解析失败 ({filepath}): {e}") from e

    errors = profile.validate()
    if errors:
        raise ValueError(f"档案校验失败 ({profile_id}): {'; '.join(errors)}")

    return profile


def resolve_progress_db_path(progress_db: str) -> Path:
    """progress.db 路径解析规则：
    1. 以 data/ 开头 → 相对于项目根目录（os.getcwd()）
    2. 绝对路径 → 直接使用
    3. 其他 → 相对于项目根目录下的 data/
    """
    import os

    prog_path = Path(progress_db)
    if prog_path.is_absolute():
        return prog_path
    if progress_db.startswith("data/"):
        return Path(os.getcwd()) / progress_db
    return Path(os.getcwd()) / "data" / progress_db
