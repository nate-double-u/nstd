# Integration Tests

Integration tests require real API credentials and are **never** run in CI.

## Required Environment Variables

| Variable | Description |
|---|---|
| `NSTD_TEST_GITHUB_TOKEN` | GitHub PAT with `repo`, `read:org`, `read:project` scopes |
| `NSTD_TEST_JIRA_URL` | Jira Cloud instance URL |
| `NSTD_TEST_JIRA_USERNAME` | Jira username (email) |
| `NSTD_TEST_JIRA_TOKEN` | Jira API token |
| `NSTD_TEST_ASANA_TOKEN` | Asana PAT |

## Safety Rules

- All tests are **read-only** where possible
- Tests that write use dedicated test resources only
- Google Calendar tests use a dedicated `NSTD Planning TEST` calendar
- Never modify production data

## Running

```bash
# Set required env vars first, then:
pytest tests/integration/ -m integration
```

## Cleanup

If a test run fails mid-execution, check for leftover test resources:
- Google Calendar: events prefixed with `[TEST]` in `NSTD Planning TEST`
- Jira: comments containing `[nstd-test]`
