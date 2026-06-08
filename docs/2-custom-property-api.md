# Custom Properties, Values, and Filters API

## Summary
- Add backend-only custom property, option, and value APIs for Work Item Types.
- Store custom values in normalized typed rows, matching Plane’s built-in field strategy.
- Support dedicated value endpoints, inline `custom_fields` on work item create/update, schema output, and `filters={...}` querying.
- Do not work on frontend and do not edit `apps/api/plane/settings/test.py`.

## Data Model
- Add `IssueProperty`: workspace/project/issue_type scoped definition with `name`, `display_name`, `description`, `logo_props`, `sort_order`, `property_type`, `relation_type`, `is_required`, `default_value`, `settings`, `is_active`, `is_multi`, `validation_rules`, `formula_config`, `external_id`, `external_source`.
- Add `IssuePropertyOption`: dropdown option scoped to property/project with `name`, `description`, `logo_props`, `sort_order`, `is_active`, `is_default`, `parent`, `external_id`, `external_source`.
- Add `IssuePropertyValue`: one parent value record per issue/property with workspace/project/issue/property and external sync fields.
- Add `IssuePropertyValueItem`: one row per actual value with typed nullable columns: `text_value`, `decimal_value`, `datetime_value`, `boolean_value`, `option`, `user`, `related_issue`, `file_asset`, `sort_order`.
- Use one item row for single-value properties and multiple item rows for multi-select/multi-relation values; avoid JSON-backed value filtering.

## API Behavior
- Add property routes under `/work-item-types/{type_id}/work-item-properties/` and `/work-item-types/{type_id}/work-item-properties/{property_id}/`.
- Add option routes under `/work-item-properties/{property_id}/options/` and `/work-item-properties/{property_id}/options/{option_id}/`.
- Add value routes under `/work-items/{work_item_id}/work-item-properties/{property_id}/values/`.
- Allow project members to read; require project admins for property/option mutations; allow project members to write values on accessible work items.
- Validate project/type scoping everywhere: properties must belong to the selected type, options to the property, values to the work item’s current type.
- Add `custom_fields` to work item create/update; accept property UUID or generated property `name` keys.
- Member-picker custom values use the typed `user` FK and also create `IssueSubscriber` rows for selected users.

## Filtering
- Extend `IssueFilterSet` with custom property filter methods using `Exists` subqueries against `IssuePropertyValueItem`.
- Add an API filter backend subclass for dynamic keys like `custom_fields.<property_uuid>__exact`, `__in`, `__icontains`, `__range`, and `__isnull`.
- Wire the filter backend into API v1 project work item listing so existing `filters={...}` query style works.
- Keep built-in filters normalized: examples like `assignee_id__in` continue using join tables, not custom value strings.
- Use typed columns for correct and efficient comparisons: user/member filters use `user_id`, option filters use `option_id`, numbers use `decimal_value`, dates use `datetime_value`, text/url/email/file/formula use `text_value`.

## Indexes And Constraints
- Add unique active constraints for property name per type, option name per property, value parent per issue/property, and external ID/source per relevant project scope.
- Add `(project, property, deleted_at)` to find all active values for a property in a project, which is the common filter scope.
- Add `(issue, property, deleted_at)` to upsert/read one work item’s property value quickly and enforce one parent value per issue/property.
- Add typed indexes such as `(property, option)`, `(property, user)`, `(property, decimal_value)`, `(property, datetime_value)`, and `(property, text_value)` where supported for filter predicates.
- Prefer typed indexes over JSONB expression indexes because custom properties need range, membership, relation, and text operations with predictable query plans.

## Tests
- Add property CRUD tests for bootstrap compatibility, list/retrieve/create/update/delete, duplicate conflicts, admin-only writes, and soft delete.
- Add option CRUD tests for inline property option creation, list/retrieve/update/delete, duplicate conflicts, inactive options, and parent scope validation.
- Add value tests for upsert/get/patch/delete, single and multi values, typed validation, inactive/deleted property rejection, and cross-project rejection.
- Add work item integration tests for inline `custom_fields`, required-property enforcement, type switching validation, and member-picker subscriber creation.
- Add filter tests for custom text `__icontains`, option/user `__in`, decimal/date `__range`, boolean `__exact`, `__isnull`, and logical `and/or/not`.
- Run with: `PATH=$PATH:/root/.local/bin tests/run_api_tests_local_network.sh plane/tests/contract/api/test_work_item_types.py`.

## Assumptions
- API token scopes remain unenforced because OSS `APIToken` has no scope field.
- `/work-items/advanced-search/` is not added in this pass because this repo currently exposes `/work-items/search/`; custom filtering targets project work item list `filters`.
- Formula values are stored as text initially; formula evaluation is out of scope unless docs expose concrete execution semantics.
