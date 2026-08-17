# -*- coding: utf-8 -*-
"""W10 P4 — seed rule lá 511x + P3 lưới an toàn TK không rule phủ."""
from odoo.exceptions import ValidationError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10LeafRulesAndUncovered(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        if not cls.company.vas_regime_id:
            cls.company.vas_regime_id = cls.regime
        cls.company.vas_start_date = '2096-01-01'
        cls.company.fiscalyear_last_day = 31
        cls.company.fiscalyear_last_month = '12'
        vnd = cls.env.ref('base.VND')
        if cls.company.currency_id != vnd:
            cls.company.currency_id = vnd

        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '=', '2096-01-01'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W10L-2096',
                'date_from': '2096-01-01',
                'date_to': '2096-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        cls.fy = fy
        period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '=', '2096-06-01'),
        ], limit=1)
        if not period:
            period = cls.env['vas.period'].create({
                'name': '06/2096',
                'date_start': '2096-06-01',
                'date_end': '2096-06-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        cls.period = period
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'KC'),
        ], limit=1) or cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        cls.Entry = cls.env['vas.closing.entry']
        cls.Rule = cls.env['vas.closing.rule']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post_pair(self, day, debit_acc, credit_acc, amount, name='W10L'):
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

    def _ending(self, code):
        amount, side = self.Rule.compute_closing_amount(
            self._acc(code), self.company, '2096-01-01', '2096-06-30', 'both',
        )
        if not side:
            return 0.0
        return amount if side == 'debit' else -amount

    def _make_entry(self, **kwargs):
        vals = {
            'company_id': self.company.id,
            'date_from': '2096-01-01',
            'date_to': '2096-06-30',
            'run_kqkd': True,
        }
        vals.update(kwargs)
        return self.Entry.create(vals)

    def test_01_leaf_rules_seeded(self):
        for code in ('5111-911', '5112-911', '5113-911', '5118-911', '511-911'):
            rule = self.Rule.search([
                ('regime_id', '=', self.regime.id),
                ('code', '=', code),
                ('active', '=', True),
            ], limit=1)
            self.assertTrue(rule, code)
            self.assertFalse(self.Rule._aggregate_children_of_from())

    def test_02_revenue_5111_closes_to_zero(self):
        self._post_pair('2096-06-10', self._acc('111'), self._acc('5111'), 400_000, 'DT5111')
        entry = self._make_entry()
        entry.action_fetch_data()
        hit = entry.line_ids.filtered(
            lambda l: l.account_debit_id.code == '5111' and l.account_credit_id.code == '911'
        )
        self.assertEqual(len(hit), 1)
        self.assertEqual(float_compare(hit.amount, 400_000.0, 2), 0)
        entry.action_post()
        self.assertTrue(float_is_zero(self._ending('5111'), precision_digits=2))

    def test_03_revenue_5111_5112_5113_all_close(self):
        self._post_pair('2096-06-10', self._acc('111'), self._acc('5111'), 100_000, 'A')
        self._post_pair('2096-06-11', self._acc('111'), self._acc('5112'), 200_000, 'B')
        self._post_pair('2096-06-12', self._acc('111'), self._acc('5113'), 300_000, 'C')
        entry = self._make_entry()
        entry.action_fetch_data()
        for code, amt in (('5111', 100_000), ('5112', 200_000), ('5113', 300_000)):
            hit = entry.line_ids.filtered(
                lambda l, c=code: l.account_debit_id.code == c and l.account_credit_id.code == '911'
            )
            self.assertEqual(len(hit), 1, code)
            self.assertEqual(float_compare(hit.amount, amt, 2), 0, code)
        entry.action_post()
        for code in ('5111', '5112', '5113'):
            self.assertTrue(
                float_is_zero(self._ending(code), precision_digits=2), code,
            )

    def test_04_parent_511_and_leaf_5111_no_double(self):
        """Ghi thẳng 511 + Có 5111 — mỗi cái một dòng, không xả đôi."""
        self._post_pair('2096-06-10', self._acc('111'), self._acc('511'), 500_000, 'CHA')
        self._post_pair('2096-06-11', self._acc('111'), self._acc('5111'), 200_000, 'LA')
        entry = self._make_entry()
        entry.action_fetch_data()
        line_511 = entry.line_ids.filtered(
            lambda l: l.account_debit_id.code == '511' and l.account_credit_id.code == '911'
        )
        line_5111 = entry.line_ids.filtered(
            lambda l: l.account_debit_id.code == '5111' and l.account_credit_id.code == '911'
        )
        self.assertEqual(len(line_511), 1)
        self.assertEqual(len(line_5111), 1)
        self.assertEqual(float_compare(line_511.amount, 500_000.0, 2), 0)
        self.assertEqual(float_compare(line_5111.amount, 200_000.0, 2), 0)
        entry.action_post()
        self.assertTrue(float_is_zero(self._ending('511'), precision_digits=2))
        self.assertTrue(float_is_zero(self._ending('5111'), precision_digits=2))

    def test_05_6421_6422_still_ok(self):
        self._post_pair('2096-06-10', self._acc('6421'), self._acc('111'), 80_000, 'BH')
        self._post_pair('2096-06-11', self._acc('6422'), self._acc('111'), 120_000, 'QL')
        entry = self._make_entry()
        entry.action_fetch_data()
        self.assertTrue(any(
            l.account_debit_id.code == '911' and l.account_credit_id.code == '6421'
            for l in entry.line_ids
        ))
        self.assertTrue(any(
            l.account_debit_id.code == '911' and l.account_credit_id.code == '6422'
            for l in entry.line_ids
        ))
        entry.action_post()
        self.assertTrue(float_is_zero(self._ending('6421'), precision_digits=2))
        self.assertTrue(float_is_zero(self._ending('6422'), precision_digits=2))

    def test_06_uncovered_pl_warns(self):
        """TK P&L mới không rule → cảnh báo trên phiếu, không im lặng."""
        orphan = self.env['vas.account'].create({
            'code': '5199',
            'name': 'DT orphan W10L',
            'regime_id': self.regime.id,
            'account_type': 'income',
            'ending_balance_policy': 'none',
            'parent_id': self._acc('511').id,
        })
        self._post_pair('2096-06-10', self._acc('111'), orphan, 77_000, 'ORPH')
        entry = self._make_entry()
        entry.action_fetch_data()
        uncovered = entry._find_uncovered_pl_none_balances()
        codes = [a.code for a, _amt, _s in uncovered]
        self.assertIn('5199', codes)
        self.assertIn('5199', entry.warning_html or '')
        self.assertIn('quy tắc', (entry.warning_html or '').lower())
        # Có số dư nhưng không có dòng KC cho 5199
        self.assertFalse(entry.line_ids.filtered(
            lambda l: orphan in (l.account_debit_id, l.account_credit_id)
        ))

    def test_07_parent_child_gate_ready_for_aggregate_mode(self):
        """Không gộp → 511+5111 OK; bật cờ gộp → _parent_child_close_conflicts True."""
        parent = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        leaf = self.env.ref('connecta_vas.vas_closing_rule_tt133_5111_911')
        self.assertTrue(parent.active and leaf.active)
        self.assertFalse(self.Rule._aggregate_children_of_from())
        self.assertFalse(parent._parent_child_close_conflicts(leaf))
        Model = self.env['vas.closing.rule'].__class__
        old = Model._AGGREGATE_CHILDREN_OF_FROM
        try:
            Model._AGGREGATE_CHILDREN_OF_FROM = True
            self.assertTrue(self.Rule._aggregate_children_of_from())
            self.assertTrue(parent._parent_child_close_conflicts(leaf))
            with self.assertRaises(ValidationError):
                (parent | leaf)._check_no_duplicate_account_from()
        finally:
            Model._AGGREGATE_CHILDREN_OF_FROM = old
