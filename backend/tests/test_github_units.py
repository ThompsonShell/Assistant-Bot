from app.integrations.github.actors import classify_actor
from app.integrations.github.summarize import summarize_event

from .conftest import ACTION_EVENT, PR_BOT_EVENT, PUSH_EVENT


def test_classify_actor():
    assert classify_actor("alice") == "human"
    assert classify_actor("dependabot[bot]") == "bot"
    assert classify_actor("github-actions[bot]") == "github_action"
    assert classify_actor("") == "unknown"
    assert classify_actor(None) == "unknown"
    # Never claims AI.
    assert classify_actor("some-ai-tool") == "human"


def test_summarize_push():
    s = summarize_event(PUSH_EVENT)
    assert s["title"] == "pushed 2 commits to main"
    assert s["branch"] == "main"
    assert "fix bug" in s["summary"]
    assert s["url"].endswith("/commits/main")


def test_summarize_pull_request():
    s = summarize_event(PR_BOT_EVENT)
    assert s["title"] == "opened pull request #7"
    assert s["number"] == 7
    assert s["url"] == "https://github.com/octo/demo/pull/7"


def test_summarize_issue():
    s = summarize_event(ACTION_EVENT)
    assert s["title"] == "closed issue #3"
    assert s["number"] == 3


def test_summarize_merged_pr():
    ev = {
        "type": "PullRequestEvent",
        "repo": {"name": "o/r"},
        "payload": {
            "action": "closed",
            "number": 9,
            "pull_request": {"number": 9, "merged": True, "title": "t"},
        },
    }
    assert summarize_event(ev)["title"] == "merged pull request #9"
