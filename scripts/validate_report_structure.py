#!/usr/bin/env python3
"""
门禁 B：报告结构审计

用法:
    python3 scripts/validate_report_structure.py <报告路径> [模式]

模式: x2 / t / m / team (可省略，自动检测)
审计通过 → exit 0
审计不通过 → 打印缺失章节清单，exit 1
"""
import re
import sys

# 各模式的标准章节清单 (名称, 匹配正则)
SECTIONS = {
    'x2': [
        ('总览表', r'总览表|📈'),
        ('技能使用评估', r'技能使用评估|🔧'),
        ('做得好', r'做得好|✅'),
        ('需要改进', r'需要改进|❌'),
        ('输出轴对比', r'输出轴对比|📊'),
        ('技能深度解析', r'技能深度解析|⏱'),
        ('副本教学要点', r'副本教学要点|📚'),
        ('死亡分析', r'死亡分析|💀'),
        ('改进计划', r'改进计划|📅'),
        ('师傅的话', r'师傅的话|💬'),
    ],
    't': [  # T 系列治疗版，同构
        ('总览表', r'总览表|📈'),
        ('技能使用评估', r'技能使用评估|🔧'),
        ('做得好', r'做得好|✅'),
        ('需要改进', r'需要改进|❌'),
        ('输出轴/治疗轴对比', r'输出轴对比|治疗轴对比|📊'),
        ('技能深度解析', r'技能深度解析|⏱'),
        ('副本教学要点', r'副本教学要点|📚'),
        ('死亡分析', r'死亡分析|💀'),
        ('改进计划', r'改进计划|📅'),
        ('师傅的话', r'师傅的话|💬'),
    ],
    'm': [  # M 系列坦克版
        ('总览表', r'总览表|📈'),
        ('技能使用评估', r'技能使用评估|🔧'),
        ('做得好', r'做得好|✅'),
        ('需要改进', r'需要改进|❌'),
        ('坦克轴对比', r'坦克轴对比|📊'),
        ('技能深度解析', r'技能深度解析|⏱'),
        ('副本教学要点', r'副本教学要点|📚'),
        ('死亡分析', r'死亡分析|💀'),
        ('改进计划', r'改进计划|📅'),
        ('师傅的话', r'师傅的话|💬'),
    ],
    'team': [
        ('做得好', r'做得好|✅'),
        ('需要改进', r'需要改进|❌'),
        ('技能使用评估', r'技能使用评估|🔧'),
        ('改进计划', r'改进计划|📅'),
        ('MVP/战犯', r'MVP|战犯'),
    ],
}


def detect_mode(content: str) -> str:
    if '全队' in content or 'Team' in content or 'team' in content:
        return 'team'
    if '酒仙' in content or '梅叔' in content or 'M系列' in content:
        return 'm'
    if '鹤僧' in content or '织雾' in content or '孙青云' in content or 'T系列' in content:
        return 't'
    return 'x2'  # 默认 X2


def validate(path: str, mode: str = None) -> bool:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if mode is None:
        mode = detect_mode(content)

    mode_name = mode.upper()
    sections = SECTIONS.get(mode, SECTIONS['x2'])

    missing = []
    for name, pattern in sections:
        if not re.search(pattern, content):
            missing.append(name)

    if missing:
        print(f"\n❌ 结构审计未通过（{mode_name} 模式）")
        print(f"   报告: {path}")
        print(f"   缺失 {len(missing)} 节: {', '.join(missing)}")
        print(f"   请补全后再交付\n")
        return False
    else:
        print(f"\n✅ 结构审计通过（{mode_name} 模式, {len(sections)} 节全齐）\n")
        return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 scripts/validate_report_structure.py <报告路径> [模式]")
        print("  模式: x2 / t / m / team（可省略，自动检测）")
        sys.exit(1)

    result = validate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    sys.exit(0 if result else 1)
