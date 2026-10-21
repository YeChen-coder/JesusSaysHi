"""Thin client for the RAGFlow HTTP API (the stack in ragflow/docker)."""

from __future__ import annotations

import json
import os

import requests


class RagflowError(RuntimeError):
    pass


class RagflowClient:
    def __init__(self, url: str | None = None, api_key: str | None = None, timeout: float = 15):
        self.url = (url or os.getenv("JESUS_RAGFLOW_URL", "http://127.0.0.1:19380")).rstrip("/")
        key = api_key or os.getenv("JESUS_RAGFLOW_API_KEY", "")
        if not key:
            raise RagflowError("JESUS_RAGFLOW_API_KEY is empty: create one in RAGFlow (avatar > API) "
                               "and put it in config.local.env")
        self.timeout = timeout
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {key}"

    def _call(self, method: str, path: str, **kwargs) -> dict | list:
        response = self.http.request(method, self.url + path, timeout=kwargs.pop("timeout", self.timeout), **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise RagflowError(f"{method} {path}: HTTP {response.status_code}, not JSON") from None
        if body.get("code") != 0:
            raise RagflowError(f"{method} {path}: {body.get('message') or body}")
        return body.get("data")

    # Datasets and documents

    def find_dataset(self, name: str) -> dict | None:
        for dataset in self._call("GET", "/api/v1/datasets", params={"name": name, "page_size": 100}) or []:
            if dataset["name"] == name:
                return dataset
        return None

    def create_dataset(self, **body) -> dict:
        return self._call("POST", "/api/v1/datasets", json=body)

    def update_dataset(self, dataset_id: str, **body) -> dict:
        return self._call("PUT", f"/api/v1/datasets/{dataset_id}", json=body)

    def documents(self, dataset_id: str) -> list[dict]:
        found, page = [], 1
        while True:
            data = self._call("GET", f"/api/v1/datasets/{dataset_id}/documents",
                              params={"page": page, "page_size": 100})
            batch = data.get("docs", []) if isinstance(data, dict) else data
            found += batch
            if len(batch) < 100:
                return found
            page += 1

    def upload(self, dataset_id: str, files: list[tuple[str, bytes]]) -> list[dict]:
        form = [("file", (name, content, "text/plain")) for name, content in files]
        return self._call("POST", f"/api/v1/datasets/{dataset_id}/documents", files=form, timeout=120)

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self._call("DELETE", f"/api/v1/datasets/{dataset_id}/documents", json={"ids": document_ids})

    def set_metadata(self, dataset_id: str, document_id: str, meta: dict) -> None:
        self._call("PATCH", f"/api/v1/datasets/{dataset_id}/documents/{document_id}", json={"meta_fields": meta})

    def parse(self, dataset_id: str, document_ids: list[str]) -> None:
        # Scheduling is slow per document; callers pass small batches.
        self._call("POST", f"/api/v1/datasets/{dataset_id}/chunks", json={"document_ids": document_ids},
                   timeout=120)

    # Retrieval

    def retrieve(self, question: str, dataset_ids: list[str], **params) -> dict:
        body = {"question": question, "dataset_ids": dataset_ids, **params}
        return self._call("POST", "/api/v1/retrieval", data=json.dumps(body),
                          headers={"Content-Type": "application/json"})
