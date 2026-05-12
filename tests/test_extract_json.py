from __future__ import annotations

from src.llm.extract_triples import parse_json_response


def test_parse_json_response_plain_json() -> None:
    raw = """
    {
      "doc_id": "D100",
      "entities": {
        "initiatives": [{"name": "Digital Access Labs", "description": "demo"}],
        "topics": [{"name": "digital literacy"}],
        "issues": [{"name": "metadata inconsistency"}],
        "learnings": [{"text": "clear templates help"}],
        "outcomes": []
      },
      "relations": [
        {
          "source_type": "Document",
          "source_id": "D100",
          "rel": "MENTIONS",
          "target_type": "Topic",
          "target_key": "name",
          "target_value": "digital literacy"
        }
      ]
    }
    """
    payload = parse_json_response(raw, doc_id="D100")
    assert payload["doc_id"] == "D100"
    assert payload["entities"]["topics"][0]["name"] == "digital literacy"
    assert payload["relations"][0]["rel"] == "MENTIONS"


def test_parse_json_response_markdown_fence() -> None:
    raw = """
    Here is JSON:
    ```json
    {
      "entities": {
        "initiatives": [],
        "topics": [{"name": "archive standards"}],
        "issues": [],
        "learnings": [],
        "outcomes": []
      },
      "relations": []
    }
    ```
    """
    payload = parse_json_response(raw, doc_id="D200")
    assert payload["doc_id"] == "D200"
    assert payload["entities"]["topics"][0]["name"] == "archive standards"


def test_parse_json_response_ignores_invalid_relation() -> None:
    raw = """
    {
      "entities": {
        "initiatives": [],
        "topics": [],
        "issues": [],
        "learnings": [],
        "outcomes": []
      },
      "relations": [
        {"source_type": "Document", "rel": "MENTIONS", "target_type": "Topic", "target_value": ""}
      ]
    }
    """
    payload = parse_json_response(raw, doc_id="DX")
    assert payload["relations"] == []
