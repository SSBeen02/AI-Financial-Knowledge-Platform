"""질문·해설은 하오체, 상황형 보기는 현대식 문장으로 표현한다."""
import re


def question_in_hao(text: str) -> str:
    """Normalize sentence endings without changing numbers or answer keys."""
    def ending(match):
        word = match.group()
        if word.endswith(('오', '소')):
            return word
        for old, new in (
            ('아닌가요', '아니오'), ('아닌가', '아니오'), ('그런가요', '그러하오'),
            ('무엇인가요', '무엇이오'), ('무엇인가', '무엇이오'),
            ('어떤가요', '어떠하오'), ('어떤가', '어떠하오'),
            ('입니까', '이오'), ('인가요', '이오'), ('인가', '이오'),
            ('있나요', '있소'), ('없나요', '없소'), ('맞나요', '맞소'),
            ('않나요', '않소'), ('좋아요', '좋소'), ('같아요', '같소'),
            ('했어요', '했소'), ('었어요', '었소'), ('았어요', '았소'),
            ('있습니다', '있소'), ('없습니다', '없소'), ('않습니다', '않소'),
            ('있어요', '있소'), ('없어요', '없소'), ('해주세요', '해 주시오'), ('하세요', '하시오'),
            ('해요', '하오'), ('돼요', '되오'), ('한다', '하오'), ('된다', '되오'),
            ('있다', '있소'), ('없다', '없소'), ('않다', '않소'),
            ('이다', '이오'), ('같다', '같소'), ('크다', '크오'), ('작다', '작소'),
            ('낮다', '낮소'), ('높다', '높소'), ('였다', '였소'), ('었다', '었소'),
        ):
            if word.endswith(old):
                return word[:-len(old)] + new
        if word.endswith('입니다'):
            stem = word[:-3]
            consonant = bool(stem) and (ord(stem[-1]) - 0xAC00) % 28 != 0
            return stem + ('이오' if consonant else '라오')
        if word.endswith('나요'):
            stem = word[:-2]
            if stem:
                consonant = (ord(stem[-1]) - 0xAC00) % 28 != 0
                return stem + ('소' if consonant else '오')
        if word.endswith(('까요', '까')):
            suffix = '까요' if word.endswith('까요') else '까'
            stem = word[:-len(suffix)]
            if stem.endswith('을'):
                stem = stem[:-1]
            elif stem and 0xAC00 <= ord(stem[-1]) <= 0xD7A3 and (ord(stem[-1])-0xAC00)%28 == 8:
                stem = stem[:-1] + chr(ord(stem[-1])-8)
            return stem + '겠소'
        if word.endswith(('은', '는')) and match.string[match.end():].startswith('?'):
            return word + ' 무엇이오'
        if word.endswith(('습니다', '습니까')):
            return word[:-3] + '소'
        if word.endswith(('니다', '니까')):
            stem = word[:-2]
            if stem and (ord(stem[-1])-0xAC00)%28 == 17:
                stem = stem[:-1] + chr(ord(stem[-1])-17)
            return stem + '오'
        if word.endswith('는다'):
            return word[:-2] + '소'
        if word.endswith('다'):
            stem = word[:-1]
            if stem and (ord(stem[-1])-0xAC00)%28 == 4:
                return stem[:-1] + chr(ord(stem[-1])-4) + '오'
            if stem and (ord(stem[-1])-0xAC00)%28 == 0:
                return stem + '오'
            return stem + '소'
        # Never produce corrupt endings such as "않나요이오".
        if word.endswith(('요', '니까', '는가')):
            raise ValueError('질문의 종결 표현을 안전하게 하오체로 변환하지 못했습니다.')
        # A question-bank fragment ending in a noun becomes a polite statement.
        consonant = (ord(word[-1]) - 0xAC00) % 28 != 0
        return word + ('이오' if consonant else '라오')

    return re.sub(r'[가-힣]+(?=[.!?。！？]|$)', ending, text.strip())


def choice_in_modern(text: str) -> str:
    """Use contemporary plain endings for situation choices; keep noun phrases."""
    def ending(match):
        word = match.group()
        for old, new in (('기다리오','기다린다'), ('나누오','나눈다'), ('맡으오','맡는다'),
                         ('늘리오','늘린다'), ('줄이오','줄인다'), ('살피오','살핀다'),
                         ('쓰오','쓴다'), ('읽으오','읽는다'), ('받으오','받는다'),
                         ('고려하겠소','고려하겠다'), ('하겠소','하겠다'), ('겠소','겠다'), ('하시오','하세요'),
                         ('하오','한다'), ('되오','된다'), ('이오','이다'), ('라오','다'),
                         ('크오','크다'), ('보오','본다'), ('주오','준다'), ('고르오','고른다'),
                         ('맞소','맞다'), ('있소','있다'), ('없소','없다'), ('않소','않다'),
                         ('좋소','좋다'), ('같소','같다'), ('했소','했다'), ('었소','었다'), ('였소','였다')):
            if word.endswith(old):
                return word[:-len(old)] + new
        return word
    return re.sub(r'[가-힣]+(?=[.!?。！？]|$)',ending,text.strip())


def explanation_in_hao(text: str) -> str:
    # 문장 끝 또는 괄호 주석 앞의 종결어미만 처리한다.
    boundary = r"(?=[.!?。！？\s\)\]’'\"”]|\(|$)"

    def copula(match):
        previous = match.group(1)
        code = ord(previous)
        vowel_ending = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 == 0
        return previous + ("요" if vowel_ending else "이오")

    text = re.sub(r"([^\s])입니다" + boundary, copula, text)
    text = re.sub(r"습니다" + boundary, "소", text)

    def polite(match):
        syllable = match.group(1)
        code = ord(syllable)
        if (code - 0xAC00) % 28 == 17:  # ㅂ니다 → 모음 어간 + 오
            return chr(code - 17) + "오"
        return match.group(0)

    return re.sub(r"([가-힣])니다" + boundary, polite, text)
