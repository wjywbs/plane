# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import models
from django.db.models import Q

# Module imports
from .project import ProjectBaseModel


class IssueProperty(ProjectBaseModel):
    class PropertyType(models.TextChoices):
        TEXT = "TEXT", "Text"
        DATETIME = "DATETIME", "Datetime"
        DECIMAL = "DECIMAL", "Decimal"
        BOOLEAN = "BOOLEAN", "Boolean"
        OPTION = "OPTION", "Option"
        RELATION = "RELATION", "Relation"
        URL = "URL", "URL"
        EMAIL = "EMAIL", "Email"
        FILE = "FILE", "File"
        FORMULA = "FORMULA", "Formula"

    class RelationType(models.TextChoices):
        ISSUE = "ISSUE", "Issue"
        USER = "USER", "User"

    issue_type = models.ForeignKey(
        "db.IssueType",
        related_name="issue_properties",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    logo_props = models.JSONField(default=dict)
    sort_order = models.FloatField(default=65535)
    property_type = models.CharField(max_length=50, choices=PropertyType.choices)
    relation_type = models.CharField(max_length=50, choices=RelationType.choices, null=True, blank=True)
    is_required = models.BooleanField(default=False)
    default_value = models.JSONField(default=list)
    settings = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    is_multi = models.BooleanField(default=False)
    validation_rules = models.JSONField(default=dict)
    formula_config = models.TextField(null=True, blank=True)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Issue Property"
        verbose_name_plural = "Issue Properties"
        db_table = "issue_properties"
        ordering = ("sort_order", "display_name")
        constraints = [
            models.UniqueConstraint(
                fields=["project", "issue_type", "name"],
                condition=Q(deleted_at__isnull=True),
                name="issue_property_unique_type_name_active",
            ),
            models.UniqueConstraint(
                fields=["project", "issue_type", "display_name"],
                condition=Q(deleted_at__isnull=True),
                name="issue_property_unique_type_display_active",
            ),
            models.UniqueConstraint(
                fields=["project", "issue_type", "external_source", "external_id"],
                condition=Q(
                    deleted_at__isnull=True,
                    external_source__isnull=False,
                    external_id__isnull=False,
                ),
                name="issue_property_unique_type_external_active",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "issue_type", "deleted_at"], name="issue_prop_project_type_idx"),
            models.Index(fields=["project", "name", "deleted_at"], name="issue_prop_project_name_idx"),
        ]

    def __str__(self):
        return f"{self.display_name} ({self.issue_type_id})"


class IssuePropertyOption(ProjectBaseModel):
    property = models.ForeignKey(
        "db.IssueProperty",
        related_name="options",
        on_delete=models.CASCADE,
    )
    parent = models.ForeignKey(
        "self",
        related_name="children",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    logo_props = models.JSONField(default=dict)
    sort_order = models.FloatField(default=65535)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Issue Property Option"
        verbose_name_plural = "Issue Property Options"
        db_table = "issue_property_options"
        ordering = ("sort_order", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["property", "name"],
                condition=Q(deleted_at__isnull=True),
                name="issue_property_option_unique_name_active",
            ),
            models.UniqueConstraint(
                fields=["property", "external_source", "external_id"],
                condition=Q(
                    deleted_at__isnull=True,
                    external_source__isnull=False,
                    external_id__isnull=False,
                ),
                name="issue_property_option_unique_external_active",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "property", "deleted_at"], name="issue_prop_option_project_idx"),
            models.Index(fields=["property", "is_active", "deleted_at"], name="issue_prop_option_active_idx"),
        ]

    def __str__(self):
        return f"{self.property_id} - {self.name}"


class IssuePropertyValue(ProjectBaseModel):
    issue = models.ForeignKey(
        "db.Issue",
        related_name="property_values",
        on_delete=models.CASCADE,
    )
    property = models.ForeignKey(
        "db.IssueProperty",
        related_name="values",
        on_delete=models.CASCADE,
    )
    external_source = models.CharField(max_length=255, null=True, blank=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        verbose_name = "Issue Property Value"
        verbose_name_plural = "Issue Property Values"
        db_table = "issue_property_values"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "property"],
                condition=Q(deleted_at__isnull=True),
                name="issue_property_value_unique_issue_property_active",
            ),
            models.UniqueConstraint(
                fields=["project", "external_source", "external_id"],
                condition=Q(
                    deleted_at__isnull=True,
                    external_source__isnull=False,
                    external_id__isnull=False,
                ),
                name="issue_property_value_unique_external_active",
            ),
        ]
        indexes = [
            models.Index(fields=["project", "property", "deleted_at"], name="issue_prop_value_project_idx"),
            models.Index(fields=["issue", "property", "deleted_at"], name="issue_prop_value_issue_idx"),
        ]

    def __str__(self):
        return f"{self.issue_id} - {self.property_id}"


class IssuePropertyValueItem(ProjectBaseModel):
    value = models.ForeignKey(
        "db.IssuePropertyValue",
        related_name="items",
        on_delete=models.CASCADE,
    )
    property = models.ForeignKey(
        "db.IssueProperty",
        related_name="value_items",
        on_delete=models.CASCADE,
    )
    issue = models.ForeignKey(
        "db.Issue",
        related_name="property_value_items",
        on_delete=models.CASCADE,
    )
    text_value = models.TextField(null=True, blank=True)
    decimal_value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    datetime_value = models.DateTimeField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    option = models.ForeignKey(
        "db.IssuePropertyOption",
        related_name="value_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="issue_property_value_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    related_issue = models.ForeignKey(
        "db.Issue",
        related_name="related_property_value_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    file_asset = models.ForeignKey(
        "db.FileAsset",
        related_name="property_value_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    sort_order = models.FloatField(default=65535)

    class Meta:
        verbose_name = "Issue Property Value Item"
        verbose_name_plural = "Issue Property Value Items"
        db_table = "issue_property_value_items"
        ordering = ("sort_order", "created_at")
        indexes = [
            models.Index(fields=["project", "property", "deleted_at"], name="issue_prop_item_project_idx"),
            models.Index(fields=["issue", "property", "deleted_at"], name="issue_prop_item_issue_idx"),
            models.Index(fields=["property", "option", "deleted_at"], name="issue_prop_item_option_idx"),
            models.Index(fields=["property", "user", "deleted_at"], name="issue_prop_item_user_idx"),
            models.Index(fields=["property", "related_issue", "deleted_at"], name="issue_prop_item_rel_issue_idx"),
            models.Index(fields=["property", "decimal_value", "deleted_at"], name="issue_prop_item_decimal_idx"),
            models.Index(fields=["property", "datetime_value", "deleted_at"], name="issue_prop_item_datetime_idx"),
            models.Index(fields=["property", "boolean_value", "deleted_at"], name="issue_prop_item_boolean_idx"),
        ]

    def __str__(self):
        return f"{self.value_id} - {self.property_id}"
