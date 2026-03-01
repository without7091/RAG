from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.common import TaskStatus, TaskStatusResponse
from app.schemas.document import DocumentStatus, DocUploadResponse, VectorizeDocInfo, VectorizeResponse, DocRetryResponse
from app.schemas.kb import KBCreateRequest, KBCreateResponse, KBInfo, KBListResponse
from app.schemas.retrieve import RetrieveRequest, RetrieveResponse, SourceNode


class TestKBSchemas:
    def test_kb_create_request_valid(self):
        req = KBCreateRequest(knowledge_base_name="test_kb", description="A test KB")
        assert req.knowledge_base_name == "test_kb"

    def test_kb_create_request_empty_name_fails(self):
        with pytest.raises(ValidationError):
            KBCreateRequest(knowledge_base_name="")

    def test_kb_create_response(self):
        resp = KBCreateResponse(
            knowledge_base_id="kb_123",
            knowledge_base_name="test",
            description="desc",
            created_at=datetime.now(),
        )
        assert resp.knowledge_base_id == "kb_123"

    def test_kb_list_response(self):
        items = [
            KBInfo(
                knowledge_base_id="kb_1",
                knowledge_base_name="name1",
                description="",
                document_count=5,
                created_at=datetime.now(),
            )
        ]
        resp = KBListResponse(knowledge_bases=items, total=1)
        assert resp.total == 1


class TestDocumentSchemas:
    def test_doc_upload_response_no_task_id(self):
        resp = DocUploadResponse(
            doc_id="doc_abc",
            file_name="test.pdf",
            knowledge_base_id="kb_1",
            status=DocumentStatus.UPLOADED,
        )
        assert resp.status == DocumentStatus.UPLOADED
        assert not hasattr(resp, "task_id")

    def test_vectorize_doc_info_no_task_id(self):
        info = VectorizeDocInfo(
            doc_id="doc_abc",
            status=DocumentStatus.PENDING,
        )
        assert info.doc_id == "doc_abc"
        assert info.status == DocumentStatus.PENDING
        assert not hasattr(info, "task_id")

    def test_vectorize_response_uses_docs(self):
        resp = VectorizeResponse(
            docs=[VectorizeDocInfo(doc_id="d1", status=DocumentStatus.PENDING)]
        )
        assert len(resp.docs) == 1
        assert resp.docs[0].doc_id == "d1"
        assert not hasattr(resp, "tasks")

    def test_doc_retry_response_no_task_id(self):
        resp = DocRetryResponse(
            doc_id="doc_retry",
            status=DocumentStatus.PENDING,
        )
        assert resp.doc_id == "doc_retry"
        assert not hasattr(resp, "task_id")


class TestRetrieveSchemas:
    def test_retrieve_request_valid(self):
        req = RetrieveRequest(
            user_id="user1",
            knowledge_base_id="kb_1",
            query="test query",
        )
        assert req.top_k == 20
        assert req.top_n == 3
        assert req.stream is True

    def test_retrieve_request_empty_query_fails(self):
        with pytest.raises(ValidationError):
            RetrieveRequest(user_id="u1", knowledge_base_id="kb", query="")

    def test_retrieve_request_custom_values(self):
        req = RetrieveRequest(
            user_id="u1",
            knowledge_base_id="kb",
            query="q",
            top_k=20,
            top_n=5,
            stream=False,
        )
        assert req.top_k == 20
        assert req.top_n == 5
        assert req.stream is False

    def test_source_node(self):
        node = SourceNode(
            text="sample text",
            score=0.95,
            doc_id="doc1",
            file_name="file.md",
            knowledge_base_id="kb1",
            chunk_index=0,
            header_path="Section > Sub",
        )
        assert node.score == 0.95

    def test_retrieve_response(self):
        resp = RetrieveResponse(
            query="test",
            knowledge_base_id="kb1",
            source_nodes=[],
            total_candidates=0,
            top_k_used=10,
            top_n_used=3,
        )
        assert resp.total_candidates == 0


class TestCommonSchemas:
    def test_task_status_enum(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.COMPLETED == "completed"

    def test_task_status_response(self):
        resp = TaskStatusResponse(
            task_id="t1",
            status=TaskStatus.PROCESSING,
            progress="Working...",
            result=None,
            error=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert resp.status == TaskStatus.PROCESSING
