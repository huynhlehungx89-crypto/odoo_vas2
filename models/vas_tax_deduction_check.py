# -*- coding: utf-8 -*-
"""Máy tự kiểm điều kiện khấu trừ GTGT đầu vào trên dòng sổ VAS."""
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import float_compare, float_is_zero, float_round


class VasMoveLine(models.Model):
    _inherit = 'vas.move.line'

    # Ba khái niệm tách rời — không gộp một trường.
    use_purpose = fields.Selection(
        [
            ('taxable_only', 'Dùng riêng hoạt động chịu thuế'),
            ('exempt_only', 'Dùng riêng hoạt động không chịu thuế'),
            ('mixed', 'Dùng chung'),
            ('investment', 'Dự án đầu tư'),
            ('unset', 'Chưa xác định'),
        ],
        string='Mục đích sử dụng',
        default='unset',
        index=True,
        copy=False,
        help='Chỉ hiện/sửa khi công ty bật «Có bán hàng không chịu thuế».',
    )
    deduction_check = fields.Selection(
        [
            ('pass', 'ĐẠT'),
            ('fail', 'KHÔNG ĐẠT'),
            ('wait_due', 'CHỜ ĐẾN HẠN'),
            ('none', 'Không áp dụng'),
        ],
        string='Điều kiện khấu trừ',
        default='none',
        required=True,
        index=True,
        copy=False,
    )
    deduction_rule_id = fields.Many2one(
        'vas.tax.deduction.rule',
        string='Lý do / quy tắc',
        ondelete='restrict',
        index=True,
        copy=False,
    )
    deductible_amount = fields.Monetary(
        string='Số được khấu trừ kỳ này',
        currency_field='company_currency_id',
        default=0.0,
        copy=False,
    )
    deduction_base_untaxed = fields.Monetary(
        string='Giá trị HHĐV (chưa thuế) liên quan',
        currency_field='company_currency_id',
        default=0.0,
        copy=False,
        help='Cơ sở để áp dụng ngưỡng / khấu trừ hạn chế (ô tô).',
    )
    deduction_base_gross = fields.Monetary(
        string='Giá trị HHĐV (đã gồm thuế) liên quan',
        currency_field='company_currency_id',
        default=0.0,
        copy=False,
    )

    def init(self):
        super().init()
        cr = self.env.cr
        cr.execute(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'vas_move_line'
               AND column_name = 'deduction_check'
            """
        )
        if not cr.fetchone():
            return
        cr.execute(
            "ALTER TABLE vas_move_line "
            "ALTER COLUMN deduction_check SET DEFAULT 'none'"
        )
        cr.execute(
            "UPDATE vas_move_line SET deduction_check = 'none' "
            "WHERE deduction_check IS NULL"
        )

    def _vas_is_input_vat_line(self):
        self.ensure_one()
        if not self.tax_id or float_is_zero(self.debit, precision_digits=2):
            return False
        code = (self.account_id.code or '')
        return code == '1331' or code.startswith('1331')

    @api.model
    def _vas_payment_is_non_cash(self, payment):
        """Suy phương thức từ phiếu chi/thu Odoo — không thêm field Odoo."""
        if not payment:
            return False
        journal = payment.journal_id
        if journal and journal.type == 'cash':
            return False
        if journal and journal.type == 'bank':
            return True
        # Phiếu không rõ → không coi là chứng từ không dùng tiền mặt.
        return False

    @api.model
    def _vas_invoice_payment_facts(self, invoice, as_of_date):
        """Trả về dict: paid, has_non_cash, has_cash_only, due_date, residual."""
        due = invoice.invoice_date_due or invoice.invoice_date
        residual = invoice.amount_residual
        paid = float_compare(residual, 0.0, precision_digits=2) <= 0
        payments = invoice._get_reconciled_payments() if hasattr(
            invoice, '_get_reconciled_payments',
        ) else self.env['account.payment']
        has_non_cash = False
        has_cash = False
        for pay in payments:
            if self._vas_payment_is_non_cash(pay):
                has_non_cash = True
            else:
                has_cash = True
        return {
            'paid': paid,
            'has_non_cash': has_non_cash,
            'has_cash': has_cash,
            'due_date': due,
            'residual': residual,
            'amount_total': invoice.amount_total,
            'amount_untaxed': invoice.amount_untaxed,
            'as_of': as_of_date,
        }

    @api.model
    def recompute_input_vat_deduction(self, lines=None, company=None, as_of_date=None):
        """Máy tự kiểm + tính số được khấu trừ. Mặc định ĐẠT khi đủ điều kiện."""
        Line = self.env['vas.move.line']
        Rule = self.env['vas.tax.deduction.rule']
        if lines is None:
            domain = [
                ('tax_id', '!=', False),
                ('debit', '>', 0),
                ('account_id.code', '=like', '1331%'),
                ('move_id.state', '=', 'posted'),
            ]
            if company:
                domain.append(('move_id.company_id', '=', company.id))
            lines = Line.search(domain)
        else:
            lines = lines.filtered(lambda l: l._vas_is_input_vat_line())
        if not lines:
            return 0

        as_of_date = fields.Date.to_date(as_of_date or fields.Date.context_today(self))
        # Nhóm theo hóa đơn nguồn để cộng dồn / trả chậm.
        by_invoice = defaultdict(lambda: self.env['vas.move.line'])
        invoice_cache = {}
        for line in lines:
            move = line.move_id
            inv = False
            if move.source_model == 'account.move' and move.source_res_id:
                inv = self.env['account.move'].browse(move.source_res_id).exists()
            if inv and inv.move_type in ('in_invoice', 'in_refund'):
                by_invoice[inv.id] |= line
                invoice_cache[inv.id] = inv

        # Cộng dồn theo (partner, date) trên hóa đơn cùng ngày.
        day_groups = defaultdict(list)
        for inv in invoice_cache.values():
            key = (inv.partner_id.id, inv.invoice_date or inv.date)
            day_groups[key].append(inv)

        # Luật: từng lần dưới ngưỡng nhưng tổng ≥ ngưỡng → cộng dồn.
        # Hóa đơn đơn lẻ đã ≥ ngưỡng thuộc quy tắc tiền mặt / trả chậm, không gán CUMULATIVE.
        cumulative_hit_ids = set()
        for key, invs in day_groups.items():
            if len(invs) < 2:
                continue
            sample_date = invs[0].invoice_date or invs[0].date or as_of_date
            rule = Rule.find_active('cash_cumulative', sample_date)
            if not rule:
                continue
            thr = rule.amount_threshold
            under = [
                i for i in invs
                if float_compare(i.amount_total, thr, precision_digits=0) < 0
            ]
            if len(under) < 2:
                continue
            total_under = sum(i.amount_total for i in under)
            if float_compare(total_under, thr, precision_digits=0) < 0:
                continue
            for inv in under:
                facts = self._vas_invoice_payment_facts(inv, as_of_date)
                if not facts['has_non_cash']:
                    cumulative_hit_ids.add(inv.id)

        ratio_by_company = {}
        updated = 0
        for line in lines:
            company = line.move_id.company_id
            on_date = line.date or as_of_date
            inv = False
            if line.move_id.source_model == 'account.move' and line.move_id.source_res_id:
                inv = invoice_cache.get(line.move_id.source_res_id) or (
                    self.env['account.move'].browse(line.move_id.source_res_id).exists()
                )

            # Mục đích mặc định khi công ty không bán hàng không chịu thuế.
            purpose = line.use_purpose
            if not company.vas_has_exempt_sales:
                purpose = 'taxable_only'
            elif purpose == 'unset' and not company.vas_has_exempt_sales:
                purpose = 'taxable_only'

            tax_amt = line.debit
            untaxed = line.deduction_base_untaxed
            gross = line.deduction_base_gross
            if inv and float_is_zero(untaxed, precision_digits=2):
                untaxed = inv.amount_untaxed
                gross = inv.amount_total
            if float_is_zero(gross, precision_digits=2):
                gross = untaxed + tax_amt

            check = 'pass'
            rule = Rule.browse()
            deductible = tax_amt

            # --- (d) Ô tô ≤ 09 chỗ (ngoại lệ KD: cờ trên sản phẩm) ---
            car_rule = Rule.find_active('passenger_car', on_date)
            if car_rule and car_rule.match_product_code and inv:
                car_lines = inv.invoice_line_ids.filtered(
                    lambda l: l.product_id.default_code == car_rule.match_product_code
                )
                if car_lines and not any(
                    l.product_id.vas_passenger_car_business_exception for l in car_lines
                ):
                    base = untaxed or sum(car_lines.mapped('price_subtotal'))
                    if float_compare(base, car_rule.amount_threshold, precision_digits=0) > 0:
                        check = 'fail'
                        rule = car_rule
                        ratio = car_rule.amount_threshold / base if base else 0.0
                        deductible = float_round(tax_amt * ratio, precision_digits=0)

            # --- (a)(b)(c) thanh toán ---
            if inv and check == 'pass':
                facts = self._vas_invoice_payment_facts(inv, as_of_date)
                cash_rule = Rule.find_active('cash_payment', on_date)
                cum_rule = Rule.find_active('cash_cumulative', on_date)
                def_rule = Rule.find_active('deferred_payment', on_date)

                thr = cash_rule.amount_threshold if cash_rule else 0.0
                over_thr = float_compare(gross, thr, precision_digits=0) >= 0 if cash_rule else False

                if over_thr and cash_rule:
                    if facts['paid'] and not facts['has_non_cash']:
                        # Trả tiền mặt / không có chứng từ không dùng tiền mặt
                        check = 'fail'
                        rule = cash_rule
                        deductible = 0.0
                    elif not facts['paid'] and def_rule and float_compare(
                        gross, def_rule.amount_threshold, precision_digits=0,
                    ) >= 0:
                        due = facts['due_date']
                        if due and due > as_of_date:
                            check = 'wait_due'
                            rule = def_rule
                            # Vẫn được khấu trừ đến hạn
                            deductible = tax_amt
                        elif due and due <= as_of_date and not facts['has_non_cash']:
                            check = 'fail'
                            rule = def_rule
                            deductible = 0.0
                elif inv.id in cumulative_hit_ids and cum_rule:
                    check = 'fail'
                    rule = cum_rule
                    deductible = 0.0

            # --- Hậu quả điều kiện ---
            if check == 'fail' and rule and rule.consequence == 'deny_all':
                deductible = 0.0
            # deny_excess: đã tính tỷ lệ 1,6 tỷ ở trên; pass/wait_due: giữ nguyên

            # --- Mục đích sử dụng / phân bổ ---
            if purpose == 'exempt_only':
                deductible = 0.0
            elif purpose == 'unset' and company.vas_has_exempt_sales:
                deductible = 0.0
            elif purpose == 'mixed' and company.vas_has_exempt_sales:
                if company.id not in ratio_by_company:
                    ratio_by_company[company.id] = company._vas_gtgt_taxable_revenue_ratio(
                        on_date,
                    )
                ratio_info = ratio_by_company[company.id]
                deductible = float_round(
                    deductible * ratio_info['ratio'], precision_digits=0,
                )

            line.write({
                'use_purpose': (
                    purpose if company.vas_has_exempt_sales else 'taxable_only'
                ),
                'deduction_check': check,
                'deduction_rule_id': rule.id if rule else False,
                'deductible_amount': deductible,
                'deduction_base_untaxed': untaxed,
                'deduction_base_gross': gross,
            })
            updated += 1
        return updated

    def action_open_source_invoice(self):
        self.ensure_one()
        move = self.move_id
        if move.source_model != 'account.move' or not move.source_res_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.source_res_id,
            'view_mode': 'form',
            'target': 'current',
        }
