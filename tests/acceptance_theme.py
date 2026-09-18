"""
acceptance_theme.py - 主题 / 调色板验收

按用户任务书要求：
- 跟随 Windows 应用主题
- 所有列表、输入框、菜单、日志、禁用态都统一适配
- 视觉对比度满足可读性

只测纯函数 + 不依赖 GUI 弹窗。
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from theme import _is_windows_dark, palette, LIGHT, DARK


# WCAG 相对亮度公式
def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrast_ratio(c1: str, c2: str) -> float:
    l1, l2 = relative_luminance(c1), relative_luminance(c2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def main():
    print("=" * 60)
    print(" Theme Acceptance")
    print("=" * 60)

    cases = []

    # 1. 系统主题探测能跑
    dark = _is_windows_dark()
    cases.append(("Windows 主题探测", True, f"is_dark={dark}"))

    # 2. 浅色 / 深色调色板都有所有关键字段
    required_keys = {"bg", "card", "fg", "fg_muted", "accent", "accent_fg",
                     "success", "warning", "error", "log_bg", "log_fg",
                     "border", "drop_target"}
    for name, pal in [("浅色", LIGHT), ("深色", DARK)]:
        missing = required_keys - set(pal.keys())
        cases.append((f"{name} 调色板字段完整", not missing,
                     f"missing={missing}" if missing else "all keys present"))

    # 3. 对比度：bg vs fg ≥ 4.5（WCAG AA 正文）
    for name, pal in [("浅色", LIGHT), ("深色", DARK)]:
        cr = contrast_ratio(pal["bg"], pal["fg"])
        cases.append((f"{name} bg/fg 对比度 ≥ 4.5", cr >= 4.5,
                     f"ratio={cr:.2f}"))

    # 4. 对比度：accent vs accent_fg ≥ 4.5（按钮文字清晰）
    for name, pal in [("浅色", LIGHT), ("深色", DARK)]:
        cr = contrast_ratio(pal["accent"], pal["accent_fg"])
        cases.append((f"{name} accent/accent_fg 对比度 ≥ 4.5", cr >= 4.5,
                     f"ratio={cr:.2f}"))

    # 5. 对比度：log_bg vs log_fg ≥ 4.5（日志可读）
    for name, pal in [("浅色", LIGHT), ("深色", DARK)]:
        cr = contrast_ratio(pal["log_bg"], pal["log_fg"])
        cases.append((f"{name} log_bg/log_fg 对比度 ≥ 4.5", cr >= 4.5,
                     f"ratio={cr:.2f}"))

    # 6. 浅色 bg 应该是浅色（亮度 > 0.7）
    cases.append(("浅色 bg 是浅色", relative_luminance(LIGHT["bg"]) > 0.7,
                 f"lum={relative_luminance(LIGHT['bg']):.2f}"))

    # 7. 深色 bg 应该是深色（亮度 < 0.15）
    cases.append(("深色 bg 是深色", relative_luminance(DARK["bg"]) < 0.15,
                 f"lum={relative_luminance(DARK['bg']):.2f}"))

    # 8. success / warning / error 在两种主题下都能跟 bg 区分
    for name, pal in [("浅色", LIGHT), ("深色", DARK)]:
        for status_color in ("success", "warning", "error"):
            cr = contrast_ratio(pal[status_color], pal["bg"])
            cases.append((f"{name} {status_color} vs bg 对比 ≥ 3.0",
                         cr >= 3.0, f"ratio={cr:.2f}"))

    # 9. palette() 函数选择正确
    cases.append(("palette(dark=True) 返回 DARK", palette(True) is DARK, ""))
    cases.append(("palette(dark=False) 返回 LIGHT", palette(False) is LIGHT, ""))

    # 汇总
    passed = sum(1 for _, ok, _ in cases if ok)
    total = len(cases)
    print()
    for name, ok, detail in cases:
        flag = "✓" if ok else "✗"
        print(f"  {flag} {name}" + (f" — {detail}" if detail else ""))
    print()
    print(f"=== 汇总：{passed}/{total} 通过 ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
