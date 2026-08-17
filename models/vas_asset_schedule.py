# -*- coding: utf-8 -*-
"""Builders lịch khấu hao / phân bổ theo TT45 Phụ lục 2."""
import calendar
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tools.float_utils import float_round


def _days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def _month_bounds(year, month):
    dim = _days_in_month(year, month)
    return date(year, month, 1), date(year, month, dim), dim


def _round_dong(amount):
    return float_round(amount, precision_digits=0)


def _iter_month_slots(date_start, n_months):
    """Yield (seq, year, month, date_from, date_to, days_in_month, days_used)."""
    cur = date_start
    for seq in range(1, n_months + 1):
        y, m = cur.year, cur.month
        first, last, dim = _month_bounds(y, m)
        if seq == 1:
            date_from = date_start
            days_used = dim - date_start.day + 1
        else:
            date_from = first
            days_used = dim
        yield seq, y, m, date_from, last, dim, days_used
        cur = last + relativedelta(days=1)


def build_straight_line(original_value, useful_life_years, date_start, prorata=True):
    """TT45 PL2.I — đường thẳng. Kỳ cuối = NG − Σ trước."""
    original_value = float(original_value)
    years = float(useful_life_years)
    n_months = int(round(years * 12))
    if n_months < 1:
        return []
    monthly = (original_value / years) / 12.0
    slots = list(_iter_month_slots(date_start, n_months))
    amounts = []
    for seq, _y, _m, _dfrom, _dto, dim, days_used in slots:
        if seq == n_months:
            break
        if seq == 1 and prorata and days_used < dim:
            amounts.append(_round_dong(monthly * days_used / dim))
        else:
            amounts.append(_round_dong(monthly))
    amounts.append(original_value - sum(amounts))

    lines = []
    accum = 0.0
    for (seq, _y, _m, dfrom, dto, dim, days_used), amount in zip(slots, amounts):
        accum += amount
        lines.append({
            'sequence': seq,
            'date_from': dfrom,
            'date_to': dto,
            'date': dto,
            'days': days_used if (seq == 1 and prorata) else dim,
            'days_in_month': dim,
            'amount': amount,
            'accumulated': accum,
            'remaining': original_value - accum,
            'is_last': seq == n_months,
            'state': 'planned',
        })
    return lines


def build_prepaid_equal(original_value, duration_months, date_start):
    """Phân bổ 242: chia đều N kỳ, KHÔNG prorata ngày."""
    original_value = float(original_value)
    n = int(duration_months)
    if n < 1:
        return []
    base = _round_dong(original_value / n)
    amounts = [base] * (n - 1)
    amounts.append(original_value - sum(amounts))
    slots = list(_iter_month_slots(date_start.replace(day=1), n))
    lines = []
    accum = 0.0
    for (seq, y, m, _dfrom, _dto, dim, _days_used), amount in zip(slots, amounts):
        first, last, dim = _month_bounds(y, m)
        accum += amount
        lines.append({
            'sequence': seq,
            'date_from': first,
            'date_to': last,
            'date': last,
            'days': dim,
            'days_in_month': dim,
            'amount': amount,
            'accumulated': accum,
            'remaining': original_value - accum,
            'is_last': seq == n,
            'state': 'planned',
        })
    return lines


def build_declining(original_value, useful_life_years, date_start, prorata=True):
    """TT45 PL2.II — số dư giảm dần có điều chỉnh, rồi chia tháng."""
    original_value = float(original_value)
    years = int(useful_life_years)
    if years < 1:
        return []
    straight_rate = 1.0 / years
    coeff = 1.5 if years <= 4 else 2.0
    fast_rate = straight_rate * coeff

    annuals = []
    residual = original_value
    for y in range(1, years + 1):
        years_left = years - y + 1
        declining_amt = residual * fast_rate
        even_amt = residual / years_left
        if y == years or declining_amt <= even_amt + 1e-9:
            annual = residual if y == years else even_amt
        else:
            annual = declining_amt
        annuals.append(annual)
        residual -= annual
    annuals[-1] = original_value - sum(annuals[:-1])

    n_months = years * 12
    slots = list(_iter_month_slots(date_start, n_months))
    monthly_amounts = []
    for yi, annual in enumerate(annuals):
        if yi == 0 and prorata:
            dim = slots[0][5]
            days_used = slots[0][6]
            if days_used < dim:
                first_amt = _round_dong((annual / 12.0) * days_used / dim)
                rest = annual - first_amt
                base2 = _round_dong(rest / 11.0) if rest else 0.0
                mid = [base2] * 10
                mid.append(rest - sum(mid))
                monthly_amounts.extend([first_amt] + mid)
                continue
        base = _round_dong(annual / 12.0)
        parts = [base] * 11
        parts.append(annual - sum(parts))
        monthly_amounts.extend(parts)

    if monthly_amounts:
        monthly_amounts[-1] = original_value - sum(monthly_amounts[:-1])

    lines = []
    accum = 0.0
    for (seq, _y, _m, dfrom, dto, dim, days_used), amount in zip(slots, monthly_amounts):
        accum += amount
        lines.append({
            'sequence': seq,
            'date_from': dfrom,
            'date_to': dto,
            'date': dto,
            'days': days_used if (seq == 1 and prorata) else dim,
            'days_in_month': dim,
            'amount': amount,
            'accumulated': accum,
            'remaining': original_value - accum,
            'is_last': seq == n_months,
            'state': 'planned',
        })
    return lines


def units_rate(original_value, units_total):
    return float(original_value) / float(units_total) if units_total else 0.0


def build_units_period_amount(original_value, units_total, units_qty, residual, is_last=False):
    """TT45 PL2.III — mức một kỳ; kỳ cuối (is_last) dồn dư."""
    residual = float(residual)
    if is_last:
        return residual
    rate = units_rate(original_value, units_total)
    amount = _round_dong(float(units_qty) * rate)
    if amount > residual:
        amount = residual
    return amount
