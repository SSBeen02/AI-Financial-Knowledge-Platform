import ast
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload')

def load_validator(root):
    path = root / 'app/services/quiz_service.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {'normalize_questions', '_normalize_ox_answer', '_validate_public_text'}:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {'OX_TRUE', 'OX_FALSE', 'ANSWER_DISCLOSURE'} for t in node.targets):
            selected.append(node)
    namespace = {'Any': Any, 're': re}
    tone = root / 'app/services/quiz_tone.py'
    if tone.exists():
        exec(compile(tone.read_text(encoding='utf-8-sig'), str(tone), 'exec'), namespace)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['normalize_questions']

tree = ast.parse((ROOT / 'tests/test_quizzes.py').read_text(encoding='utf-8-sig'))
sample = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SAMPLE_QUESTIONS' for t in n.targets))
cases = [('正常3문항', sample, False)]
cases[0] = ('정상 3문항', sample, False)
cases.extend([('2문항', sample[:2], True), ('4문항', sample + [sample[0]], True)])
def changed(label, mutate, reject=True):
    value = copy.deepcopy(sample)
    mutate(value)
    cases.append((label, value, reject))
changed('허용하지 않는 유형', lambda q: q[0].update(question_type='essay'))
changed('유형 순서 오류', lambda q: (q[0].update(question_type='situation'), q[2].update(question_type='ox', answer='O', choices=copy.deepcopy(q[1]['choices']))))
for field in ['question_type', 'prompt', 'explanation', 'question_index', 'choices', 'answer']:
    changed('필수 값 누락: ' + field, lambda q, f=field: q[0].pop(f))
changed('빈 문제', lambda q: q[0].update(prompt=' '))
changed('빈 해설', lambda q: q[0].update(explanation=' '))
changed('보기 텍스트 누락', lambda q: q[0]['choices'][0].pop('text'))
changed('중복 문항 번호', lambda q: q[1].update(question_index=1))
changed('OX 정답 오류', lambda q: q[0].update(answer='Z'))
changed('상황형 정답이 보기에 없음', lambda q: q[2].update(answer='Z'))
changed('상황형 보기 키 중복', lambda q: q[2]['choices'][1].update(key='A'))
changed('문제에 정답 표시', lambda q: q[0].update(prompt=q[0]['prompt']+' 정답: O'))
changed('보기에 정답 표시', lambda q: q[2]['choices'][1].update(text='정답: B'))
changed('상황형 보기 3개(검사 범위 확인)', lambda q: q[2]['choices'].pop(), False)
results = {}
for label, root in [('C Github final quiz', ROOT)]:
    validate = load_validator(root)
    rows = []
    for name, payload, reject in cases:
        try:
            validate(copy.deepcopy(payload))
            rejected, detail = False, ''
        except ValueError as exc:
            rejected, detail = True, str(exc)
        except Exception as exc:
            rejected, detail = None, type(exc).__name__ + ': ' + str(exc)
        rows.append({'case': name, 'expected_rejection': reject, 'rejected': rejected, 'pass': rejected == reject, 'detail': detail})
    results[label] = rows
    print(label, sum(r['pass'] for r in rows), '/', len(rows))
    for row in rows:
        print(('PASS' if row['pass'] else 'FAIL'), row['case'], row['detail'])
(Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload\\verification\\quiz-final-2026-11-09\\ut-qz03-results.json')).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
