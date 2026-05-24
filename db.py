"""
SQLite persistence for quiz state, backed by aiosqlite.

Quizzes are stored so an in-flight quiz survives a process restart (deploy,
Railway OOM, crash) and so completed quizzes accumulate as history for future
per-user stats. The schema keeps every quiz (surrogate `id` key) and marks it
`active` or `completed`; a partial unique index enforces the bot's invariant
of at most one *active* quiz per channel while leaving completed rows for
history.

The store is decoupled from the bot's in-memory QUIZ_STATE shape: it returns
naturalized rows (datetimes parsed, options as lists, answers nested by int
user_id), and app.py maps those onto its runtime dict.
"""
import json
from datetime import datetime
from typing import List, Optional

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quizzes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id       INTEGER NOT NULL,
    guild_id         INTEGER,
    initiator_id     INTEGER NOT NULL,
    topic            TEXT,
    started_at       TEXT NOT NULL,
    end_time         TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active'
);

-- At most one active quiz per channel; completed quizzes are unconstrained
-- so history accumulates and a channel can start a new quiz after one ends.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_quiz_per_channel
    ON quizzes (channel_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS quiz_questions (
    quiz_id      INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    question     TEXT NOT NULL,
    options_json TEXT NOT NULL,
    answer       TEXT NOT NULL,
    explain      TEXT NOT NULL,
    topic        TEXT,
    page         INTEGER,
    PRIMARY KEY (quiz_id, position)
);

CREATE TABLE IF NOT EXISTS quiz_answers (
    quiz_id      INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    choice       TEXT NOT NULL,
    answered_at  TEXT NOT NULL,
    PRIMARY KEY (quiz_id, position, user_id)
);
"""


class QuizStore:
    """Async wrapper around the quiz persistence tables."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    @classmethod
    async def connect(cls, path: str) -> "QuizStore":
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        # WAL improves concurrent read/write behavior; foreign_keys must be
        # enabled per-connection for the ON DELETE CASCADE to fire.
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.executescript(_SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def create_quiz(
        self,
        *,
        channel_id: int,
        guild_id: Optional[int],
        initiator_id: int,
        topic: str,
        started_at: datetime,
        end_time: datetime,
        duration_minutes: int,
        questions: List[dict],
    ) -> int:
        """
        Insert a new active quiz and its (shuffled) questions in one
        transaction. `questions` are stored in list order as positions 0..N-1.
        Returns the new quiz id. Raises if the channel already has an active
        quiz (enforced by the partial unique index).
        """
        cur = await self._conn.execute(
            """
            INSERT INTO quizzes
                (channel_id, guild_id, initiator_id, topic, started_at,
                 end_time, duration_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                channel_id,
                guild_id,
                initiator_id,
                topic,
                started_at.isoformat(),
                end_time.isoformat(),
                duration_minutes,
            ),
        )
        quiz_id = cur.lastrowid
        await self._conn.executemany(
            """
            INSERT INTO quiz_questions
                (quiz_id, position, question, options_json, answer, explain, topic, page)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    quiz_id,
                    position,
                    q["q"],
                    json.dumps(q["options"]),
                    q["answer"],
                    q["explain"],
                    q.get("topic"),
                    q.get("page"),
                )
                for position, q in enumerate(questions)
            ],
        )
        await self._conn.commit()
        return quiz_id

    async def record_answer(
        self,
        *,
        quiz_id: int,
        position: int,
        user_id: int,
        choice: str,
        answered_at: datetime,
    ) -> None:
        """Upsert a user's answer to one question (re-answering overwrites)."""
        await self._conn.execute(
            """
            INSERT INTO quiz_answers (quiz_id, position, user_id, choice, answered_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (quiz_id, position, user_id)
            DO UPDATE SET choice = excluded.choice, answered_at = excluded.answered_at
            """,
            (quiz_id, position, user_id, choice, answered_at.isoformat()),
        )
        await self._conn.commit()

    async def complete_quiz(self, quiz_id: int) -> None:
        """Mark a quiz completed so it no longer counts as active."""
        await self._conn.execute(
            "UPDATE quizzes SET status = 'completed' WHERE id = ?", (quiz_id,)
        )
        await self._conn.commit()

    async def load_active_quizzes(self) -> List[dict]:
        """
        Return all active quizzes with their questions and recorded answers,
        for rehydrating QUIZ_STATE on startup. Each dict:

            {
              quiz_id, channel_id, guild_id, initiator_id, topic,
              started_at: datetime, end_time: datetime, duration_minutes,
              questions: [{q, options, answer, explain, topic, page}, ...],  # by position
              answers: {user_id(int): {position(int): choice}},
            }
        """
        quiz_rows = await self._fetchall(
            "SELECT * FROM quizzes WHERE status = 'active'"
        )
        result = []
        for qr in quiz_rows:
            quiz_id = qr["id"]
            question_rows = await self._fetchall(
                "SELECT * FROM quiz_questions WHERE quiz_id = ? ORDER BY position",
                (quiz_id,),
            )
            questions = [
                {
                    "q": r["question"],
                    "options": json.loads(r["options_json"]),
                    "answer": r["answer"],
                    "explain": r["explain"],
                    "topic": r["topic"],
                    "page": r["page"],
                }
                for r in question_rows
            ]
            answer_rows = await self._fetchall(
                "SELECT position, user_id, choice FROM quiz_answers WHERE quiz_id = ?",
                (quiz_id,),
            )
            answers: dict = {}
            for r in answer_rows:
                answers.setdefault(r["user_id"], {})[r["position"]] = r["choice"]

            result.append(
                {
                    "quiz_id": quiz_id,
                    "channel_id": qr["channel_id"],
                    "guild_id": qr["guild_id"],
                    "initiator_id": qr["initiator_id"],
                    "topic": qr["topic"],
                    "started_at": datetime.fromisoformat(qr["started_at"]),
                    "end_time": datetime.fromisoformat(qr["end_time"]),
                    "duration_minutes": qr["duration_minutes"],
                    "questions": questions,
                    "answers": answers,
                }
            )
        return result

    async def _fetchall(self, sql: str, params: tuple = ()) -> List[aiosqlite.Row]:
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows
