from app.retrieval.retriever import Passage, Retriever, parse_document, tokenize

MIN_SCORE = 3.0


def top_sources(retriever, message, k=3):
    return [p.source_id for p in retriever.search(message, k=k, min_score=MIN_SCORE)]


def test_knowledge_base_loads(retriever):
    assert retriever.passage_count >= 30
    assert "POL-BILL-001" in retriever.source_ids


def test_customer_wording_matches_policy_wording(retriever):
    # The customer says "charged twice"; the policy says "duplicate".
    assert top_sources(retriever, "I was charged twice for my subscription")[0] == "POL-BILL-001"


def test_security_message_finds_security_policy(retriever):
    assert "POL-SEC-001" in top_sources(retriever, "I think I've been hacked, someone logged into my account")


def test_export_question_finds_export_policy(retriever):
    assert top_sources(retriever, "How do I download all my account data?")[0] == "POL-GEN-002"


def test_nothing_relevant_returns_nothing(retriever):
    assert retriever.search("Do you offer an on-premise version of your software?", min_score=MIN_SCORE) == []
    assert retriever.search("Help!!", min_score=MIN_SCORE) == []


def test_results_carry_source_ids_and_scores(retriever):
    hit = retriever.search("password reset link expired", k=1, min_score=MIN_SCORE)[0]
    assert hit.source_id.startswith("POL-") and hit.score > 0 and hit.text


def test_missing_directory_gives_empty_retriever(tmp_path):
    empty = Retriever.from_directory(tmp_path / "does-not-exist")
    assert empty.passage_count == 0
    assert empty.search("anything at all") == []


def test_parse_document_splits_sections():
    passages = parse_document("POL-X-1", "# Title\n\n## A\nfirst text\n\n## B\nsecond text\n")
    assert [(p.section, p.text) for p in passages] == [("A", "first text"), ("B", "second text")]
    assert all(isinstance(p, Passage) and p.title == "Title" for p in passages)


def test_tokenizer_applies_synonyms_and_drops_stopwords():
    # Tokens are stemmed, so compare against the stemmed form of the policy word.
    assert tokenize("duplicate")[0] in tokenize("charged twice")
    assert "the" not in tokenize("the invoice")
