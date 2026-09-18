"""Skill registry — keyword-triggered domain guidance for the planner.

Skills keep the planner domain-agnostic at its core while injecting targeted
SQL/analysis idioms based on the question (multiple skills can activate).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    name: str
    priority: int
    triggers: list[str] = field(default_factory=list)
    guidance: str = ""
    # Catalog preconditions: at least one column name must contain one of these
    # patterns (case-insensitive). Empty = always applicable.
    requires_columns: tuple[str, ...] = ()
    # At least one table name must contain one of these patterns. Empty = any.
    requires_tables: tuple[str, ...] = ()


class SkillRegistry:
    def __init__(self, skills: list[Skill] | None = None):
        self._skills = list(skills or [])

    def register(self, skill: Skill) -> None:
        self._skills.append(skill)

    def all(self) -> list[Skill]:
        return list(self._skills)

    def match(self, question: str, catalog=None) -> list[Skill]:
        ql = question.lower()
        matched = [s for s in self._skills
                   if any(t in ql for t in s.triggers) and self._preconditions_hold(s, catalog)]
        return sorted(matched, key=lambda s: s.priority, reverse=True)

    @staticmethod
    def _preconditions_hold(skill: Skill, catalog) -> bool:
        if catalog is None or (not skill.requires_columns and not skill.requires_tables):
            return True
        tables = [t.name.lower() for t in catalog.tables]
        columns = [c.name.lower() for t in catalog.tables for c in t.columns]
        if skill.requires_tables and not any(
                p in table for p in skill.requires_tables for table in tables):
            return False
        if skill.requires_columns and not any(
                p in column for p in skill.requires_columns for column in columns):
            return False
        return True


def build_skill_prompt(skills: list[Skill]) -> str:
    if not skills:
        return ""
    lines = [f"- {s.guidance}" for s in skills]
    return "Domain guidance:\n" + "\n".join(lines)


def builtin_skills() -> list[Skill]:
    """Domain-agnostic default skills for the OSS planner."""
    return [
        Skill(
            name="analytics", priority=5,
            triggers=["count", "top", "distribution", "breakdown", "sum", "average", "aggregate", "total", "rank"],
            guidance="Use group-by aggregations and top-N ordering for analytical questions.",
        ),
        Skill(
            name="timeseries", priority=10,
            triggers=["trend", "hourly", "daily", "weekly", "over time", "last week", "last month", "by hour", "by day", "trending"],
            guidance="Group by time buckets and order by time for trend questions.",
            requires_columns=("time", "date", "ts", "day", "month", "hour"),
        ),
        Skill(
            name="debugging", priority=10,
            triggers=["error", "root cause", "why", "failed", "failure", "anomaly", "spike", "outage"],
            guidance="Filter for failure states and correlate likely causes.",
            requires_columns=("status", "error", "level", "state", "outcome"),
        ),
        Skill(
            name="data_exploration", priority=3,
            triggers=["what tables", "what columns", "schema", "describe", "list", "explore"],
            guidance="Answer from the schema catalog; only plan a query when the question needs data.",
        ),
    ]