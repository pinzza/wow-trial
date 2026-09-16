#!/usr/bin/env python3
"""
统一报告构建器 (report_builder.py)

通过 profile.role 选择角色特定模板，profile.persona_* 控制报告口吻。
旧 xiaoxue_report_builder.py / meishu_report_builder.py 标记 deprecated 并委托至此。

Usage:
    from core.report_builder import ReportBuilder
    builder = ReportBuilder(profile, output_dir)
    skeleton_md = builder.build_header(meta) + builder.build_overview_table(...)
"""

from pathlib import Path
from typing import Any, Optional

from core.profile_loader import Profile
from core.pipeline_strategies import ROLE_CONFIGS


class ReportBuilder:
    """统一报告构建器，role_config + profile 驱动差异"""

    ROLE_ICON = {
        "dps": "🧊",
        "healer": "🪷",
        "tank": "🍺",
    }

    PERSONA_STYLES = {
        "qingxin": {"coach_name": "清心", "emoji": "🧊"},
        "sunqingyun": {"coach_name": "孙青云", "emoji": "🪷"},
        "yingwan": {"coach_name": "硬玩复仇", "emoji": "🍺"},
        "yeshifu": {"coach_name": "叶师傅", "emoji": "🐑"},
        "default": {"coach_name": "教练", "emoji": "📊"},
    }

    def __init__(self, profile: Profile, output_dir: Path):
        self.profile = profile
        self.role_config = ROLE_CONFIGS[profile.role].copy()
        self.output_dir = output_dir

    def build_header(self, meta: dict) -> str:
        """标题块：优先使用 persona emoji，其次 role 决定 emoji"""
        persona_style = self.profile.persona_style or "default"
        persona_meta = self.PERSONA_STYLES.get(persona_style, self.PERSONA_STYLES["default"])
        icon = persona_meta.get("emoji", self.ROLE_ICON.get(self.profile.role, "📊"))
        lines = [
            f"# {icon} {self.profile.display_name or self.profile.name} 教练报告",
            "",
            f"**专精**: {self.profile.spec} | **角色**: {self.profile.role.upper()}",
        ]
        if meta.get("report_code"):
            lines.append(f"**报告**: {meta['report_code']} | **Fight**: {meta.get('fight_id', '?')}")
        lines.append("")
        return "\n".join(lines)

    def build_overview_table(self, skill_data: dict, benchmark_data: dict) -> str:
        """总览表：role 决定行（ROLE_CONFIGS.overview_rows）"""
        rows = self.role_config.get("overview_rows", ["总伤害", "DPS"])
        lines = ["## 📈 总览", "", "| 指标 | 学习者 | 基准 | 差距 |", "|---|---|---|---|"]

        for row_key in rows:
            learner_val = skill_data.get(row_key, "—")
            benchmark_val = benchmark_data.get(row_key, "—")
            gap = self._compute_gap(learner_val, benchmark_val, row_key)
            lines.append(f"| {row_key} | {learner_val} | {benchmark_val} | {gap} |")

        lines.append("")
        return "\n".join(lines)

    def _compute_gap(self, learner, benchmark, row_key: str) -> str:
        """计算差距显示"""
        try:
            l_val = float(str(learner).replace("M", "").replace("k", "").replace(",", ""))
            b_val = float(str(benchmark).replace("M", "").replace("k", "").replace(",", ""))
            if row_key in ("过量%",):
                diff = l_val - b_val
                return f"{diff:+.1f}%"
            diff = l_val - b_val
            return f"{diff:+.1f}"
        except (ValueError, TypeError):
            return "—"

    def build_skill_assessment(self, skill_data: dict) -> str:
        """技能评估表"""
        lines = ["## 🔧 技能使用评估", "", "| 技能 | 学习者次数 | 基准次数 | 差距 | 评级 | 分析 |",
                 "|---|---|---|---|---|---|"]

        skills = skill_data.get("skills", {})
        if not isinstance(skills, dict):
            skills = {}

        for skill_name, skill_info in skills.items():
            learner_count = skill_info.get("learner_count", "—")
            benchmark_count = skill_info.get("benchmark_count", "—")
            gap = skill_info.get("gap", "—")
            rating = skill_info.get("rating", "🟡")
            analysis = skill_info.get("analysis", "")
            lines.append(
                f"| {skill_name} | {learner_count} | {benchmark_count} | {gap} | {rating} | {analysis} |"
            )

        if not skills:
            lines.append("| — | — | — | — | 🟡 | 暂无可比数据 |")

        lines.append("")
        return "\n".join(lines)

    def build_wave_comparison(self, comparison_json: Path) -> str:
        """波次对比：共用的 comparison_engine 数据"""
        if not comparison_json or not Path(comparison_json).exists():
            return "> ⚠️ 未找到波次对比数据\n\n"

        lines = ["## 🎯 波次对比", ""]
        lines.append(f"> 数据来源: {comparison_json.name}")
        lines.append("")
        return "\n".join(lines)

    def build_death_analysis(self, death_data: list) -> str:
        """死亡分析：role_config.death_depth 决定深度"""
        if not death_data:
            return "## 💀 死亡分析\n\n✅ 零死亡\n\n"

        depth = self.role_config.get("death_depth", "normal")
        lines = ["## 💀 死亡分析", ""]
        lines.append(f"共 {len(death_data)} 次死亡")

        for i, death in enumerate(death_data, 1):
            lines.append(f"  {i}. {death.get('time', '?')}s — {death.get('name', '?')} — {death.get('killing_blow', '?')}")

        if depth == "full" and len(death_data) > 0:
            lines.append("")
            lines.append("**深度分析 (Tank)**:")
            lines.append("  - 减伤链覆盖检查: 待补充")
            lines.append("  - 酒池/灵打时机: 待补充")

        lines.append("")
        return "\n".join(lines)

    def build_improvement_plan(self) -> str:
        """改进计划：6 行结构"""
        lines = ["## 📅 改进计划", "",
                 "| # | 改进项 | 优先级 | 具体做法 | 目标量化 |",
                 "|---|---|---|---|---|",
                 "| 1 | 技能循环 | 🟡 | 优化循环顺序 | CPM 提升 10% |",
                 "| 2 | 减伤使用 | 🟡 | 提高覆盖率 | 减伤使用率 >80% |",
                 "| 3 | 打断管理 | 🟢 | 关注关键打断 | 打断次数 >5 |",
                 "| 4 | 站位优化 | 🟡 | 减少无效移动 | 死亡次数 ≤2 |",
                 "| 5 | 冷却规划 | 🔴 | 匹配BOSS时间轴 | 冷却利用率 >90% |",
                 "| 6 | 装备优化 | 🟢 | 调整绿字配比 | 模拟提升 >2% |",
                 "", "---", ""]
        return "\n".join(lines)

    def build_coach_note(self, analysis_data: dict) -> str:
        """师傅的话：persona_style 决定口吻"""
        style = self.profile.persona_style or "default"
        persona = self.PERSONA_STYLES.get(style, self.PERSONA_STYLES["default"])
        coach_name = persona["coach_name"]
        greeting = self.profile.persona_greeting or self.profile.display_name or self.profile.name

        # 从 analysis_data 提取关键发现
        highlights = analysis_data.get("highlights", [])
        issues = analysis_data.get("issues", [])

        lines = [f"## 💬 {coach_name}的话", "",
                 f"> 此分析由 {coach_name} 基于 WCL 数据自动生成。"]

        if highlights:
            lines.append(f"> **做得好**: {'; '.join(highlights[:2])}")
        if issues:
            lines.append(f"> **提升方向**: {'; '.join(issues[:2])}")

        lines.append(f"> 继续加油，{greeting}！")
        lines.append(f"> —— {persona['coach_name']}")
        lines.append("")
        return "\n".join(lines)

    def build_skeleton(self, meta: dict, skill_data: dict,
                       benchmark_data: dict, death_data: list,
                       analysis_data: dict, comparison_json: Optional[Path] = None) -> str:
        """生成完整含占位符的 Markdown 骨架"""
        parts = [
            self.build_header(meta),
            self.build_overview_table(skill_data, benchmark_data),
            self.build_skill_assessment(skill_data),
            "## ✅ 做得好\n{{DO_WELL_FINAL}}\n",
            "## ❌ 需要改进\n{{IMPROVE_FINAL}}\n",
            self.build_death_analysis(death_data),
            "{{DEATH_ROOT_CAUSE}}\n",
            self.build_improvement_plan(),
            self.build_coach_note(analysis_data),
        ]

        if comparison_json and Path(comparison_json).exists():
            parts.append(self.build_wave_comparison(comparison_json))

        return "\n".join(parts)


def build_report_from_profile(profile: Profile, output_dir: Path,
                               meta: dict, skill_data: dict,
                               benchmark_data: dict, death_data: list,
                               analysis_data: dict,
                               comparison_json: Optional[Path] = None) -> str:
    """便捷函数：一步生成报告骨架"""
    builder = ReportBuilder(profile, output_dir)
    return builder.build_skeleton(
        meta=meta,
        skill_data=skill_data,
        benchmark_data=benchmark_data,
        death_data=death_data,
        analysis_data=analysis_data,
        comparison_json=comparison_json,
    )
