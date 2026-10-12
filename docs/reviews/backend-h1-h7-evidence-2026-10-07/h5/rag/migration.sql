Django VERSION (3, 2, 25, 'final', 0)
BEGIN;
--
-- Creates extension pg_trgm
--
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
--
-- Create index rag_chunk_content_fts_gin on SearchVector(F(content)) on model ragchunk
--
CREATE INDEX "rag_chunk_content_fts_gin" ON "rag_chunk" USING gin ((to_tsvector('simple'::regconfig, COALESCE("content", ''))));
--
-- Create index rag_chunk_content_trgm_gin on OpClass(Upper(F(content)), name=gin_trgm_ops) on model ragchunk
--
CREATE INDEX "rag_chunk_content_trgm_gin" ON "rag_chunk" USING gin ((UPPER("content")) gin_trgm_ops);
COMMIT;
