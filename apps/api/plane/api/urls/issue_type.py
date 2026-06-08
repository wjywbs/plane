# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.api.views import (
    IssueTypeDetailAPIEndpoint,
    IssueTypeListCreateAPIEndpoint,
    IssueTypeSchemaAPIEndpoint,
    IssuePropertyDetailAPIEndpoint,
    IssuePropertyListCreateAPIEndpoint,
    IssuePropertyOptionDetailAPIEndpoint,
    IssuePropertyOptionListCreateAPIEndpoint,
    IssuePropertyValueAPIEndpoint,
)

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/schema/",
        IssueTypeSchemaAPIEndpoint.as_view(http_method_names=["get"]),
        name="work-item-type-schema",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/",
        IssueTypeListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="work-item-type-list",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/<uuid:type_id>/work-item-properties/",
        IssuePropertyListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="work-item-property-list",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/<uuid:type_id>/work-item-properties/<uuid:property_id>/",
        IssuePropertyDetailAPIEndpoint.as_view(http_method_names=["get", "patch", "delete"]),
        name="work-item-property-detail",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-properties/<uuid:property_id>/options/",
        IssuePropertyOptionListCreateAPIEndpoint.as_view(http_method_names=["get", "post"]),
        name="work-item-property-option-list",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-properties/<uuid:property_id>/options/<uuid:option_id>/",
        IssuePropertyOptionDetailAPIEndpoint.as_view(http_method_names=["get", "patch", "delete"]),
        name="work-item-property-option-detail",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-items/<uuid:work_item_id>/work-item-properties/<uuid:property_id>/values/",
        IssuePropertyValueAPIEndpoint.as_view(http_method_names=["get", "post", "patch", "delete"]),
        name="work-item-property-value",
    ),
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/work-item-types/<uuid:type_id>/",
        IssueTypeDetailAPIEndpoint.as_view(http_method_names=["get", "patch", "delete"]),
        name="work-item-type-detail",
    ),
]
