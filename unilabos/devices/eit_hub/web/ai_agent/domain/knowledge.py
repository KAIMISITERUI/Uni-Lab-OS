# -*- coding: utf-8 -*-
"""
功能:
    知识库服务, 使用 LlamaIndex 读取文档, 使用 Qdrant 存储和检索向量.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import AI_AGENT_DB_PATH

logger = logging.getLogger("EITHubAiAgentKnowledge")

JsonDict = Dict[str, Any]

DEFAULT_KNOWLEDGE_COLLECTION = "eit_hub_knowledge"
DEFAULT_VECTOR_SIZE = 384


@dataclass(frozen=True)
class KnowledgeChunk:
    """
    功能:
        知识库待入库文本块.
    参数:
        source_path: str, 来源路径.
        chunk_index: int, 文本块序号.
        text: str, 文本内容.
    """

    source_path: str
    chunk_index: int
    text: str


class KnowledgeService:
    """
    功能:
        知识库摄取和检索服务. Qdrant 使用本地持久化路径, embedding 使用确定性本地特征哈希.
    """

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        collection_name: str = DEFAULT_KNOWLEDGE_COLLECTION,
    ) -> None:
        if storage_path is None:
            storage_path = AI_AGENT_DB_PATH.parent / "knowledge_qdrant"
        self._storage_path = storage_path
        self._collection_name = collection_name
        self._storage_path.mkdir(parents=True, exist_ok=True)

    @property
    def collection_name(self) -> str:
        """
        功能:
            返回默认 Qdrant collection 名称.
        返回:
            str, collection 名称.
        """
        return self._collection_name

    def ingest_path(self, path_text: str, collection_name: Optional[str] = None) -> JsonDict:
        """
        功能:
            摄取文件或目录到知识库.
        参数:
            path_text: str, 文件或目录路径.
            collection_name: Optional[str], 目标 collection, 留空使用默认值.
        返回:
            Dict[str, Any], 入库统计.
        """
        collection = collection_name or self._collection_name
        source_path = Path(path_text).expanduser().resolve()
        if source_path.exists() is False:
            raise FileNotFoundError(f"知识源路径不存在: {source_path}")

        chunks = self._load_chunks(source_path)
        if len(chunks) == 0:
            return {"collection": collection, "source": str(source_path), "chunks": 0}

        client = self._client()
        try:
            self._ensure_collection(client, collection)

            from qdrant_client.http import models

            points = []
            for chunk in chunks:
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.source_path}:{chunk.chunk_index}"))
                points.append(
                    models.PointStruct(
                        id=point_id,
                        vector=_embed_text(chunk.text),
                        payload={
                            "source_path": chunk.source_path,
                            "chunk_index": chunk.chunk_index,
                            "text": chunk.text,
                        },
                    )
                )
            client.upsert(collection_name=collection, points=points)
        finally:
            self._close_client(client)
        return {
            "collection": collection,
            "source": str(source_path),
            "chunks": len(points),
        }

    def search(self, query: str, limit: int = 5, collection_name: Optional[str] = None) -> JsonDict:
        """
        功能:
            从知识库检索与问题最相似的文本块.
        参数:
            query: str, 检索问题.
            limit: int, 返回条数.
            collection_name: Optional[str], 目标 collection.
        返回:
            Dict[str, Any], 检索结果和来源.
        """
        query_text = (query or "").strip()
        if query_text == "":
            raise ValueError("知识库检索问题不能为空")
        if limit <= 0:
            limit = 5
        if limit > 20:
            limit = 20

        collection = collection_name or self._collection_name
        client = self._client()
        try:
            self._ensure_collection(client, collection)
            response = client.query_points(
                collection_name=collection,
                query=_embed_text(query_text),
                limit=limit,
                with_payload=True,
            )
        finally:
            self._close_client(client)
        points = getattr(response, "points", [])
        items: List[JsonDict] = []
        for point in points:
            payload = point.payload or {}
            items.append(
                {
                    "score": float(point.score or 0.0),
                    "source_path": payload.get("source_path"),
                    "chunk_index": payload.get("chunk_index"),
                    "text": payload.get("text"),
                }
            )
        return {
            "collection": collection,
            "query": query_text,
            "items": items,
            "total": len(items),
        }

    def _client(self):
        """
        功能:
            创建 Qdrant 本地客户端.
        返回:
            QdrantClient, 本地向量库客户端.
        """
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("未安装 qdrant-client, 请先安装知识库依赖") from exc
        return QdrantClient(path=str(self._storage_path))

    def _ensure_collection(self, client: Any, collection_name: str) -> None:
        """
        功能:
            确保 Qdrant collection 存在.
        参数:
            client: Any, QdrantClient.
            collection_name: str, collection 名称.
        返回:
            None.
        """
        from qdrant_client.http import models

        exists = client.collection_exists(collection_name)
        if exists is True:
            return
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=DEFAULT_VECTOR_SIZE, distance=models.Distance.COSINE),
        )

    def _close_client(self, client: Any) -> None:
        """
        功能:
            关闭 Qdrant 本地客户端, 释放 Windows 文件锁.
        参数:
            client: Any, QdrantClient.
        返回:
            None.
        """
        close_fn = getattr(client, "close", None)
        if callable(close_fn) is True:
            close_fn()

    def _load_chunks(self, source_path: Path) -> List[KnowledgeChunk]:
        """
        功能:
            读取文件或目录并切分为文本块.
        参数:
            source_path: Path, 文件或目录.
        返回:
            List[KnowledgeChunk], 文本块列表.
        """
        documents = self._load_documents(source_path)
        chunks: List[KnowledgeChunk] = []
        for doc in documents:
            text = str(doc.get("text") or "")
            path = str(doc.get("source_path") or source_path)
            for index, chunk_text in enumerate(_chunk_text(text)):
                chunks.append(KnowledgeChunk(source_path=path, chunk_index=index, text=chunk_text))
        return chunks

    def _load_documents(self, source_path: Path) -> List[JsonDict]:
        """
        功能:
            使用轻量文本读取和 LlamaIndex 文档读取器加载知识源.
        参数:
            source_path: Path, 文件或目录.
        返回:
            List[Dict[str, Any]], 文档列表.
        """
        text_suffixes = {".md", ".txt", ".py", ".json", ".yml", ".yaml", ".csv", ".log"}
        paths: List[Path] = []
        if source_path.is_dir() is True:
            for item in source_path.rglob("*"):
                if item.is_file() is True and item.suffix.lower() in text_suffixes:
                    paths.append(item)
        elif source_path.suffix.lower() in text_suffixes:
            paths.append(source_path)

        if len(paths) > 0:
            docs: List[JsonDict] = []
            for item in paths:
                docs.append(
                    {
                        "source_path": str(item),
                        "text": item.read_text(encoding="utf-8", errors="replace"),
                    }
                )
            return docs

        try:
            from llama_index.core import SimpleDirectoryReader
        except ImportError as exc:
            raise RuntimeError("未安装 llama-index-core, 无法读取该类型知识源") from exc

        if source_path.is_dir() is True:
            reader = SimpleDirectoryReader(input_dir=str(source_path), recursive=True)
        else:
            reader = SimpleDirectoryReader(input_files=[str(source_path)])
        loaded = reader.load_data()
        docs = []
        for item in loaded:
            metadata = getattr(item, "metadata", {}) or {}
            docs.append(
                {
                    "source_path": str(metadata.get("file_path") or source_path),
                    "text": item.get_content(),
                }
            )
        return docs


def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """
    功能:
        将长文本切分为带少量重叠的块.
    参数:
        text: str, 原始文本.
        chunk_size: int, 块大小.
        overlap: int, 重叠字符数.
    返回:
        List[str], 文本块.
    """
    cleaned = (text or "").strip()
    if cleaned == "":
        return []
    chunks: List[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(0, end - overlap)
    return chunks


def _embed_text(text: str, dimension: int = DEFAULT_VECTOR_SIZE) -> List[float]:
    """
    功能:
        使用确定性特征哈希生成本地向量, 避免知识库依赖外部 embedding 服务.
    参数:
        text: str, 待编码文本.
        dimension: int, 向量维度.
    返回:
        List[float], L2 归一化向量.
    """
    vector = [0.0] * dimension
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]
