"""Retry Windows loop initialization only; never retry a test assertion."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
TARGET=Path(os.environ.get('QUIZ_TEST_ROOT',str(ROOT/'AI-Financial-Knowledge-Platform/quiz-upload')))
sys.path.insert(0,str(TARGET))
policy=asyncio.get_event_loop_policy()
original=policy.new_event_loop
retries=0

def new_event_loop():
    global retries
    for attempt in range(10):
        try:
            return original()
        except OSError as exc:
            if getattr(exc,'winerror',None)!=10014 or attempt==9:
                raise
            retries+=1
            time.sleep(0.05)

policy.new_event_loop=new_event_loop
suite=unittest.defaultTestLoader.loadTestsFromNames([
    'tests.test_quiz_tone','tests.test_quiz_novelty','tests.test_quizzes',
    'tests.test_team_quiz_adapter','tests.test_quiz_concurrency','tests.test_quiz_logging','tests.test_quiz_requirements'])
result=unittest.TextTestRunner(verbosity=1).run(suite)
output={'tests_run':result.testsRun,'all_passed':result.wasSuccessful(),
        'failures':len(result.failures),'errors':len(result.errors),
        'windows_event_loop_initialization_retries':retries,
        'note':'Retries apply only to OS WinError 10014 before a test starts; assertions and test bodies are not retried.'}
(TARGET/'verification/quiz-requirements-2026-11-10/unit-results.json').write_text(json.dumps(output,indent=2),encoding='utf-8')
print(json.dumps(output))
raise SystemExit(0 if result.wasSuccessful() else 1)
