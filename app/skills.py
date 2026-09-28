"""Import inert skill text from a browser directory or a public GitHub repository."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

import requests

from . import db
from .config import SKILLS_DIR

MAX_FILES = 128
MAX_FILE_BYTES = 256_000
MAX_TOTAL_BYTES = 1_000_000
MAX_SKILLS = 20
ALLOWED_SUFFIXES = {".md", ".txt"}
GITHUB_API = "https://api.github.com"


def _clean_path(value: str) -> str:
    if not isinstance(value, str) or "\\" in value or "\x00" in value or len(value) > 300:
        raise ValueError("文件路径无效")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("不允许绝对路径或跨目录路径")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("只接受 Markdown 或纯文本资料")
    return str(path)


def _skill_roots(files: dict[str, str]) -> list[str]:
    roots = sorted(str(PurePosixPath(path).parent) for path in files if PurePosixPath(path).name == "SKILL.md")
    if not roots:
        raise ValueError("未找到 SKILL.md")
    if len(roots) > MAX_SKILLS:
        raise ValueError(f"一次最多导入 {MAX_SKILLS} 个 skill")
    return roots


def _title(content: str, fallback: str) -> tuple[str, str]:
    name = fallback
    description = ""
    if content.startswith("---\n"):
        header = content.split("\n---", 1)[0]
        for key, val in re.findall(r"^(name|description):\s*(.+)$", header, re.MULTILINE):
            if key == "name":
                name = val.strip(' "\'')
            else:
                description = val.strip(' "\'')
    if name == fallback:
        heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if heading:
            name = heading.group(1).strip()
    return name[:120], description[:500]


def import_files(files: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise ValueError(f"文件数必须为 1 到 {MAX_FILES}")
    if not isinstance(source, str) or len(source) > 500:
        raise ValueError("来源无效")
    validated: dict[str, str] = {}
    total = 0
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            raise ValueError("文件内容必须是文本")
        path = _clean_path(item.get("path"))
        size = len(item["content"].encode("utf-8"))
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("skill 资料超过大小限制")
        if path in validated:
            raise ValueError("文件路径重复")
        validated[path] = item["content"]
    roots = _skill_roots(validated)
    records: list[dict[str, Any]] = []
    for root in roots:
        key = "SKILL.md" if root == "." else f"{root}/SKILL.md"
        section = {path[len(root) + 1:] if root != "." else path: text
                   for path, text in validated.items()
                   if root == "." or path.startswith(root + "/")}
        # A nested SKILL.md starts a separate skill, never a parent resource.
        section = {path: text for path, text in section.items()
                   if path == "SKILL.md" or not any(path.startswith(
                       (child[len(root) + 1:] if root != "." else child) + "/") for child in roots if child != root)}
        skill_id = uuid.uuid4().hex
        name, description = _title(validated[key], PurePosixPath(root).name if root != "." else "Imported skill")
        destination = SKILLS_DIR / skill_id
        destination.mkdir(parents=True, exist_ok=False)
        for path, content in section.items():
            file = destination / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        db.execute("INSERT INTO skills(id,name,description,source,path,imported_at) VALUES(?,?,?,?,?,?)",
                   (skill_id, name, description, source, str(destination), db.utc_now()))
        records.append({"id": skill_id, "name": name, "description": description, "source": source,
                        "file_count": len(section)})
    return records


def list_skills() -> list[dict[str, Any]]:
    return db.rows("SELECT id,name,description,source,imported_at FROM skills ORDER BY imported_at DESC,id DESC")


def skill_context(ids: list[str]) -> str:
    if not isinstance(ids, list) or len(ids) > 5 or any(not re.fullmatch(r"[0-9a-f]{32}", value) for value in ids):
        raise ValueError("一次最多选择五个已导入的 skill")
    parts = []
    for skill_id in ids:
        record = db.row("SELECT name,path FROM skills WHERE id=?", (skill_id,))
        if record is None:
            raise ValueError("选择的 skill 不存在")
        root = Path(record["path"])
        docs = []
        for file in sorted(root.rglob("*")):
            if file.is_file() and file.suffix.lower() in ALLOWED_SUFFIXES:
                docs.append(f"## {file.relative_to(root).as_posix()}\n{file.read_text(encoding='utf-8')}")
        parts.append(f"# {record['name']}\n" + "\n\n".join(docs))
    result = "\n\n".join(parts)
    if len(result) > 50_000:
        raise ValueError("所选 skill 内容过长，请减少选择")
    return result


def _get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "a-share-lab"},
                            timeout=12, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f"GitHub 返回 {response.status_code}，请检查公开仓库地址或稍后重试")
    if len(response.content) > MAX_TOTAL_BYTES * 4:
        raise ValueError("GitHub 目录信息过大")
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("GitHub 返回格式无效")
    return value


def import_github(url: str) -> list[dict[str, Any]]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment:
        raise ValueError("请使用公开 GitHub 仓库的 https 地址")
    parts = parsed.path.strip("/").split("/")
    if (len(parts) != 2 and len(parts) < 4) or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts[:2]):
        raise ValueError("GitHub 地址格式应为 /owner/repo 或 /owner/repo/tree/branch/目录")
    owner, repo = parts[:2]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo or (len(parts) > 2 and parts[2] != "tree"):
        raise ValueError("GitHub 仓库地址无效")
    branch = parts[3] if len(parts) > 2 else None
    prefix = "/".join(parts[4:]) if len(parts) > 4 else ""
    if prefix:
        _clean_path(prefix + "/SKILL.md")
    repo_info = _get_json(f"{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}")
    if repo_info.get("private") is not False:
        raise ValueError("只支持公开 GitHub 仓库")
    branch = branch or repo_info.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise ValueError("无法确定 GitHub 默认分支")
    tree = _get_json(f"{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(branch, safe='')}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("GitHub 目录列表被截断，请指定更小的目录")
    entries = tree.get("tree", [])
    paths = []
    for entry in entries:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if prefix and not path.startswith(prefix + "/"):
            continue
        if PurePosixPath(path).suffix.lower() in ALLOWED_SUFFIXES:
            paths.append(_clean_path(path))
    roots = _skill_roots({path: "" for path in paths})
    chosen = [path for path in paths if any(root == "." or path.startswith(root + "/") for root in roots)]
    if len(chosen) > MAX_FILES:
        raise ValueError("仓库中的文本资料太多，请指定更小的目录")
    files = []
    total = 0
    for path in chosen:
        raw_url = f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/{quote(branch, safe='')}/{quote(path)}"
        response = requests.get(raw_url, timeout=12, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"GitHub 文件下载失败：{path} ({response.status_code})")
        total += len(response.content)
        if len(response.content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("GitHub skill 资料超过大小限制")
        files.append({"path": path, "content": response.content.decode("utf-8")})
    return import_files(files, url)
