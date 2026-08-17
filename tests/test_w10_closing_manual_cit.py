# -*- coding: utf-8 -*-
"""W10 chặng 4 — dòng nhập tay + CIT + kế thừa khi đảo."""
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10ClosingManualCit(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        if not cls.company.vas_regime_id:
            cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2090-01-01'
        cls.company.fiscalyear_last_day = 31
        cls.company.fiscalyear_last_month = '12'
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2090-06-15'),
            ('date_to', '>=', '2090-06-15'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W10C-2090',
                'date_from': '2090-01-01',
                'date_to': '2090-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2090-06-01'),
        ], limit=1)
        if not period:
            cls.env['vas.period'].create({
                'name': '06/2090-C',
                'date_start': '2090-06-01',
                'date_end': '2090-06-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        # Kỳ 12 cho CIT cuối năm
        if not cls.env['vas.period'].search([
            ('fiscalyear_id.company_id', '=', cls.company.id),
            ('date_start', '=', '2090-12-01'),
        ], limit=1):
            cls.env['vas.period'].create({
                'name': '12/2090-C',
                'date_start': '2090-12-01',
                'date_end': '2090-12-31',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        cls.fy = fy
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'KC'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].search([
                ('company_id', '=', cls.company.id),
            ], limit=1)
        cls.Entry = cls.env['vas.closing.entry']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post_pair(self, day, debit_acc, credit_acc, amount, name='W10C'):
        move = self.env['vas.move'].create({
            'date': day,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'ref': name,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id, 'name': name,
                    'debit': amount, 'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': credit_acc.id, 'name': name,
                    'debit': 0.0, 'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _make_entry(self, **kwargs):
        vals = {
            'company_id': self.company.id,
            'date_from': '2090-06-01',
            'date_to': '2090-06-30',
            'run_kqkd': False,
            'run_year_start': False,
            'run_fx': False,
            'run_vat': False,
            'run_prepaid': False,
            'run_manual': False,
            'run_cit': False,
        }
        vals.update(kwargs)
        return self.Entry.create(vals)

    def test_01_manual_zero_skipped_on_post(self):
        entry = self._make_entry(run_manual=True)
        entry.action_fetch_data()
        zeros = entry.line_ids.filtered(
            lambda l: l.is_manual and float_is_zero(l.amount, precision_digits=2)
        )
        self.assertTrue(zeros)
        # Điền một dòng để có gì ghi sổ; các dòng 0 còn lại bỏ qua
        filled = entry.line_ids.filtered(lambda l: l.template_code == 'C02')
        filled.amount = 10_000.0
        entry.action_post()
        moves = entry._batch_active_moves()
        self.assertEqual(len(moves), 1)
        move = moves
        # Chỉ 1 cặp Nợ/Có từ C02 — không có dòng amount 0
        self.assertEqual(len(move.line_ids), 2)
        self.assertIn('6422', move.line_ids.mapped('account_id.code'))
        self.assertIn('335', move.line_ids.mapped('account_id.code'))

    def test_02_manual_filled_posts(self):
        entry = self._make_entry(run_manual=True)
        entry.action_fetch_data()
        c03 = entry.line_ids.filtered(lambda l: l.template_code == 'C03')
        c03.amount = 25_000.0
        entry.action_post()
        codes = set(
            entry._batch_active_moves().mapped('line_ids.account_id.code')
        )
        self.assertEqual(codes, {'6422', '2293'})

    def test_03_provision_shows_229_balance(self):
        self._post_pair('2090-06-10', self._acc('6422'), self._acc('2293'), 40_000, 'DP')
        entry = self._make_entry(run_manual=True)
        entry.action_fetch_data()
        c03 = entry.line_ids.filtered(lambda l: l.template_code == 'C03')
        self.assertTrue(c03.balance_hint)
        self.assertIn('2293', c03.balance_hint)
        self.assertIn('40', c03.balance_hint.replace(',', ''))

    def test_04_inherit_manual_not_layer_a(self):
        # Phiếu 1: DT + dòng nhập tay
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 500_000, 'DT')
        e1 = self._make_entry(run_kqkd=True, run_manual=True)
        e1.action_fetch_data()
        c02 = e1.line_ids.filtered(lambda l: l.template_code == 'C02')
        c02.amount = 7_000.0
        layer_a_count = len(e1.line_ids.filtered(lambda l: not l.is_manual))
        self.assertTrue(layer_a_count)
        e1.action_post()
        e1.action_reverse_entry()
        self.assertEqual(e1.state, 'cancelled')

        e2 = self._make_entry(run_kqkd=True, run_manual=True)
        inherited = e2.line_ids.filtered('is_inherited')
        self.assertTrue(inherited)
        self.assertTrue(all(l.is_manual for l in inherited))
        self.assertTrue(any(
            l.template_code == 'C02' and float_compare(l.amount, 7_000.0, 2) == 0
            for l in inherited
        ))
        # Chưa fetch: không có dòng lớp A máy
        self.assertFalse(e2.line_ids.filtered(lambda l: not l.is_manual))
        e2.action_fetch_data()
        # Sau fetch: có lớp A tính lại + vẫn giữ C02 7000
        self.assertTrue(e2.line_ids.filtered(lambda l: not l.is_manual))
        c02b = e2.line_ids.filtered(lambda l: l.template_code == 'C02')
        self.assertEqual(float_compare(c02b.amount, 7_000.0, precision_digits=2), 0)

    def test_05_cit_provisional(self):
        entry = self._make_entry(
            run_cit=True, cit_amount=30_000.0, cit_nature='provisional',
        )
        entry.action_fetch_data()
        line = entry.line_ids.filtered(lambda l: l.layer == 'B_cit')
        self.assertEqual(len(line), 1)
        self.assertEqual(line.account_debit_id.code, '821')
        self.assertEqual(line.account_credit_id.code, '3334')
        entry.action_post()
        self.assertTrue(entry._batch_active_moves())

    def test_06_cit_final_reduce(self):
        entry = self._make_entry(
            run_cit=True, cit_amount=12_000.0, cit_nature='final_reduce',
        )
        entry.action_fetch_data()
        line = entry.line_ids.filtered(lambda l: l.layer == 'B_cit')
        self.assertEqual(line.account_debit_id.code, '3334')
        self.assertEqual(line.account_credit_id.code, '821')

    def test_07_cit_prior_material_no_line(self):
        entry = self._make_entry(
            run_cit=True, cit_amount=99_000.0, cit_nature='prior_material_note',
        )
        entry.action_fetch_data()
        self.assertFalse(entry.line_ids.filtered(lambda l: l.layer == 'B_cit'))
        self.assertTrue(entry.warning_html)
        self.assertIn('trọng yếu', entry.warning_html.lower())

    def test_08_cit_mid_year_no_821_to_911(self):
        entry = self._make_entry(
            run_cit=True, run_kqkd=True,
            cit_amount=20_000.0, cit_nature='provisional',
        )
        self.assertFalse(entry.is_year_end)
        # Có PS để lớp A có dòng
        self._post_pair('2090-06-10', self._acc('111'), self._acc('511'), 100_000, 'DT')
        entry.action_fetch_data()
        self.assertTrue(entry.line_ids.filtered(lambda l: l.layer == 'B_cit'))
        self.assertFalse(any(
            '821' in (l.account_debit_id.code, l.account_credit_id.code)
            and '911' in (l.account_debit_id.code, l.account_credit_id.code)
            for l in entry.line_ids
        ))
