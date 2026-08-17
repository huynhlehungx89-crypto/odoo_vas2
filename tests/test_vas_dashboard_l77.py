# -*- coding: utf-8 -*-
"""Dashboard l77 — số khớp F01 cùng kỳ; menu Tổng quan."""
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_l77')
class TestVasDashboardL77(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        cls.company = cls.env['res.company'].create({
            'name': 'L77 Dash Co',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2097-01-01',
        })
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'L77-2097',
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
        cls.env['vas.journal']._ensure_journals_for_company(cls.company)
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        cls.partner = cls.env['res.partner'].create({
            'name': 'L77 Partner',
            'company_id': cls.company.id,
        })

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post(self, date, lines, ref='L77'):
        move = self.env['vas.move'].create({
            'date': date,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': ref,
            'move_kind': 'manual',
            'line_ids': [(0, 0, {
                'account_id': acc.id,
                'name': name,
                'debit': deb,
                'credit': cre,
                'partner_id': partner.id if partner else False,
            }) for acc, name, deb, cre, partner in lines],
        })
        move.action_post()
        return move

    def test_l77_menu_five_top_level_dashboard_direct(self):
        root = self.env.ref('connecta_vas.menu_connecta_vas_root')
        dash = self.env.ref('connecta_vas.menu_vas_dashboard')
        self.assertEqual(dash.parent_id, root)
        self.assertFalse(dash.child_id)
        self.assertEqual(
            dash.action,
            self.env.ref('connecta_vas.action_vas_dashboard'),
        )
        act = self.env.ref('connecta_vas.action_vas_dashboard')
        self.assertEqual(act.tag, 'vas_dashboard')

    def test_l77_dashboard_matches_f01_same_period(self):
        # Cân bằng: Nợ 1111 5tr + 1121 3tr + 131 2tr + 156 4tr + 642 1.5tr = 15.5tr
        # Có 331 1.5tr + 511 8tr + 411 6tr = 15.5tr
        self._post('2097-02-10', [
            (self._acc('1111'), 'cash', 5_000_000, 0, False),
            (self._acc('1121'), 'bank', 3_000_000, 0, False),
            (self._acc('131'), 'ar', 2_000_000, 0, self.partner),
            (self._acc('156'), 'inv', 4_000_000, 0, False),
            (self._acc('6422'), 'exp', 1_500_000, 0, False),
            (self._acc('331'), 'ap', 0, 1_500_000, self.partner),
            (self._acc('511'), 'rev', 0, 8_000_000, False),
            (self._acc('4111'), 'cap', 0, 6_000_000, False),
        ])
        # Kỳ có số liệu gần nhất phải là Feb (Jan trống)
        opts = self.env['vas.dashboard'].get_period_options()
        self.assertEqual(opts['default_period_id'], self.period_feb.id)

        cmp_rows = self.env['vas.dashboard'].get_f01_compare_amounts(
            self.period_feb.id,
        )
        for row in cmp_rows['rows']:
            self.assertEqual(
                float_compare(row['dashboard'], row['f01'], 2), 0,
                'Lệch %s: dashboard=%s f01=%s' % (
                    row['label'], row['dashboard'], row['f01'],
                ),
            )
            self.assertNotEqual(
                float_compare(row['dashboard'], 0.0, 2), 0,
                'Kỳ seed phải có số cho %s' % row['label'],
            )

        data = self.env['vas.dashboard'].get_dashboard_data(self.period_feb.id)
        self.assertFalse(data.get('error'))
        self.assertFalse(data['tiles']['finance']['empty'])
        self.assertFalse(data['tiles']['ar']['empty'])
        self.assertFalse(data['tiles']['ap']['empty'])
        # L79: tuổi nợ 6 cột — manual không có due → cột unknown, không đoán hạn
        self.assertTrue(data['tiles']['ar']['aging_available'])
        self.assertTrue(data['tiles']['ap']['aging_available'])
        self.assertEqual(
            float_compare(data['tiles']['ar']['aging']['buckets']['unknown'], 2_000_000, 2), 0,
        )
        self.assertEqual(
            float_compare(data['tiles']['ap']['aging']['buckets']['unknown'], 1_500_000, 2), 0,
        )
        for k in ('not_due', 'd1_30', 'd31_60', 'd61_90', 'd90_plus'):
            self.assertEqual(
                float_compare(data['tiles']['ar']['aging']['buckets'][k], 0.0, 2), 0, k,
            )
            self.assertEqual(
                float_compare(data['tiles']['ap']['aging']['buckets'][k], 0.0, 2), 0, k,
            )
        todos = data['tiles']['todos']
        self.assertFalse(todos['empty'])
        by_key = {i['key']: i for i in todos['items']}
        self.assertFalse(by_key['lock']['done'])
        self.assertFalse(by_key['closing']['done'])
        self.assertFalse(by_key['fs']['done'])

        # Đổi kỳ → Jan trống / hoặc không có số BS
        data_jan = self.env['vas.dashboard'].get_dashboard_data(self.period_jan.id)
        self.assertTrue(data_jan['tiles']['finance']['empty'])

        # Phản ánh khóa sổ: ghi state trực tiếp (ca này chỉ kiểm dashboard ĐỌC state,
        # không chạy quy trình đóng kỳ đầy đủ — kỳ đang còn số DT/CP mở).
        self.env.cr.execute(
            "UPDATE vas_period SET state = 'closed' WHERE id = %s",
            (self.period_feb.id,),
        )
        self.period_feb.invalidate_recordset(['state'])
        data2 = self.env['vas.dashboard'].get_dashboard_data(self.period_feb.id)
        by_key2 = {i['key']: i for i in data2['tiles']['todos']['items']}
        self.assertTrue(by_key2['lock']['done'])

        act = self.env['vas.dashboard'].action_open_general_workflow()
        self.assertEqual(act.get('tag'), 'vas_ops_workflow')
        self.assertEqual(
            (act.get('context') or {}).get('vas_ops_group_code'), 'general',
        )

    def test_l77_root_menus_named_five(self):
        root = self.env.ref('connecta_vas.menu_connecta_vas_root')
        top = self.env['ir.ui.menu'].search([
            ('parent_id', '=', root.id),
            ('name', 'in', [
                'Tổng quan',
                'Nghiệp vụ',
                'Sổ & Báo cáo',
                'Danh mục & Số dư đầu kỳ',
                'Cấu hình',
            ]),
        ])
        self.assertEqual(len(top), 5)
