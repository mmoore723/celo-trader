"""Beginner education with account-scoped progress. No execution dependencies."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/learning/course', tags=['learning'])
DB_PATH = Path(__file__).resolve().parents[2] / 'user_data' / 'learning_portal.db'
VERSION = 'options-foundations-1'
LESSONS = json.loads(Path(__file__).with_name('learning_course_content.json').read_text())
FINAL_IDS = [2,3,4,5,7,9,12,13,17,19]
SOURCES = [
    {'title':'Options Industry Council: Getting started', 'url':'https://www.optionseducation.org/optionsoverview/getting-started-with-options'},
    {'title':'Investor.gov: An introduction to options', 'url':'https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-63'},
    {'title':'Schwab: Options Greeks', 'url':'https://www.schwab.com/options/options-greeks'},
]


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('CREATE TABLE IF NOT EXISTS course_progress (user_id TEXT, version TEXT, lesson TEXT, attempts INTEGER NOT NULL, best_score INTEGER NOT NULL, passed INTEGER NOT NULL, updated_at TEXT, PRIMARY KEY(user_id,version,lesson))')
    return conn


def progress_for(conn, user):
    return {r[0]: dict(attempts=r[1], best_score=r[2], passed=bool(r[3])) for r in conn.execute('SELECT lesson,attempts,best_score,passed FROM course_progress WHERE user_id=? AND version=?', (user,VERSION))}


def public_questions(questions):
    return [dict(prompt=q['prompt'], choices=q['choices']) for q in questions]


@router.get('')
def course(request: Request):
    with closing(connect()) as conn:
        progress = progress_for(conn,request.state.user_id)
    lessons = [{k:v for k,v in l.items() if k!='questions'} | {'questions':public_questions(l['questions']), 'progress':progress.get(l['id'],{})} for l in LESSONS]
    return dict(version=VERSION, lessons=lessons, sources=SOURCES, final=dict(id='final',title='Foundation knowledge check',questions=public_questions([LESSONS[i]['questions'][0] for i in FINAL_IDS]),progress=progress.get('final',{}),pass_percent=80), disclaimer='Original illustrative examples. Education and paper practice only. This is not an accredited qualification or approval to trade.')


class Submission(BaseModel):
    lesson: str = Field(max_length=40)
    choices: list[int] = Field(min_length=1, max_length=10)


@router.post('/answer')
def answer(body: Submission, request: Request):
    lesson = next((l for l in LESSONS if l['id']==body.lesson),None)
    if body.lesson=='final':
        questions = [LESSONS[i]['questions'][0] for i in FINAL_IDS]
    elif lesson:
        questions = lesson['questions']
    else:
        raise HTTPException(422,'Choose a lesson in this course.')
    if len(body.choices)!=len(questions) or any(c<0 or c>=len(q['choices']) for c,q in zip(body.choices,questions)):
        raise HTTPException(422,'Answer each question using its choices.')
    with closing(connect()) as conn:
        if body.lesson=='final' and not all(progress_for(conn,request.state.user_id).get(l['id'],{}).get('passed') for l in LESSONS):
            raise HTTPException(409,'Complete the lesson checks before the final knowledge check.')
        results=[dict(correct=c==q['correct'],explanation=q['explanation']) for c,q in zip(body.choices,questions)]
        score=round(100*sum(r['correct'] for r in results)/len(results))
        passed=score >= (80 if body.lesson=='final' else 100)
        with conn:
            conn.execute('INSERT INTO course_progress VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,version,lesson) DO UPDATE SET attempts=course_progress.attempts+1,best_score=MAX(course_progress.best_score,excluded.best_score),passed=MAX(course_progress.passed,excluded.passed),updated_at=excluded.updated_at',(request.state.user_id,VERSION,body.lesson,1,score,int(passed),datetime.now(timezone.utc).isoformat()))
    return dict(score=score,passed=passed,results=results,version=VERSION)
