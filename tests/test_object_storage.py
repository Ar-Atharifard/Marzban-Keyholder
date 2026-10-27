import datetime as dt
import io
from typing import Any

from botocore.response import StreamingBody  # type: ignore[import-untyped]
from botocore.stub import Stubber  # type: ignore[import-untyped]
from pydantic import SecretStr

from keyholder.config import Settings
from keyholder.object_storage import ObjectStorage
from tests.support import ADMIN_KEY


def test_s3_version_accounting_and_encrypted_upload_contract() -> None:
    settings = Settings(
        admin_key=SecretStr(ADMIN_KEY),
        storage_enabled=True,
        receipt_s3_endpoint="https://s3.example.invalid",
        receipt_s3_region="example",
        receipt_s3_bucket="synthetic-receipts",
        receipt_s3_access_key=SecretStr("synthetic-id"),
        receipt_s3_secret_key=SecretStr("synthetic-secret"),
    )
    store = ObjectStorage(settings)
    moment = dt.datetime(2026, 10, 23, tzinfo=dt.UTC)
    with Stubber(store.client) as stub:
        stub.add_response(
            "list_object_versions",
            {
                "IsTruncated": False,
                "Versions": [
                    {
                        "Key": "receipts/opaque",
                        "VersionId": "v1",
                        "Size": 3,
                        "LastModified": moment,
                    },
                    {
                        "Key": "receipts/opaque",
                        "VersionId": "v0",
                        "Size": 2,
                        "LastModified": moment,
                    },
                ],
                "DeleteMarkers": [
                    {"Key": "receipts/old", "VersionId": "marker", "LastModified": moment}
                ],
            },
            {"Bucket": store.bucket},
        )
        stub.add_response(
            "list_multipart_uploads",
            {"IsTruncated": False, "Uploads": []},
            {"Bucket": store.bucket},
        )
        assert store.inventory()["size_bytes"] == 5
        stub.add_response(
            "put_object",
            {"VersionId": "v2"},
            {
                "Bucket": store.bucket,
                "Key": "receipts/opaque",
                "Body": b"abc",
                "ContentType": "image/png",
                "ServerSideEncryption": "AES256",
            },
        )
        assert store.put("receipts/opaque", b"abc", "image/png") == "v2"
        response: dict[str, Any] = {"Body": StreamingBody(io.BytesIO(b"abc"), 3)}
        stub.add_response(
            "get_object",
            response,
            {"Bucket": store.bucket, "Key": "receipts/opaque", "VersionId": "v2"},
        )
        assert store.get("receipts/opaque", "v2", 5) == b"abc"
        stub.add_response(
            "delete_object",
            {},
            {"Bucket": store.bucket, "Key": "receipts/opaque", "VersionId": "v0"},
        )
        store.delete("receipts/opaque", "v0")
        stub.assert_no_pending_responses()
