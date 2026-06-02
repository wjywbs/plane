# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import IssueType
from .base import BaseSerializer


class IssueTypeCreateUpdateSerializer(BaseSerializer):
    level = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = IssueType
        fields = [
            "name",
            "description",
            "logo_props",
            "is_epic",
            "is_default",
            "is_active",
            "level",
            "external_source",
            "external_id",
        ]
        read_only_fields = ["is_default"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be empty")
        return value


class IssueTypeSerializer(BaseSerializer):
    class Meta:
        model = IssueType
        fields = "__all__"
        read_only_fields = [
            "id",
            "workspace",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "deleted_at",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        project_issue_type = getattr(instance, "project_issue_type", None)
        if project_issue_type is not None:
            response["project"] = project_issue_type.project_id
            response["is_default"] = project_issue_type.is_default
            response["level"] = project_issue_type.level
        return response
