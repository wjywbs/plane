# Work Item Types API Plan

## Summary
- Implement backend-only Work Item Types APIs under `apps/api/plane/api`.
- Scope is Types Only: CRUD + schema endpoint; custom property APIs/data models are deferred.
- Use lazy bootstrap: first Work Item Types API access enables the project and creates `Task` and `Epic`.
- Add an in-container test runner script using local service hostnames and a temporary database.

## Key Changes
- Add `IssueType` API serializers/views/urls and register routes for:
  - `GET/POST /api/v1/workspaces/{slug}/projects/{project_id}/work-item-types/`
  - `GET/PATCH/DELETE /api/v1/workspaces/{slug}/projects/{project_id}/work-item-types/{type_id}/`
  - `GET /api/v1/workspaces/{slug}/projects/{project_id}/work-item-types/schema/`
- Use existing `IssueType` and `ProjectIssueType` models; no frontend work and no new custom-property models.
- Make bootstrap idempotent in a transaction: reuse workspace-level `Task`/`Epic` types if present, link them to the project, set `Task` as default, and set `Project.is_issue_type_enabled=True`.
- Enforce project scoping for `type_id` on work item create/update so callers cannot assign cross-project or inactive types; fix default type lookup to use the project link.
- Restrict mutations to project admins; allow project members to read.
- Return schema with standard fields, priority/state options, optional members/labels via `include`, estimate points when configured, and `custom_fields: {}`.

## Validation Rules
- Reject duplicate type names within the workspace-backed model scope with `409`.
- Reject duplicate `external_id` + `external_source` for types linked to the same project with `409`.
- Prevent disabling or deleting the project default type.
- Soft-delete non-default types so existing work items retain their historical type reference.

## Tests
- Add contract tests for lazy bootstrap, list/retrieve/create/update/delete, duplicate handling, admin-only writes, and default protection.
- Add schema tests for standard fields, priority/state options, `include=members,labels`, estimate-point options, and invalid `type_id`.
- Add work item integration tests for default type assignment, valid explicit type assignment, inactive type rejection, and cross-project type rejection.
- Add `apps/api/tests/run_api_tests_local_network.sh` to create a unique DB on `plane-db`, run pytest with local service host overrides, and drop all temporary DBs on exit.

## Assumptions
- API token scopes in docs are not enforced because the OSS `APIToken` model has no scope field.
- Custom property/options/value endpoints are intentionally out of scope for this pass.
- The new test script is meant to run in an environment with API Python dependencies installed, such as the API Docker image/container.
