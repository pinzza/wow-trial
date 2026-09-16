# CLAUDE.md — Claude Code 兼容入口

**本仓库的唯一事实源是 [`AGENTS.md`](./AGENTS.md)。请在改动任何文件前完整阅读并遵守它。**

TL;DR：

- 项目：魔兽世界 Warcraft Logs (WCL) 日志分析 → 中文教练报告（Markdown + PDF）
- 主工具：`PYTHONPATH=. python3 core/v1_pipeline.py <CODE> --fight-id <N> --db-dir data/wcl_db`
- **用系统 `python3`（3.12，依赖齐全），不要用 `venv/bin/python`（缺 pydantic）**
- 项目 skills 在 `.agents/skills/`（`wcl-player-review`、`mplus-t-coach`）
- 已知 API 陷阱、数据库模式、报告规范、PDF 管线：见 `AGENTS.md`

## 给 Claude Code 用户

若你的 Claude Code 版本不识别 `.agents/skills/`，请在本机自行建立适配器（该目录已在 `.gitignore` 中，**不要提交**）：

```bash
mkdir -p .claude/skills
ln -s ../../.agents/skills/wcl-player-review .claude/skills/wcl-player-review
ln -s ../../.agents/skills/mplus-t-coach     .claude/skills/mplus-t-coach
```

本项目已不再使用 superpowers 插件（`.claude/skills/`、`.claude/agents/`、`.hermes/` 中的相关产物已于 2026-09-10 全部移除），请不要重新引入。
