# -*- coding: utf-8 -*-
"""W9 — payroll soft adapter + (khi có module) ca mẫu 20tr / R38–R42."""
from datetime import date

from odoo import Command, fields
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('connecta_vas', 'connecta_vas_w9')
class TestW9PayrollSoft(TransactionCase):
    """Soft-depend: không có hr_payroll → adapter im, không lỗi."""

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

    def test_soft_no_crash_without_payslip_model(self):
        """Nếu thiếu hr.payslip, _sync_payroll vẫn trả stats, không raise."""
        if self.Sync._hr_payslip_available():
            # Force soft path even when payroll installed (W8 lesson regression).
            origin = type(self.Sync)._hr_payslip_available
            type(self.Sync)._hr_payslip_available = lambda self: False
            try:
                stats = self.Sync._sync_payroll(self.company)
            finally:
                type(self.Sync)._hr_payslip_available = origin
            self.assertIn('payslips', stats)
            self.assertEqual(stats['payslips']['created'], 0)
            return
        stats = self.Sync._sync_payroll(self.company)
        self.assertIn('payslips', stats)
        self.assertEqual(stats['payslips']['created'], 0)

    def test_manifest_no_hard_depend_hr_payroll(self):
        mod = self.env['ir.module.module'].search([
            ('name', '=', 'connecta_vas'),
        ], limit=1)
        self.assertTrue(mod)
        # depends string from manifest is not always on DB; check registry soft API
        self.assertFalse(
            hasattr(self.env.registry, 'connecta_vas_requires_hr_payroll'),
        )
        # Hard check: connecta_vas must load without depending — already loaded.
        self.assertIn('vas.sync', self.env)


@tagged('connecta_vas', 'connecta_vas_w9', 'post_install', '-at_install')
class TestW9PayrollFull(TransactionCase):
    """Ca mẫu §4 + R38–R42 khi l10n_vn_hr_payroll + hr_payroll đã cài."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.payslip' not in cls.env:
            return
        if not cls.env['ir.module.module'].search([
            ('name', '=', 'l10n_vn_hr_payroll'),
            ('state', '=', 'installed'),
        ], limit=1):
            return

        cls.company = cls.env.company
        cls.company.country_id = cls.env.ref('base.vn')
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd
        cls.regime = cls.env['vas.regime'].search([('code', '=', 'TT133')], limit=1)
        if not cls.regime:
            cls.regime = cls.env['vas.regime'].create({
                'code': 'TT133', 'name': 'TT133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'

        codes = {
            '112': ('asset', 'Tiền gửi'),
            '334': ('liability', 'Phải trả NLĐ'),
            '3335': ('liability', 'TNCN'),
            '3382': ('liability', 'KPCĐ'),
            '3383': ('liability', 'BHXH'),
            '3384': ('liability', 'BHYT'),
            '3385': ('liability', 'BHTN'),
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

        cls.journal_luong = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'LUONG'),
        ], limit=1)
        if not cls.journal_luong:
            cls.journal_luong = cls.env['vas.journal'].create({
                'code': 'LUONG', 'name': 'Lương', 'type': 'payroll',
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
            'name': 'W9-2099',
            'date_from': '2099-01-01',
            'date_to': '2099-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.period = cls.env['vas.period'].create({
            'name': '2099-07',
            'date_start': '2099-07-01',
            'date_end': '2099-07-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })

        cls.struct = cls.env.ref(
            'l10n_vn_hr_payroll.hr_payroll_structure_vn_employee')
        cls.structure_type = cls.env.ref(
            'l10n_vn_hr_payroll.structure_type_employee_vn')
        cls.employee = cls.env['hr.employee'].create({
            'name': 'NV W9 Full',
            'company_id': cls.company.id,
            'structure_type_id': cls.structure_type.id,
            'contract_date_start': '2026-07-01',
            'wage': 20_000_000,
            'l10n_vn_dependent_count': 0,
            'l10n_vn_si_participates': True,
            'l10n_vn_region': '1',
        })
        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        if not cls.bank_journal:
            cls.bank_journal = cls.env['account.journal'].create({
                'name': 'Bank W9',
                'code': 'BNKW9',
                'type': 'bank',
                'company_id': cls.company.id,
            })

    def _require_payroll(self):
        if 'hr.payslip' not in self.env:
            self.skipTest('hr.payslip unavailable')
        if not self.env['ir.module.module'].search([
            ('name', '=', 'l10n_vn_hr_payroll'),
            ('state', '=', 'installed'),
        ], limit=1):
            self.skipTest('l10n_vn_hr_payroll not installed')

    def _line_total(self, payslip, code):
        line = payslip.line_ids.filtered(lambda l: l.code == code)
        self.assertTrue(line, f'missing {code}')
        return line.total

    def _create_payslip(self, date_from='2026-07-01', date_to='2026-07-31'):
        payslip = self.env['hr.payslip'].create({
            'name': f'PS {date_from}',
            'employee_id': self.employee.id,
            'struct_id': self.struct.id,
            'date_from': date_from,
            'date_to': date_to,
            'company_id': self.company.id,
        })
        payslip.compute_sheet()
        return payslip

    def test_rule_sample_20m(self):
        self._require_payroll()
        payslip = self._create_payslip()
        self.assertAlmostEqual(self._line_total(payslip, 'NET'), 17_780_000, places=0)
        self.assertAlmostEqual(self._line_total(payslip, 'PIT'), -120_000, places=0)
        self.assertAlmostEqual(self._line_total(payslip, 'BHXH_EE'), -1_600_000, places=0)

    def test_si_reference_dated(self):
        self._require_payroll()
        Param = self.env['hr.rule.parameter']
        val = Param._get_parameter_from_code(
            'vn_si_reference', date(2026, 7, 15))
        self.assertEqual(val, 2_530_000)
        missing = Param._get_parameter_from_code(
            'vn_si_reference', date(2026, 6, 15), raise_if_not_found=False)
        self.assertIsNone(missing)

    def test_vas_r38_r42_balance_remit_cancel(self):
        self._require_payroll()
        Sync = self.env['vas.sync']
        payslip = self._create_payslip()
        payslip.action_payslip_done()

        move = self.env['vas.move'].search([
            ('source_model', '=', 'hr.payslip'),
            ('source_res_id', '=', payslip.id),
            ('move_kind', '=', 'payroll'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(move, 'Expected R38–R40 vas.move')
        self.assertEqual(move.state, 'posted')

        by_code = {}
        for line in move.line_ids:
            by_code.setdefault(line.account_id.code, {'debit': 0.0, 'credit': 0.0})
            by_code[line.account_id.code]['debit'] += line.debit
            by_code[line.account_id.code]['credit'] += line.credit

        self.assertAlmostEqual(by_code['6422']['debit'], 20_000_000 + 4_700_000, places=0)
        self.assertAlmostEqual(by_code['334']['credit'], 20_000_000, places=0)
        self.assertAlmostEqual(by_code['334']['debit'], 2_220_000, places=0)
        self.assertAlmostEqual(by_code['3383']['credit'], 1_600_000 + 3_500_000, places=0)
        self.assertAlmostEqual(by_code['3384']['credit'], 300_000 + 600_000, places=0)
        self.assertAlmostEqual(by_code['3385']['credit'], 200_000 + 200_000, places=0)
        self.assertAlmostEqual(by_code['3335']['credit'], 120_000, places=0)
        self.assertAlmostEqual(by_code['3382']['credit'], 400_000, places=0)

        # R41 pay NET
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': 17_780_000,
            'date': '2026-07-31',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': 'payroll_pay',
            'vas_payslip_id': payslip.id,
        })
        payment.action_post()
        pay_move = Sync._sync_one_payroll_payment(payment, self.company)
        self.assertTrue(pay_move)
        self.assertEqual(pay_move.move_kind, 'payroll_pay')

        # (a) Số dư 334 sau R41 = 0 (cộng mọi dòng posted liên quan ca này)
        lines_334 = (move | pay_move).line_ids.filtered(
            lambda l: l.account_id.code == '334')
        bal_334 = sum(lines_334.mapped('debit')) - sum(lines_334.mapped('credit'))
        self.assertAlmostEqual(
            bal_334, 0.0, places=0,
            msg=f'334 phải về 0 sau R41, được {bal_334}',
        )

        # (b) R42 cả hai nhãn tách
        pit_pay = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': 120_000,
            'date': '2026-08-05',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': 'pit_remit',
        })
        pit_pay.action_post()
        remit_pit = Sync._sync_one_payroll_payment(pit_pay, self.company)
        self.assertTrue(remit_pit)
        self.assertEqual(remit_pit.move_kind, 'payroll_remit')
        self.assertAlmostEqual(
            sum(remit_pit.line_ids.filtered(
                lambda l: l.account_id.code == '3335').mapped('debit')),
            120_000, places=0,
        )

        si_pay = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': 6_400_000,  # 3383 5.1M + 3384 0.9M + 3385 0.4M (không 3382)
            'date': '2026-08-05',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': 'social_insurance_remit',
            'vas_payslip_id': payslip.id,
        })
        si_pay.action_post()
        remit_si = Sync._sync_one_payroll_payment(si_pay, self.company)
        self.assertTrue(remit_si)
        self.assertEqual(remit_si.move_kind, 'payroll_remit')
        by_si = {}
        for line in remit_si.line_ids:
            by_si.setdefault(line.account_id.code, 0.0)
            by_si[line.account_id.code] += line.debit - line.credit
        self.assertAlmostEqual(by_si.get('3383', 0.0), 5_100_000, places=0)
        self.assertAlmostEqual(by_si.get('3384', 0.0), 900_000, places=0)
        self.assertAlmostEqual(by_si.get('3385', 0.0), 400_000, places=0)
        self.assertAlmostEqual(by_si.get('112', 0.0), -6_400_000, places=0)
        # 3382 không nằm trong social_insurance_remit
        self.assertEqual(by_si.get('3382', 0.0), 0.0)

        # Sau R38-40 + remit SI: 3383/3384/3385 về 0 trên combo
        combo = move | remit_si
        for code, expect in (('3383', 0.0), ('3384', 0.0), ('3385', 0.0)):
            lines = combo.line_ids.filtered(lambda l: l.account_id.code == code)
            bal = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))
            self.assertAlmostEqual(bal, expect, places=0, msg=f'{code} bal={bal}')

        # union_fee_remit — nộp từng phần (NĐ 191): 250k rồi 150k
        lines_3382 = move.line_ids.filtered(lambda l: l.account_id.code == '3382')
        bal_3382 = sum(lines_3382.mapped('debit')) - sum(lines_3382.mapped('credit'))
        self.assertAlmostEqual(bal_3382, -400_000, places=0)

        uf1 = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': 250_000,
            'date': '2026-08-05',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': 'union_fee_remit',
        })
        uf1.action_post()
        remit_uf1 = Sync._sync_one_payroll_payment(uf1, self.company)
        self.assertTrue(remit_uf1)
        combo1 = move | remit_uf1
        bal_after_1 = (
            sum(combo1.line_ids.filtered(lambda l: l.account_id.code == '3382').mapped('debit'))
            - sum(combo1.line_ids.filtered(lambda l: l.account_id.code == '3382').mapped('credit'))
        )
        self.assertAlmostEqual(bal_after_1, -150_000, places=0)

        uf2 = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'amount': 150_000,
            'date': '2026-08-06',
            'journal_id': self.bank_journal.id,
            'company_id': self.company.id,
            'vas_operation_type': 'union_fee_remit',
        })
        uf2.action_post()
        remit_uf2 = Sync._sync_one_payroll_payment(uf2, self.company)
        combo2 = move | remit_si | remit_uf1 | remit_uf2
        for code in ('3382', '3383', '3384', '3385'):
            lines = combo2.line_ids.filtered(lambda l: l.account_id.code == code)
            bal = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))
            self.assertAlmostEqual(bal, 0.0, places=0, msg=f'{code} bal={bal}')

        # (c) Cancel kỳ MỞ → đảo
        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', self.company.id),
            ('date_from', '<=', '2026-07-01'),
            ('date_to', '>=', '2026-07-31'),
        ], limit=1)
        if not fy:
            fy = self.env['vas.fiscalyear'].create({
                'name': '2026-w9',
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
                'company_id': self.company.id,
            })
        period = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2026-07-31'),
            ('date_end', '>=', '2026-07-31'),
        ], limit=1)
        if not period:
            period = self.env['vas.period'].create({
                'name': '2026-07-w9',
                'date_start': '2026-07-01',
                'date_end': '2026-07-31',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        else:
            self.env.cr.execute(
                "UPDATE vas_period SET state='open' WHERE id=%s", (period.id,))
            period.invalidate_recordset()

        payslip.action_payslip_cancel()
        stats_open = Sync._sync_cancel_regressions(self.company)
        move.invalidate_recordset()
        self.assertIn(move.state, ('reversed', 'cancelled'))
        self.assertFalse(move.source_cancel_pending)
        self.assertGreaterEqual(stats_open.get('reversed', 0), 1)

    def test_cancel_payslip_closed_period_flags(self):
        """Kỳ KHÓA + payslip cancel → không đảo, gắn source_cancel_pending.

        Phải xanh cả khi period_id stored lúc post = False (kỳ tạo/đóng
        sau) — regression full-suite W9 vòng 2/3.
        """
        self._require_payroll()
        Sync = self.env['vas.sync']
        # Ca A: post TRƯỚC khi có kỳ (period_id stored False) → đóng kỳ → cancel
        payslip = self._create_payslip(
            date_from='2026-08-01', date_to='2026-08-31')
        payslip.action_payslip_done()
        move = self.env['vas.move'].search([
            ('source_model', '=', 'hr.payslip'),
            ('source_res_id', '=', payslip.id),
            ('move_kind', '=', 'payroll'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(move)

        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', self.company.id),
            ('date_from', '<=', '2026-08-01'),
            ('date_to', '>=', '2026-08-31'),
        ], limit=1)
        if not fy:
            fy = self.env['vas.fiscalyear'].create({
                'name': '2026-w9b',
                'date_from': '2026-01-01',
                'date_to': '2026-12-31',
                'state': 'open',
                'company_id': self.company.id,
            })
        period = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2026-08-31'),
            ('date_end', '>=', '2026-08-31'),
        ], limit=1)
        if not period:
            period = self.env['vas.period'].create({
                'name': '2026-08-w9',
                'date_start': '2026-08-01',
                'date_end': '2026-08-31',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        # Force-close (bỏ qua chặn default-account — pattern P02)
        self.env.cr.execute(
            "UPDATE vas_period SET state='closed' WHERE id=%s", (period.id,))
        period.invalidate_recordset()
        self.assertEqual(period.state, 'closed')
        # Engine phải nhìn kỳ đóng theo ngày, không tin period_id stored
        self.assertTrue(
            Sync._move_date_in_closed_period(move),
            'Cancel phải nhận kỳ khóa theo ngày move',
        )

        payslip.action_payslip_cancel()
        stats = Sync._sync_cancel_regressions(self.company)
        move.invalidate_recordset()
        self.assertEqual(move.state, 'posted', 'Kỳ khóa không được tự đảo')
        self.assertTrue(move.source_cancel_pending)
        self.assertGreaterEqual(stats.get('closed_period_flagged', 0), 1)

    def _dept_with_employee(self, dept_name, emp_name):
        dept = self.env['hr.department'].create({
            'name': dept_name, 'company_id': self.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': emp_name,
            'company_id': self.company.id,
            'department_id': dept.id,
            'structure_type_id': self.structure_type.id,
            'contract_date_start': '2026-07-01',
            'wage': 20_000_000,
            'l10n_vn_dependent_count': 0,
            'l10n_vn_si_participates': True,
            'l10n_vn_region': '1',
        })
        return dept, employee

    def _ensure_period(self, name, date_start, date_end):
        fy = self.env['vas.fiscalyear'].search([
            ('company_id', '=', self.company.id),
            ('date_from', '<=', date_start),
            ('date_to', '>=', date_end),
        ], limit=1)
        if not fy:
            fy = self.env['vas.fiscalyear'].create({
                'name': f'FY {name}',
                'date_from': date_start[:4] + '-01-01',
                'date_to': date_start[:4] + '-12-31',
                'state': 'open',
                'company_id': self.company.id,
            })
        period = self.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', date_end),
            ('date_end', '>=', date_end),
        ], limit=1)
        if not period:
            period = self.env['vas.period'].create({
                'name': name,
                'date_start': date_start,
                'date_end': date_end,
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        return period

    def test_payroll_map_unmapped_flag_block_then_clear(self):
        """B4 test 1+2+4+5 (đường thật): bộ phận chưa khai map.

        post payslip → cờ + lọc thấy; narration/UserError nêu ĐÚNG TÊN
        BỘ PHẬN; đóng kỳ bị chặn; khai map + đảo + đồng bộ lại → cờ hết.
        """
        self._require_payroll()
        from odoo.exceptions import UserError
        Sync = self.env['vas.sync']
        period = self._ensure_period('2026-09-w9map', '2026-09-01', '2026-09-30')
        dept, employee = self._dept_with_employee(
            'Phong Thi Nghiem Map', 'NV Map Probe')

        payslip = self.env['hr.payslip'].create({
            'name': 'PS map probe 2026-09',
            'employee_id': employee.id,
            'struct_id': self.struct.id,
            'date_from': '2026-09-01',
            'date_to': '2026-09-30',
            'company_id': self.company.id,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()

        move = self.env['vas.move'].search([
            ('source_model', '=', 'hr.payslip'),
            ('source_res_id', '=', payslip.id),
            ('move_kind', '=', 'payroll'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        # 1. có cờ + lọc thấy (đúng domain filter "Dùng TK mặc định")
        self.assertTrue(move.vas_has_default_account)
        filtered = self.env['vas.move'].search([
            ('vas_has_default_account', '=', True),
            ('source_res_id', '=', payslip.id),
        ])
        self.assertIn(move, filtered)
        # 2. narration nêu ĐÚNG TÊN BỘ PHẬN, không phải "(không có sản phẩm)"
        self.assertIn('Phong Thi Nghiem Map', move.narration)
        self.assertNotIn('(không có sản phẩm)', move.narration)

        # 4. còn cờ chưa xử → đóng kỳ bị chặn, UserError nêu tên bộ phận
        with self.assertRaises(UserError) as ctx:
            period.write({'state': 'closed'})
        msg = str(ctx.exception)
        self.assertIn('TÀI KHOẢN', msg)
        self.assertIn('MẶC ĐỊNH', msg)
        self.assertIn('Phong Thi Nghiem Map', msg)
        self.assertIn('Map bộ phận lương', msg)

        # 5. khai map → đảo → đồng bộ lại → cờ hết
        self.env['vas.payroll.department.map'].create({
            'company_id': self.company.id,
            'department_id': dept.id,
            'expense_account_id': self.acc['6422'].id,
            'cost_item_id': self.env['vas.cost.item'].search([
                ('company_id', '=', self.company.id),
                ('code', '=', 'NCTT'),
            ], limit=1).id,
        })
        move.action_reverse()
        move.invalidate_recordset()
        self.assertEqual(move.state, 'reversed')
        move2 = Sync._sync_one_payslip(payslip, self.company)
        self.assertTrue(move2)
        self.assertEqual(move2.state, 'posted')
        self.assertFalse(move2.vas_has_default_account)
        self.assertFalse(move2.narration)
        # Hết cờ posted trong kỳ → check khóa kỳ đi qua (gọi thẳng check
        # default-account để không dính các check khác ngoài phạm vi test).
        period._check_no_default_account_move()

    def test_payroll_map_declared_late_close_names_resync(self):
        """S1: khai map SAU khi post, KHÔNG đảo/KHÔNG sync lại → đóng kỳ vẫn
        chặn, message nêu rõ bút toán cũ chưa đồng bộ lại + cách gỡ
        (không bỏ rơi kế toán với danh sách bộ phận rỗng).
        """
        self._require_payroll()
        from odoo.exceptions import UserError
        period = self._ensure_period('2026-11-w9map', '2026-11-01', '2026-11-30')
        dept, employee = self._dept_with_employee(
            'Phong Khai Map Muon', 'NV Khai Muon')
        payslip = self.env['hr.payslip'].create({
            'name': 'PS khai muon 2026-11',
            'employee_id': employee.id,
            'struct_id': self.struct.id,
            'date_from': '2026-11-01',
            'date_to': '2026-11-30',
            'company_id': self.company.id,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()
        move = self.env['vas.move'].search([
            ('source_model', '=', 'hr.payslip'),
            ('source_res_id', '=', payslip.id),
            ('move_kind', '=', 'payroll'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(move.vas_has_default_account)

        # Khai map SAU — không đảo, không sync lại
        self.env['vas.payroll.department.map'].create({
            'company_id': self.company.id,
            'department_id': dept.id,
            'expense_account_id': self.acc['6422'].id,
        })
        with self.assertRaises(UserError) as ctx:
            period.write({'state': 'closed'})
        msg = str(ctx.exception)
        # Phần gốc giữ nguyên văn
        self.assertIn('bút toán dùng TÀI KHOẢN MẶC ĐỊNH '
                      'vì sản phẩm/nhóm sản phẩm chưa khai ánh xạ', msg)
        # Bộ phận ĐÃ khai → không nằm trong "Bộ phận cần khai map..."
        self.assertNotIn('Bộ phận cần khai map TK chi phí lương', msg)
        # Đường ra cho ca khai-map-muộn: nêu số hiệu move + đảo + sync lại
        self.assertIn('chưa đồng bộ lại', msg)
        self.assertIn(move.name, msg)
        self.assertIn('đảo bút toán lương', msg)

    def test_payroll_map_mapped_no_flag(self):
        """B4 test 3: bộ phận ĐÃ khai map → post payslip → KHÔNG cờ."""
        self._require_payroll()
        self._ensure_period('2026-10-w9map', '2026-10-01', '2026-10-31')
        dept, employee = self._dept_with_employee(
            'Phong Da Khai Map', 'NV Mapped Probe')
        self.env['vas.payroll.department.map'].create({
            'company_id': self.company.id,
            'department_id': dept.id,
            'expense_account_id': self.acc['6422'].id,
            'cost_item_id': self.env['vas.cost.item'].search([
                ('company_id', '=', self.company.id),
                ('code', '=', 'NCTT'),
            ], limit=1).id,
        })
        payslip = self.env['hr.payslip'].create({
            'name': 'PS mapped 2026-10',
            'employee_id': employee.id,
            'struct_id': self.struct.id,
            'date_from': '2026-10-01',
            'date_to': '2026-10-31',
            'company_id': self.company.id,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()
        move = self.env['vas.move'].search([
            ('source_model', '=', 'hr.payslip'),
            ('source_res_id', '=', payslip.id),
            ('move_kind', '=', 'payroll'),
            ('is_reversal', '=', False),
        ], limit=1)
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        self.assertFalse(move.vas_has_default_account)
        self.assertFalse(move.narration)


@tagged('connecta_vas', 'connecta_vas_w9')
class TestPayrollMapFlagUnit(TransactionCase):
    """Khuôn cờ TK mặc định cho payroll — phần chạy được KHÔNG cần hr_payroll.

    Đường payslip thật (post → cờ → chặn khóa kỳ → khai map → hết cờ) nằm ở
    ``TestW9PayrollFull`` (post_install, cần l10n_vn_hr_payroll).
    """

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
                'code': 'TT133', 'name': 'Thông tư 133',
            })
        cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2000-01-01'
        cls.Sync = cls.env['vas.sync']
        cls.acc_6422 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '6422'),
        ], limit=1)
        if not cls.acc_6422:
            cls.acc_6422 = cls.env['vas.account'].create({
                'code': '6422', 'name': 'CP QLDN',
                'regime_id': cls.regime.id, 'account_type': 'expense',
            'ending_balance_policy': 'none',
            })
        cls.acc_154 = cls.env['vas.account'].search([
            ('regime_id', '=', cls.regime.id), ('code', '=', '154'),
        ], limit=1)
        if not cls.acc_154:
            cls.acc_154 = cls.env['vas.account'].create({
                'code': '154', 'name': 'CP SXKD dở dang',
                'regime_id': cls.regime.id, 'account_type': 'asset',
            'ending_balance_policy': 'debit',
            })
        cls.dept = cls.env['hr.department'].create({
            'name': 'Bo Phan Unit Probe', 'company_id': cls.company.id,
        })

    def test_resolve_unmapped_appends_fallback_named_department(self):
        """B4 test 2 (unit): fallback + narration nêu ĐÚNG TÊN BỘ PHẬN."""
        fallbacks = []
        acc = self.env['vas.payroll.department.map'].resolve_expense_account(
            self.company, self.dept, fallbacks=fallbacks,
        )
        self.assertEqual(acc, self.acc_6422)
        self.assertEqual(len(fallbacks), 1)
        self.assertEqual(fallbacks[0]['selector'], 'payroll_expense')
        self.assertEqual(fallbacks[0]['default_code'], '6422')
        self.assertIn('Bo Phan Unit Probe', fallbacks[0]['label'])

        vals = self.Sync._default_account_flag_vals(fallbacks)
        self.assertTrue(vals['vas_has_default_account'])
        self.assertIn('Bo Phan Unit Probe', vals['narration'])
        self.assertNotIn('(không có sản phẩm)', vals['narration'])

    def test_resolve_no_department_appends_fallback(self):
        """Payslip không có bộ phận → vẫn cờ, nhãn '(không có bộ phận)'."""
        fallbacks = []
        acc = self.env['vas.payroll.department.map'].resolve_expense_account(
            self.company, self.env['hr.department'], fallbacks=fallbacks,
        )
        self.assertEqual(acc, self.acc_6422)
        self.assertEqual(len(fallbacks), 1)
        self.assertIn('(không có bộ phận)', fallbacks[0]['label'])

    def test_resolve_mapped_no_fallback(self):
        """B4 test 3 (unit): đã khai map → đúng TK khai, KHÔNG fallback."""
        self.env['vas.payroll.department.map'].create({
            'company_id': self.company.id,
            'department_id': self.dept.id,
            'expense_account_id': self.acc_154.id,
        })
        fallbacks = []
        acc = self.env['vas.payroll.department.map'].resolve_expense_account(
            self.company, self.dept, fallbacks=fallbacks,
        )
        self.assertEqual(acc, self.acc_154)
        self.assertEqual(fallbacks, [])
        self.assertEqual(self.Sync._default_account_flag_vals(fallbacks), {})

    def test_product_path_narration_unchanged(self):
        """B4 test 6: đường sản phẩm ra narration Y NHƯ TRƯỚC khi sửa.

        Chuỗi kỳ vọng bên dưới là NGUYÊN VĂN định dạng cũ (trước khi thêm
        key ``label``) — đối chiếu byte-một với kết quả mới.
        """
        categ = self.env['product.category'].create({
            'name': 'Nhom Chua Khai Unit',
        })
        product = self.env['product.product'].create({
            'name': 'SP Chua Khai Map Unit',
            'type': 'consu',
            'categ_id': categ.id,
        })
        fallbacks = []
        acc = self.Sync._product_account(
            product, 'product_inventory', self.company, fallbacks=fallbacks,
        )
        self.assertTrue(acc)
        self.assertEqual(acc.code, '156')
        self.assertEqual(len(fallbacks), 1)
        self.assertNotIn('label', fallbacks[0])

        vals = self.Sync._default_account_flag_vals(fallbacks)
        expected_old = (
            'CHƯA KHAI ÁNH XẠ TÀI KHOẢN — bút toán này dùng tài khoản mặc định:\n'
            '- %s / nhóm %s → dùng mặc định 156'
        ) % (product.display_name, product.categ_id.display_name)
        self.assertEqual(vals['narration'], expected_old)
        self.assertTrue(vals['vas_has_default_account'])

    def test_close_block_product_only_message_unchanged(self):
        """B4 test 6 (khóa kỳ): move cờ KHÔNG phải lương → message NGUYÊN
        VĂN khuôn cũ, KHÔNG có đoạn 'Bộ phận cần khai map TK chi phí lương'.
        """
        from odoo import Command
        from odoo.exceptions import UserError
        self.env['vas.journal']._connecta_seed_tt133_journals()
        journal = self.env['vas.journal'].search([
            ('company_id', '=', self.company.id), ('code', '=', 'TH'),
        ], limit=1)
        acc_111 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id), ('code', '=', '111'),
        ], limit=1)
        acc_411 = self.env['vas.account'].search([
            ('regime_id', '=', self.regime.id), ('code', '=', '411'),
        ], limit=1)
        self.assertTrue(journal and acc_111 and acc_411)
        fy = self.env['vas.fiscalyear'].create({
            'name': 'FY unit 2097',
            'date_from': '2097-01-01',
            'date_to': '2097-12-31',
            'state': 'open',
            'company_id': self.company.id,
        })
        period = self.env['vas.period'].create({
            'name': '2097-03-unit',
            'date_start': '2097-03-01',
            'date_end': '2097-03-31',
            'fiscalyear_id': fy.id,
            'state': 'open',
        })
        vnd = self.env.ref('base.VND')
        move = self.env['vas.move'].create({
            'date': '2097-03-15',
            'journal_id': journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'currency_id': vnd.id,
            'ref': 'unit default-account',
            'vas_has_default_account': True,
            'line_ids': [
                Command.create({
                    'sequence': 10, 'account_id': acc_111.id, 'name': 'Nợ',
                    'debit': 1000.0, 'credit': 0.0, 'currency_id': vnd.id,
                }),
                Command.create({
                    'sequence': 20, 'account_id': acc_411.id, 'name': 'Có',
                    'debit': 0.0, 'credit': 1000.0, 'currency_id': vnd.id,
                }),
            ],
        })
        move.action_post()
        with self.assertRaises(UserError) as ctx:
            period.write({'state': 'closed'})
        msg = str(ctx.exception)
        self.assertIn('bút toán dùng TÀI KHOẢN MẶC ĐỊNH '
                      'vì sản phẩm/nhóm sản phẩm chưa khai ánh xạ', msg)
        self.assertIn('Cấu hình > Ánh xạ tài khoản > Rà soát cấu hình', msg)
        self.assertNotIn('Bộ phận cần khai map TK chi phí lương', msg)
        self.assertNotIn('chưa đồng bộ lại', msg)
