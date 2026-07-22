# apps/api/tests/test_old_skill_removed.py
"""验证旧 agent_skills 体系已彻底移除（spec Q5 解耦决定）。"""

import importlib

import pytest


def test_agent_skill_model_removed():
    """AgentSkill 模型不再可导入。"""
    from app import models
    assert not hasattr(models, "AgentSkill")


def test_old_skill_service_removed():
    """旧 skill_service 模块（含 is_skill_enabled）不再存在。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.skill_service")


def test_projects_skills_route_removed():
    """/projects/{id}/skills 路由不再存在。"""
    from app.api import projects
    paths = [r.path for r in projects.router.routes]
    assert not any("/skills" in p for p in paths)


def test_builtin_skills_constant_removed():
    """BUILTIN_SKILLS 常量从 seed_service 移除。"""
    from app.services import seed_service
    assert not hasattr(seed_service, "BUILTIN_SKILLS")
