"""Check that quiz explanations use Korean while preserving finance terms."""

import hashlib
import re
import unicodedata


# Recognize English questions and finite clauses, not arbitrary English nouns.
_ENGLISH_PROSE = re.compile(
    r"(?i)(?:\b(?:what|which|why|how|please|explain|describe|compare)\b"
    r"(?:[\s,;:!?()/-]+[A-Za-z][A-Za-z'-]*){2,}|"
    r"\b[A-Za-z][A-Za-z'-]*(?:[\s/-]+[A-Za-z][A-Za-z'-]*){0,5}\s+"
    r"(?:is|are|was|were|has|have|does|do|should|would|can|will|"
    r"requires?|repays?|increases?|decreases?|indicates?|means|refers?|"
    r"reduces?|measures?|borrows?|lends?)\s+[A-Za-z])"
)
# These are validation aliases only: never replace the displayed term.
_FINANCE_TERMS = frozenset(term.casefold() for term in (
    'LTV', 'GDP', 'GNP', 'GNI', 'DTI', 'DSR', 'M&A', 'ROA', 'ROE',
    'ETF', 'IPO', 'CPI', 'PPI', 'PER', 'PBR', 'EPS', 'BPS', 'FDI',
    'FTA', 'WTO', 'IMF', 'BIS', 'ESG', 'Loan-to-Value ratio',
    'Loan to Value ratio', 'Gross Domestic Product', 'Value at Risk',
    'Price to Earnings ratio', 'Return on Equity', 'The Great Depression',
))


def is_finance_term(text: str) -> bool:
    value = unicodedata.normalize('NFKC', text).strip().casefold()
    if value in _FINANCE_TERMS:
        return True
    measured = re.fullmatch(r'(.+?)\s+[+-]?\d+(?:[.,]\d+)?\s*%?', value)
    return bool(measured and measured.group(1) in _FINANCE_TERMS)


_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:sk-|sb_secret_|bearer\s+|(?:api[_-]?key|password|secret|token)\s*[:=]|"
    r"https?://|[\w.+-]+@[\w.-]+\.[a-z]{2,}|eyJ[A-Za-z0-9_-]+\.)"
)


def localize_quiz_text(text: str) -> str:
    """Normalize Unicode without changing the generated finance terminology."""
    return unicodedata.normalize("NFKC", text)


class QuizLanguageError(ValueError):
    """Keep raw content out of exceptions and expose only bounded diagnostics."""

    def __init__(self, text: str, *, field: str, reason: str, invalid: list[str]):
        self.field = field
        self.reason = reason
        self.text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.codepoints = tuple(dict.fromkeys(f"U+{ord(char):04X}" for char in invalid))[:8]
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text)
        if _SENSITIVE_VALUE.search(text):
            self.rejected_tokens = ("[redacted]",)
        else:
            self.rejected_tokens = tuple(dict.fromkeys(
                token if len(token) <= 24 else "[long-token-redacted]" for token in tokens
            ))[:5]
        super().__init__("문제, 상황형 보기, 해설은 한국어로 작성해야 합니다.")


def validate_korean_text(text: str, *, allow_numeric: bool = False, allow_finance_terms: bool = False, field: str = "text") -> None:
    if _SENSITIVE_VALUE.search(text):
        raise QuizLanguageError(text, field=field, reason="sensitive_content", invalid=[])
    if _ENGLISH_PROSE.search(text):
        raise QuizLanguageError(text, field=field, reason="english_prose", invalid=[])
    has_hangul = False
    has_digit = False
    has_latin = False
    invalid = []
    for char in unicodedata.normalize("NFC", text):
        name = unicodedata.name(char, "")
        if name.startswith(("HANGUL SYLLABLE ", "HANGUL LETTER ", "HANGUL CHOSEONG ",
                            "HANGUL JUNGSEONG ", "HANGUL JONGSEONG ")):
            has_hangul = True
        elif char in "0123456789":
            has_digit = True
        elif char.isascii() and char.isalpha():
            has_latin = True
            continue
        elif not (char.isspace() or unicodedata.category(char).startswith("P")
                  or unicodedata.category(char) in {"Sm", "Sc"}):
            invalid.append(char)
    if invalid:
        raise QuizLanguageError(text, field=field, reason="unsupported_characters", invalid=invalid)
    if not has_hangul and not (allow_numeric and has_digit and not has_latin):
        if allow_finance_terms and is_finance_term(text):
            return
        raise QuizLanguageError(text, field=field, reason="missing_korean_content", invalid=[])
