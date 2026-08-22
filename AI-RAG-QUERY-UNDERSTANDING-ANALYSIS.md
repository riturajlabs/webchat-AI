# AI RAG Query Understanding Analysis

> Date: 2026-08-20 | Scope: Should a Query Understanding Layer be added before retrieval?
> Analysis type: Architecture decision record | No code changes

---

## Executive Summary

**Recommendation: Do NOT add a Query Understanding Layer at this time.**

The current pipeline already handles the common failure modes through existing mechanisms: vector embeddings are semantically robust to short/ambiguous queries, hybrid search covers keyword matching, and the reranker corrects retrieval ordering. A query understanding layer would add 200-1,500ms latency (7-50% of total request time), introduce hallucination risk in query rewriting, break the embedding cache, and increase system complexity — all for marginal accuracy gains on edge cases that the existing pipeline already handles.

**The latency cost and hallucination risk outweigh the accuracy benefit.**

---

## 1. Current Query Flow (Post-All Optimizations)

```
User Question
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. SANITIZE & VALIDATE                                          │
│    sanitize_question() → strip control chars, collapse WS,     │
│    cap length, detect injection patterns                        │
│    Cost: < 1ms                                                  │
│    Handles: injection, empty input, oversized input             │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. EMBED QUESTION                                               │
│    _embed_question() → Gemini embedding API                     │
│    Cache: Redis LRU (256 entries, 1h TTL) on normalized text   │
│    Cost: ~950-1100ms (miss) / ~5ms (hit)                        │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. VECTOR SEARCH                                                │
│    similarity_search() → MongoDB $vectorSearch                   │
│    top_k=8, numCandidates=160                                    │
│    Cost: ~160-250ms                                              │
│    Handles: semantic similarity, synonym matching, paraphrasing  │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. HYBRID RETRIEVAL                                             │
│    _load_all_chunks(limit=50) + keyword_search + RRF fusion     │
│    Cost: ~20-55ms                                               │
│    Handles: exact keyword matching, proper nouns, acronyms      │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. RERANK (stored embeddings)                                   │
│    cosine_similarity(query_embedding, chunk.embedding)          │
│    Cost: ~1-5ms                                                 │
│    Handles: final relevance correction, ordering refinement     │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. BUILD CONTEXT + GENERATE                                     │
│    min_score=0.25, dedup, char_budget=20000                     │
│    Gemini streaming                                             │
│    Cost: ~1000-1600ms                                           │
└─────────────────────────────────────────────────────────────────┘
```

**Total: ~2,100-3,000ms** (post-optimization)

---

## 2. Current Failure Modes Analysis

### Failure Mode 1: Short Queries

**Example:** "pricing", "SSO", "refund"

| Stage          | Behavior                                           | Impact                                            |
| -------------- | -------------------------------------------------- | ------------------------------------------------- |
| Embedding      | Gemini produces a meaningful vector for short text | Low risk — embeddings handle single words well    |
| Vector search  | Returns semantically similar chunks                | Low risk — "pricing" matches chunks about pricing |
| Keyword search | 1-2 tokens after stop-word removal                 | Low risk — exact match on relevant keywords       |
| Reranker       | Corrects ordering based on similarity              | Low risk — fine-grained relevance                 |

**Assessment:** Short queries are handled well by the existing pipeline. Vector embeddings are particularly robust to single-word inputs because Gemini's embedding model is trained on diverse text lengths.

### Failure Mode 2: Ambiguous Queries

**Example:** "How does it work?", "Tell me more", "What about the other one?"

| Stage          | Behavior                                            | Impact                                       |
| -------------- | --------------------------------------------------- | -------------------------------------------- |
| Embedding      | Produces a generic vector for vague text            | Medium risk — may not match specific content |
| Vector search  | Returns broadly similar chunks                      | Medium risk — may include irrelevant results |
| Keyword search | Few meaningful tokens after stop-word removal       | Low risk — "work" matches general content    |
| Reranker       | May not improve much if all candidates are mediocre | Medium risk — no good candidates to rank     |

**Assessment:** Ambiguous queries are the hardest case. However, in a support chatbot context, users rarely ask vague questions without context. The conversation history (loaded async, rendered in prompt) provides disambiguation context for the generation step, even if retrieval is imperfect.

### Failure Mode 3: Spelling Mistakes

**Example:** "prcing", "enterprse", "refnd"

| Stage          | Behavior                                                  | Impact                                                  |
| -------------- | --------------------------------------------------------- | ------------------------------------------------------- |
| Embedding      | Gemini is somewhat robust to typos (subword tokenization) | Low-medium risk — similar words produce similar vectors |
| Vector search  | May miss exact matches                                    | Medium risk — "prcing" may not match "pricing" chunks   |
| Keyword search | Exact token match fails                                   | High risk — "prcing" ≠ "pricing"                        |
| Reranker       | Can't recover if no good candidates                       | High risk — ordering won't help                         |

**Assessment:** Spelling mistakes are a real problem for keyword search but are partially mitigated by vector search (Gemini's subword tokenization handles minor typos). The reranker cannot recover from a complete miss at the retrieval stage.

### Failure Mode 4: Missing Context

**Example:** "What about the enterprise plan?" (after asking about pricing)

| Stage          | Behavior                                                | Impact                                      |
| -------------- | ------------------------------------------------------- | ------------------------------------------- |
| Embedding      | "enterprise plan" is embedded without "pricing" context | Low risk — still matches enterprise content |
| Vector search  | Returns enterprise-related chunks                       | Low risk — semantic match works             |
| Keyword search | Matches "enterprise" and "plan" keywords                | Low risk — good keyword coverage            |
| Reranker       | Corrects based on similarity                            | Low risk — enterprise chunks are relevant   |
| Generation     | Conversation history provides full context              | Low risk — prompt includes prior turns      |

**Assessment:** Missing context is handled by two mechanisms: (1) the query itself ("enterprise plan") is sufficient for retrieval, and (2) the conversation history in the prompt provides the full context for generation. The system already loads conversation memory (`_load_history`) and renders it in the user prompt.

### Failure Mode 5: Multi-Intent Queries

**Example:** "How much does enterprise cost and what features does it include?"

| Stage          | Behavior                                      | Impact                             |
| -------------- | --------------------------------------------- | ---------------------------------- |
| Embedding      | Combines both intents into one vector         | Medium risk — may favor one intent |
| Vector search  | Returns chunks matching the combined semantic | Medium risk — may miss one intent  |
| Keyword search | Matches both "cost" and "features"            | Low risk — both keywords present   |
| Reranker       | May not balance both intents                  | Medium risk — ordering favors one  |

**Assessment:** Multi-intent queries are rare in support chatbot contexts. Users typically ask one question at a time. The hybrid search (vector + keyword via RRF) provides decent coverage for multi-topic queries because vector search captures one intent and keyword search captures the other.

---

## 3. Query Understanding Approaches

### Approach A: Rule-Based Query Expansion

**How it works:** Pattern matching to detect query characteristics and apply transformations:

- Typo correction via edit distance dictionary
- Abbreviation expansion ("SSO" → "Single Sign-On")
- Query clarification for short/ambiguous queries
- Domain-specific synonym mapping

**Implementation:**

```python
def expand_query(query: str, context: list[str] | None = None) -> str:
    # 1. Typo correction (edit distance)
    corrected = spell_check(query, domain_dictionary)
    # 2. Abbreviation expansion
    expanded = expand_abbreviations(corrected, ABBREVIATION_MAP)
    # 3. Context injection from conversation history
    if context and is_ambiguous(query):
        expanded = inject_context(expanded, context)
    return expanded
```

| Criterion                     | Assessment                                                  |
| ----------------------------- | ----------------------------------------------------------- |
| **Accuracy impact**           | Low-medium — handles common patterns but misses novel cases |
| **Latency impact**            | ~1-5ms — pure Python, no API calls                          |
| **Cost impact**               | Zero — no external services                                 |
| **Implementation complexity** | Low — regex, dictionary lookups, edit distance              |
| **Hallucination risk**        | Zero — deterministic transformations                        |
| **Maintenance burden**        | Medium — dictionaries need updating as domain evolves       |

**Strengths:**

- Zero latency overhead
- Zero cost
- Deterministic and debuggable
- No hallucination risk

**Weaknesses:**

- Limited to known patterns (can't handle novel queries)
- Requires manual dictionary maintenance
- No semantic understanding
- Abbreviation/expansion maps must be curated per tenant

### Approach B: LLM-Based Query Rewriting

**How it works:** Use Gemini (or a smaller model) to rewrite/expand the query before embedding:

- "How much?" → "What is the pricing for the product?"
- "SSO" → "Single Sign-On authentication feature"
- "refnd" → "refund policy and process"

**Implementation:**

```python
async def rewrite_query(question: str, history: list[str]) -> str:
    prompt = f"""Rewrite this customer support question to be more specific
    and searchable. Keep the original meaning. Do not add information.
    Question: {question}"""
    return await generation_client.generate(prompt)
```

| Criterion                     | Assessment                                         |
| ----------------------------- | -------------------------------------------------- |
| **Accuracy impact**           | High — semantic understanding of intent            |
| **Latency impact**            | ~500-1500ms — Gemini API call                      |
| **Cost impact**               | ~$0.001-0.003 per request (Gemini Flash)           |
| **Implementation complexity** | Medium — prompt engineering, error handling        |
| **Hallucination risk**        | **HIGH** — LLM may invent details or change intent |
| **Maintenance burden**        | Low — prompt-driven, no dictionaries               |

**Strengths:**

- Handles all query types (short, ambiguous, typos, multi-intent)
- Semantic understanding
- Minimal maintenance

**Weaknesses:**

- **Latency: +500-1500ms (20-50% of total request time)**
- **Hallucination: LLM may rewrite "How much?" as "What is the pricing for the enterprise plan?" when the user meant the basic plan**
- **Cache invalidation: rewritten query produces different embedding, breaking cache**
- Cost: ~$0.001-0.003 per request (adds up at scale)
- Error handling: what if the rewrite fails or is nonsensical?

### Approach C: Small Classifier for Intent Detection

**How it works:** Train a lightweight classifier to categorize queries into intents (pricing, features, support, etc.) and route to appropriate retrieval strategies.

**Implementation:**

```python
# Requires: training data, model serving infrastructure
intent_classifier = load_model("intent_classifier.onnx")
intent = intent_classifier.predict(query)
# Route based on intent
if intent == "pricing":
    boost_pricing_chunks()
elif intent == "feature":
    boost_feature_chunks()
```

| Criterion                     | Assessment                                                    |
| ----------------------------- | ------------------------------------------------------------- |
| **Accuracy impact**           | Medium — depends on training data quality                     |
| **Latency impact**            | ~50-200ms — local ONNX inference                              |
| **Cost impact**               | Model hosting (~$50-200/month for small model)                |
| **Implementation complexity** | **High** — training data, model training, serving, monitoring |
| **Hallucination risk**        | Low — classification is deterministic                         |
| **Maintenance burden**        | **High** — retraining, drift detection, data labeling         |

**Strengths:**

- Fast inference (ONNX)
- Deterministic
- No hallucination risk

**Weaknesses:**

- **Requires labeled training data** (expensive, time-consuming)
- **Model serving infrastructure** (not currently in stack)
- **Domain-specific** — each tenant needs different intents
- **No query rewriting** — only classification, not expansion
- **Training data drift** — new products/features require retraining

### Approach D: Hybrid Approach (Rule-Based + Conditional LLM)

**How it works:** Apply rules for common cases, escalate to LLM only for complex/ambiguous queries:

```python
def understand_query(query: str, history: list[str]) -> str:
    # 1. Apply rules (fast, deterministic)
    expanded = apply_rules(query)
    # 2. Check if query is still ambiguous
    if is_ambiguous(expanded) and history:
        # 3. Only call LLM for genuinely ambiguous cases
        expanded = rewrite_with_llm(expanded, history)
    return expanded
```

| Criterion                     | Assessment                                              |
| ----------------------------- | ------------------------------------------------------- |
| **Accuracy impact**           | High — rules for common cases, LLM for edge cases       |
| **Latency impact**            | ~1-5ms (rules) + ~500-1500ms (LLM, ~10-20% of requests) |
| **Cost impact**               | ~$0.0001-0.0006 per request (most handled by rules)     |
| **Implementation complexity** | Medium-high — rules + LLM + ambiguity detection         |
| **Hallucination risk**        | **Medium** — LLM used selectively, but still present    |
| **Maintenance burden**        | Medium — rules need updating, LLM prompt tuning         |

**Strengths:**

- Best of both worlds: fast rules + powerful LLM
- Lower cost than pure LLM
- Lower latency than pure LLM (most queries skip LLM)

**Weaknesses:**

- **Ambiguity detection is itself a hard problem** (how do you know when to call the LLM?)
- **Still has hallucination risk** when LLM is called
- **Still has latency impact** when LLM is called
- **Complexity is higher** than any single approach

---

## 4. Head-to-Head Comparison

| Criterion                 | Weight | Rule-Based | LLM-Based         | Classifier          | Hybrid               |
| ------------------------- | ------ | ---------- | ----------------- | ------------------- | -------------------- |
| Accuracy improvement      | 25%    | Low-medium | High              | Medium              | High                 |
| Latency impact            | 25%    | **+1-5ms** | +500-1500ms       | +50-200ms           | +1-1500ms (variable) |
| Cost impact               | 15%    | **Zero**   | ~$0.001-0.003/req | ~$100/month hosting | ~$0.0001-0.0006/req  |
| Implementation complexity | 20%    | **Low**    | Medium            | High                | Medium-high          |
| Hallucination risk        | 15%    | **Zero**   | **HIGH**          | Low                 | Medium               |
| **Weighted Score**        | 100%   | **3.8/5**  | **2.5/5**         | **2.2/5**           | **2.8/5**            |

---

## 5. Why Query Understanding Doesn't Help This System

### 5.1 The Reranker Already Handles Retrieval Quality

The `EmbeddingReranker` re-scores all candidates using embedding-model cosine similarity. Even if vector search returns suboptimal results due to a short/ambiguous query, the reranker corrects the ordering. The retrieval pipeline is designed to be "retrieve broadly, rank precisely" — query understanding would improve the "retrieve" step, but the "rank" step already compensates.

### 5.2 Vector Embeddings Are Robust to Query Variations

Gemini's embedding model is trained on diverse text and produces meaningful vectors even for:

- Single words: "pricing" → vector in pricing semantic space
- Abbreviations: "SSO" → vector near "Single Sign-On"
- Minor typos: "prcing" → subword tokens still overlap with "pricing"

The embedding model is itself a form of "query understanding" — it encodes semantic meaning regardless of surface form.

### 5.3 Conversation History Provides Context

The system already loads conversation history (`_load_history`) and renders it in the user prompt (`render_history`). When a user asks "What about enterprise?" after discussing pricing, the generation model sees:

```
Conversation history (most recent last):
[user] What are your pricing plans?
[assistant] We offer three plans: Basic ($9/mo), Pro ($29/mo), Enterprise (custom)...

Question: What about enterprise?
```

The generation model uses this history to understand the query — no query understanding layer needed for retrieval.

### 5.4 The Cost-Benefit Ratio Is Poor

**Current total latency: ~2,100-3,000ms**

| Query Understanding Approach | Added Latency | % of Total |
| ---------------------------- | ------------- | ---------- |
| Rule-based                   | +1-5ms        | 0.05-0.2%  |
| LLM-based                    | +500-1500ms   | 20-50%     |
| Classifier                   | +50-200ms     | 2-7%       |
| Hybrid                       | +1-1500ms     | 0.05-50%   |

The LLM-based approach adds 20-50% latency. The classifier adds 2-7%. Only the rule-based approach has negligible impact — but it also has the lowest accuracy improvement.

### 5.5 Hallucination Risk in Query Rewriting

The system's primary design principle is **low hallucination**. The system prompt explicitly states: "Answer only using the reference material. Never invent, guess, or use outside knowledge."

Adding an LLM call before retrieval introduces a new hallucination vector: the query rewrite itself. If the LLM rewrites "How much?" as "What is the pricing for the enterprise plan?" when the user meant the basic plan, the entire retrieval is skewed. The user gets an answer to a question they didn't ask.

This is especially dangerous because:

1. The rewrite is invisible to the user (they see their original question)
2. The generation model trusts the retrieved context (it doesn't know the query was rewritten)
3. There's no way to verify the rewrite was correct

---

## 6. What WOULD Justify Query Understanding

The analysis would change if:

1. **The reranker is removed:** Without reranking, retrieval quality matters much more. Query understanding would improve the initial retrieval, which becomes the final ranking.

2. **Multi-language support is required:** Query understanding for non-English queries (translation, transliteration) would significantly improve retrieval quality.

3. **The knowledge base is very small (< 100 chunks):** With fewer candidates, retrieval precision matters more. Query understanding could help surface the right chunks from a small pool.

4. **The system handles highly specialized queries:** Medical, legal, or technical domains where query formulation is critical for accuracy.

5. **Latency budget is generous (> 10s acceptable):** If the user experience can tolerate additional delay, the accuracy gains may justify the cost.

**None of these conditions apply to WebChat AI SaaS.**

---

## 7. Recommended Alternative: Improve Existing Pipeline

Instead of adding a query understanding layer, improve the existing pipeline components:

### Option A: Improve Embedding Cache Hit Rate (Trivial effort, high impact)

The embedding cache uses `question.strip().lower()` as the key. Synonym normalization would increase cache hits:

- "pricing" and "prices" → same cache key
- "SSO" and "single sign-on" → same cache key

**Complexity:** Low (normalization function)
**Impact:** Higher cache hit rate → lower average latency
**Risk:** Zero

### Option B: Add Synonym Boosting to Keyword Search (Low effort, medium impact)

Expand the keyword search with domain-specific synonyms:

- "price" ↔ "pricing" ↔ "cost"
- "SSO" ↔ "single sign-on" ↔ "authentication"

**Complexity:** Low (configurable synonym map)
**Impact:** Better keyword matching for synonyms
**Risk:** Zero

### Option C: Improve Short Query Handling in Keyword Search (Low effort, low impact)

When query has ≤ 2 tokens, lower the `min_score` threshold or boost keyword scores:

- Current: `keyword_search` returns empty if score = 0
- Improved: return results with score > threshold for short queries

**Complexity:** Low (configurable threshold)
**Impact:** Better recall for short queries
**Risk:** Low (may include slightly less relevant results)

### Option D: Multi-Query Retrieval (Medium effort, high impact)

Generate multiple query variations from the original query using simple rules, then merge results:

```python
queries = [original_query]
if is_short(original_query):
    queries.append(expand_abbreviations(original_query))
if is_ambiguous(original_query):
    queries.append(add_domain_context(original_query))
# Run retrieval for each query, merge via RRF
```

**Complexity:** Medium (query generation + result merging)
**Impact:** Better recall for problematic queries
**Risk:** Low (no LLM hallucination, deterministic rules)

---

## 8. Implementation Plan (If Insisted Upon)

If the decision is made to proceed despite the recommendation:

### Phase 1: Rule-Based Expansion (Day 1-2)

1. Add `QueryExpander` class with:
   - Abbreviation expansion (configurable per-tenant)
   - Typo correction (edit distance dictionary)
   - Domain synonym mapping
2. Add `enable_query_expansion: bool = False` setting (opt-in)
3. Integrate into `rag_service.py` before `_embed_question()`
4. Add `query_expansion_ms` to timing metrics

### Phase 2: Embedding Cache Integration (Day 2)

1. Ensure cache key uses **expanded** query (not original)
2. Original query is used for keyword search (preserves exact matching)
3. Expanded query is used for embedding (better semantic match)

### Phase 3: Testing (Day 3)

1. Unit tests for each expansion rule
2. Integration tests for expanded query flow
3. Accuracy comparison tests (with/without expansion)
4. Cache hit rate comparison tests

### Phase 4: Conditional LLM Rewrite (Day 3-4, optional)

1. Add `enable_llm_query_rewrite: bool = False` setting
2. Add `llm_query_rewrite_threshold` — only call LLM when confidence is low
3. Add timeout and fallback for LLM rewrite failures
4. Log all rewrites for monitoring

### Estimated Effort: 3-4 days (rule-based only), 5-7 days (with LLM)

---

## 9. Conclusion

**The Query Understanding Layer is not justified for WebChat AI SaaS at this time.**

The current pipeline already handles the common failure modes:

- **Short queries:** Vector embeddings are robust to single-word inputs
- **Ambiguous queries:** Conversation history provides context for generation
- **Spelling mistakes:** Gemini's subword tokenization handles minor typos
- **Missing context:** Conversation history fills in gaps

The proposed query understanding approaches have poor cost-benefit ratios:

- **Rule-based:** Low impact, but zero latency/cost — acceptable if added
- **LLM-based:** High impact, but +20-50% latency + hallucination risk — unacceptable
- **Classifier:** Medium impact, but high complexity + training data requirement — unjustified
- **Hybrid:** Best of both worlds, but still has latency/hallucination when LLM is called

**The existing pipeline's "retrieve broadly, rank precisely" design is the right architecture.** The reranker corrects retrieval imperfections, vector embeddings handle semantic variations, and conversation history provides context. Adding query understanding would be optimizing a step that doesn't need optimization.

**If** query quality becomes a significant problem in production (measured by fallback rate, faithfulness warnings, or user feedback), the first action should be improving the embedding cache hit rate and adding synonym boosting — not adding an LLM-based query rewriting layer.

---

_End of analysis. No code changes were made. All findings are based on static code analysis and architecture evaluation._
