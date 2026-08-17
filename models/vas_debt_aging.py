# -*- coding: utf-8 -*-
"""Tuổi nợ Công nợ — phương án B (sáu cột, cột cuối = chưa xác định hạn).

Số dư đối tác / tổng = Σ Nợ − Σ Có (hoặc ngược lại với phải trả) trên sổ VAS
cùng công thức F01 (`domain_for_amounts`, tới ngày cuối kỳ).

Không đoán hạn: chỉ dùng ``account.move.invoice_date_due`` khi
``vas.move.source_model == 'account.move'``. Các nguồn khác → cột unknown.
"""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.tools.float_utils import float_is_zero, float_round


AGING_BUCKET_KEYS = (
    'not_due',
    'd1_30',
    'd31_60',
    'd61_90',
    'd90_plus',
    'unknown',
)

AR_PREFIXES = ('131',)
AP_PREFIXES = ('331',)


class VasDebtAging(models.AbstractModel):
    _name = 'vas.debt.aging'
    _description = 'VAS tuổi nợ công nợ (6 cột — phương án B)'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _aging_bucket_meta(self):
        return [
            {
                'key': 'not_due',
                'label': _('Chưa đến hạn'),
            },
            {
                'key': 'd1_30',
                'label': _('Quá hạn 1–30 ngày'),
            },
            {
                'key': 'd31_60',
                'label': _('Quá hạn 31–60 ngày'),
            },
            {
                'key': 'd61_90',
                'label': _('Quá hạn 61–90 ngày'),
            },
            {
                'key': 'd90_plus',
                'label': _('Quá hạn trên 90 ngày'),
            },
            {
                'key': 'unknown',
                'label': _('Chưa xác định hạn'),
                'hint': _(
                    'Khoản chưa gắn được hóa đơn có hạn thanh toán '
                    '(thu/chi, bút tay, đầu kỳ, doanh thu tách ngày giao, bù trừ…).'
                ),
            },
        ]

    @api.model
    def _empty_buckets(self):
        return {k: 0.0 for k in AGING_BUCKET_KEYS}

    @api.model
    def _code_matches(self, code, prefixes):
        code = code or ''
        for pfx in prefixes:
            if code == pfx or code.startswith(pfx):
                return True
        return False

    @api.model
    def _account_ids_for_prefixes(self, company, prefixes):
        regime = company.vas_regime_id
        if not regime:
            return []
        accounts = self.env['vas.account'].search([('regime_id', '=', regime.id)])
        return [
            a.id for a in accounts
            if self._code_matches(a.code, prefixes)
        ]

    @api.model
    def _resolve_invoice_due(self, move, am_cache):
        """Trả ``date`` hạn thanh toán hoặc False — không đoán."""
        if not move or move.source_model != 'account.move' or not move.source_res_id:
            return False
        res_id = move.source_res_id
        if res_id not in am_cache:
            am = self.env['account.move'].browse(res_id).exists()
            am_cache[res_id] = am.invoice_date_due if am else False
        return am_cache[res_id]

    @api.model
    def _bucket_for_due(self, due, as_of):
        if not due or not as_of:
            return 'unknown'
        delta = (as_of - due).days
        if delta <= 0:
            return 'not_due'
        if delta <= 30:
            return 'd1_30'
        if delta <= 60:
            return 'd31_60'
        if delta <= 90:
            return 'd61_90'
        return 'd90_plus'

    # ------------------------------------------------------------------
    # Core compute
    # ------------------------------------------------------------------

    @api.model
    def get_aging_report(self, period_id, kind='ar'):
        """Báo cáo tuổi nợ một chiều.

        ``kind``: ``'ar'`` (131, dư Nợ) hoặc ``'ap'`` (331, dư Có).
        Mốc xếp cột = ``period.date_end``.
        """
        period = self.env['vas.period'].browse(period_id)
        if not period.exists():
            return {'error': _('Không tìm thấy kỳ kế toán.'), 'rows': []}
        company = period.fiscalyear_id.company_id or self.env.company
        as_of = period.date_end
        prefixes = AR_PREFIXES if kind == 'ar' else AP_PREFIXES
        side = 'debit' if kind == 'ar' else 'credit'
        account_ids = self._account_ids_for_prefixes(company, prefixes)
        if not account_ids:
            return {
                'error': False,
                'kind': kind,
                'period_id': period.id,
                'period_name': period.name or '',
                'as_of': fields.Date.to_string(as_of),
                'company_id': company.id,
                'currency_id': (company.currency_id or self.env.ref('base.VND')).id,
                'columns': self._aging_bucket_meta(),
                'rows': [],
                'totals': self._empty_buckets() | {'total': 0.0},
                'f01_total': 0.0,
                'match_f01': True,
                'unknown_hint': self._aging_bucket_meta()[-1]['hint'],
            }

        Line = self.env['vas.move.line']
        domain = [
            ('company_id', '=', company.id),
            ('account_id', 'in', account_ids),
            ('date', '<=', as_of),
        ] + self.env['vas.move'].domain_for_amounts(prefix='move_id')

        lines = Line.search(domain)
        am_cache = {}
        by_partner = defaultdict(lambda: self._empty_buckets())
        partner_names = {}

        for line in lines:
            pid = line.partner_id.id if line.partner_id else False
            if line.partner_id:
                partner_names[pid] = line.partner_id.display_name
            else:
                partner_names[False] = _('(Không có đối tác)')
            if side == 'debit':
                amt = float_round((line.debit or 0.0) - (line.credit or 0.0), 2)
            else:
                amt = float_round((line.credit or 0.0) - (line.debit or 0.0), 2)
            if float_is_zero(amt, 2):
                continue
            due = self._resolve_invoice_due(line.move_id, am_cache)
            bucket = self._bucket_for_due(due, as_of)
            by_partner[pid][bucket] = float_round(
                by_partner[pid][bucket] + amt, 2,
            )

        rows = []
        totals = self._empty_buckets()
        grand = 0.0
        for pid, buckets in by_partner.items():
            total = float_round(sum(buckets[k] for k in AGING_BUCKET_KEYS), 2)
            if float_is_zero(total, 2) and all(
                float_is_zero(buckets[k], 2) for k in AGING_BUCKET_KEYS
            ):
                continue
            row = {
                'partner_id': pid or False,
                'partner_name': partner_names.get(pid, ''),
                'total': total,
            }
            row.update({k: buckets[k] for k in AGING_BUCKET_KEYS})
            rows.append(row)
            grand = float_round(grand + total, 2)
            for k in AGING_BUCKET_KEYS:
                totals[k] = float_round(totals[k] + buckets[k], 2)

        rows.sort(key=lambda r: (
            0 if r['partner_id'] else 1,
            (r['partner_name'] or '').lower(),
            r['partner_id'] or 0,
        ))

        # Đối chiếu F01 cùng kỳ (FY start → date_end)
        fy = period.fiscalyear_id
        f01_total = self._f01_closing_for_prefixes(
            company, fy.date_from, as_of, prefixes, side,
        )
        match_f01 = float_is_zero(grand - f01_total, 2)

        return {
            'error': False,
            'kind': kind,
            'kind_label': (
                _('Phải thu khách hàng (131)') if kind == 'ar'
                else _('Phải trả người bán (331)')
            ),
            'period_id': period.id,
            'period_name': period.name or '',
            'as_of': fields.Date.to_string(as_of),
            'company_id': company.id,
            'currency_id': (company.currency_id or self.env.ref('base.VND')).id,
            'columns': self._aging_bucket_meta(),
            'rows': rows,
            'totals': {**totals, 'total': grand},
            'f01_total': f01_total,
            'match_f01': match_f01,
            'unknown_hint': self._aging_bucket_meta()[-1]['hint'],
        }

    @api.model
    def _f01_closing_for_prefixes(self, company, date_from, date_to, prefixes, side):
        """Cùng công thức dashboard / F01 — Σ closing theo tiền tố."""
        Agg = self.env['vas.books.aggregate']
        buckets = Agg._books_aggregate_buckets(
            company, date_from, date_to, hide_reversed=True,
        )
        accounts = {
            a.id: a
            for a in self.env['vas.account'].search([
                ('regime_id', '=', company.vas_regime_id.id),
            ])
        } if company.vas_regime_id else {}
        seen = set()
        total = 0.0
        for (acc_id, _pid), _b in buckets.items():
            if acc_id in seen:
                continue
            acc = accounts.get(acc_id)
            if not acc or not self._code_matches(acc.code, prefixes):
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
    def get_aging_compare(self, period_id, kind='ar'):
        """Đối chiếu máy: Σ 6 cột = tổng đối tác = F01."""
        data = self.get_aging_report(period_id, kind)
        if data.get('error'):
            return {'ok': False, 'error': data['error']}
        col_sum = float_round(
            sum(data['totals'][k] for k in AGING_BUCKET_KEYS), 2,
        )
        partner_sum = data['totals']['total']
        f01 = data['f01_total']
        ok = (
            float_is_zero(col_sum - partner_sum, 2)
            and float_is_zero(partner_sum - f01, 2)
        )
        return {
            'ok': ok,
            'columns_total': col_sum,
            'partners_total': partner_sum,
            'f01_total': f01,
            'unknown_total': data['totals']['unknown'],
            'kind': kind,
        }

    @api.model
    def action_open_aging(self, kind='ar'):
        """Client action — tuổi nợ AR hoặc AP."""
        label = (
            _('Tuổi nợ phải thu (131)') if kind == 'ar'
            else _('Tuổi nợ phải trả (331)')
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'vas_debt_aging',
            'name': label,
            'context': {'vas_aging_kind': kind},
        }
