"""《一页纸打法》定生死的那一条“至今的命中数和战绩”（v3.3 第六节）。

规则键 = 编号 + 条文哈希（第七节：哈希不同不合并统计）。哈希和场次包
（``tools/session_package.py`` 的 ``versions``）同一个算法：规则的文字加上这一页
每个数字、手牌表和读法；页上改了任何一个数，每条规则都从 0 记起。

* 之前各场：每场停下录像出体检单时，``tools/flywheel_session.py`` 把这一场按规则键
  的命中次数、它定过的手和这些手的大盲记进账本（``PokerSense_private/flywheel/
  ledger.jsonl`` 每行的 ``rules``）。窗口每次开始时读一次（这一场录完再出的体检单，
  下次开始才算进来，所以不会和本场的数重复）。
* 本场：窗口自己数，每个决策只算一次。

只是记录：单条规则的盈亏量不出好坏（第七节），不拿它改规则；建议本身一点不变。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..data_paths import private_root

LEDGER = ("flywheel", "ledger.jsonl")


def digest(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def canonical(value):
    """A constant of the page as JSON that does not depend on set order."""
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(
            value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(canonical(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value if isinstance(value, (int, float, str, type(None))) else repr(value)


def page_numbers(page):
    """sha256 (16 hex) of every number, hand table and reading of the page
    (its upper-case constants)."""
    numbers = {name: canonical(value) for name, value in sorted(vars(page).items())
               if name.isupper() and not name.startswith("_")
               and isinstance(value, (int, float, str, dict, list, tuple, set,
                                      frozenset))}
    return digest(json.dumps(numbers, ensure_ascii=False, sort_keys=True))


def rule_keys(page=None):
    """{编号: "编号#哈希"} for every rule of the page."""
    if page is None:
        from ..scoreboard import plain_policy as page
    numbers = page_numbers(page)
    return {rule: f"{rule}#{digest(text + chr(10) + numbers)}"
            for rule, text in page.RULES.items()}


def default_ledger():
    return private_root().joinpath(*LEDGER)


def read_ledger(path):
    """The ledger's sessions; a line that does not read is left out."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def totals(rows):
    """{rule key: {"hits", "hands", "bb", "sessions"}} added up over the
    sessions of the ledger."""
    out = {}
    for row in rows:
        rules = row.get("rules")
        if not isinstance(rules, dict):
            continue
        for key, item in rules.items():
            if not isinstance(item, dict):
                continue
            total = out.setdefault(key, {"hits": 0, "hands": 0, "bb": 0.0,
                                         "sessions": 0})
            total["hits"] += int(item.get("hits") or 0)
            total["hands"] += int(item.get("hands") or 0)
            total["bb"] = round(total["bb"] + float(item.get("bb") or 0), 2)
            total["sessions"] += 1
    return out


class RuleRecord:
    """Puts the deciding rule's key and record on each answer of the page
    (``plain.rule_key``, ``plain.record``); fed the advice of every frame."""

    def __init__(self, ledger=None, keys=None):
        self._ledger = Path(ledger) if ledger is not None else None
        self._keys = keys
        self.reset()

    def reset(self):
        """A new observation: the ledger is read again, this session counts from 0."""
        self._before, self._session, self._shown = None, {}, {}

    def keys(self):
        if self._keys is None:
            self._keys = rule_keys()
        return self._keys

    def before(self):
        if self._before is None:
            path = self._ledger if self._ledger is not None else default_ledger()
            self._before = totals(read_ledger(path))
        return self._before

    def __call__(self, advice):
        if (not isinstance(advice, dict) or advice.get("status") != "ready"
                or advice.get("kind") != "plain"):
            return advice
        page = advice.get("plain")
        if not isinstance(page, dict):
            return advice
        key = self.keys().get(page.get("rule"))
        if key is None:
            return advice
        decision = (advice.get("hand_id"), advice.get("decision"), key)
        record = self._shown.get(decision)
        if record is None:
            self._session[key] = self._session.get(key, 0) + 1
            before = self.before().get(key) or {}
            record = {"hits": before.get("hits", 0) + self._session[key],
                      "session": self._session[key],
                      "sessions": before.get("sessions", 0),
                      "hands": before.get("hands", 0), "bb": before.get("bb", 0.0)}
            self._shown[decision] = record
        return {**advice, "plain": {**page, "rule_key": key, "record": dict(record)}}


__all__ = ["RuleRecord", "default_ledger", "read_ledger", "rule_keys", "totals"]
