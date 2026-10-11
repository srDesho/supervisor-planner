"""
Deterministic text normalization and fuzzy matching engine.
Implements the multi-stage matching pipeline:
1. Exact matching
2. Normalized matching (case, accents, whitespace, punctuation)
3. Specialized route number extraction
4. RapidFuzz token matching
Returns categorized results: OK (unique match), AMBIGUO (multiple candidates), or NO_ENCONTRADO.
"""
import re
import unicodedata
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from rapidfuzz import fuzz


class MatchStatus(str, Enum):
    OK = "OK"
    AMBIGUO = "AMBIGUO"
    NO_ENCONTRADO = "NO_ENCONTRADO"


class MatchResult:
    def __init__(
        self,
        status: MatchStatus,
        match: Optional[Dict[str, Any]] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
        score: float = 0.0,
        explanation: str = ""
    ):
        self.status = status
        self.match = match
        self.candidates = candidates or []
        self.score = score
        self.explanation = explanation

    def __repr__(self) -> str:
        return f"<MatchResult status={self.status.value} score={self.score:.1f} match={self.match}>"


def normalize_text(text: Optional[str]) -> str:
    """
    Normalizes text for comparison:
    - Removes leading/trailing whitespace
    - Uppercases
    - Replaces special punctuation/hyphens with spaces
    - Strips accents/diacritics
    - Collapses multiple whitespace into single space
    """
    if not text:
        return ""
    
    # Uppercase and strip
    clean = text.strip().upper()
    
    # Remove accents using NFKD decomposition
    # Example: 'SÉLLER' -> 'SELLER'
    clean = "".join(
        c for c in unicodedata.normalize("NFKD", clean)
        if unicodedata.category(c) != "Mn"
    )
    
    # Replace hyphens, underscores, dots, slashes with spaces
    clean = re.sub(r"[-_/.,;:!?]+", " ", clean)
    
    # Collapse multiple whitespaces
    clean = re.sub(r"\s+", " ", clean).strip()
    
    return clean


def extract_route_number(text: str) -> Optional[str]:
    """
    Extracts isolated route numbers from text, e.g.:
    'RUTA 77' -> '77'
    'DTS-81' -> '81'
    'voy a la 12' -> '12'
    """
    match = re.search(r"\b(\d{1,4})\b", text)
    if match:
        return match.group(1)
    return None


def match_item(
    query: str,
    items: List[Dict[str, Any]],
    key: str,
    threshold: float = 85.0,
    ambiguity_delta: float = 10.0
) -> MatchResult:
    """
    Matches a text query against a list of dictionary items using a specific key.
    Pipeline:
    1. Exact match.
    2. Normalized exact match.
    3. Numeric route match (if key is 'RUTA' and query has numbers).
    4. Substring / Token matching.
    5. RapidFuzz token_set_ratio.

    :param query: Input text from user or LLM.
    :param items: List of candidate dicts from master data.
    :param key: Key to match against in candidate dicts (e.g. 'VENDEDOR' or 'RUTA').
    :param threshold: Minimum RapidFuzz score for acceptable match.
    :param ambiguity_delta: If difference between top-1 and top-2 is less than this, mark AMBIGUO.
    :return: MatchResult.
    """
    if not query or not query.strip():
        return MatchResult(MatchStatus.NO_ENCONTRADO, explanation="Query vacía")

    norm_query = normalize_text(query)
    if not norm_query:
        return MatchResult(MatchStatus.NO_ENCONTRADO, explanation="Query vacía tras normalización")

    # 1. Exact match on raw string
    for item in items:
        val = item.get(key, "")
        if val and val.strip() == query.strip():
            return MatchResult(MatchStatus.OK, match=item, score=100.0, explanation="Coincidencia exacta")

    # 2. Normalized exact match
    norm_matches = []
    seen_exact = set()
    for item in items:
        val = item.get(key, "")
        if val and normalize_text(val) == norm_query:
            val_norm = normalize_text(val)
            if val_norm not in seen_exact:
                seen_exact.add(val_norm)
                norm_matches.append(item)

    if len(norm_matches) == 1:
        return MatchResult(MatchStatus.OK, match=norm_matches[0], score=100.0, explanation="Coincidencia normalizada exacta")
    elif len(norm_matches) > 1:
        return MatchResult(
            MatchStatus.AMBIGUO,
            candidates=norm_matches,
            score=100.0,
            explanation=f"Múltiples coincidencias exactas para '{norm_query}'"
        )

    # 3. Route number specific matching (if key is RUTA)
    if "RUTA" in key.upper():
        query_num = extract_route_number(norm_query)
        if query_num:
            num_matches = []
            seen_num = set()
            for item in items:
                val = item.get(key, "")
                item_num = extract_route_number(normalize_text(val))
                if item_num == query_num:
                    val_norm = normalize_text(val)
                    if val_norm not in seen_num:
                        seen_num.add(val_norm)
                        num_matches.append(item)
            if len(num_matches) == 1:
                return MatchResult(
                    MatchStatus.OK,
                    match=num_matches[0],
                    score=95.0,
                    explanation=f"Coincidencia unívoca por número de ruta '{query_num}'"
                )
            elif len(num_matches) > 1:
                return MatchResult(
                    MatchStatus.AMBIGUO,
                    candidates=num_matches,
                    score=95.0,
                    explanation=f"Múltiples rutas contienen el número '{query_num}'"
                )

    # 4. Normalized substring / contains match
    sub_matches = []
    seen_sub = set()
    for item in items:
        val_norm = normalize_text(item.get(key, ""))
        if (norm_query in val_norm or val_norm in norm_query) and val_norm:
            if val_norm not in seen_sub:
                seen_sub.add(val_norm)
                sub_matches.append(item)

    if len(sub_matches) == 1:
        return MatchResult(
            MatchStatus.OK,
            match=sub_matches[0],
            score=90.0,
            explanation=f"Coincidencia unívoca por subcadena '{norm_query}'"
        )
    elif len(sub_matches) > 1:
        return MatchResult(
            MatchStatus.AMBIGUO,
            candidates=sub_matches,
            score=90.0,
            explanation=f"Múltiples coincidencias por subcadena para '{norm_query}'"
        )

    # 5. Fuzzy matching with RapidFuzz
    scored_candidates: List[Tuple[float, Dict[str, Any]]] = []
    q_tokens = [t for t in norm_query.split() if len(t) >= 2]

    for item in items:
        val_norm = normalize_text(item.get(key, ""))
        if not val_norm:
            continue

        c_tokens = [t for t in val_norm.split() if len(t) >= 2]
        if q_tokens and c_tokens:
            alignment = sum(max(fuzz.ratio(qt, ct) for ct in c_tokens) for qt in q_tokens) / len(q_tokens)
        else:
            alignment = 0.0

        w_ratio = fuzz.WRatio(norm_query, val_norm)
        token_set = fuzz.token_set_ratio(norm_query, val_norm)
        token_sort = fuzz.token_sort_ratio(norm_query, val_norm)

        score = max(w_ratio, token_set, token_sort, alignment)
        if score >= threshold:
            scored_candidates.append((score, item))

    # Deduplicate candidates by distinct normalized value of key
    distinct_candidates: List[Tuple[float, Dict[str, Any]]] = []
    seen_fuzzy = set()
    for sc, item in scored_candidates:
        val_norm = normalize_text(item.get(key, ""))
        if val_norm not in seen_fuzzy:
            seen_fuzzy.add(val_norm)
            distinct_candidates.append((sc, item))

    if not distinct_candidates:
        return MatchResult(
            MatchStatus.NO_ENCONTRADO,
            explanation=f"No se encontró coincidencia suficiente para '{norm_query}'"
        )

    # Sort candidates by descending score
    distinct_candidates.sort(key=lambda x: x[0], reverse=True)
    top_score, top_item = distinct_candidates[0]

    # Check ambiguity with second candidate if present
    if len(distinct_candidates) > 1:
        second_score, _ = distinct_candidates[1]
        if (top_score - second_score) < ambiguity_delta:
            ambiguous_items = [item for sc, item in distinct_candidates if (top_score - sc) < ambiguity_delta]
            return MatchResult(
                MatchStatus.AMBIGUO,
                candidates=ambiguous_items,
                score=top_score,
                explanation="Coincidencias cercanas ambiguas"
            )

    return MatchResult(
        MatchStatus.OK,
        match=top_item,
        score=top_score,
        explanation="Coincidencia fuzzy exitosa"
    )
