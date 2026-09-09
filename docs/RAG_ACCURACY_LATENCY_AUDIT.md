# RAG ACCURACY + LATENCY AUDIT

## WebChat AI — Comprehensive Production-Readiness Audit

### Date: September 4, 2026

---

## PIPELINE LATENCY WATERFALL (Measured/Estimated)

### Cache Miss Path (typical first query)

| Stage                              | Latency (ms)  | Type              | Blocking? |
| ---------------------------------- | ------------- | ----------------- | --------- |
| 1. Quota check                     | 5-20          | Redis/Mongo       | Async     |
| 2. Widget validation (widget path) | 10-40         | 5 sequential deps | Async     |
| 3. Sanitization                    | <1            | Pure regex        | Sync      |
| 4. Session resolve                 | 5-20          | MongoDB           | Async     |
| 5. User message persist            | 10-30         | MongoDB           | Async     |
| 6. History load (started early)    | 10-30         | MongoDB           | Async     |
| 7. Query rewrite                   | <1            | Pure regex        | Sync      |
| 8. Query classification            | <1            | Pure rules        | Sync      |
| 9. Embedding cache check           | 2-5           | Redis             | Async     |
| 10. Query embedding (MISS)         | 200-800       | **External API**  | Async     |
| 11. Retrieval cache check          | 2-5           | Redis             | Async     |
| 12. Vector search                  | 50-500        | MongoDB Atlas     | Async     |
| 13. Retrieval cache set            | 2-5           | Redis             | Async     |
| 14. Lexical corpus load            | 20-200        | Redis or Mongo    | Async     |
| 15. Keyword search                 | 50-300        | **CPU-bound**     | **SYNC**  |
| 16. RRF fusion                     | <1            | Pure computation  | Sync      |
| 17. Source diversity               | <1            | Pure computation  | Sync      |
| 18. Hydration                      | 10-50         | MongoDB $in       | Async     |
| 19. Reranking                      | 5-20          | CPU cosine        | Sync      |
| 20. Confidence check               | <1            | Pure arithmetic   | Sync      |
| 21. Context build                  | 1-5           | Dedup + budget    | Sync      |
| 22. History await                  | 0-10          | Already done      | Async     |
| 23. Prompt construction            | <1            | String assembly   | Sync      |
| 24. LLM TTFT                       | 300-2000      | **External API**  | Async     |
| 25. LLM generation                 | 1000-8000     | **External API**  | Async     |
| 26. Citation validation            | <1            | Pure regex        | Sync      |
| 27. Faithfulness check             | <1            | Word overlap      | Sync      |
| 28. Message persist                | 10-30         | MongoDB           | Async     |
| 29. Session touch + usage          | 10-30         | Concurrent Mongo  | Async     |
| **TOTAL (excl LLM stream)**        | **800-12000** |                   |           |

### Cache Hit Path (retrieval cache hit)

| Stage           | Latency (ms)           | Savings vs Miss |
| --------------- | ---------------------- | --------------- |
| Query embedding | 0 (cached)             | 200-800ms       |
| Vector search   | 0 (cached)             | 50-500ms        |
| Lexical corpus  | 20-200 (still loaded!) | 0ms (BUG)       |
| Keyword search  | 50-300 (still runs!)   | 0ms             |
| Everything else | Same                   | Same            |
| **TOTAL**       | **400-6000**           | **~30-40%**     |

### CRITICAL LATENCY ISSUES

1. **Keyword search blocks event loop** (50-300ms)
   - File: `repositories/vector/hybrid.py:208-262`
   - CPU-bound O(n) scan runs synchronously in async context
   - Blocks ALL concurrent requests during execution
   - FIX: Wrap in `asyncio.to_thread`

2. **Retrieval cache hit still loads lexical corpus** (20-200ms)
   - File: `services/chat/rag_service.py:467-476`
   - Cache only saves embedding + vector search, not keyword corpus
   - FIX: Cache corpus in retrieval cache entry

3. **Lexical corpus loaded from Redis/Mongo on every hybrid search**
   - File: `repositories/vector/hybrid.py`
   - Full chunk set loaded even when not all chunks are needed
   - FIX: Pre-compute inverted index

---

## TOKEN BUDGET BREAKDOWN

### Typical Query (5 context chunks, 3 history turns)

| Component                       | Chars     | Est. Tokens    | % of Input |
| ------------------------------- | --------- | -------------- | ---------- |
| System prompt (v1)              | ~600      | ~150           | 4-5%       |
| Question                        | ~80-200   | ~20-50         | <2%        |
| Context (5 chunks × ~800 chars) | ~4000     | ~1000          | 30-35%     |
| History (3 turns × ~200 chars)  | ~600      | ~150           | 4-5%       |
| Template overhead               | ~200      | ~50            | 1-2%       |
| **Total input**                 | ~5500     | **~2500-3500** | **100%**   |
| Output (answer)                 | ~800-2000 | ~200-500       | N/A        |

### Embedding Tokens (separate from LLM)

- Query embedding: ~10-30 tokens (single text)
- Ingestion embedding: batched, amortized per chunk

### Token Optimization Opportunities

| Opportunity                                          | Token Savings      | Cost Savings | Risk                                        |
| ---------------------------------------------------- | ------------------ | ------------ | ------------------------------------------- |
| Reduce context from 5 to 3 chunks for SIMPLE queries | ~400 tokens/query  | ~12% input   | Low (query classifier already adapts top_k) |
| Limit history to 2 turns instead of 3                | ~50 tokens/query   | ~1.5% input  | Low                                         |
| Truncate oversized chunks earlier                    | Variable           | 5-10% input  | Low                                         |
| Skip context for obvious single-fact queries         | ~1000 tokens/query | ~30% input   | Medium (accuracy risk)                      |

### CRITICAL TOKEN ISSUE

None identified. Token usage is reasonable and well-budgeted.

---

## RAG ACCURACY ASSESSMENT

### Known Working Queries (Production Validated)

| Query Type               | Status    | Notes                      |
| ------------------------ | --------- | -------------------------- |
| Course listing           | WORKS     | Broad ranking can improve  |
| Admission process        | WORKS     | Can mix sources            |
| AI-DS admission          | WORKS     |                            |
| Cyber Security admission | WORKS     |                            |
| BCA admission            | RECOVERED | After lexical improvements |
| Dean of SOIT             | WORKS     |                            |
| Chairperson              | RECOVERED | After lexical improvements |

### Accuracy Issues by Pipeline Stage

| Stage          | Issue                               | Severity | Impact                          |
| -------------- | ----------------------------------- | -------- | ------------------------------- |
| Sanitization   | Injection detection runs twice      | LOW      | None (redundant)                |
| Sanitization   | InjectionTracker never used         | MEDIUM   | Injections not tracked          |
| Embedding      | Jina has no retry                   | LOW      | Transient errors cause fallback |
| Cache          | Stale after corpus update           | LOW      | Old chunks surfaced             |
| Vector search  | Brute-force loads all into memory   | MEDIUM   | Memory pressure                 |
| Keyword search | Blocks event loop                   | MEDIUM   | Concurrent request stall        |
| Context        | Truncation at char boundary         | LOW      | Garbled last chunk              |
| Prompt         | Question truncated before detection | MEDIUM   | Malicious content bypass        |

### RAG Pipeline Correctness Assessment

| Component                 | Correctness                           | Confidence |
| ------------------------- | ------------------------------------- | ---------- |
| Query rewrite (follow-up) | Good                                  | HIGH       |
| Query classification      | Good (rule-based)                     | HIGH       |
| Atlas vector search       | Good (HNSW index)                     | HIGH       |
| Hybrid RRF fusion         | Good (k=60 standard)                  | HIGH       |
| Lexical protection        | Good (strong match guarantee)         | HIGH       |
| Source diversity (MAX-2)  | Good                                  | HIGH       |
| Confidence gating         | Good (evidence-proportional)          | HIGH       |
| Citation extraction       | Good (with minor edge cases)          | HIGH       |
| Prompt injection defense  | Partial (detection only, no blocking) | MEDIUM     |

---

## RAG RETRIEVAL QUALITY ASSESSMENT

### Hybrid Search Effectiveness

| Metric                   | Assessment | Evidence                                          |
| ------------------------ | ---------- | ------------------------------------------------- |
| Dense retrieval recall   | Good       | Atlas HNSW index with 1024-dim Jina embeddings    |
| Keyword retrieval recall | Good       | IDF-weighted scoring with typo normalization      |
| RRF fusion               | Good       | Standard k=60, preserves both rankings            |
| Source diversity         | Good       | MAX-2 chunks per source prevents domination       |
| Lexical protection       | Good       | Strong matches always reach context               |
| Candidate expansion      | Good       | candidate_top_k > top_k ensures reranker sees all |

### Remaining Retrieval Weaknesses

1. **Broad queries** ("courses") return too many similar chunks
2. **Typo normalization** only handles 2 specific typos ("addmission", "admisssion")
3. **No phrase matching** — bag-of-words only in keyword search
4. **Stop words** remove question words, making "what is X" identical to "is X"
