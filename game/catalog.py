"""사용자 제공 게임규칙 9장. 리소스는 경로 대신 프론트가 매핑할 의미 ID다."""
from game.rules import StoryDefinition, StoryRules
from game.schemas import Accessory, Rank, Title
from game.service import RankVisual


STAGE_TOTALS = {1: 30, 2: 40, 3: 50, 4: 60, 5: 70}
TITLES = tuple(Title(title_id=f"title_{i + 1}", name=name) for i, name in enumerate([
    "미래의 로또1등", "카푸어", "월급 로그아웃", "통장은 다이어트 중", "인간 경제지표",
    "소비요정", "내일부터 저축왕", "물타기 장인", "조선의 영끌러", "잔고는 비밀",
]))
ACCESSORIES = (
    Accessory(accessory_id="shoes", name="신발(짚신→목화)", rank=Rank.BEGGAR, unlock_pass_count=20, price=200),
    Accessory(accessory_id="rice_paddle", name="놀부의 밥주걱", rank=Rank.COMMONER, unlock_pass_count=27, price=270),
    Accessory(accessory_id="silver_glasses", name="은빛 동그란 안경", rank=Rank.SCHOLAR, unlock_pass_count=34, price=340),
    Accessory(accessory_id="dragon_belt", name="금빛 용 허리띠", rank=Rank.KING, unlock_pass_count=40, price=400),
)
VISUALS = {
    Rank.BEGGAR: RankVisual("beggar_default", "beggar_home"),
    Rank.COMMONER: RankVisual("commoner_default", "commoner_home"),
    Rank.SCHOLAR: RankVisual("scholar_default", "scholar_home"),
    Rank.KING: RankVisual("king_default", "palace"),
}

# (장면, 무료 이야기 소품, 말풍선). 애니메이션·표정 변화는 MVP에 포함하지 않는다.
_STORIES = {
    1: [
        ("beggar_start", None, "날씨도 좋고 기분도 최고!"),
        ("beggar_rain", None, "갑자기 비가 오잖아!"),
        ("beggar_can", "can", "비는 언제 그칠까ㅠㅠ?.."),
        ("beggar_umbrella", "umbrella", "오늘은 비가 와도 괜찮아!"),
        ("beggar_awning", "awning", "우산을 안 들어도 돼서 편하다!"),
        ("beggar_complete", None, None),
    ],
    2: [
        ("commoner_start", None, "거지를 탈출해서 좋은데 배가 좀 고프네.."),
        ("commoner_rice_plant", "rice_plant", "언제 밥을 먹을 수 있을까..?"),
        ("commoner_rice_bowl", "rice_bowl", "이제야 좀 살겠네!"),
        ("commoner_swallow", "swallow", "어쩌다 여기 떨어졌을꼬.."),
        ("commoner_gourd", "gourd", "제비가 박을 물어왔네!"),
        ("commoner_complete", None, None),
    ],
    3: [
        ("scholar_start", None, "시험에 붙으면 왕이 된다고?!"),
        ("scholar_book", "book", "나라를 다스리려면 공부부터 해야지!"),
        ("scholar_inkstone", "brush_inkstone", "왕이 되는 길은 졸음과의 싸움이구나…"),
        ("scholar_bundle", "bundle", "한양엔 언제 도착할까.."),
        ("scholar_exam", None, "백성이 굶주린다면 어떻게 하겠느냐고…? 음.."),
        ("scholar_complete", None, "누구도 굶주리지 않는 나라를 만들겠어!"),
    ],
    4: [
        ("king_start", None, "왕이 되긴 했는데… 뭘 먼저 해야 하지?"),
        ("king_petitions", "petitions", "백성들이 이렇게 힘들었다니…\n그런데 어떻게 해결해야하지..?"),
        ("king_grain", "grain", "배고픈 서러움은 내가 잘 알지!"),
        ("king_justice", None, "네 이놈! 물건을 훔쳐놓고 당당하더냐!"),
        ("king_harvest", None, "곳간도 가득하고, 백성들 얼굴에도 웃음꽃이 피었구나!\n이대로만 하면 되겠어!"),
        ("king_complete", None, "내가 조선의 왕이로다!"),
    ],
}
STORY_RULES = StoryRules([
    StoryDefinition(stage, step, scene, reward, dialogue)
    for stage, rows in _STORIES.items()
    for step, (scene, reward, dialogue) in enumerate(rows)
])
