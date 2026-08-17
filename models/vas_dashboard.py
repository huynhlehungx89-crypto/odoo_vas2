# -*- coding: utf-8 -*-
"""Tổng quan (dashboard) — số liệu chỉ từ sổ VAS, công thức F01 qua books.aggregate."""
from collections import defaultdict
from datetime import datetime

from odoo import _, api, fields, models
from odoo.tools.float_utils import float_is_zero, float_round


# Tiền / tồn / công nợ — tiền tố mã TK (lá F01; cha tổng hợp bằng Σ lá).
DASH_CASH_PREFIXES = ('111',)
DASH_BANK_PREFIXES = ('112',)
DASH_AR_PREFIXES = ('131',)
DASH_AP_PREFIXES = ('331',)
DASH_INV_PREFIXES = ('152', '153', '155', '156')

# Doanh thu / chi phí theo account_type (cột PS/closing F01).
DASH_INCOME_TYPES = ('income', 'other_income')
DASH_EXPENSE_TYPES = ('expense', 'other_expense')


class VasDashboard(models.AbstractModel):
    _name = 'vas.dashboard'
    _description = 'VAS Tổng quan dashboard'

    # ------------------------------------------------------------------
    # Period helpers
    # ------------------------------------------------------------------

    @api.model
    def _dashboard_company(self):
        return self.env.company

    @api.model
    def _period_has_books(self, period, company):
        """Kỳ có ít nhất một dòng sổ VAS (sau domain_for_amounts)."""
        period.ensure_one()
        domain = [
            ('move_id.company_id', '=', company.id),
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
        ] + self.env['vas.move'].domain_for_amounts(prefix='move_id')
        return bool(self.env['vas.move.line'].search(domain, limit=1))

    @api.model
    def _default_period(self, company):
        """Kỳ gần nhất ĐÃ CÓ SỐ LIỆU (không phải kỳ lịch hiện tại)."""
        Period = self.env['vas.period']
        periods = Period.search([
            ('fiscalyear_id.company_id', '=', company.id),
        ], order='date_end desc, id desc')
        for period in periods:
            if self._period_has_books(period, company):
                return period
        return Period.browse()

    @api.model
    def get_period_options(self):
        """Danh sách kỳ + kỳ mặc định cho bộ chọn."""
        company = self._dashboard_company()
        periods = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', company.id),
        ], order='date_start desc, id desc')
        default = self._default_period(company)
        return {
            'company_id': company.id,
            'company_name': company.name or '',
            'currency_id': (company.currency_id or self.env.ref('base.VND')).id,
            'default_period_id': default.id if default else False,
            'periods': [{
                'id': p.id,
                'name': p.name or '',
                'date_start': fields.Date.to_string(p.date_start) if p.date_start else False,
                'date_end': fields.Date.to_string(p.date_end) if p.date_end else False,
                'state': p.state,
                'has_data': self._period_has_books(p, company),
            } for p in periods],
        }

    # ------------------------------------------------------------------
    # F01-compatible rollup (một lần _books_aggregate_buckets)
    # ------------------------------------------------------------------

    @api.model
    def _code_matches_prefixes(self, code, prefixes):
        code = code or ''
        for pfx in prefixes:
            if code == pfx or code.startswith(pfx):
                return True
        return False

    @api.model
    def _accounts_by_id(self, company):
        regime = company.vas_regime_id
        if not regime:
            return {}
        accounts = self.env['vas.account'].search([('regime_id', '=', regime.id)])
        return {a.id: a for a in accounts}

    @api.model
    def _sum_closing_for_prefixes(self, buckets, accounts_by_id, prefixes, side='debit'):
        """Σ closing_* F01 cho mọi TK khớp tiền tố (lá có bucket).

        ``side='debit'`` → closing_debit − closing_credit (tài sản / phải thu).
        ``side='credit'`` → closing_credit − closing_debit (phải trả).
        """
        Agg = self.env['vas.books.aggregate']
        seen = set()
        total = 0.0
        for (acc_id, _pid), _b in buckets.items():
            if acc_id in seen:
                continue
            acc = accounts_by_id.get(acc_id)
            if not acc or not self._code_matches_prefixes(acc.code, prefixes):
                continue
            seen.add(acc_id)
            row = Agg._books_rollup_account(buckets, acc_id)
            if side == 'credit':
                total = float_round(
                    total + row['closing_credit'] - row['closing_debit'], 2,
                )
            else:
                total = float_round(
                    total + row['closing_debit'] - row['closing_credit'], 2,
                )
        return total

    @api.model
    def _sum_ps_for_prefixes(self, buckets, accounts_by_id, prefixes):
        """Σ ps_debit / ps_credit F01 cho tiền tố (dùng dòng tiền)."""
        Agg = self.env['vas.books.aggregate']
        seen = set()
        pd = pc = 0.0
        for (acc_id, _pid), _b in buckets.items():
            if acc_id in seen:
                continue
            acc = accounts_by_id.get(acc_id)
            if not acc or not self._code_matches_prefixes(acc.code, prefixes):
                continue
            seen.add(acc_id)
            row = Agg._books_rollup_account(buckets, acc_id)
            pd = float_round(pd + row['ps_debit'], 2)
            pc = float_round(pc + row['ps_credit'], 2)
        return pd, pc

    @api.model
    def _sum_ps_by_account_types(self, buckets, accounts_by_id, types, nature='credit'):
        """Σ PS theo account_type — cột PS F01 (nature credit = DT, debit = CP)."""
        Agg = self.env['vas.books.aggregate']
        seen = set()
        total = 0.0
        for (acc_id, _pid), _b in buckets.items():
            if acc_id in seen:
                continue
            acc = accounts_by_id.get(acc_id)
            if not acc or acc.account_type not in types:
                continue
            seen.add(acc_id)
            row = Agg._books_rollup_account(buckets, acc_id)
            if nature == 'credit':
                net = float_round(row['ps_credit'] - row['ps_debit'], 2)
            else:
                net = float_round(row['ps_debit'] - row['ps_credit'], 2)
            total = float_round(total + net, 2)
        return total

    # ------------------------------------------------------------------
    # Tiles
    # ------------------------------------------------------------------

    @api.model
    def _tile_finance(self, buckets, accounts_by_id):
        cash = self._sum_closing_for_prefixes(
            buckets, accounts_by_id, DASH_CASH_PREFIXES, 'debit',
        )
        bank = self._sum_closing_for_prefixes(
            buckets, accounts_by_id, DASH_BANK_PREFIXES, 'debit',
        )
        inv = self._sum_closing_for_prefixes(
            buckets, accounts_by_id, DASH_INV_PREFIXES, 'debit',
        )
        total_cash = float_round(cash + bank, 2)
        has = not all(float_is_zero(v, 2) for v in (cash, bank, inv))
        if not has:
            return {
                'key': 'finance',
                'title': _('Tình hình tài chính'),
                'empty': True,
                'empty_message': _(
                    'Chưa có số dư tiền / tồn kho trên sổ VAS trong kỳ này.'
                ),
                'pending': [],
            }
        return {
            'key': 'finance',
            'title': _('Tình hình tài chính'),
            'empty': False,
            'cash_111': cash,
            'bank_112': bank,
            'total_cash': total_cash,
            'inventory': inv,
            'pending': [],
        }

    @api.model
    def _tile_ar_ap(self, buckets, accounts_by_id, kind, period=None):
        if kind == 'ar':
            key, title, prefixes, side = (
                'ar', _('Phải thu khách hàng (131)'), DASH_AR_PREFIXES, 'debit',
            )
        else:
            key, title, prefixes, side = (
                'ap', _('Phải trả người bán (331)'), DASH_AP_PREFIXES, 'credit',
            )
        total = self._sum_closing_for_prefixes(
            buckets, accounts_by_id, prefixes, side,
        )
        aging = False
        if period:
            aging = self.env['vas.debt.aging'].get_aging_report(period.id, kind)
            if aging.get('error'):
                aging = False
        if float_is_zero(total, 2):
            return {
                'key': key,
                'title': title,
                'empty': True,
                'empty_message': _(
                    'Chưa có số dư %(label)s trên sổ VAS trong kỳ này.',
                    label=title,
                ),
                'pending': [],
                'aging_available': False,
            }
        tile = {
            'key': key,
            'title': title,
            'empty': False,
            'total': total,
            'aging_available': bool(aging),
            'pending': [],
        }
        if aging:
            tile['aging'] = {
                'columns': aging['columns'],
                'buckets': {
                    k: aging['totals'][k]
                    for k in (
                        'not_due', 'd1_30', 'd31_60',
                        'd61_90', 'd90_plus', 'unknown',
                    )
                },
                'unknown_hint': aging.get('unknown_hint') or '',
                'match_f01': aging.get('match_f01'),
            }
            overdue = float_round(
                sum(aging['totals'][k] for k in (
                    'd1_30', 'd31_60', 'd61_90', 'd90_plus',
                )), 2,
            )
            tile['overdue'] = overdue
            tile['current'] = aging['totals']['not_due']
            tile['unknown'] = aging['totals']['unknown']
        return tile

    @api.model
    def _tile_pnl(self, company, period, accounts_by_id, hide_reversed=True):
        fy = period.fiscalyear_id
        if not fy:
            return {
                'key': 'pnl',
                'title': _('Doanh thu · Chi phí · Lợi nhuận'),
                'empty': True,
                'empty_message': _('Kỳ chưa gắn năm tài chính.'),
                'pending': [],
            }
        Agg = self.env['vas.books.aggregate']
        ytd_buckets = Agg._books_aggregate_buckets(
            company, fy.date_from, period.date_end, hide_reversed,
        )
        revenue = self._sum_ps_by_account_types(
            ytd_buckets, accounts_by_id, DASH_INCOME_TYPES, 'credit',
        )
        expense = self._sum_ps_by_account_types(
            ytd_buckets, accounts_by_id, DASH_EXPENSE_TYPES, 'debit',
        )
        profit = float_round(revenue - expense, 2)

        months = self._monthly_pnl_series(
            company, fy, period, accounts_by_id, hide_reversed,
        )
        if all(float_is_zero(v, 2) for v in (revenue, expense)):
            return {
                'key': 'pnl',
                'title': _('Doanh thu · Chi phí · Lợi nhuận'),
                'empty': True,
                'empty_message': _(
                    'Chưa có phát sinh doanh thu/chi phí lũy kế từ đầu năm '
                    'tới kỳ đang chọn (cột PS F01).'
                ),
                'months': months,
                'pending': [],
            }
        return {
            'key': 'pnl',
            'title': _('Doanh thu · Chi phí · Lợi nhuận'),
            'empty': False,
            'revenue': revenue,
            'expense': expense,
            'profit': profit,
            'months': months,
            'pending': [],
        }

    @api.model
    def _monthly_ps_by_account(self, company, date_from, date_to, hide_reversed=True):
        """PS theo (account_id, 'YYYY-MM') — cùng điều kiện PS của aggregate."""
        Line = self.env['vas.move.line']
        base = [('company_id', '=', company.id)]
        if hide_reversed:
            base += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            base.append(('move_id.state', 'in', ('posted', 'reversed')))
        domain = base + [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_id.move_kind', '!=', 'opening'),
        ]
        # Odoo 19: formatted_read_group (read_group date:month lỗi aggregate method).
        groups = Line.formatted_read_group(
            domain,
            groupby=['account_id', 'date:month'],
            aggregates=['debit:sum', 'credit:sum'],
        )
        out = defaultdict(lambda: [0.0, 0.0])
        for row in groups:
            acc = row.get('account_id')
            acc_id = acc[0] if isinstance(acc, (list, tuple)) else acc
            if not acc_id:
                continue
            month_val = row.get('date:month')
            # ('2097-02-01', 'February 2097') hoặc date
            if isinstance(month_val, (list, tuple)) and month_val:
                raw = month_val[0]
            else:
                raw = month_val
            if not raw:
                continue
            if isinstance(raw, str):
                mk = raw[:7]
            else:
                mk = fields.Date.to_string(raw)[:7]
            out[(acc_id, mk)][0] = float_round(
                out[(acc_id, mk)][0] + (row.get('debit:sum') or 0.0), 2,
            )
            out[(acc_id, mk)][1] = float_round(
                out[(acc_id, mk)][1] + (row.get('credit:sum') or 0.0), 2,
            )
        return out

    @api.model
    def _monthly_pnl_series(self, company, fy, period, accounts_by_id, hide_reversed):
        """Biểu đồ cột theo tháng — PS từng kỳ (cùng điều kiện PS aggregate)."""
        periods = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', period.date_end),
        ], order='date_start, id')
        if not periods:
            return []
        ps_map = self._monthly_ps_by_account(
            company, fy.date_from, period.date_end, hide_reversed,
        )
        income_ids = {
            aid for aid, acc in accounts_by_id.items()
            if acc.account_type in DASH_INCOME_TYPES
        }
        expense_ids = {
            aid for aid, acc in accounts_by_id.items()
            if acc.account_type in DASH_EXPENSE_TYPES
        }
        series = []
        for p in periods:
            mk = fields.Date.to_string(p.date_start)[:7]
            rev = exp = 0.0
            for aid in income_ids:
                pd, pc = ps_map.get((aid, mk), (0.0, 0.0))
                rev = float_round(rev + pc - pd, 2)
            for aid in expense_ids:
                pd, pc = ps_map.get((aid, mk), (0.0, 0.0))
                exp = float_round(exp + pd - pc, 2)
            series.append({
                'label': p.name or '',
                'revenue': rev,
                'expense': exp,
                'profit': float_round(rev - exp, 2),
            })
        return series

    @api.model
    def _monthly_cash_series(self, company, period, accounts_by_id, hide_reversed):
        fy = period.fiscalyear_id
        if not fy:
            return []
        periods = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', period.date_end),
        ], order='date_start, id')
        if not periods:
            return []
        prefixes = DASH_CASH_PREFIXES + DASH_BANK_PREFIXES
        cash_ids = {
            aid for aid, acc in accounts_by_id.items()
            if self._code_matches_prefixes(acc.code, prefixes)
        }
        ps_map = self._monthly_ps_by_account(
            company, fy.date_from, period.date_end, hide_reversed,
        )
        series = []
        for p in periods:
            mk = fields.Date.to_string(p.date_start)[:7]
            pd = pc = 0.0
            for aid in cash_ids:
                d, c = ps_map.get((aid, mk), (0.0, 0.0))
                pd = float_round(pd + d, 2)
                pc = float_round(pc + c, 2)
            series.append({
                'label': p.name or '',
                'inflow': pd,
                'outflow': pc,
            })
        return series

    @api.model
    def _tile_todos(self, company, period):
        Closing = self.env['vas.closing.entry']
        closing_done = bool(Closing.search([
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('date_to', '=', period.date_end),
        ], limit=1))
        period_locked = period.state == 'closed'
        Snap = self.env['vas.report.snapshot']
        fs_done = bool(Snap.search([
            ('company_id', '=', company.id),
            ('period_to_id', '=', period.id),
            ('form_code', 'in', (
                'B01a-DNN', 'B02-DNN', 'B03-DNN', 'B09-DNN',
            )),
        ], limit=1))
        items = [
            {
                'key': 'closing',
                'label': _('Kết chuyển cuối kỳ'),
                'done': closing_done,
                'status_label': _('Đã xong') if closing_done else _('Chưa xong'),
            },
            {
                'key': 'lock',
                'label': _('Khóa sổ kỳ'),
                'done': period_locked,
                'status_label': _('Đã xong') if period_locked else _('Chưa xong'),
            },
            {
                'key': 'fs',
                'label': _('Lập báo cáo tài chính'),
                'done': fs_done,
                'status_label': _('Đã xong') if fs_done else _('Chưa xong'),
            },
        ]
        return {
            'key': 'todos',
            'title': _('Cần làm kỳ này'),
            'empty': False,
            'items': items,
            'open_general_action_xmlid': 'connecta_vas.action_vas_ops_workflow_general',
            'pending': [],
        }

    @api.model
    def _tile_cashflow(self, buckets, accounts_by_id, company, period, hide_reversed):
        prefixes = DASH_CASH_PREFIXES + DASH_BANK_PREFIXES
        pd, pc = self._sum_ps_for_prefixes(buckets, accounts_by_id, prefixes)
        closing = self._sum_closing_for_prefixes(
            buckets, accounts_by_id, prefixes, 'debit',
        )
        months = self._monthly_cash_series(
            company, period, accounts_by_id, hide_reversed,
        )
        if all(float_is_zero(v, 2) for v in (pd, pc, closing)):
            return {
                'key': 'cashflow',
                'title': _('Dòng tiền'),
                'empty': True,
                'empty_message': _(
                    'Chưa có phát sinh / số dư quỹ 111·112 trên sổ VAS trong kỳ.'
                ),
                'months': months,
                'pending': [],
            }
        return {
            'key': 'cashflow',
            'title': _('Dòng tiền'),
            'empty': False,
            'inflow': pd,
            'outflow': pc,
            'closing': closing,
            'months': months,
            'pending': [],
        }

    @api.model
    def _tile_cost_structure(self, company, period, hide_reversed=True):
        """Cơ cấu chi phí theo khoản mục — gom dòng sổ có cost_item_id."""
        domain = [
            ('move_id.company_id', '=', company.id),
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
            ('cost_item_id', '!=', False),
            ('account_id.account_type', 'in', list(DASH_EXPENSE_TYPES)),
        ]
        if hide_reversed:
            domain += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            domain.append(('move_id.state', 'in', ('posted', 'reversed')))
        rows = self.env['vas.move.line'].read_group(
            domain,
            ['debit:sum', 'credit:sum', 'cost_item_id'],
            ['cost_item_id'],
            lazy=False,
        )
        slices = []
        for row in rows:
            item = row.get('cost_item_id')
            if not item:
                continue
            deb = row.get('debit') or 0.0
            cre = row.get('credit') or 0.0
            amount = float_round(deb - cre, 2)
            if float_is_zero(amount, 2):
                continue
            slices.append({
                'id': item[0],
                'label': item[1],
                'amount': amount,
            })
        slices.sort(key=lambda s: abs(s['amount']), reverse=True)
        if not slices:
            return {
                'key': 'cost_structure',
                'title': _('Cơ cấu chi phí'),
                'empty': True,
                'empty_message': _(
                    'Chưa có dòng chi phí gắn khoản mục (cost_item) trong kỳ.'
                ),
                'slices': [],
                'pending': [_(
                    'Cơ cấu chi phí chỉ hiện khi dòng sổ VAS có gắn khoản mục chi phí.'
                )],
            }
        return {
            'key': 'cost_structure',
            'title': _('Cơ cấu chi phí'),
            'empty': False,
            'slices': slices,
            'pending': [],
        }

    # ------------------------------------------------------------------
    # Public API (OWL)
    # ------------------------------------------------------------------

    @api.model
    def get_dashboard_data(self, period_id=None, hide_reversed=True):
        """Payload đủ 7 ô + meta. Số dư BS = một lần ``_books_aggregate_buckets``."""
        t0 = datetime.utcnow()
        company = self._dashboard_company()
        if not company.vas_regime_id:
            return {
                'error': _('Công ty chưa chọn chế độ kế toán VAS.'),
                'elapsed_ms': 0,
            }
        Period = self.env['vas.period']
        if period_id:
            period = Period.browse(period_id)
            if not period.exists() or period.fiscalyear_id.company_id != company:
                return {
                    'error': _('Kỳ không thuộc công ty đang chọn.'),
                    'elapsed_ms': 0,
                }
        else:
            period = self._default_period(company)
        if not period:
            elapsed = (datetime.utcnow() - t0).total_seconds()
            empty_msg = _('Chưa có kỳ kế toán có số liệu trên sổ VAS.')
            return {
                'error': False,
                'period_id': False,
                'period_name': '',
                'elapsed_ms': int(elapsed * 1000),
                'elapsed_seconds': round(elapsed, 3),
                'tiles': {
                    'finance': {
                        'key': 'finance', 'title': _('Tình hình tài chính'),
                        'empty': True, 'empty_message': empty_msg, 'pending': [],
                    },
                    'ar': {
                        'key': 'ar', 'title': _('Phải thu khách hàng (131)'),
                        'empty': True, 'empty_message': empty_msg, 'pending': [],
                    },
                    'ap': {
                        'key': 'ap', 'title': _('Phải trả người bán (331)'),
                        'empty': True, 'empty_message': empty_msg, 'pending': [],
                    },
                    'pnl': {
                        'key': 'pnl',
                        'title': _('Doanh thu · Chi phí · Lợi nhuận'),
                        'empty': True, 'empty_message': empty_msg,
                        'months': [], 'pending': [],
                    },
                    'todos': {
                        'key': 'todos', 'title': _('Cần làm kỳ này'),
                        'empty': True, 'empty_message': empty_msg,
                        'items': [], 'pending': [],
                    },
                    'cashflow': {
                        'key': 'cashflow', 'title': _('Dòng tiền'),
                        'empty': True, 'empty_message': empty_msg,
                        'months': [], 'pending': [],
                    },
                    'cost_structure': {
                        'key': 'cost_structure', 'title': _('Cơ cấu chi phí'),
                        'empty': True, 'empty_message': empty_msg,
                        'slices': [], 'pending': [],
                    },
                },
            }

        accounts_by_id = self._accounts_by_id(company)
        Agg = self.env['vas.books.aggregate']
        # MỘT lần gom sổ theo TK (+ đối tác) cho kỳ đang chọn — ô BS / AR / AP / CF.
        buckets = Agg._books_aggregate_buckets(
            company, period.date_start, period.date_end, hide_reversed,
        )

        tiles = {
            'finance': self._tile_finance(buckets, accounts_by_id),
            'ar': self._tile_ar_ap(buckets, accounts_by_id, 'ar', period),
            'ap': self._tile_ar_ap(buckets, accounts_by_id, 'ap', period),
            'pnl': self._tile_pnl(
                company, period, accounts_by_id, hide_reversed,
            ),
            'todos': self._tile_todos(company, period),
            'cashflow': self._tile_cashflow(
                buckets, accounts_by_id, company, period, hide_reversed,
            ),
            'cost_structure': self._tile_cost_structure(
                company, period, hide_reversed,
            ),
        }
        elapsed = (datetime.utcnow() - t0).total_seconds()
        return {
            'error': False,
            'company_id': company.id,
            'company_name': company.name or '',
            'currency_id': (company.currency_id or self.env.ref('base.VND')).id,
            'period_id': period.id,
            'period_name': period.name or '',
            'date_from': fields.Date.to_string(period.date_start),
            'date_to': fields.Date.to_string(period.date_end),
            'hide_reversed': bool(hide_reversed),
            'elapsed_ms': int(elapsed * 1000),
            'elapsed_seconds': round(elapsed, 3),
            'tiles': tiles,
        }

    @api.model
    def action_open_general_workflow(self):
        """Nút trong ô Cần làm → quy trình Tổng hợp (giữ breadcrumb)."""
        action = self.env.ref(
            'connecta_vas.action_vas_ops_workflow_general',
        ).sudo().read()[0]
        action['context'] = dict(self.env.context, vas_ops_group_code='general')
        return action

    @api.model
    def get_f01_compare_amounts(self, period_id, hide_reversed=True):
        """Đối chiếu máy: số dashboard vs Σ lá F01 cùng kỳ (cùng công thức)."""
        company = self._dashboard_company()
        period = self.env['vas.period'].browse(period_id)
        if not period.exists():
            return {}
        dash = self.get_dashboard_data(period_id, hide_reversed)
        wiz = self.env['vas.trial.balance.wizard'].create({
            'company_id': company.id,
            'period_from_id': period.id,
            'period_to_id': period.id,
            'hide_reversed': bool(hide_reversed),
        })
        account_rows, _totals = wiz._compute_dataset()

        def sum_f01(prefixes, side='debit'):
            total = 0.0
            for row in account_rows:
                code = row.get('account_code') or ''
                if not self._code_matches_prefixes(code, prefixes):
                    continue
                if side == 'credit':
                    total = float_round(
                        total
                        + (row.get('closing_credit') or 0.0)
                        - (row.get('closing_debit') or 0.0),
                        2,
                    )
                else:
                    total = float_round(
                        total
                        + (row.get('closing_debit') or 0.0)
                        - (row.get('closing_credit') or 0.0),
                        2,
                    )
            return total

        fin = dash['tiles']['finance']
        ar = dash['tiles']['ar']
        ap = dash['tiles']['ap']
        return {
            'period_id': period.id,
            'period_name': period.name,
            'rows': [
                {
                    'label': 'Tiền mặt (111)',
                    'dashboard': fin.get('cash_111', 0.0) if not fin.get('empty') else 0.0,
                    'f01': sum_f01(DASH_CASH_PREFIXES, 'debit'),
                },
                {
                    'label': 'Tiền gửi (112)',
                    'dashboard': fin.get('bank_112', 0.0) if not fin.get('empty') else 0.0,
                    'f01': sum_f01(DASH_BANK_PREFIXES, 'debit'),
                },
                {
                    'label': 'Phải thu (131)',
                    'dashboard': ar.get('total', 0.0) if not ar.get('empty') else 0.0,
                    'f01': sum_f01(DASH_AR_PREFIXES, 'debit'),
                },
                {
                    'label': 'Phải trả (331)',
                    'dashboard': ap.get('total', 0.0) if not ap.get('empty') else 0.0,
                    'f01': sum_f01(DASH_AP_PREFIXES, 'credit'),
                },
                {
                    'label': 'Tồn kho (152+153+155+156)',
                    'dashboard': fin.get('inventory', 0.0) if not fin.get('empty') else 0.0,
                    'f01': sum_f01(DASH_INV_PREFIXES, 'debit'),
                },
            ],
        }
