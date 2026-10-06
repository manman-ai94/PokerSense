"""Manual per-table AA rules; user declarations never become visual truth."""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2


AMOUNTS = ("small_blind", "big_blind", "ante", "straddle_amount",
           "rake_percent", "rake_cap_bb", "minimum_chip")
STACK_RANGE = ("common_effective_stack_min_bb", "common_effective_stack_max_bb")
OPTIONS = {
    "straddle_mode": ("unknown", "none", "mandatory_utg", "optional_explicit_utg"),
    "rake_application": ("unknown", "all_pots", "postflop_only"),
    "rake_rounding": ("unknown", "exact", "floor_to_chip", "ceil_to_chip"),
    "rake_distribution": ("unknown", "proportional_all_pots", "main_pot_first"),
    "insurance": ("unknown", "off", "on"),
    "bomb": ("unknown", "off", "on"),
    "mushroom": ("unknown", "off", "on"),
}


def empty_config():
    return {"table_label": "", "dealt_players": None,
            **dict.fromkeys(AMOUNTS), **dict.fromkeys(OPTIONS, "unknown"),
            **dict.fromkeys(STACK_RANGE)}


def _normalize_config(document, current=None):
    """Only the optional range metadata may be absent in legacy documents."""
    expected = set(empty_config())
    required = expected - set(STACK_RANGE)
    if (not isinstance(document, dict) or not required <= set(document)
            or not set(document) <= expected):
        raise ValueError("AA 规则必须包含完整表单字段")
    defaults = current if current is not None else empty_config()
    return {**document, **{key: document.get(key, defaults[key])
                           for key in STACK_RANGE}}


def _rule_document(document):
    # Preserve the source identity of existing rules, including table_label.
    # Common stack ranges describe usual tables, never this hand's stacks.
    return {key: value for key, value in document.items() if key not in STACK_RANGE}


def revision(document):
    raw = json.dumps(document, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_config(document):
    document = _normalize_config(document)
    label = document["table_label"]
    if not isinstance(label, str) or len(label) > 100:
        raise ValueError("牌桌备注不能超过 100 字")
    count = document["dealt_players"]
    if count is not None and (type(count) is not int or count not in (6, 7, 8)):
        raise ValueError("发牌人数必须为 6、7、8 或未知")
    amounts = {}
    pending = ["dealt_players"] if count is None else []
    for key in AMOUNTS + STACK_RANGE:
        value = document[key]
        if value is None:
            amounts[key] = None
            if key in AMOUNTS and key != "straddle_amount":
                pending.append(key)
            continue
        if not isinstance(value, str) or not value or len(value) > 32:
            raise ValueError(f"{key}: 请使用十进制数字或留空")
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ValueError(f"{key}: 无效金额") from None
        if (not number.is_finite() or number < 0 or number > Decimal('1e12')
                or number.as_tuple().exponent < -8):
            raise ValueError(f"{key}: 金额必须有限、非负，最多八位小数")
        if (key in ("small_blind", "big_blind", "minimum_chip") + STACK_RANGE
                and number <= 0):
            raise ValueError(f"{key}: 必须大于零")
        if key == "rake_percent" and number > 100:
            raise ValueError("抽水百分比必须在 0–100 之间；3 表示 3%")
        amounts[key] = number
    lower, upper = (amounts[key] for key in STACK_RANGE)
    if (lower is None) != (upper is None):
        raise ValueError("常见有效筹码范围请同时填写上下限，或全部留空")
    if lower is not None and lower > upper:
        raise ValueError("常见有效筹码下限不能大于上限")
    for key, choices in OPTIONS.items():
        if document[key] not in choices:
            raise ValueError(f"{key}: 不支持的选项")
        if document[key] == "unknown":
            pending.append(key)
    sb, bb = amounts["small_blind"], amounts["big_blind"]
    if sb is not None and bb is not None and sb >= bb:
        raise ValueError("小盲必须小于大盲")
    mode, amount = document["straddle_mode"], amounts["straddle_amount"]
    if mode == "none" and amount not in (None, Decimal(0)):
        raise ValueError("未启用 straddle 时金额必须为零或留空")
    if mode in ("mandatory_utg", "optional_explicit_utg"):
        if amount is None:
            pending.append("straddle_amount")
        elif bb is not None and amount <= bb:
            raise ValueError("straddle 金额必须大于大盲")
    special = [key for key in ("insurance", "bomb", "mushroom")
               if document[key] == "on"]
    rules = None
    if not pending:
        rules = AARuleProfileV2.from_dict({
            "schema_version": 2, "table_size": count,
            **{key: str(amounts[key]) for key in AMOUNTS
               if key not in ("rake_percent", "straddle_amount")},
            "straddle_amount": str(amount or Decimal(0)),
            "rake_percent": str(amounts["rake_percent"] / Decimal(100)),
            "ante_mode": "none" if amounts["ante"] == 0 else "per_dealt_player",
            **{key: document[key] for key in (
                "straddle_mode", "rake_application", "rake_rounding",
                "rake_distribution")},
            "verification_status": "simulation",
            "source": "manual-table-settings:" + revision(_rule_document(document)),
        })
    return {"document": document, "revision": revision(document),
            "source": "MANUAL_DECLARATION", "pending_fields": pending,
            "unsupported_effects": special,
            "conditional_analysis_ready": rules is not None and not special,
            "simulation_rules": rules.to_dict() if rules and not special else None,
            "visual_verified": False, "live_strategy_eligible": False}


class AATableConfigStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.lock = threading.RLock()
        self.document = empty_config()
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.document = validate_config(raw)["document"]

    def get(self):
        with self.lock:
            return validate_config(json.loads(json.dumps(self.document)))

    def save(self, document, expected_revision):
        with self.lock:
            if expected_revision != revision(self.document):
                raise ValueError("规则已被其他页面修改，请刷新后重试")
            document = _normalize_config(document, current=self.document)
            result = validate_config(document)
            text = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                     dir=self.path.parent,
                                                     delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(text)
                        stream.flush()
                        os.fsync(stream.fileno())
                    temporary.replace(self.path)
                finally:
                    if temporary and temporary.exists():
                        temporary.unlink()
            self.document = json.loads(text)
            return result
