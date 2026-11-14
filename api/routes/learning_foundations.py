"""Small educational replay library, separate from research and order execution."""
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
import sqlite3
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/learning/foundations', tags=['learning'])
DB_PATH = Path(__file__).resolve().parents[2] / 'user_data' / 'learning_foundations.db'
VERSION = 'chart-foundations-1'
# Invented teaching candles, never presented as a real ticker, signal or result.
LESSONS = [
    dict(id='candle', title='Read one candle', intro='A candle is a small price story. Its body connects the opening and closing prices. The thin lines show the highest and lowest prices reached.',
         candles=[[100,103,99,102],[102,104,100,101],[101,102,98,99]],
         notes=['Price opened at $100 and closed at $102. Buyers finished this candle higher. Its low was $99 and its high was $103.',
                'This candle reached $104, but closed at $101, below its $102 opening. Reaching a high does not mean price stayed there.',
                'Price closed at $99. This candle ended lower than the previous close of $101. That describes what happened, not what happens next.'],
         question='The second candle reached $104 but closed at $101. Where did it finish?', choices=['At its highest price, $104','At its closing price, $101','At the next candle’s price'], correct=1,
         explanation='The close is the final price of that completed candle. The high tells you how far price reached along the way.'),
    dict(id='level', title='A touch is not a close', intro='A price level is a line you watch. A quick move through it can disappear before the candle ends. Here the example level is $102.',
         candles=[[100,102,99,101],[101,103,100,101],[101,104,101,103]],
         notes=['The first candle closes at $101, below our $102 example level.',
                'Price briefly reaches $103, above the line, but closes back at $101. It touched beyond the level without closing above it.',
                'This completed candle closes at $103, above $102. That confirms a close beyond this line. It does not guarantee the next candle will rise.'],
         question='Which candle has a completed close above $102?', choices=['The first','The second','The third'], correct=2,
         explanation='Only the third closes above $102. The second only reaches above it during the candle. Different strategies can use different checks.'),
    dict(id='pullback', title='Follow a pullback', intro='A pullback is a move back toward a recent price level after price has moved away. It can pause a move or turn into a reversal.',
         candles=[[100,103,99,102],[102,106,102,105],[105,105,102,103],[103,106,102,105]],
         notes=['The example starts with a close at $102.',
                'Price moves up to a $105 close. We have not seen a pullback yet.',
                'Price moves back to a $103 close. That is a pullback from $105. At this point we cannot know whether it will recover.',
                'The next candle closes at $105. Now we can see a recovery. That fourth candle was not available when the third closed.'],
         question='At the end of candle three, could you know candle four would recover?', choices=['Yes, every pullback recovers','No, candle four had not happened yet'], correct=1,
         explanation='A chart can look obvious after the move. A decision can only use information already available at that moment. A pullback alone is not a buy instruction.'),
]
# Additional scenarios preserve the original lesson IDs and saved progress.
LESSONS.extend([
    dict(id='failed-break',title='Spot a failed breakout',intro='The watched ceiling is $103. Reveal each candle and decide whether price stayed above it.',candles=[[100,102,99,101],[101,103,100,102],[102,105,102,104],[104,104,101,102]],notes=['Price closes at $101, below the ceiling.','Price touches $103 but closes at $102. A touch is not a completed breakout.','Now a candle closes at $104, above $103. A breakout has occurred, but it can still fail.','The next close returns to $102, below the ceiling. The breakout did not hold.'],question='What changed on the fourth candle?',choices=['The earlier breakout returned below its level','The fourth candle guarantees a larger rally','Nothing changed because the prior candle was green'],correct=0,explanation='Price closed back below $103. This is evidence of a failed breakout in this example, not a prediction of the next candle.'),
    dict(id='higher-low',title='Find a higher low',intro='A higher low means a later turning low sits above an earlier turning low. Watch for confirmation before naming it.',candles=[[102,103,99,100],[100,104,100,103],[103,105,102,104],[104,104,101,102],[102,105,102,104]],notes=['This candle reaches $99. We do not yet know whether that is a turning low.','Price moves up. The earlier $99 low is now behind a rising candle.','Price continues upward before pulling back.','The pullback reaches $101, above $99, but it may still continue lower.','A later candle rises from the pullback. Only now does this simple example confirm the $101 turning low above $99.'],question='When was the second turning low confirmed in this example?',choices=['As soon as candle four touched $101','After candle five showed the recovery','Before any candle appeared'],correct=1,explanation='The confirming candle came later. You cannot use candle five’s evidence while making a decision at candle four.'),
    dict(id='lower-high',title='Recognize a lower high',intro='A rally can stop below the previous peak. That is different from a sustained recovery.',candles=[[100,104,99,103],[103,106,102,105],[105,105,101,102],[102,104,101,103],[103,103,99,100]],notes=['Price climbs to a $103 close.','The next candle reaches $106. This is the highest point seen so far.','Price retreats. The earlier $106 high is followed by a lower candle.','The bounce reaches $104, below $106. We still need to see what follows.','The next candle drops. This example now confirms a lower turning high of $104 compared with $106.'],question='Why is the bounce not enough to prove the down move is over?',choices=['Every green candle is a complete reversal','The bounce stayed below the earlier high and was followed by another drop','A stock cannot recover after a red candle'],correct=1,explanation='Compare the turning points, not only candle color. A green candle can be part of a bounce inside a declining sequence.'),
    dict(id='retest',title='Read a breakout retest',intro='Here price breaks above $102, then returns to that area. A return is not automatically a successful retest.',candles=[[100,102,99,101],[101,104,101,103],[103,103,101,102],[102,105,102,104]],notes=['Price remains below the watched $102 area.','A completed candle closes at $103, above the level.','Price returns to $102. We cannot yet say whether the level will hold.','The next candle closes at $104. We now have a recovery after the return to the level.'],question='Which information was unavailable at the end of candle three?',choices=['The $102 close of candle three','The earlier breakout','The recovery close of candle four'],correct=2,explanation='The recovery is only known after it happens. A real-time plan must distinguish a possible retest from a later confirmed recovery.'),
])



def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute('CREATE TABLE IF NOT EXISTS progress (user_id TEXT, version TEXT, lesson TEXT, attempts INTEGER NOT NULL, passed INTEGER NOT NULL, updated_at TEXT, PRIMARY KEY(user_id, version, lesson))')
    return conn


@router.get('')
def foundations(request: Request):
    with closing(connect()) as conn:
        progress = {r[0]: dict(attempts=r[1], passed=bool(r[2])) for r in conn.execute('SELECT lesson, attempts, passed FROM progress WHERE user_id=? AND version=?', (request.state.user_id, VERSION))}
    return dict(version=VERSION, source='Illustrative teaching examples, not market data or trading signals', lessons=[{k:v for k,v in lesson.items() if k not in {'correct', 'explanation'}} | {'progress': progress.get(lesson['id'], dict(attempts=0, passed=False))} for lesson in LESSONS])


class Answer(BaseModel):
    lesson: str = Field(max_length=40)
    choice: int = Field(ge=0, le=10)


@router.post('/answer')
def answer(body: Answer, request: Request):
    lesson = next((l for l in LESSONS if l['id'] == body.lesson), None)
    if not lesson or body.choice >= len(lesson['choices']):
        raise HTTPException(422, 'Choose an answer from this lesson.')
    correct = body.choice == lesson['correct']
    with closing(connect()) as conn:
        conn.execute('INSERT INTO progress VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,version,lesson) DO UPDATE SET attempts=progress.attempts+1, passed=MAX(progress.passed, excluded.passed), updated_at=excluded.updated_at', (request.state.user_id, VERSION, body.lesson, 1, int(correct), datetime.now(timezone.utc).isoformat()))
        conn.commit()
    return dict(correct=correct, explanation=lesson['explanation'], version=VERSION)
