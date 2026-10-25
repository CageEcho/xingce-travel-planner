"""只暂存应用源代码；不会上传本机数据库、密钥或个人文档。"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / ".deploy" / "vefaas"
IGNORE = shutil.ignore_patterns(
    "node_modules", ".next", "__pycache__", ".pytest_cache", ".env*", "tmp",
    "test-results", "playwright-report", "AGENTS.md", "*.pyc", ".vefaas",
)


def prepare() -> None:
    api = STAGE / "api"
    web = STAGE / "web"
    api.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)
    for name in ["backend", "seed"]:
        shutil.copytree(ROOT / name, api / name, dirs_exist_ok=True, ignore=IGNORE)
    shutil.copy(ROOT / "backend" / "requirements.txt", api / "requirements.txt")
    shutil.copy(ROOT / "deploy" / "vefaas" / "start_api.py", api / "start_api.py")
    shutil.copy(ROOT / "deploy" / "vefaas" / "build_api.sh", api / "build.sh")
    shutil.copytree(ROOT / "frontend", web, dirs_exist_ok=True, ignore=IGNORE)
    shutil.copy(ROOT / "deploy" / "vefaas" / "build_web.sh", web / "build.sh")
    for p in [api / "build.sh", web / "build.sh"]:
        p.chmod(0o755)
    print(f"API source: {api}")
    print(f"Web source: {web}")


if __name__ == "__main__":
    prepare()
