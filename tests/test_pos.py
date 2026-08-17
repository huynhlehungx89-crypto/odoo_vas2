# -*- coding: utf-8 -*-
"""Luồng bán tại quầy — T1–T10 + C1/C2 (R17/R01). Soft depend pos.order."""
from datetime import datetime

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_pos')
class TestVasPosSoft(TransactionCase):
    """T9: không có module quầy / force-off → sync không lỗi."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.Sync = cls.env['vas.sync']

    def test_t9_soft_no_crash_without_pos(self):
        origin = type(self.Sync)._pos_available
        type(self.Sync)._pos_available = lambda self: False
        try:
            stats = self.Sync._sync_pos(self.company)
        finally:
            type(self.Sync)._pos_available = origin
        self.assertIn('orders', stats)
        self.assertEqual(stats['orders']['created'], 0)

    def test_t9_manifest_no_hard_depend_pos(self):
        mod = self.env['ir.module.module'].search([
            ('name', '=', 'connecta_vas'),
        ], limit=1)
        self.assertTrue(mod)
        manifest = self.env['ir.module.module'].get_module_info('connecta_vas')
        depends = manifest.get('depends') or []
        self.assertNotIn('point_of_sale', depends)


@tagged('connecta_vas', 'connecta_vas_pos')
class TestVasPosFlow(TransactionCase):
    """T1–T8, T10 — cần point_of_sale. Bỏ qua nếu registry không có pos.order."""

    UNTAXED = 100_000.0
    TAX = 10_000.0
    TOTAL = 110_000.0
    COGS = 60_000.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != cls.vnd:
            cls.company.currency_id = cls.vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.Sync = cls.env['vas.sync']
        cls.has_pos = 'pos.order' in cls.env
        if not cls.has_pos:
            return
        cls._ensure_periods()
        cls._ensure_pos_setup()

    @classmethod
    def _ensure_periods(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-08-31'),
            ('date_to', '>=', '2099-09-01'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        for month, start, end in (
            (8, '2099-08-01', '2099-08-31'),
            (9, '2099-09-01', '2099-09-30'),
            (1, '2099-01-01', '2099-01-31'),
        ):
            p = cls.env['vas.period'].search([
                ('fiscalyear_id', '=', fy.id),
                ('date_start', '=', start),
            ], limit=1)
            if not p:
                cls.env['vas.period'].create({
                    'name': '%02d/2099' % month,
                    'date_start': start,
                    'date_end': end,
                    'fiscalyear_id': fy.id,
                    'state': 'open',
                })
            else:
                p.state = 'open'
        cls.fy = fy
        cls.period_jan = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2099-01-01'),
        ], limit=1)
        cls.period_aug = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2099-08-01'),
        ], limit=1)
        cls.period_sep = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2099-09-01'),
        ], limit=1)

    @classmethod
    def _ensure_pos_setup(cls):
        cls.env.user.group_ids += cls.env.ref('point_of_sale.group_pos_manager')
        cash_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'cash'),
        ], limit=1)
        if not cash_journal:
            cash_journal = cls.env['account.journal'].create({
                'name': 'Cash VAS POS',
                'code': 'CSHV',
                'type': 'cash',
                'company_id': cls.company.id,
            })
        bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        if not bank_journal:
            bank_journal = cls.env['account.journal'].create({
                'name': 'Bank VAS POS',
                'code': 'BNKV',
                'type': 'bank',
                'company_id': cls.company.id,
            })
        sale_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'sale'),
        ], limit=1)
        cls.cash_pm = cls.env['pos.payment.method'].create({
            'name': 'TM VAS',
            'journal_id': cash_journal.id,
            'company_id': cls.company.id,
        })
        cls.bank_pm = cls.env['pos.payment.method'].create({
            'name': 'The VAS',
            'journal_id': bank_journal.id,
            'company_id': cls.company.id,
        })
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'VAS POS Test',
            'company_id': cls.company.id,
            'journal_id': sale_journal.id if sale_journal else False,
            'cash_control': True,
            'payment_method_ids': [Command.set((cls.cash_pm | cls.bank_pm).ids)],
        })
        tax = cls.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10),
            ('company_id', '=', cls.company.id),
            ('amount_type', '=', 'percent'),
        ], limit=1)
        if not tax:
            tax = cls.env['account.tax'].create({
                'name': 'GTGT 10% POS',
                'amount': 10.0,
                'amount_type': 'percent',
                'type_tax_use': 'sale',
                'company_id': cls.company.id,
            })
        cls.tax = tax
        cls.product = cls.env['product.product'].create({
            'name': 'HH POS VAS',
            'is_storable': True,
            'available_in_pos': True,
            'list_price': cls.UNTAXED,
            'standard_price': cls.COGS,
            'taxes_id': [Command.set(tax.ids)],
        })
        cls.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': cls.product.id,
            'inventory_quantity': 100,
            'location_id': cls.env.ref('stock.stock_location_stock').id,
        }).action_apply_inventory()
        cls.partner = cls.env['res.partner'].create({
            'name': 'KH POS VAS',
            'company_id': cls.company.id,
        })

    def _skip_if_no_pos(self):
        if not self.has_pos:
            self.skipTest('pos.order not in registry')

    def _open_session(self):
        self.pos_config.open_ui()
        session = self.pos_config.current_session_id
        self.assertTrue(session)
        return session

    def _pay_and_done(self, order, amount, payment_method):
        wizard = self.env['pos.make.payment'].with_context(
            active_id=order.id, active_ids=order.ids,
        ).create({
            'amount': amount,
            'payment_method_id': payment_method.id,
        })
        wizard.check()
        return order

    def _close_session(self, session, stop_at=None, counted_delta=0.0):
        stop_at = stop_at or datetime(2099, 1, 15, 18, 0, 0)
        if session.state != 'closed':
            session.action_pos_session_closing_control()
        session.invalidate_recordset()
        theoretical = session.cash_register_balance_end
        session.sudo().write({
            'cash_register_balance_end_real': theoretical + counted_delta,
            'stop_at': stop_at,
        })
        session.invalidate_recordset()
        return session

    def _make_order(self, session, qty=1, partner=False, to_invoice=False, date_order=None):
        untaxed = self.UNTAXED * qty
        tax = self.TAX * qty
        total = self.TOTAL * qty
        if date_order is None:
            date_order = datetime(2099, 1, 15, 10, 0, 0)
        order = self.env['pos.order'].create({
            'session_id': session.id,
            'company_id': self.company.id,
            'partner_id': partner.id if partner else False,
            'to_invoice': to_invoice,
            'amount_tax': tax,
            'amount_total': total,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'lines': [Command.create({
                'product_id': self.product.id,
                'qty': qty,
                'price_unit': self.UNTAXED,
                'price_subtotal': untaxed,
                'price_subtotal_incl': total,
                'tax_ids': [Command.set(self.tax.ids)],
                'full_product_name': self.product.name,
                'name': self.product.display_name,
            })],
        })
        if date_order:
            order.write({'date_order': date_order})
        return order

    def _vas_moves(self, source, kind=None):
        domain = [
            ('source_model', '=', source._name),
            ('source_res_id', '=', source.id),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ]
        if kind:
            domain.append(('move_kind', '=', kind))
        return self.env['vas.move'].search(domain)

    def _line_amt(self, move, code_prefix, side):
        lines = move.line_ids.filtered(
            lambda l: (l.account_id.code or '').startswith(code_prefix)
        )
        if side == 'debit':
            return sum(lines.mapped('debit'))
        return sum(lines.mapped('credit'))

    def test_t1_order_without_invoice_has_revenue(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self.Sync.sync_company(self.company)
        sale = self._vas_moves(order, 'pos_sale')
        self.assertEqual(len(sale), 1, 'T1: đơn không HĐ phải có bút toán doanh thu')
        self.assertGreater(self._line_amt(sale, '511', 'credit'), 0.0)

    def test_t2_invoiced_order_not_doubled(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session, partner=self.partner, to_invoice=False)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': '2099-01-15',
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': self.UNTAXED,
                'tax_ids': [Command.set(self.tax.ids)],
            })],
        })
        invoice.action_post()
        order.write({'account_move': invoice.id})
        self.Sync.sync_company(self.company)
        pos_sale = self._vas_moves(order, 'pos_sale')
        self.assertEqual(len(pos_sale), 1)
        if order.account_move:
            r01 = self.env['vas.move'].search([
                ('source_model', '=', 'account.move'),
                ('source_res_id', '=', order.account_move.id),
                ('move_kind', '=', 'sale_inv'),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ])
            self.assertFalse(r01, 'T2/C2: HĐ quầy không được R01 ghi thêm')
        credits_511 = self.env['vas.move.line'].search([
            ('move_id.source_model', 'in', ('pos.order', 'account.move')),
            ('move_id.source_res_id', 'in', [order.id] + (
                [order.account_move.id] if order.account_move else []
            )),
            ('account_id.code', '=like', '511%'),
            ('credit', '>', 0),
            ('move_id.is_reversal', '=', False),
            ('move_id.state', '=', 'posted'),
        ])
        self.assertEqual(
            len(credits_511.mapped('move_id')), 1,
            'T2: đúng một bút toán doanh thu',
        )

    def test_t3_session_cash_111_131(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        cash_move = self._vas_moves(session, 'pos_session_cash')
        self.assertEqual(len(cash_move), 1, 'T3: phải có bút toán kết ca TM')
        self.assertEqual(
            float_compare(self._line_amt(cash_move, '111', 'debit'), self.TOTAL, 2),
            0,
        )
        self.assertEqual(
            float_compare(self._line_amt(cash_move, '131', 'credit'), self.TOTAL, 2),
            0,
        )

    def test_t4_r17_skips_pos_payment(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.bank_pm)
        self._close_session(session)
        Payment = self.env['account.payment']
        pos_pays = Payment.search([
            ('pos_session_id', '=', session.id),
        ]) if 'pos_session_id' in Payment._fields else Payment.browse()
        self.Sync.sync_company(self.company)
        for pay in pos_pays:
            r17 = self.env['vas.move'].search([
                ('source_model', '=', 'account.payment'),
                ('source_res_id', '=', pay.id),
                ('move_kind', '=', 'payment'),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ])
            self.assertFalse(r17, 'T4/C1: R17 không ghi payment gắn pos_session_id')
        bank_move = self._vas_moves(session, 'pos_session_bank')
        self.assertEqual(len(bank_move), 1)

    def test_t4_r17_filter_on_payment_with_pos_session_id(self):
        """C1 đơn vị: payment inbound gắn session bị loại khỏi R17 dù không đóng ca."""
        self._skip_if_no_pos()
        session = self._open_session()
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 55_000,
            'date': '2099-01-15',
            'journal_id': journal.id,
            'pos_session_id': session.id,
        })
        pay.action_post()
        self.assertTrue(self.Sync._payment_is_pos(pay))
        inbound = self.Sync._search_payments(self.company, '2099-01-01', '2099-01-31', 'inbound')
        inbound = inbound.filtered(
            lambda p: not p.vas_operation_type and not self.Sync._payment_is_pos(p)
        )
        self.assertNotIn(pay, inbound)

    def test_t5_shortage_1381_session_on_ledger(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session, counted_delta=-50_000)
        self.Sync.sync_company(self.company)
        diff = self._vas_moves(session, 'pos_cash_diff')
        self.assertEqual(len(diff), 1, 'T5: phải có bút toán đếm thiếu')
        self.assertEqual(
            float_compare(self._line_amt(diff, '1381', 'debit'), 50_000, 2), 0,
        )
        self.assertEqual(
            float_compare(self._line_amt(diff, '131', 'credit'), 50_000, 2), 0,
        )
        acc_1381 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '1381'),
        ], limit=1)
        wiz = self.env['vas.account.ledger.wizard'].create({
            'company_id': self.company.id,
            'account_id': acc_1381.id,
            'period_from_id': self.period_jan.id,
            'period_to_id': self.period_jan.id,
            'pos_session_res_id': session.id,
        })
        wiz.action_compute()
        move_rows = wiz.line_ids.filtered(lambda l: l.row_type == 'move')
        self.assertTrue(move_rows, 'T5: sổ 1381 lọc phiên phải thấy dòng')
        self.assertTrue(
            any(session.name in (r.pos_session_name or '') or r.pos_session_res_id == session.id
                for r in move_rows),
        )

    def test_t6_overage_3381_session(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session, counted_delta=20_000)
        self.Sync.sync_company(self.company)
        diff = self._vas_moves(session, 'pos_cash_diff')
        self.assertEqual(len(diff), 1)
        self.assertEqual(
            float_compare(self._line_amt(diff, '3381', 'credit'), 20_000, 2), 0,
        )
        self.assertEqual(
            float_compare(self._line_amt(diff, '131', 'debit'), 20_000, 2), 0,
        )
        acc_3381 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '3381'),
        ], limit=1)
        wiz = self.env['vas.account.ledger.wizard'].create({
            'company_id': self.company.id,
            'account_id': acc_3381.id,
            'period_from_id': self.period_jan.id,
            'period_to_id': self.period_jan.id,
            'pos_session_res_id': session.id,
        })
        wiz.action_compute()
        self.assertTrue(wiz.line_ids.filtered(lambda l: l.row_type == 'move'))

    def test_t7_cross_month_two_periods(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(
            session, date_order=datetime(2099, 8, 31, 10, 0, 0),
        )
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session, stop_at=datetime(2099, 9, 1, 9, 0, 0))
        self.Sync.sync_company(self.company)
        sale = self._vas_moves(order, 'pos_sale')
        self.assertEqual(fields.Date.to_string(sale.date), '2099-08-31')
        cash = self._vas_moves(session, 'pos_session_cash')
        self.assertEqual(fields.Date.to_string(cash.date), '2099-09-01')

    def test_t8_sync_twice_no_extra_move(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self.Sync.sync_company(self.company)
        n1 = len(self._vas_moves(order))
        self.Sync.sync_company(self.company)
        n2 = len(self._vas_moves(order))
        self.assertEqual(n1, n2)

    def test_t10_pos_refund_reverses_131(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        refund_action = order.refund()
        refund = self.env['pos.order'].browse(refund_action['res_id'])
        self._pay_and_done(refund, refund.amount_total, self.cash_pm)
        self.Sync.sync_company(self.company)
        rev = self._vas_moves(refund, 'pos_refund')
        self.assertEqual(len(rev), 1, 'T10: trả hàng phải có bút toán ngược')
        self.assertEqual(
            float_compare(self._line_amt(rev, '131', 'credit'), self.TOTAL, 2), 0,
        )
        self.assertGreater(self._line_amt(rev, '511', 'debit'), 0.0)

    def test_c3_pos_picking_not_r02_duplicate(self):
        self._skip_if_no_pos()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        pos_cogs = self._vas_moves(order, 'pos_cogs')
        stock_moves = order.picking_ids.mapped('move_ids').filtered(
            lambda m: m.state == 'done'
        )
        r02 = self.env['vas.move'].search([
            ('source_model', '=', 'stock.move'),
            ('source_res_id', 'in', stock_moves.ids),
            ('move_kind', '=', 'cogs'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        self.assertFalse(r02, 'C3: phiếu WH/POS không vào R02')
        self.assertLessEqual(len(pos_cogs), 1)
        if stock_moves:
            self.assertEqual(len(pos_cogs), 1, 'C3: giá vốn quầy đúng một lần')

    def _vas_1111(self):
        return self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '1111'),
        ], limit=1)

    def _add_cash_io(self, session, amount, io_date='2099-01-15'):
        self.assertTrue(session.cash_journal_id, 'Phiên phải có nhật ký tiền mặt')
        line = self.env['account.bank.statement.line'].sudo().create({
            'pos_session_id': session.id,
            'journal_id': session.cash_journal_id.id,
            'amount': amount,
            'date': io_date,
            'payment_ref': '%s-%s-VAS' % (
                session.name,
                'Cash out' if amount < 0 else 'Cash in',
            ),
        })
        return line

    def test_t11_rounding_off_no_511_dump(self):
        self._skip_if_no_pos()
        self.assertFalse(
            self.pos_config.cash_rounding,
            'T11: mặc định quầy tắt làm tròn',
        )
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        sale = self._vas_moves(order, 'pos_sale')
        self.assertEqual(len(sale), 1)
        self.assertEqual(
            float_compare(self._line_amt(sale, '511', 'credit'), self.UNTAXED, 2),
            0,
            'T11: 511 chỉ doanh thu thật, không nhận làm tròn',
        )
        self.assertFalse(
            any('Làm tròn' in (l.name or '') for l in sale.line_ids),
        )
        self.assertFalse(
            self._vas_moves(session, 'pos_rounding'),
            'T11: không sinh bút toán làm tròn kết ca',
        )
        self.assertFalse(
            self.env['vas.move'].search([
                ('move_kind', '=', 'pos_cash_io'),
                ('line_ids.pos_session_res_id', '=', session.id),
                ('is_reversal', '=', False),
            ]),
            'T11: quầy tắt làm tròn, ca thường — không có rút/bỏ giữa ca',
        )

    def test_t12_rounding_on_blocks_lock_no_book(self):
        self._skip_if_no_pos()
        from odoo.exceptions import UserError
        income = self.env['account.account'].search([
            ('account_type', '=', 'income'),
        ], limit=1)
        rounding = self.env['account.cash.rounding'].create({
            'name': 'VAS T12 rounding',
            'rounding': 1000.0,
            'strategy': 'add_invoice_line',
            'profit_account_id': income.id if income else False,
            'loss_account_id': income.id if income else False,
        })
        self.pos_config.write({
            'cash_rounding': True,
            'rounding_method': rounding.id,
        })
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        self._close_session(session)
        # Lệch làm tròn: tổng đơn > tiền đã thu, quầy đang bật làm tròn.
        # Đóng ca trước rồi mới đẩy amount_total — tránh phá cân bút toán Odoo lúc validate.
        order.sudo().write({'amount_total': self.TOTAL + 110})
        with self.assertRaises(UserError) as err:
            self.Sync.sync_company(self.company)
        msg = str(err.exception)
        self.assertIn(self.pos_config.name, msg)
        self.assertIn(session.name, msg)
        self.assertTrue('110' in msg)
        self.assertFalse(
            self._vas_moves(session, 'pos_rounding'),
            'T12: không ghi sổ khoản lệch làm tròn',
        )
        extra_511 = self.env['vas.move.line'].search([
            ('move_id.source_model', '=', 'pos.session'),
            ('move_id.source_res_id', '=', session.id),
            ('account_id.code', '=like', '511%'),
            ('move_id.is_reversal', '=', False),
        ])
        self.assertFalse(extra_511, 'T12: không dồn lệch vào 511')
        with self.assertRaises(UserError) as lock_err:
            self.period_jan.write({'state': 'closed'})
        lock_msg = str(lock_err.exception)
        self.assertIn(self.pos_config.name, lock_msg)
        self.assertIn(session.name, lock_msg)

    def test_t13_cash_out_configured_separate_move(self):
        self._skip_if_no_pos()
        acc = self._vas_1111()
        self.assertTrue(acc)
        self.company.vas_pos_cash_account_id = acc
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        line = self._add_cash_io(session, -200_000)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        io_moves = self.env['vas.move'].search([
            ('source_model', '=', line._name),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', 'pos_cash_io'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        self.assertEqual(len(io_moves), 1, 'T13: bút toán riêng rút giữa ca')
        self.assertEqual(fields.Date.to_string(io_moves.date), '2099-01-15')
        self.assertEqual(
            float_compare(self._line_amt(io_moves, '111', 'debit'), 200_000, 2), 0,
        )
        self.assertEqual(
            float_compare(self._line_amt(io_moves, '131', 'credit'), 200_000, 2), 0,
        )
        self.assertFalse(io_moves.vas_has_default_account)
        cash_close = self._vas_moves(session, 'pos_session_cash')
        self.assertEqual(len(cash_close), 1)
        self.assertEqual(
            float_compare(self._line_amt(cash_close, '111', 'debit'), self.TOTAL, 2),
            0,
            'T13: kết ca không gộp số rút giữa ca',
        )
        self.assertNotEqual(io_moves.id, cash_close.id)

    def test_t14_cash_out_empty_config_flags_and_blocks_lock(self):
        self._skip_if_no_pos()
        from odoo.exceptions import UserError
        self.company.vas_pos_cash_account_id = False
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        line = self._add_cash_io(session, -200_000)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        io_moves = self.env['vas.move'].search([
            ('source_model', '=', line._name),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', 'pos_cash_io'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        self.assertEqual(len(io_moves), 1)
        self.assertTrue(io_moves.vas_has_default_account, 'T14: phải mang cờ TK mặc định')
        self.assertIn(session.name, io_moves.narration or '')
        self.assertIn('200', io_moves.narration or '')
        with self.assertRaises(UserError) as err:
            self.period_jan.write({'state': 'closed'})
        self.assertIn('MẶC ĐỊNH', str(err.exception))

    def test_t15_cash_in_opposite_of_out(self):
        self._skip_if_no_pos()
        self.company.vas_pos_cash_account_id = self._vas_1111()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        line = self._add_cash_io(session, 200_000)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        io_moves = self.env['vas.move'].search([
            ('source_model', '=', line._name),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', 'pos_cash_io'),
            ('is_reversal', '=', False),
            ('state', 'not in', ('reversed', 'cancelled')),
        ])
        self.assertEqual(len(io_moves), 1)
        self.assertEqual(
            float_compare(self._line_amt(io_moves, '131', 'debit'), 200_000, 2), 0,
        )
        self.assertEqual(
            float_compare(self._line_amt(io_moves, '111', 'credit'), 200_000, 2), 0,
        )

    def test_t7_unlink_cash_io_open_reverses(self):
        self._skip_if_no_pos()
        self.company.vas_pos_cash_account_id = self._vas_1111()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        line = self._add_cash_io(session, -200_000)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        io = self.env['vas.move'].search([
            ('source_model', '=', line._name),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', 'pos_cash_io'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(io)
        self.assertEqual(io.state, 'posted')
        line.sudo().unlink()
        stats = self.Sync._sync_cancel_regressions(self.company)
        self.assertGreaterEqual(stats['reversed'], 1)
        io.invalidate_recordset()
        self.assertEqual(io.state, 'reversed')

    def test_t8_unlink_cash_io_closed_pending(self):
        self._skip_if_no_pos()
        self.company.vas_pos_cash_account_id = self._vas_1111()
        session = self._open_session()
        order = self._make_order(session)
        self._pay_and_done(order, order.amount_total, self.cash_pm)
        line = self._add_cash_io(session, -200_000)
        self._close_session(session)
        self.Sync.sync_company(self.company)
        io = self.env['vas.move'].search([
            ('source_model', '=', line._name),
            ('source_res_id', '=', line.id),
            ('move_kind', '=', 'pos_cash_io'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(io)
        # Pattern P02: đóng kỳ SQL để chỉ nghiệm cơ chế hủy, không đụng gate khóa kỳ.
        self.env.cr.execute(
            "UPDATE vas_period SET state='closed' WHERE id=%s",
            (self.period_jan.id,),
        )
        self.period_jan.invalidate_recordset()
        self.assertEqual(self.period_jan.state, 'closed')
        line.sudo().unlink()
        stats = self.Sync._sync_cancel_regressions(self.company)
        io.invalidate_recordset()
        self.assertGreaterEqual(stats['closed_period_flagged'], 1)
        self.assertEqual(io.state, 'posted')
        self.assertTrue(io.source_cancel_pending)
        self.assertEqual(stats.get('reversed', 0), 0)
