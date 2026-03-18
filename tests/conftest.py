"""Shared test fixtures and factories for nstd tests."""

import factory


class GitHubIssueFactory(factory.Factory):
    """Factory for GitHub issue API response dicts."""

    class Meta:
        model = dict

    number = factory.Sequence(lambda n: n + 100)
    title = factory.Faker("sentence", nb_words=5)
    body = factory.Faker("paragraph")
    state = "open"
    html_url = factory.LazyAttribute(
        lambda o: f"https://github.com/cncf/staff/issues/{o.number}"
    )
    assignees = factory.LazyFunction(lambda: [{"login": "nate-double-u"}])
    labels = factory.LazyFunction(lambda: [])
    created_at = "2026-03-01T00:00:00Z"
    updated_at = "2026-03-15T00:00:00Z"


class JiraIssueFactory(factory.Factory):
    """Factory for Jira issue dicts (simplified)."""

    class Meta:
        model = dict

    key = factory.Sequence(lambda n: f"CNCFSD-{n + 100}")
    fields = factory.LazyAttribute(
        lambda o: {
            "summary": f"Jira task {o.key}",
            "description": "A Jira task description",
            "status": {"name": "In Progress", "statusCategory": {"name": "In Progress"}},
            "priority": {"name": "Medium"},
            "assignee": {"displayName": "Nate", "emailAddress": "nate@example.com"},
            "created": "2026-03-01T00:00:00.000+0000",
            "updated": "2026-03-15T00:00:00.000+0000",
            "duedate": "2026-03-25",
        }
    )


class AsanaTaskFactory(factory.Factory):
    """Factory for Asana task dicts."""

    class Meta:
        model = dict

    gid = factory.Sequence(lambda n: str(1200000000000 + n))
    name = factory.Faker("sentence", nb_words=4)
    notes = factory.Faker("paragraph")
    completed = False
    due_on = "2026-03-25"
    start_on = "2026-03-18"
    permalink_url = factory.LazyAttribute(
        lambda o: f"https://app.asana.com/0/0/{o.gid}"
    )
    assignee = factory.LazyFunction(lambda: {"gid": "me"})
    memberships = factory.LazyFunction(lambda: [])
    custom_fields = factory.LazyFunction(lambda: [])


class CalendarEventFactory(factory.Factory):
    """Factory for Google Calendar event dicts."""

    class Meta:
        model = dict

    id = factory.Faker("uuid4")
    summary = factory.Faker("sentence", nb_words=4)
    start = factory.LazyFunction(lambda: {"dateTime": "2026-03-20T09:00:00-07:00"})
    end = factory.LazyFunction(lambda: {"dateTime": "2026-03-20T11:00:00-07:00"})
    description = ""
    colorId = None
