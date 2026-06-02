# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch

# Third party imports
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

# Module imports
from plane.app.permissions import ProjectAdminPermission, ProjectLitePermission
from plane.api.serializers import IssueTypeCreateUpdateSerializer, IssueTypeSerializer
from plane.db.models import EstimatePoint, Issue, IssueType, Label, Project, ProjectMember, State
from plane.db.models.issue_type import ProjectIssueType
from .base import BaseAPIView


DEFAULT_ISSUE_TYPES = [
    {
        "name": "Task",
        "description": "Default work item type",
        "logo_props": {},
        "is_epic": False,
        "is_default": True,
        "is_active": True,
        "level": 0,
    },
    {
        "name": "Epic",
        "description": "Epic work item type",
        "logo_props": {},
        "is_epic": True,
        "is_default": False,
        "is_active": True,
        "level": 1,
    },
]


class IssueTypeMixin:
    permission_classes = [ProjectLitePermission]

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [ProjectLitePermission()]
        return [ProjectAdminPermission()]

    def get_project(self):
        return Project.objects.select_related("workspace").get(id=self.project_id, workspace__slug=self.workspace_slug)

    def bootstrap_project_issue_types(self, project):
        with transaction.atomic():
            project = Project.objects.select_for_update().select_related("workspace").get(id=project.id)

            linked_issue_types = ProjectIssueType.objects.filter(project=project)
            linked_default_names = set(linked_issue_types.values_list("issue_type__name", flat=True))
            has_project_default = linked_issue_types.filter(is_default=True).exists()
            if (
                project.is_issue_type_enabled
                and {"Task", "Epic"}.issubset(linked_default_names)
                and has_project_default
            ):
                return

            for default_type in DEFAULT_ISSUE_TYPES:
                issue_type, _ = IssueType.objects.get_or_create(
                    workspace=project.workspace,
                    name=default_type["name"],
                    defaults={
                        "description": default_type["description"],
                        "logo_props": default_type["logo_props"],
                        "is_epic": default_type["is_epic"],
                        "is_default": default_type["is_default"],
                        "is_active": default_type["is_active"],
                        "level": default_type["level"],
                    },
                )
                ProjectIssueType.objects.get_or_create(
                    project=project,
                    issue_type=issue_type,
                    defaults={
                        "level": default_type["level"],
                        "is_default": default_type["is_default"],
                    },
                )

            ProjectIssueType.objects.filter(project=project).exclude(issue_type__name="Task").update(is_default=False)
            ProjectIssueType.objects.filter(project=project, issue_type__name="Task").update(is_default=True)

            if not project.is_issue_type_enabled:
                project.is_issue_type_enabled = True
                project.save(update_fields=["is_issue_type_enabled", "updated_at"])

    def get_queryset(self):
        project = self.get_project()
        self.bootstrap_project_issue_types(project)
        project_issue_types = ProjectIssueType.objects.filter(project=project).only(
            "id", "project_id", "issue_type_id", "is_default", "level"
        )
        return (
            IssueType.objects.filter(workspace=project.workspace, project_issue_types__project=project)
            .prefetch_related(Prefetch("project_issue_types", queryset=project_issue_types))
            .distinct()
            .order_by("project_issue_types__level", "name")
        )

    def serialize_issue_type(self, issue_type):
        project_issue_type = next(iter(issue_type.project_issue_types.all()), None)
        issue_type.project_issue_type = project_issue_type
        return IssueTypeSerializer(issue_type, fields=self.fields, expand=self.expand).data

    def next_level(self, project):
        max_level = ProjectIssueType.objects.filter(project=project).aggregate(max_level=Max("level"))["max_level"]
        return 0 if max_level is None else max_level + 1

    def has_external_conflict(self, project, external_id, external_source, exclude_id=None):
        if not external_id or not external_source:
            return None

        queryset = IssueType.objects.filter(
            workspace=project.workspace,
            external_id=external_id,
            external_source=external_source,
            project_issue_types__project=project,
        )
        if exclude_id:
            queryset = queryset.exclude(id=exclude_id)
        return queryset.first()

    def get_project_issue_type(self, project, type_id):
        return ProjectIssueType.objects.select_related("issue_type").get(
            project=project,
            issue_type_id=type_id,
        )


class IssueTypeListCreateAPIEndpoint(IssueTypeMixin, BaseAPIView):
    serializer_class = IssueTypeSerializer
    model = IssueType
    use_read_replica = True

    def get(self, request, slug, project_id):
        return self.paginate(
            request=request,
            queryset=self.get_queryset(),
            on_results=lambda issue_types: [self.serialize_issue_type(issue_type) for issue_type in issue_types],
        )

    def post(self, request, slug, project_id):
        project = self.get_project()
        self.bootstrap_project_issue_types(project)

        conflict = self.has_external_conflict(
            project=project,
            external_id=request.data.get("external_id"),
            external_source=request.data.get("external_source"),
        )
        if conflict:
            return Response(
                {
                    "error": "Work item type with the same external id and external source already exists",
                    "id": str(conflict.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = IssueTypeCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        existing = IssueType.objects.filter(
            workspace=project.workspace,
            name=serializer.validated_data["name"],
        ).first()
        if existing:
            return Response(
                {
                    "error": "Work item type with the same name already exists in the workspace",
                    "id": str(existing.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        level = serializer.validated_data.get("level", self.next_level(project))

        try:
            with transaction.atomic():
                issue_type = serializer.save(workspace=project.workspace)
                project_issue_type = ProjectIssueType.objects.create(
                    project=project,
                    issue_type=issue_type,
                    level=level,
                    is_default=False,
                )
        except IntegrityError:
            existing = IssueType.objects.filter(workspace=project.workspace, name=request.data.get("name")).first()
            return Response(
                {
                    "error": "Work item type with the same name already exists in the workspace",
                    "id": str(existing.id) if existing else None,
                },
                status=status.HTTP_409_CONFLICT,
            )

        issue_type.project_issue_type = project_issue_type
        return Response(IssueTypeSerializer(issue_type).data, status=status.HTTP_201_CREATED)


class IssueTypeDetailAPIEndpoint(IssueTypeMixin, BaseAPIView):
    serializer_class = IssueTypeSerializer
    model = IssueType
    use_read_replica = True

    def get(self, request, slug, project_id, type_id):
        project = self.get_project()
        self.bootstrap_project_issue_types(project)
        project_issue_type = self.get_project_issue_type(project, type_id)
        issue_type = project_issue_type.issue_type
        issue_type.project_issue_type = project_issue_type
        return Response(IssueTypeSerializer(issue_type, fields=self.fields, expand=self.expand).data)

    def patch(self, request, slug, project_id, type_id):
        project = self.get_project()
        self.bootstrap_project_issue_types(project)
        project_issue_type = self.get_project_issue_type(project, type_id)
        issue_type = project_issue_type.issue_type

        if request.data.get("is_active") is False and project_issue_type.is_default:
            return Response(
                {"error": "The default work item type cannot be disabled"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conflict = self.has_external_conflict(
            project=project,
            external_id=request.data.get("external_id"),
            external_source=request.data.get("external_source"),
            exclude_id=type_id,
        )
        if conflict:
            return Response(
                {
                    "error": "Work item type with the same external id and external source already exists",
                    "id": str(conflict.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = IssueTypeCreateUpdateSerializer(issue_type, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if "name" in serializer.validated_data:
            existing = (
                IssueType.objects.filter(workspace=project.workspace, name=serializer.validated_data["name"])
                .exclude(id=type_id)
                .first()
            )
            if existing:
                return Response(
                    {
                        "error": "Work item type with the same name already exists in the workspace",
                        "id": str(existing.id),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        try:
            issue_type = serializer.save()
            if "level" in serializer.validated_data:
                project_issue_type.level = serializer.validated_data["level"]
                project_issue_type.save(update_fields=["level", "updated_at"])
        except IntegrityError:
            existing = (
                IssueType.objects.filter(workspace=project.workspace, name=request.data.get("name"))
                .exclude(id=type_id)
                .first()
            )
            return Response(
                {
                    "error": "Work item type with the same name already exists in the workspace",
                    "id": str(existing.id) if existing else None,
                },
                status=status.HTTP_409_CONFLICT,
            )

        issue_type.project_issue_type = project_issue_type
        return Response(IssueTypeSerializer(issue_type).data, status=status.HTTP_200_OK)

    def delete(self, request, slug, project_id, type_id):
        project = self.get_project()
        self.bootstrap_project_issue_types(project)
        project_issue_type = self.get_project_issue_type(project, type_id)

        if project_issue_type.is_default:
            return Response(
                {"error": "The default work item type cannot be deleted"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issue_type = project_issue_type.issue_type
        project_issue_type.delete()

        if (
            not ProjectIssueType.objects.filter(issue_type=issue_type).exists()
            and not Issue.objects.filter(type=issue_type).exists()
        ):
            issue_type.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class IssueTypeSchemaAPIEndpoint(IssueTypeMixin, BaseAPIView):
    serializer_class = IssueTypeSerializer
    model = IssueType
    use_read_replica = True

    def get(self, request, slug, project_id):
        project = self.get_project()
        self.bootstrap_project_issue_types(project)
        issue_type = self.get_schema_issue_type(project, request.GET.get("type_id"))
        include = {item.strip() for item in request.GET.get("include", "").split(",") if item.strip()}

        response = {
            "type_id": str(issue_type.id) if issue_type else None,
            "type_name": issue_type.name if issue_type else None,
            "type_description": issue_type.description if issue_type else "",
            "type_logo_props": issue_type.logo_props if issue_type else {},
            "fields": self.get_standard_fields(project, include),
            "custom_fields": {},
        }
        return Response(response, status=status.HTTP_200_OK)

    def get_schema_issue_type(self, project, type_id):
        if type_id:
            project_issue_type = self.get_project_issue_type(project, type_id)
            return project_issue_type.issue_type

        project_issue_type = (
            ProjectIssueType.objects.select_related("issue_type")
            .filter(project=project, is_default=True)
            .first()
        )
        return project_issue_type.issue_type if project_issue_type else None

    def get_standard_fields(self, project, include):
        fields = {
            "name": {"type": "string", "required": True, "max_length": 255},
            "description_html": {"type": "html", "required": False},
            "priority": {
                "type": "option",
                "required": False,
                "options": [{"value": value, "label": label} for value, label in Issue.PRIORITY_CHOICES],
            },
            "state_id": {
                "type": "uuid",
                "required": False,
                "options": [
                    {
                        "id": str(state.id),
                        "name": state.name,
                        "color": state.color,
                        "group": state.group,
                    }
                    for state in State.objects.filter(project=project).order_by("sequence", "name")
                ],
            },
            "assignee_ids": {"type": "uuid[]", "required": False},
            "label_ids": {"type": "uuid[]", "required": False},
            "start_date": {"type": "date", "required": False},
            "target_date": {"type": "date", "required": False},
            "parent_id": {"type": "uuid", "required": False},
        }

        if "members" in include:
            fields["assignee_ids"]["options"] = [
                {
                    "id": str(project_member.member_id),
                    "email": project_member.member.email,
                    "first_name": project_member.member.first_name,
                    "last_name": project_member.member.last_name,
                }
                for project_member in ProjectMember.objects.filter(project=project, is_active=True)
                .select_related("member")
                .order_by("member__first_name", "member__email")
            ]

        if "labels" in include:
            fields["label_ids"]["options"] = [
                {
                    "id": str(label.id),
                    "name": label.name,
                    "color": label.color,
                }
                for label in Label.objects.filter(project=project).order_by("name")
            ]

        if project.estimate_id:
            fields["estimate_point_id"] = {
                "type": "uuid",
                "required": False,
                "options": [
                    {
                        "id": str(estimate_point.id),
                        "key": estimate_point.key,
                        "value": estimate_point.value,
                    }
                    for estimate_point in EstimatePoint.objects.filter(
                        project=project,
                        estimate_id=project.estimate_id,
                    ).order_by("key", "value")
                ],
            }

        return fields
