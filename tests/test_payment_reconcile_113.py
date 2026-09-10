# -*- coding: utf-8 -*-
"""Phase 1 — đối soát thanh toán TK 113 / mã CK."""
import base64

from odoo.tests import tagged, TransactionCase


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_payment_113')
class TestPaymentReconcile113(TransactionCase):

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
                'code': 'TT133',
                'name': 'Thông tư 133/2016/TT-BTC',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'

        Acc = cls.env['vas.account']
        for code, name in (
            ('111', 'Tiền mặt'),
            ('112', 'Tiền gửi Ngân hàng'),
            ('113', 'Tiền đang chuyển'),
            ('131', 'Phải thu khách hàng'),
        ):
            if not Acc.search([('code', '=', code), ('regime_id', '=', cls.regime.id)], limit=1):
                Acc.create({
                    'code': code,
                    'name': name,
                    'regime_id': cls.regime.id,
                    'ending_balance_policy': 'debit',
                    'account_type': 'asset',
                    'reconcile': code == '131',
                })

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2099-06-15'),
            ('date_to', '>=', '2099-06-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': '2099',
                'date_from': '2099-01-01',
                'date_to': '2099-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        if not fy.period_ids:
            fy.action_generate_periods()
        else:
            fy.period_ids.write({'state': 'open'})

        Journal = cls.env['vas.journal']
        if not Journal.search([
            ('company_id', '=', cls.company.id), ('code', '=', 'THU'),
        ], limit=1):
            Journal.create({
                'name': 'Sổ thu',
                'code': 'THU',
                'type': 'cash',
                'company_id': cls.company.id,
            })

        cls.partner = cls.env['res.partner'].create({
            'name': 'KH VietQR Test',
            'company_id': cls.company.id,
        })

    def _make_pending(self, amount=100_000.0, ref='HD999001'):
        return self.env['vas.payment.pending113'].create({
            'company_id': self.company.id,
            'partner_id': self.partner.id,
            'reference_code': ref,
            'amount': amount,
            'date': '2099-06-15',
        })

    def test_post_pending_113_131(self):
        pending = self._make_pending()
        pending.action_post_pending()
        self.assertEqual(pending.state, 'pending')
        self.assertTrue(pending.pending_move_id)
        move = pending.pending_move_id
        self.assertEqual(move.state, 'posted')
        debits = {l.account_id.code: l.debit for l in move.line_ids if l.debit}
        credits = {l.account_id.code: l.credit for l in move.line_ids if l.credit}
        self.assertAlmostEqual(debits.get('113', 0.0), 100_000.0, places=2)
        self.assertAlmostEqual(credits.get('131', 0.0), 100_000.0, places=2)

    def test_match_by_reference_code(self):
        pending = self._make_pending(amount=250_000.0, ref='HD250001')
        pending.action_post_pending()
        csv_text = (
            'Ngay,So tien,Noi dung\n'
            '2099-06-16,250000,CK HD250001 thanh toan HD\n'
        )
        imp = self.env['vas.bank.statement.import'].create({
            'company_id': self.company.id,
            'bank_label': 'TestBank',
            'data_file': base64.b64encode(csv_text.encode('utf-8')),
            'filename': 'test.csv',
            'settle_account_code': '112',
        })
        imp.action_parse_file()
        self.assertEqual(len(imp.line_ids), 1)
        imp.action_run_matching()
        pending.invalidate_recordset()
        self.assertEqual(pending.state, 'matched')
        self.assertEqual(pending.match_method, 'reference_code')
        self.assertTrue(pending.settle_move_id)
        settle = pending.settle_move_id
        debits = {l.account_id.code: l.debit for l in settle.line_ids if l.debit}
        credits = {l.account_id.code: l.credit for l in settle.line_ids if l.credit}
        self.assertAlmostEqual(debits.get('112', 0.0), 250_000.0, places=2)
        self.assertAlmostEqual(credits.get('113', 0.0), 250_000.0, places=2)

    def test_invoice_ref_code_format(self):
        Move = self.env['account.move']
        inv = Move.new({
            'name': 'INV/2099/00042',
            'move_type': 'out_invoice',
            'company_id': self.company.id,
        })
        code = inv._vas_build_payment_ref_code()
        self.assertTrue(code.startswith('HD'))
        self.assertIn('42', code)
