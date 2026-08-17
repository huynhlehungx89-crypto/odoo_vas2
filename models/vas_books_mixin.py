# -*- coding: utf-8 -*-
"""Lõi tính đầu kỳ / phát sinh / cuối kỳ — dùng chung Sổ chi tiết + BCĐPS."""
from odoo import models
from odoo.tools.float_utils import float_compare, float_round

# Sentinel: không lọc theo đối tác.
PARTNER_ALL = object()


class VasBooksMixin(models.AbstractModel):
    """Công thức số dư / PS chuẩn TT133 — một chỗ, nhiều báo cáo gọi lại."""

    _name = 'vas.books.mixin'
    _description = 'VAS books balance engine'

    def _books_line_domain(self, company, account, hide_reversed, extra=None):
        domain = [
            ('account_id', '=', account.id),
            ('move_id.company_id', '=', company.id),
        ]
        if hide_reversed:
            # Một nguồn: vas.move.domain_for_amounts (cùng nghĩa ẩn đảo).
            domain += self.env['vas.move'].domain_for_amounts(prefix='move_id')
        else:
            domain.append(('move_id.state', 'in', ('posted', 'reversed')))
        if extra:
            domain += extra
        return domain

    def _books_opening_balance(
        self, company, account, date_from, date_to, hide_reversed, partner=PARTNER_ALL,
        extra=None,
    ):
        """SD đầu khoảng = PS trước date_from + opening trong khoảng."""
        extra = list(extra or [])
        domain_before = self._books_line_domain(company, account, hide_reversed, extra + [
            ('date', '<', date_from),
        ])
        domain_opening = self._books_line_domain(company, account, hide_reversed, extra + [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_id.move_kind', '=', 'opening'),
        ])
        if partner is not PARTNER_ALL:
            if partner:
                domain_before.append(('partner_id', '=', partner.id))
                domain_opening.append(('partner_id', '=', partner.id))
            else:
                domain_before.append(('partner_id', '=', False))
                domain_opening.append(('partner_id', '=', False))
        Line = self.env['vas.move.line']
        bal = sum(l.debit - l.credit for l in Line.search(domain_before))
        bal += sum(l.debit - l.credit for l in Line.search(domain_opening))
        return float_round(bal, precision_digits=2)

    def _books_period_ps(
        self, company, account, date_from, date_to, hide_reversed, partner=PARTNER_ALL,
        extra=None,
    ):
        """(PS Nợ, PS Có) trong khoảng — loại move_kind=opening."""
        extra = list(extra or [])
        domain = self._books_line_domain(company, account, hide_reversed, extra + [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_id.move_kind', '!=', 'opening'),
        ])
        if partner is not PARTNER_ALL:
            if partner:
                domain.append(('partner_id', '=', partner.id))
            else:
                domain.append(('partner_id', '=', False))
        lines = self.env['vas.move.line'].search(domain)
        debit = float_round(sum(lines.mapped('debit')), precision_digits=2)
        credit = float_round(sum(lines.mapped('credit')), precision_digits=2)
        return debit, credit

    def _books_balance_cols(self, balance):
        """Một cột SD Nợ hoặc SD Có."""
        bal = float_round(balance, precision_digits=2)
        if float_compare(bal, 0.0, 2) > 0:
            return bal, 0.0
        if float_compare(bal, 0.0, 2) < 0:
            return 0.0, abs(bal)
        return 0.0, 0.0

    def _books_account_row(
        self, company, account, date_from, date_to, hide_reversed, partner=PARTNER_ALL,
    ):
        """Dict một dòng TK: đầu / PS / cuối (đã tách cột Nợ–Có)."""
        opening = self._books_opening_balance(
            company, account, date_from, date_to, hide_reversed, partner=partner,
        )
        ps_debit, ps_credit = self._books_period_ps(
            company, account, date_from, date_to, hide_reversed, partner=partner,
        )
        closing = float_round(opening + ps_debit - ps_credit, precision_digits=2)
        open_dr, open_cr = self._books_balance_cols(opening)
        close_dr, close_cr = self._books_balance_cols(closing)
        return {
            'account': account,
            'opening': opening,
            'opening_debit': open_dr,
            'opening_credit': open_cr,
            'ps_debit': ps_debit,
            'ps_credit': ps_credit,
            'closing': closing,
            'closing_debit': close_dr,
            'closing_credit': close_cr,
        }
