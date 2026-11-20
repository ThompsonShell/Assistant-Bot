import httpx
import pytest

from app.bot import runtime
from app.config import settings
from app.integrations import jira, jira_diag
from app.integrations.jira_diag import scan_env_text

GOOD = """# bot settings
JIRA_BASE_URL=https://acme.atlassian.net
JIRA_EMAIL=me@example.com
JIRA_API_TOKEN=ATATT3xSECRET
"""


def test_a_clean_file_has_no_problems():
    scan = scan_env_text(GOOD)
    assert set(scan.keys) == {"JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"}
    assert all(k.problems == [] and k.lines[-1][1] for k in scan.keys.values())
    assert scan.file_problems == []


def test_a_later_empty_line_erases_the_real_value():
    """The likely cause: the empty template block pasted again below the real values."""
    text = GOOD + "\nSOMETHING=else\n\nJIRA_BASE_URL=\nJIRA_EMAIL=\nJIRA_API_TOKEN=\n"
    scan = scan_env_text(text)
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        info = scan.keys[name]
        assert [has for _, has in info.lines] == [True, False]
        assert any("OXIRGISI" in p and "bo'sh" in p for p in info.problems), name


def test_duplicate_with_a_value_last_is_only_a_note():
    scan = scan_env_text("JIRA_EMAIL=old@example.com\nJIRA_EMAIL=new@example.com\n")
    problems = scan.keys["JIRA_EMAIL"].problems
    assert len(problems) == 1 and "oxirgisi ishlaydi" in problems[0]


@pytest.mark.parametrize("line,fragment", [
    ("JIRA_EMAIL = me@example.com", "'=' dan oldin bo'sh joy"),
    ("JIRA_EMAIL= me@example.com", "'=' dan keyin bo'sh joy"),
    ("JIRA_EMAIL=me@example.com\r", "CRLF"),
    ('JIRA_EMAIL="me@example.com', "bitta qo'shtirnoq"),
    ("JIRA_EMAIL=me@example.com # work", "izoh"),
])
def test_common_typing_mistakes_are_named(line, fragment):
    problems = scan_env_text(line + "\n").keys["JIRA_EMAIL"].problems
    assert any(fragment in p for p in problems), problems


def test_other_lines_that_would_break_sourcing_are_reported():
    scan = scan_env_text("GOOD=1\nthis is not an assignment\nHH_USER_AGENT=WorkXplorer/1.0 (https://x.uz)\nQUOTED=\"a b\"\n")
    assert len(scan.file_problems) == 2
    assert "2-qator" in scan.file_problems[0]
    assert "HH_USER_AGENT" in scan.file_problems[1] and "bo'sh joy" in scan.file_problems[1]


def test_report_never_contains_secret_values(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(GOOD.replace("JIRA_API_TOKEN=ATATT3xSECRET", "JIRA_API_TOKEN=ATATT3xSECRETVALUE1234"))
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "me@example.com")
    monkeypatch.setattr(settings, "jira_api_token", "ATATT3xSECRETVALUE1234")
    monkeypatch.setattr(settings, "jira_project_key", None)

    def handler(request):
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"displayName": "Asilbek"})
        return httpx.Response(200, json={"values": [{"key": "PRJ", "name": "Practice"}]})

    real = httpx.Client
    monkeypatch.setattr(jira.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    assert jira_diag.main(str(env)) == 0
    out = capsys.readouterr().out
    assert "Ulandi: Asilbek" in out and "PRJ" in out
    assert "acme.atlassian.net" in out and "m***@example.com" in out        # host and masked email only
    assert "SECRETVALUE" not in out and "me@example.com" not in out and "1234" not in out
    assert "uzunligi 22" in out and "ATATT" in out


def test_report_says_what_is_missing(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(GOOD + "JIRA_EMAIL=\n")
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "")
    monkeypatch.setattr(settings, "jira_api_token", "ATATT3x")
    assert jira_diag.main(str(env)) == 1
    out = capsys.readouterr().out
    assert "OXIRGISI" in out and "Yetishmayotgan: JIRA_EMAIL" in out and "ATATT3x" not in out


def test_report_explains_a_rejected_token(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text(GOOD)
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net")
    monkeypatch.setattr(settings, "jira_email", "me@example.com")
    monkeypatch.setattr(settings, "jira_api_token", "wrong")
    real = httpx.Client
    monkeypatch.setattr(jira.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})), **kw))
    assert jira_diag.main(str(env)) == 1
    assert "JIRA_API_TOKEN noto'g'ri" in capsys.readouterr().out


def test_runtime_footer_identifies_the_process():
    assert str(runtime.PID) in runtime.footer() and "ishga tushgan" in runtime.footer()
