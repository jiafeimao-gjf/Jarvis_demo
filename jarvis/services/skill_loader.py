# jarvis/services/skill_loader.py
"""技能加载器 — 扫描 workspace/skills/ 目录, 解析 skill.md YAML frontmatter"""
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from jarvis.utils.logger import get_logger

logger = get_logger(__name__)

SKILL_DIR = Path(__file__).parent.parent.parent / "workspace" / "skills"

YAML_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


@dataclass
class SkillInfo:
    name: str
    description: str
    path: str  # relative path to skill directory


def load_skills(skill_dir: Optional[Path] = None) -> list[SkillInfo]:
    """扫描 skills 目录, 解析每个 skill.md 的 YAML frontmatter"""
    if skill_dir is None:
        skill_dir = SKILL_DIR

    if not skill_dir.exists():
        logger.debug(f"Skills dir not found: {skill_dir}")
        return []

    skills: list[SkillInfo] = []
    for md_file in sorted(skill_dir.rglob("skill.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            match = YAML_RE.search(content)
            if not match:
                logger.warning(f"No YAML frontmatter in {md_file}")
                continue

            frontmatter = match.group(1)
            parsed = _parse_yaml_kv(frontmatter)

            name = parsed.get("name", md_file.parent.name)
            description = parsed.get("description", "")
            if not name or not description:
                logger.warning(f"Missing name/description in {md_file}")
                continue

            rel = md_file.parent.relative_to(skill_dir)
            skills.append(SkillInfo(name=name, description=description, path=str(rel)))
            logger.debug(f"Loaded skill: {name} ({rel})")
        except Exception as e:
            logger.warning(f"Failed to load skill {md_file}: {e}")

    return skills


def load_prompt_files(workspace_dir: Optional[Path] = None) -> dict[str, str]:
    """加载 workspace 下的角色设定文件 (persona.md, abilities.md 等)"""
    if workspace_dir is None:
        workspace_dir = SKILL_DIR.parent  # workspace/

    prompts: dict[str, str] = {}
    for name in ("persona", "abilities", "memory", "tools", "work_folder"):
        fpath = workspace_dir / f"{name}.md"
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    prompts[name] = content
            except Exception:
                pass
    return prompts


def save_prompt_file(name: str, content: str, workspace_dir: Optional[Path] = None) -> bool:
    """保存单个角色设定到 workspace/{name}.md"""
    if workspace_dir is None:
        workspace_dir = SKILL_DIR.parent
    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        fpath = workspace_dir / f"{name}.md"
        fpath.write_text(content, encoding="utf-8")
        logger.info(f"Saved prompt: {fpath}")
        return True
    except Exception as e:
        logger.error(f"Failed to save {name}: {e}")
        return False


def _parse_yaml_kv(text: str) -> dict[str, str]:
    """Parse simple key: value YAML (no nested structures)"""
    result = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result
