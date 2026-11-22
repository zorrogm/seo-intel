from seo_intel.text import MinHasher, jaccard, sentences, shingles, token_spans, tokenize


def test_hindi_words_keep_their_vowel_signs():
    assert tokenize("मैं स्कूल जा रहा हूँ।") == ["मैं", "स्कूल", "जा", "रहा", "हूँ"]
    # The danda ends a sentence, not a word
    assert sentences("यह पहला वाक्य है। यह दूसरा है।") == ["यह पहला वाक्य है।", "यह दूसरा है।"]


def test_hinglish_mixes_scripts_in_one_sentence():
    words = tokenize("Mera naya PHONE बहुत अच्छा hai, price sirf ₹9,999!")
    assert words == ["mera", "naya", "phone", "बहुत", "अच्छा", "hai", "price", "sirf", "9", "999"]


def test_invisible_joiners_do_not_split_words():
    assert tokenize("क्\u200dष") == tokenize("क्ष")


def test_token_spans_point_back_into_the_text():
    text = "Buy नया phone today"
    assert [text[start:end] for _word, start, end in token_spans(text)] == ["Buy", "नया", "phone", "today"]


def test_shingles_and_minhash_work_across_scripts():
    base = tokenize("आज मौसम बहुत अच्छा है और hum log park ja rahe hain " * 6)
    near = list(base)
    near[5] = "kal"
    far = tokenize("stock market news and share price updates for investors " * 6)
    assert jaccard(shingles(base), shingles(near)) > 0.5
    assert jaccard(shingles(base), shingles(far)) == 0.0
    hasher = MinHasher(seed=0)
    same = (hasher.signature(shingles(base)) == hasher.signature(shingles(near))).mean()
    different = (hasher.signature(shingles(base)) == hasher.signature(shingles(far))).mean()
    assert same > 0.4 and different < 0.1
