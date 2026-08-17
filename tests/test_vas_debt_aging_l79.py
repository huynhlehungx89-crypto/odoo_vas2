# -*- coding: utf-8 -*-
"""L79 — tuổi nợ Công nợ phương án B (6 cột, cột cuối = chưa xác định hạn)."""
from datetime import date

from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.tools.float_utils import float_compare, float_is_zero

from odoo.addons.connecta_vas.models.vas_debt_aging import AGING_BUCKET_KEYS


@tagged('post_install', '-at_install', 'connecta_vas', 'connecta_vas_l79')
class TestVasDebtAgingL79(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regime = cls.env.ref('connecta_vas.vas_regime_tt133')
        vnd = cls.env.ref('base.VND')
        cls.company = cls.env['res.company'].create({
            'name': 'L79 Aging Co',
            'currency_id': vnd.id,
            'vas_regime_id': cls.regime.id,
            'vas_start_date': '2098-01-01',
        })
        cls.env.user.company_ids = [(4, cls.company.id)]
        cls.env.user.company_id = cls.company
        cls.fy = cls.env['vas.fiscalyear'].create({
            'name': 'L79-2098',
            'date_from': '2098-01-01',
            'date_to': '2098-12-31',
            'state': 'open',
            'company_id': cls.company.id,
        })
        cls.period = cls.env['vas.period'].create({
            'name': '03/2098',
            'date_start': '2098-03-01',
            'date_end': '2098-03-31',
            'fiscalyear_id': cls.fy.id,
            'state': 'open',
        })
        cls.env['vas.journal']._ensure_journals_for_company(cls.company)
        cls.journal = cls.env['vas.journal'].search([
            ('company_id', '=', cls.company.id), ('code', '=', 'TH'),
        ], limit=1)
        cls.partner_a = cls.env['res.partner'].create({
            'name': 'L79 KH A',
            'company_id': cls.company.id,
        })
        cls.partner_b = cls.env['res.partner'].create({
            'name': 'L79 KH B',
            'company_id': cls.company.id,
        })
        cls.Aging = cls.env['vas.debt.aging']

    def _acc(self, code):
        return self.env.ref('connecta_vas.vas_account_tt133_%s' % code)

    def _post(self, date_str, lines, ref='L79', **move_extra):
        move = self.env['vas.move'].create({
            'date': date_str,
            'journal_id': self.journal.id,
            'regime_id': self.regime.id,
            'company_id': self.company.id,
            'ref': ref,
            'move_kind': move_extra.pop('move_kind', 'manual'),
            'line_ids': [(0, 0, {
                'account_id': acc.id,
                'name': name,
                'debit': deb,
                'credit': cre,
                'partner_id': partner.id if partner else False,
            }) for acc, name, deb, cre, partner in lines],
            **move_extra,
        })
        move.action_post()
        return move

    def _stub_invoice(self, due_date, partner=None):
        """Tạo account.move tối thiểu chỉ để đọc invoice_date_due — không sync.

        Dùng công ty chính (đã có COA/journal); aging chỉ đọc field hạn theo id.
        """
        main = self.env.ref('base.main_company')
        journal = self.env['account.journal'].search([
            ('company_id', '=', main.id),
            ('type', 'in', ('general', 'sale')),
        ], limit=1)
        self.assertTrue(journal, 'Thiếu journal Odoo trên main company')
        am = self.env['account.move'].with_company(main).create({
            'move_type': 'entry',
            'date': '2098-01-01',
            'journal_id': journal.id,
            'company_id': main.id,
            'ref': 'L79-due-stub',
        })
        # Field stored + compute: write sau create để không bị mặc định = hôm nay.
        due = fields.Date.to_date(due_date)
        am.write({'invoice_date_due': due})
        self.assertEqual(am.invoice_date_due, due)
        return am

    def test_l79_six_columns_meta_and_ops_hub(self):
        cols = self.Aging._aging_bucket_meta()
        self.assertEqual([c['key'] for c in cols], list(AGING_BUCKET_KEYS))
        self.assertEqual(cols[-1]['key'], 'unknown')
        self.assertTrue(cols[-1].get('hint'))

        group = self.env.ref('connecta_vas.vas_ops_group_ar_ap')
        self.assertEqual(group.state, 'ready')
        self.assertEqual(group.screen_kind, 'hub')
        labels = set(group.button_ids.mapped('label'))
        self.assertIn('Tuổi nợ phải thu', labels)
        self.assertIn('Tuổi nợ phải trả', labels)
        self.assertIn('Bù trừ công nợ', labels)

        act = self.env.ref('connecta_vas.action_vas_debt_aging_ar')
        self.assertEqual(act.tag, 'vas_debt_aging')
        ctx = act.context or {}
        if isinstance(ctx, str):
            from odoo.tools.safe_eval import safe_eval
            ctx = safe_eval(ctx)
        self.assertEqual(ctx.get('vas_aging_kind'), 'ar')

    def test_l79_unknown_for_non_invoice_sources_match_f01(self):
        """Manual / payment / opening / revenue / offset → unknown; Σ = F01."""
        # Cân: 131 3tr + 1111 1tr = 331 1tr + 411 3tr
        self._post('2098-03-10', [
            (self._acc('131'), 'ar-manual', 1_000_000, 0, self.partner_a),
            (self._acc('1111'), 'cash', 1_000_000, 0, False),
            (self._acc('331'), 'ap', 0, 1_000_000, self.partner_b),
            (self._acc('4111'), 'cap', 0, 1_000_000, False),
        ], move_kind='manual', ref='L79-man')
        self._post('2098-03-11', [
            (self._acc('131'), 'ar-pay', 500_000, 0, self.partner_a),
            (self._acc('4111'), 'cap2', 0, 500_000, False),
        ], move_kind='payment', ref='L79-pay')
        self._post('2098-03-12', [
            (self._acc('131'), 'ar-open', 800_000, 0, self.partner_b),
            (self._acc('4111'), 'cap3', 0, 800_000, False),
        ], move_kind='opening', ref='L79-open')
        self._post('2098-03-13', [
            (self._acc('131'), 'ar-rev', 400_000, 0, self.partner_a),
            (self._acc('4111'), 'cap4', 0, 400_000, False),
        ], move_kind='revenue', ref='L79-rev')
        self._post('2098-03-14', [
            (self._acc('131'), 'ar-off', 300_000, 0, self.partner_a),
            (self._acc('4111'), 'cap5', 0, 300_000, False),
        ], move_kind='debt_offset', ref='L79-off')

        data = self.Aging.get_aging_report(self.period.id, 'ar')
        self.assertFalse(data.get('error'))
        self.assertEqual(len(data['columns']), 6)
        self.assertEqual(data['columns'][-1]['key'], 'unknown')

        # Toàn bộ vào unknown — không đoán hạn từ ngày hạch toán
        for k in ('not_due', 'd1_30', 'd31_60', 'd61_90', 'd90_plus'):
            self.assertTrue(
                float_is_zero(data['totals'][k], 2),
                '%s=%s' % (k, data['totals'][k]),
            )
        expected = 1_000_000 + 500_000 + 800_000 + 400_000 + 300_000
        self.assertEqual(
            float_compare(data['totals']['unknown'], expected, 2), 0,
            data['totals'],
        )
        self.assertEqual(
            float_compare(data['totals']['total'], expected, 2), 0,
        )
        self.assertTrue(data['match_f01'], data)
        cmp_ = self.Aging.get_aging_compare(self.period.id, 'ar')
        self.assertTrue(cmp_['ok'], cmp_)
        self.assertEqual(
            float_compare(cmp_['columns_total'], cmp_['f01_total'], 2), 0,
        )

        # Từng đối tác: Σ 6 cột = tổng dòng
        for row in data['rows']:
            col_sum = sum(row[k] for k in AGING_BUCKET_KEYS)
            self.assertEqual(
                float_compare(col_sum, row['total'], 2), 0,
                row,
            )

    def test_l79_invoice_due_buckets_as_of_period_end(self):
        """Nối account.move.invoice_date_due — mốc = date_end kỳ (31/03)."""
        # as_of = 2098-03-31
        # due 2098-04-10 → not_due (còn hạn)
        # due 2098-03-20 → d1_30 (11 ngày)
        # due 2098-02-15 → d31_60 (44 ngày)
        # due 2098-01-20 → d61_90 (70 ngày)
        # due 2097-12-01 → d90_plus (120 ngày)
        cases = [
            ('2098-04-10', 'not_due', 1_000_000, self.partner_a),
            ('2098-03-20', 'd1_30', 2_000_000, self.partner_a),
            ('2098-02-15', 'd31_60', 3_000_000, self.partner_b),
            ('2098-01-20', 'd61_90', 4_000_000, self.partner_b),
            ('2097-12-01', 'd90_plus', 5_000_000, self.partner_a),
        ]
        bal = 0.0
        for due, _bucket, amt, partner in cases:
            am = self._stub_invoice(due, partner)
            self._post('2098-03-15', [
                (self._acc('131'), 'ar-inv', amt, 0, partner),
                (self._acc('4111'), 'cap', 0, amt, False),
            ], move_kind='sale_inv', ref='L79-%s' % due,
                source_model='account.move', source_res_id=am.id)
            bal += amt

        # Manual không due → unknown
        self._post('2098-03-16', [
            (self._acc('131'), 'ar-man', 700_000, 0, self.partner_a),
            (self._acc('4111'), 'cap-m', 0, 700_000, False),
        ], move_kind='manual', ref='L79-man2')
        bal += 700_000

        data = self.Aging.get_aging_report(self.period.id, 'ar')
        self.assertEqual(data['as_of'], '2098-03-31')

        expect = {
            'not_due': 1_000_000,
            'd1_30': 2_000_000,
            'd31_60': 3_000_000,
            'd61_90': 4_000_000,
            'd90_plus': 5_000_000,
            'unknown': 700_000,
        }
        for k, v in expect.items():
            self.assertEqual(
                float_compare(data['totals'][k], v, 2), 0,
                '%s got %s want %s' % (k, data['totals'][k], v),
            )
        self.assertEqual(float_compare(data['totals']['total'], bal, 2), 0)
        self.assertTrue(data['match_f01'], data)

        # Không lẫn: unknown chỉ phần không nối due
        self.assertEqual(
            float_compare(data['totals']['unknown'], 700_000, 2), 0,
        )
        # Partner A: not_due+d1_30+d90_plus+unknown
        row_a = next(r for r in data['rows'] if r['partner_id'] == self.partner_a.id)
        self.assertEqual(
            float_compare(
                sum(row_a[k] for k in AGING_BUCKET_KEYS), row_a['total'], 2,
            ), 0,
        )
        self.assertEqual(float_compare(row_a['unknown'], 700_000, 2), 0)
        self.assertEqual(float_compare(row_a['not_due'], 1_000_000, 2), 0)

        # Không dùng "hôm nay" — nếu as_of sai (today) thì bucket lệch
        self.assertNotEqual(fields.Date.context_today(self.Aging), date(2098, 3, 31))

    def test_l79_ap_331_credit_side_and_no_guess_from_date(self):
        """331: dư Có; source payment không suy hạn từ date."""
        self._post('2098-01-05', [
            (self._acc('156'), 'inv', 2_000_000, 0, False),
            (self._acc('331'), 'ap', 0, 2_000_000, self.partner_b),
        ], move_kind='payment', ref='L79-ap')

        data = self.Aging.get_aging_report(self.period.id, 'ap')
        self.assertEqual(
            float_compare(data['totals']['unknown'], 2_000_000, 2), 0,
            data['totals'],
        )
        for k in ('not_due', 'd1_30', 'd31_60', 'd61_90', 'd90_plus'):
            self.assertTrue(float_is_zero(data['totals'][k], 2), k)
        self.assertTrue(data['match_f01'], data)
        cmp_ = self.Aging.get_aging_compare(self.period.id, 'ap')
        self.assertTrue(cmp_['ok'], cmp_)
