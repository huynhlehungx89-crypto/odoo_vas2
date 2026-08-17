# -*- coding: utf-8 -*-
"""Do tay B03 ma 10/11/L4 tren W11 — chi doc."""
from collections import defaultdict
from odoo.tools.float_utils import float_round

env['res.company']._vas_w11_ensure_bctc_demo()
company = env['res.company'].search([('name', 'like', 'W11%BCTC')], limit=1)
print('COMPANY', company.id, company.name)

p01 = env['vas.period'].search([
    ('fiscalyear_id.company_id', '=', company.id),
    ('date_start', '=', '2026-01-01'),
], limit=1)
p12 = env['vas.period'].search([
    ('fiscalyear_id.company_id', '=', company.id),
    ('date_start', '=', '2026-12-01'),
], limit=1)
print('PERIOD', p01.name, '->', p12.name)

Snap = env['vas.report.snapshot']
buckets = Snap._books_aggregate_buckets(
    company, p01.date_start, p12.date_end, hide_reversed=True,
)
accounts = env['vas.account'].search([('regime_id', '=', company.vas_regime_id.id)])
acc_by_code = {a.code: a for a in accounts}
ids_by_code = {a.code: a.id for a in accounts}
code_by_id = {a.id: a.code for a in accounts}


def rollup(code):
    acc = acc_by_code.get(code)
    if not acc:
        return None
    return Snap._books_rollup_account(buckets, acc.id)


def debit_detail(code_list):
    id_set = set(ids_by_code[c] for c in code_list if c in ids_by_code)
    rows = []
    total = 0.0
    for (aid, pid), b in buckets.items():
        if aid not in id_set:
            continue
        code = code_by_id.get(aid, str(aid))
        o = b['opening']
        cl = b['closing']
        o_dr = o if o > 0 else 0.0
        c_dr = cl if cl > 0 else 0.0
        contrib = float_round(o_dr - c_dr, 2)
        if abs(o) > 0.005 or abs(cl) > 0.005 or abs(contrib) > 0.005:
            rows.append((code, pid, o, cl, o_dr, c_dr, contrib))
        total = float_round(total + contrib, 2)
    return rows, total


recv = [
    '131', '1361', '1368', '1381', '1386', '1388',
    '133', '1331', '1332', '141',
]
print('=== D1 ROLLUP ===')
for code in recv + ['331']:
    row = rollup(code)
    if not row:
        print('ROLLUP', code, 'NO_ACC')
        continue
    print(
        'ROLLUP', code,
        'open=', row['opening'], 'close=', row['closing'],
        'open-close=', float_round(row['opening'] - row['closing'], 2),
        'o_dr=', row['opening_debit'], 'c_dr=', row['closing_debit'],
        'o_cr=', row['opening_credit'], 'c_cr=', row['closing_credit'],
    )

print('=== D1 PARTNER debit_bal_delta ===')
rows, tot = debit_detail(recv)
rows2, tot2 = debit_detail(['331'])
byc = defaultdict(float)
for code, pid, o, cl, o_dr, c_dr, contrib in rows + rows2:
    byc[code] += contrib
    print(
        'P', code, 'pid=', pid,
        'open_net=', o, 'close_net=', cl,
        'o_dr=', o_dr, 'c_dr=', c_dr, 'contrib=', contrib,
    )
print('=== D1 BY CODE ===')
for c in sorted(byc):
    print(c, float_round(byc[c], 2))
print('TOTAL_10', float_round(tot + tot2, 2))

print('=== D2 ROLLUP ===')
inv = ['151', '152', '153', '154', '155', '156', '157']
for code in inv:
    row = rollup(code)
    if not row:
        print('ROLLUP', code, 'NO_ACC_OR_EMPTY')
        continue
    print(
        'ROLLUP', code,
        'open=', row['opening'], 'close=', row['closing'],
        'open-close=', float_round(row['opening'] - row['closing'], 2),
    )
rows11, tot11 = debit_detail(inv)
byc11 = defaultdict(float)
for code, pid, o, cl, o_dr, c_dr, contrib in rows11:
    byc11[code] += contrib
    print('P', code, 'pid=', pid, 'open=', o, 'close=', cl, 'contrib=', contrib)
print('=== D2 BY CODE ===')
for c in sorted(byc11):
    print(c, float_round(byc11[c], 2))
print('TOTAL_11', tot11)

b01a = Snap.generate_b01a(company, p01, p12, hide_reversed=True)
b01 = {l.code: l for l in b01a.line_ids}
print('=== B01a ===')
for code in ['110', '131', '132', '133', '134', '135', '136', '141', '142']:
    l = b01.get(code)
    if l:
        print(
            'B01a', code, 'o=', l.amount_opening, 'c=', l.amount_closing,
            'c-o=', float_round(l.amount_closing - l.amount_opening, 2),
        )

print('=== D5 CASH ===')
Line = env['vas.move.line']
Move = env['vas.move']
domain_base = [
    ('company_id', '=', company.id),
    ('date', '>=', p01.date_start),
    ('date', '<=', p12.date_end),
    ('move_id.move_kind', '!=', 'opening'),
] + Move.domain_for_amounts(prefix='move_id')
cash_codes = ['111', '1111', '1112', '112', '1121', '1122']
cash_ids = [ids_by_code[c] for c in cash_codes if c in ids_by_code]
rows_g = Line.read_group(
    domain_base + [('account_id', 'in', cash_ids)],
    ['debit:sum', 'credit:sum', 'account_id'],
    ['account_id'],
    lazy=False,
)
gross_d = gross_c = 0.0
for r in rows_g:
    aid = r['account_id'][0]
    print('CASH_PS', code_by_id[aid], 'd=', r.get('debit') or 0, 'c=', r.get('credit') or 0)
    gross_d += r.get('debit') or 0.0
    gross_c += r.get('credit') or 0.0
print('GROSS_D', gross_d, 'GROSS_C', gross_c, 'NET_D-C', float_round(gross_d - gross_c, 2))

# Internal: moves where every non-zero line is on cash accounts
moves = Line.search(domain_base + [('account_id', 'in', cash_ids)]).mapped('move_id')
internal_d = 0.0
n_internal = 0
for mv in moves:
    money = mv.line_ids.filtered(lambda l: l.debit or l.credit)
    if money and all(l.account_id.id in cash_ids for l in money):
        n_internal += 1
        internal_d += sum(money.mapped('debit'))
print('INTERNAL_MOVES', n_internal, 'INTERNAL_DEBIT_SUM', float_round(internal_d, 2))
print(
    'NET_EXCL_INTERNAL_SIDES',
    float_round((gross_d - internal_d) - (gross_c - internal_d), 2),
)

b03 = Snap.generate_b03(company, p01, p12, hide_reversed=True)
by = {l.code: l.amount_closing for l in b03.line_ids}
print('B03', {k: by[k] for k in (
    '01', '02', '09', '10', '11', '12', '13', '14',
    '20', '30', '40', '50', '60', '61', '70',
)})
cash_delta = float_round(b01['110'].amount_closing - b01['110'].amount_opening, 2)
print('CASH_DELTA_110', cash_delta)
print('B03_50', by['50'], 'B03_20', by['20'], 'B03_30', by['30'], 'B03_40', by['40'])
print('B03_20+30+40', float_round(by['20'] + by['30'] + by['40'], 2))
print('L4_GAP cash_delta - 50 - 61', float_round(cash_delta - by['50'] - by['61'], 2))
