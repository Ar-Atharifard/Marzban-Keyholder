"""Bounded S3 operations. Credentials and object URLs never leave the server."""

from typing import Any

from keyholder.config import Settings


class ObjectStorage:
    def __init__(self, settings: Settings):
        import boto3  # type: ignore[import-untyped]
        from botocore.config import Config  # type: ignore[import-untyped]

        self.bucket = settings.receipt_s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.receipt_s3_endpoint,
            region_name=settings.receipt_s3_region,
            aws_access_key_id=settings.receipt_s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.receipt_s3_secret_key.get_secret_value(),
            config=Config(
                connect_timeout=5,
                read_timeout=20,
                retries={"max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )

    def inventory(self) -> dict[str, Any]:
        versions: list[dict[str, Any]] = []
        size = 0
        for page in self.client.get_paginator("list_object_versions").paginate(Bucket=self.bucket):
            for item in page.get("Versions", []):
                size += item["Size"]
                versions.append(
                    {"key": item["Key"], "version": item["VersionId"], "size": item["Size"]}
                )
            for item in page.get("DeleteMarkers", []):
                versions.append({"key": item["Key"], "version": item["VersionId"], "size": 0})
            if len(versions) > 100_000:
                raise ValueError("Storage inventory exceeds the configured workload")
        uploads = []
        for page in self.client.get_paginator("list_multipart_uploads").paginate(
            Bucket=self.bucket
        ):
            for upload in page.get("Uploads", []):
                parts_size = 0
                for parts in self.client.get_paginator("list_parts").paginate(
                    Bucket=self.bucket, Key=upload["Key"], UploadId=upload["UploadId"]
                ):
                    parts_size += sum(part["Size"] for part in parts.get("Parts", []))
                size += parts_size
                uploads.append(
                    {
                        "key": upload["Key"],
                        "id": upload["UploadId"],
                        "size": parts_size,
                        "started_at": upload["Initiated"],
                    }
                )
                if len(uploads) > 1000:
                    raise ValueError("Too many unfinished uploads")
        return {"size_bytes": size, "versions": versions, "uploads": uploads}

    def put(self, key: str, data: bytes, media_type: str) -> str:
        result = self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
            ServerSideEncryption="AES256",
        )
        version = result.get("VersionId")
        if not version:
            raise ValueError("Versioned object storage is required")
        return str(version)

    def get(self, key: str, version: str, maximum: int) -> bytes:
        result = self.client.get_object(Bucket=self.bucket, Key=key, VersionId=version)
        with result["Body"] as stream:
            data: bytes = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("Receipt exceeds size limit")
        return data

    def delete(self, key: str, version: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key, VersionId=version)

    def abort(self, key: str, upload_id: str) -> None:
        self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
