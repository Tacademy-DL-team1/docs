import argparse
import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


NOTION_VERSION = "2022-06-28"
DEFAULT_OUTPUT_DIR = Path("meeting_log")
DEFAULT_REPO = "Tacademy-DL-team1/docs"


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value else default


def require_env(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"Missing environment variable: {name}")
    return value


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict | None = None,
    expected: tuple[int, ...] = (200,),
) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method, headers=headers)

    try:
        with urlopen(request, timeout=30) as response:
            content = response.read().decode("utf-8")
            if response.status not in expected:
                raise SystemExit(f"HTTP {response.status}: {content}")
            return json.loads(content) if content else {}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise SystemExit(f"Network error: {error}") from error


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "notion-meeting-sync",
    }


def notion_request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    return request_json(
        method,
        f"https://api.notion.com/v1{path}",
        notion_headers(token),
        body,
        expected=(200,),
    )


def github_request(method: str, path: str, token: str, body: dict | None = None, expected: tuple[int, ...] = (200,)) -> dict:
    return request_json(
        method,
        f"https://api.github.com{path}",
        github_headers(token),
        body,
        expected=expected,
    )


def rich_text_to_markdown(parts: list[dict]) -> str:
    chunks = []
    for part in parts:
        text = part.get("plain_text", "")
        href = part.get("href")
        annotations = part.get("annotations", {})
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"
        if href:
            text = f"[{text}]({href})"
        chunks.append(text)
    return "".join(chunks).strip()


def plain_text(parts: list[dict]) -> str:
    return "".join(part.get("plain_text", "") for part in parts).strip()


def page_property(page: dict, name: str) -> dict:
    return page.get("properties", {}).get(name, {})


def page_title(page: dict, property_name: str) -> str:
    title = plain_text(page_property(page, property_name).get("title", []))
    return title or "회의록"


def page_date(page: dict, property_name: str) -> datetime:
    date_value = page_property(page, property_name).get("date") or {}
    start = date_value.get("start")
    if start:
        return datetime.fromisoformat(start.replace("Z", "+00:00"))
    edited_time = page.get("last_edited_time") or page.get("created_time")
    if edited_time:
        return datetime.fromisoformat(edited_time.replace("Z", "+00:00"))
    return datetime.now()


def page_rich_text(page: dict, property_name: str) -> str:
    prop = page_property(page, property_name)
    prop_type = prop.get("type")
    if prop_type == "rich_text":
        return rich_text_to_markdown(prop.get("rich_text", []))
    if prop_type == "title":
        return rich_text_to_markdown(prop.get("title", []))
    return ""


def fetch_children(token: str, block_id: str) -> list[dict]:
    children = []
    cursor = None
    while True:
        path = f"/blocks/{quote(block_id)}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={quote(cursor)}"
        result = notion_request("GET", path, token)
        children.extend(result.get("results", []))
        if not result.get("has_more"):
            return children
        cursor = result.get("next_cursor")


def file_url(block: dict, block_type: str) -> str:
    value = block.get(block_type, {})
    file_info = value.get("file") or value.get("external") or {}
    return file_info.get("url", "")


def block_to_markdown(block: dict, token: str, indent: int = 0) -> list[str]:
    block_type = block.get("type")
    value = block.get(block_type, {})
    prefix = "  " * indent
    lines: list[str] = []

    if block_type == "paragraph":
        text = rich_text_to_markdown(value.get("rich_text", []))
        if text:
            lines.append(f"{prefix}{text}")
    elif block_type == "heading_1":
        lines.append(f"# {rich_text_to_markdown(value.get('rich_text', []))}")
    elif block_type == "heading_2":
        lines.append(f"## {rich_text_to_markdown(value.get('rich_text', []))}")
    elif block_type == "heading_3":
        lines.append(f"### {rich_text_to_markdown(value.get('rich_text', []))}")
    elif block_type == "bulleted_list_item":
        text = rich_text_to_markdown(value.get("rich_text", []))
        lines.append(f"{prefix}- {text}")
    elif block_type == "numbered_list_item":
        text = rich_text_to_markdown(value.get("rich_text", []))
        lines.append(f"{prefix}1. {text}")
    elif block_type == "to_do":
        text = rich_text_to_markdown(value.get("rich_text", []))
        marker = "x" if value.get("checked") else " "
        lines.append(f"{prefix}- [{marker}] {text}")
    elif block_type == "quote":
        text = rich_text_to_markdown(value.get("rich_text", []))
        lines.append(f"> {text}")
    elif block_type == "callout":
        text = rich_text_to_markdown(value.get("rich_text", []))
        if text:
            lines.extend([f"> {line}" for line in text.splitlines()])
    elif block_type == "code":
        language = value.get("language") or ""
        text = plain_text(value.get("rich_text", []))
        lines.extend([f"```{language}", text, "```"])
    elif block_type == "divider":
        lines.append("---")
    elif block_type == "image":
        caption = plain_text(value.get("caption", [])) or "image"
        url = file_url(block, block_type)
        if url:
            lines.append(f"![{caption}]({url})")

    if block.get("has_children"):
        for child in fetch_children(token, block["id"]):
            lines.extend(block_to_markdown(child, token, indent + 1))

    return lines


def normalize_lines(lines: Iterable[str]) -> str:
    output: list[str] = []
    previous_blank = False
    for line in lines:
        stripped = line.rstrip()
        blank = not stripped
        if blank and previous_blank:
            continue
        output.append(stripped)
        previous_blank = blank
    return "\n".join(output).strip()


def strip_duplicate_title(markdown: str) -> str:
    lines = markdown.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith("# "):
        lines.pop(0)
    return "\n".join(lines).strip()


def clean_heading(text: str) -> str:
    text = re.sub(r"^[#*\s]+|[*\s]+$", "", text).strip()
    text = re.sub(r"^[\W_]+", "", text, flags=re.UNICODE).strip()
    return text


def is_placeholder(line: str) -> bool:
    text = re.sub(r"^[>\-\s\[\]xX0-9.]+", "", line).strip()
    placeholders = [
        "미리 읽어야 할 자료나 결정해야 할 사항을 적어주세요",
        "회의 준비",
        "회의록",
        "Summary",
    ]
    if not text:
        return True
    return any(placeholder == text for placeholder in placeholders)


def strip_list_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?", "", line).strip()


def normalize_bullet(line: str) -> str:
    stripped = line.strip()
    if re.match(r"^- \[[ xX]\]", stripped):
        return stripped
    if re.match(r"^\d+\.\s+", stripped):
        return f"- {strip_list_marker(stripped)}"
    if stripped.startswith(("- ", "* ")):
        return f"- {strip_list_marker(stripped)}"
    return f"- {stripped}"


def split_sections(markdown: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "본문"
    current_lines: list[str] = []
    in_leading_quote = False

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped == "---":
            continue

        if stripped.startswith(">") and not sections and current_title == "본문":
            in_leading_quote = True
            continue
        if in_leading_quote and not stripped:
            continue
        in_leading_quote = False

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        bold_heading_match = re.match(r"^\*\*\s*(.+?)\s*\*\*$", stripped)
        if heading_match or bold_heading_match:
            title = clean_heading(heading_match.group(2) if heading_match else bold_heading_match.group(1))
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = title
            current_lines = []
            continue

        if is_placeholder(stripped):
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))
    return sections


def section_kind(title: str) -> str:
    normalized = re.sub(r"\s+", "", title).lower()
    if "회의준비" in normalized:
        return "skip"
    if "회의안건" in normalized or normalized == "안건":
        return "agenda"
    if "todo" in normalized or "to-do" in normalized or "할일" in normalized:
        return "todo"
    if "회의결과" in normalized or normalized == "결과" or "결정" in normalized:
        return "result"
    if "주의사항" in normalized or "주의" in normalized:
        return "caution"
    return "discussion"


def section_lines(lines: list[str], checkbox: bool = False) -> list[str]:
    output = []
    for line in lines:
        stripped = line.strip()
        if not stripped or is_placeholder(stripped):
            continue
        if stripped.startswith("#"):
            continue
        if checkbox:
            if re.match(r"^- \[[ xX]\]", stripped):
                output.append(stripped)
            else:
                output.append(f"- [ ] {strip_list_marker(stripped)}")
        else:
            output.append(normalize_bullet(stripped))
    return output


def organize_body(markdown: str) -> tuple[list[str], str]:
    sections = split_sections(strip_duplicate_title(markdown))
    agenda: list[str] = []
    caution: list[str] = []
    discussion: list[tuple[str, list[str]]] = []
    result: list[str] = []
    todo: list[str] = []

    for title, lines in sections:
        kind = section_kind(title)
        if kind == "skip":
            continue
        if kind == "agenda":
            agenda.extend(section_lines(lines))
        elif kind == "caution":
            caution.extend(section_lines(lines))
        elif kind == "result":
            result.extend(section_lines(lines))
        elif kind == "todo":
            todo.extend(section_lines(lines, checkbox=True))
        else:
            cleaned = section_lines(lines)
            if cleaned:
                discussion.append((title, cleaned))

    body: list[str] = []
    if agenda:
        body.extend(["## 📌 회의 안건", "", *agenda, ""])
    if caution:
        body.extend(["## ⚠️ 주제 선정 시 주의사항", "", *caution, ""])
    if discussion:
        body.extend(["## 🗣️ 주요 논의 내용", ""])
        for title, lines in discussion:
            if title != "본문":
                body.extend([f"### {title}", ""])
            body.extend([*lines, ""])
    if result:
        body.extend(["## 🎯 회의 결과", "", *result, ""])
    if todo:
        body.extend(["## ✅ To-Do List", "", *todo, ""])

    if not body:
        body = [markdown.strip()]

    agenda_text = ", ".join(strip_list_marker(line) for line in agenda[:3])
    return body, agenda_text


def build_markdown(page: dict, blocks: list[dict], token: str, args: argparse.Namespace) -> str:
    title = page_title(page, args.title_property)
    date = page_date(page, args.date_property).strftime("%Y-%m-%d")
    summary = page_rich_text(page, args.summary_property) or "Notion 회의록 원문을 바탕으로 정리한 내용입니다."

    body_lines: list[str] = []
    for block in blocks:
        body_lines.extend(block_to_markdown(block, token))
        body_lines.append("")

    body, agenda_text = organize_body(normalize_lines(body_lines))
    front = [
        f"# 🧠 {title} 회의록",
        "",
        "> **💡 Summary**",
        ">",
        f"> {summary}",
        "",
        "---",
        "",
        "## 📅 회의 개요",
        "",
        f"* **회의 날짜:** {date}",
        f"* **회의 주제:** {title}",
    ]
    if agenda_text:
        front.append(f"* **회의 안건:** {agenda_text}")
    front.extend(["", "---", ""])
    return normalize_lines([*front, *body]) + "\n"


def block_plain_title(block: dict) -> str:
    block_type = block.get("type")
    value = block.get(block_type, {})
    return plain_text(value.get("rich_text", []))


def is_refined_section_heading(block: dict, section_title: str) -> bool:
    if block.get("type") not in {"heading_1", "heading_2", "heading_3", "paragraph"}:
        return False
    return block_plain_title(block).strip() == section_title


def refined_markdown_from_blocks(blocks: list[dict], token: str, section_title: str) -> str:
    start = None
    for index, block in enumerate(blocks):
        if is_refined_section_heading(block, section_title):
            start = index + 1

    if start is None:
        raise SystemExit(f"Could not find Notion refined section: {section_title}")

    lines: list[str] = []
    for block in blocks[start:]:
        lines.extend(block_to_markdown(block, token))
        lines.append("")
    markdown = normalize_lines(lines)
    if not markdown:
        raise SystemExit(f"Notion refined section is empty: {section_title}")
    return markdown + "\n"


def markdown_for_github(page: dict, blocks: list[dict], token: str, args: argparse.Namespace) -> str:
    if args.draft_from_raw:
        return build_markdown(page, blocks, token, args)
    if args.refined_section:
        return refined_markdown_from_blocks(blocks, token, args.refined_section)
    return build_markdown(page, blocks, token, args)


def query_pages(token: str, database_id: str, args: argparse.Namespace) -> list[dict]:
    pages = []
    cursor = None
    while True:
        body: dict = {
            "page_size": 100,
            "filter": {
                "property": args.status_property,
                "select": {"equals": args.status},
            },
            "sorts": [{"property": args.date_property, "direction": "ascending"}],
        }
        if cursor:
            body["start_cursor"] = cursor
        result = notion_request("POST", f"/databases/{database_id}/query", token, body)
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            return pages
        cursor = result.get("next_cursor")


def patch_page_properties(token: str, page_id: str, properties: dict) -> None:
    notion_request("PATCH", f"/pages/{quote(page_id)}", token, {"properties": properties})


def filename_for(page: dict, args: argparse.Namespace) -> str:
    return f"{page_date(page, args.date_property).strftime('%y%m%d')}_meeting.md"


def branch_slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", text, flags=re.UNICODE).strip("-")
    return slug[:40] or "meeting"


def meeting_date_label(filename: str) -> str:
    match = re.match(r"(\d{6})_meeting\.md$", filename)
    return match.group(1) if match else filename.removesuffix(".md")


def docs_title(filename: str) -> str:
    return f"📝docs: {meeting_date_label(filename)} 회의록 추가"


def commit_message(filename: str, issue_number: int) -> str:
    return "\n".join(
        [
            f"docs: {meeting_date_label(filename)} 회의록 추가",
            "",
            "- Notion 정리본을 기반으로 회의록 문서 추가",
            f"- `meeting_log/{filename}` 파일 생성",
            "- 팀 회의록 템플릿 형식에 맞춰 문서화",
            "",
            f"Closes #{issue_number}",
        ]
    )


def create_issue(repo: str, token: str, page: dict, filename: str, args: argparse.Namespace) -> dict:
    title = docs_title(filename)
    body = "\n".join(
        [
            "### 설명",
            f"Notion에 작성된 `{page_title(page, args.title_property)}` 회의록을 정리하여 문서화합니다.",
            "",
            "### 작업 항목",
            f"- [ ] `meeting_log/{filename}` 생성",
            "- [ ] 회의록 템플릿 형식 확인",
            "- [ ] Notion 상태 업데이트",
            "",
            "### 참고사항",
            f"- Notion page id: `{page['id']}`",
        ]
    )
    return github_request("POST", f"/repos/{repo}/issues", token, {"title": title, "body": body}, expected=(201,))


def default_branch(repo: str, token: str) -> str:
    repository = github_request("GET", f"/repos/{repo}", token)
    return repository.get("default_branch", "main")


def ref_sha(repo: str, token: str, branch: str) -> str:
    ref = github_request("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='')}", token)
    return ref["object"]["sha"]


def create_branch(repo: str, token: str, branch: str, sha: str) -> None:
    github_request(
        "POST",
        f"/repos/{repo}/git/refs",
        token,
        {"ref": f"refs/heads/{branch}", "sha": sha},
        expected=(201,),
    )


def put_file(repo: str, token: str, branch: str, path: str, content: str, message: str) -> None:
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    body = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    github_request("PUT", f"/repos/{repo}/contents/{quote(path)}", token, body, expected=(201,))


def create_pr(repo: str, token: str, base: str, branch: str, issue_number: int, filename: str) -> dict:
    title = docs_title(filename)
    body = "\n".join(
        [
            "### 설명",
            "Notion에 정리된 회의록을 GitHub 문서로 추가합니다.",
            "",
            "### 작업 항목",
            f"- [x] `meeting_log/{filename}` 생성",
            "- [x] 회의록 템플릿 형식 확인",
            "- [x] Notion 상태 업데이트",
            "",
            "### 참고사항",
            f"Closes #{issue_number}",
        ]
    )
    return github_request(
        "POST",
        f"/repos/{repo}/pulls",
        token,
        {"title": title, "head": branch, "base": base, "body": body},
        expected=(201,),
    )


def sync_one(page: dict, notion_token: str, github_token: str, args: argparse.Namespace) -> None:
    blocks = fetch_children(notion_token, page["id"])
    filename = filename_for(page, args)
    markdown = markdown_for_github(page, blocks, notion_token, args)
    file_path = f"meeting_log/{filename}"

    issue = create_issue(args.repo, github_token, page, filename, args)
    branch = f"docs/issue-{issue['number']}-{branch_slug(filename)}"
    base = default_branch(args.repo, github_token)
    create_branch(args.repo, github_token, branch, ref_sha(args.repo, github_token, base))
    put_file(args.repo, github_token, branch, file_path, markdown, commit_message(filename, issue["number"]))
    pr = create_pr(args.repo, github_token, base, branch, issue["number"], filename)

    properties = {
        args.status_property: {"select": {"name": args.next_status}},
    }
    if args.issue_property:
        properties[args.issue_property] = {"url": issue["html_url"]}
    if args.pr_property:
        properties[args.pr_property] = {"url": pr["html_url"]}
    patch_page_properties(notion_token, page["id"], properties)

    print(f"created issue: {issue['html_url']}")
    print(f"created branch: {branch}")
    print(f"created pr: {pr['html_url']}")


def export_local(page: dict, notion_token: str, args: argparse.Namespace) -> None:
    blocks = fetch_children(notion_token, page["id"])
    filename = filename_for(page, args)
    markdown = markdown_for_github(page, blocks, notion_token, args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / filename
    output_path.write_text(markdown, encoding="utf-8")
    print(f"wrote: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create GitHub issue/branch/PR from Notion meeting logs.")
    parser.add_argument("--repo", default=env("GITHUB_REPOSITORY", DEFAULT_REPO))
    parser.add_argument("--database-id", default=env("NOTION_MEETING_DATABASE_ID"))
    parser.add_argument("--title-property", default=env("NOTION_MEETING_TITLE_PROPERTY", "회의 주제"))
    parser.add_argument("--date-property", default=env("NOTION_MEETING_DATE_PROPERTY", "날짜"))
    parser.add_argument("--summary-property", default=env("NOTION_MEETING_SUMMARY_PROPERTY", "회의 요약"))
    parser.add_argument("--status-property", default=env("NOTION_MEETING_STATUS_PROPERTY", "상태"))
    parser.add_argument("--status", default=env("NOTION_MEETING_STATUS", "정리 완료"))
    parser.add_argument("--next-status", default=env("NOTION_MEETING_NEXT_STATUS", "PR 생성"))
    parser.add_argument("--issue-property", default=env("NOTION_MEETING_ISSUE_PROPERTY", "GitHub Issue"))
    parser.add_argument("--pr-property", default=env("NOTION_MEETING_PR_PROPERTY", "GitHub PR"))
    parser.add_argument("--refined-section", default=env("NOTION_MEETING_REFINED_SECTION", "정리본"))
    parser.add_argument("--draft-from-raw", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--local-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    notion_token = require_env("NOTION_TOKEN")
    if not args.database_id:
        raise SystemExit("Missing NOTION_MEETING_DATABASE_ID")

    pages = query_pages(notion_token, args.database_id, args)
    if not pages:
        print(f"No Notion pages with {args.status_property}={args.status}")
        return

    if args.local_only:
        for page in pages:
            export_local(page, notion_token, args)
        return

    github_token = require_env("GITHUB_TOKEN")
    for page in pages:
        sync_one(page, notion_token, github_token, args)


if __name__ == "__main__":
    main()
