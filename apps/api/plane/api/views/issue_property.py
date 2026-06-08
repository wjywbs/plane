# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Max

# Third party imports
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ProjectAdminPermission, ProjectEntityPermission, ProjectLitePermission
from plane.api.serializers import (
    IssuePropertyOptionSerializer,
    IssuePropertySerializer,
    IssuePropertyValueSerializer,
)
from plane.api.serializers.issue_property import upsert_issue_property_value
from plane.db.models import Issue, IssueProperty, IssuePropertyOption, IssuePropertyValue, Project
from .base import BaseAPIView
from .issue_type import IssueTypeMixin


class IssuePropertyMixin(IssueTypeMixin):
    permission_classes = [ProjectLitePermission]

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [ProjectLitePermission()]
        return [ProjectAdminPermission()]

    def get_project(self):
        return Project.objects.select_related("workspace").get(id=self.project_id, workspace__slug=self.workspace_slug)

    def get_issue_type(self, project, type_id):
        self.bootstrap_project_issue_types(project)
        return self.get_project_issue_type(project, type_id).issue_type

    def get_issue_property(self, project, property_id, type_id=None):
        queryset = IssueProperty.objects.filter(project=project, id=property_id)
        if type_id:
            queryset = queryset.filter(issue_type_id=type_id)
        return queryset.get()

    def next_property_sort_order(self, project, issue_type):
        max_sort_order = IssueProperty.objects.filter(project=project, issue_type=issue_type).aggregate(
            max_sort_order=Max("sort_order")
        )["max_sort_order"]
        return 10000 if max_sort_order is None else max_sort_order + 10000

    def has_property_external_conflict(self, project, issue_type, external_id, external_source, exclude_id=None):
        if not external_id or not external_source:
            return None
        queryset = IssueProperty.objects.filter(
            project=project,
            issue_type=issue_type,
            external_id=external_id,
            external_source=external_source,
        )
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.first()


class IssuePropertyListCreateAPIEndpoint(IssuePropertyMixin, BaseAPIView):
    serializer_class = IssuePropertySerializer
    model = IssueProperty
    use_read_replica = True

    def get(self, request, slug, project_id, type_id):
        project = self.get_project()
        issue_type = self.get_issue_type(project, type_id)
        queryset = IssueProperty.objects.filter(project=project, issue_type=issue_type).order_by(
            "sort_order", "display_name"
        )
        return self.paginate(
            request=request,
            queryset=queryset,
            on_results=lambda properties: IssuePropertySerializer(properties, many=True).data,
        )

    def post(self, request, slug, project_id, type_id):
        project = self.get_project()
        issue_type = self.get_issue_type(project, type_id)

        conflict = self.has_property_external_conflict(
            project=project,
            issue_type=issue_type,
            external_id=request.data.get("external_id"),
            external_source=request.data.get("external_source"),
        )
        if conflict:
            return Response(
                {
                    "error": "Work item property with the same external id and external source already exists",
                    "id": str(conflict.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = IssuePropertySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if IssueProperty.objects.filter(
            project=project,
            issue_type=issue_type,
            display_name=serializer.validated_data["display_name"],
        ).exists():
            return Response(
                {"error": "Work item property with the same display name already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            with transaction.atomic():
                issue_property = serializer.save(
                    project=project,
                    issue_type=issue_type,
                    sort_order=serializer.validated_data.get(
                        "sort_order",
                        self.next_property_sort_order(project, issue_type),
                    ),
                )
        except IntegrityError:
            return Response(
                {"error": "Work item property with the same name already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(IssuePropertySerializer(issue_property).data, status=status.HTTP_201_CREATED)


class IssuePropertyDetailAPIEndpoint(IssuePropertyMixin, BaseAPIView):
    serializer_class = IssuePropertySerializer
    model = IssueProperty
    use_read_replica = True

    def get(self, request, slug, project_id, type_id, property_id):
        project = self.get_project()
        self.get_issue_type(project, type_id)
        issue_property = self.get_issue_property(project, property_id, type_id)
        return Response(IssuePropertySerializer(issue_property).data, status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, type_id, property_id):
        project = self.get_project()
        issue_type = self.get_issue_type(project, type_id)
        issue_property = self.get_issue_property(project, property_id, type_id)

        conflict = self.has_property_external_conflict(
            project=project,
            issue_type=issue_type,
            external_id=request.data.get("external_id"),
            external_source=request.data.get("external_source"),
            exclude_id=property_id,
        )
        if conflict:
            return Response(
                {
                    "error": "Work item property with the same external id and external source already exists",
                    "id": str(conflict.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = IssuePropertySerializer(issue_property, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if "display_name" in serializer.validated_data and IssueProperty.objects.filter(
            project=project,
            issue_type=issue_type,
            display_name=serializer.validated_data["display_name"],
        ).exclude(id=property_id).exists():
            return Response(
                {"error": "Work item property with the same display name already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            issue_property = serializer.save()
        except IntegrityError:
            return Response(
                {"error": "Work item property with the same name already exists"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(IssuePropertySerializer(issue_property).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, type_id, property_id):
        project = self.get_project()
        self.get_issue_type(project, type_id)
        issue_property = self.get_issue_property(project, property_id, type_id)
        issue_property.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssuePropertyOptionMixin(BaseAPIView):
    serializer_class = IssuePropertyOptionSerializer
    model = IssuePropertyOption
    permission_classes = [ProjectLitePermission]
    use_read_replica = True

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [ProjectLitePermission()]
        return [ProjectAdminPermission()]

    def get_project(self):
        return Project.objects.select_related("workspace").get(id=self.project_id, workspace__slug=self.workspace_slug)

    def get_issue_property(self, project, property_id):
        issue_property = IssueProperty.objects.get(project=project, id=property_id)
        if issue_property.property_type != IssueProperty.PropertyType.OPTION:
            raise IssueProperty.DoesNotExist
        return issue_property

    def get_option(self, project, issue_property, option_id):
        return IssuePropertyOption.objects.get(project=project, property=issue_property, id=option_id)

    def next_option_sort_order(self, issue_property):
        max_sort_order = IssuePropertyOption.objects.filter(property=issue_property).aggregate(
            max_sort_order=Max("sort_order")
        )["max_sort_order"]
        return 10000 if max_sort_order is None else max_sort_order + 10000

    def has_option_external_conflict(self, issue_property, external_id, external_source, exclude_id=None):
        if not external_id or not external_source:
            return None
        queryset = IssuePropertyOption.objects.filter(
            property=issue_property,
            external_id=external_id,
            external_source=external_source,
        )
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.first()


class IssuePropertyOptionListCreateAPIEndpoint(IssuePropertyOptionMixin):
    def get(self, request, slug, project_id, property_id):
        project = self.get_project()
        issue_property = self.get_issue_property(project, property_id)
        return self.paginate(
            request=request,
            queryset=IssuePropertyOption.objects.filter(property=issue_property).order_by("sort_order", "name"),
            on_results=lambda options: IssuePropertyOptionSerializer(options, many=True).data,
        )

    def post(self, request, slug, project_id, property_id):
        project = self.get_project()
        issue_property = self.get_issue_property(project, property_id)

        conflict = self.has_option_external_conflict(
            issue_property=issue_property,
            external_id=request.data.get("external_id"),
            external_source=request.data.get("external_source"),
        )
        if conflict:
            return Response(
                {
                    "error": "Work item property option with the same external id and external source already exists",
                    "id": str(conflict.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = IssuePropertyOptionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if (
            serializer.validated_data.get("parent")
            and serializer.validated_data["parent"].property_id != issue_property.id
        ):
            return Response({"error": "Parent option is not valid"}, status=status.HTTP_400_BAD_REQUEST)
        if IssuePropertyOption.objects.filter(
            property=issue_property,
            name=serializer.validated_data["name"],
        ).exists():
            return Response(
                {"error": "Work item property option with the same name already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            option = serializer.save(
                project=project,
                property=issue_property,
                sort_order=serializer.validated_data.get("sort_order", self.next_option_sort_order(issue_property)),
            )
        except IntegrityError:
            return Response(
                {"error": "Work item property option with the same name already exists"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(IssuePropertyOptionSerializer(option).data, status=status.HTTP_201_CREATED)


class IssuePropertyOptionDetailAPIEndpoint(IssuePropertyOptionMixin):
    def get(self, request, slug, project_id, property_id, option_id):
        project = self.get_project()
        issue_property = self.get_issue_property(project, property_id)
        option = self.get_option(project, issue_property, option_id)
        return Response(IssuePropertyOptionSerializer(option).data, status=status.HTTP_200_OK)

    def patch(self, request, slug, project_id, property_id, option_id):
        project = self.get_project()
        issue_property = self.get_issue_property(project, property_id)
        option = self.get_option(project, issue_property, option_id)

        conflict = self.has_option_external_conflict(
            issue_property=issue_property,
            external_id=request.data.get("external_id"),
            external_source=request.data.get("external_source"),
            exclude_id=option_id,
        )
        if conflict:
            return Response(
                {
                    "error": "Work item property option with the same external id and external source already exists",
                    "id": str(conflict.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = IssuePropertyOptionSerializer(option, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        if (
            serializer.validated_data.get("parent")
            and serializer.validated_data["parent"].property_id != issue_property.id
        ):
            return Response({"error": "Parent option is not valid"}, status=status.HTTP_400_BAD_REQUEST)
        if "name" in serializer.validated_data and IssuePropertyOption.objects.filter(
            property=issue_property,
            name=serializer.validated_data["name"],
        ).exclude(id=option_id).exists():
            return Response(
                {"error": "Work item property option with the same name already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            option = serializer.save()
        except IntegrityError:
            return Response(
                {"error": "Work item property option with the same name already exists"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(IssuePropertyOptionSerializer(option).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, property_id, option_id):
        project = self.get_project()
        issue_property = self.get_issue_property(project, property_id)
        option = self.get_option(project, issue_property, option_id)
        option.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class IssuePropertyValueAPIEndpoint(BaseAPIView):
    serializer_class = IssuePropertyValueSerializer
    model = IssuePropertyValue
    permission_classes = [ProjectEntityPermission]
    use_read_replica = True

    def get_project(self):
        return Project.objects.select_related("workspace").get(id=self.project_id, workspace__slug=self.workspace_slug)

    def get_issue(self, project, work_item_id):
        return Issue.issue_objects.select_related("type").get(project=project, id=work_item_id)

    def get_issue_property(self, issue, property_id):
        return IssueProperty.objects.get(
            project_id=issue.project_id,
            issue_type_id=issue.type_id,
            id=property_id,
            is_active=True,
        )

    def get_value(self, issue, issue_property):
        return IssuePropertyValue.objects.get(issue=issue, property=issue_property)

    def get(self, request, slug, project_id, work_item_id, property_id):
        project = self.get_project()
        issue = self.get_issue(project, work_item_id)
        issue_property = self.get_issue_property(issue, property_id)
        value = self.get_value(issue, issue_property)
        return Response(IssuePropertyValueSerializer(value).data, status=status.HTTP_200_OK)

    def post(self, request, slug, project_id, work_item_id, property_id):
        return self.upsert(request, project_id, work_item_id, property_id)

    def patch(self, request, slug, project_id, work_item_id, property_id):
        return self.upsert(request, project_id, work_item_id, property_id)

    def upsert(self, request, project_id, work_item_id, property_id):
        project = self.get_project()
        issue = self.get_issue(project, work_item_id)
        issue_property = self.get_issue_property(issue, property_id)
        if "value" not in request.data:
            return Response({"value": "This field is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            value = upsert_issue_property_value(
                issue=issue,
                issue_property=issue_property,
                raw_value=request.data["value"],
                external_id=request.data.get("external_id"),
                external_source=request.data.get("external_source"),
            )
        except Exception as error:
            return Response(
                {"value": error.detail if hasattr(error, "detail") else str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(IssuePropertyValueSerializer(value).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, work_item_id, property_id):
        project = self.get_project()
        issue = self.get_issue(project, work_item_id)
        issue_property = self.get_issue_property(issue, property_id)
        value = self.get_value(issue, issue_property)
        value.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
