import math
import re
from typing import List, Dict, Set, Any
from dataclasses import dataclass

@dataclass
class TokenizedDoc:
    id: int
    text: str
    tokens: List[str]
    token_set: Set[str]
    length: int
    original_item: Any

def tokenize(text: str) -> List[str]:
    # PhD level tokenizer: split on non-alphanumeric, lowercase, filter short
    return [x for x in re.split(r"\W+", text.lower()) if len(x) >= 2]

class BM25Scorer:
    """Okapi BM25 implementation optimized for local code context."""
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs: Dict[str, int] = {}
        self.docs: List[TokenizedDoc] = []
        self.avgdl: float = 0
        self._idf: Dict[str, float] = {}

    def fit(self, texts: List[str], objects: List[Any]):
        self.docs.clear()
        self.doc_freqs.clear()
        self._idf.clear()
        
        total_len = 0
        for idx, (text, obj) in enumerate(zip(texts, objects)):
            tks = tokenize(text)
            tks_set = set(tks)
            doc = TokenizedDoc(idx, text, tks, tks_set, len(tks), obj)
            self.docs.append(doc)
            total_len += doc.length
            
            for t in tks_set:
                self.doc_freqs[t] = self.doc_freqs.get(t, 0) + 1
                
        num_docs = len(self.docs)
        self.avgdl = total_len / max(1, num_docs)
        
        # Precompute IDF
        for t, freq in self.doc_freqs.items():
            # Standard BM25 IDF formula with +0.5 smoothing
            idf_val = math.log(1 + (num_docs - freq + 0.5) / (freq + 0.5))
            self._idf[t] = max(0.01, idf_val) # Prevent negative IDF for stop words

    def score_document(self, query_tokens: List[str], doc: TokenizedDoc) -> float:
        score = 0.0
        doc_len = doc.length
        # Precompute denominator length penalty
        len_norm = 1.0 - self.b + self.b * (doc_len / self.avgdl)
        
        # Term frequencies in THIS document
        tf = {}
        for qt in query_tokens:
            if qt in doc.token_set:
                tf[qt] = doc.tokens.count(qt)
                
        for qt in query_tokens:
            if qt not in tf:
                continue
            freq = tf[qt]
            idf = self._idf.get(qt, 0.01) # Default tiny IDF if missing (smooths out unseen query words)
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * len_norm
            score += idf * (numerator / denominator)
        return score

    def rank(self, query: str) -> List[tuple[float, Any]]:
        q_tokens = set(tokenize(query)) # Unique query terms only
        results = []
        for doc in self.docs:
            s = self.score_document(list(q_tokens), doc)
            if s > 0:
                results.append((s, doc))
        # Sort by BM25 score descending
        results.sort(key=lambda x: -x[0])
        return [(score, doc.original_item) for score, doc in results]

def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    intersection = len(set1.intersection(set2))
    if intersection == 0:
        return 0.0
    union = len(set1) + len(set2) - intersection
    return intersection / union

def maximal_marginal_relevance(
    query_tokens: List[str], 
    candidates: List[TokenizedDoc], 
    scores: List[float], 
    lambda_param: float = 0.5,
    max_items: int = 10
) -> List[Any]:
    """
    Submodular Maximization: Selects items that are relevant to query but diverse from already selected items.
    MMR = ArgMax_new [ lambda * Sim(new, query) - (1-lambda) * Max_selected Sim(new, selected) ]
    """
    if not candidates:
        return []
        
    selected_docs: List[TokenizedDoc] = []
    selected_items: List[Any] = []
    
    # Normalize BM25 scores so lambda weighting makes mathematical sense (range 0 to 1 scaling roughly)
    max_score = max(scores) if scores else 1.0
    if max_score <= 0: max_score = 1.0
    norm_scores = [s / max_score for s in scores]
    
    unselected = list(range(len(candidates)))
    
    while unselected and len(selected_items) < max_items:
        mmr_scores = {}
        for idx in unselected:
            # Relevance component
            relevancy = norm_scores[idx]
            
            # Submodular Diversity penalty component
            if not selected_docs:
                diversity_penalty = 0.0
            else:
                cand_set = candidates[idx].token_set
                # Max similarity to any already selected doc
                diversity_penalty = max(jaccard_similarity(cand_set, s.token_set) for s in selected_docs)
            
            mmr = lambda_param * relevancy - (1 - lambda_param) * diversity_penalty
            mmr_scores[idx] = mmr
            
        # Greedily select the item that maximizes the marginal gain
        best_idx = max(mmr_scores.items(), key=lambda x: x[1])[0]
        
        selected_docs.append(candidates[best_idx])
        selected_items.append(candidates[best_idx].original_item)
        unselected.remove(best_idx)
        
    return selected_items
