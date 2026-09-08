# -*- coding: utf-8 -*-
import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

EVENT_MOVE_KIND = {
    'sale_invoice': 'sale_inv',
    'sale_delivery': 'cogs',
    'payment_in': 'payment',
    'purchase_receipt': 'stock',
    'purchase_invoice': 'purchase_inv',
    'payment_out': 'payment',
    'advance_employee': 'payment',
    'cash_transfer': 'payment',
    'deposit': 'payment',
    'payment_discount': 'expense',  # distinct from R17/R18 payment move on same source
    'sale_refund': 'refund',
    'sale_discount': 'refund',
    'sale_return_stock': 'stock',
    # R08 phải có ô riêng: hóa đơn TRỘN hàng + dịch vụ sinh hai bút toán trên cùng
    # một account.move, mà _already_synced khóa theo (model, id, move_kind). Dùng
    # chung 'purchase_inv' với R07 thì rule chạy sau bị bỏ qua.
    'purchase_service': 'expense',
    'purchase_refund': 'refund',
    'purchase_discount': 'refund',
    'purchase_return_stock': 'stock',
    'purchase_price_adjust': 'purchase_inv',
    'stock_issue_production': 'stock',
    'advance_settlement': 'expense',
    'advance_refund': 'payment',
    'employee_debt_payment': 'payment',
    # R25/R26: kind riêng — không đụng R06 (stock) / R08 (expense) trên cùng nguồn.
    'landed_cost_adjust': 'landed',
    'purchase_landed_tax': 'landed_tax',
    'import_vat_payment': 'import_vat_payment',
    'goods_in_transit': 'goods_in_transit',
            'forex_realized': 'forex',
            'pos_sale': 'pos_sale',
            'pos_cogs': 'pos_cogs',
            'pos_refund': 'pos_refund',
            'pos_session_cash': 'pos_session_cash',
            'pos_session_bank': 'pos_session_bank',
            'pos_cash_shortage': 'pos_cash_diff',
    'pos_cash_overage': 'pos_cash_diff',
    'pos_cash_io': 'pos_cash_io',
    'stock_scrap': 'scrap',
}

# hr.expense đã duyệt — mọi trạng thái từ "duyệt" trở đi đều là chi phí thật.
ADVANCE_SETTLED_STATES = ('approved', 'posted', 'in_payment', 'paid')

EVENT_JOURNAL_CODE = {
    'sale_invoice': 'BH',
    'sale_delivery': 'KHO',
    'payment_in': 'THU',
    'purchase_receipt': 'KHO',
    'purchase_invoice': 'MH',
    'payment_out': 'THU',
    'advance_employee': 'THU',
    'cash_transfer': 'THU',
    'deposit': 'THU',
    'payment_discount': 'THU',
    'sale_refund': 'BH',
    'sale_discount': 'BH',
    'sale_return_stock': 'KHO',
    'purchase_service': 'MH',
    'purchase_refund': 'MH',
    'purchase_discount': 'MH',
    'purchase_return_stock': 'KHO',
    'purchase_price_adjust': 'MH',
    'stock_issue_production': 'KHO',
    'advance_settlement': 'TH',
    'advance_refund': 'THU',
    'employee_debt_payment': 'THU',
    'landed_cost_adjust': 'KHO',
    'purchase_landed_tax': 'MH',
    'import_vat_payment': 'THU',
    'goods_in_transit': 'MH',
    'forex_realized': 'THU',
    'pos_sale': 'BH',
    'pos_cogs': 'KHO',
    'pos_refund': 'BH',
    'pos_session_cash': 'THU',
    'pos_session_bank': 'NH',
    'pos_cash_shortage': 'THU',
    'pos_cash_overage': 'THU',
    'pos_cash_io': 'THU',
    'stock_scrap': 'KHO',
}

SELECTOR_FIXED_CODE = {
    'partner_receivable': '131',
    'partner_payable': '331',
    'tax_output': '33311',
    'tax_input': '1331',
    'tax_import_vat_payable': '33312',
    'goods_in_transit': '151',
    'cash': '111',
    'bank': '112',
    'employee_advance': '141',
    'employee_payable': '334',
    'finance_income': '515',
    'finance_expense': '635',
}

# Trục 1 "chọn tài khoản động": tài khoản suy được từ sản phẩm.
# selector → (trường trên vas.account.map, mã mặc định khi chưa khai)
PRODUCT_ACCOUNT_SELECTOR = {
    'product_inventory': ('stock_account_id', '156'),
    'product_revenue': ('revenue_account_id', '5111'),
    'product_cogs': ('cogs_account_id', '632'),
    # TRỤC 2 — mặc định 6422 "chi phí quản lý doanh nghiệp" của TT133.
    # Không dùng 641/642 của TT200; TT133 chỉ có 154 / 6421 / 6422.
    'product_expense': ('expense_account_id', '6422'),
}


class VasSync(models.AbstractModel):
    _name = 'vas.sync'
    _description = 'Đồng bộ sự kiện Odoo → bút toán VAS'

    # -------------------------------------------------------------------------
    # Public entry points
    # -------------------------------------------------------------------------

    @api.model
    def cron_sync_all(self):
        companies = self.env['res.company'].search([('vas_regime_id', '!=', False)])
        for company in companies:
            try:
                self.sync_company(company)
            except Exception:
                _logger.exception('VAS sync failed for company %s', company.display_name)

    @api.model
    def sync_company(self, company=None, date_from=None, date_to=None):
        company = company or self.env.company
        if not company.vas_regime_id:
            raise UserError(_(
                "Company %(company)s has no VAS regime. Set it in Settings before syncing.",
                company=company.display_name,
            ))
        if not company.vas_start_date:
            raise UserError(_(
                "Công ty %(company)s chưa khai Ngày bắt đầu ghi sổ VAS. "
                "Vào Cài đặt → Connecta VAS để đặt mốc cutoff trước khi đồng bộ.",
                company=company.display_name,
            ))
        # Công ty phụ (vd. Công ty B): seed chỉ tạo sổ / khoản mục cho main_company
        # lúc cài module — bổ sung BH/MH/KHO/… và NVLTT/NCTT/CPC/CPD trước khi sync.
        self.env['vas.journal']._ensure_journals_for_company(company)
        self.env['vas.cost.item']._ensure_system_items_for_company(company)
        # Cutoff sàn: chứng từ ngày < vas_start_date bỏ qua hoàn toàn.
        cutoff = company.vas_start_date
        if date_from:
            date_from = max(fields.Date.to_date(date_from), cutoff)
        else:
            date_from = cutoff
        # Sổ ghi các move chưa có giá trị / cờ landed, gom suốt lượt đồng bộ rồi
        # tổng kết một lần ở cuối — cùng đường cảnh báo với nhóm chưa khai ánh xạ.
        self = self.with_context(
            vas_unvalued=[], vas_landed_flags=[], vas_period_missing=[],
        )
        # Cancel-handling TRƯỚC tạo mới: đảo JE nguồn đã chết → mở _already_synced.
        cancel_stats = self._sync_cancel_regressions(company)
        # W9.5 §8.3: thử ghi lại nháp thiếu kỳ TRƯỚC khi sync nguồn mới.
        retry_stats = self._retry_period_missing_drafts(company, date_from, date_to)
        # W3 first so R17/R18 skip transfers / advances / discounts handled elsewhere
        stats = {
            'cancel_regression': cancel_stats,
            'period_missing_retry': retry_stats,
            'cash_transfer': self._sync_cash_transfers(company, date_from, date_to),
            'deposit': self._sync_deposits(company, date_from, date_to),
            # W7 vay & vốn — nhãn payment / misc trước R17/R18
            'loan_capital': self._sync_loan_and_capital(company, date_from, date_to),
            'advance_employee': self._sync_advances_employee(company, date_from, date_to),
            'advance_refund': self._sync_advance_refunds(company, date_from, date_to),
            'advance_settlement': self._sync_advance_settlements(company, date_from, date_to),
            'employee_debt_payment': self._sync_employee_debt_payments(
                company, date_from, date_to),
            'payment_discount': self._sync_payment_discounts(company, date_from, date_to),
            'sale_invoice': self._sync_sale_invoices(company, date_from, date_to),
            'sale_delivery': self._sync_sale_deliveries(company, date_from, date_to),
            'sale_refund': self._sync_sale_refunds(company, date_from, date_to),
            'sale_return_stock': self._sync_sale_return_stocks(company, date_from, date_to),
            'payment_in': self._sync_payments_in(company, date_from, date_to),
            # R10 trước R06: khi HĐ + nhập cùng lượt, treo 151 trước rồi R06 Có 151.
            'goods_in_transit': self._sync_goods_in_transit(company, date_from, date_to),
            'purchase_receipt': self._sync_purchase_receipts(company, date_from, date_to),
            'purchase_invoice': self._sync_purchase_invoices(company, date_from, date_to),
            'purchase_service': self._sync_purchase_services(company, date_from, date_to),
            'purchase_prepaid': self._sync_purchase_prepaid(company, date_from, date_to),
            'purchase_landed_tax': self._sync_purchase_landed_tax(company, date_from, date_to),
            'purchase_price_adjust': self._sync_purchase_price_adjusts(company, date_from, date_to),
            'purchase_refund': self._sync_purchase_refunds(company, date_from, date_to),
            'purchase_return_stock': self._sync_purchase_return_stocks(company, date_from, date_to),
            'stock_issue_production': self._sync_production_issues(company, date_from, date_to),
            'stock_scrap': self._sync_stock_scraps(company, date_from, date_to),
            'landed_cost_adjust': self._sync_landed_cost_adjusts(company, date_from, date_to),
            # R27 trước R18: payment nhãn import_vat_payment → 33312/112;
            # R18 chỉ bắt payment không nhãn (tránh Nợ 331/Có 112 trùng).
            'import_vat_payment': self._sync_import_vat_payments(
                company, date_from, date_to),
            'payment_out': self._sync_payments_out(company, date_from, date_to),
            # R24 sau payment in/out: cần AML tiền + reconcile + EXCH đã có.
            'forex_realized': self._sync_forex_realized(company, date_from, date_to),
            # W9 — lương (soft: im nếu không có hr.payslip)
            'payroll': self._sync_payroll(company, date_from, date_to),
            'pos': self._sync_pos(company, date_from, date_to),
        }
        stats['landed_orphan'] = self._flag_orphan_landed_bills(company, date_from, date_to)
        stats['default_account'] = self._default_account_summary(company, date_from, date_to)
        stats['period_missing'] = self._period_missing_summary(company, date_from, date_to)
        # 1A: bổ sung tax_id trên sổ cũ — không đổi số tiền / không sinh bút toán.
        stats['tax_backfill'] = self.backfill_line_tax_ids(company, date_from, date_to)
        stats['direct_industry_backfill'] = self.backfill_direct_industry(
            company, date_from, date_to,
        )
        # Chặng 2: máy tự kiểm điều kiện khấu trừ đầu vào (không đổi số tiền sổ).
        stats['tax_deduction_check'] = self.env['vas.move.line'].recompute_input_vat_deduction(
            company=company, as_of_date=date_to or fields.Date.context_today(self),
        )
        _logger.info('VAS sync company=%s stats=%s', company.id, stats)
        return stats

    def _default_account_summary(self, company, date_from=None, date_to=None):
        """C2: sau mỗi lượt đồng bộ, đếm bút toán phải dùng tài khoản mặc định."""
        domain = [
            ('company_id', '=', company.id),
            ('vas_has_default_account', '=', True),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['vas.move'].search(domain)
        unvalued = self.env.context.get('vas_unvalued') or []
        landed_flags = self.env.context.get('vas_landed_flags') or []
        summary = {
            'moves': len(moves),
            'categories': self.env['vas.account.map.review']._missing_summary(company),
            'unvalued_moves': len(unvalued),
            'landed_flags': len(landed_flags),
        }
        if moves:
            _logger.warning(
                'VAS sync company=%s: %s bút toán dùng TK mặc định. Nhóm thiếu cấu hình: %s',
                company.id, len(moves), summary['categories'] or '(không xác định)',
            )
        if unvalued:
            _logger.warning(
                'VAS sync company=%s: %s chứng từ kho CHƯA CÓ GIÁ TRỊ nên không ghi sổ: %s',
                company.id, len(unvalued), '; '.join(unvalued),
            )
        if landed_flags:
            _logger.warning(
                'VAS sync company=%s: %s cảnh báo landed cost (thiếu bill / orphan): %s',
                company.id, len(landed_flags), '; '.join(landed_flags),
            )
        return summary

    # -------------------------------------------------------------------------
    # Event scanners
    # -------------------------------------------------------------------------

    def _sync_sale_invoices(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['account.move'].search(domain)
        created = skipped = 0
        rules = self._find_rules('sale_invoice', company.vas_regime_id)
        if not rules:
            return {'created': 0, 'skipped': 0, 'no_rule': True}
        rule = rules[:1]
        for invoice in moves:
            if self._invoice_is_pos(invoice):
                skipped += 1
                continue
            if self._already_synced(invoice._name, invoice.id, 'sale_inv'):
                skipped += 1
                continue
            # Policy B: DT theo tỷ lệ đã xuất (gross); thuế đủ; không chặn sync.
            ratio = self._sale_invoice_delivery_ratio(invoice)
            move = self._generate_sale_invoice_move(
                rule, invoice, company, revenue_ratio=ratio,
            )
            if move:
                created += 1
        return {'created': created, 'skipped': skipped}

    def _sync_sale_deliveries(self, company, date_from, date_to):
        """R02 — giá vốn của hàng RỜI KHO ĐI KHÁCH.

        Mốc duy nhất là `location_dest_usage='customer'`. Nhánh
        `sale_line_id != False` đứng một mình đã bị BỎ: kho `pick_ship` tách một
        đơn thành chặng PICK (internal→internal) và chặng OUT, cả hai đều mang
        `sale_line_id`, nên nhánh đó làm R02 ghi giá vốn HAI LẦN cho một lần bán.
        `_already_synced` không đỡ được vì đó là hai `stock.move` khác id.

        Bỏ luôn `picking_code='outgoing'`: hàng đi khách không qua phiếu (giao
        thẳng, điều chỉnh tay) vẫn phải ghi giá vốn, mà đích `customer` đã đủ
        nhận diện.
        """
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
            ('location_dest_usage', '=', 'customer'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        stock_moves = self.env['stock.move'].search(domain)
        stock_moves = stock_moves.filtered(lambda sm: not self._stock_move_is_pos(sm))
        created = skipped = 0
        rules_cogs = self._find_rules('sale_delivery', company.vas_regime_id)
        if not rules_cogs:
            return {'created': 0, 'skipped': 0, 'no_rule': True}
        rule_cogs = rules_cogs[:1]
        for sm in stock_moves:
            # COGS — move_kind=cogs
            if self._already_synced(sm._name, sm.id, 'cogs'):
                skipped += 1
            else:
                move = self._generate_move(rule_cogs, sm, company, 'cogs', event_type='sale_delivery')
                if move:
                    created += 1
            # Revenue on delivery if invoice exists without revenue yet
            rev = self._generate_delivery_revenue_move(sm, company)
            if rev:
                created += 1
        return {'created': created, 'skipped': skipped}

    def _sync_payments_in(self, company, date_from, date_to):
        payments = self._search_payments(company, date_from, date_to, 'inbound')
        payments = payments.filtered(
            lambda p: not p.vas_operation_type and not self._payment_is_pos(p)
        )
        return self._apply_payment_event('payment_in', payments, company)

    def _sync_payments_out(self, company, date_from, date_to):
        """R18: chi trả nhà cung cấp.

        Loại trừ:
        - payment gắn `hr.expense` (R19c/d/g đã ghi);
        - mọi payment có `vas_operation_type` (R19/R20/R21/R27…) — gồm
          `import_vat_payment` để R27 ghi Nợ 33312 / Có 112 mà R18 không ghi
          thêm Nợ 331 / Có 112 (cùng tinh thần loại is_landed khỏi R08).
        """
        payments = self._search_payments(company, date_from, date_to, 'outbound')
        payments = payments.filtered(
            lambda p: not p.vas_operation_type
            and not self._payment_linked_to_expense(p)
            and not self._payment_reconciled_to_payslip(p)
            and not self._payment_is_pos(p)
        )
        return self._apply_payment_event('payment_out', payments, company)

    def _sync_import_vat_payments(self, company, date_from, date_to):
        """R27 — nộp GTGT hàng NK: payment nhãn import_vat_payment.

        Nợ 33312 / Có 111|112 (M11-7). Chứng từ vas.import.vat không tự Có 112.
        """
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        targets = payments.filtered(
            lambda p: p.vas_operation_type == 'import_vat_payment'
            and p.payment_type == 'outbound'
        )
        stats = self._apply_event('import_vat_payment', targets, company)
        Move = self.env['vas.move']
        for payment in targets:
            decl = payment.vas_import_vat_id
            if not decl:
                continue
            move = Move.search([
                ('source_model', '=', payment._name),
                ('source_res_id', '=', payment.id),
                ('move_kind', '=', 'import_vat_payment'),
                ('state', '=', 'posted'),
                ('is_reversal', '=', False),
            ], limit=1)
            if move and decl.payment_move_id != move:
                decl.payment_move_id = move.id
        return stats

    def _payment_linked_to_expense(self, payment):
        """Payment này có phải là thanh toán cho `hr.expense` không?

        Hai đường Odoo 19:
        - Paid By = Company: payment.expense_ids (related qua move của chính payment).
        - Register Payment trên own_account: payment thường `move_id` trống /
          `state=in_process`, liên kết nằm ở `account.move.matched_payment_ids`
          của biên lai chi phí — không có `payment.expense_ids`.
        """
        return bool(self._expenses_of_payment(payment))

    def _apply_payment_event(self, event_type, payments, company):
        """R17/R18: book payment then allocate residuals via Odoo partial.reconcile."""
        created = skipped = 0
        move_kind = EVENT_MOVE_KIND[event_type]
        rules = self._find_rules(event_type, company.vas_regime_id)
        if not rules:
            return {'created': 0, 'skipped': 0, 'no_rule': True}
        for payment in payments:
            if self._already_synced(payment._name, payment.id, move_kind):
                skipped += 1
                # Still try residual sync if payment move exists
                vas_pay = self.env['vas.move'].search([
                    ('source_model', '=', payment._name),
                    ('source_res_id', '=', payment.id),
                    ('move_kind', '=', move_kind),
                    ('state', '=', 'posted'),
                ], limit=1)
                if vas_pay:
                    self._vas_apply_payment_partials(payment, vas_pay)
                continue
            # FX: chưa khớp HĐ → chưa ghi (tránh settle nhầm); sync lại sau reconcile.
            if self._payment_fx_awaiting_reconcile(payment, company):
                skipped += 1
                continue
            rule = self._match_rule(rules, payment)
            if not rule:
                continue
            cash_code = self._payment_fx_cash_code(payment, company)
            ctx = {}
            if cash_code:
                ctx['vas_forex_cash_code'] = cash_code
            move = self.with_context(**ctx)._generate_move(
                rule, payment, company, move_kind, event_type=event_type,
            )
            if move:
                created += 1
                self._vas_apply_payment_partials(payment, move)
        return {'created': created, 'skipped': skipped}

    def _sync_goods_in_transit(self, company, date_from, date_to):
        """R10 — HĐ mua posted, chưa nhập kho, công tắc 151 bật → Nợ 151 / Có 331.

        Chỉ phần untaxed dòng hàng. Thuế vẫn do R07. Đã có receipt done → bỏ qua
        (không treo 151 khi hàng đã về).
        """
        if not company.vas_theo_doi_hang_di_duong:
            return {'created': 0, 'skipped': 0, 'toggle_off': True}
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        bills = self.env['account.move'].search(domain).filtered(
            lambda m: bool(self._goods_lines(m))
            and not self._bill_has_done_receipt(m)
        )
        return self._apply_event('goods_in_transit', bills, company)

    def _bill_has_done_receipt(self, bill):
        """True nếu đã có stock.move purchase done gắn PO line của dòng hàng."""
        if 'purchase_line_id' not in bill.invoice_line_ids._fields:
            return False
        po_lines = self._goods_lines(bill).mapped('purchase_line_id')
        if not po_lines:
            return False
        return bool(self.env['stock.move'].search_count([
            ('purchase_line_id', 'in', po_lines.ids),
            ('state', '=', 'done'),
        ]))

    def _receipt_has_open_transit(self, stock_move, company):
        """R06: Có 151 nếu đã có vas.move goods_in_transit trên HĐ cùng PO line."""
        if not company.vas_theo_doi_hang_di_duong:
            return False
        po_line = stock_move.purchase_line_id
        if not po_line:
            return False
        inv_lines = self.env['account.move.line'].search([
            ('purchase_line_id', '=', po_line.id),
            ('move_id.move_type', '=', 'in_invoice'),
            ('move_id.state', '=', 'posted'),
            ('move_id.company_id', '=', company.id),
            ('display_type', 'not in', ('line_section', 'line_note')),
        ])
        bills = inv_lines.mapped('move_id')
        if not bills:
            return False
        return bool(self.env['vas.move'].search_count([
            ('source_model', '=', 'account.move'),
            ('source_res_id', 'in', bills.ids),
            ('move_kind', '=', 'goods_in_transit'),
            ('state', '=', 'posted'),
            ('company_id', '=', company.id),
        ]))

    def _sync_purchase_receipts(self, company, date_from, date_to):
        """R06 — nhập kho mua hàng (hàng THỰC đi vào kho).

        Domain trước (bug): ``purchase_line_id`` gồm cả phiếu trả
        (``internal → supplier``) → JE cùng ``move_kind=stock`` → R09s skip.

        Domain sau: loại mọi move có đích NCC (``location_dest_usage=supplier``)
        — tức loại chiều trả. Giữ các chiều còn lại (supplier→internal,
        dropship supplier→customer, …). Không whitelist hẹp chỉ internal.
        """
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
            # Loại chiều-RA về NCC (phiếu trả); không đụng dropship / nhập thường.
            ('location_dest_usage', '!=', 'supplier'),
            '|',
            ('purchase_line_id', '!=', False),
            '&',
            ('picking_code', '=', 'incoming'),
            ('location_usage', '=', 'supplier'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['stock.move'].search(domain)
        return self._apply_event('purchase_receipt', moves, company)

    def _sync_purchase_invoices(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['account.move'].search(domain)
        # R07 chỉ ghi thuế của các DÒNG HÀNG. Hóa đơn trộn hàng + dịch vụ thì
        # phần dịch vụ do R08 ghi, nên ở đây lọc theo "có ít nhất một dòng hàng"
        # chứ không phải "không có dòng dịch vụ nào".
        moves = moves.filtered(lambda m: bool(self._goods_lines(m)))
        return self._apply_event('purchase_invoice', moves, company)

    def _sync_purchase_services(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['account.move'].search(domain).filtered(
            lambda m: bool(self._service_lines(m))
        )
        return self._apply_event('purchase_service', moves, company)

    def _prepaid_months_from_deferred(self, line):
        """Số kỳ tháng từ deferred_start/end — đọc mềm (không hard-depend accountant).

        End date **tính cả** (giống Odoo: khoảng inclusive theo tháng lịch).
        VD 2026-01-01 → 2028-12-31 = 36.
        """
        if (
            'deferred_start_date' not in line._fields
            or 'deferred_end_date' not in line._fields
        ):
            return False
        start = line.deferred_start_date
        end = line.deferred_end_date
        if not start or not end or end < start:
            return False
        months = (end.year - start.year) * 12 + (end.month - start.month) + 1
        return months if months >= 1 else False

    def _resolve_prepaid_duration(self, lines):
        """Thứ tự: deferred Odoo → vas_prepaid_months. Không bịa 12.

        Trả ``(months_or_False, source)`` với source in
        ``('deferred', 'vas', None)``.
        """
        for line in lines:
            months = self._prepaid_months_from_deferred(line)
            if months:
                return months, 'deferred'
        for line in lines:
            months = getattr(line, 'vas_prepaid_months', 0) or 0
            if months >= 1:
                return int(months), 'vas'
        return False, None

    def _resolve_prepaid_expense_account(self, lines, company, bill, fallbacks):
        """Map SP ``product_expense`` → else 6422 + cờ (nhãn trả trước)."""
        regime = company.vas_regime_id
        for line in lines:
            if not line.product_id:
                continue
            peek = []
            acc = self._product_account(
                line.product_id, 'product_expense', company, peek,
            )
            if not peek:
                return acc
            fallbacks.append({
                'selector': 'product_expense',
                'default_code': '6422',
                'label': _(
                    'khoản trả trước %(name)s → dùng mặc định 6422',
                    name=bill.display_name,
                ),
            })
            return acc
        fallbacks.append({
            'selector': 'product_expense',
            'default_code': '6422',
            'label': _(
                'khoản trả trước %(name)s → dùng mặc định 6422 '
                '(không có sản phẩm trên dòng)',
                name=bill.display_name,
            ),
        })
        return self._account_by_code(regime, '6422')

    def _sync_purchase_prepaid(self, company, date_from, date_to):
        """A10 — dòng vas_is_prepaid: Nợ 242 / Có 331 + tạo thẻ prepaid_service.

        Kỳ hạn: deferred_start/end (mềm) → ``vas_prepaid_months`` → không bịa 12
        (thẻ draft + cờ, kế toán khai tay). TK CP: map SP rồi 6422 + cờ §8.3.
        """
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        bills = self.env['account.move'].search(domain).filtered(
            lambda m: bool(self._prepaid_service_lines(m))
        )
        created = skipped = cards = 0
        regime = company.vas_regime_id
        acc_242 = self._account_by_code(regime, '242')
        acc_331 = self._account_by_code(regime, '331')
        if not acc_242 or not acc_331:
            return {'created': 0, 'skipped': 0, 'no_account': True}
        for bill in bills:
            if self._already_synced(bill._name, bill.id, 'prepaid_alloc'):
                skipped += 1
                continue
            lines = self._prepaid_service_lines(bill)
            untaxed = self._invoice_lines_amount(lines, 'untaxed')
            if float_is_zero(untaxed, precision_digits=2):
                skipped += 1
                continue
            fallbacks = []
            duration, dur_source = self._resolve_prepaid_duration(lines)
            if not duration:
                fallbacks.append({
                    'selector': 'prepaid_duration',
                    'default_code': 'duration',
                    'label': _(
                        'khoản trả trước %(name)s → chưa có kỳ hạn '
                        '(deferred/VAS) — thẻ draft, khai tay trên thẻ',
                        name=bill.display_name,
                    ),
                })
                _logger.warning(
                    'VAS prepaid: %s thiếu kỳ hạn → thẻ draft, gắn cờ',
                    bill.display_name,
                )
            exp = self._resolve_prepaid_expense_account(
                lines, company, bill, fallbacks,
            )
            journal = self._resolve_journal('purchase_service', bill, company)
            move_vals = {
                'date': bill.date,
                'journal_id': journal.id,
                'regime_id': regime.id,
                'move_kind': 'prepaid_alloc',
                'ref': _('Ghi nhận CP trả trước %s') % bill.display_name,
                'source_model': bill._name,
                'source_res_id': bill.id,
                'source_ref': bill.display_name,
                'company_id': company.id,
                'currency_id': company.currency_id.id,
                'line_ids': [
                    Command.create({
                        'sequence': 10, 'account_id': acc_242.id,
                        'name': bill.display_name, 'debit': untaxed, 'credit': 0.0,
                        'currency_id': company.currency_id.id,
                        'partner_id': bill.partner_id.id,
                    }),
                    Command.create({
                        'sequence': 20, 'account_id': acc_331.id,
                        'name': bill.display_name, 'debit': 0.0, 'credit': untaxed,
                        'currency_id': company.currency_id.id,
                        'partner_id': bill.partner_id.id,
                    }),
                ],
            }
            move_vals.update(self._default_account_flag_vals(fallbacks))
            move = self.env['vas.move'].create(move_vals)
            posted = self._post_or_flag_period_missing(move)
            if not posted:
                continue
            created += 1
            card_vals = {
                'code': 'PP-%s' % bill.id,
                'name': _('Trả trước %s') % bill.display_name,
                'company_id': company.id,
                'regime_id': regime.id,
                'asset_type': 'prepaid',
                'asset_kind': 'prepaid_service',
                'original_value': untaxed,
                'date_start': bill.date,
                'method': 'straight_line',
                'prorata': False,
                'account_gross_id': acc_242.id,
                'account_accum_id': acc_242.id,
                'account_expense_id': exp.id if exp else False,
                'source_mode': 'manual',
            }
            if duration:
                card_vals['duration_months'] = duration
                card_vals['useful_life_years'] = duration / 12.0
            card = self.env['vas.asset'].create(card_vals)
            # Có kỳ hạn → confirm + lịch. Thiếu → draft (cấm action_confirm:
            # _recompute_schedule dùng ``duration or 1`` sẽ bịa 1 kỳ).
            if duration:
                card.action_confirm()
            else:
                _logger.info(
                    'VAS prepaid card %s draft (source=%s, chờ khai kỳ hạn)',
                    card.code, dur_source,
                )
            cards += 1
        return {'created': created, 'skipped': skipped, 'cards': cards}

    def _landed_costs_available(self):
        """Soft-check: module stock_landed_costs đã nạp model adjustment lines."""
        return 'stock.valuation.adjustment.lines' in self.env

    def _sync_purchase_landed_tax(self, company, date_from, date_to):
        """R26 — thuế GTGT trên dòng hóa đơn cước (đã loại khỏi R08).

        Thuế = 0 (cước quốc tế): bỏ qua im lặng — không sinh 1331, không gắn cờ.
        """
        if not self._landed_costs_available():
            return {'created': 0, 'skipped': 0, 'no_module': True}
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        bills = self.env['account.move'].search(domain).filtered(
            lambda m: bool(self._landed_lines(m))
        )
        created = skipped = silent_zero = 0
        rules = self._find_rules('purchase_landed_tax', company.vas_regime_id)
        if not rules:
            return {'created': 0, 'skipped': 0, 'no_rule': True}
        rule = rules[:1]
        move_kind = EVENT_MOVE_KIND['purchase_landed_tax']
        for bill in bills:
            if self._already_synced(bill._name, bill.id, move_kind):
                skipped += 1
                continue
            tax = self._invoice_lines_amount(self._landed_lines(bill), 'tax')
            if float_is_zero(tax, precision_digits=2):
                # Cước 0% — đúng thiết kế: không bút toán, không cảnh báo.
                silent_zero += 1
                continue
            move = self._generate_move(
                rule, bill, company, move_kind, event_type='purchase_landed_tax',
            )
            if move:
                created += 1
        return {
            'created': created,
            'skipped': skipped,
            'silent_zero_tax': silent_zero,
        }

    def _sync_landed_cost_adjusts(self, company, date_from, date_to):
        """R25 — vốn hóa `additional_landed_cost` vào TK tồn.

        Mỗi adjustment.line độc lập:
        - SP cost nằm trong vas.landed.tax.map → Nợ tồn / Có TK thuế (3333…);
          không cần vendor_bill_id.
        - Còn lại (cước): Nợ tồn / Có 331; thiếu vendor_bill → cờ, không ghi.
        """
        if not self._landed_costs_available():
            return {'created': 0, 'skipped': 0, 'no_module': True}
        Adj = self.env['stock.valuation.adjustment.lines']
        domain = [
            ('cost_id.state', '=', 'done'),
            ('cost_id.company_id', '=', company.id),
            ('additional_landed_cost', '!=', 0),
        ]
        if date_from:
            domain.append(('cost_id.date', '>=', date_from))
        if date_to:
            domain.append(('cost_id.date', '<=', date_to))
        lines = Adj.search(domain)
        created = skipped = flagged = tax_created = 0
        rules = self._find_rules('landed_cost_adjust', company.vas_regime_id)
        if not rules:
            return {'created': 0, 'skipped': 0, 'no_rule': True}
        rule = rules[:1]
        move_kind = EVENT_MOVE_KIND['landed_cost_adjust']
        for adj in lines:
            if self._already_synced(adj._name, adj.id, move_kind):
                skipped += 1
                continue
            is_tax = bool(self._landed_tax_map_for_adj(adj, company))
            if not is_tax and not adj.cost_id.vendor_bill_id:
                self._note_landed_flag(
                    'R25',
                    _(
                        '%(adj)s: LC cước không có hóa đơn (vendor_bill_id) '
                        '→ KHÔNG ghi Nợ tồn / Có 331. Bổ sung hóa đơn rồi đồng bộ lại.',
                        adj=adj.display_name,
                    ),
                )
                flagged += 1
                continue
            move = self._generate_move(
                rule, adj, company, move_kind, event_type='landed_cost_adjust',
            )
            if move:
                created += 1
                if is_tax:
                    tax_created += 1
        return {
            'created': created,
            'skipped': skipped,
            'flagged_no_bill': flagged,
            'tax_created': tax_created,
        }

    def _landed_tax_map_for_adj(self, adj, company):
        """Dòng map thuế nếu SP trên cost_line được cấu hình; ngược lại empty."""
        if adj._name != 'stock.valuation.adjustment.lines':
            return self.env['vas.landed.tax.map']
        cost_product = adj.cost_line_id.product_id
        if not cost_product:
            return self.env['vas.landed.tax.map']
        regime = company.vas_regime_id
        return self.env['vas.landed.tax.map']._find_for_product(
            cost_product, regime, company,
        )

    def _flag_orphan_landed_bills(self, company, date_from, date_to):
        """ĐIỂM DỪNG: dòng HĐ landed nhưng chưa có LC done gắn bill.

        R08 đã loại dòng → nếu R25 không chạy (chưa LC) thì untaxed cước MẤT
        khỏi sổ VAS. Chỉ gắn cờ / log — KHÔNG tự chế số vào 642 hay 156.
        """
        if not self._landed_costs_available():
            return {'flagged': 0, 'no_module': True}
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        bills = self.env['account.move'].search(domain).filtered(
            lambda m: bool(self._landed_lines(m))
        )
        flagged = 0
        for bill in bills:
            done_lc = bill.landed_costs_ids.filtered(lambda c: c.state == 'done')
            if done_lc:
                continue
            untaxed = self._invoice_lines_amount(self._landed_lines(bill), 'untaxed')
            if float_is_zero(untaxed, precision_digits=2):
                continue
            self._note_landed_flag(
                'ORPHAN-LC',
                _(
                    '%(bill)s: dòng landed %(amt)s chưa có LC done — đã loại R08 '
                    'nhưng R25 chưa chạy → khoản MẤT sổ VAS đến khi tạo/validate LC. '
                    'Không tự ghi 642/156.',
                    bill=bill.display_name,
                    amt=f'{untaxed:,.0f}',
                ),
            )
            flagged += 1
        return {'flagged': flagged}

    def _note_landed_flag(self, code, message):
        """Cảnh báo landed — tái dùng bucket sync + log, không tự chế bút toán."""
        _logger.warning('VAS %s: %s', code, message)
        bucket = self.env.context.get('vas_landed_flags')
        if bucket is not None:
            bucket.append(f'{code}:{message}')

    def _is_landed_invoice_line(self, line):
        """Dòng HĐ cước/BH landed — loại khỏi R08, nguồn thuế cho R26."""
        if not self._landed_costs_available():
            return False
        if getattr(line, 'is_landed_costs_line', False):
            return True
        product = line.product_id
        return bool(product) and bool(getattr(product, 'landed_cost_ok', False))

    def _landed_lines(self, move):
        return self._real_invoice_lines(move).filtered(self._is_landed_invoice_line)

    def _sync_sale_refunds(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'out_refund'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        refunds = self.env['account.move'].search(domain)
        refunds = refunds.filtered(lambda m: not self._invoice_is_pos(m))
        with_return = refunds.filtered(self._refund_has_stock_return)
        without = refunds - with_return
        s1 = self._apply_event('sale_refund', with_return, company)
        s2 = self._apply_event('sale_discount', without, company)
        return {'sale_refund': s1, 'sale_discount': s2}

    def _sync_sale_return_stocks(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
            ('location_usage', '=', 'customer'),
            ('location_dest_usage', '=', 'internal'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['stock.move'].search(domain)
        # Prefer returns linked to sale lines / refunds
        moves = moves.filtered(
            lambda m: not self._stock_move_is_pos(m) and (
                ('sale_line_id' in m._fields and m.sale_line_id)
                or bool(m.origin)
            )
        )
        return self._apply_event('sale_return_stock', moves, company)

    def _sync_purchase_refunds(self, company, date_from, date_to):
        """R09 (có trả kho) + R09b giảm giá phi kho (G6/G7 / M09)."""
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_refund'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        refunds = self.env['account.move'].search(domain)
        with_return = refunds.filtered(self._refund_has_stock_return)
        without = refunds - with_return
        s1 = self._apply_event('purchase_refund', with_return, company)
        s2 = self._apply_event('purchase_discount', without, company)
        return {'purchase_refund': s1, 'purchase_discount': s2}

    def _sync_purchase_return_stocks(self, company, date_from, date_to):
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
            ('location_dest_usage', '=', 'supplier'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['stock.move'].search(domain)
        moves = moves.filtered(
            lambda m: ('purchase_line_id' in m._fields and m.purchase_line_id)
            or m.picking_code == 'outgoing'
        )
        return self._apply_event('purchase_return_stock', moves, company)

    # R13 (điều chuyển kho nội bộ) ĐÃ BỎ — xem KE_HOACH_ENGINE_RULE.md §5.10c.
    # Tóm tắt: workbook K01 chốt không ghi Sổ Cái; `vas.account.map` khóa theo SẢN
    # PHẨM chứ không theo KHO nên hai đầu điều chuyển luôn ra cùng một tài khoản,
    # rule này về cấu trúc không bao giờ sinh nổi bút toán có nghĩa.

    def _sync_production_issues(self, company, date_from, date_to):
        """R14 — xuất nguyên vật liệu cho sản xuất (K02).

        Chỉ cần hai trường mà `mrp` thêm vào `stock.move`, không đọc thẳng model
        `mrp.production`. Nhờ vậy `mrp` là phụ thuộc MỀM: khách không cài
        Manufacturing thì rule tự nằm im thay vì làm hỏng cả lượt đồng bộ.
        """
        if not self._mrp_available():
            return {'created': 0, 'skipped': 0, 'no_mrp': True}
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'done'),
            ('raw_material_production_id', '!=', False),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['stock.move'].search(domain)
        return self._apply_event('stock_issue_production', moves, company)

    def _mrp_available(self):
        """Manufacturing có được cài không — kiểm bằng trường, không bằng depends."""
        return 'raw_material_production_id' in self.env['stock.move']._fields

    @api.model
    def _pos_available(self):
        return 'pos.order' in self.env

    def _payment_is_pos(self, payment):
        return 'pos_session_id' in payment._fields and bool(payment.pos_session_id)

    def _invoice_is_pos(self, invoice):
        return 'pos_order_ids' in invoice._fields and bool(invoice.pos_order_ids)

    def _stock_move_is_pos(self, stock_move):
        picking = stock_move.picking_id
        if picking:
            if 'pos_order_id' in picking._fields and picking.pos_order_id:
                return True
            if 'pos_session_id' in picking._fields and picking.pos_session_id:
                return True
        if 'reference_ids' in stock_move._fields and stock_move.reference_ids:
            refs = stock_move.reference_ids
            if 'pos_order_ids' in refs._fields and refs.pos_order_ids:
                return True
        return False

    def _pos_session_line_vals(self, record):
        session = False
        if record._name == 'pos.session':
            session = record
        elif 'session_id' in getattr(record, '_fields', {}) and record.session_id:
            session = record.session_id
        if not session:
            return {}
        return {
            'pos_session_res_id': session.id,
            'pos_session_name': session.name or session.display_name,
        }

    def _sync_purchase_price_adjusts(self, company, date_from, date_to):
        """R07b: when vendor bill untaxed ≠ linked receipt stock value, adjust 156/331."""
        domain = [
            ('company_id', '=', company.id),
            ('move_type', '=', 'in_invoice'),
            ('state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        bills = self.env['account.move'].search(domain).filtered(
            lambda m: not self._is_service_purchase_move(m)
            and not float_is_zero(self._purchase_price_adjust_amount(m), precision_digits=2)
        )
        created = skipped = 0
        rules = self._find_rules('purchase_price_adjust', company.vas_regime_id)
        if not rules:
            return {'created': 0, 'skipped': 0, 'no_rule': True}
        rule = rules[:1]
        for bill in bills:
            # Distinct move_kind collision with R07 purchase_inv — use refund kind? Use source + kind purchase_inv
            # Already used by R07. Use move_kind 'manual' via custom generate with kind purchase_inv
            # and different source_res encoding — better: kind 'manual' for adjust.
            if self._already_synced(bill._name, bill.id, 'manual'):
                skipped += 1
                continue
            move = self._generate_price_adjust_move(rule, bill, company)
            if move:
                created += 1
        return {'created': created, 'skipped': skipped}

    def _real_invoice_lines(self, move):
        return move.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        )

    def _invoice_uses_signed_line_amounts(self, invoice, scope):
        """Hóa đơn BÁN gốc: dòng âm = chiết khấu cả đơn, phải cộng có dấu.

        Hoàn (`out_refund`), mua, POS refund — giữ abs (độ lớn + chiều Nợ/Có của rule).
        """
        return (
            scope == 'output'
            and invoice._name == 'account.move'
            and invoice.move_type == 'out_invoice'
        )

    def _is_goods_invoice_line(self, line):
        """Dòng hóa đơn là HÀNG TỒN KHO (giá trị đi qua stock.move → R06/R07)?

        Ranh giới duy nhất là `is_storable`: chỉ sản phẩm lưu kho mới sinh
        `stock.move` có giá trị để R06 ghi Nợ 156. Mọi thứ còn lại — dịch vụ,
        `consu` không lưu kho, dòng không có sản phẩm — là chi phí mua ngoài (R08).
        """
        product = line.product_id
        return bool(product) and bool(getattr(product, 'is_storable', False))

    def _goods_lines(self, move):
        return self._real_invoice_lines(move).filtered(self._is_goods_invoice_line)

    def _service_lines(self, move):
        """Dòng chi phí mua ngoài: điện, nước, thuê, quảng cáo, vận chuyển thường…

        Phần bù chính xác của `_goods_lines` trên cùng tập dòng thật, trừ thêm
        dòng landed cost (R08 không ghi — vốn hóa qua R25, thuế qua R26).
        """
        return self._real_invoice_lines(move).filtered(
            lambda l: (
                not self._is_goods_invoice_line(l)
                and not self._is_landed_invoice_line(l)
                and not getattr(l, 'vas_is_prepaid', False)
            )
        )

    def _prepaid_service_lines(self, move):
        return self._real_invoice_lines(move).filtered(
            lambda l: getattr(l, 'vas_is_prepaid', False)
        )

    def _is_service_purchase_move(self, move):
        """Hóa đơn THUẦN dịch vụ — chỉ dùng cho R07b (điều chỉnh giá tạm tính)."""
        lines = self._real_invoice_lines(move)
        return bool(lines) and not self._goods_lines(move)

    def _invoice_lines_amount(self, lines, amount_selector):
        """Số tiền của một TẬP DÒNG hóa đơn, không phải của cả hóa đơn.

        `price_total` đã gồm thuế nên thuế = total − subtotal; cách này lấy đúng
        thuế của riêng các dòng đang xét, kể cả khi các dòng khác chịu thuế suất
        khác.
        """
        untaxed = sum(abs(line.price_subtotal or 0.0) for line in lines)
        total = sum(abs(line.price_total or 0.0) for line in lines)
        return {
            'untaxed': untaxed,
            'tax': total - untaxed,
            'total': total,
        }.get(amount_selector, 0.0)

    def _refund_has_stock_return(self, refund):
        """True nếu credit note kèm nhập/xuất trả kho (bán: khách→kho; mua: kho→NCC)."""
        if refund.move_type == 'out_refund':
            if 'sale_line_ids' in refund.line_ids._fields:
                sale_orders = refund.line_ids.sale_line_ids.order_id
                if sale_orders:
                    returns = self.env['stock.move'].search_count([
                        ('sale_line_id.order_id', 'in', sale_orders.ids),
                        ('state', '=', 'done'),
                        ('location_usage', '=', 'customer'),
                        ('location_dest_usage', '=', 'internal'),
                    ])
                    return bool(returns)
            return False
        if refund.move_type == 'in_refund':
            po_lines = self.env['purchase.order.line']
            if 'purchase_line_id' in refund.invoice_line_ids._fields:
                po_lines = refund.invoice_line_ids.mapped('purchase_line_id')
            if not po_lines and refund.reversed_entry_id:
                orig = refund.reversed_entry_id
                if 'purchase_line_id' in orig.invoice_line_ids._fields:
                    po_lines = orig.invoice_line_ids.mapped('purchase_line_id')
            po_lines = po_lines.filtered(lambda l: l)
            if not po_lines:
                return False
            return bool(self.env['stock.move'].search_count([
                ('purchase_line_id', 'in', po_lines.ids),
                ('state', '=', 'done'),
                ('location_dest_usage', '=', 'supplier'),
            ]))
            return False
        return False

    def _purchase_line_for_refund_line(self, inv_line):
        """POL gắn dòng CN, hoặc khớp SP trên hóa đơn gốc bị đảo."""
        if 'purchase_line_id' in inv_line._fields and inv_line.purchase_line_id:
            return inv_line.purchase_line_id
        move = inv_line.move_id
        if move.reversed_entry_id and inv_line.product_id:
            orig = move.reversed_entry_id.invoice_line_ids.filtered(
                lambda l: l.product_id == inv_line.product_id
                and 'purchase_line_id' in l._fields
                and l.purchase_line_id
            )[:1]
            if orig:
                return orig.purchase_line_id
        return self.env['purchase.order.line']

    def _purchase_discount_is_proxy_line(self, inv_line, refund):
        """Dòng CN dùng SP Discount/dịch vụ thay vì đúng hàng trên HĐ gốc.

        Odoo hay tạo CN giảm giá bằng 1 dòng SP «Discount» (type service) —
        không có map 156/632 → trước đây rơi TK mặc định.
        """
        origin = refund.reversed_entry_id
        origin_goods = self._goods_lines(origin) if origin else self.env['account.move.line']
        if not origin_goods:
            return False
        product = inv_line.product_id
        if not product:
            return True
        if self._is_goods_invoice_line(inv_line):
            # Đúng SP lưu kho đã có trên HĐ gốc → không phải proxy.
            if product in origin_goods.mapped('product_id'):
                return False
            return True
        # Dịch vụ / không lưu kho trên CN trong khi gốc là hàng → coi là CK proxy.
        return True

    def _purchase_discount_target_rows(self, inv_line, refund, company):
        """Các cặp (product, pol, untaxed_share) để chọn TK + tỷ lệ tồn.

        Proxy Discount → chia theo trọng số untaxed các dòng hàng trên HĐ gốc.
        """
        untaxed = abs(inv_line.price_subtotal or 0.0)
        if float_is_zero(untaxed, precision_digits=2):
            return []
        if not self._purchase_discount_is_proxy_line(inv_line, refund):
            pol = self._purchase_line_for_refund_line(inv_line)
            product = (pol.product_id if pol else inv_line.product_id) or inv_line.product_id
            return [(product, pol, untaxed)]

        origin = refund.reversed_entry_id
        origin_goods = self._goods_lines(origin)
        weights = []
        for g in origin_goods:
            w = abs(g.price_subtotal or 0.0)
            if float_is_zero(w, precision_digits=2):
                w = abs(g.quantity or 0.0) or 1.0
            pol = g.purchase_line_id if 'purchase_line_id' in g._fields else self.env['purchase.order.line']
            weights.append((g.product_id, pol, w))
        total_w = sum(w for _p, _pol, w in weights)
        if float_is_zero(total_w, precision_digits=2):
            # Không chia được — gán hết SP đầu.
            g0 = origin_goods[:1]
            pol = g0.purchase_line_id if g0 and 'purchase_line_id' in g0._fields else self.env['purchase.order.line']
            return [(g0.product_id, pol, untaxed)]
        rows = []
        allocated = 0.0
        for idx, (product, pol, w) in enumerate(weights):
            if idx == len(weights) - 1:
                part = round(untaxed - allocated, 2)
            else:
                part = round(untaxed * (w / total_w), 2)
                allocated += part
            if not float_is_zero(part, precision_digits=2):
                rows.append((product, pol, part))
        return rows

    def _purchase_discount_stock_fraction_for(self, product, pol, company):
        """Tỷ lệ ghi vào tồn (156); phần còn lại → 632."""
        if not product or not getattr(product, 'is_storable', False):
            return 0.0
        net_in = 0.0
        if pol:
            moves = pol.move_ids.filtered(lambda m: m.state == 'done')
            incoming = moves.filtered(
                lambda m: (m.location_id.usage == 'supplier')
                or (getattr(m, 'location_usage', False) == 'supplier')
            )
            returned = moves.filtered(
                lambda m: (m.location_dest_id.usage == 'supplier')
                or (getattr(m, 'location_dest_usage', False) == 'supplier')
            )
            net_in = sum(incoming.mapped('quantity')) - sum(returned.mapped('quantity'))
        if float_is_zero(net_in, precision_digits=2):
            on_hand = product.with_company(company).qty_available
            return 1.0 if float_compare(on_hand, 0.0, precision_digits=2) > 0 else 0.0
        on_hand = product.with_company(company).qty_available
        remaining = min(max(on_hand, 0.0), net_in)
        return max(0.0, min(1.0, remaining / net_in))

    def _purchase_discount_stock_fraction(self, inv_line, company):
        """Tương thích test cũ — một dòng CN / một SP đích."""
        refund = inv_line.move_id
        rows = self._purchase_discount_target_rows(inv_line, refund, company)
        if not rows:
            return 0.0
        if len(rows) == 1:
            product, pol, _amt = rows[0]
            return self._purchase_discount_stock_fraction_for(product, pol, company)
        # Nhiều đích: trung bình có trọng số theo số tiền.
        total = sum(a for _p, _pol, a in rows)
        if float_is_zero(total, precision_digits=2):
            return 0.0
        weighted = 0.0
        for product, pol, amt in rows:
            weighted += amt * self._purchase_discount_stock_fraction_for(
                product, pol, company,
            )
        return weighted / total

    def _generate_purchase_discount_move(self, rule, refund, company):
        """R09b / M09: CN giảm giá không trả hàng — phân bổ Có 156 vs Có 632 + Có 1331.

        Dòng SP Discount (proxy) lấy map TK theo **hàng trên HĐ gốc**, không theo
        SP Discount (tránh cờ tài khoản mặc định).
        """
        real_lines = self._real_invoice_lines(refund)
        stock_by_product = {}
        cogs_by_product = {}
        expense_by_product = {}
        tax_total = 0.0
        fallbacks = []

        for line in real_lines:
            untaxed = abs(line.price_subtotal or 0.0)
            tax_total += abs(line.price_total or 0.0) - untaxed
            if float_is_zero(untaxed, precision_digits=2):
                continue
            targets = self._purchase_discount_target_rows(line, refund, company)
            if not targets:
                # Không gắn được gốc — vẫn ghi expense theo SP dòng (có thể default).
                product = line.product_id
                expense_by_product[product] = (
                    expense_by_product.get(product, 0.0) + untaxed
                )
                continue
            for product, pol, part in targets:
                if float_is_zero(part, precision_digits=2):
                    continue
                if product and getattr(product, 'is_storable', False):
                    frac = self._purchase_discount_stock_fraction_for(
                        product, pol, company,
                    )
                    stock_amt = round(part * frac, 2)
                    cogs_amt = round(part - stock_amt, 2)
                    if stock_amt:
                        stock_by_product[product] = (
                            stock_by_product.get(product, 0.0) + stock_amt
                        )
                    if cogs_amt:
                        cogs_by_product[product] = (
                            cogs_by_product.get(product, 0.0) + cogs_amt
                        )
                else:
                    expense_by_product[product] = (
                        expense_by_product.get(product, 0.0) + part
                    )

        tax_total = round(tax_total, 2)
        stock_total = round(sum(stock_by_product.values()), 2)
        cogs_total = round(sum(cogs_by_product.values()), 2)
        expense_total = round(sum(expense_by_product.values()), 2)
        debit_331 = round(stock_total + cogs_total + expense_total + tax_total, 2)
        if float_is_zero(debit_331, precision_digits=2):
            return self.env['vas.move']

        regime = company.vas_regime_id
        acc_331 = self._account_by_code(regime, '331')
        acc_1331 = self._account_by_code(regime, '1331')
        if not acc_331 or not acc_1331:
            raise UserError(_("Missing VAS accounts 331/1331 for purchase discount."))

        lines = []
        seq = 10
        partner = refund.partner_id
        lines.append(Command.create({
            'sequence': seq, 'account_id': acc_331.id, 'name': rule.name,
            'debit': debit_331, 'credit': 0.0,
            'partner_id': partner.id if partner else False,
            'currency_id': company.currency_id.id,
        }))
        seq += 10

        def _credit_splits(amount_map, selector):
            nonlocal seq
            for product, amount in amount_map.items():
                if float_is_zero(amount, precision_digits=2):
                    continue
                account = self._product_account(
                    product, selector, company, fallbacks,
                )
                if not account:
                    raise UserError(_(
                        "Missing VAS account (%(sel)s) for purchase discount.",
                        sel=selector,
                    ))
                lines.append(Command.create({
                    'sequence': seq, 'account_id': account.id, 'name': rule.name,
                    'debit': 0.0, 'credit': amount,
                    'partner_id': partner.id if partner else False,
                    'currency_id': company.currency_id.id,
                }))
                seq += 10

        _credit_splits(stock_by_product, 'product_inventory')
        _credit_splits(cogs_by_product, 'product_cogs')
        _credit_splits(expense_by_product, 'product_expense')

        if not float_is_zero(tax_total, precision_digits=2):
            lines.append(Command.create({
                'sequence': seq, 'account_id': acc_1331.id, 'name': rule.name,
                'debit': 0.0, 'credit': tax_total,
                'partner_id': partner.id if partner else False,
                'currency_id': company.currency_id.id,
            }))

        journal = self._resolve_journal('purchase_discount', refund, company)
        move = self.env['vas.move'].create({
            'date': refund.invoice_date or refund.date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'refund',
            'ref': rule.name,
            'source_model': refund._name,
            'source_res_id': refund.id,
            'source_ref': refund.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': lines,
            **self._default_account_flag_vals(fallbacks),
        })
        return self._post_or_flag_period_missing(move)

    def _purchase_price_adjust_amount(self, bill):
        """untaxed của các DÒNG HÀNG − sum(stock.move.value) của phiếu nhập theo PO.

        Chỉ dòng hàng tồn kho mới có phiếu nhập để so; lấy `amount_untaxed` của cả
        hóa đơn thì hóa đơn trộn sẽ coi tiền dịch vụ là chênh lệch giá hàng và ghi
        thừa vào 156.
        """
        receipt_value = 0.0
        if 'purchase_line_id' in bill.invoice_line_ids._fields:
            po_lines = bill.invoice_line_ids.mapped('purchase_line_id')
            if po_lines:
                moves = self.env['stock.move'].search([
                    ('purchase_line_id', 'in', po_lines.ids),
                    ('state', '=', 'done'),
                ])
                # Prefer incoming (supplier → internal); else all linked done moves
                incoming = moves.filtered(
                    lambda m: getattr(m, 'location_usage', False) == 'supplier'
                    or (m.location_id and m.location_id.usage == 'supplier')
                )
                moves = incoming or moves
                receipt_value = sum(abs(self._stock_move_value(m)) for m in moves)
        # Gate: chưa có receipt done → không đẩy full untaxed vào 156 (bug gấp đôi
        # với R06). M01 chênh tạm tính chỉ chạy khi đã nhập kho.
        if float_is_zero(receipt_value, precision_digits=2):
            return 0.0
        goods_untaxed = self._invoice_lines_amount(self._goods_lines(bill), 'untaxed')
        return goods_untaxed - receipt_value

    def _generate_price_adjust_move(self, rule, bill, company):
        adjust = self._purchase_price_adjust_amount(bill)
        if float_is_zero(adjust, precision_digits=2):
            return self.env['vas.move']
        amount = abs(adjust)
        regime = company.vas_regime_id
        inv = self._account_by_code(regime, '156')
        pay = self._account_by_code(regime, '331')
        if not inv or not pay:
            raise UserError(_('Missing VAS 156/331 for purchase price adjust.'))
        # bill > receipt → Dr 156 / Cr 331; else reverse
        if adjust > 0:
            debit_acc, credit_acc = inv, pay
        else:
            debit_acc, credit_acc = pay, inv
        journal = self._resolve_journal('purchase_price_adjust', bill, company)
        move = self.env['vas.move'].create({
            'date': bill.date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'manual',
            'ref': rule.name,
            'source_model': bill._name,
            'source_res_id': bill.id,
            'source_ref': f'{bill.display_name} price adjust',
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10, 'account_id': debit_acc.id, 'name': rule.name,
                    'debit': amount, 'credit': 0.0, 'currency_id': company.currency_id.id,
                    'partner_id': bill.partner_id.id,
                }),
                Command.create({
                    'sequence': 20, 'account_id': credit_acc.id, 'name': rule.name,
                    'debit': 0.0, 'credit': amount, 'currency_id': company.currency_id.id,
                    'partner_id': bill.partner_id.id,
                }),
            ],
        })
        return self._post_or_flag_period_missing(move)

    def _sync_advances_employee(self, company, date_from, date_to):
        """R19: nhãn ``vas_operation_type='employee_advance'`` + đối tác là NLĐ.

        Loại trừ hoàn tiền hr.expense và thanh toán gắn payslip (→ R41 / W9).
        """
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        advances = payments.filtered(
            lambda p: self._is_employee_advance_payment(p)
            and not self._payment_reconciled_to_payslip(p)
        )
        return self._apply_event('advance_employee', advances, company)

    def _sync_advance_settlements(self, company, date_from, date_to):
        """R19c/R19d/R19g — ghi nhận chi phí từ `hr.expense` đã duyệt.

        - R19c/R19d: `payment_mode='own_account'` → Có 141 / Có 334.
        - R19g: `payment_mode='company_account'` → Có 111/112 theo journal của
          phiếu chi Odoo tự sinh. Chưa có payment (mới approve, chưa post) thì
          bỏ qua chờ lần sync sau — KHÔNG tự chế Có 331.
        """
        if 'hr.expense' not in self.env:
            return {'created': 0, 'skipped': 0, 'no_hr_expense': True}
        domain = [
            ('company_id', '=', company.id),
            ('state', 'in', ADVANCE_SETTLED_STATES),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        expenses = self.env['hr.expense'].search(domain)
        ready = expenses.filtered(self._expense_ready_for_settlement)
        waiting = expenses - ready
        if waiting:
            _logger.info(
                'VAS: %s hr.expense company_account chua co payment — bo qua '
                '(cho post xong roi sync lai): %s',
                len(waiting), ', '.join(waiting.mapped('display_name')),
            )
        return self._apply_event('advance_settlement', ready, company)

    def _expense_ready_for_settlement(self, expense):
        """own_account luôn sẵn; company_account cần phiếu chi Odoo đã gắn."""
        if expense.payment_mode != 'company_account':
            return True
        return bool(self._expense_company_payment(expense))

    def _expense_company_payment(self, expense):
        """Phiếu chi Odoo tự sinh khi post expense Paid By = Company."""
        move = expense.account_move_id
        if move and move.origin_payment_id:
            return move.origin_payment_id
        Payment = self.env['account.payment']
        if 'expense_ids' in Payment._fields:
            return Payment.search([('expense_ids', 'in', expense.ids)], limit=1)
        return Payment

    def _advance_split(self, expense):
        """Chia số phải trả của một khoản chi thành phần trừ 141 và phần nợ 334.

        Có 141 **tối đa** bằng số dư Nợ 141 còn lại của chính phiếu tạm ứng gốc;
        phần vượt đẩy sang Có 334 (T05). Không có phiếu tạm ứng gốc thì toàn bộ
        vào 334 (E1) — cùng bản chất: công ty nợ người lao động.

        Thứ tự tiêu tạm ứng chốt theo `(date, id)` nên nhiều khoản chi cùng ăn
        một phiếu tạm ứng vẫn chia ra kết quả giống nhau ở mọi lượt đồng bộ,
        không phụ thuộc khoản nào được ghi sổ trước.
        """
        total = abs(expense.total_amount or 0.0)
        payment = expense.vas_advance_payment_id
        if not payment:
            return {'advance_applied': 0.0, 'advance_excess': total, 'remaining': 0.0}
        used = 0.0
        siblings = self.env['hr.expense'].search([
            ('vas_advance_payment_id', '=', payment.id),
            ('state', 'in', ADVANCE_SETTLED_STATES),
        ], order='date, id')
        for sibling in siblings:
            if sibling.id == expense.id:
                break
            used += abs(sibling.total_amount or 0.0)
        remaining = max(abs(payment.amount or 0.0) - used, 0.0)
        applied = min(total, remaining)
        return {
            'advance_applied': applied,
            'advance_excess': total - applied,
            'remaining': remaining,
        }

    def _sync_employee_debt_payments(self, company, date_from, date_to):
        """R19f — trả nốt phần công ty còn nợ người lao động (Nợ 334 / Có 111·112).

        Nhận cả phiếu gắn nhãn tay `employee_debt_payment` VÀ phiếu sinh từ nút
        Register Payment của Odoo (không nhãn, gắn hr.expense own_account).
        KHÔNG nhận company_account — ca đó đi R19g, không qua 334.
        """
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        settles = payments.filtered(self._is_employee_debt_payment)
        return self._apply_event('employee_debt_payment', settles, company)

    def _is_employee_debt_payment(self, payment):
        """Bốn điều kiện cho R19f — xem KE_HOACH / đợt sửa hr.expense."""
        if payment.payment_type != 'outbound':
            return False
        if payment.vas_operation_type == 'employee_debt_payment':
            return True
        if payment.vas_operation_type:
            # Nhãn khác (tạm ứng, ký quỹ, …) không vào R19f.
            return False
        if not self._payment_linked_to_expense(payment):
            return False
        expenses = self._expenses_of_payment(payment)
        return bool(expenses) and all(
            e.payment_mode == 'own_account' for e in expenses
        )

    def _expenses_of_payment(self, payment):
        """Mọi `hr.expense` gắn với payment — company_account lẫn Register Payment."""
        expenses = self.env['hr.expense']
        if 'expense_ids' in payment._fields and payment.expense_ids:
            expenses |= payment.expense_ids
        move = payment.move_id
        if move and 'expense_ids' in move._fields and move.expense_ids:
            expenses |= move.expense_ids
        Move = self.env['account.move']
        if 'matched_payment_ids' in Move._fields:
            bills = Move.search([
                ('matched_payment_ids', 'in', payment.ids),
                ('expense_ids', '!=', False),
            ])
            expenses |= bills.expense_ids
        return expenses

    def _sync_advance_refunds(self, company, date_from, date_to):
        """R19e — T04 bước 2: phiếu THU nhãn `advance_refund` → Nợ 111/112 / Có 141."""
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        refunds = payments.filtered(
            lambda p: p.vas_operation_type == 'advance_refund'
            and p.payment_type == 'inbound'
        )
        return self._apply_event('advance_refund', refunds, company)

    def _sync_cash_transfers(self, company, date_from, date_to):
        """R20: một payment mang nhãn ``internal_transfer`` + sổ đích → một bút toán.

        Tiền rời ``journal_id`` (Có) và vào ``vas_dest_journal_id`` (Nợ);
        111 hay 112 do loại của từng sổ quyết định (T06 / T07).
        """
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        transfers = payments.filtered(self._is_cash_transfer_payment)
        return self._apply_event('cash_transfer', transfers, company)

    def _sync_deposits(self, company, date_from, date_to):
        """R21: ký quỹ/ký cược theo nhãn + chiều tiền (T08, T10 bước 1–2)."""
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        deposits = payments.filtered(
            lambda p: p.vas_operation_type in ('deposit_out', 'deposit_in')
        )
        return self._apply_event('deposit', deposits, company)

    def _sync_loan_and_capital(self, company, date_from, date_to):
        """W7 R26–R30: payment nhãn vay/vốn/cổ tức.

        Giải ngân trả NCC và góp vốn hiện vật là chứng từ/sự kiện VAS
        (vas.loan.disbursement / vas.capital.in.kind) — không đọc misc JE Odoo.
        """
        stats = {
            'payments': {'created': 0, 'skipped': 0, 'errors': 0},
        }
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        labeled = payments.filtered(
            lambda p: p.vas_operation_type in self._W7_PAYMENT_OPS
        )
        for payment in labeled:
            try:
                move = self._sync_one_w7_payment(payment, company)
                if move:
                    stats['payments']['created'] += 1
                else:
                    stats['payments']['skipped'] += 1
            except Exception:
                stats['payments']['errors'] += 1
                _logger.exception(
                    'VAS W7 payment sync failed payment=%s op=%s',
                    payment.id, payment.vas_operation_type,
                )
        return stats

    def _w7_cash_account(self, payment, company):
        regime = company.vas_regime_id
        journal = payment.journal_id
        fx = self._payment_fx_cash_code(payment, company)
        if fx:
            return self._account_by_code(regime, fx)
        code = '111' if journal and journal.type == 'cash' else '112'
        return self._account_by_code(regime, code)

    def _w7_loan_account(self, loan, company, fallbacks=None):
        if loan:
            return loan._resolve_loan_account(fallbacks)
        acc = self._account_by_code(company.vas_regime_id, '3411')
        if fallbacks is not None:
            fallbacks.append({
                'label': _(
                    'thanh toán vay — không gắn thẻ, dùng mặc định 3411',
                ),
            })
        return acc

    def _sync_one_w7_payment(self, payment, company):
        op = payment.vas_operation_type
        kind_map = {
            'loan_receipt': 'loan_receipt',
            'loan_repay': 'loan_repay',
            'loan_interest_pay': 'loan_interest_pay',
            'loan_interest_pay_direct': 'loan_interest_pay',
            'capital_receipt': 'capital_receipt',
            'dividend_pay': 'dividend_pay',
            'dividend_tax_pay': 'dividend_tax_pay',
        }
        move_kind = kind_map[op]
        if self._already_synced(payment._name, payment.id, move_kind):
            return self.env['vas.move']

        if op in ('loan_receipt', 'loan_repay') and not payment.vas_loan_id:
            raise UserError(_(
                'Payment %(p)s (%(op)s) thiếu Thẻ vay VAS.',
                p=payment.display_name, op=op,
            ))

        # direct-pay overlap với line lãi
        if op == 'loan_interest_pay_direct' and payment.vas_loan_id:
            self._w7_handle_direct_interest_overlap(payment)

        amount = abs(payment.amount)
        if float_is_zero(amount, precision_digits=2):
            return self.env['vas.move']

        regime = company.vas_regime_id
        cash = self._w7_cash_account(payment, company)
        loan = payment.vas_loan_id
        partner = payment.partner_id
        fallbacks = []

        if op == 'loan_receipt':
            debit, credit = cash, self._w7_loan_account(loan, company, fallbacks)
        elif op == 'loan_repay':
            debit, credit = self._w7_loan_account(loan, company, fallbacks), cash
        elif op == 'loan_interest_pay':
            if loan:
                _exp, payable = loan._resolve_interest_accounts(fallbacks)
            else:
                payable = self._account_by_code(regime, '335')
                fallbacks.append({
                    'label': _(
                        'thanh toán lãi %(p)s — không gắn thẻ vay, dùng mặc định 335',
                        p=payment.display_name,
                    ),
                })
            debit, credit = payable, cash
        elif op == 'loan_interest_pay_direct':
            if loan:
                expense, _pay = loan._resolve_interest_accounts(fallbacks)
            else:
                expense = self._account_by_code(regime, '635')
                fallbacks.append({
                    'label': _(
                        'trả lãi thẳng %(p)s — không gắn thẻ vay, dùng mặc định 635',
                        p=payment.display_name,
                    ),
                })
            debit, credit = expense, cash
        elif op == 'capital_receipt':
            debit, credit = cash, self._account_by_code(regime, '4111')
        elif op == 'dividend_pay':
            debit, credit = self._account_by_code(regime, '3388'), cash
        elif op == 'dividend_tax_pay':
            debit, credit = self._account_by_code(regime, '3335'), cash
        else:
            return self.env['vas.move']

        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'THU'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS THU/TH.'))

        move = self.env['vas.move'].create({
            'date': payment.date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': move_kind,
            'ref': payment.memo or payment.name,
            'source_model': payment._name,
            'source_res_id': payment.id,
            'source_ref': payment.name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': [
                Command.create({
                    'sequence': 10, 'account_id': debit.id,
                    'name': payment.name, 'debit': amount, 'credit': 0.0,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
                Command.create({
                    'sequence': 20, 'account_id': credit.id,
                    'name': payment.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
            ],
            **self._default_account_flag_vals(fallbacks),
        })
        posted = self._post_or_flag_period_missing(move)
        if not posted:
            return self.env['vas.move']
        move = posted
        if op == 'loan_repay' and loan:
            loan.invalidate_recordset(['outstanding_principal'])
            loan._compute_outstanding_principal()
            loan.flush_recordset(['outstanding_principal'])
            loan.action_recompute_planned_amounts()
        return move

    def _w7_handle_direct_interest_overlap(self, payment):
        """§9: planned → skip+WARN; posted → chặn."""
        loan = payment.vas_loan_id
        Period = self.env['vas.period']
        period = Period.search([
            ('fiscalyear_id.company_id', '=', payment.company_id.id),
            ('date_start', '<=', payment.date),
            ('date_end', '>=', payment.date),
        ], limit=1)
        if not period:
            return
        posted = loan.line_ids.filtered(
            lambda l: l.period_id == period and l.state == 'posted'
        )
        if posted:
            raise UserError(_(
                'Đã trích lãi (Có 335) kỳ %(p)s cho thẻ %(loan)s. '
                'Không dùng loan_interest_pay_direct — hãy trả qua '
                'loan_interest_pay (Nợ 335) hoặc đảo JE trích trước.',
                p=period.display_name, loan=loan.display_name,
            ))
        loan.skip_planned_interest_for_period(
            period, reason='payment %s' % payment.name,
        )

    def _sync_payment_discounts(self, company, date_from, date_to):
        """R23 FALLBACK: write-off lines on payment.move_id, else invoice_total − paid."""
        payments = self._search_payments(company, date_from, date_to, payment_type=None)
        discounted = payments.filtered(lambda p: self._payment_discount_amount(p) > 0)
        return self._apply_event('payment_discount', discounted, company)

    def _search_payments(self, company, date_from, date_to, payment_type):
        domain = [
            ('company_id', '=', company.id),
            ('state', 'in', ('in_process', 'paid')),
        ]
        if payment_type:
            domain.append(('payment_type', '=', payment_type))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return self.env['account.payment'].search(domain)

    # -------------------------------------------------------------------------
    # W3 classifiers (FALLBACK-aware)
    # -------------------------------------------------------------------------

    def _employee_for_partner(self, partner):
        if not partner or 'hr.employee' not in self.env:
            return self.env['hr.employee'] if 'hr.employee' in self.env else False
        Employee = self.env['hr.employee']
        return Employee.search([
            '|',
            ('work_contact_id', '=', partner.id),
            ('user_id.partner_id', '=', partner.id),
        ], limit=1)

    def _payment_reconcile_counterpart_moves(self, payment):
        """account.move records reconciled with this payment's receivable/payable lines."""
        if not payment.move_id:
            return self.env['account.move']
        lines = payment.move_id.line_ids.filtered(lambda l: l.account_id.reconcile)
        moves = self.env['account.move']
        for line in lines:
            for partial in line.matched_debit_ids:
                other = partial.debit_move_id if partial.credit_move_id == line else partial.credit_move_id
                if other.move_id != payment.move_id:
                    moves |= other.move_id
            for partial in line.matched_credit_ids:
                other = partial.credit_move_id if partial.debit_move_id == line else partial.debit_move_id
                if other.move_id != payment.move_id:
                    moves |= other.move_id
        return moves

    def _payment_reconciled_to_invoice(self, payment):
        moves = self._payment_reconcile_counterpart_moves(payment)
        return bool(moves.filtered(lambda m: m.is_invoice(include_receipts=True)))

    def _payment_reconciled_to_payslip(self, payment):
        if 'hr.payslip' not in self.env:
            return False
        moves = self._payment_reconcile_counterpart_moves(payment)
        if not moves:
            return False
        Payslip = self.env['hr.payslip']
        # Odoo 19 payslip may not expose move_id; probe known link fields.
        for fname in ('move_id', 'account_move_id', 'slip_id'):
            if fname in Payslip._fields and Payslip._fields[fname].comodel_name == 'account.move':
                return bool(Payslip.search_count([(fname, 'in', moves.ids)]))
        return False

    def _is_employee_advance_payment(self, payment):
        """R19: nhãn employee_advance + đối tác là NLĐ; loại trừ hr.expense."""
        if not payment.partner_id:
            return False
        if payment.vas_operation_type != 'employee_advance':
            return False
        # D5(b): giữ nguyên loại trừ hoàn tiền hr.expense — nguồn đó là của R19c/R19d
        if self._payment_linked_to_expense(payment):
            return False
        if self._payment_reconciled_to_payslip(payment):
            return False
        if self._payment_reconciled_to_invoice(payment):
            return False
        return bool(self._employee_for_partner(payment.partner_id))

    def _payment_discount_amount(self, payment):
        """R23: write-off lines only when linked invoices are fully closed.

        No invoice−paid fallback (that mis-labels partial payments as discount).
        """
        if not payment.move_id:
            return 0.0
        invoices = self.env['account.move']
        if 'reconciled_invoice_ids' in payment._fields:
            invoices |= payment.reconciled_invoice_ids
        if 'reconciled_bill_ids' in payment._fields:
            invoices |= payment.reconciled_bill_ids
        if not invoices and 'invoice_ids' in payment._fields:
            invoices = payment.invoice_ids
        if not invoices:
            return 0.0
        # All must be fully closed
        if any(not float_is_zero(inv.amount_residual, precision_digits=2) for inv in invoices):
            return 0.0
        try:
            liquidity_accounts = payment._get_valid_liquidity_accounts()
        except Exception:
            liquidity_accounts = self.env['account.account']
        transfer = payment.company_id.transfer_account_id
        wo = 0.0
        for line in payment.move_id.line_ids:
            acc = line.account_id
            if acc in liquidity_accounts:
                continue
            if acc.account_type in ('asset_receivable', 'liability_payable'):
                continue
            if transfer and acc == transfer:
                continue
            wo += abs(line.balance)
        return wo if not float_is_zero(wo, precision_digits=2) else 0.0

    def _is_cash_transfer_payment(self, payment):
        """R20: chỉ nhận diện bằng nhãn người dùng chọn, không đoán theo ngày/số tiền."""
        return payment.vas_operation_type == 'internal_transfer'

    # -------------------------------------------------------------------------
    # R01/R02 delivery-aware revenue + R17 residual helpers
    # -------------------------------------------------------------------------

    def _sale_line_gross_qty_out(self, sale_line):
        """Số lượng đã xuất đi khách (done), không trừ phiếu trả.

        `qty_delivered` Odoo là net (xuất − trả) → sau trả một phần bị thấp
        giả và biến HĐ đã giao đủ thành ``partial``. R01/R02 dùng gross.
        """
        if not sale_line:
            return 0.0
        if hasattr(sale_line, '_get_outgoing_incoming_moves'):
            outgoing, _incoming = sale_line._get_outgoing_incoming_moves()
            qty = 0.0
            uom = sale_line.product_uom_id
            for move in outgoing:
                if move.state != 'done':
                    continue
                qty += move.product_uom._compute_quantity(
                    move.quantity, uom, rounding_method='HALF-UP',
                )
            return qty
        return sale_line.qty_delivered or 0.0

    def _invoice_line_sale_lines(self, inv_line):
        if 'sale_line_ids' in inv_line._fields and inv_line.sale_line_ids:
            return inv_line.sale_line_ids
        move = inv_line.move_id
        if 'sale_line_ids' in move.line_ids._fields:
            return move.line_ids.sale_line_ids.filtered(
                lambda s: s.product_id == inv_line.product_id
            )
        return self.env['sale.order.line']

    def _sale_invoice_delivery_ratio(self, invoice):
        """Tỷ lệ DT đã giao (0..1) — xuất gross / SL trên HĐ, cân theo subtotal.

        Dịch vụ / không tồn kho: hệ số 1. HĐ không dòng SP lưu kho → 1.
        """
        product_lines = invoice.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note') and l.product_id
        )
        if not product_lines:
            return 1.0
        storable = product_lines.filtered(
            lambda l: getattr(l.product_id, 'is_storable', False)
        )
        if not storable:
            return 1.0
        recognized = 0.0
        total_weight = 0.0
        for line in product_lines:
            weight = line.price_subtotal or 0.0
            total_weight += weight
            if not getattr(line.product_id, 'is_storable', False):
                recognized += weight
                continue
            qty_inv = line.quantity or 0.0
            if float_is_zero(qty_inv, precision_digits=2):
                continue
            sols = self._invoice_line_sale_lines(line)
            gross = sum(self._sale_line_gross_qty_out(sol) for sol in sols)
            factor = min(max(gross, 0.0), qty_inv) / qty_inv
            recognized += weight * factor
        if float_is_zero(total_weight, precision_digits=2):
            # Subtotal 0 (toàn CK) — fallback theo số lượng dòng lưu kho.
            qty_inv = sum(storable.mapped('quantity'))
            if float_is_zero(qty_inv, precision_digits=2):
                return 1.0
            gross = 0.0
            for line in storable:
                sols = self._invoice_line_sale_lines(line)
                gross += sum(self._sale_line_gross_qty_out(sol) for sol in sols)
            return max(0.0, min(1.0, gross / qty_inv))
        ratio = recognized / total_weight
        if float_compare(ratio, 0.0, precision_digits=4) <= 0:
            return 0.0
        if float_compare(ratio, 1.0, precision_digits=4) >= 0:
            return 1.0
        return ratio

    def _sale_invoice_delivery_status(self, invoice):
        """Return 'none' | 'full' | 'partial' (dựa xuất gross, không net trả hàng)."""
        ratio = self._sale_invoice_delivery_ratio(invoice)
        if float_is_zero(ratio, precision_digits=4):
            return 'none'
        if float_compare(ratio, 1.0, precision_digits=4) >= 0:
            return 'full'
        return 'partial'

    def _invoice_vas_revenue_booked(self, invoice):
        """Tổng Có 511* đã ghi cho HĐ (sale_inv) + DT lúc giao gắn SOL của HĐ."""
        Move = self.env['vas.move']
        amount = 0.0
        inv_moves = Move.search([
            ('source_model', '=', invoice._name),
            ('source_res_id', '=', invoice.id),
            ('move_kind', '=', 'sale_inv'),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ])
        for line in inv_moves.mapped('line_ids'):
            if (line.account_id.code or '').startswith('511'):
                amount += line.credit - line.debit
        sols = self.env['sale.order.line']
        for aml in invoice.invoice_line_ids:
            sols |= self._invoice_line_sale_lines(aml)
        stock_moves = sols.mapped('move_ids').filtered(
            lambda m: m.state == 'done' and m.location_dest_usage == 'customer'
        )
        if stock_moves:
            rev_moves = Move.search([
                ('source_model', '=', 'stock.move'),
                ('source_res_id', 'in', stock_moves.ids),
                ('move_kind', '=', 'revenue'),
                ('state', '=', 'posted'),
                ('is_reversal', '=', False),
            ])
            for line in rev_moves.mapped('line_ids'):
                if (line.account_id.code or '').startswith('511'):
                    amount += line.credit - line.debit
        return amount

    def _invoice_has_vas_revenue(self, invoice):
        return float_compare(
            self._invoice_vas_revenue_booked(invoice), 0.0, precision_digits=2,
        ) > 0

    # -------------------------------------------------------------------------
    # GTGT 1A — khớp thuế suất (dữ liệu vas.tax) + tách dòng sổ theo suất
    # -------------------------------------------------------------------------

    def _collect_invoice_tax_buckets(self, invoice, scope, event_type=None):
        """Gom dòng HĐ theo vas.tax đã khớp (hoặc undetermined).

        Mỗi bucket: tax (recordset), status, warning, amls, untaxed, tax, total.
        Không mặc định thuế suất khi không khớp.
        """
        if event_type == 'purchase_invoice':
            amls = self._goods_lines(invoice)
        elif event_type == 'goods_in_transit':
            amls = self._goods_lines(invoice)
        elif event_type == 'purchase_service':
            amls = self._service_lines(invoice)
        elif event_type == 'purchase_landed_tax':
            amls = self._landed_lines(invoice)
        else:
            amls = self._real_invoice_lines(invoice)
        date = invoice.invoice_date or invoice.date
        company = invoice.company_id
        Tax = self.env['vas.tax']
        ordered = []
        index = {}
        for aml in amls:
            odoo_taxes = aml.tax_ids
            empty = not odoo_taxes
            tax, status, warn = Tax.find_for_invoice_line(
                company, date, scope,
                odoo_taxes=odoo_taxes,
                empty_taxes=empty,
            )
            if warn:
                _logger.warning(
                    'VAS tax match invoice=%s line=%s: %s',
                    invoice.display_name, aml.display_name, warn,
                )
            key = ('resolved', tax.id) if status == 'resolved' and tax else (
                'undetermined', False
            )
            if key not in index:
                index[key] = {
                    'vas_tax': tax,
                    'status': status,
                    'warning': warn,
                    'amls': self.env['account.move.line'],
                    'untaxed': 0.0,
                    'tax_amount': 0.0,
                    'total': 0.0,
                }
                ordered.append(key)
            bucket = index[key]
            bucket['amls'] |= aml
            if self._invoice_uses_signed_line_amounts(invoice, scope):
                untaxed = aml.price_subtotal or 0.0
                total = aml.price_total or 0.0
            else:
                untaxed = abs(aml.price_subtotal or 0.0)
                total = abs(aml.price_total or 0.0)
            bucket['untaxed'] += untaxed
            bucket['total'] += total
            bucket['tax_amount'] += total - untaxed
            if warn and not bucket.get('warning'):
                bucket['warning'] = warn
        buckets = [index[k] for k in ordered]
        if self._invoice_uses_signed_line_amounts(invoice, scope):
            buckets = self._fold_negative_output_tax_buckets(buckets)
        return buckets

    def _fold_negative_output_tax_buckets(self, buckets):
        """Dồn bucket CK (untaxed/thuế âm) vào bucket dương — không ghi Có 511 số âm."""
        pos = [b for b in buckets if (b['untaxed'] or 0.0) > 0]
        neg = [b for b in buckets if (b['untaxed'] or 0.0) < 0]
        neg += [
            b for b in buckets
            if b not in neg
            and float_is_zero(b['untaxed'] or 0.0, precision_digits=2)
            and (b['tax_amount'] or 0.0) < 0
        ]
        if not neg:
            return buckets
        if not pos:
            return buckets
        pos_untaxed = sum(b['untaxed'] for b in pos)
        for n in neg:
            if float_is_zero(pos_untaxed, precision_digits=2):
                break
            nu, nt, ntot = n['untaxed'], n['tax_amount'], n['total']
            allocated_u = allocated_t = allocated_tot = 0.0
            for p in pos[:-1]:
                share = p['untaxed'] / pos_untaxed
                du = round(nu * share, 2)
                dt = round(nt * share, 2)
                dtt = round(ntot * share, 2)
                p['untaxed'] += du
                p['tax_amount'] += dt
                p['total'] += dtt
                allocated_u += du
                allocated_t += dt
                allocated_tot += dtt
            last = pos[-1]
            last['untaxed'] += nu - allocated_u
            last['tax_amount'] += nt - allocated_t
            last['total'] += ntot - allocated_tot
            n['untaxed'] = n['tax_amount'] = n['total'] = 0.0
        return [
            b for b in buckets
            if not (
                float_is_zero(b['untaxed'], precision_digits=2)
                and float_is_zero(b['tax_amount'], precision_digits=2)
            )
        ]

    def _product_amount_splits_for_amls(
        self, amls, selector, amount_selector, company, amount, fallbacks=None,
        cost_fallbacks=None, positive_weights_only=False,
    ):
        """Như ``_product_amount_splits`` nhưng trên tập AML đã chọn (một suất thuế)."""
        if float_is_zero(amount, precision_digits=2):
            return []
        field = 'price_total' if amount_selector == 'total' else 'price_subtotal'
        weights = []
        for line in amls:
            w = line[field] or 0.0
            if positive_weights_only:
                if w <= 0:
                    continue
                weights.append((line.product_id, w))
            else:
                weights.append((line.product_id, abs(w)))
        attach_cost = selector == 'product_expense'
        buckets = {}
        total_weight = 0.0
        for product, weight in weights:
            account = self._product_account(product, selector, company, fallbacks)
            if not account:
                continue
            cost_item = False
            if attach_cost:
                cost_item = self._product_cost_item(
                    product, company, cost_fallbacks,
                )
            key = (account.id, cost_item.id if cost_item else False)
            bucket = buckets.setdefault(key, [account, cost_item, 0.0])
            bucket[2] += weight
            total_weight += weight
        if not buckets:
            account = self._product_account(
                self.env['product.product'], selector, company, fallbacks,
            )
            cost_item = False
            if attach_cost:
                cost_item = self._product_cost_item(
                    self.env['product.product'], company, cost_fallbacks,
                )
            return [(account, amount, cost_item)]
        items = list(buckets.values())
        if len(items) == 1 or float_is_zero(total_weight, precision_digits=2):
            return [(items[0][0], amount, items[0][1])]
        splits = []
        allocated = 0.0
        for account, cost_item, weight in items[:-1]:
            part = round(amount * weight / total_weight, 2)
            allocated += part
            splits.append((account, part, cost_item))
        last_acc, last_cost, _last_w = items[-1]
        splits.append((last_acc, round(amount - allocated, 2), last_cost))
        return [
            (account, part, cost_item) for account, part, cost_item in splits
            if not float_is_zero(part, precision_digits=2)
        ]

    def _product_amount_splits_for_amls_industry(
        self, amls, selector, amount_selector, company, amount, fallbacks=None,
        positive_weights_only=False,
    ):
        """Tách doanh thu theo (TK, nhóm ngành) — gắn chiều trực tiếp lên dòng 511."""
        if float_is_zero(amount, precision_digits=2):
            return []
        field = 'price_total' if amount_selector == 'total' else 'price_subtotal'
        buckets = {}
        total_weight = 0.0
        for aml in amls:
            product = aml.product_id
            raw = aml[field] or 0.0
            if positive_weights_only:
                if raw <= 0:
                    continue
                weight = raw
            else:
                weight = abs(raw)
            account = self._product_account(product, selector, company, fallbacks)
            if not account:
                continue
            industry = (
                product.vas_gtgt_direct_industry_id
                if product and product.vas_gtgt_direct_industry_id
                else self.env['vas.gtgt.direct.industry']
            )
            status = 'resolved' if industry else 'undetermined'
            key = (account.id, industry.id if industry else 0, status)
            bucket = buckets.setdefault(key, [account, industry, status, 0.0])
            bucket[3] += weight
            total_weight += weight
        if not buckets:
            account = self._product_account(
                self.env['product.product'], selector, company, fallbacks,
            )
            return [(
                account, amount, False,
                self.env['vas.gtgt.direct.industry'], 'undetermined',
            )]
        items = list(buckets.values())
        if len(items) == 1 or float_is_zero(total_weight, precision_digits=2):
            acc, ind, st, _w = items[0]
            return [(acc, amount, False, ind, st)]
        splits = []
        allocated = 0.0
        for account, industry, status, weight in items[:-1]:
            part = round(amount * weight / total_weight, 2)
            allocated += part
            splits.append((account, part, False, industry, status))
        last_acc, last_ind, last_st, _lw = items[-1]
        splits.append((
            last_acc, round(amount - allocated, 2), False, last_ind, last_st,
        ))
        return [
            row for row in splits
            if not float_is_zero(row[1], precision_digits=2)
        ]

    def _snapshot_ledger_by_account(self, company, date_from=None, date_to=None):
        """Số bút toán + tổng Nợ/Có theo TK — dùng kiểm D3 backfill ngành."""
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['vas.move'].search(domain)
        by_account = {}
        for line in moves.mapped('line_ids'):
            code = line.account_id.code or ''
            slot = by_account.setdefault(code, {'debit': 0.0, 'credit': 0.0})
            slot['debit'] += line.debit
            slot['credit'] += line.credit
        return {
            'move_count': len(moves),
            'by_account': {
                k: {
                    'debit': round(v['debit'], 2),
                    'credit': round(v['credit'], 2),
                }
                for k, v in sorted(by_account.items())
            },
        }

    @api.model
    def backfill_direct_industry(self, company, date_from=None, date_to=None):
        """Chỉ BỔ SUNG nhóm ngành trên dòng DT còn thiếu — không đổi số tiền / không tạo BT.

        Trước/sau: số bút toán và tổng tiền theo TK phải bằng tuyệt đối — lệch → DỪNG.
        """
        before = self._snapshot_ledger_by_account(company, date_from, date_to)
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
            ('source_model', '=', 'account.move'),
            ('source_res_id', '!=', False),
            ('move_kind', 'in', ('sale_inv', 'refund')),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['vas.move'].search(domain)
        filled = 0
        undetermined = 0
        for move in moves:
            invoice = self.env['account.move'].browse(move.source_res_id).exists()
            if not invoice:
                continue
            rev_lines = move.line_ids.filtered(
                lambda l: (l.account_id.code or '').startswith('511') and l.credit > 0
                and l.direct_industry_status in ('none', 'undetermined')
                and not l.direct_industry_id
            )
            if not rev_lines:
                continue
            industries = set()
            missing = 0
            for aml in invoice.invoice_line_ids.filtered(
                lambda l: l.display_type not in ('line_section', 'line_note')
            ):
                ind = aml.product_id.vas_gtgt_direct_industry_id if aml.product_id else False
                if ind:
                    industries.add(ind.id)
                else:
                    missing += 1
            if len(industries) == 1 and missing == 0:
                ind = self.env['vas.gtgt.direct.industry'].browse(list(industries)[0])
                rev_lines.with_context(
                    vas_allow_posted_write=True,
                    vas_skip_period_check=True,
                ).write({
                    'direct_industry_id': ind.id,
                    'direct_industry_status': 'resolved',
                })
                filled += len(rev_lines)
            else:
                rev_lines.with_context(
                    vas_allow_posted_write=True,
                    vas_skip_period_check=True,
                ).write({
                    'direct_industry_id': False,
                    'direct_industry_status': 'undetermined',
                })
                undetermined += len(rev_lines)
        after = self._snapshot_ledger_by_account(company, date_from, date_to)
        if before != after:
            raise UserError(_(
                'D3 — backfill nhóm ngành làm lệch sổ: trước %(b)s · sau %(a)s. DỪNG.',
                b=before, a=after,
            ))
        result = {
            'before': before,
            'after': after,
            'filled': filled,
            'undetermined': undetermined,
        }
        _logger.info('VAS direct industry backfill company=%s %s', company.id, result)
        return result

    def _tax_line_vals(self, tax, status):
        """Giá trị tax_id / tax_status gắn lên dòng doanh thu·chi phí·thuế."""
        if status == 'resolved' and tax:
            return {'tax_id': tax.id, 'tax_status': 'resolved'}
        if status == 'undetermined':
            return {'tax_id': False, 'tax_status': 'undetermined'}
        return {'tax_id': False, 'tax_status': 'none'}

    def _snapshot_tax_ledger(self, company, date_from=None, date_to=None):
        """Đếm bút toán + tổng |thuế| theo TK — dùng kiểm bất biến backfill."""
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['vas.move'].search(domain)
        tax_codes = ('33311', '1331', '33312', '133', '3331')
        by_account = {}
        for line in moves.mapped('line_ids'):
            code = line.account_id.code or ''
            if code not in tax_codes:
                continue
            by_account.setdefault(code, 0.0)
            by_account[code] += abs((line.debit or 0.0) - (line.credit or 0.0))
        by_account = {k: round(v, 2) for k, v in sorted(by_account.items())}
        return {
            'move_count': len(moves),
            'tax_by_account': by_account,
            'tax_total': round(sum(by_account.values()), 2),
        }

    @api.model
    def backfill_line_tax_ids(self, company, date_from=None, date_to=None):
        """Chỉ BỔ SUNG tax_id/tax_status — không sửa số tiền, không tạo bút toán.

        Trước/sau: số bút toán và tổng tiền thuế theo TK phải bằng tuyệt đối.
        """
        before = self._snapshot_tax_ledger(company, date_from, date_to)
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
            ('source_model', '=', 'account.move'),
            ('source_res_id', '!=', False),
            ('move_kind', 'in', (
                'sale_inv', 'purchase_inv', 'expense', 'revenue', 'refund',
            )),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['vas.move'].search(domain)
        filled = 0
        undetermined = 0
        skipped_multi = 0
        for move in moves:
            invoice = self.env['account.move'].browse(move.source_res_id).exists()
            if not invoice:
                continue
            scope = 'output' if invoice.move_type in (
                'out_invoice', 'out_refund',
            ) else 'input'
            event = None
            if move.move_kind == 'purchase_inv':
                event = 'purchase_invoice'
            elif move.move_kind == 'expense':
                event = 'purchase_service'
            buckets = self._collect_invoice_tax_buckets(
                invoice, scope, event_type=event,
            )
            # Dòng cần gắn thuế: doanh thu (511*), chi phí (642*), thuế (33311/1331)
            target_lines = move.line_ids.filtered(
                lambda l: (
                    (l.account_id.code or '').startswith('511')
                    or (l.account_id.code or '').startswith('642')
                    or (l.account_id.code or '') in (
                        '33311', '1331', '33312', '133', '3331',
                    )
                )
            )
            if not target_lines:
                continue
            if len(buckets) == 1:
                bucket = buckets[0]
                tax_vals = self._tax_line_vals(bucket['vas_tax'], bucket['status'])
                to_write = target_lines.filtered(
                    lambda l: not l.tax_id and l.tax_status in ('none', 'undetermined')
                )
                if to_write:
                    to_write.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write(tax_vals)
                    filled += len(to_write)
                    if tax_vals.get('tax_status') == 'undetermined':
                        undetermined += len(to_write)
            else:
                # Nhiều suất trên HĐ cũ đã gộp — không tách dòng; đánh dấu chưa xác định
                # nếu chưa có tax_id (không đụng số tiền).
                skipped_multi += 1
                bare = target_lines.filtered(lambda l: not l.tax_id)
                if bare:
                    bare.with_context(
                        vas_allow_posted_write=True,
                        vas_skip_period_check=True,
                    ).write({'tax_id': False, 'tax_status': 'undetermined'})
                    undetermined += len(bare)

        after = self._snapshot_tax_ledger(company, date_from, date_to)
        if (
            before['move_count'] != after['move_count']
            or before['tax_by_account'] != after['tax_by_account']
        ):
            raise UserError(_(
                "Backfill thuế suất làm lệch sổ — DỪNG.\n"
                "Trước: moves=%(bm)s tax=%(bt)s\n"
                "Sau: moves=%(am)s tax=%(at)s",
                bm=before['move_count'], bt=before['tax_by_account'],
                am=after['move_count'], at=after['tax_by_account'],
            ))
        result = {
            'before': before,
            'after': after,
            'lines_filled': filled,
            'lines_undetermined': undetermined,
            'moves_multi_rate_skipped_split': skipped_multi,
        }
        _logger.info('VAS tax backfill company=%s %s', company.id, result)
        return result

    def _generate_sale_invoice_move(self, rule, invoice, company, revenue_ratio=1.0):
        """R01: tách doanh thu + thuế theo suất; DT = untaxed × ratio (policy B).

        ``revenue_ratio`` 0..1: chưa giao → chỉ thuế; giao từng phần → DT tỷ lệ;
        giao đủ → DT đủ. Thuế đầu ra luôn theo HĐ (đủ).
        """
        buckets = self._collect_invoice_tax_buckets(invoice, 'output')
        untaxed = sum(b['untaxed'] for b in buckets)
        tax = sum(b['tax_amount'] for b in buckets)
        ratio = max(0.0, min(1.0, revenue_ratio or 0.0))
        revenue = round(untaxed * ratio, 2) if untaxed > 0 else 0.0
        if float_is_zero(tax, precision_digits=2) and float_is_zero(revenue, precision_digits=2):
            return self.env['vas.move']
        regime = company.vas_regime_id
        acc_131 = self._account_by_code(regime, '131')
        acc_33311 = self._account_by_code(regime, '33311')
        if not acc_131 or not acc_33311:
            raise UserError(_("Missing VAS accounts 131/33311 for sale invoice."))
        lines = []
        seq = 10
        fallbacks = []
        debit_131 = tax + revenue
        if debit_131 > 0 and not float_is_zero(debit_131, precision_digits=2):
            lines.append(Command.create({
                'sequence': seq, 'account_id': acc_131.id, 'name': rule.name,
                'debit': debit_131, 'credit': 0.0,
                'partner_id': invoice.partner_id.id,
                'currency_id': company.currency_id.id,
                'tax_status': 'none',
            }))
            seq += 10
        if not float_is_zero(revenue, precision_digits=2):
            # Chia DT theo bucket; phần làm tròn dồn bucket cuối có untaxed > 0.
            pos_buckets = [
                b for b in buckets
                if b['untaxed'] > 0 and not float_is_zero(b['untaxed'], precision_digits=2)
            ]
            allocated_rev = 0.0
            for idx, bucket in enumerate(pos_buckets):
                if idx == len(pos_buckets) - 1:
                    bucket_rev = round(revenue - allocated_rev, 2)
                else:
                    bucket_rev = round(revenue * (bucket['untaxed'] / untaxed), 2)
                    allocated_rev += bucket_rev
                if float_is_zero(bucket_rev, precision_digits=2):
                    continue
                tax_vals = self._tax_line_vals(bucket['vas_tax'], bucket['status'])
                signed = self._invoice_uses_signed_line_amounts(invoice, 'output')
                for account, part, _cost, industry, ind_status in (
                    self._product_amount_splits_for_amls_industry(
                        bucket['amls'], 'product_revenue', 'untaxed', company,
                        bucket_rev, fallbacks,
                        positive_weights_only=signed,
                    )
                ):
                    if not account:
                        raise UserError(_("Missing VAS revenue account for sale invoice."))
                    if part <= 0:
                        continue
                    lines.append(Command.create({
                        'sequence': seq, 'account_id': account.id, 'name': rule.name,
                        'debit': 0.0, 'credit': part,
                        'partner_id': invoice.partner_id.id,
                        'currency_id': company.currency_id.id,
                        'direct_industry_id': industry.id if industry else False,
                        'direct_industry_status': ind_status,
                        **tax_vals,
                    }))
                    seq += 10
        for bucket in buckets:
            if bucket['tax_amount'] <= 0 or float_is_zero(bucket['tax_amount'], precision_digits=2):
                continue
            tax_vals = self._tax_line_vals(bucket['vas_tax'], bucket['status'])
            lines.append(Command.create({
                'sequence': seq, 'account_id': acc_33311.id, 'name': rule.name,
                'debit': 0.0, 'credit': bucket['tax_amount'],
                'partner_id': invoice.partner_id.id,
                'currency_id': company.currency_id.id,
                **tax_vals,
            }))
            seq += 10
        if not lines:
            return self.env['vas.move']
        if float_is_zero(ratio, precision_digits=4):
            ref_suffix = _(' (thuế — chưa giao)')
        elif float_compare(ratio, 1.0, precision_digits=4) < 0:
            ref_suffix = _(' (DT %(pct)s%% đã giao)', pct=int(round(ratio * 100)))
        else:
            ref_suffix = ''
        journal = self._resolve_journal('sale_invoice', invoice, company)
        move = self.env['vas.move'].create({
            'date': invoice.invoice_date or invoice.date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'sale_inv',
            'ref': rule.name + ref_suffix,
            'source_model': invoice._name,
            'source_res_id': invoice.id,
            'source_ref': invoice.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': lines,
            **self._default_account_flag_vals(fallbacks),
        })
        return self._post_or_flag_period_missing(move)

    def _generate_purchase_invoice_tax_split_move(
        self, rule, record, company, move_kind, event_type,
    ):
        """R07/R08/R26: tách chi phí + thuế đầu vào theo từng thuế suất."""
        buckets = self._collect_invoice_tax_buckets(
            record, 'input', event_type=event_type,
        )
        if not buckets:
            self._note_unvalued(record, rule)
            return self.env['vas.move']
        line_commands = []
        seq = 10
        fallbacks = []
        cost_fallbacks = []
        partner = self._source_partner(record)
        for rline in rule.line_ids.sorted(lambda l: (l.sequence, l.id)):
            selector = rline.amount_selector
            if selector == 'tax':
                for bucket in buckets:
                    if float_is_zero(bucket['tax_amount'], precision_digits=2):
                        continue
                    account = self._resolve_account(
                        rline, record, company.vas_regime_id, event_type,
                    )
                    if not account:
                        raise UserError(_(
                            "Cannot resolve VAS account for rule %(rule)s tax line.",
                            rule=rule.code,
                        ))
                    tax_vals = self._tax_line_vals(bucket['vas_tax'], bucket['status'])
                    vals = {
                        'sequence': seq,
                        'account_id': account.id,
                        'name': rule.name,
                        'partner_id': partner.id if partner else False,
                        'currency_id': company.currency_id.id,
                        **tax_vals,
                    }
                    if rline.side == 'debit':
                        vals['debit'] = bucket['tax_amount']
                        vals['credit'] = 0.0
                    else:
                        vals['debit'] = 0.0
                        vals['credit'] = bucket['tax_amount']
                    line_commands.append(Command.create(vals))
                    seq += 10
                continue
            if selector == 'untaxed':
                for bucket in buckets:
                    if float_is_zero(bucket['untaxed'], precision_digits=2):
                        continue
                    tax_vals = self._tax_line_vals(bucket['vas_tax'], bucket['status'])
                    if rline.account_selector in PRODUCT_ACCOUNT_SELECTOR:
                        splits = self._product_amount_splits_for_amls(
                            bucket['amls'], rline.account_selector, 'untaxed',
                            company, bucket['untaxed'], fallbacks, cost_fallbacks,
                        )
                    else:
                        account = self._resolve_account(
                            rline, record, company.vas_regime_id, event_type,
                        )
                        splits = [(account, bucket['untaxed'], False)]
                    for account, part, split_cost_item in splits:
                        if not account:
                            raise UserError(_(
                                "Cannot resolve VAS account for rule %(rule)s.",
                                rule=rule.code,
                            ))
                        vals = {
                            'sequence': seq,
                            'account_id': account.id,
                            'name': rule.name,
                            'partner_id': partner.id if partner else False,
                            'currency_id': company.currency_id.id,
                            **tax_vals,
                        }
                        if rline.side == 'debit':
                            vals['debit'] = part
                            vals['credit'] = 0.0
                        else:
                            vals['debit'] = 0.0
                            vals['credit'] = part
                        if split_cost_item:
                            vals['cost_item_id'] = split_cost_item.id
                        line_commands.append(Command.create(vals))
                        seq += 10
                continue
            # total / khác: một dòng tổng, không gắn thuế suất
            amount = self._resolve_amount(selector, record, event_type)
            if not amount:
                continue
            for account, part, split_cost_item in self._account_splits(
                rline, record, company, amount, fallbacks, event_type,
                cost_fallbacks,
            ):
                if not account:
                    raise UserError(_(
                        "Cannot resolve VAS account for rule %(rule)s.",
                        rule=rule.code,
                    ))
                vals = {
                    'sequence': seq,
                    'account_id': account.id,
                    'name': rule.name,
                    'partner_id': partner.id if partner else False,
                    'currency_id': company.currency_id.id,
                    'tax_status': 'none',
                }
                if rline.side == 'debit':
                    vals['debit'] = part
                    vals['credit'] = 0.0
                else:
                    vals['debit'] = 0.0
                    vals['credit'] = part
                if split_cost_item:
                    vals['cost_item_id'] = split_cost_item.id
                line_commands.append(Command.create(vals))
                seq += 10

        if not line_commands:
            self._note_unvalued(record, rule)
            return self.env['vas.move']

        journal = self._resolve_journal(event_type, record, company)
        date = self._source_date(record)
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': journal.id,
            'regime_id': company.vas_regime_id.id,
            'move_kind': move_kind,
            'ref': rule.name,
            'source_model': record._name,
            'source_res_id': record.id,
            'source_ref': record.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': line_commands,
            **self._merge_move_flag_vals(
                self._default_account_flag_vals(fallbacks),
                self._unclassified_cost_flag_vals(cost_fallbacks),
            ),
        })
        return self._post_or_flag_period_missing(move)

    def _generate_delivery_revenue_move(self, stock_move, company):
        """R02 add-on: ghi thêm 511 khi tỷ lệ đã giao > phần DT đã book trên HĐ."""
        if self._stock_move_is_pos(stock_move):
            return self.env['vas.move']
        if self._already_synced(stock_move._name, stock_move.id, 'revenue'):
            return self.env['vas.move']
        invoices = self.env['account.move']
        if 'sale_line_id' in stock_move._fields and stock_move.sale_line_id:
            invoices = stock_move.sale_line_id.invoice_lines.move_id.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
            )
        if not invoices:
            return self.env['vas.move']
        to_book = 0.0
        need = self.env['account.move']
        for inv in invoices:
            # Chưa có JE thuế/HĐ thì để R01 ghi trước (cùng lượt sync: invoice trước delivery).
            if not self._already_synced(inv._name, inv.id, 'sale_inv'):
                continue
            ratio = self._sale_invoice_delivery_ratio(inv)
            target = round(max(inv.amount_untaxed or 0.0, 0.0) * ratio, 2)
            booked = self._invoice_vas_revenue_booked(inv)
            gap = round(target - booked, 2)
            if gap > 0 and not float_is_zero(gap, precision_digits=2):
                to_book += gap
                need |= inv
        if not need or float_is_zero(to_book, precision_digits=2):
            return self.env['vas.move']
        regime = company.vas_regime_id
        acc_131 = self._account_by_code(regime, '131')
        journal = self._resolve_journal('sale_delivery', stock_move, company)
        lines = [Command.create({
            'sequence': 10, 'account_id': acc_131.id, 'name': _('DT lúc giao'),
            'debit': to_book, 'credit': 0.0,
            'partner_id': stock_move.partner_id.id if stock_move.partner_id else (
                need[:1].partner_id.id
            ),
            'currency_id': company.currency_id.id,
        })]
        seq = 20
        fallbacks = []
        for account, part, _cost in self._product_amount_splits(
            need, 'product_revenue', 'untaxed', company, to_book, fallbacks,
        ):
            lines.append(Command.create({
                'sequence': seq, 'account_id': account.id, 'name': _('DT lúc giao'),
                'debit': 0.0, 'credit': part,
                'partner_id': need[:1].partner_id.id,
                'currency_id': company.currency_id.id,
            }))
            seq += 10
        move = self.env['vas.move'].create({
            'date': self._source_date(stock_move),
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'revenue',
            'ref': _('Doanh thu khi giao hàng'),
            'source_model': stock_move._name,
            'source_res_id': stock_move.id,
            'source_ref': stock_move.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': lines,
            **self._default_account_flag_vals(fallbacks),
        })
        return self._post_or_flag_period_missing(move)

    def _vas_all_131_331_lines(self, odoo_move, code_prefix):
        """All VAS 131/331 lines for invoice/bill (incl. residual=0 and delivery revenue)."""
        vas_moves = self.env['vas.move'].search([
            ('source_model', '=', odoo_move._name),
            ('source_res_id', '=', odoo_move.id),
            ('state', '=', 'posted'),
            ('is_reversal', '=', False),
        ])
        if odoo_move.is_sale_document(include_receipts=True) and code_prefix.startswith('131'):
            sols = self.env['sale.order.line']
            for aml in odoo_move.invoice_line_ids:
                if 'sale_line_ids' in aml._fields:
                    sols |= aml.sale_line_ids
            stock_ids = sols.mapped('move_ids').ids if sols else []
            if stock_ids:
                vas_moves |= self.env['vas.move'].search([
                    ('source_model', '=', 'stock.move'),
                    ('source_res_id', 'in', stock_ids),
                    ('move_kind', '=', 'revenue'),
                    ('state', '=', 'posted'),
                    ('is_reversal', '=', False),
                ])
        return vas_moves.mapped('line_ids').filtered(
            lambda l: (l.account_id.code or '').startswith(code_prefix) and l.account_id.reconcile
        )

    def _vas_find_131_331_lines(self, odoo_move, code_prefix):
        """Open VAS subledger 131/331 lines for an Odoo invoice/bill."""
        return self._vas_all_131_331_lines(odoo_move, code_prefix).filtered(
            lambda l: not float_is_zero(l.amount_residual, precision_digits=2)
        )

    def _vas_find_131_331_line(self, odoo_move, code_prefix):
        """First open VAS 131/331 line for an Odoo invoice/bill (compat helper)."""
        return self._vas_find_131_331_lines(odoo_move, code_prefix)[:1]

    def _vas_reset_line_residual(self, line):
        bal = (line.debit or 0.0) - (line.credit or 0.0)
        line.with_context(
            vas_allow_reconcile_write=True,
            vas_allow_posted_write=True,
            vas_skip_period_check=True,
        ).write({
            'amount_residual': bal,
            'amount_residual_currency': line.amount_currency or bal,
            'reconciled': False,
            'full_reconcile_id': False,
            'matching_number': False,
        })

    def _vas_apply_amount_across_lines(self, lines, amount, full_reconcile=None, matching_number=None):
        """Reduce residuals across multiple lines until ``amount`` is consumed."""
        remaining = abs(amount)
        for line in lines.sorted(key=lambda l: abs(l.amount_residual)):
            if float_is_zero(remaining, precision_digits=2):
                break
            take = min(remaining, abs(line.amount_residual))
            if float_is_zero(take, precision_digits=2):
                continue
            line._vas_apply_match(take, full_reconcile=full_reconcile, matching_number=matching_number)
            remaining -= take
        return remaining

    def _vas_odoo_matched_amount(self, move):
        """How much of move's AR/AP has been reconciled in Odoo."""
        amls = move.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
        )
        matched = 0.0
        for aml in amls:
            matched += abs(aml.balance) - abs(aml.amount_residual)
        return matched

    def _vas_rebuild_invoice_residual(self, inv_move):
        """Idempotent: set VAS residuals from Odoo matched + posted VAS debt offsets."""
        if not inv_move.is_invoice(include_receipts=True):
            return
        prefix = '131' if inv_move.is_sale_document(include_receipts=True) else '331'
        vas_lines = self._vas_all_131_331_lines(inv_move, prefix)
        if not vas_lines:
            return
        for line in vas_lines:
            self._vas_reset_line_residual(line)
        original = sum(abs((l.debit or 0.0) - (l.credit or 0.0)) for l in vas_lines)
        matched = min(self._vas_odoo_matched_amount(inv_move), original)
        if not float_is_zero(matched, precision_digits=2):
            full = self.env['vas.full.reconcile'].create({
                'name': f'INV/{inv_move.id}/rebuild',
            })
            self._vas_apply_amount_across_lines(
                vas_lines, matched, full_reconcile=full, matching_number=full.name,
            )
        # Re-apply VAS-owned debt offsets (R22) — not visible in Odoo native
        if 'vas.debt.offset.line' in self.env:
            OffsetLine = self.env['vas.debt.offset.line']
            for line in vas_lines:
                for ol in OffsetLine.search([
                    ('move_line_id', '=', line.id),
                    ('offset_id.state', '=', 'posted'),
                ]):
                    line._vas_apply_match(ol.amount)

    def _vas_apply_payment_partials(self, payment, vas_payment_move):
        """Rebuild VAS residuals from Odoo partial.reconcile (idempotent on re-sync)."""
        if not payment.move_id:
            return
        pay_vas_line = vas_payment_move.line_ids.filtered(
            lambda l: (l.account_id.code or '')[:3] in ('131', '331') and l.account_id.reconcile
        )[:1]
        if not pay_vas_line:
            return
        odoo_pay_lines = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
        )
        Partial = self.env['account.partial.reconcile']
        partials = Partial.search([
            '|',
            ('debit_move_id', 'in', odoo_pay_lines.ids),
            ('credit_move_id', 'in', odoo_pay_lines.ids),
        ])
        invoices = self.env['account.move']
        for partial in partials:
            counterpart = (
                partial.debit_move_id
                if partial.credit_move_id in odoo_pay_lines
                else partial.credit_move_id
            )
            if counterpart.move_id.is_invoice(include_receipts=True):
                invoices |= counterpart.move_id
        for inv in invoices:
            self._vas_rebuild_invoice_residual(inv)
        # Payment line residual — FX: khớp theo principal (book/settle ma trận),
        # không theo settle VND trên AML Odoo (tránh lệch sổ 131/331).
        self._vas_reset_line_residual(pay_vas_line)
        original = abs((pay_vas_line.debit or 0.0) - (pay_vas_line.credit or 0.0))
        company = payment.company_id or vas_payment_move.company_id
        fx_principal = self._payment_fx_principal_amount(payment, company)
        if fx_principal is not None:
            matched = min(fx_principal, original)
        else:
            matched = min(self._vas_odoo_matched_amount(payment.move_id), original)
        if float_is_zero(matched, precision_digits=2):
            return  # advance / unreconciled — full residual on payment 131/331
        full = self.env['vas.full.reconcile'].create({
            'name': f'PAY/{payment.id}/{vas_payment_move.id}',
        })
        pay_vas_line._vas_apply_match(matched, full_reconcile=full, matching_number=full.name)

    # -------------------------------------------------------------------------
    # R17/R18 FX principal + R24 shared book/settle
    # -------------------------------------------------------------------------

    def _payment_is_foreign(self, payment, company):
        """Thanh toán / công nợ gốc ngoại tệ (≠ tiền công ty)."""
        company_cur = company.currency_id
        if payment.currency_id and payment.currency_id != company_cur:
            return True
        for inv in (
            getattr(payment, 'reconciled_invoice_ids', self.env['account.move'])
            | getattr(payment, 'reconciled_bill_ids', self.env['account.move'])
        ):
            if inv.currency_id and inv.currency_id != company_cur:
                return True
        return False

    def _payment_debt_partials(self, payment):
        """Partials khớp AR/AP gắn JE thanh toán (hoặc outstanding đã reconcile)."""
        Partial = self.env['account.partial.reconcile']
        if not payment.move_id:
            return Partial
        odoo_pay_lines = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type in (
                'asset_receivable', 'liability_payable',
            )
        )
        if not odoo_pay_lines:
            return Partial
        return Partial.search([
            '|',
            ('debit_move_id', 'in', odoo_pay_lines.ids),
            ('credit_move_id', 'in', odoo_pay_lines.ids),
        ])

    def _payment_fx_awaiting_reconcile(self, payment, company):
        """True = payment FX đã post nhưng chưa có partial khớp HĐ → chưa ghi R17/R18."""
        if not self._payment_is_foreign(payment, company):
            return False
        return not bool(self._payment_debt_partials(payment))

    def _payment_fx_cash_code(self, payment, company):
        """1112/1122 khi payment ngoại tệ; False khi VND (để bank_cash mặc định)."""
        if not self._payment_is_foreign(payment, company):
            return False
        journal = payment.journal_id
        is_cash = journal and journal.type == 'cash'
        return '1112' if is_cash else '1122'

    def _payment_fx_principal_amount(self, payment, company):
        """Số GỐC R17/R18 khi ngoại tệ; None = dùng abs(payment.amount) (VND).

        Mỗi partial: principal = book nếu settle≥book, else settle.
        Cộng dồn; partial không phải cặp công nợ FX → cộng partial.amount (VND lẫn).
        """
        if not self._payment_is_foreign(payment, company):
            return None
        partials = self._payment_debt_partials(payment)
        if not partials:
            return None
        total = 0.0
        for partial in partials:
            info = self._forex_book_settle_for_partial(partial, company)
            if info:
                # Bỏ partial phụ EXCH (book không phải HĐ/bill) — tránh cộng thêm |diff|.
                if not info['book_aml'].move_id.is_invoice(include_receipts=True):
                    continue
                book_vnd = info['book_vnd']
                settle_vnd = info['settle_vnd']
                if settle_vnd >= book_vnd:
                    total += book_vnd
                else:
                    total += settle_vnd
            else:
                total += abs(partial.amount or 0.0)
        return round(total, 2)

    def _forex_book_settle_for_partial(self, partial, company):
        """book_vnd / settle_vnd trên partial công nợ — dùng chung R17/R18 + R24.

        Không lọc diff≈0 (R24 tự skip). Trả None nếu không phải cặp AR/AP↔đối ứng.
        """
        debit = partial.debit_move_id
        credit = partial.credit_move_id
        if not debit or not credit:
            return None
        debt_types = ('asset_receivable', 'liability_payable')
        if debit.account_id.account_type not in debt_types:
            return None
        if credit.account_id.account_type not in debt_types:
            return None
        if debit.account_id.account_type != credit.account_id.account_type:
            return None

        debt_side = (
            'ar' if debit.account_id.account_type == 'asset_receivable' else 'ap'
        )
        book_aml, settle_aml = self._forex_book_settle_amls(debit, credit)
        if not book_aml or not settle_aml:
            return None

        book_vnd = self._forex_matched_company_amount(
            book_aml,
            partial.debit_amount_currency if book_aml == debit
            else partial.credit_amount_currency,
        )
        settle_vnd = self._forex_matched_company_amount(
            settle_aml,
            partial.debit_amount_currency if settle_aml == debit
            else partial.credit_amount_currency,
        )
        if float_is_zero(book_vnd, precision_digits=2) and float_is_zero(
            settle_vnd, precision_digits=2,
        ):
            return None

        cash_code = self._forex_cash_account_code(settle_aml, company)
        return {
            'debt_side': debt_side,
            'book_vnd': book_vnd,
            'settle_vnd': settle_vnd,
            'diff': settle_vnd - book_vnd,
            'cash_code': cash_code,
            'book_aml': book_aml,
            'settle_aml': settle_aml,
        }

    # (debt_side, pnl) → rule code. Sync chọn rule; không dùng condition trên partial.
    _FOREX_RULE_CODE = {
        ('ar', 'gain'): 'R24a',  # Nợ tiền / Có 515
        ('ar', 'loss'): 'R24b',  # Nợ 635 / Có 131
        ('ap', 'loss'): 'R24c',  # Nợ 635 / Có tiền
        ('ap', 'gain'): 'R24d',  # Nợ 331 / Có 515
    }

    def _sync_forex_realized(self, company, date_from=None, date_to=None):
        """Sinh JE R24 cho mỗi partial có exchange_move_id (chỉ phần chênh).

        Không đọc số dư EXCH 441/641 — tự tính settle_vnd − book_vnd.
        """
        if not company.vas_regime_id:
            return {'created': 0, 'skipped': 0}
        Partial = self.env['account.partial.reconcile']
        domain = [('exchange_move_id', '!=', False)]
        # Cửa sổ theo ngày EXCH (ngày TT thực tế).
        if date_from:
            domain.append(('exchange_move_id.date', '>=', date_from))
        if date_to:
            domain.append(('exchange_move_id.date', '<=', date_to))
        cutoff = company.vas_start_date
        if cutoff:
            domain.append(('exchange_move_id.date', '>=', cutoff))
        partials = Partial.search(domain)
        # Lọc company qua AML (partial.company_id có thể trống trên một số bản).
        partials = partials.filtered(
            lambda p: (
                (p.company_id and p.company_id == company)
                or p.debit_move_id.company_id == company
                or p.credit_move_id.company_id == company
            )
        )
        move_kind = EVENT_MOVE_KIND['forex_realized']
        rules = self._find_rules('forex_realized', company.vas_regime_id)
        created = skipped = 0
        for partial in partials:
            if self._already_synced(partial._name, partial.id, move_kind):
                skipped += 1
                continue
            info = self._forex_realized_info(partial, company)
            if not info:
                skipped += 1
                continue
            rule_code = self._FOREX_RULE_CODE.get((info['debt_side'], info['pnl']))
            rule = rules.filtered(lambda r: r.code == rule_code)[:1]
            if not rule:
                _logger.warning(
                    'VAS R24: thiếu rule %s (regime=%s) — skip partial %s',
                    rule_code, company.vas_regime_id.code, partial.id,
                )
                skipped += 1
                continue
            move = self.with_context(
                vas_forex_diff=info['diff_abs'],
                vas_forex_cash_code=info['cash_code'],
            )._generate_move(
                rule, partial, company, move_kind, event_type='forex_realized',
            )
            if move:
                created += 1
            else:
                skipped += 1
        return {'created': created, 'skipped': skipped}

    def _forex_realized_info(self, partial, company):
        """Phân tích partial+EXCH → book/settle/diff + AR/AP + mã tiền VAS.

        Trả dict hoặc None nếu không đủ điều kiện (không phải công nợ, diff≈0…).
        """
        base = self._forex_book_settle_for_partial(partial, company)
        if not base:
            return None

        diff = base['diff']
        if company.currency_id.is_zero(diff):
            return None

        debt_side = base['debt_side']
        pnl = 'gain' if diff > 0 else 'loss'
        # AR: diff>0 lãi, diff<0 lỗ; AP: diff>0 lỗ, diff<0 lãi — map qua _FOREX_RULE_CODE.
        if debt_side == 'ap':
            pnl = 'loss' if diff > 0 else 'gain'

        return {
            'debt_side': debt_side,
            'pnl': pnl,
            'book_vnd': base['book_vnd'],
            'settle_vnd': base['settle_vnd'],
            'diff': diff,
            'diff_abs': abs(diff),
            'cash_code': base['cash_code'],
            'book_aml': base['book_aml'],
            'settle_aml': base['settle_aml'],
        }

    def _forex_book_settle_amls(self, debit, credit):
        """Xác định AML công nợ gốc (book) vs AML đối ứng thanh toán (settle)."""
        def score(aml):
            move = aml.move_id
            # Hóa đơn/bill gốc → book
            if move.is_invoice(include_receipts=True):
                return (0, move.date or fields.Date.today(), aml.id)
            # Sổ ngân hàng / quỹ / payment → settle
            if move.journal_id.type in ('bank', 'cash'):
                return (2, move.date or fields.Date.today(), aml.id)
            if getattr(move, 'originator_payment_id', False) or getattr(move, 'payment_id', False):
                return (2, move.date or fields.Date.today(), aml.id)
            # EXCH không phải cặp book/settle của partial nguồn
            return (1, move.date or fields.Date.today(), aml.id)

        ranked = sorted([debit, credit], key=score)
        book, settle = ranked[0], ranked[1]
        # Cần đúng một bên invoice-like và một bên payment-like khi có thể.
        if score(book)[0] == score(settle)[0]:
            # Fallback: ngày sớm hơn = book (TG ghi sổ)
            if (debit.date or debit.move_id.date) <= (credit.date or credit.move_id.date):
                return debit, credit
            return credit, debit
        return book, settle

    def _forex_matched_company_amount(self, aml, amount_currency_matched):
        """VND tương ứng phần nguyên tệ đã khớp trên AML."""
        fc = abs(aml.amount_currency or 0.0)
        matched_fc = abs(amount_currency_matched or 0.0)
        balance = abs(aml.balance or 0.0)
        if float_is_zero(fc, precision_digits=6) or float_is_zero(matched_fc, precision_digits=6):
            return balance
        return round(balance * matched_fc / fc, 2)

    def _forex_cash_account_code(self, settle_aml, company):
        """1112/1122 khi nguyên tệ; 111/112 khi nội tệ — theo journal settle."""
        move = settle_aml.move_id
        journal = move.journal_id
        foreign = bool(
            settle_aml.currency_id
            and settle_aml.currency_id != company.currency_id
        )
        is_cash = journal and journal.type == 'cash'
        if foreign:
            return '1112' if is_cash else '1122'
        return '111' if is_cash else '112'

    # Models quét cancel; fingerprint kho không vào đây.
    _CANCEL_SOURCE_MODELS = (
        'account.move',
        'account.payment',
        'hr.expense',
        'vas.debt.offset',
        'vas.import.vat',
        'account.partial.reconcile',  # R24: unreconcile/unlink partial → đảo JE
        'vas.asset.line',
        'vas.asset',
        'vas.loan.line',
        'vas.loan',
        'vas.loan.disbursement',
        'vas.profit.distribution',
        'vas.capital.in.kind',
        'hr.payslip',  # W9 soft — chỉ chết khi model có trong registry
        'pos.order',
        'pos.session',
        'account.bank.statement.line',  # POS rút/bỏ tiền giữa ca
        'stock.landed.cost',
        'stock.valuation.adjustment.lines',  # nguồn JE R25
        'stock.scrap',
        'vas.inventory.provision',
    )

    _W7_PAYMENT_OPS = frozenset({
        'loan_receipt', 'loan_repay',
        'loan_interest_pay', 'loan_interest_pay_direct',
        'capital_receipt', 'dividend_pay', 'dividend_tax_pay',
    })
    _W9_PAYMENT_OPS = frozenset({
        'payroll_pay', 'social_insurance_remit', 'pit_remit', 'union_fee_remit',
    })

    _PAYSLIP_DED_MAP = (
        ('BHXH_EE', '3383'),
        ('BHYT_EE', '3384'),
        ('BHTN_EE', '3385'),
        ('PIT', '3335'),
    )
    _PAYSLIP_ER_MAP = (
        # (codes_sum, account) — TNLD gộp 3383 với BHXH_ER
        (('BHXH_ER', 'TNLD_ER'), '3383'),
        (('BHYT_ER',), '3384'),
        (('BHTN_ER',), '3385'),
        (('KPCD_ER',), '3382'),
    )

    def _sync_cancel_regressions(self, company):
        """Đảo vas.move khi nguồn đã sync bị hủy/reset (non-stock).

        Quét MỌI JE sống (mọi kỳ, không bó cửa sổ ngày). Kỳ mở + nguồn chết →
        action_reverse. Kỳ đã khóa + nguồn chết → gắn cờ, không đảo (Q1).
        """
        stats = {
            'scanned': 0,
            'dead_sources': 0,
            'reversed': 0,
            'closed_period_flagged': 0,
            'errors': 0,
        }
        cutoff = company.vas_start_date
        domain = [
            ('company_id', '=', company.id),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
            ('source_model', 'in', list(self._CANCEL_SOURCE_MODELS)),
            ('source_res_id', '!=', 0),
            ('source_res_id', '!=', False),
        ]
        if cutoff:
            domain.append(('date', '>=', cutoff))
        moves = self.env['vas.move'].search(domain)
        stats['scanned'] = len(moves)
        if not moves:
            return stats

        # Group by source key → đảo tất cả kind của cùng nguồn chết (§2.4).
        by_source = {}
        for move in moves:
            key = (move.source_model, move.source_res_id)
            by_source.setdefault(key, self.env['vas.move'])
            by_source[key] |= move

        dead_keys = []
        for (model, res_id), group in by_source.items():
            if self._source_is_dead(model, res_id):
                dead_keys.append((model, res_id))
        stats['dead_sources'] = len(dead_keys)

        for model, res_id in dead_keys:
            group = by_source[(model, res_id)]
            for move in group:
                # Resolve kỳ theo ngày+công ty LÚC cancel — không tin
                # period_id stored lúc post (có thể False nếu kỳ tạo sau,
                # hoặc lệch khi trùng nhiều kỳ). Kỳ khóa → tuyệt đối không đảo.
                if self._move_date_in_closed_period(move):
                    if not move.source_cancel_pending:
                        move.with_context(
                            vas_allow_posted_write=True,
                            vas_skip_period_check=True,
                        ).write({'source_cancel_pending': True})
                    stats['closed_period_flagged'] += 1
                    _logger.warning(
                        'VAS cancel: nguồn chết nhưng kỳ đã khóa — cần đảo tay. '
                        'move=%s source=%s(%s)',
                        move.display_name, model, res_id,
                    )
                    continue
                try:
                    move.action_reverse()
                    stats['reversed'] += 1
                except Exception:
                    stats['errors'] += 1
                    _logger.exception(
                        'VAS cancel reverse failed move=%s source=%s(%s)',
                        move.id, model, res_id,
                    )
        return stats

    def _move_date_in_closed_period(self, move):
        """True nếu ngày move nằm trong kỳ closed — ủy quyền helper W9.5."""
        return self.env['vas.period']._date_in_closed_period(
            move.company_id, move.date,
        )

    def _source_is_dead(self, source_model, source_res_id):
        """True nếu nguồn mất (Q8) hoặc state thuộc tập chết (Q2/Q3/…)."""
        if source_model not in self._CANCEL_SOURCE_MODELS:
            return False
        if source_model not in self.env:
            return True
        record = self.env[source_model].browse(source_res_id).exists()
        if not record:
            return True  # Q8 unlink
        if source_model == 'account.move':
            # Q2: payment_state=reversed mà vẫn posted → KHÔNG chết
            return record.state in ('cancel', 'draft')
        if source_model == 'account.payment':
            # Q3: unreconcile không tính
            return record.state in ('canceled', 'rejected', 'draft')
        if source_model == 'hr.expense':
            return record.state in ('refused', 'draft')
        if source_model == 'vas.debt.offset':
            return record.state == 'cancelled'
        if source_model == 'vas.import.vat':
            return record.state == 'cancelled'
        if source_model == 'account.partial.reconcile':
            # Q8 unlink đã chết ở trên; còn tồn tại nhưng mất EXCH → cũng đảo.
            return not record.exchange_move_id
        if source_model == 'vas.asset.line':
            return (
                not record.exists()
                or record.state == 'skipped'
                or record.asset_id.state == 'cancelled'
            )
        if source_model == 'vas.asset':
            return record.state == 'cancelled'
        if source_model == 'vas.loan.line':
            return (
                not record.exists()
                or record.state == 'skipped'
                or record.loan_id.state == 'cancelled'
            )
        if source_model == 'vas.loan':
            return record.state == 'cancelled'
        if source_model == 'vas.loan.disbursement':
            return record.state == 'cancelled'
        if source_model == 'vas.profit.distribution':
            return record.state == 'cancelled'
        if source_model == 'vas.capital.in.kind':
            return record.state == 'cancelled'
        if source_model == 'hr.payslip':
            return record.state == 'cancel'
        if source_model == 'pos.order':
            return record.state == 'cancel'
        if source_model == 'pos.session':
            # Đóng rồi mở lại (opening_control / opened) → đảo bút toán kết ca.
            return record.state in ('opening_control', 'opened')
        if source_model == 'account.bank.statement.line':
            return not record.exists()
        if source_model == 'stock.landed.cost':
            return record.state in ('cancel', 'draft')
        if source_model == 'stock.valuation.adjustment.lines':
            cost = record.cost_id
            return (
                not record.exists()
                or not cost
                or cost.state != 'done'
            )
        if source_model == 'stock.scrap':
            return record.state != 'done'
        if source_model == 'vas.inventory.provision':
            return record.state in ('cancelled', 'reversed')
        return False

    # -------------------------------------------------------------------------
    # W9 — Payroll soft adapter (hr.payslip → vas.move)
    # -------------------------------------------------------------------------

    @api.model
    def _hr_payslip_available(self):
        return 'hr.payslip' in self.env

    def _register_hook(self):
        """Soft-patch action_payslip_done khi hr_payroll đã cài."""
        super()._register_hook()
        if not self._hr_payslip_available():
            return
        Payslip = type(self.env['hr.payslip'])
        if getattr(Payslip, '_vas_payroll_hooked', False):
            return

        origin = Payslip.action_payslip_done

        def action_payslip_done_vas(payslips):
            res = origin(payslips)
            Sync = payslips.env['vas.sync']
            for slip in payslips:
                try:
                    Sync._sync_one_payslip(slip, slip.company_id)
                except Exception:
                    _logger.exception(
                        'VAS payroll sync after validate failed payslip=%s',
                        slip.id,
                    )
            return res

        Payslip.action_payslip_done = action_payslip_done_vas
        Payslip._vas_payroll_hooked = True

    def _sync_payroll(self, company, date_from=None, date_to=None):
        """Scan payslip validated + payment nhãn payroll. Soft: no-op nếu thiếu model."""
        stats = {
            'payslips': {'created': 0, 'skipped': 0, 'errors': 0},
            'payments': {'created': 0, 'skipped': 0, 'errors': 0},
        }
        if self._hr_payslip_available():
            Payslip = self.env['hr.payslip']
            domain = [
                ('company_id', '=', company.id),
                ('state', 'in', ('validated', 'paid')),
            ]
            if date_from:
                domain.append(('date_to', '>=', date_from))
            if date_to:
                domain.append(('date_from', '<=', date_to))
            if company.vas_start_date:
                domain.append(('date_to', '>=', company.vas_start_date))
            for slip in Payslip.search(domain):
                try:
                    move = self._sync_one_payslip(slip, company)
                    if move:
                        stats['payslips']['created'] += 1
                    else:
                        stats['payslips']['skipped'] += 1
                except Exception:
                    stats['payslips']['errors'] += 1
                    _logger.exception(
                        'VAS payroll payslip sync failed id=%s', slip.id,
                    )

        Payment = self.env['account.payment']
        pay_domain = [
            ('company_id', '=', company.id),
            ('state', 'in', ('in_process', 'paid')),
            ('vas_operation_type', 'in', list(self._W9_PAYMENT_OPS)),
        ]
        if date_from:
            pay_domain.append(('date', '>=', date_from))
        if date_to:
            pay_domain.append(('date', '<=', date_to))
        if company.vas_start_date:
            pay_domain.append(('date', '>=', company.vas_start_date))
        for payment in Payment.search(pay_domain):
            try:
                move = self._sync_one_payroll_payment(payment, company)
                if move:
                    stats['payments']['created'] += 1
                else:
                    stats['payments']['skipped'] += 1
            except Exception:
                stats['payments']['errors'] += 1
                _logger.exception(
                    'VAS payroll payment sync failed id=%s op=%s',
                    payment.id, payment.vas_operation_type,
                )
        return stats

    def _payslip_line_amount(self, payslip, code):
        line = payslip.line_ids.filtered(lambda l: l.code == code)[:1]
        if not line:
            return 0.0
        return abs(line.total)

    def _sync_one_payslip(self, payslip, company):
        """R38+R39+R40 → một vas.move (move_kind=payroll) / payslip."""
        if not self._hr_payslip_available():
            return self.env['vas.move']
        if payslip.state not in ('validated', 'paid'):
            return self.env['vas.move']
        if self._already_synced(payslip._name, payslip.id, 'payroll'):
            return self.env['vas.move']

        regime = company.vas_regime_id
        if not regime:
            return self.env['vas.move']

        gross = self._payslip_line_amount(payslip, 'GROSS')
        if float_is_zero(gross, precision_digits=2):
            return self.env['vas.move']

        department = (
            payslip.employee_id.department_id
            or payslip.version_id.department_id
        )
        fallbacks = []
        cost_fallbacks = []
        cp = self.env['vas.payroll.department.map'].resolve_expense_account(
            company, department, fallbacks=fallbacks,
        )
        cost_item = self.env['vas.payroll.department.map'].resolve_cost_item(
            company, department, fallbacks=cost_fallbacks,
        )
        acc_334 = self._account_by_code(regime, '334')

        lines = []
        seq = 10
        # R38: Nợ CP / Có 334 (GROSS)
        r38_debit = {
            'sequence': seq, 'account_id': cp.id,
            'name': f'R38 {payslip.name}',
            'debit': gross, 'credit': 0.0,
            'currency_id': company.currency_id.id,
            'partner_id': payslip.employee_id.work_contact_id.id
            if payslip.employee_id.work_contact_id else False,
        }
        if cost_item:
            r38_debit['cost_item_id'] = cost_item.id
        lines.append(Command.create(r38_debit))
        seq += 10
        lines.append(Command.create({
            'sequence': seq, 'account_id': acc_334.id,
            'name': f'R38 {payslip.name}',
            'debit': 0.0, 'credit': gross,
            'currency_id': company.currency_id.id,
            'partner_id': payslip.employee_id.work_contact_id.id
            if payslip.employee_id.work_contact_id else False,
        }))
        seq += 10

        # R39: Nợ 334 / Có 338x|3335
        for code, acct in self._PAYSLIP_DED_MAP:
            amt = self._payslip_line_amount(payslip, code)
            if float_is_zero(amt, precision_digits=2):
                continue
            credit_acc = self._account_by_code(regime, acct)
            lines.append(Command.create({
                'sequence': seq, 'account_id': acc_334.id,
                'name': f'R39 {code}',
                'debit': amt, 'credit': 0.0,
                'currency_id': company.currency_id.id,
            }))
            seq += 10
            lines.append(Command.create({
                'sequence': seq, 'account_id': credit_acc.id,
                'name': f'R39 {code}',
                'debit': 0.0, 'credit': amt,
                'currency_id': company.currency_id.id,
            }))
            seq += 10

        # R40: Nợ CP / Có 338x
        for codes, acct in self._PAYSLIP_ER_MAP:
            amt = sum(self._payslip_line_amount(payslip, c) for c in codes)
            if float_is_zero(amt, precision_digits=2):
                continue
            credit_acc = self._account_by_code(regime, acct)
            r40_debit = {
                'sequence': seq, 'account_id': cp.id,
                'name': f'R40 {"+".join(codes)}',
                'debit': amt, 'credit': 0.0,
                'currency_id': company.currency_id.id,
            }
            if cost_item:
                r40_debit['cost_item_id'] = cost_item.id
            lines.append(Command.create(r40_debit))
            seq += 10
            lines.append(Command.create({
                'sequence': seq, 'account_id': credit_acc.id,
                'name': f'R40 {"+".join(codes)}',
                'debit': 0.0, 'credit': amt,
                'currency_id': company.currency_id.id,
            }))
            seq += 10

        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'LUONG'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('type', '=', 'payroll'),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS LUONG (payroll).'))

        move_date = payslip.date_to or payslip.date_from
        move = self.env['vas.move'].create({
            'date': move_date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': 'payroll',
            'ref': payslip.name or f'Payslip {payslip.id}',
            'source_model': payslip._name,
            'source_res_id': payslip.id,
            'source_ref': payslip.name or f'Payslip {payslip.id}',
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': lines,
            **self._merge_move_flag_vals(
                self._default_account_flag_vals(fallbacks),
                self._unclassified_cost_flag_vals(cost_fallbacks),
            ),
        })
        return self._post_or_flag_period_missing(move)

    def _payroll_si_remit_split(self, payment):
        """Số Nợ 3383/3384/3385 khi nộp BHXH gộp (không gồm KPCĐ 3382).

        Ưu tiên đọc từ ``vas_payslip_id`` (soft). Không có phiếu → None
        (caller dùng mã TK đơn lẻ legacy).
        """
        if not payment.vas_payslip_id or not self._hr_payslip_available():
            return None
        slip = self.env['hr.payslip'].browse(payment.vas_payslip_id).exists()
        if not slip:
            return None
        return {
            '3383': (
                self._payslip_line_amount(slip, 'BHXH_EE')
                + self._payslip_line_amount(slip, 'BHXH_ER')
                + self._payslip_line_amount(slip, 'TNLD_ER')
            ),
            '3384': (
                self._payslip_line_amount(slip, 'BHYT_EE')
                + self._payslip_line_amount(slip, 'BHYT_ER')
            ),
            '3385': (
                self._payslip_line_amount(slip, 'BHTN_EE')
                + self._payslip_line_amount(slip, 'BHTN_ER')
            ),
        }

    def _sync_one_payroll_payment(self, payment, company):
        """R41 payroll_pay / R42 SI·union·PIT remit.

        ``social_insurance_remit`` + ``vas_payslip_id`` → Nợ 3383+3384+3385
        (gộp nộp cơ quan BHXH). ``union_fee_remit`` → Nợ 3382 / Có 112
        theo số tiền payment (Nộp từng phần — không đòi tất toán một lệnh).
        """
        op = payment.vas_operation_type
        if op not in self._W9_PAYMENT_OPS:
            return self.env['vas.move']
        kind_map = {
            'payroll_pay': 'payroll_pay',
            'social_insurance_remit': 'payroll_remit',
            'union_fee_remit': 'payroll_remit',
            'pit_remit': 'payroll_remit',
        }
        move_kind = kind_map[op]
        if self._already_synced(payment._name, payment.id, move_kind):
            return self.env['vas.move']

        amount = abs(payment.amount)
        if float_is_zero(amount, precision_digits=2):
            return self.env['vas.move']

        regime = company.vas_regime_id
        cash = self._w7_cash_account(payment, company)
        partner = payment.partner_id
        line_cmds = []

        if op == 'payroll_pay':
            debit = self._account_by_code(regime, '334')
            line_cmds = [
                Command.create({
                    'sequence': 10, 'account_id': debit.id,
                    'name': payment.name, 'debit': amount, 'credit': 0.0,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
                Command.create({
                    'sequence': 20, 'account_id': cash.id,
                    'name': payment.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
            ]
        elif op == 'pit_remit':
            debit = self._account_by_code(regime, '3335')
            line_cmds = [
                Command.create({
                    'sequence': 10, 'account_id': debit.id,
                    'name': payment.name, 'debit': amount, 'credit': 0.0,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
                Command.create({
                    'sequence': 20, 'account_id': cash.id,
                    'name': payment.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
            ]
        elif op == 'union_fee_remit':
            # Nộp từng phần: mỗi payment ghi đúng số tiền Nợ 3382 / Có 112.
            debit = self._account_by_code(regime, '3382')
            line_cmds = [
                Command.create({
                    'sequence': 10, 'account_id': debit.id,
                    'name': payment.name, 'debit': amount, 'credit': 0.0,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
                Command.create({
                    'sequence': 20, 'account_id': cash.id,
                    'name': payment.name, 'debit': 0.0, 'credit': amount,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }),
            ]
        else:  # social_insurance_remit
            split = self._payroll_si_remit_split(payment)
            if split:
                total = sum(split.values())
                if float_compare(amount, total, precision_digits=2) != 0:
                    raise UserError(_(
                        'Payment %(p)s (social_insurance_remit): số tiền %(amt)s '
                        'không khớp tổng BH gộp 3383+3384+3385 = %(total)s '
                        '(từ payslip id=%(slip)s). Không gồm KPCĐ 3382.',
                        p=payment.display_name, amt=amount, total=total,
                        slip=payment.vas_payslip_id,
                    ))
                seq = 10
                for code in ('3383', '3384', '3385'):
                    amt = split[code]
                    if float_is_zero(amt, precision_digits=2):
                        continue
                    acc = self._account_by_code(regime, code)
                    line_cmds.append(Command.create({
                        'sequence': seq, 'account_id': acc.id,
                        'name': f'{payment.name} {code}',
                        'debit': amt, 'credit': 0.0,
                        'currency_id': company.currency_id.id,
                        'partner_id': partner.id if partner else False,
                    }))
                    seq += 10
                line_cmds.append(Command.create({
                    'sequence': seq, 'account_id': cash.id,
                    'name': payment.name, 'debit': 0.0, 'credit': total,
                    'currency_id': company.currency_id.id,
                    'partner_id': partner.id if partner else False,
                }))
            else:
                # Legacy: một TK (mặc định 3383) khi chưa gắn payslip.
                code = payment.vas_payroll_remit_account_code or '3383'
                debit = self._account_by_code(regime, code)
                line_cmds = [
                    Command.create({
                        'sequence': 10, 'account_id': debit.id,
                        'name': payment.name, 'debit': amount, 'credit': 0.0,
                        'currency_id': company.currency_id.id,
                        'partner_id': partner.id if partner else False,
                    }),
                    Command.create({
                        'sequence': 20, 'account_id': cash.id,
                        'name': payment.name, 'debit': 0.0, 'credit': amount,
                        'currency_id': company.currency_id.id,
                        'partner_id': partner.id if partner else False,
                    }),
                ]

        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'THU'),
        ], limit=1) or self.env['vas.journal'].search([
            ('company_id', '=', company.id), ('code', '=', 'TH'),
        ], limit=1)
        if not journal:
            raise UserError(_('Thiếu sổ nhật ký VAS THU/TH.'))

        move = self.env['vas.move'].create({
            'date': payment.date,
            'journal_id': journal.id,
            'regime_id': regime.id,
            'move_kind': move_kind,
            'ref': payment.memo or payment.name,
            'source_model': payment._name,
            'source_res_id': payment.id,
            'source_ref': payment.name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': line_cmds,
        })
        return self._post_or_flag_period_missing(move)

    # -------------------------------------------------------------------------
    # Core apply
    # -------------------------------------------------------------------------

    def _apply_event(self, event_type, records, company):
        created = skipped = 0
        move_kind = EVENT_MOVE_KIND[event_type]
        rules = self._find_rules(event_type, company.vas_regime_id)
        if not rules:
            return {'created': 0, 'skipped': 0, 'no_rule': True}

        for record in records:
            if self._already_synced(record._name, record.id, move_kind):
                skipped += 1
                continue
            rule = self._match_rule(rules, record)
            if not rule:
                continue
            move = self._generate_move(rule, record, company, move_kind, event_type=event_type)
            if move:
                created += 1
        return {'created': created, 'skipped': skipped}

    def _find_rules(self, event_type, regime):
        return self.env['vas.rule'].search([
            ('regime_id', '=', regime.id),
            ('event_type', '=', event_type),
            ('active', '=', True),
        ], order='sequence, id')

    def _match_rule(self, rules, record):
        for rule in rules:
            if not rule.condition:
                return rule
            try:
                domain = safe_eval(rule.condition, {'uid': self.env.uid})
            except Exception:
                _logger.exception('Invalid vas.rule condition on %s', rule.code)
                continue
            if not isinstance(domain, (list, tuple)):
                continue
            if record.filtered_domain(domain):
                return rule
        return self.env['vas.rule']

    def _already_synced(self, source_model, source_res_id, move_kind):
        return bool(self.env['vas.move'].search_count([
            ('source_model', '=', source_model),
            ('source_res_id', '=', source_res_id),
            ('move_kind', '=', move_kind),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ]))

    def _generate_move(self, rule, record, company, move_kind, event_type=None):
        event_type = event_type or rule.event_type
        if (
            record._name == 'account.move'
            and event_type in (
                'purchase_invoice', 'purchase_service', 'purchase_landed_tax',
            )
        ):
            return self._generate_purchase_invoice_tax_split_move(
                rule, record, company, move_kind, event_type,
            )
        if record._name == 'account.move' and event_type == 'purchase_discount':
            return self._generate_purchase_discount_move(rule, record, company)
        line_commands = []
        seq = 10
        fallbacks = []
        cost_fallbacks = []
        notes = []
        allow_zero = event_type in ('sale_return_stock', 'stock_scrap')
        self = self.with_context(
            vas_amount_fallbacks=fallbacks,
            vas_return_cost_notes=notes,
            vas_allow_zero_amount=allow_zero,
        )
        partner = self._source_partner(record)
        for rline in rule.line_ids.sorted(lambda l: (l.sequence, l.id)):
            amount = self._resolve_amount(rline.amount_selector, record, event_type)
            if float_is_zero(amount or 0.0, precision_digits=2) and not allow_zero:
                continue
            for account, part, split_cost_item in self._account_splits(
                rline, record, company, amount, fallbacks, event_type,
                cost_fallbacks,
            ):
                if not account:
                    raise UserError(_(
                        "Cannot resolve VAS account for rule %(rule)s line %(line)s "
                        "(selector=%(sel)s) on %(model)s(%(rid)s).",
                        rule=rule.code,
                        line=rline.id,
                        sel=rline.account_selector,
                        model=record._name,
                        rid=record.id,
                    ))
                vals = {
                    'sequence': seq,
                    'account_id': account.id,
                    'name': rule.name,
                    'partner_id': partner.id if partner else False,
                    'currency_id': company.currency_id.id,
                    'tax_status': 'none',
                    **self._pos_session_line_vals(record),
                }
                if rline.side == 'debit':
                    vals['debit'] = part
                    vals['credit'] = 0.0
                else:
                    vals['debit'] = 0.0
                    vals['credit'] = part
                if split_cost_item:
                    vals['cost_item_id'] = split_cost_item.id
                line_commands.append(Command.create(vals))
                seq += 10

        if not line_commands:
            self._note_unvalued(record, rule)
            return self.env['vas.move']

        journal = self._resolve_journal(event_type, record, company)
        date = self._source_date(record)
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': journal.id,
            'regime_id': company.vas_regime_id.id,
            'move_kind': move_kind,
            'ref': rule.name,
            'source_model': record._name,
            'source_res_id': record.id,
            'source_ref': record.display_name,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'line_ids': line_commands,
            **self._merge_move_flag_vals(
                self._default_account_flag_vals(fallbacks),
                self._unclassified_cost_flag_vals(cost_fallbacks),
                {'narration': '\n'.join(notes)} if notes else {},
            ),
        })
        return self._post_or_flag_period_missing(move)

    def _post_or_flag_period_missing(self, move):
        """§8.3: missing/closed → giữ nháp + cờ, KHÔNG nổ lô; open → post.

        Lần sync sau ``_retry_period_missing_drafts`` sẽ ghi sổ khi đã có kỳ.
        """
        if not move:
            return move
        Period = self.env['vas.period']
        status = Period._coverage_status(move.company_id, move.date)
        if status == 'open':
            move.with_context(vas_no_redirect_warning=True).action_post()
            return move
        # missing hoặc closed — không dừng lô
        note = _(
            'CHƯA GHI SỔ — %(reason)s (ngày %(date)s). '
            'Tạo/mở kỳ rồi chạy Đồng bộ VAS lại.',
            reason=(
                _('chưa có kỳ kế toán phủ ngày')
                if status == 'missing'
                else _('kỳ kế toán đã khóa')
            ),
            date=move.date,
        )
        narration = move.narration or ''
        if note not in narration:
            narration = (narration + '\n' + note).strip() if narration else note
        move.with_context(
            vas_skip_period_check=True,
            vas_allow_posted_write=True,
        ).write({
            'period_missing_pending': True,
            'narration': narration,
        })
        _logger.warning(
            'VAS PERIOD-MISSING: giữ nháp move=%s source=%s(%s) date=%s status=%s',
            move.id, move.source_model, move.source_res_id, move.date, status,
        )
        bucket = self.env.context.get('vas_period_missing')
        if bucket is not None:
            bucket.append(move.id)
        return self.env['vas.move']  # caller không đếm là created posted

    def _retry_period_missing_drafts(self, company, date_from=None, date_to=None):
        """Ghi sổ lại nháp ``period_missing_pending`` khi kỳ đã open."""
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'draft'),
            ('period_missing_pending', '=', True),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        drafts = self.env['vas.move'].search(domain)
        posted = skipped = 0
        Period = self.env['vas.period']
        for move in drafts:
            if Period._coverage_status(move.company_id, move.date) != 'open':
                skipped += 1
                continue
            try:
                move.with_context(vas_no_redirect_warning=True).action_post()
                posted += 1
            except Exception:
                skipped += 1
                _logger.exception(
                    'VAS retry period_missing failed move=%s', move.id,
                )
        return {'posted': posted, 'skipped': skipped, 'scanned': len(drafts)}

    def _period_missing_summary(self, company, date_from=None, date_to=None):
        domain = [
            ('company_id', '=', company.id),
            ('period_missing_pending', '=', True),
            ('state', '=', 'draft'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        moves = self.env['vas.move'].search(domain)
        bucket = self.env.context.get('vas_period_missing') or []
        if moves:
            _logger.warning(
                'VAS sync company=%s: %s chứng từ chưa ghi sổ vì thiếu/khóa kỳ. '
                'Bộ lọc «Chưa ghi sổ — thiếu kỳ».',
                company.id, len(moves),
            )
        return {
            'pending': len(moves),
            'flagged_this_run': len(bucket),
        }

    def _note_unvalued(self, record, rule):
        """Chứng từ khớp rule nhưng mọi chân đều 0 → không ghi sổ, nhưng phải kêu.

        Dùng lại nguyên đường cảnh báo của nhóm chưa khai ánh xạ
        (`_resolve_product_account`): warning từng lần lúc phát hiện, rồi tổng kết
        một lần cuối lượt trong `stats['default_account']`. Không dựng cơ chế mới.

        Khác một điểm và phải nói thẳng: cờ `vas_has_default_account` KHÔNG gắn
        được ở đây vì không có `vas.move` nào để gắn, nên chốt "chặn khóa
        `vas.period`" không phủ trường hợp này — chỉ có log và số đếm.
        """
        _logger.warning(
            'VAS %s: %s chưa có giá trị (value=0) → KHÔNG ghi sổ. '
            'Kiểm tra phương pháp tính giá của nhóm sản phẩm.',
            rule.code, record.display_name,
        )
        bucket = self.env.context.get('vas_unvalued')
        if bucket is not None:
            bucket.append(f'{rule.code}:{record.display_name}')

    def _default_account_flag_vals(self, fallbacks):
        """Cờ + ghi chú khi bút toán phải dùng tài khoản mặc định (C2).

        Mỗi item mô tả một lần rơi về mặc định, hai dạng nhãn nguồn:
        - sản phẩm/nhóm (khuôn gốc): key ``product`` + ``category`` — giữ
          nguyên định dạng cũ, không đổi một ký tự;
        - nguồn khác (payroll — bộ phận): key ``label`` mang sẵn nhãn đọc
          được, nêu đúng thứ chưa khai.
        MỘT cờ ``vas_has_default_account`` dùng chung, chỉ khác nhãn nguồn —
        không tách field riêng cho từng loại.
        """
        if not fallbacks:
            return {}
        seen = []
        for item in fallbacks:
            label = item.get('label') or _(
                '%(product)s / nhóm %(category)s → dùng mặc định %(code)s',
                product=item['product'],
                category=item['category'],
                code=item['default_code'],
            )
            if label not in seen:
                seen.append(label)
        return {
            'vas_has_default_account': True,
            'narration': _(
                'CHƯA KHAI ÁNH XẠ TÀI KHOẢN — bút toán này dùng tài khoản mặc định:\n%s',
                '\n'.join(f'- {label}' for label in seen),
            ),
        }

    def _unclassified_cost_flag_vals(self, fallbacks):
        """Cùng khuôn ``_default_account_flag_vals`` cho khoản mục CPD.

        Một cờ ``vas_has_unclassified_cost`` — lọc được, chặn khóa kỳ.
        """
        if not fallbacks:
            return {}
        seen = []
        for item in fallbacks:
            label = item.get('label') or _('(chưa phân loại khoản mục)')
            if label not in seen:
                seen.append(label)
        return {
            'vas_has_unclassified_cost': True,
            'narration': _(
                'KHOẢN MỤC CHƯA PHÂN LOẠI — bút toán này dùng CPD «Chưa phân loại»:\n%s',
                '\n'.join(f'- {label}' for label in seen),
            ),
        }

    def _merge_move_flag_vals(self, *flag_dicts):
        """Gộp cờ + narration từ nhiều nguồn (TK mặc định / CPD)."""
        out = {}
        notes = []
        for d in flag_dicts:
            if not d:
                continue
            for key, val in d.items():
                if key == 'narration' and val:
                    notes.append(val)
                else:
                    out[key] = val
        if notes:
            out['narration'] = '\n\n'.join(notes)
        return out

    def _product_cost_item(self, product, company, cost_fallbacks=None):
        """Tra ``cost_item_id`` trên vas.account.map — cùng trật tự TK, không leo cha.

        Chưa khai → CPD + ghi ``cost_fallbacks``.
        """
        CostItem = self.env['vas.cost.item']
        regime = company.vas_regime_id
        Map = self.env['vas.account.map']
        targets = []
        template = product.product_tmpl_id if product else self.env['product.template']
        if template:
            targets.append(('product', template.id))
        if product and product.categ_id:
            targets.append(('category', product.categ_id.id))
        for apply_to, target_id in targets:
            for row in Map._find_rows(regime, company, apply_to, target_id):
                if row.cost_item_id:
                    return row.cost_item_id
        cpd = CostItem._system_by_code(company, 'CPD')
        if cost_fallbacks is not None:
            cost_fallbacks.append({
                'source': 'purchase',
                'label': _(
                    '%(product)s / nhóm %(category)s → khoản mục Chưa phân loại (CPD)',
                    product=product.display_name if product else _('(không có sản phẩm)'),
                    category=(
                        product.categ_id.display_name
                        if product and product.categ_id else _('(chưa gán nhóm)')
                    ),
                ),
            })
        return cpd

    # -------------------------------------------------------------------------
    # Resolvers
    # -------------------------------------------------------------------------

    def _resolve_journal(self, event_type, record, company):
        code = EVENT_JOURNAL_CODE.get(event_type, 'THU')
        if event_type in (
            'payment_in', 'payment_out', 'advance_employee', 'payment_discount',
            'cash_transfer', 'deposit',
        ) and getattr(record, 'journal_id', False):
            if record.journal_id.type == 'bank':
                code = 'NH'
            elif record.journal_id.type == 'cash':
                code = 'THU'
        journal = self.env['vas.journal'].search([
            ('company_id', '=', company.id),
            ('code', '=', code),
            ('regime_id', '=', company.vas_regime_id.id),
        ], limit=1)
        if not journal:
            journal = self.env['vas.journal'].search([
                ('company_id', '=', company.id),
                ('code', '=', code),
            ], limit=1)
        if not journal:
            # Công ty mới / chưa seed: tạo đủ BH/MH/KHO/… rồi tra lại.
            self.env['vas.journal']._ensure_journals_for_company(company)
            journal = self.env['vas.journal'].search([
                ('company_id', '=', company.id),
                ('code', '=', code),
            ], limit=1)
        if not journal:
            raise UserError(_(
                "Missing VAS journal code %(code)s for company %(company)s.",
                code=code,
                company=company.display_name,
            ))
        return journal

    # -------------------------------------------------------------------------
    # Trục 1 — chọn tài khoản theo sản phẩm / nhóm sản phẩm
    # -------------------------------------------------------------------------

    def _product_account(self, product, selector, company, fallbacks=None):
        """Trật tự tra đầy đủ, dừng ở dòng đầu tiên có khai trường đang cần:

            1. sản phẩm / đích danh công ty
            2. sản phẩm / chung (company_id trống)
            3. nhóm TRỰC TIẾP / đích danh công ty
            4. nhóm TRỰC TIẾP / chung
            5. mặc định 156 / 5111 / 632 + gắn cờ

        KHÔNG leo nhóm cha ở bất kỳ bước nào: một nhóm con chưa khai phải lộ ra là
        chưa khai, chứ không âm thầm mượn tài khoản của nhóm cha. Cũng KHÔNG raise —
        một nhóm chưa khai không được làm dừng cả lượt đồng bộ; thay vào đó ghi vào
        `fallbacks` để gắn cờ lên bút toán (xem `_generate_move`).

        Từng trường đi hết bốn bước một cách độc lập: dòng khai TK doanh thu mà bỏ
        trống TK tồn kho thì riêng TK tồn kho rơi tiếp xuống bước sau.
        """
        fname, default_code = PRODUCT_ACCOUNT_SELECTOR[selector]
        regime = company.vas_regime_id
        Map = self.env['vas.account.map']
        targets = []
        template = product.product_tmpl_id if product else self.env['product.template']
        if template:
            targets.append(('product', template.id))
        if product and product.categ_id:
            targets.append(('category', product.categ_id.id))
        for apply_to, target_id in targets:
            for row in Map._find_rows(regime, company, apply_to, target_id):
                if row[fname]:
                    return row[fname]
        _logger.warning(
            'VAS %s: chưa khai %s cho sản phẩm %s (nhóm %s) → dùng mặc định %s',
            selector, fname,
            product.display_name if product else '(không có sản phẩm)',
            product.categ_id.display_name if product and product.categ_id else '(trống)',
            default_code,
        )
        if fallbacks is not None:
            fallbacks.append({
                'selector': selector,
                'default_code': default_code,
                'product': product.display_name if product else _('(không có sản phẩm)'),
                'category': (
                    product.categ_id.display_name
                    if product and product.categ_id else _('(chưa gán nhóm)')
                ),
            })
        return self._account_by_code(regime, default_code)

    def _product_weights(self, record, amount_selector, event_type=None):
        """Các cặp (sản phẩm, trọng số) để chia số tiền của một dòng quy tắc.

        `event_type` thu hẹp tập dòng hóa đơn được cân: R07 chỉ cân dòng hàng,
        R08 chỉ cân dòng dịch vụ. Thiếu tham số này thì hóa đơn trộn sẽ chia
        chi phí dịch vụ lên cả nhóm hàng tồn kho — sai tài khoản đích.
        """
        if record._name == 'stock.move':
            return [(record.product_id, 1.0)] if record.product_id else []
        if record._name == 'stock.scrap':
            return [(record.product_id, 1.0)] if record.product_id else []
        if record._name == 'stock.valuation.adjustment.lines':
            # R25: TK tồn theo SP trên phiếu nhập gốc (move_id), không theo SP cước.
            product = record.move_id.product_id or record.product_id
            return [(product, 1.0)] if product else []
        if record._name == 'hr.expense':
            return [(record.product_id, 1.0)] if record.product_id else []
        if record._name == 'account.move':
            field = 'price_total' if amount_selector == 'total' else 'price_subtotal'
            if event_type == 'purchase_invoice':
                lines = self._goods_lines(record)
            elif event_type == 'goods_in_transit':
                lines = self._goods_lines(record)
            elif event_type == 'purchase_service':
                lines = self._service_lines(record)
            elif event_type == 'purchase_landed_tax':
                lines = self._landed_lines(record)
            else:
                lines = self._real_invoice_lines(record)
            return [(line.product_id, abs(line[field] or 0.0)) for line in lines]
        if record._name == 'pos.order':
            field = (
                'price_subtotal_incl' if amount_selector == 'total' else 'price_subtotal'
            )
            pairs = []
            for line in record.lines:
                w = line[field] or 0.0
                if event_type == 'pos_sale' and w < 0:
                    continue
                pairs.append((line.product_id, abs(w)))
            return pairs
        return []

    def _product_amount_splits(
        self, record, selector, amount_selector, company, amount, fallbacks=None,
        event_type=None, cost_fallbacks=None,
    ):
        """Chia `amount` thành các cặp (vas.account, số tiền[, cost_item]) theo SP.

        Hóa đơn nhiều dòng khác nhóm → mỗi nhóm một dòng bút toán riêng;
        tổng các phần luôn bằng `amount` (chênh lệch làm tròn dồn vào phần cuối).

        Khi ``selector == product_expense`` (mua ngoài): bucket theo
        (account, cost_item) để không gộp nhầm hai khoản mục cùng TK.
        """
        weights = self._product_weights(record, amount_selector, event_type)
        attach_cost = selector == 'product_expense'
        buckets = {}
        total_weight = 0.0
        for product, weight in weights:
            account = self._product_account(product, selector, company, fallbacks)
            if not account:
                continue
            cost_item = False
            if attach_cost:
                cost_item = self._product_cost_item(
                    product, company, cost_fallbacks,
                )
            key = (account.id, cost_item.id if cost_item else False)
            bucket = buckets.setdefault(key, [account, cost_item, 0.0])
            bucket[2] += weight
            total_weight += weight
        if not buckets:
            account = self._product_account(
                self.env['product.product'], selector, company, fallbacks,
            )
            cost_item = False
            if attach_cost:
                cost_item = self._product_cost_item(
                    self.env['product.product'], company, cost_fallbacks,
                )
            return [(account, amount, cost_item)]
        items = list(buckets.values())
        if len(items) == 1 or float_is_zero(total_weight, precision_digits=2):
            return [(items[0][0], amount, items[0][1])]
        splits = []
        allocated = 0.0
        for account, cost_item, weight in items[:-1]:
            part = round(amount * weight / total_weight, 2)
            allocated += part
            splits.append((account, part, cost_item))
        last_acc, last_cost, _last_w = items[-1]
        splits.append((last_acc, round(amount - allocated, 2), last_cost))
        keep_zero = self.env.context.get('vas_allow_zero_amount')
        return [
            (account, part, cost_item) for account, part, cost_item in splits
            if keep_zero or not float_is_zero(part, precision_digits=2)
        ]

    def _account_splits(self, rline, record, company, amount, fallbacks=None,
                        event_type=None, cost_fallbacks=None):
        """Trả list (account, amount, cost_item_or_empty)."""
        CostItem = self.env['vas.cost.item']
        if rline.account_selector in PRODUCT_ACCOUNT_SELECTOR:
            return self._product_amount_splits(
                record, rline.account_selector, rline.amount_selector,
                company, amount, fallbacks, event_type, cost_fallbacks,
            )
        if rline.account_selector == 'scrap_expense':
            account, _used_default = self._scrap_expense_account(company, fallbacks)
            return [(account, amount, CostItem.browse())]
        account = self._resolve_account(
            rline, record, company.vas_regime_id, event_type,
        )
        cost_item = CostItem.browse()
        if event_type == 'stock_issue_production' and rline.side == 'debit':
            cost_item = CostItem._system_by_code(company, 'NVLTT')
        return [(account, amount, cost_item)]

    def _resolve_account(self, rline, record, regime, event_type=None):
        selector = rline.account_selector
        if selector == 'fixed':
            return rline.account_id
        if selector in PRODUCT_ACCOUNT_SELECTOR:
            weights = self._product_weights(record, rline.amount_selector, event_type)
            product = weights[0][0] if weights else self.env['product.product']
            company = self.env['res.company'].search([('vas_regime_id', '=', regime.id)], limit=1)
            return self._product_account(product, selector, company or self.env.company)
        if selector in ('bank_cash', 'dest_bank_cash'):
            # R24: đối ứng tiền theo mã đã chọn (1112/1122 khi ngoại tệ).
            forex_code = self.env.context.get('vas_forex_cash_code')
            if forex_code and selector == 'bank_cash':
                return self._account_by_code(regime, forex_code)
            journal = False
            if selector == 'dest_bank_cash':
                journal = getattr(record, 'vas_dest_journal_id', False)
                if not journal:
                    raise UserError(_(
                        "Chuyển quỹ nội bộ %(pay)s chưa chọn Sổ đích nhận tiền.",
                        pay=record.display_name,
                    ))
            elif record._name == 'hr.expense':
                # R19g: Có 111/112 theo journal phiếu chi Odoo gắn expense.
                payment = self._expense_company_payment(record)
                if not payment:
                    raise UserError(_(
                        "Chi phí %(exp)s (Paid By = Company) chưa có phiếu chi "
                        "Odoo gắn kèm — không xác định được Có 111 hay 112. "
                        "Hãy post expense rồi đồng bộ lại. VAS không tự ghi Có 331.",
                        exp=record.display_name,
                    ))
                journal = payment.journal_id
            else:
                journal = getattr(record, 'journal_id', False)
            # R17/R18 FX: 1112/1122 theo currency payment (cùng R24).
            if (
                selector == 'bank_cash'
                and record._name == 'account.payment'
                and journal
            ):
                company = record.company_id or self.env.company
                fx_code = self._payment_fx_cash_code(record, company)
                if fx_code:
                    return self._account_by_code(regime, fx_code)
            code = '111' if journal and journal.type == 'cash' else '112'
            return self._account_by_code(regime, code)
        if selector == 'receipt_counterpart':
            # R06: treo 151 trên HĐ cùng PO → Có 151; không thì Có 331.
            company = (
                record.company_id
                if record._name == 'stock.move'
                else self.env.company
            )
            if self._receipt_has_open_transit(record, company):
                return self._account_by_code(regime, '151')
            return self._account_by_code(regime, SELECTOR_FIXED_CODE['partner_payable'])
        if selector == 'landed_counterpart':
            # R25: thuế (map) → Có 333x; cước → Có 331.
            company = (
                record.cost_id.company_id
                if record._name == 'stock.valuation.adjustment.lines'
                else self.env.company
            )
            tax_map = self._landed_tax_map_for_adj(record, company)
            if tax_map:
                return tax_map.credit_account_id
            return self._account_by_code(regime, SELECTOR_FIXED_CODE['partner_payable'])
        if selector in SELECTOR_FIXED_CODE:
            return self._account_by_code(regime, SELECTOR_FIXED_CODE[selector])
        return self.env['vas.account']

    def _account_by_code(self, regime, code):
        return self.env['vas.account'].search([
            ('regime_id', '=', regime.id),
            ('code', '=', code),
            ('active', '=', True),
        ], limit=1)

    def _resolve_amount(self, amount_selector, record, event_type):
        # Hóa đơn mua: R07 chỉ ghi phần DÒNG HÀNG, R08 chỉ ghi phần DÒNG DỊCH VỤ.
        # Hóa đơn thuần một loại thì tập dòng = cả hóa đơn nên số tiền không đổi;
        # hóa đơn trộn thì mỗi rule lấy đúng phần của mình, không đếm hai lần.
        if event_type == 'purchase_invoice':
            return abs(self._invoice_lines_amount(
                self._goods_lines(record), amount_selector))
        if event_type == 'goods_in_transit':
            return abs(self._invoice_lines_amount(
                self._goods_lines(record), amount_selector))
        if event_type == 'purchase_service':
            return abs(self._invoice_lines_amount(
                self._service_lines(record), amount_selector))
        if event_type == 'purchase_landed_tax':
            return abs(self._invoice_lines_amount(
                self._landed_lines(record), amount_selector))
        if event_type == 'landed_cost_adjust' and amount_selector == 'landed_cost':
            return abs(record.additional_landed_cost or 0.0)
        if event_type == 'advance_settlement':
            if amount_selector in ('advance_applied', 'advance_excess'):
                return self._advance_split(record)[amount_selector]
            # Số tiền công ty ghi sổ là tiền đồng của công ty, không phải ngoại tệ
            # nhân viên chi; `*_currency` là cột theo tiền của chứng từ.
            mapping = {
                'untaxed': record.untaxed_amount,
                'tax': record.tax_amount,
                'total': record.total_amount,
            }
            return abs(mapping.get(amount_selector, 0.0) or 0.0)
        if event_type in (
            'sale_invoice', 'sale_refund', 'sale_discount',
            'purchase_refund', 'purchase_discount',
            'pos_sale', 'pos_refund',
        ):
            if record._name == 'pos.order':
                untaxed = abs(record.amount_total or 0.0) - abs(record.amount_tax or 0.0)
                mapping = {
                    'untaxed': untaxed,
                    'tax': abs(record.amount_tax or 0.0),
                    'total': abs(record.amount_total or 0.0),
                }
                return abs(mapping.get(amount_selector, 0.0) or 0.0)
            mapping = {
                'untaxed': record.amount_untaxed,
                'tax': record.amount_tax,
                'total': record.amount_total,
            }
            return abs(mapping.get(amount_selector, 0.0) or 0.0)
        if event_type == 'sale_return_stock' and amount_selector in ('cogs', 'stock_value'):
            fallbacks = self.env.context.get('vas_amount_fallbacks')
            notes = self.env.context.get('vas_return_cost_notes')
            return abs(self._sale_return_origin_cogs(record, fallbacks, notes) or 0.0)
        if event_type == 'stock_scrap':
            fallbacks = self.env.context.get('vas_amount_fallbacks')
            return abs(self._scrap_lot_cost(record, fallbacks) or 0.0)
        if event_type in (
            'sale_delivery', 'purchase_receipt', 'purchase_return_stock',
            'stock_issue_production',
        ):
            if amount_selector in ('cogs', 'stock_value'):
                return abs(self._stock_move_value(record))
        if event_type in (
            'payment_in', 'payment_out', 'advance_employee', 'advance_refund',
            'employee_debt_payment', 'cash_transfer', 'deposit',
            'import_vat_payment',
        ):
            if amount_selector == 'paid':
                if event_type in ('payment_in', 'payment_out'):
                    company = record.company_id or self.env.company
                    principal = self._payment_fx_principal_amount(record, company)
                    if principal is not None:
                        return abs(principal)
                return abs(record.amount or 0.0)
        if event_type == 'payment_discount' and amount_selector == 'discount':
            return abs(self._payment_discount_amount(record))
        if event_type == 'purchase_price_adjust' and amount_selector == 'price_adjust':
            return abs(self._purchase_price_adjust_amount(record))
        if event_type == 'forex_realized' and amount_selector == 'forex_diff':
            return abs(self.env.context.get('vas_forex_diff') or 0.0)
        return 0.0

    def _stock_move_value(self, stock_move):
        """Valued amount of a done stock.move (Odoo 19: stock.move.value)."""
        return self._cogs_amount(stock_move)

    def _cogs_amount(self, stock_move):
        """Giá trị đã ghi nhận của một `stock.move` đã done.

        Odoo 19 bỏ `stock.valuation.layer`; giá trị perpetual/FIFO/AVCO nằm trên
        `stock.move.value` (đặt trong `_set_value` lúc done).

        KHÔNG còn fallback `standard_price × qty`. Odoo để `value = 0` là **cố ý**
        — chặng nội bộ không làm đổi giá trị kho thì không có gì để ghi. Lấy giá
        chuẩn trên thẻ sản phẩm mà lấp vào là VAS tự chế số tiền: đó chính là thứ
        đã biến chặng PICK của kho `pick_ship` thành một bút toán giá vốn thứ hai
        (KE_HOACH_ENGINE_RULE.md §5.10). Về 0 thì `_generate_move` bỏ dòng, và nếu
        cả bút toán trống thì `_note_unvalued` kêu lên chứ không ghi sổ im lặng.

        Ngoại lệ có chứng từ: **Điều chỉnh định giá** ghi `product.value` gắn
        `move_id`. Với FIFO xuất đi khách, `_set_value` có thể để `move.value = 0`
        dù đã chỉnh tay — vẫn phải đọc số điều chỉnh đó (không phải standard_price).
        """
        if 'stock_valuation_layer_ids' in stock_move._fields:
            layers = stock_move.stock_valuation_layer_ids
            if layers:
                amount = abs(sum(layers.mapped('value')))
                if amount:
                    return amount
        if 'value' in stock_move._fields:
            amount = abs(stock_move.value or 0.0)
            if amount:
                return amount
        # Điều chỉnh định giá (product.value trên move) — ưu tiên trước price_unit
        amount = self._stock_move_manual_value(stock_move)
        if amount:
            return amount
        # `price_unit` là giá trên CHỨNG TỪ (đơn mua), không phải giá đoán từ thẻ
        # sản phẩm, nên vẫn dùng được khi Odoo chưa kịp điền `value`.
        qty = stock_move.quantity or stock_move.product_uom_qty or 0.0
        price_unit = getattr(stock_move, 'price_unit', 0.0) or 0.0
        return abs(price_unit * qty) if price_unit else 0.0

    def _stock_move_manual_value(self, stock_move):
        """Số tiền từ Điều chỉnh định giá (`product.value` gắn move), nếu có."""
        ProductValue = self.env.get('product.value')
        if ProductValue is None or 'move_id' not in ProductValue._fields:
            return 0.0
        manual = ProductValue.sudo().search(
            [('move_id', '=', stock_move.id)],
            order='date desc, id desc',
            limit=1,
        )
        return abs(manual.value or 0.0) if manual else 0.0

    def _source_date(self, record):
        if record._name == 'stock.valuation.adjustment.lines':
            return record.cost_id.date or fields.Date.context_today(self)
        if record._name == 'account.partial.reconcile':
            exch = record.exchange_move_id
            if exch and exch.date:
                return exch.date
            if record.max_date:
                return record.max_date
            return fields.Date.context_today(self)
        if record._name == 'pos.order' and record.date_order:
            return fields.Date.to_date(record.date_order)
        if record._name == 'pos.session':
            if record.stop_at:
                return fields.Date.to_date(record.stop_at)
            if record.start_at:
                return fields.Date.to_date(record.start_at)
        if 'date' in record._fields and record.date:
            return record.date
        if 'date_done' in record._fields and record.date_done:
            return fields.Date.to_date(record.date_done)
        return fields.Date.context_today(self)

    def _source_partner(self, record):
        if record._name == 'account.partial.reconcile':
            for aml in (record.debit_move_id, record.credit_move_id):
                if aml and aml.partner_id:
                    return aml.partner_id
            return self.env['res.partner']
        if record._name == 'stock.valuation.adjustment.lines':
            # Nhánh thuế (Có 333x): không gắn NCC cước. Cước: partner từ bill.
            company = record.cost_id.company_id or self.env.company
            if self._landed_tax_map_for_adj(record, company):
                return self.env['res.partner']
            bill = record.cost_id.vendor_bill_id
            return bill.partner_id if bill else self.env['res.partner']
        if 'partner_id' in record._fields and record.partner_id:
            return record.partner_id
        if record._name == 'hr.expense':
            # 141 và 334 đều theo dõi chi tiết từng người, nên bút toán phải gắn
            # đúng đối tác của người lao động, không để trống.
            employee = record.employee_id
            return (
                employee.work_contact_id
                or employee.user_id.partner_id
                or self.env['res.partner']
            )
        if record._name == 'stock.move':
            partner = record.picking_id.partner_id if record.picking_id else False
            if partner:
                return partner
            if 'sale_line_id' in record._fields and record.sale_line_id:
                return record.sale_line_id.order_id.partner_id
            if 'purchase_line_id' in record._fields and record.purchase_line_id:
                return record.purchase_line_id.order_id.partner_id
        return self.env['res.partner']
