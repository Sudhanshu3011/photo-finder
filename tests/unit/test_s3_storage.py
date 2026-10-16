"""
tests/unit/test_s3_storage.py — Unit tests for AWS S3 Storage Adapter.
Verifies multi-tenant key prefixes, URL generation, bucket resolution, and graceful fallbacks.
"""
import io
import pytest
from unittest.mock import MagicMock, patch

from src.modules.storage.s3_storage import (
    build_s3_url,
    get_s3_bucket,
    upload_to_s3,
    upload_image_to_s3,
    list_s3_folders,
    list_s3_folder_images,
    delete_s3_resource,
    delete_s3_folder,
    ping_s3,
)
from src.core.tenant_context import set_current_tenant_id, reset_tenant_context


def test_build_s3_url_default_and_regions():
    # US-East-1 default format
    url_east = build_s3_url("tenants/t1/album/pic.jpg", "my-bucket", "us-east-1")
    assert url_east == "https://my-bucket.s3.amazonaws.com/tenants/t1/album/pic.jpg"

    # Non-us-east-1 regional format
    url_eu = build_s3_url("tenants/t1/album/pic.jpg", "my-bucket", "eu-central-1")
    assert url_eu == "https://my-bucket.s3.eu-central-1.amazonaws.com/tenants/t1/album/pic.jpg"

    # CloudFront CDN public prefix
    with patch("src.modules.storage.s3_storage.AWS_S3_PUBLIC_URL_PREFIX", "https://cdn.example.com"):
        url_cdn = build_s3_url("tenants/t1/album/pic.jpg", "my-bucket")
        assert url_cdn == "https://cdn.example.com/tenants/t1/album/pic.jpg"


def test_get_s3_bucket_resolution():
    # Resolves from creds dict
    assert get_s3_bucket({"bucket_name": "custom-tenant-bucket"}) == "custom-tenant-bucket"
    # Falls back to default
    assert get_s3_bucket(None) != ""


def test_upload_image_to_s3_tenant_partitioning():
    set_current_tenant_id("tenant_enterprise_42")
    try:
        mock_file = io.BytesIO(b"fake-image-binary-data")
        res = upload_image_to_s3(
            file_obj=mock_file,
            folder="conferences_2026",
            key="keynote.jpg",
            bucket="prod-saas-media",
        )
        assert res is not None
        assert "secure_url" in res
        assert "url" in res
        assert "key" in res
        # Verify key contains tenant_id and folder
        assert res["key"].startswith("tenant_enterprise_42/conferences_2026/")
        assert "keynote.jpg" in res["key"]
        assert "prod-saas-media" in res["url"]
    finally:
        reset_tenant_context()


def test_upload_to_s3_with_mocked_boto3():
    mock_client = MagicMock()
    with patch("src.modules.storage.s3_storage.get_s3_client", return_value=mock_client):
        res = upload_to_s3(
            file_obj=b"image-bytes-content",
            key="tenant_1/test.jpg",
            bucket="test-bucket",
            content_type="image/jpeg",
        )
        mock_client.upload_fileobj.assert_called_once()
        assert res["public_id"] == "tenant_1/test.jpg"
        assert res["bucket"] == "test-bucket"
        assert "test-bucket" in res["secure_url"] and "/tenant_1/test.jpg" in res["secure_url"]


def test_ping_s3_mocked():
    mock_client = MagicMock()
    with patch("src.modules.storage.s3_storage.get_s3_client", return_value=mock_client):
        assert ping_s3("test-bucket") is True
        mock_client.head_bucket.assert_called_once_with(Bucket="test-bucket")


def test_list_and_delete_s3():
    mock_client = MagicMock()
    mock_paginator = MagicMock()
    mock_paginator.paginate.side_effect = [
        # list folders
        [{"CommonPrefixes": [{"Prefix": "tenant_1/family/"}, {"Prefix": "tenant_1/work/"}]}],
        # delete folder objects
        [{"Contents": [{"Key": "tenant_1/family/img1.jpg"}]}],
    ]
    mock_client.get_paginator.return_value = mock_paginator
    mock_client.list_objects_v2.return_value = {
        "Contents": [{"Key": "tenant_1/family/img1.jpg", "Size": 12345, "LastModified": "2026-10-14T00:00:00Z"}],
        "NextContinuationToken": None,
    }

    with patch("src.modules.storage.s3_storage.get_s3_client", return_value=mock_client):
        folders = list_s3_folders(tenant_id="tenant_1")
        assert "family" in folders
        assert "work" in folders

        images_resp = list_s3_folder_images(folder="family", tenant_id="tenant_1")
        resources = images_resp["resources"]
        assert len(resources) == 1
        assert resources[0]["key"] == "tenant_1/family/img1.jpg"

        delete_res = delete_s3_resource("tenant_1/family/img1.jpg")
        assert delete_res["result"] == "ok"
        mock_client.delete_object.assert_called_once()

        delete_s3_folder("family", tenant_id="tenant_1")
        mock_client.delete_objects.assert_called_once()

