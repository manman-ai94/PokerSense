"""Card and price reading diagnosis on a window log, totals and patterns only.

Writes no card identities: each reading two ways is described by how the
readings differ (same rank? same colour? how many cards changed), when
(street, before or after your first button, after you folded), and how long
each was held. Run from a checkout of the PokerSense branch or main that has
``desktop/aa_card_check.py``:

    PYTHONPATH=src:. .venv/bin/python du_card_diag.py <frames.jsonl> [...] > out.json
"""
import gzip
import json
import statistics
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path[:0] = ['src', '.']
import tools.plain_live_report as rep  # noqa: E402
from poker_engine.desktop.aa_card_check import AACardCheck  # noqa: E402

RED = set('hd')


def rows_of(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as f:
        return [r for r in map(json.loads, f) if 'fields' in r]


def checked(rows):
    check = AACardCheck()
    out = []
    for row in rows:
        f = row['fields']
        hand = (f.get('actions_v1') or {}).get('hand_id')
        hero, board, report = check.observe(f.get('hero'), f.get('board'), hand,
                                            row.get('pts_seconds'))
        out.append({**row, 'fields': {**f, 'hero': hero, 'board': board}})
    return out


def q(values, share):
    values = sorted(v for v in values if v is not None)
    return round(values[min(len(values) - 1, int(share * len(values)))], 3) if values else None


def runs(series):
    """[(value, start, seconds, frames)] runs of one reading held >= 2 frames."""
    out, last = [], object()
    for value, t in series:
        if value != last:
            out.append([value, t, t, 1])
            last = value
        else:
            out[-1][2] = t
            out[-1][3] += 1
    return [(v, s, e - s, n) for v, s, e, n in out if v is not None and n >= 2]


def describe(a, b):
    """How reading b differs from a (one card, or two cards as 'Xx Yy')."""
    a, b = a.split(), b.split()
    changed = list(zip(sorted(set(a) - set(b)), sorted(set(b) - set(a))))
    return {'cards_changed': len(changed),
            'rank_same': all(x[0] == y[0] for x, y in changed),
            'colour_same': all((x[1] in RED) == (y[1] in RED) for x, y in changed)}


def conflicts(rows):
    """Hands with hero cards or a board slot read two ways (steady >= 2 frames)."""
    by_hand = {}
    for i, r in enumerate(rows):
        h = (r['fields'].get('actions_v1') or {}).get('hand_id')
        by_hand.setdefault(h, []).append(i)
    found = []
    for hand, idx in by_hand.items():
        if hand is None:
            continue
        t0 = rows[idx[0]]['pts_seconds']
        button = next((rows[i]['pts_seconds'] for i in idx
                       if (rows[i]['fields'].get('hero_controls') or {}).get('visible')), None)
        folded = next((rows[i]['pts_seconds'] for i in idx
                       if (rows[i]['fields'].get('participants') or {}).get('4') == 'folded'), None)
        series = {'hero': [(' '.join(sorted(rows[i]['fields']['hero'])) if rows[i]['fields'].get('hero') and all(rows[i]['fields']['hero']) else None,
                            rows[i]['pts_seconds']) for i in idx]}
        for s in range(5):
            series['board%d' % s] = [(((rows[i]['fields'].get('board') or [None] * 5) + [None] * 5)[s], rows[i]['pts_seconds']) for i in idx]
        streets = {rows[i]['pts_seconds']: rows[i]['fields'].get('street') for i in idx}
        for what, ser in series.items():
            held = runs(ser)
            distinct = []
            for v, s, d, n in held:
                if v not in [x[0] for x in distinct]:
                    distinct.append((v, s, d, n))
            if len(distinct) < 2:
                continue
            first = distinct[0][0]
            items = []
            for v, s, d, n in held:
                items.append({'reading': 'first' if v == first else 'other',
                              'since_hand_start': round(s - t0, 2),
                              'since_first_button': None if button is None else round(s - button, 2),
                              'after_you_folded': folded is not None and s >= folded,
                              'street': streets.get(s), 'seconds': round(d, 2), 'frames': n,
                              **({} if v == first else describe(first, v))})
            found.append({'what': 'hero' if what == 'hero' else 'board', 'slot': what[-1] if what != 'hero' else None,
                          'runs': items})
    return found


def amount(v):
    try:
        return Decimal(str(v)) if v is not None else None
    except InvalidOperation:
        return None


def turn_reading(rows):
    turns = [t for t in rep.turns(rows) if t['seconds'] >= 1.0]
    out = {'turns': len(turns), 'hero_not_in_2s': 0, 'price_not_in_2s': 0,
           'hero_first_read_after_button': [], 'price_first_read_after_button': [],
           'hero_why': Counter(), 'price_reasons_first_2s': Counter(),
           'price_buttons_when_slow': Counter(), 'price_slow_eventually_equals_chips': Counter()}
    for turn in turns:
        idx = turn['indexes']
        res = rep.reading_turn(turn, rows)
        fs = [rows[i]['fields'] for i in idx]
        ts = [rows[i]['pts_seconds'] - turn['start'] for i in idx]
        hero_t = next((t for f, t in zip(fs, ts) if f.get('hero') and all(f['hero'])), None)
        price_t = next((t for f, t in zip(fs, ts) if (f.get('hero_controls') or {}).get('call_amount') is not None), None)
        out['hero_first_read_after_button'].append(hero_t)
        out['price_first_read_after_button'].append(price_t)
        if not res['hero_cards'][0]:
            out['hero_not_in_2s'] += 1
            before = [rows[i]['fields'].get('hero') for i in range(max(0, idx[0] - 10), idx[0])]
            out['hero_why'][('read_before_button' if any(before) else 'not_read_before_button')
                            + ('_then_read_at_%.1fs' % hero_t if hero_t is not None and hero_t < 6 else '_unread_in_turn' if hero_t is None else '_late')] += 1
        if not res['price'][0]:
            out['price_not_in_2s'] += 1
            for f, t in zip(fs, ts):
                if t <= 2.0:
                    c = f.get('hero_controls') or {}
                    out['price_reasons_first_2s'][c.get('reason')] += 1
                    out['price_buttons_when_slow'][c.get('button')] += 1
            w = fs[0].get('street_wagers') or {}
            vals = {s: amount(v) for s, v in w.items()}
            top = max((v for s, v in vals.items() if s != '4' and v is not None), default=None)
            chips = None if top is None else top - (vals.get('4') or 0)
            got = next((amount(f['hero_controls'].get('call_amount')) for f in fs
                        if (f.get('hero_controls') or {}).get('call_amount') is not None), None)
            out['price_slow_eventually_equals_chips'][
                'never_read' if got is None else 'no_chips_price' if chips is None
                else 'equal' if got == chips else 'different'] += 1
    for key in ('hero_first_read_after_button', 'price_first_read_after_button'):
        v = out[key]
        out[key] = {'p50': q(v, .5), 'p75': q(v, .75), 'p90': q(v, .9), 'never': sum(x is None for x in v)}
    for key in list(out):
        if isinstance(out[key], Counter):
            out[key] = dict(out[key].most_common())
    return out


def hero_deal_time(rows):
    """Seconds from a hand's first frame with your card faces located (any
    reading, even unconfirmed is not logged) -- approximated by the first frame
    with both cards read -- to that: from the hand start."""
    by_hand = {}
    for r in rows:
        h = (r['fields'].get('actions_v1') or {}).get('hand_id')
        by_hand.setdefault(h, []).append(r)
    gaps = []
    for h, rs in by_hand.items():
        t0 = rs[0]['pts_seconds']
        t = next((r['pts_seconds'] for r in rs if r['fields'].get('hero') and all(r['fields']['hero'])), None)
        if t is not None:
            gaps.append(t - t0)
    return {'hands': len(by_hand), 'p50': q(gaps, .5), 'p90': q(gaps, .9)}


def main(paths):
    out = {}
    for path in paths:
        rows = rows_of(path)
        steps = sorted(b['pts_seconds'] - a['pts_seconds'] for a, b in zip(rows, rows[1:]))
        after = checked(rows)
        before_c, after_c = conflicts(rows), conflicts(after)
        hands = len({(r['fields'].get('actions_v1') or {}).get('hand_id') for r in rows})
        out[Path(path).parent.name or Path(path).name] = {
            'rows': len(rows), 'hands': hands,
            'frame_seconds': {'p50': q(steps, .5), 'p90': q(steps, .9)},
            'conflicts_before': {'hero_hands': sum(c['what'] == 'hero' for c in before_c),
                                 'board_slots': sum(c['what'] == 'board' for c in before_c)},
            'conflicts_after_check': {'hero_hands': sum(c['what'] == 'hero' for c in after_c),
                                      'board_slots': sum(c['what'] == 'board' for c in after_c)},
            'conflict_patterns_before': before_c,
            'conflict_patterns_after': after_c,
            'turn_reading_before': turn_reading(rows),
            'turn_reading_after': turn_reading(after),
            'hand_start_to_hero_read': hero_deal_time(rows),
        }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main(sys.argv[1:])
