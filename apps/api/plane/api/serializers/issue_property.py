# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from decimal import Decimal, InvalidOperation
from uuid import UUID

# Django imports
from django.core.exceptions import ValidationError as DjangoValidationError
from django.template.defaultfilters import slugify
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

# Third party imports
from rest_framework import serializers

# Module imports
from plane.db.models import (
    FileAsset,
    Issue,
    IssueProperty,
    IssuePropertyOption,
    IssuePropertyValue,
    IssuePropertyValueItem,
    IssueSubscriber,
    ProjectMember,
    User,
)
from .base import BaseSerializer


TEXT_PROPERTY_TYPES = {
    IssueProperty.PropertyType.TEXT,
    IssueProperty.PropertyType.URL,
    IssueProperty.PropertyType.EMAIL,
    IssueProperty.PropertyType.FORMULA,
}


def generate_property_name(display_name):
    value = slugify(display_name or "").replace("-", "_")
    return value.strip("_")


def parse_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise serializers.ValidationError("Value must be a valid UUID")


def ensure_list(value, is_multi):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    if len(values) > 1 and not is_multi:
        raise serializers.ValidationError("Property does not allow multiple values")
    return values


def serialize_property_value(issue_property, items):
    values = []
    for item in items:
        if issue_property.property_type in TEXT_PROPERTY_TYPES:
            values.append(item.text_value)
        elif issue_property.property_type == IssueProperty.PropertyType.FILE:
            values.append(str(item.file_asset_id) if item.file_asset_id else item.text_value)
        elif issue_property.property_type == IssueProperty.PropertyType.DECIMAL:
            values.append(float(item.decimal_value) if item.decimal_value is not None else None)
        elif issue_property.property_type == IssueProperty.PropertyType.DATETIME:
            values.append(item.datetime_value.isoformat() if item.datetime_value else None)
        elif issue_property.property_type == IssueProperty.PropertyType.BOOLEAN:
            values.append(item.boolean_value)
        elif issue_property.property_type == IssueProperty.PropertyType.OPTION:
            values.append(str(item.option_id))
        elif issue_property.property_type == IssueProperty.PropertyType.RELATION:
            if issue_property.relation_type == IssueProperty.RelationType.USER:
                values.append(str(item.user_id))
            else:
                values.append(str(item.related_issue_id))

    return values if issue_property.is_multi else (values[0] if values else None)


def validate_property_value(issue_property, raw_value, issue):
    values = ensure_list(raw_value, issue_property.is_multi)
    validated_items = []

    for index, value in enumerate(values):
        if issue_property.property_type in TEXT_PROPERTY_TYPES:
            if not isinstance(value, str):
                raise serializers.ValidationError("Value must be a string")
            validated_items.append({"text_value": value, "sort_order": index})
        elif issue_property.property_type == IssueProperty.PropertyType.FILE:
            asset_id = parse_uuid(value)
            if not FileAsset.objects.filter(project_id=issue.project_id, id=asset_id).exists():
                raise serializers.ValidationError("File asset is not valid")
            validated_items.append({"file_asset_id": asset_id, "sort_order": index})
        elif issue_property.property_type == IssueProperty.PropertyType.DECIMAL:
            try:
                decimal_value = Decimal(str(value))
            except (InvalidOperation, TypeError):
                raise serializers.ValidationError("Value must be a number")
            validated_items.append({"decimal_value": decimal_value, "sort_order": index})
        elif issue_property.property_type == IssueProperty.PropertyType.DATETIME:
            datetime_value = parse_datetime(str(value))
            if datetime_value is None:
                date_value = parse_date(str(value))
                if date_value is not None:
                    datetime_value = timezone.datetime.combine(date_value, timezone.datetime.min.time())
            if datetime_value is None:
                raise serializers.ValidationError("Value must be a valid date or datetime")
            if timezone.is_naive(datetime_value):
                datetime_value = timezone.make_aware(datetime_value)
            validated_items.append({"datetime_value": datetime_value, "sort_order": index})
        elif issue_property.property_type == IssueProperty.PropertyType.BOOLEAN:
            if not isinstance(value, bool):
                raise serializers.ValidationError("Value must be a boolean")
            validated_items.append({"boolean_value": value, "sort_order": index})
        elif issue_property.property_type == IssueProperty.PropertyType.OPTION:
            option_id = parse_uuid(value)
            if not IssuePropertyOption.objects.filter(
                project_id=issue.project_id,
                property=issue_property,
                id=option_id,
                is_active=True,
            ).exists():
                raise serializers.ValidationError("Option is not valid")
            validated_items.append({"option_id": option_id, "sort_order": index})
        elif issue_property.property_type == IssueProperty.PropertyType.RELATION:
            related_id = parse_uuid(value)
            if issue_property.relation_type == IssueProperty.RelationType.USER:
                if not ProjectMember.objects.filter(
                    project_id=issue.project_id,
                    member_id=related_id,
                    is_active=True,
                    role__gte=15,
                ).exists():
                    raise serializers.ValidationError("User is not valid")
                validated_items.append({"user_id": related_id, "sort_order": index})
            else:
                if not Issue.issue_objects.filter(project_id=issue.project_id, id=related_id).exists():
                    raise serializers.ValidationError("Related work item is not valid")
                validated_items.append({"related_issue_id": related_id, "sort_order": index})
        else:
            raise serializers.ValidationError("Unsupported property type")

    return validated_items


def get_issue_property_for_key(project_id, issue_type_id, key):
    queryset = IssueProperty.objects.filter(
        project_id=project_id,
        issue_type_id=issue_type_id,
        is_active=True,
    )
    try:
        return queryset.get(id=key)
    except (DjangoValidationError, IssueProperty.DoesNotExist, ValueError):
        return queryset.get(name=key)


def validate_required_properties(issue, custom_fields):
    missing = []
    properties = IssueProperty.objects.filter(
        project_id=issue.project_id,
        issue_type_id=issue.type_id,
        is_active=True,
        is_required=True,
    )
    for issue_property in properties:
        has_value = issue_property.values.filter(issue=issue).exists()
        has_in_payload = str(issue_property.id) in custom_fields or issue_property.name in custom_fields
        if not has_value and not has_in_payload:
            missing.append(issue_property.name)
    if missing:
        raise serializers.ValidationError(
            {"custom_fields": f"Required custom fields are missing: {', '.join(missing)}"}
        )


def upsert_issue_property_value(issue, issue_property, raw_value, external_id=None, external_source=None):
    validated_items = validate_property_value(issue_property, raw_value, issue)
    if issue_property.is_required and not validated_items:
        raise serializers.ValidationError("Required property value cannot be empty")

    value, _ = IssuePropertyValue.objects.get_or_create(
        issue=issue,
        property=issue_property,
        defaults={
            "project_id": issue.project_id,
            "workspace_id": issue.workspace_id,
            "external_id": external_id,
            "external_source": external_source,
        },
    )

    update_fields = []
    if external_id is not None:
        value.external_id = external_id
        update_fields.append("external_id")
    if external_source is not None:
        value.external_source = external_source
        update_fields.append("external_source")
    if update_fields:
        value.save(update_fields=[*update_fields, "updated_at"])

    value.items.all().delete()
    IssuePropertyValueItem.objects.bulk_create(
        [
            IssuePropertyValueItem(
                value=value,
                property=issue_property,
                issue=issue,
                project_id=issue.project_id,
                workspace_id=issue.workspace_id,
                **item_data,
            )
            for item_data in validated_items
        ]
    )

    if issue_property.property_type == IssueProperty.PropertyType.RELATION:
        if issue_property.relation_type == IssueProperty.RelationType.USER:
            IssueSubscriber.objects.bulk_create(
                [
                    IssueSubscriber(
                        issue=issue,
                        subscriber_id=item_data["user_id"],
                        project_id=issue.project_id,
                        workspace_id=issue.workspace_id,
                    )
                    for item_data in validated_items
                    if item_data.get("user_id")
                ],
                ignore_conflicts=True,
            )

    return value


def apply_custom_fields(issue, custom_fields):
    if not custom_fields:
        validate_required_properties(issue, {})
        return
    if not issue.type_id:
        raise serializers.ValidationError({"custom_fields": "Work item type is required for custom fields"})

    validate_required_properties(issue, custom_fields)
    errors = {}
    for key, raw_value in custom_fields.items():
        try:
            issue_property = get_issue_property_for_key(issue.project_id, issue.type_id, key)
            upsert_issue_property_value(issue, issue_property, raw_value)
        except IssueProperty.DoesNotExist:
            errors[key] = "Property is not valid"
        except serializers.ValidationError as error:
            errors[key] = error.detail
    if errors:
        raise serializers.ValidationError({"custom_fields": errors})


class IssuePropertyOptionSerializer(BaseSerializer):
    class Meta:
        model = IssuePropertyOption
        fields = "__all__"
        validators = []
        read_only_fields = [
            "id",
            "workspace",
            "project",
            "property",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "deleted_at",
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be empty")
        return value


class IssuePropertySerializer(BaseSerializer):
    options = IssuePropertyOptionSerializer(many=True, required=False)

    class Meta:
        model = IssueProperty
        fields = "__all__"
        validators = []
        read_only_fields = [
            "id",
            "workspace",
            "project",
            "issue_type",
            "name",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "deleted_at",
        ]

    def validate_display_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Display name cannot be empty")
        return value

    def validate(self, attrs):
        property_type = attrs.get("property_type", getattr(self.instance, "property_type", None))
        relation_type = attrs.get("relation_type", getattr(self.instance, "relation_type", None))
        is_required = attrs.get("is_required", getattr(self.instance, "is_required", False))

        if property_type == IssueProperty.PropertyType.RELATION and relation_type not in {
            IssueProperty.RelationType.ISSUE,
            IssueProperty.RelationType.USER,
        }:
            raise serializers.ValidationError({"relation_type": "Relation type is required for relation properties"})
        if property_type != IssueProperty.PropertyType.RELATION and relation_type:
            raise serializers.ValidationError({"relation_type": "Relation type is only valid for relation properties"})
        if property_type == IssueProperty.PropertyType.BOOLEAN and is_required:
            raise serializers.ValidationError({"is_required": "Boolean properties cannot be required"})
        if (
            property_type == IssueProperty.PropertyType.TEXT
            and attrs.get("settings", {}).get("is_read_only")
            and is_required
        ):
            raise serializers.ValidationError({"is_required": "Read-only text properties cannot be required"})
        return attrs

    def create(self, validated_data):
        options = validated_data.pop("options", [])
        validated_data["name"] = generate_property_name(validated_data["display_name"])
        issue_property = super().create(validated_data)
        for index, option_data in enumerate(options):
            IssuePropertyOption.objects.create(
                project=issue_property.project,
                property=issue_property,
                sort_order=option_data.get("sort_order", (index + 1) * 10000),
                **option_data,
            )
        return issue_property

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["options"] = IssuePropertyOptionSerializer(
            instance.options.filter(deleted_at__isnull=True).order_by("sort_order", "name"),
            many=True,
        ).data
        return response


class IssuePropertyValueSerializer(BaseSerializer):
    value = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = IssuePropertyValue
        fields = "__all__"
        validators = []
        read_only_fields = [
            "id",
            "workspace",
            "project",
            "issue",
            "property",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "deleted_at",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        issue_property = instance.property
        items = instance.items.filter(deleted_at__isnull=True).order_by("sort_order", "created_at")
        response["property_id"] = str(issue_property.id)
        response["issue_id"] = str(instance.issue_id)
        response["value"] = serialize_property_value(issue_property, items)
        response["value_type"] = issue_property.property_type
        return response
