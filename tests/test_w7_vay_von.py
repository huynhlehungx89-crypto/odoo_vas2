# -*- coding: utf-8 -*-
"""W7 — vay & vốn: lãi (split/capitalize) + sync nhãn + distribution + cancel."""
from datetime import date

from odoo import fields, Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_w7')
class TestW7VayVon(TransactionCase):

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

        codes = {
            '111': ('asset', 'Tiền mặt'),
            '112': ('asset', 'Tiền gửi'),
            '2111': ('asset', 'TSCĐ'),
            '2141': ('asset', 'HM TSCĐ'),
            '241': ('asset', 'XDCB dở dang'),
            '331': ('liability', 'Phải trả NCC'),
            '335': ('liability', 'Chi phí phải trả'),
            '3388': ('liability', 'Phải trả CSH'),
            '3335': ('liability', 'TNCN'),
            '3411': ('liability', 'Vay NH'),
            '4111': ('equity', 'Vốn góp'),
            '418': ('equity', 'Quỹ VCSH'),
            '4211': ('equity', 'LNST chưa PP'),
            '635': ('expense', 'Chi phí tài chính'),
            '6422': ('expense', 'CP QLDN'),
        }
        cls.acc = {}
        for code, (atype, name) in codes.items():
            acc = cls.env['vas.account'].search([
                ('regime_id', '=', cls.regime.id), ('code', '=', code),
            ], limit=1)
            if not acc:
                pol = {
                    'asset': 'debit', 'liability': 'credit', 'equity': 'debit_or_credit',
                    'income': 'none', 'expense': 'none', 'other_income': 'none',
                    'other_expense': 'none', 'pl': 'none',
                }.get(atype, 'debit_or_credit')
                acc = cls.env['vas.account'].create({
                    'code': code, 'name': name, 'regime_id': cls.regime.id,
                    'account_type': atype,
                    'ending_balance_policy': pol,
                })
            cls.acc[code] = acc

        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].create({
                'code': 'TH', 'name': 'Tổng hợp', 'type': 'general',
                'company_id': cls.company.id,
            })
        cls.journal_thu = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'THU'),
        ], limit=1)
        if not cls.journal_thu:
            cls.journal_thu = cls.env['vas.journal'].create({
                'code': 'THU', 'name': 'Thu', 'type': 'cash',
                'company_id': cls.company.id,
            })

        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': '2097',
            'date_from': '2097-01-01',
            'date_to': '2097-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.period_jan = cls.env['vas.period'].create({
            'name': '01/2097',
            'date_start': '2097-01-01',
            'date_end': '2097-01-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.period_feb = cls.env['vas.period'].create({
            'name': '02/2097',
            'date_start': '2097-02-01',
            'date_end': '2097-02-28',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })

    def _acc(self, code):
        return self.acc[code]

    def _make_loan(self, principal=100_000_000, rate=0.12, **kwargs):
        vals = {
            'code': kwargs.pop('code', 'VAY-TEST'),
            'name': kwargs.pop('name', 'Vay test'),
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date_start': kwargs.pop('date_start', date(2097, 1, 1)),
            'principal': principal,
            'interest_rate': rate,
            'day_count_basis': 'actual_365',
            'interest_balance_mode': 'accurate',
            'account_loan_id': self._acc('3411').id,
            'account_interest_expense_id': self._acc('635').id,
            'account_interest_payable_id': self._acc('335').id,
            'journal_id': self.journal.id,
        }
        vals.update(kwargs)
        return self.env['vas.loan'].create(vals)

    # ------------------------------------------------------------------
    # Interest formula
    # ------------------------------------------------------------------

    def test_interest_full_month_no_repay(self):
        """100tr × 12% × 31/365 ≈ 1.019.178."""
        loan = self._make_loan()
        loan.action_confirm()
        info = loan.compute_interest_for_period(self.period_jan)
        expected = round(100_000_000 * 0.12 * 31 / 365)
        self.assertEqual(info['amount'], expected)
        self.assertEqual(info['days'], 31)

    def test_interest_split_mid_period_repay(self):
        """Trả gốc giữa kỳ → lãi đoạn trước/sau khác nhau (accurate)."""
        loan = self._make_loan(code='VAY-SPLIT')
        loan.action_confirm()
        # giả lập trả gốc 40tr ngày 15/01 qua vas.move + payment stub
        partner = self.env['res.partner'].create({'name': 'NH Test'})
        bank = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.company.id),
        ], limit=1)
        if not bank:
            self.skipTest('No bank journal')
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': partner.id,
            'amount': 40_000_000,
            'date': '2097-01-15',
            'journal_id': bank.id,
            'vas_operation_type': 'loan_repay',
            'vas_loan_id': loan.id,
        })
        # Force state without full Odoo payment flow
        payment.write({'state': 'paid'})
        self.env['vas.move'].create({
            'date': '2097-01-15',
            'journal_id': self.journal_thu.id,
            'regime_id': self.regime.id,
            'move_kind': 'loan_repay',
            'source_model': 'account.payment',
            'source_res_id': payment.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
                Command.create({
                    'account_id': self._acc('3411').id, 'debit': 40_000_000, 'credit': 0,
                }),
                Command.create({
                    'account_id': self._acc('112').id, 'debit': 0, 'credit': 40_000_000,
                }),
            ],
        }).action_post()
        loan.invalidate_recordset(['outstanding_principal'])
        loan._compute_outstanding_principal()

        info = loan.compute_interest_for_period(self.period_jan)
        # 1–15: 100tr (15 ngày), 16–31: 60tr (16 ngày)
        expected = round(
            100_000_000 * 0.12 * 15 / 365
            + 60_000_000 * 0.12 * 16 / 365
        )
        self.assertEqual(info['amount'], expected)
        full = round(100_000_000 * 0.12 * 31 / 365)
        self.assertLess(info['amount'], full)

    def test_pass_interest_idempotent_and_capitalize(self):
        loan = self._make_loan(
            code='VAY-CAP',
            capitalize_interest=True,
            capitalize_account_id=self._acc('241').id,
            capitalize_date_from=date(2097, 1, 1),
            capitalize_date_to=date(2097, 12, 31),
        )
        loan.action_confirm()
        stats = self.env['vas.loan'].generate_interest_entries(
            self.company, self.period_jan,
        )
        self.assertEqual(stats['created'], 1)
        line = loan.line_ids.filtered(lambda l: l.period_id == self.period_jan)
        self.assertEqual(line.state, 'posted')
        self.assertTrue(line.is_capitalized)
        move = line.move_id
        self.assertEqual(move.move_kind, 'loan_interest')
        debit_codes = move.line_ids.filtered('debit').mapped('account_id.code')
        self.assertIn('241', debit_codes)
        credit_codes = move.line_ids.filtered('credit').mapped('account_id.code')
        self.assertIn('335', credit_codes)

        stats2 = self.env['vas.loan'].generate_interest_entries(
            self.company, self.period_jan,
        )
        self.assertEqual(stats2['created'], 0)
        self.assertEqual(
            self.env['vas.move'].search_count([
                ('source_model', '=', 'vas.loan.line'),
                ('source_res_id', '=', line.id),
                ('move_kind', '=', 'loan_interest'),
                ('is_reversal', '=', False),
                ('state', 'not in', ('reversed', 'cancelled')),
            ]),
            1,
        )

    def test_closed_period_refuse_and_hard_block_close(self):
        loan = self._make_loan(code='VAY-LOCK')
        loan.action_confirm()
        # khóa kỳ (bypass) rồi refuse sinh lãi
        self.period_jan.with_context(
            vas_skip_asset_lock_check=True,
        ).write({'state': 'closed'})
        with self.assertRaises(UserError):
            self.env['vas.loan'].generate_interest_entries(
                self.company, self.period_jan,
            )
        self.period_jan.with_context(
            vas_skip_asset_lock_check=True,
        ).write({'state': 'open'})
        # planned còn → chặn khóa
        with self.assertRaises(UserError):
            self.period_jan.write({'state': 'closed'})

    def test_direct_pay_skips_planned_blocks_posted(self):
        loan = self._make_loan(code='VAY-DIR')
        loan.action_confirm()
        Sync = self.env['vas.sync']
        bank = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.company.id),
        ], limit=1)
        if not bank:
            self.skipTest('No bank journal')
        partner = self.env['res.partner'].create({'name': 'NH Dir'})
        pay = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': partner.id,
            'amount': 1_000_000,
            'date': '2097-01-20',
            'journal_id': bank.id,
            'vas_operation_type': 'loan_interest_pay_direct',
            'vas_loan_id': loan.id,
        })
        pay.write({'state': 'paid'})
        Sync._w7_handle_direct_interest_overlap(pay)
        line = loan.line_ids.filtered(lambda l: l.period_id == self.period_jan)
        self.assertEqual(line.state, 'skipped')

        # restore planned, post interest, then direct must block
        line.state = 'planned'
        self.env['vas.loan'].generate_interest_entries(self.company, self.period_jan)
        with self.assertRaises(UserError):
            Sync._w7_handle_direct_interest_overlap(pay)

    def test_distribution_v10_v11(self):
        dist = self.env['vas.profit.distribution'].create({
            'company_id': self.company.id,
            'regime_id': self.regime.id,
            'date': '2097-01-31',
            'source_account_id': self._acc('4211').id,
            'line_ids': [
                Command.create({
                    'line_type': 'dividend',
                    'partner_id': self.env['res.partner'].create({'name': 'CSH'}).id,
                    'amount_gross': 10_000_000,
                    'withholding_rate': 0.05,
                    'dest_account_id': self._acc('3388').id,
                }),
                Command.create({
                    'line_type': 'fund',
                    'amount_gross': 2_000_000,
                    'dest_account_id': self._acc('418').id,
                }),
            ],
        })
        for line in dist.line_ids:
            line._prepare_amounts()
        dist.action_post()
        self.assertEqual(dist.state, 'posted')
        move = dist.move_id
        self.assertEqual(move.move_kind, 'profit_distribution')
        # V10 gộp: 4211 debit 12tr; 3388 9.5tr; 3335 0.5tr; 418 2tr
        debit_4211 = sum(
            l.debit for l in move.line_ids if l.account_id.code == '4211'
        )
        self.assertEqual(debit_4211, 12_000_000)
        self.assertEqual(
            sum(l.credit for l in move.line_ids if l.account_id.code == '3388'),
            9_500_000,
        )
        self.assertEqual(
            sum(l.credit for l in move.line_ids if l.account_id.code == '3335'),
            500_000,
        )
        self.assertEqual(
            sum(l.credit for l in move.line_ids if l.account_id.code == '418'),
            2_000_000,
        )

    def test_sync_loan_receipt_and_repay(self):
        loan = self._make_loan(code='VAY-SYNC', principal=50_000_000)
        loan.action_confirm()
        bank = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.company.id),
        ], limit=1)
        if not bank:
            self.skipTest('No bank journal')
        partner = self.env['res.partner'].create({'name': 'NH Sync'})
        Sync = self.env['vas.sync']
        receipt = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': 50_000_000,
            'date': '2097-01-05',
            'journal_id': bank.id,
            'vas_operation_type': 'loan_receipt',
            'vas_loan_id': loan.id,
        })
        receipt.write({'state': 'paid'})
        move = Sync._sync_one_w7_payment(receipt, self.company)
        self.assertEqual(move.move_kind, 'loan_receipt')
        self.assertIn('112', move.line_ids.filtered('debit').mapped('account_id.code')
                      + move.line_ids.filtered('debit').mapped('account_id.code'))
        # Có 3411
        self.assertIn(
            '3411',
            move.line_ids.filtered('credit').mapped('account_id.code'),
        )

        repay = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': partner.id,
            'amount': 10_000_000,
            'date': '2097-01-20',
            'journal_id': bank.id,
            'vas_operation_type': 'loan_repay',
            'vas_loan_id': loan.id,
        })
        repay.write({'state': 'paid'})
        move2 = Sync._sync_one_w7_payment(repay, self.company)
        self.assertEqual(move2.move_kind, 'loan_repay')
        loan.invalidate_recordset(['outstanding_principal'])
        loan._compute_outstanding_principal()
        self.assertEqual(loan.outstanding_principal, 40_000_000)

    def test_vas_loan_id_required(self):
        bank = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.company.id),
        ], limit=1)
        if not bank:
            self.skipTest('No bank journal')
        partner = self.env['res.partner'].create({'name': 'X'})
        with self.assertRaises(ValidationError):
            self.env['account.payment'].create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': partner.id,
                'amount': 1_000,
                'date': '2097-01-01',
                'journal_id': bank.id,
                'vas_operation_type': 'loan_receipt',
            })

    def test_loan_disbursement_post_and_reverse(self):
        loan = self._make_loan(code='VAY-V02', principal=30_000_000)
        loan.action_confirm()
        partner = self.env['res.partner'].create({'name': 'NCC V02'})
        disb = self.env['vas.loan.disbursement'].create({
            'loan_id': loan.id,
            'date': '2097-01-10',
            'amount': 30_000_000,
            'partner_id': partner.id,
            'ref': 'Giải ngân trả NCC',
        })
        disb.action_post()
        self.assertEqual(disb.state, 'posted')
        move = disb.move_id
        self.assertTrue(move)
        self.assertEqual(move.move_kind, 'loan_disburse')
        self.assertEqual(move.state, 'posted')
        debit_codes = move.line_ids.filtered('debit').mapped('account_id.code')
        credit_codes = move.line_ids.filtered('credit').mapped('account_id.code')
        self.assertIn('331', debit_codes)
        self.assertEqual(credit_codes, [loan.account_loan_id.code])

        disb.action_cancel()
        self.assertEqual(disb.state, 'cancelled')
        move.invalidate_recordset()
        self.assertIn(move.state, ('reversed', 'cancelled'))

    def test_capital_in_kind_post_and_spawn_asset(self):
        partner = self.env['res.partner'].create({'name': 'CSH góp TS'})
        rec = self.env['vas.capital.in.kind'].create({
            'date': '2097-01-12',
            'amount': 80_000_000,
            'partner_id': partner.id,
            'asset_account_id': self.acc['2111'].id,
            'ref': 'Góp TSCĐ',
            'spawn_asset': True,
            'asset_name': 'Máy góp vốn',
        })
        rec.action_post()
        self.assertEqual(rec.state, 'posted')
        move = rec.move_id
        self.assertEqual(move.move_kind, 'capital_receipt')
        debit = move.line_ids.filtered('debit')
        credit = move.line_ids.filtered('credit')
        self.assertEqual(debit.account_id, self.acc['2111'])
        self.assertEqual(credit.account_id.code, '4111')
        self.assertTrue(rec.asset_id)
        self.assertEqual(rec.asset_id.state, 'draft')
        self.assertEqual(rec.asset_id.original_value, 80_000_000)
        self.assertEqual(rec.asset_id.name, 'Máy góp vốn')

    def test_no_odoo_misc_je_path_to_vas_ledger(self):
        """Khẳng định: không còn đọc bút toán tổng hợp Odoo để sinh sổ VAS."""
        Sync = self.env['vas.sync']
        self.assertFalse(
            hasattr(Sync, '_sync_one_w7_misc'),
            'Đường _sync_one_w7_misc đã gỡ — không thêm lại.',
        )
        self.assertFalse(
            hasattr(type(Sync), '_W7_MISC_OPS'),
            '_W7_MISC_OPS đã gỡ — không thêm lại.',
        )
        Move = self.env['account.move']
        for fname in (
            'vas_operation_type',
            'vas_loan_id',
            'vas_spawn_fixed_asset',
        ):
            self.assertNotIn(
                fname, Move._fields,
                'Field %s trên account.move đã gỡ (chỉ phục vụ đường misc cũ).' % fname,
            )
        import inspect
        src = inspect.getsource(type(Sync)._sync_loan_and_capital)
        self.assertNotIn("move_type', '=', 'entry'", src)
        self.assertNotIn('move_type", "=", "entry"', src)
        self.assertNotIn('_sync_one_w7_misc', src)

    def test_migration_warns_legacy_misc_labels(self):
        import importlib.util
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / (
            'migrations/19.0.1.61.0/post-migrate.py'
        )
        spec = importlib.util.spec_from_file_location(
            'vas_w7_post_migrate_61', path,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cr = self.env.cr
        cr.execute("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'account_move'
               AND column_name = 'vas_operation_type'
        """)
        created_col = False
        if not cr.fetchone():
            cr.execute(
                "ALTER TABLE account_move "
                "ADD COLUMN vas_operation_type VARCHAR"
            )
            created_col = True
        try:
            gen_j = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', self.company.id),
            ], limit=1)
            if not gen_j:
                self.skipTest('No general journal')
            accs = self.env['account.account'].search([
                ('company_ids', 'in', self.company.id),
            ], limit=2)
            if len(accs) < 2:
                self.skipTest('Need 2 Odoo accounts')
            amove = self.env['account.move'].create({
                'move_type': 'entry',
                'date': '2097-02-01',
                'journal_id': gen_j.id,
                'line_ids': [
                    Command.create({
                        'account_id': accs[0].id,
                        'debit': 1000, 'credit': 0, 'name': 'legacy',
                    }),
                    Command.create({
                        'account_id': accs[1].id,
                        'debit': 0, 'credit': 1000, 'name': 'legacy',
                    }),
                ],
            })
            amove.action_post()
            cr.execute(
                "UPDATE account_move SET vas_operation_type = %s WHERE id = %s",
                ('loan_disburse_vendor', amove.id),
            )
            warned = mod.warn_legacy_w7_misc_labels(cr)
            self.assertTrue(
                any(r[0] == amove.id for r in warned),
                'Migration phải liệt kê bút toán mang nhãn cũ.',
            )
            self.assertTrue(
                any(r[2] == 'loan_disburse_vendor' for r in warned),
            )
        finally:
            if created_col:
                cr.execute(
                    "ALTER TABLE account_move "
                    "DROP COLUMN IF EXISTS vas_operation_type"
                )
    def test_cancel_loan(self):
        loan = self._make_loan(code='VAY-CAN')
        loan.action_confirm()
        self.env['vas.loan'].generate_interest_entries(self.company, self.period_jan)
        loan.action_cancel()
        self.assertEqual(loan.state, 'cancelled')
        line = loan.line_ids.filtered(lambda l: l.period_id == self.period_jan)
        self.assertEqual(line.state, 'skipped')
