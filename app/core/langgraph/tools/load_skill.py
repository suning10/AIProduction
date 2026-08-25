"""Skill-loading tool for LangGraph.

Lets the agent pull a skill's markdown instructions into context on demand,
separating *what tools exist* (this package) from *how and when to use them
for a given class of task* (``app/core/skills/*.md``).
"""

from langchain_core.tools import tool

from app.core.logging import logger
from app.core.skills import SKILLS


@tool
def load_skill(skill_name: str) -> str:
    """Load a skill's step-by-step instructions by name.

    Call this when the user's request matches one of the skills listed in
    your system prompt, before taking further action. The returned text
    contains guidance for handling that class of task, including which
    other tools to use and how.

    Args:
        skill_name: The exact name of the skill to load.

    Returns:
        str: The skill's full instructions, or an error message listing the
            available skill names if no skill matches.
    """
    skill = SKILLS.get(skill_name)
    if skill is None:
        logger.warning("skill_not_found", requested=skill_name, available=list(SKILLS.keys()))
        return f"skill '{skill_name}' not found. available skills: {', '.join(SKILLS.keys())}"

    logger.info("skill_loaded", skill_name=skill_name)
    return skill.body
