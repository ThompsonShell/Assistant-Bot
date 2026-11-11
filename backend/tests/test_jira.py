from app.integrations.jira import JiraIssue, format_issues, is_configured


def _issue(key="PROJ-1", summary="Fix bug", status="To Do", cat="new", due=None, prio="High"):
    return JiraIssue(
        key=key, summary=summary, status=status, status_category=cat,
        due=due, priority=prio, url=f"https://x.atlassian.net/browse/{key}",
    )


def test_is_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "jira_base_url", None)
    monkeypatch.setattr(settings, "jira_email", None)
    monkeypatch.setattr(settings, "jira_api_token", None)
    assert is_configured() is False

    monkeypatch.setattr(settings, "jira_base_url", "https://x.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "a@b.com")
    monkeypatch.setattr(settings, "jira_api_token", "t")
    assert is_configured() is True


def test_format_empty():
    assert "ochiq issue yo'q" in format_issues([])


def test_format_lists_issues_with_markers():
    out = format_issues([
        _issue("PROJ-12", "Login bug", "In Progress", "indeterminate", prio="High"),
        _issue("PROJ-8", "Write docs", "To Do", "new", due="2099-01-02", prio="Low"),
    ])
    assert "PROJ-12" in out and "Login bug" in out
    assert "🟡" in out                    # in-progress marker
    assert "⚪️" in out                    # to-do marker
    assert "In Progress" in out
    assert "02-Jan" in out                # formatted due date
    assert "High" in out and "Low" in out


def test_overdue_flag():
    assert _issue(due="2000-01-01").is_overdue is True
    assert _issue(due=None).is_overdue is False
    out = format_issues([_issue("PROJ-3", "Old", due="2000-01-01")])
    assert "⚠️" in out                    # overdue warning
