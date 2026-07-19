import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote


sys.path.append(str(Path(__file__).resolve().parent))
import sync_notion_meeting_pr as common  # noqa: E402


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
REFINED_SECTION_TITLE = "정리본"


def openai_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def meeting_schema() -> dict:
    item_array = {
        "type": "array",
        "items": {"type": "string"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "summary", "agenda", "discussion", "decisions", "todos", "needs_review"],
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "agenda": item_array,
            "discussion": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["heading", "items"],
                    "properties": {
                        "heading": {"type": "string"},
                        "items": item_array,
                    },
                },
            },
            "decisions": item_array,
            "todos": item_array,
            "needs_review": item_array,
        },
    }


def extract_output_text(response: dict) -> str:
    if response.get("output_text"):
        return response["output_text"]

    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def call_openai(openai_token: str, model: str, raw_markdown: str, title: str, date: str) -> dict:
    prompt = f"""
다음은 Notion에서 가져온 DL 팀프로젝트 회의 메모입니다.
GitHub 문서에 올리기 전에 Notion 안에서 검토할 수 있는 회의록 정리본으로 재구성하세요.

규칙:
- 원문에 없는 사실을 추가하지 않습니다.
- 불확실하거나 맥락이 부족한 내용은 needs_review에 넣습니다.
- Notion 템플릿 안내문, 빈 placeholder, 중복 Summary는 제거합니다.
- 회의 안건, 주요 논의 내용, 회의 결과, To-Do를 분리합니다.
- 문장은 자연스럽게 다듬되 의미를 바꾸지 않습니다.
- To-Do는 실행 가능한 작업 문장으로 정리합니다.
- 한국어로 작성합니다.

회의 주제: {title}
회의 날짜: {date}

원문:
{raw_markdown}
""".strip()

    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": "You are a careful Korean meeting-minutes editor. Preserve facts and avoid hallucination.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "meeting_minutes",
                "strict": True,
                "schema": meeting_schema(),
            },
        },
    }
    response = common.request_json("POST", OPENAI_RESPONSES_URL, openai_headers(openai_token), body, expected=(200,))
    output_text = extract_output_text(response)
    if not output_text:
        raise SystemExit("OpenAI response did not include output text.")
    return json.loads(output_text)


def render_markdown(meeting: dict, date: str) -> str:
    lines = [
        f"# 🧠 {meeting['title']} 회의록",
        "",
        "> **💡 Summary**",
        ">",
        f"> {meeting['summary']}",
        "",
        "---",
        "",
        "## 📅 회의 개요",
        "",
        f"* **회의 날짜:** {date}",
        f"* **회의 주제:** {meeting['title']}",
    ]

    if meeting["agenda"]:
        lines.append(f"* **회의 안건:** {', '.join(meeting['agenda'][:3])}")

    lines.extend(["", "---", ""])

    if meeting["agenda"]:
        lines.extend(["## 📌 회의 안건", ""])
        lines.extend(f"- {item}" for item in meeting["agenda"])
        lines.append("")

    if meeting["discussion"]:
        lines.extend(["## 🗣️ 주요 논의 내용", ""])
        for section in meeting["discussion"]:
            heading = section["heading"].strip() or "논의 내용"
            lines.extend([f"### {heading}", ""])
            lines.extend(f"- {item}" for item in section["items"])
            lines.append("")

    if meeting["decisions"]:
        lines.extend(["## 🎯 회의 결과", ""])
        lines.extend(f"- {item}" for item in meeting["decisions"])
        lines.append("")

    if meeting["todos"]:
        lines.extend(["## ✅ To-Do List", ""])
        lines.extend(f"- [ ] {item}" for item in meeting["todos"])
        lines.append("")

    if meeting["needs_review"]:
        lines.extend(["## 🔎 확인 필요", ""])
        lines.extend(f"- {item}" for item in meeting["needs_review"])
        lines.append("")

    return common.normalize_lines(lines) + "\n"


def rich_text(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text[:2000]}}]


def markdown_to_notion_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = [
        {"object": "block", "type": "divider", "divider": {}},
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": rich_text(REFINED_SECTION_TITLE)},
        },
    ]

    in_summary = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue
        if stripped.startswith("# "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": rich_text(stripped[2:].strip())},
                }
            )
            continue
        if stripped.startswith("## "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": rich_text(stripped[3:].strip())},
                }
            )
            in_summary = False
            continue
        if stripped.startswith("### "):
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": rich_text(stripped[4:].strip())},
                }
            )
            continue
        if stripped == "> **💡 Summary**":
            in_summary = True
            blocks.append(
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {"rich_text": rich_text("💡 Summary"), "icon": {"emoji": "💡"}},
                }
            )
            continue
        if stripped.startswith(">"):
            text = stripped.lstrip(">").strip()
            if not text:
                continue
            block_type = "quote" if not in_summary else "paragraph"
            blocks.append(
                {
                    "object": "block",
                    "type": block_type,
                    block_type: {"rich_text": rich_text(text)},
                }
            )
            continue
        todo_match = common.re.match(r"^- \[[ xX]\]\s+(.+)$", stripped)
        if todo_match:
            blocks.append(
                {
                    "object": "block",
                    "type": "to_do",
                    "to_do": {"rich_text": rich_text(todo_match.group(1)), "checked": False},
                }
            )
            continue
        if stripped.startswith("- "):
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rich_text(stripped[2:].strip())},
                }
            )
            continue
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": rich_text(stripped)},
            }
        )
    return blocks


def append_children(token: str, page_id: str, blocks: list[dict]) -> None:
    for index in range(0, len(blocks), 100):
        common.notion_request(
            "PATCH",
            f"/blocks/{quote(page_id)}/children",
            token,
            {"children": blocks[index : index + 100]},
        )


def block_title(block: dict) -> str:
    block_type = block.get("type")
    value = block.get(block_type, {})
    return common.plain_text(value.get("rich_text", []))


def archive_existing_refined_section(token: str, blocks: list[dict]) -> None:
    start = None
    for index, block in enumerate(blocks):
        if block.get("type") == "heading_2" and block_title(block) == REFINED_SECTION_TITLE:
            start = index
            break
    if start is None:
        return

    for block in blocks[start:]:
        common.notion_request("PATCH", f"/blocks/{quote(block['id'])}", token, {"archived": True})


def refine_one(page: dict, notion_token: str, openai_token: str, args: argparse.Namespace) -> None:
    blocks = common.fetch_children(notion_token, page["id"])
    raw_lines: list[str] = []
    for block in blocks:
        raw_lines.extend(common.block_to_markdown(block, notion_token))
        raw_lines.append("")

    title = common.page_title(page, args.title_property)
    date = common.page_date(page, args.date_property).strftime("%Y-%m-%d")
    meeting = call_openai(openai_token, args.model, common.normalize_lines(raw_lines), title, date)
    markdown = render_markdown(meeting, date)

    if args.overwrite:
        archive_existing_refined_section(notion_token, blocks)
    append_children(notion_token, page["id"], markdown_to_notion_blocks(markdown))

    properties = {
        args.status_property: {"select": {"name": args.next_status}},
    }
    if args.summary_property and meeting.get("summary"):
        properties[args.summary_property] = {"rich_text": rich_text(meeting["summary"])}
    common.patch_page_properties(notion_token, page["id"], properties)

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / common.filename_for(page, args)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"wrote preview: {output_path}")
    print(f"refined: {title}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refine Notion meeting notes with OpenAI and write back to Notion.")
    parser.add_argument("--database-id", default=common.env("NOTION_MEETING_DATABASE_ID"))
    parser.add_argument("--model", default=common.env("OPENAI_MODEL", "gpt-5-mini"))
    parser.add_argument("--title-property", default=common.env("NOTION_MEETING_TITLE_PROPERTY", "회의 주제"))
    parser.add_argument("--date-property", default=common.env("NOTION_MEETING_DATE_PROPERTY", "날짜"))
    parser.add_argument("--summary-property", default=common.env("NOTION_MEETING_SUMMARY_PROPERTY", "회의 요약"))
    parser.add_argument("--status-property", default=common.env("NOTION_MEETING_STATUS_PROPERTY", "상태"))
    parser.add_argument("--status", default=common.env("NOTION_MEETING_REFINE_STATUS", "정리 필요"))
    parser.add_argument("--next-status", default=common.env("NOTION_MEETING_REFINED_STATUS", "정리 완료"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    notion_token = common.require_env("NOTION_TOKEN")
    openai_token = common.require_env("OPENAI_API_KEY")
    if not args.database_id:
        raise SystemExit("Missing NOTION_MEETING_DATABASE_ID")

    pages = common.query_pages(notion_token, args.database_id, args)
    if not pages:
        print(f"No Notion pages with {args.status_property}={args.status}")
        return

    for page in pages:
        refine_one(page, notion_token, openai_token, args)


if __name__ == "__main__":
    main()
