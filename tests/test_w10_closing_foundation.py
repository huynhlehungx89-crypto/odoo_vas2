# -*- coding: utf-8 -*-
"""W10 chặng 1 — nền dữ liệu: ending_balance_policy, vas.closing.rule, hàm số dư."""
from odoo.exceptions import UserError
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


TT200_FORBIDDEN = (
    '521', '5211', '5212', '5213',
    '621', '622', '623', '627',
    '641', '642',  # 642 cha có trong TT133 — chỉ cấm nếu rule dùng như TT200 không chi tiết?
    '8211', '8212', '4131',
)
# 642 cấp 1 tồn tại trên TT133 (cha của 6421/6422). Cấm trong RULE là mã TT200
# dùng như đích KC thay 6421/6422 — seed không được có account_from/to = 642 đơn.
TT200_FORBIDDEN_AS_RULE_ACCOUNT = (
    '521', '5211', '5212', '5213',
    '621', '622', '623', '627',
    '641', '8211', '8212', '4131',
)


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_w10')
class TestW10ClosingFoundation(TransactionCase):

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

        cls.Account = cls.env['vas.account']
        cls.ClosingRule = cls.env['vas.closing.rule']

        # Kỳ + journal để post bút toán thử số dư
        fy = cls.env['vas.fiscalyear'].search([
            ('company_id', '=', cls.company.id),
            ('date_from', '<=', '2090-06-30'),
            ('date_to', '>=', '2090-06-01'),
        ], limit=1)
        if not fy:
            fy = cls.env['vas.fiscalyear'].create({
                'name': 'W10-2090',
                'date_from': '2090-01-01',
                'date_to': '2090-12-31',
                'state': 'open',
                'company_id': cls.company.id,
            })
        period = cls.env['vas.period'].search([
            ('fiscalyear_id', '=', fy.id),
            ('date_start', '<=', '2090-06-15'),
            ('date_end', '>=', '2090-06-15'),
        ], limit=1)
        if not period:
            period = cls.env['vas.period'].create({
                'name': '06/2090',
                'date_start': '2090-06-01',
                'date_end': '2090-06-30',
                'fiscalyear_id': fy.id,
                'state': 'open',
            })
        cls.period = period

        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id),
            ('code', '=', 'KC'),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['vas.journal'].search([
                ('company_id', '=', cls.company.id),
            ], limit=1)

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    # ----- V1 policy seed -----

    def test_01_ending_balance_policy_seed_key_accounts(self):
        self.assertEqual(self._acc('511').ending_balance_policy, 'none')
        self.assertEqual(self._acc('911').ending_balance_policy, 'none')
        self.assertEqual(self._acc('413').ending_balance_policy, 'none')
        self.assertEqual(self._acc('111').ending_balance_policy, 'debit')
        for code in ('421', '4211', '4212'):
            self.assertEqual(
                self._acc(code).ending_balance_policy, 'debit_or_credit',
                code,
            )
        # 331: «Thường dư Có; có thể dư Nợ theo từng NCC»
        self.assertEqual(self._acc('331').ending_balance_policy, 'debit_or_credit')

    def test_02_child_inherits_parent_policy(self):
        parent = self._acc('511')
        child = self.Account.create({
            'code': '5119W10',
            'name': 'DT test thừa kế',
            'regime_id': self.regime.id,
            'account_type': 'income',
            'parent_id': parent.id,
        })
        self.assertEqual(child.ending_balance_policy, parent.ending_balance_policy)
        self.assertEqual(child.ending_balance_policy, 'none')

    def test_03_root_without_policy_blocked(self):
        with self.assertRaises(UserError) as err:
            self.Account.create({
                'code': '9999W10',
                'name': 'TK gốc thiếu policy',
                'regime_id': self.regime.id,
                'account_type': 'asset',
            })
        self.assertIn('tính chất số dư', err.exception.args[0].lower())

    def test_04_no_empty_policy_on_tt133_chart(self):
        empty = self.Account.search([
            ('regime_id', '=', self.regime.id),
            ('ending_balance_policy', '=', False),
        ])
        self.assertFalse(
            empty,
            'TK TT133 còn trống ending_balance_policy: %s' % empty.mapped('code'),
        )

    # ----- V2 closing.rule -----

    def test_05_system_rule_blocks_account_change_via_write(self):
        rule = self.ClosingRule.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '511-911'),
            ('is_system', '=', True),
        ], limit=1)
        self.assertTrue(rule)
        other = self._acc('515')
        with self.assertRaises(UserError) as err:
            rule.write({'account_from_id': other.id})
        self.assertIn('hệ thống', err.exception.args[0].lower())

    def test_05b_seed_blocks_clear_is_system_then_account(self):
        """K4: không lách bằng hạ is_system rồi đổi account (nhận diện xml_id)."""
        rule = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        self.assertTrue(rule._xml_seed_rules())
        with self.assertRaises(UserError) as err1:
            rule.write({'is_system': False})
        self.assertIn('nhãn hệ thống', err1.exception.args[0].lower())
        self.assertTrue(rule.is_system)
        # Giả lập nhãn đã hạ (SQL) — write account vẫn bị chặn vì seed XML
        self.env.cr.execute(
            'UPDATE vas_closing_rule SET is_system = FALSE WHERE id = %s',
            [rule.id],
        )
        rule.invalidate_recordset(['is_system'])
        self.assertFalse(rule.is_system)
        other = self._acc('515')
        with self.assertRaises(UserError) as err2:
            rule.write({'account_from_id': other.id})
        self.assertIn('cấu trúc', err2.exception.args[0].lower())
        self.env.cr.execute(
            'UPDATE vas_closing_rule SET is_system = TRUE WHERE id = %s',
            [rule.id],
        )
        rule.invalidate_recordset(['is_system'])

    def test_05c_seed_blocks_unlink(self):
        """K8: không xóa được rule seed (cùng nhận diện xml_id như K4)."""
        rule = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        self.assertTrue(rule._xml_seed_rules())
        with self.assertRaises(UserError) as err:
            rule.unlink()
        self.assertIn('Không được xóa', err.exception.args[0])
        self.assertTrue(rule.exists())

    def test_05d_seed_blocks_structural_fields(self):
        """K9: chặn regime/company/layer/close_side/timing/code trên seed."""
        rule = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        fake = self.env['vas.regime'].create({'code': 'K9Z', 'name': 'K9 fake'})
        for vals in (
            {'regime_id': fake.id},
            {'company_id': self.company.id},
            {'rule_layer': 'B_cit'},
            {'close_side': 'debit'},
            {'timing': 'year_start'},
            {'code': 'HACKED'},
        ):
            with self.assertRaises(UserError) as err:
                rule.write(vals)
            self.assertIn('cấu trúc', err.exception.args[0].lower(), vals)

    def test_05e_seed_allows_active_sequence_name(self):
        """K9: cố ý cho bật/tắt + thứ tự + diễn giải."""
        rule = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        old = rule.name
        rule.write({'active': False, 'sequence': 11, 'name': old + ' x'})
        self.assertFalse(rule.active)
        rule.write({'active': True, 'sequence': 10, 'name': old})

    def test_05f_copy_is_user_rule_editable(self):
        """K9: copy seed → is_system=False, active=False; được sửa (thêm rule phụ)."""
        rule = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        copy = rule.copy()
        self.assertFalse(copy.is_system)
        self.assertFalse(copy.active)
        self.assertFalse(copy._xml_seed_rules())
        # TK không có seed rule — đổi nguồn rồi bật được
        other = self.env['vas.account'].create({
            'code': '5188',
            'name': 'DT phụ K9',
            'regime_id': self.regime.id,
            'account_type': 'income',
            'ending_balance_policy': 'none',
            'parent_id': self._acc('511').id,
        })
        copy.write({'account_from_id': other.id, 'active': True})
        self.assertEqual(copy.account_from_id, other)
        self.assertEqual(rule.account_from_id.code, '511')
        copy.write({'active': False})

    def test_05h_duplicate_account_from_blocked(self):
        """K10: bật bản sao cùng TK nguồn → chặn; đổi nguồn khác thì được."""
        from odoo.exceptions import ValidationError
        seed = self.env.ref('connecta_vas.vas_closing_rule_tt133_511_911')
        copy = seed.copy({'code': 'K10-DUP-511'})
        self.assertFalse(copy.active)
        with self.assertRaises(ValidationError) as err:
            copy.write({'active': True})
        self.assertIn('511', err.exception.args[0])
        self.assertIn(seed.code, err.exception.args[0])
        # Đổi nguồn sang TK không có rule → được bật (không gộp con)
        other = self.env['vas.account'].create({
            'code': '5187',
            'name': 'DT phụ K10',
            'regime_id': self.regime.id,
            'account_type': 'income',
            'ending_balance_policy': 'none',
            'parent_id': self._acc('511').id,
        })
        copy.write({
            'account_from_id': other.id,
            'active': True,
        })
        self.assertTrue(copy.active)
        copy.write({'active': False})

    def test_05i_complementary_debit_credit_allowed(self):
        """K10: cặp Nợ/Có bổ sung cùng TK nguồn (821/911…) vẫn cho cùng active."""
        debit = self.ClosingRule.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '821-911-debit'),
            ('active', '=', True),
        ], limit=1)
        credit = self.ClosingRule.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '821-911-credit'),
            ('active', '=', True),
        ], limit=1)
        self.assertTrue(debit and credit)
        self.assertEqual(debit.account_from_id, credit.account_from_id)
        # Ghi lại active không lỗi
        credit.write({'active': True})
        debit.write({'active': True})

    def test_05g_unlink_account_used_by_seed_blocked(self):
        """K9: xóa gián tiếp TK đang được rule trỏ — FK restrict."""
        acc = self._acc('515')
        with self.assertRaises(Exception):
            acc.unlink()
        self.assertTrue(acc.exists())

    def test_06_system_rule_allows_active_and_name(self):
        rule = self.ClosingRule.search([
            ('regime_id', '=', self.regime.id),
            ('code', '=', '511-911'),
        ], limit=1)
        old_name = rule.name
        rule.write({'active': False, 'name': old_name + ' (tắt thử)'})
        self.assertFalse(rule.active)
        rule.write({'active': True, 'name': old_name})
        self.assertTrue(rule.active)
        self.assertEqual(rule.name, old_name)

    def test_07_seed_has_no_tt200_codes(self):
        rules = self.ClosingRule.with_context(active_test=False).search([
            ('regime_id', '=', self.regime.id),
        ])
        self.assertTrue(rules)
        banned_hit = []
        for rule in rules:
            for acc in (rule.account_from_id | rule.account_to_id):
                if acc.code in TT200_FORBIDDEN_AS_RULE_ACCOUNT:
                    banned_hit.append('%s:%s' % (rule.code, acc.code))
            for bad in TT200_FORBIDDEN_AS_RULE_ACCOUNT:
                if rule.code == bad or rule.code.startswith(bad + '-'):
                    banned_hit.append('code=%s' % rule.code)
        self.assertFalse(banned_hit, banned_hit)

        # 16 lớp A gốc + 4 rule lá 511x (P4)
        layer_a = rules.filtered(lambda r: r.rule_layer == 'A_close')
        self.assertEqual(len(layer_a), 20)
        for leaf_code in ('5111-911', '5112-911', '5113-911', '5118-911'):
            self.assertTrue(layer_a.filtered(lambda r: r.code == leaf_code), leaf_code)

        # KKĐK inactive
        inactive_kk = rules.filtered(
            lambda r: r.group_code == 'costing' and r.rule_layer == 'B_costing'
        )
        self.assertTrue(inactive_kk)
        self.assertTrue(all(not r.active for r in inactive_kk))

        # L06/V09/CIT không gắn from/to
        for code in ('L06', 'V09', 'CIT'):
            rule = rules.filtered(lambda r: r.code == code)
            self.assertEqual(len(rule), 1, code)
            self.assertFalse(rule.account_from_id)
            self.assertFalse(rule.account_to_id)

    # ----- V3 balance function -----

    def _post_pair(self, date, debit_acc, credit_acc, amount, name='W10 bal'):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'move_kind': 'manual',
            'company_id': self.company.id,
            'ref': name,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_acc.id,
                    'name': name,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': credit_acc.id,
                    'name': name,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def test_08_balance_both_net_revenue(self):
        """511 hỗn hợp: both = DT thuần; from_side=debit = CHIỀU GHI KC (Nợ 511 xả dư Có)."""
        acc_511 = self._acc('511')
        acc_111 = self._acc('111')
        # Doanh thu 1.000.000 (Có 511)
        self._post_pair('2090-06-10', acc_111, acc_511, 1_000_000.0, 'DT')
        # Giảm trừ 100.000 (Nợ 511)
        self._post_pair('2090-06-12', acc_511, acc_111, 100_000.0, 'Giam tru')

        amount, side = self.ClosingRule.compute_closing_amount(
            acc_511, self.company, '2090-06-01', '2090-06-30', 'both',
        )
        # Net = 100k − 1000k = −900k → dư Có 900k → from_side debit = ghi Nợ 511 trên JE KC
        self.assertEqual(side, 'debit')
        self.assertEqual(float_compare(amount, 900_000.0, precision_digits=2), 0)

    def test_09_balance_single_side(self):
        acc_632 = self._acc('632')
        acc_156 = self._acc('156')
        self._post_pair('2090-06-20', acc_632, acc_156, 50_000.0, 'GV')

        amount, side = self.ClosingRule.compute_closing_amount(
            acc_632, self.company, '2090-06-01', '2090-06-30', 'both',
        )
        self.assertEqual(side, 'credit')  # dư Nợ → ghi Có
        self.assertEqual(float_compare(amount, 50_000.0, precision_digits=2), 0)

        # close_side=credit khi đang dư Nợ → 0
        amount2, side2 = self.ClosingRule.compute_closing_amount(
            acc_632, self.company, '2090-06-01', '2090-06-30', 'credit',
        )
        self.assertFalse(side2)
        self.assertEqual(amount2, 0.0)

        amount3, side3 = self.ClosingRule.compute_closing_amount(
            acc_632, self.company, '2090-06-01', '2090-06-30', 'debit',
        )
        self.assertEqual(side3, 'credit')
        self.assertEqual(float_compare(amount3, 50_000.0, precision_digits=2), 0)
