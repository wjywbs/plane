# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock
from uuid import uuid4

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from plane.db.models import (
    APIToken,
    Estimate,
    EstimatePoint,
    Issue,
    IssueType,
    Label,
    Project,
    ProjectMember,
    State,
    User,
)
from plane.db.models.issue_type import ProjectIssueType
from plane.db.models.state import StateGroup


@pytest.fixture
def project(db, workspace, create_user):
    project = Project.objects.create(
        name="Test Project",
        identifier="TP",
        workspace=workspace,
        created_by=create_user,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=True)
    State.objects.create(
        name="Backlog",
        color="#60646C",
        group=StateGroup.BACKLOG.value,
        default=True,
        project=project,
        workspace=workspace,
    )
    State.objects.create(
        name="Todo",
        color="#60646C",
        group=StateGroup.UNSTARTED.value,
        project=project,
        workspace=workspace,
    )
    return project


@pytest.fixture
def member_user(db, workspace, project):
    unique_id = uuid4().hex[:8]
    user = User.objects.create(
        email=f"member-{unique_id}@plane.so",
        username=f"member_{unique_id}",
        first_name="Project",
        last_name="Member",
    )
    ProjectMember.objects.create(project=project, member=user, role=15, is_active=True)
    return user


@pytest.fixture
def member_api_key_client(db, member_user):
    token = APIToken.objects.create(user=member_user, label="Member Token", token=f"member-token-{uuid4().hex}")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=token.token)
    return client


@pytest.fixture
def bootstrapped_types(api_key_client, workspace, project):
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-item-types/"
    response = api_key_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    return {
        project_issue_type.issue_type.name: project_issue_type.issue_type
        for project_issue_type in ProjectIssueType.objects.filter(project=project).select_related("issue_type")
    }


@pytest.mark.contract
class TestIssueTypeListCreateAPIEndpoint:
    def get_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-item-types/"

    @pytest.mark.django_db
    def test_list_bootstraps_task_and_epic(self, api_key_client, workspace, project):
        url = self.get_url(workspace.slug, project.id)

        response = api_key_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        project.refresh_from_db()
        assert project.is_issue_type_enabled is True
        names = {item["name"] for item in response.data["results"]}
        assert names == {"Task", "Epic"}
        assert ProjectIssueType.objects.filter(project=project, issue_type__name="Task", is_default=True).exists()
        assert ProjectIssueType.objects.filter(project=project, issue_type__name="Epic", is_default=False).exists()

    @pytest.mark.django_db
    def test_list_bootstrap_is_idempotent(self, api_key_client, workspace, project):
        url = self.get_url(workspace.slug, project.id)

        first_response = api_key_client.get(url)
        second_response = api_key_client.get(url)

        assert first_response.status_code == status.HTTP_200_OK
        assert second_response.status_code == status.HTTP_200_OK
        assert IssueType.objects.filter(workspace=workspace).count() == 2
        assert ProjectIssueType.objects.filter(project=project).count() == 2

    @pytest.mark.django_db
    def test_project_member_can_read_but_not_create(self, member_api_key_client, workspace, project):
        url = self.get_url(workspace.slug, project.id)

        read_response = member_api_key_client.get(url)
        write_response = member_api_key_client.post(url, {"name": "Bug"}, format="json")

        assert read_response.status_code == status.HTTP_200_OK
        assert write_response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.django_db
    def test_create_work_item_type_success(self, api_key_client, workspace, project):
        url = self.get_url(workspace.slug, project.id)

        response = api_key_client.post(
            url,
            {
                "name": "Bug",
                "description": "Software defect",
                "logo_props": {"icon": "bug", "color": "#ff0000"},
                "external_id": "bug-ext",
                "external_source": "github",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        issue_type = IssueType.objects.get(name="Bug", workspace=workspace)
        assert issue_type.description == "Software defect"
        assert issue_type.logo_props == {"icon": "bug", "color": "#ff0000"}
        assert ProjectIssueType.objects.filter(project=project, issue_type=issue_type, is_default=False).exists()

    @pytest.mark.django_db
    def test_create_duplicate_name_returns_409(self, api_key_client, workspace, project, bootstrapped_types):
        url = self.get_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "Task"}, format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "same name" in response.data["error"]

    @pytest.mark.django_db
    def test_create_duplicate_external_id_returns_409(self, api_key_client, workspace, project):
        url = self.get_url(workspace.slug, project.id)
        payload = {"name": "Bug", "external_id": "ext-1", "external_source": "github"}
        first_response = api_key_client.post(url, payload, format="json")

        second_response = api_key_client.post(
            url,
            {"name": "Story", "external_id": "ext-1", "external_source": "github"},
            format="json",
        )

        assert first_response.status_code == status.HTTP_201_CREATED
        assert second_response.status_code == status.HTTP_409_CONFLICT
        assert "same external id" in second_response.data["error"]


@pytest.mark.contract
class TestIssueTypeDetailAPIEndpoint:
    def get_url(self, workspace_slug, project_id, type_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-item-types/{type_id}/"

    @pytest.mark.django_db
    def test_retrieve_update_and_delete_type(self, api_key_client, workspace, project):
        list_url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/work-item-types/"
        create_response = api_key_client.post(list_url, {"name": "Bug", "description": "Old"}, format="json")
        assert create_response.status_code == status.HTTP_201_CREATED
        type_id = create_response.data["id"]
        detail_url = self.get_url(workspace.slug, project.id, type_id)

        retrieve_response = api_key_client.get(detail_url)
        update_response = api_key_client.patch(detail_url, {"description": "New", "is_active": False}, format="json")
        delete_response = api_key_client.delete(detail_url)

        assert retrieve_response.status_code == status.HTTP_200_OK
        assert retrieve_response.data["name"] == "Bug"
        assert update_response.status_code == status.HTTP_200_OK
        assert update_response.data["description"] == "New"
        assert update_response.data["is_active"] is False
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert not ProjectIssueType.objects.filter(project=project, issue_type_id=type_id).exists()

    @pytest.mark.django_db
    def test_default_type_cannot_be_disabled_or_deleted(self, api_key_client, workspace, project, bootstrapped_types):
        task = bootstrapped_types["Task"]
        detail_url = self.get_url(workspace.slug, project.id, task.id)

        disable_response = api_key_client.patch(detail_url, {"is_active": False}, format="json")
        delete_response = api_key_client.delete(detail_url)

        assert disable_response.status_code == status.HTTP_400_BAD_REQUEST
        assert delete_response.status_code == status.HTTP_400_BAD_REQUEST
        task.refresh_from_db()
        assert task.is_active is True
        assert ProjectIssueType.objects.filter(project=project, issue_type=task, is_default=True).exists()


@pytest.mark.contract
class TestIssueTypeSchemaAPIEndpoint:
    def get_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-item-types/schema/"

    @pytest.mark.django_db
    def test_schema_returns_standard_fields(self, api_key_client, workspace, project, bootstrapped_types):
        url = self.get_url(workspace.slug, project.id)

        response = api_key_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["type_name"] == "Task"
        assert response.data["custom_fields"] == {}
        fields = response.data["fields"]
        assert fields["name"]["required"] is True
        assert {option["value"] for option in fields["priority"]["options"]} == {
            "urgent",
            "high",
            "medium",
            "low",
            "none",
        }
        assert len(fields["state_id"]["options"]) == 2

    @pytest.mark.django_db
    def test_schema_include_members_labels_and_estimates(
        self, api_key_client, workspace, project, create_user, member_user, bootstrapped_types
    ):
        Label.objects.create(name="Backend", color="#000000", project=project, workspace=workspace)
        estimate = Estimate.objects.create(name="Effort", project=project, workspace=workspace)
        project.estimate = estimate
        project.save(update_fields=["estimate"])
        EstimatePoint.objects.create(estimate=estimate, key=1, value="1", project=project, workspace=workspace)
        url = (
            f"{self.get_url(workspace.slug, project.id)}"
            f"?include=members,labels&type_id={bootstrapped_types['Epic'].id}"
        )

        response = api_key_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["type_name"] == "Epic"
        fields = response.data["fields"]
        assert len(fields["assignee_ids"]["options"]) == 2
        assert fields["label_ids"]["options"][0]["name"] == "Backend"
        assert fields["estimate_point_id"]["options"][0]["value"] == "1"

    @pytest.mark.django_db
    def test_schema_rejects_cross_project_type_id(
        self, api_key_client, workspace, project, create_user, bootstrapped_types
    ):
        other_project = Project.objects.create(
            name="Other", identifier="OP", workspace=workspace, created_by=create_user
        )
        ProjectMember.objects.create(project=other_project, member=create_user, role=20, is_active=True)
        other_type = IssueType.objects.create(name="Other Type", workspace=workspace)
        ProjectIssueType.objects.create(project=other_project, issue_type=other_type)
        url = f"{self.get_url(workspace.slug, project.id)}?type_id={other_type.id}"

        response = api_key_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.contract
class TestWorkItemTypeIntegration:
    def get_work_item_url(self, workspace_slug, project_id):
        return f"/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-items/"

    @pytest.mark.django_db
    def test_work_item_uses_default_type(self, api_key_client, workspace, project, bootstrapped_types):
        url = self.get_work_item_url(workspace.slug, project.id)

        with (
            mock.patch("plane.api.views.issue.issue_activity.delay"),
            mock.patch("plane.api.views.issue.model_activity.delay"),
        ):
            response = api_key_client.post(url, {"name": "Default typed item"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        issue = Issue.objects.get(id=response.data["id"])
        assert issue.type_id == bootstrapped_types["Task"].id

    @pytest.mark.django_db
    def test_work_item_accepts_valid_explicit_type(self, api_key_client, workspace, project, bootstrapped_types):
        url = self.get_work_item_url(workspace.slug, project.id)

        with (
            mock.patch("plane.api.views.issue.issue_activity.delay"),
            mock.patch("plane.api.views.issue.model_activity.delay"),
        ):
            response = api_key_client.post(
                url,
                {"name": "Epic item", "type_id": str(bootstrapped_types["Epic"].id)},
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED
        issue = Issue.objects.get(id=response.data["id"])
        assert issue.type_id == bootstrapped_types["Epic"].id

    @pytest.mark.django_db
    def test_work_item_rejects_inactive_type(self, api_key_client, workspace, project, bootstrapped_types):
        bug = IssueType.objects.create(name="Bug", workspace=workspace, is_active=False)
        ProjectIssueType.objects.create(project=project, issue_type=bug)
        url = self.get_work_item_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "Bug item", "type_id": str(bug.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "type_id" in response.data

    @pytest.mark.django_db
    def test_work_item_rejects_cross_project_type(
        self, api_key_client, workspace, project, create_user, bootstrapped_types
    ):
        other_project = Project.objects.create(
            name="Other", identifier="OP", workspace=workspace, created_by=create_user
        )
        ProjectMember.objects.create(project=other_project, member=create_user, role=20, is_active=True)
        other_type = IssueType.objects.create(name="Other Type", workspace=workspace)
        ProjectIssueType.objects.create(project=other_project, issue_type=other_type)
        url = self.get_work_item_url(workspace.slug, project.id)

        response = api_key_client.post(url, {"name": "Cross type item", "type_id": str(other_type.id)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "type_id" in response.data
