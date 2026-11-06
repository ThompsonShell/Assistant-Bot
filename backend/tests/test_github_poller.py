import datetime as dt

from app.db import Base, make_engine, make_sessionmaker
from app.integrations.github import poll_repo
from app.models.github import GitHubEvent, GitHubRepo
from app.models.notification import Notification
from app.notifications import DashboardChannel, Notifier

from .conftest import SAMPLE_EVENTS, FakeGitHubClient


def _session():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_sessionmaker(engine)()


def _repo(db):
    repo = GitHubRepo(owner="octo", name="demo", full_name="octo/demo", active=True)
    db.add(repo)
    db.commit()
    return repo


def test_poll_stores_and_tags_actors():
    db = _session()
    repo = _repo(db)
    client = FakeGitHubClient(SAMPLE_EVENTS)

    n = poll_repo(db, client, repo)
    assert n == 3
    assert db.query(GitHubEvent).count() == 3

    tags = {e.gh_id: e.actor_type for e in db.query(GitHubEvent).all()}
    assert tags["1001"] == "human"
    assert tags["1002"] == "bot"
    assert tags["1003"] == "github_action"
    assert repo.etag == "ETAG-1"
    assert repo.last_polled_at is not None


def test_poll_is_idempotent_via_etag():
    db = _session()
    repo = _repo(db)
    client = FakeGitHubClient(SAMPLE_EVENTS)
    assert poll_repo(db, client, repo) == 3
    # Second poll presents the stored ETag -> 304 -> nothing new.
    assert poll_repo(db, client, repo) == 0
    assert db.query(GitHubEvent).count() == 3


def test_poll_dedups_even_without_etag():
    db = _session()
    repo = _repo(db)
    assert poll_repo(db, FakeGitHubClient(SAMPLE_EVENTS, etag="A") , repo) == 3
    repo.etag = None  # force re-fetch with a different client/etag
    db.commit()
    # Same events returned again -> all duplicates -> 0 new.
    assert poll_repo(db, FakeGitHubClient(SAMPLE_EVENTS, etag="B"), repo) == 0
    assert db.query(GitHubEvent).count() == 3


COMMIT_SAMPLE = [
    {
        "sha": "abc123def456",
        "html_url": "https://github.com/octo/demo/commit/abc123def456",
        "commit": {"author": {"name": "Alice", "date": "2026-01-06T09:00:00Z"}, "message": "Fix things\n\nbody"},
        "author": {"login": "alice", "type": "User"},
    }
]


def test_poll_ingests_commits():
    db = _session()
    repo = _repo(db)
    client = FakeGitHubClient([], etag="X", commits=COMMIT_SAMPLE)
    assert poll_repo(db, client, repo) == 1
    ev = db.query(GitHubEvent).filter(GitHubEvent.type == "Commit").one()
    assert ev.gh_id == "commit:abc123def456"
    assert ev.actor_login == "alice"
    assert ev.title == "committed abc123d"
    assert ev.summary == "Fix things"
    # Polling again doesn't duplicate the commit.
    assert poll_repo(db, client, repo) == 0


def test_first_poll_is_silent_baseline():
    # Adding a repo backfills history WITHOUT notifications (no flood).
    db = _session()
    repo = _repo(db)  # last_polled_at is None -> first poll
    notifier = Notifier([DashboardChannel()])
    n = poll_repo(db, FakeGitHubClient(SAMPLE_EVENTS), repo, notifier)
    assert n == 3  # events ARE stored
    assert db.query(GitHubEvent).count() == 3
    assert db.query(Notification).count() == 0  # but nothing was sent


def test_poll_records_notifications():
    db = _session()
    repo = _repo(db)
    # Simulate a repo that has already been baselined (not the first poll).
    repo.last_polled_at = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    db.commit()
    notifier = Notifier([DashboardChannel()])
    poll_repo(db, FakeGitHubClient(SAMPLE_EVENTS), repo, notifier)
    notes = db.query(Notification).all()
    assert len(notes) == 3
    assert all(n.channel == "dashboard" and n.delivered for n in notes)
    assert all(n.category == "github" for n in notes)
