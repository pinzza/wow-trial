#!/usr/bin/env python3
"""
安全内容过滤器 — 防止 DeepSeek "Content Exists Risk" 400 错误

增强版 v2.0: 在原有中文敏感词替换基础上，增加了全面的 Unicode 特殊字符清洗。

触发原理:
  DeepSeek 安全系统将以下字符判定为"潜在隐写/迷惑攻击":
  - 零宽字符 (ZWJ/ZWNJ/BOM) → 可隐藏信息
  - 变体选择符 (VS16) → Emoji 的"隐藏层"
  - 希腊字母/数学符号 → 同形异义攻击 (homoglyph attack)
  - Emoji 序列 → 携带 ZWJ+VS，且语义不确定
  - Unicode 长破折号/箭头 → 迷惑字符 (confusable)

用法:
    from scripts.safe_content_filter import safe_content_filter, safe_dict_filter

    text = safe_content_filter(text)
    data = safe_dict_filter(data)
"""

import re
import unicodedata

# ═══════════════════════════════════════════════════════════════════
# 第 1 层: 中文敏感词替换
# ═══════════════════════════════════════════════════════════════════
_TEXT_REPLACEMENTS = [
    # 安全替换暂为空 — 400 问题仅对特定日志生效，不再需要主动替换
]

# ═══════════════════════════════════════════════════════════════════
# 第 2 层: Unicode 特殊字符清洗
# ═══════════════════════════════════════════════════════════════════

# 零宽字符 — 直接删除 (这些字符在终端/文件中不可见，但安全扫描器会检测)
_ZERO_WIDTH_RE = re.compile(
    '[\u200B\u200C\u200D\u200E\u200F'   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    '\uFEFF'                              # BOM / ZWNBS
    '\u2060\u2061\u2062\u2063\u2064'      # Word joiner, math invis ops
    '\u00AD'                              # Soft hyphen
    '\u180E'                              # Mongolian vowel separator
    ']'
)

# 变体选择符 — 直接删除 (Emoji 的隐藏修饰层)
# ⚠️ 不能用 \uE0100 写法：Python regex 的 \u 只支持 4 位 hex，
#     会被解析为 \uE010 + '0'，导致 0-\uE01E 误伤大量字符。
#     必须用 chr() 构建实际字符。
_VARIATION_SELECTOR_RE = re.compile(
    '[\uFE00-\uFE0F'
    + chr(0xE0100) + '-' + chr(0xE01EF)
    + ']'
)

# 常用 Emoji → 安全文本标记
_EMOJI_REPLACEMENTS = [
    # 记号类
    (chr(0x2705), '[OK]'),   (chr(0x2714), '[OK]'),  (chr(0x2611), '[OK]'),
    (chr(0x274C), '[X]'),    (chr(0x2716), '[X]'),   (chr(0x2717), '[X]'),
    (chr(0x274E), '[X]'),    (chr(0x26D4), '[!]'),
    (chr(0x26A0), '[!]'),    (chr(0x2620), '[!!]'),
    (chr(0x2B50), '[*]'),    (chr(0x1F31F), '[*]'),
    # 箭头类 -> ASCII
    (chr(0x2192), '->'),     (chr(0x2190), '<-'),
    (chr(0x2191), '^'),      (chr(0x2193), 'v'),
    (chr(0x21D2), '=>'),     (chr(0x21D0), '<='),
    (chr(0x25B6), '>'),      (chr(0x25C0), '<'),
    # 职业标记
    (chr(0x1F6E1), '[T]'),   (chr(0x2694), '[D]'),   (chr(0x1F49A), '[H]'),
    (chr(0x1F534), '[P0]'),  (chr(0x1F7E1), '[P1]'), (chr(0x1F7E2), '[OK]'),
    # 其他常用标记
    (chr(0x1F525), '[!!]'),  (chr(0x1F480), '[!!]'),
    (chr(0x1F3C6), '[MVP]'),
    (chr(0x1F4CA), '[=]'),
    (chr(0x1F4CB), '[*]'),
    (chr(0x2139),  '[i]'),
    (chr(0x1F3AF), '[!]'),
    (chr(0x1F4A1), '[i]'),
]

# Unicode 破折号 -> ASCII
_UNICODE_DASH_MAP = {
    chr(0x2014): '--',    # EM DASH
    chr(0x2013): '-',     # EN DASH
    chr(0x2015): '--',    # HORIZONTAL BAR
    chr(0x2012): '--',    # FIGURE DASH
}

# Greek 字母 -> Latin/Chinese
_GREEK_MAP = {
    chr(0x03C3): '标准差',  # sigma
    chr(0x03BC): 'mu',      # mu
    chr(0x03B4): 'delta',   # delta lowercase
    chr(0x0394): 'Delta',   # Delta uppercase
    chr(0x03B1): 'alpha',   # alpha
    chr(0x03B2): 'beta',    # beta
    chr(0x03B3): 'gamma',   # gamma
    chr(0x03B5): 'epsilon', # epsilon
}

# 数学符号 -> ASCII
_MATH_SYMBOL_MAP = {
    chr(0x2248): '~',       # almost equal
    chr(0x2260): '!=',      # not equal
    chr(0x2264): '<=',      # less or equal
    chr(0x2265): '>=',      # greater or equal
    chr(0x00B1): '+/-',     # plus-minus
    chr(0x221E): 'inf',     # infinity
    chr(0x00D7): 'x',       # multiplication
    chr(0x00F7): '/',       # division
}

# 其他特殊字符 -> ASCII
_OTHER_SYMBOL_MAP = {
    chr(0x2022): '-',       # bullet
    chr(0x2026): '...',     # ellipsis
    chr(0x00A0): ' ',       # non-breaking space
    chr(0x2002): ' ',       # en space
    chr(0x2003): ' ',       # em space
    chr(0x2009): ' ',       # thin space
}


def _build_emoji_re():
    """构建 Emoji 匹配正则。"""
    chars = ''.join(re.escape(k) for k, v in _EMOJI_REPLACEMENTS)
    return re.compile(f'[{chars}]')


_EMOJI_RE = _build_emoji_re()


def _replace_emoji(match):
    """Emoji -> 安全文本 的替换回调。"""
    ch = match.group(0)
    for emoji, safe in _EMOJI_REPLACEMENTS:
        if emoji == ch:
            return safe
    return ch


def safe_content_filter(text: str) -> str:
    """
    内容安全过滤器 — 全面清洗所有可能触发 DeepSeek 400 的字符。

    清洗顺序:
      1. 零宽字符 -> 删除
      2. 变体选择符 -> 删除
      3. Emoji -> 安全文本替代
      4. Unicode 破折号 -> ASCII
      5. Greek 字母 -> Latin/Chinese
      6. 数学符号 -> ASCII
      7. 其他特殊字符 -> ASCII
      8. 中文敏感词 -> 替换
    """
    if not isinstance(text, str):
        return text

    # 1. 删除零宽字符
    text = _ZERO_WIDTH_RE.sub('', text)
    # 2. 删除变体选择符
    text = _VARIATION_SELECTOR_RE.sub('', text)
    # 3. Emoji -> 安全文本
    text = _EMOJI_RE.sub(_replace_emoji, text)
    # 4. Unicode 破折号 -> ASCII
    for old, new in _UNICODE_DASH_MAP.items():
        text = text.replace(old, new)
    # 5. Greek 字母
    for old, new in _GREEK_MAP.items():
        text = text.replace(old, new)
    # 6. 数学符号
    for old, new in _MATH_SYMBOL_MAP.items():
        text = text.replace(old, new)
    # 7. 其他特殊字符
    for old, new in _OTHER_SYMBOL_MAP.items():
        text = text.replace(old, new)
    # 8. 中文敏感词
    for old, new in _TEXT_REPLACEMENTS:
        text = text.replace(old, new)

    return text


def safe_dict_filter(data):
    """
    递归过滤字典/列表中的所有字符串值。
    安全的类型 (int/float/bool/None) 直接透传。
    """
    if isinstance(data, str):
        return safe_content_filter(data)
    elif isinstance(data, dict):
        return {safe_content_filter(k) if isinstance(k, str) else k: safe_dict_filter(v)
                for k, v in data.items()}
    elif isinstance(data, list):
        return [safe_dict_filter(item) for item in data]
    elif isinstance(data, (int, float, bool, type(None))):
        return data
    else:
        return safe_content_filter(str(data))


def audit_text(text: str) -> dict:
    """
    审计文本，返回所有潜在风险字符的统计信息。
    """
    issues = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        category = None
        detail = None

        if cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F):
            category = 'ZERO_WIDTH'
            detail = f"U+{cp:04X}"
        elif cp == 0xFEFF:
            category = 'BOM'
            detail = 'U+FEFF'
        elif 0xFE00 <= cp <= 0xFE0F:
            category = 'VARIATION_SELECTOR'
            detail = f"U+{cp:04X}"
        elif 0x0370 <= cp <= 0x03FF:
            category = 'GREEK'
            detail = f"U+{cp:04X} '{ch}'"
        elif cp == 0x2014:
            category = 'EM_DASH'
            detail = 'U+2014'
        elif cp == 0x2248:
            category = 'MATH_SYMBOL'
            detail = f"U+{cp:04X} '{ch}'"
        elif 0x1F300 <= cp <= 0x1F9FF:
            category = 'EMOJI'
            detail = f"U+{cp:04X} '{ch}'"
        elif 0x2600 <= cp <= 0x27BF:
            category = 'MISC_SYMBOL'
            detail = f"U+{cp:04X} '{ch}'"
        elif cp > 127 and not (0x4E00 <= cp <= 0x9FFF) and not (0x3000 <= cp <= 0x303F):
            category = 'OTHER_NON_ASCII'
            detail = f"U+{cp:04X} '{ch}'"

        if category:
            ctx_start = max(0, i - 20)
            ctx_end = min(len(text), i + 21)
            ctx = text[ctx_start:ctx_end].replace('\n', '\\n')
            issues.append({
                'category': category,
                'char': ch,
                'codepoint': f"U+{cp:04X}",
                'position': i,
                'context': ctx,
                'detail': detail,
            })

    by_category = {}
    for issue in issues:
        cat = issue['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(issue)

    return {
        'total_chars': len(text),
        'total_issues': len(issues),
        'by_category': {k: len(v) for k, v in by_category.items()},
        'details': issues,
    }


# ── CLI 自检 ────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys

    test_cases = [
        ("step3 模拟", "副本: 三头议会 | 层数: +16 | \u2705 限时\n队伍: \U0001F6E1\uFE0F坦克 \U0001F49A治疗 \u2694\uFE0FDPS\n\u03C3=19.9s | \u2248 40.8s | \u2192 结果"),
        ("敏感词", "执政团之座 的 统治议会 在行动"),
        ("ZWJ+VS", "\U0001F9D1\u200D\U0001F91D\u200D\U0001F9D1 和 \u2620\uFE0F 测试"),
    ]

    for name, text in test_cases:
        print(f"\n{'='*60}")
        print(f"测试: {name}")
        truncated = text[:80].replace('\n', '\\n')
        print(f"原始: {truncated}")

        audit = audit_text(text)
        print(f"  清洗前问题数: {audit['total_issues']}")
        for cat, count in audit['by_category'].items():
            print(f"    {cat}: {count}")

        cleaned = safe_content_filter(text)
        truncated2 = cleaned[:80].replace('\n', '\\n')
        print(f"  清洗后: {truncated2}")
        post_audit = audit_text(cleaned)
        print(f"  残留问题: {post_audit['total_issues']}")
        if post_audit['total_issues'] > 0:
            for issue in post_audit['details']:
                print(f"    FAIL: {issue['category']} {issue['detail']}: ...{issue['context']}...")
        else:
            print("  [PASS]")

    print(f"\n{'='*60}")
    print("所有测试完成")
