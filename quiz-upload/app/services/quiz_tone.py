"""퀴즈와 학습노트의 문장 종결을 현대 존댓말로 통일합니다.

숫자·보기 식별자·명사구는 보존합니다. 변환할 수 없는 문장은 출력 전에 차단합니다.
"""
import re


def _formal(stem: str, question: bool = False) -> str:
    if not stem:
        return stem
    code = ord(stem[-1])
    jong = (code - 0xAC00) % 28 if 0xAC00 <= code <= 0xD7A3 else 0
    if jong == 8:  # ㄹ 탈락: 만들다 → 만듭니다
        stem = stem[:-1] + chr(code - 8)
        jong = 0
    if not jong and 0xAC00 <= ord(stem[-1]) <= 0xD7A3:
        return stem[:-1] + chr(ord(stem[-1]) + 17) + ('니까' if question else '니다')
    return stem + ('습니까' if question else '습니다')


def _polite(text: str, *, question: bool = False) -> str:
    def ending(match):
        word = match.group()
        if len(word) == 1 and match.start() and match.string[match.start()-1] in '(（':
            return word
        interrogative = match.string[match.end():].startswith(('?', '？'))
        if word.endswith(('습니다', '니다', '습니까', '니까', '세요', '십시오')):
            return word
        if word in {'라디오', '시나리오', '수요', '필요', '바다', '캐나다', '장소', '요소', '감소', '증가', '산소', '연구소'}:
            return word
        replacements = (
            ('아닌가요', '아닙니까'), ('아닌가', '아닙니까'),
            ('무엇인가요', '무엇입니까'), ('무엇인가', '무엇입니까'),
            ('어떤가요', '어떻습니까'), ('어떤가', '어떻습니까'),
            ('인가요', '입니까'), ('인가', '입니까'),
            ('아니에요', '아닙니다'), ('이에요', '입니다'), ('예요', '입니다'),
            ('좋아요', '좋습니다'), ('같아요', '같습니다'),
            ('했어요', '했습니다'), ('었어요', '었습니다'), ('았어요', '았습니다'),
            ('있어요', '있습니다'), ('없어요', '없습니다'),
            ('해주세요', '해 주십시오'), ('해요', '합니다'), ('돼요', '됩니다'),
            ('시오', '십시오'), ('옳소', '옳습니다'), ('모으오', '모읍니다'),
            ('기다리오', '기다립니다'),
            ('나누오', '나눕니다'), ('맡으오', '맡습니다'), ('읽으오', '읽습니다'),
            ('받으오', '받습니다'), ('쓰오', '씁니다'),
            ('하오', '합니다'), ('되오', '됩니다'), ('라오', '입니다'), ('이오', '입니다'),
            ('있소', '있습니다'), ('없소', '없습니다'), ('않소', '않습니다'),
            ('맞소', '맞습니다'), ('좋소', '좋습니다'), ('같소', '같습니다'),
            ('했소', '했습니다'), ('었소', '었습니다'), ('았소', '았습니다'), ('였소', '였습니다'),
            ('한다', '합니다'), ('된다', '됩니다'), ('이다', '입니다'),
            ('했어', '했습니다'), ('었어', '었습니다'), ('았어', '았습니다'),
            ('있어', '있습니다'), ('없어', '없습니다'), ('겠소', '겠습니다'),
            ('많소', '많습니다'), ('낮소', '낮습니다'), ('높소', '높습니다'),
            ('크오', '큽니다'), ('보오', '봅니다'), ('주오', '줍니다'),
            ('고르오', '고릅니다'), ('줄이오', '줄입니다'), ('늘리오', '늘립니다'), ('살피오', '살핍니다'),
        )
        for old, new in replacements:
            if word.endswith(old):
                return word[:-len(old)] + (new[:-2] + '니까' if interrogative and new.endswith('니다') else new)
        if word.endswith('나요'):
            return _formal(word[:-2], True)
        if word.endswith(('까요', '까')):
            stem = word[:-(2 if word.endswith('까요') else 1)]
            if stem.endswith('을'):
                stem = stem[:-1]
            elif stem and (ord(stem[-1])-0xAC00) % 28 == 8:
                stem = stem[:-1] + chr(ord(stem[-1])-8)
            return _formal(stem + '겠', True)
        if word.endswith('는다'):
            return _formal(word[:-2])
        if word.endswith('다'):
            stem = word[:-1]
            if stem and (ord(stem[-1])-0xAC00) % 28 == 4:
                stem = stem[:-1] + chr(ord(stem[-1])-4)
            return _formal(stem)
        if question and interrogative and word.endswith(('은', '는')):
            return word + ' 무엇입니까'
        # 과거 변환에서 생성한 명사+요(관계요)도 정중한 서술형으로 복원합니다.
        if word.endswith(('관계요', '결과요', '경우요')):
            return word[:-1] + '입니다'
        return word

    return re.sub(r'[가-힣]+(?=[.!?。！？(]|[)\]’\"”]|$)', ending, text.strip())


class PoliteToneError(ValueError):
    """존댓말로 확인할 수 없는 문장의 외부 출력을 막습니다."""


# 마침표 부재만으로 명사구라고 추정하지 않습니다. 허용된 명사 종결만 통과합니다.
_NOMINAL_WORDS = frozenset("""
참고 사례 감소 과열 구축효과 극대화 금융계정 기계화 기술력 남용 도입 디스인플레이션 디플레이션
매도 매입 모형 무역전환효과 무역창출효과 방식 보험 부과 부품 비대칭 비배제성 사모펀드
상승 상품수지 서비스 서비스수지 손익계산서 스마트팩토리 승수효과 않음 업무 우려 원 위치
인상 인플레이션 인하 입금 자동화 자본변동표 재무상태표 적자 정기예금 증가 지원 체제 축적
폐지 하락 할증 행사 현금흐름표 확대 흑자 금융연구소 라디오 오디오 시나리오 카카오 수요 필요 장소
요소 산소 주소 취소 해소 최소 축소 예시 기회 위협 생산국 대각선 대리인 대차대조표 배신 자본
비경합성 비탄력적 변화 등 비용 여행 외부경제 환율 가능 포함 자기자본이익률 자연독점
자유무역협정 판매 절상 존재 주인 총부채원리금상환비율 실업자 침체 탄력적 투자수익률
피구세 한계효용 행사가격 혼합 확산 완료 압박 가격 금리 물가 이자 원금 예금 저축 투자
본원소득수지 한계비용 한계소비성향 우수성 의존도 인수합병 상장지수펀드 사물인터넷 제어기
주식 채권 적금 정기적금 상품 보장 금융상품 원금보장 보기
""".split())
_FORMAL_ENDINGS = ('니다', '니까', '세요', '십시오')


def _is_nominal(text: str) -> bool:
    # 숫자 보기·계산식·O/X·A~D 등에는 말투가 없습니다.
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    if not re.search(r'[가-힣]', text):
        return bool(re.fullmatch(r'[A-Za-z0-9\s.,%+−*/=÷×→~&:_\-]+', text))
    if ',' in text:
        return all(_is_nominal(part.strip()) for part in text.split(',') if part.strip())
    if re.search(r'\d\s*(?:%|원|개|접시|명|회|배|년|월|일)$', text):
        return True
    label = re.fullmatch(r'(.+)\s+[A-D갑을병정]', text)
    if label:
        return _is_nominal(label.group(1))
    last = re.search(r'[가-힣]+$', text)
    return bool(last and last.group() in _NOMINAL_WORDS)


def validate_polite_text(text: str, *, allow_fragments: bool = False) -> None:
    """괄호·열거·마지막 마침표 없는 구간까지 빠짐없이 검사합니다."""
    def validate(value: str, fragments: bool, depth: int = 0) -> None:
        if depth > 32:
            raise PoliteToneError('괄호가 너무 깊어 문체를 확인할 수 없습니다.')
        value = value.strip()
        if not value:
            raise PoliteToneError('검사할 문장이 없습니다.')
        pieces = []
        cursor = 0
        had_labels = False
        while cursor < len(value):
            char = value[cursor]
            if char in ')）':
                raise PoliteToneError('괄호가 올바르게 닫히지 않았습니다.')
            if char not in '(（':
                pieces.append(char)
                cursor += 1
                continue
            closing = ')' if char == '(' else '）'
            stack = [closing]
            end = cursor + 1
            while end < len(value) and stack:
                token = value[end]
                if token in '(（':
                    stack.append(')' if token == '(' else '）')
                elif token in ')）':
                    if token != stack.pop():
                        raise PoliteToneError('괄호의 짝이 맞지 않습니다.')
                end += 1
            if stack:
                raise PoliteToneError('괄호가 올바르게 닫히지 않았습니다.')
            inner = value[cursor + 1:end - 1].strip()
            if inner in {'가', '나', '다', '라'}:
                # 열거 내용은 별도 명사구/문장으로 검사하며 버리지 않습니다.
                following = value[end:end + 1]
                pieces.append(' ' if following and not following.isspace() and following not in ',;:' else '\n@item@')
                had_labels = True
            else:
                validate(inner, True, depth + 1)
                pieces.append(' ')
            cursor = end
        outside = ''.join(pieces)
        outside = re.sub(r'[“”‘’"\']', '', outside)
        outside = re.sub(r'(?<=\d)\.(?=\d)', '', outside)
        sections = outside.split('@item@')
        for index, section in enumerate(sections):
            nominal = fragments or index > 0
            chunks = re.split(r'[.!?。！？\n]+', section)
            for chunk in chunks:
                chunk = chunk.strip(' \t,;:')
                if not chunk:
                    continue
                if had_labels and chunk in {'와', '과', '및', '그리고'}:
                    continue
                if chunk.endswith(_FORMAL_ENDINGS):
                    continue
                if nominal and _is_nominal(chunk):
                    continue
                raise PoliteToneError('문장의 존댓말 종결 표현을 확인할 수 없습니다.')
    validate(text, allow_fragments)


def _safe_polite(text: str, *, question: bool = False, fragments: bool = False, strict: bool = False) -> str:
    converted = _polite(text, question=question)
    try:
        validate_polite_text(converted, allow_fragments=fragments)
    except PoliteToneError:
        if strict:
            raise
        # 저장된 원본은 수정하지 않고, 검증되지 않은 표현의 노출만 차단합니다.
        return '이 문장의 존댓말 표현을 확인할 수 없습니다.'
    return converted


def question_in_polite(text: str, *, strict: bool = False) -> str:
    return _safe_polite(text, question=True, strict=strict)


def choice_in_polite(text: str, *, strict: bool = False) -> str:
    return _safe_polite(text, fragments=True, strict=strict)


def explanation_in_polite(text: str, *, strict: bool = False) -> str:
    return _safe_polite(text, strict=strict)
