# -*- coding: utf-8 -*-
"""N1 P1 — hóa đơn trả trước: kỳ hạn thật + TK CP + cờ (không bịa 12)."""
from datetime import date

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare

DATE = '2099-08-15'
AMOUNT = 36_000_000.0


@tagged('connecta_vas', 'connecta_vas_prepaid')
class TestPrepaidInvoiceDuration(TransactionCase):

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
        cls._ensure_period()
        cls.vendor = cls.env['res.partner'].create({
            'name': 'NCC trả trước N1', 'supplier_rank': 1,
        })
        Journal = cls.env['account.journal']
        cls.purchase_journal = Journal.search([
            ('company_id', '=', cls.company.id), ('type', '=', 'purchase'),
        ], limit=1) or Journal.create({
            'name': 'N1 MH', 'code': 'N1MH', 'type': 'purchase',
            'company_id': cls.company.id,
        })
        # VAS journal MH
        if not cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'MH'),
        ], limit=1):
            cls.env['vas.journal'].create({
                'name': 'Mua hàng', 'code': 'MH',
                'company_id': cls.company.id, 'regime_id': cls.regime.id,
                'type': 'purchase',
            })
        cls.cat_mapped = cls.env['product.category'].create({'name': 'N1 DV map 6421'})
        cls.cat_unset = cls.env['product.category'].create({'name': 'N1 DV chưa map'})
        cls.env['vas.account.map'].create({
            'regime_id': cls.regime.id,
            'apply_to': 'category',
            'company_id': cls.company.id,
            'category_id': cls.cat_mapped.id,
            'expense_account_id': cls._acc('6421').id,
        })
        cls.svc_mapped = cls.env['product.product'].create({
            'name': 'N1 Thuê kho map', 'type': 'service',
            'categ_id': cls.cat_mapped.id, 'purchase_ok': True,
        })
        cls.svc_unset = cls.env['product.product'].create({
            'name': 'N1 Thuê VP chưa map', 'type': 'service',
            'categ_id': cls.cat_unset.id, 'purchase_ok': True,
        })
        cls.Sync = cls.env['vas.sync']

    @classmethod
    def _acc(cls, code):
        acc = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', code),
        ], limit=1)
        assert acc, f'Thiếu TK {code}'
        return acc

    @classmethod
    def _ensure_period(cls):
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', DATE), ('date_to', '>=', DATE),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099-N1',
                'date_from': '2099-01-01', 'date_to': '2099-12-31',
                'state': 'open', 'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})

    def _bill(self, product, amount, prepaid=True, months=None, deferred=None):
        line_vals = {
            'product_id': product.id,
            'quantity': 1.0,
            'price_unit': amount,
            'tax_ids': [Command.clear()],
            'vas_is_prepaid': prepaid,
        }
        if months is not None:
            line_vals['vas_prepaid_months'] = months
        if deferred and 'deferred_start_date' in self.env['account.move.line']._fields:
            line_vals['deferred_start_date'] = deferred[0]
            line_vals['deferred_end_date'] = deferred[1]
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_date': DATE,
            'date': DATE,
            'company_id': self.company.id,
            'journal_id': self.purchase_journal.id,
            'invoice_line_ids': [Command.create(line_vals)],
        })
        bill.action_post()
        return bill

    def _card_for(self, bill):
        return self.env['vas.asset'].search([
            ('company_id', '=', self.company.id),
            ('code', '=', 'PP-%s' % bill.id),
        ], limit=1)

    def _move_for(self, bill):
        return self.env['vas.move'].search([
            ('source_model', '=', bill._name),
            ('source_res_id', '=', bill.id),
            ('move_kind', '=', 'prepaid_alloc'),
        ], limit=1)

    def test_01_deferred_36_months(self):
        """HĐ có deferred 36 tháng → thẻ 36 kỳ, CP/tháng = 1/36."""
        if 'deferred_start_date' not in self.env['account.move.line']._fields:
            self.skipTest('account_accountant không có deferred_* — bỏ ca này')
        # 36 tháng lịch inclusive: 2099-01-01 → 2101-12-31
        start = fields.Date.to_date('2099-01-01')
        end = fields.Date.to_date('2101-12-31')
        self.assertEqual(
            self.Sync._prepaid_months_from_deferred(
                type('L', (), {
                    '_fields': {
                        'deferred_start_date': True,
                        'deferred_end_date': True,
                    },
                    'deferred_start_date': start,
                    'deferred_end_date': end,
                })(),
            ),
            36,
        )
        bill = self._bill(
            self.svc_mapped, AMOUNT,
            deferred=(start, end),
        )
        stats = self.Sync.sync_company(self.company)
        self.assertEqual(stats['purchase_prepaid']['cards'], 1)
        card = self._card_for(bill)
        self.assertTrue(card)
        self.assertEqual(card.duration_months, 36)
        self.assertEqual(card.state, 'running')
        self.assertEqual(len(card.line_ids), 36)
        monthly = card.line_ids.sorted('sequence')[0].amount
        self.assertEqual(float_compare(monthly, AMOUNT / 36.0, 2), 0)
        move = self._move_for(bill)
        self.assertFalse(move.vas_has_default_account)
        self.assertEqual(card.account_expense_id.code, '6421')

    def test_02_vas_months_manual(self):
        """Không deferred, có vas_prepaid_months → theo số khai."""
        bill = self._bill(self.svc_mapped, AMOUNT, months=24)
        # Clear deferred if auto-filled
        if 'deferred_start_date' in bill.invoice_line_ids._fields:
            bill.invoice_line_ids.write({
                'deferred_start_date': False,
                'deferred_end_date': False,
            })
        self.Sync.sync_company(self.company)
        card = self._card_for(bill)
        self.assertEqual(card.duration_months, 24)
        self.assertEqual(len(card.line_ids), 24)
        self.assertEqual(card.state, 'running')

    def test_03_no_duration_flag_draft_no_12(self):
        """Không đường kỳ hạn → thẻ draft, CÓ CỜ, không bịa 12."""
        bill = self._bill(self.svc_unset, AMOUNT, months=0)
        if 'deferred_start_date' in bill.invoice_line_ids._fields:
            bill.invoice_line_ids.write({
                'deferred_start_date': False,
                'deferred_end_date': False,
                'vas_prepaid_months': 0,
            })
        self.Sync.sync_company(self.company)
        card = self._card_for(bill)
        move = self._move_for(bill)
        self.assertTrue(card)
        self.assertEqual(card.state, 'draft')
        self.assertFalse(card.duration_months)
        self.assertFalse(card.line_ids)
        self.assertTrue(move.vas_has_default_account)
        self.assertIn('kỳ hạn', (move.narration or '').lower())

    def test_04_expense_mapped_no_flag(self):
        bill = self._bill(self.svc_mapped, 12_000_000.0, months=12)
        if 'deferred_start_date' in bill.invoice_line_ids._fields:
            bill.invoice_line_ids.write({
                'deferred_start_date': False, 'deferred_end_date': False,
            })
        self.Sync.sync_company(self.company)
        card = self._card_for(bill)
        move = self._move_for(bill)
        self.assertEqual(card.account_expense_id.code, '6421')
        self.assertFalse(move.vas_has_default_account)
        self.assertEqual(card.duration_months, 12)
        self.assertEqual(len(card.line_ids), 12)

    def test_05_expense_default_flag_blocks_period(self):
        bill = self._bill(self.svc_unset, 12_000_000.0, months=12)
        if 'deferred_start_date' in bill.invoice_line_ids._fields:
            bill.invoice_line_ids.write({
                'deferred_start_date': False, 'deferred_end_date': False,
            })
        self.Sync.sync_company(self.company)
        card = self._card_for(bill)
        move = self._move_for(bill)
        self.assertEqual(card.account_expense_id.code, '6422')
        self.assertTrue(move.vas_has_default_account)
        self.assertIn('6422', move.narration or '')
        # Lọc UI
        found = self.env['vas.move'].search([
            ('vas_has_default_account', '=', True),
            ('id', '=', move.id),
        ])
        self.assertEqual(found, move)
        # Chặn khóa kỳ
        period = self.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', self.company.id),
            ('date_start', '<=', fields.Date.to_date(DATE)),
            ('date_end', '>=', fields.Date.to_date(DATE)),
        ], limit=1)
        with self.assertRaises(UserError):
            period.write({'state': 'closed'})

    def test_06_twelve_months_still_ok(self):
        """Ca 12 tháng thật (VAS) — không vỡ đường cũ."""
        bill = self._bill(self.svc_mapped, 12_000_000.0, months=12)
        if 'deferred_start_date' in bill.invoice_line_ids._fields:
            bill.invoice_line_ids.write({
                'deferred_start_date': False, 'deferred_end_date': False,
            })
        self.Sync.sync_company(self.company)
        card = self._card_for(bill)
        self.assertEqual(card.duration_months, 12)
        self.assertEqual(len(card.line_ids), 12)
        self.assertEqual(
            float_compare(card.line_ids[0].amount, 1_000_000.0, 2), 0,
        )

    def test_07_soft_deferred_fields_missing(self):
        """Đọc mềm: không có field deferred → không nổ, rơi sang VAS/cờ."""
        Sync = self.Sync
        # Giả lập dòng không có deferred trong _fields
        class _FakeLine:
            _fields = {'vas_prepaid_months': True}
            vas_prepaid_months = 0
            product_id = False
            deferred_start_date = date(2099, 1, 1)
            deferred_end_date = date(2099, 12, 31)

        months = Sync._prepaid_months_from_deferred(_FakeLine())
        self.assertFalse(months)
        dur, src = Sync._resolve_prepaid_duration([_FakeLine()])
        self.assertFalse(dur)
        self.assertIsNone(src)
        # Có VAS months trên fake
        fake2 = _FakeLine()
        fake2.vas_prepaid_months = 18
        dur, src = Sync._resolve_prepaid_duration([fake2])
        self.assertEqual(dur, 18)
        self.assertEqual(src, 'vas')
